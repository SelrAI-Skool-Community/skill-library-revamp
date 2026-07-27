#!/usr/bin/env python3
"""Manage reviewed rewrite proposals without committing skill changes."""

from __future__ import annotations

import argparse
import difflib
import getpass
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

sys.dont_write_bytecode = True

from ledger import all_skills, atomic_write_text, load, save
from scan_frontmatter import parse_frontmatter


def add_common_args(
    parser: argparse.ArgumentParser, *, suppress_defaults: bool = False
) -> None:
    root_default: Path | str = (
        argparse.SUPPRESS
        if suppress_defaults
        else Path.home() / ".claude/skills"
    )
    run_dir_default: Path | str = (
        argparse.SUPPRESS
        if suppress_defaults
        else Path.home() / ".claude/skill-revamp-runs/current"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=root_default,
        help="top-level skills directory",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=run_dir_default,
        help="pipeline run directory",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose_parser = subparsers.add_parser("propose", help="stage a rewrite proposal")
    add_common_args(propose_parser, suppress_defaults=True)
    propose_parser.add_argument("skill")
    propose_parser.add_argument(
        "--from", dest="from_dir", type=Path, required=True, help="proposal source dir"
    )

    apply_parser = subparsers.add_parser("apply", help="apply an approved proposal")
    add_common_args(apply_parser, suppress_defaults=True)
    apply_parser.add_argument("skill")

    approve_parser = subparsers.add_parser("approve", help="approve a proposal")
    add_common_args(approve_parser, suppress_defaults=True)
    approve_parser.add_argument("skill")
    approve_parser.add_argument("--reviewer", default=getpass.getuser())

    reject_parser = subparsers.add_parser("reject", help="reject a proposal")
    add_common_args(reject_parser, suppress_defaults=True)
    reject_parser.add_argument("skill")
    reject_parser.add_argument("--reason", required=True)

    rollback_parser = subparsers.add_parser("rollback", help="roll back an apply")
    add_common_args(rollback_parser, suppress_defaults=True)
    rollback_parser.add_argument("skill")
    rollback_parser.add_argument(
        "--commit",
        help="explicit source commit for a rewrite that has already been committed",
    )

    status_parser = subparsers.add_parser(
        "status", help="show T2/T3 rewrite and review state"
    )
    add_common_args(status_parser, suppress_defaults=True)
    return parser.parse_args()


def validate_skill_name(skill: str) -> str:
    name = Path(skill).name
    if (
        not name
        or name != skill
        or name.startswith((".", "_"))
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name)
    ):
        raise ValueError(f"invalid skill name: {skill!r}")
    return name


def live_skill_dir(obj: dict[str, Any], root: Path) -> Path:
    skill = obj["skill"]
    raw_path = obj.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"{skill}.path must be a non-empty string")
    live = Path(raw_path).expanduser().absolute()
    resolved_root = root.expanduser().resolve()
    resolved_live = live.resolve()
    try:
        resolved_live.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"ledger path for {skill} is outside skills root: {live}"
        ) from exc
    if live.name != skill:
        raise ValueError(f"ledger path dirname mismatch for {skill}: {live.name!r}")
    if not live.is_dir():
        raise NotADirectoryError(f"live skill directory not found: {live}")
    if not (live / "SKILL.md").is_file():
        raise FileNotFoundError(f"live SKILL.md not found: {live / 'SKILL.md'}")
    return live


def proposal_dir(run_dir: Path, skill: str) -> Path:
    return run_dir.expanduser().absolute() / "proposals" / skill


def safe_relative(path: Path, base: Path) -> PurePosixPath:
    relative = PurePosixPath(path.relative_to(base).as_posix())
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"unsafe proposal path: {path}")
    return relative


def proposal_payload(source: Path) -> dict[PurePosixPath, tuple[bytes, int]]:
    source = source.expanduser().absolute()
    if not source.is_dir():
        raise NotADirectoryError(f"proposal source directory not found: {source}")
    if source.is_symlink():
        raise ValueError(f"proposal source may not be a symlink: {source}")

    payload: dict[PurePosixPath, tuple[bytes, int]] = {}
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError(f"proposal may not contain symlinks: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"proposal contains a non-file entry: {path}")
        relative = safe_relative(path, source)
        payload[relative] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
    skill_md = PurePosixPath("SKILL.md")
    if skill_md not in payload:
        raise FileNotFoundError(f"proposal source must contain SKILL.md: {source}")
    return payload


def atomic_write_bytes(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def materialize_proposal(
    destination: Path, payload: dict[PurePosixPath, tuple[bytes, int]]
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    try:
        for relative, (data, mode) in payload.items():
            atomic_write_bytes(temp.joinpath(*relative.parts), data, mode)
        if destination.exists():
            if not destination.is_dir() or destination.is_symlink():
                raise ValueError(
                    f"proposal destination is not a safe directory: {destination}"
                )
            shutil.rmtree(destination)
        os.replace(temp, destination)
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def decode_text(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"proposal file is not UTF-8 text: {label}") from exc


def unified_proposal_diff(
    live: Path, payload: dict[PurePosixPath, tuple[bytes, int]]
) -> tuple[str, list[str]]:
    sections: list[str] = []
    changed: list[str] = []
    for relative, (new_data, _mode) in payload.items():
        current = live.joinpath(*relative.parts)
        current_is_file = current.is_file()
        old_data = current.read_bytes() if current_is_file else b""
        if current.exists() and not current.is_file():
            raise ValueError(f"proposal would overwrite a non-file: {current}")
        if current_is_file and old_data == new_data:
            continue
        old_text = decode_text(old_data, str(current))
        new_text = decode_text(new_data, relative.as_posix())
        diff = list(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile=f"a/{live.name}/{relative.as_posix()}",
                tofile=f"b/{live.name}/{relative.as_posix()}",
                lineterm="",
            )
        )
        if not diff:
            diff = [
                f"--- a/{live.name}/{relative.as_posix()}",
                f"+++ b/{live.name}/{relative.as_posix()}",
            ]
        sections.extend(diff)
        changed.append(relative.as_posix())
    text = "\n".join(sections)
    if text:
        text += "\n"
    return text, changed


def stages(obj: dict[str, Any]) -> dict[str, Any]:
    value = obj.setdefault("stages", {})
    if not isinstance(value, dict):
        raise ValueError(f"{obj['skill']}.stages must be an object")
    return value


def propose(root: Path, run_dir: Path, skill: str, source: Path) -> None:
    skill = validate_skill_name(skill)
    obj = load(run_dir, skill)
    live = live_skill_dir(obj, root)
    payload = proposal_payload(source)
    diff, changed = unified_proposal_diff(live, payload)
    destination = proposal_dir(run_dir, skill)
    materialize_proposal(destination, payload)
    atomic_write_text(run_dir / "proposals" / f"{skill}.diff", diff)

    ledger_stages = stages(obj)
    ledger_stages["rewrite"] = {
        "status": "proposed",
        "proposal": str(destination),
    }
    ledger_stages["review"] = {"status": "pending"}
    save(run_dir, skill, obj)
    print(f"rewrite_harness propose: skill={skill} changed_files={len(changed)}")


def require_proposal(
    run_dir: Path, skill: str
) -> tuple[Path, dict[PurePosixPath, tuple[bytes, int]]]:
    destination = proposal_dir(run_dir, skill)
    if not destination.is_dir() or destination.is_symlink():
        raise FileNotFoundError(f"proposal does not exist for {skill}: {destination}")
    return destination, proposal_payload(destination)


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_repo(path: Path) -> Path:
    root = git_output(path, "rev-parse", "--show-toplevel")
    repo = Path(root)
    if not repo.is_dir():
        raise NotADirectoryError(f"git repository root not found: {repo}")
    return repo


def git_blob_sha(repo: Path, path: Path) -> str:
    sha = git_output(repo, "hash-object", str(path))
    if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
        raise ValueError(f"git hash-object returned an invalid object id: {sha!r}")
    return sha


def description_chars(text: str, skill: str) -> int:
    _keys, values = parse_frontmatter(text)
    if "description" not in values:
        raise ValueError(f"SKILL.md description missing for {skill}")
    return len(values["description"])


def safe_live_destination(live: Path, relative: PurePosixPath) -> Path:
    destination = live.joinpath(*relative.parts)
    resolved_live = live.resolve()
    resolved_destination = destination.resolve(strict=False)
    try:
        resolved_destination.relative_to(resolved_live)
    except ValueError as exc:
        raise ValueError(f"proposal path escapes live skill: {relative}") from exc
    if destination.exists() and not destination.is_file():
        raise ValueError(f"proposal would overwrite a non-file: {destination}")
    return destination


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def append_improvement(
    run_dir: Path,
    skill: str,
    tier: str,
    changed: list[str],
    before_chars: int,
    after_chars: int,
) -> None:
    path = run_dir / "IMPROVEMENTS.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if not existing:
        existing = (
            "# Skill rewrite improvements\n\n"
            "| skill | tier | what changed | desc before chars | desc after chars |\n"
            "|---|---|---|---:|---:|\n"
        )
    elif not existing.endswith("\n"):
        existing += "\n"
    what_changed = ", ".join(changed) if changed else "no content changes"
    row = (
        f"| {markdown_cell(skill)} | {markdown_cell(tier)} | "
        f"{markdown_cell(what_changed)} | {before_chars} | {after_chars} |\n"
    )
    atomic_write_text(path, existing + row)


def apply_proposal(root: Path, run_dir: Path, skill: str) -> None:
    skill = validate_skill_name(skill)
    obj = load(run_dir, skill)
    live = live_skill_dir(obj, root)
    _destination, payload = require_proposal(run_dir, skill)
    review = stages(obj).get("review", {})
    if not isinstance(review, dict) or review.get("status") != "approved":
        raise ValueError(f"proposal for {skill} is not approved")

    rewrite = stages(obj).get("rewrite", {})
    if not isinstance(rewrite, dict):
        raise ValueError(f"{skill}.stages.rewrite must be an object")

    repo = git_repo(live)
    current_sha = git_blob_sha(repo, live / "SKILL.md")
    proposal_matches = all(
        live.joinpath(*relative.parts).is_file()
        and live.joinpath(*relative.parts).read_bytes() == data
        and stat.S_IMODE(live.joinpath(*relative.parts).stat().st_mode) == mode
        for relative, (data, mode) in payload.items()
    )
    if rewrite.get("status") == "applied":
        if obj.get("sha_after") == current_sha and proposal_matches:
            print(f"rewrite_harness apply: skill={skill} already_applied=true")
            return
        raise ValueError(f"live files drifted after the applied proposal for {skill}")

    diff, changed = unified_proposal_diff(live, payload)
    del diff
    before_text = (live / "SKILL.md").read_text(encoding="utf-8")
    after_text = decode_text(payload[PurePosixPath("SKILL.md")][0], "SKILL.md")
    before_chars = description_chars(before_text, skill)
    after_chars = description_chars(after_text, skill)

    destinations: list[tuple[Path, bytes, int]] = []
    added_files: list[str] = []
    for relative, (data, mode) in payload.items():
        destination = safe_live_destination(live, relative)
        if not destination.exists():
            added_files.append(relative.as_posix())
        destinations.append((destination, data, mode))
    for destination, data, mode in destinations:
        atomic_write_bytes(destination, data, mode)

    sha_after = git_blob_sha(repo, live / "SKILL.md")
    obj["sha_after"] = sha_after
    rewrite["status"] = "applied"
    rewrite.setdefault("proposal", str(proposal_dir(run_dir, skill)))
    rewrite["added_files"] = added_files
    stages(obj)["rewrite"] = rewrite
    tier = obj.get("tier")
    tier_text = tier if isinstance(tier, str) else "-"
    append_improvement(
        run_dir, skill, tier_text, changed, before_chars, after_chars
    )
    save(run_dir, skill, obj)
    print(
        f"rewrite_harness apply: skill={skill} "
        f"changed_files={len(changed)} sha_after={sha_after}"
    )


def approve(run_dir: Path, skill: str, reviewer: str) -> None:
    skill = validate_skill_name(skill)
    if not reviewer.strip():
        raise ValueError("reviewer may not be empty")
    obj = load(run_dir, skill)
    require_proposal(run_dir, skill)
    stages(obj)["review"] = {
        "status": "approved",
        "reviewer": reviewer.strip(),
    }
    save(run_dir, skill, obj)
    print(f"rewrite_harness approve: skill={skill} reviewer={reviewer.strip()}")


def reject(run_dir: Path, skill: str, reason: str) -> None:
    skill = validate_skill_name(skill)
    if not reason.strip():
        raise ValueError("rejection reason may not be empty")
    obj = load(run_dir, skill)
    require_proposal(run_dir, skill)
    stages(obj)["review"] = {
        "status": "rejected",
        "reason": reason.strip(),
    }
    save(run_dir, skill, obj)
    print(f"rewrite_harness reject: skill={skill}")


def rollback(root: Path, run_dir: Path, skill: str, commit: str | None) -> None:
    skill = validate_skill_name(skill)
    obj = load(run_dir, skill)
    live = live_skill_dir(obj, root)
    rewrite = stages(obj).get("rewrite", {})
    if not isinstance(rewrite, dict) or rewrite.get("status") != "applied":
        raise ValueError(f"no applied rewrite to roll back for {skill}")
    added_files = rewrite.get("added_files", [])
    if not isinstance(added_files, list) or not all(
        isinstance(item, str) for item in added_files
    ):
        raise ValueError(
            f"{skill}.stages.rewrite.added_files must be an array of paths"
        )
    parsed_added: list[PurePosixPath] = []
    for raw_added in added_files:
        added = PurePosixPath(raw_added)
        if added.is_absolute() or ".." in added.parts or not added.parts:
            raise ValueError(f"unsafe added file recorded for {skill}: {raw_added!r}")
        parsed_added.append(added)

    repo = git_repo(live)
    relative = live.resolve().relative_to(repo.resolve()).as_posix()
    revision = "HEAD"
    if commit is None:
        result = subprocess.run(
            ["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", relative],
            check=False,
        )
        if result.returncode == 0:
            has_untracked_addition = False
            for added in parsed_added:
                repo_path = f"{relative}/{added.as_posix()}"
                tracked_at_head = git_output(
                    repo, "ls-tree", "--name-only", "HEAD", "--", repo_path
                )
                destination = safe_live_destination(live, added)
                if destination.exists() and not tracked_at_head:
                    has_untracked_addition = True
                    break
            if not has_untracked_addition:
                raise ValueError(
                    f"{skill} has no uncommitted diff; "
                    "pass --commit for a committed apply"
                )
        elif result.returncode != 1:
            raise subprocess.CalledProcessError(result.returncode, result.args)
    else:
        revision = git_output(repo, "rev-parse", "--verify", f"{commit}^{{commit}}")

    subprocess.run(
        ["git", "-C", str(repo), "checkout", revision, "--", relative],
        check=True,
    )
    for added in parsed_added:
        repo_path = f"{relative}/{added.as_posix()}"
        tracked_at_revision = git_output(
            repo, "ls-tree", "--name-only", revision, "--", repo_path
        )
        if tracked_at_revision:
            continue
        destination = safe_live_destination(live, added)
        if destination.exists():
            destination.unlink()
        parent = destination.parent
        while parent != live and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    rewrite["status"] = "proposed"
    rewrite.pop("added_files", None)
    rewrite.setdefault("proposal", str(proposal_dir(run_dir, skill)))
    stages(obj)["rewrite"] = rewrite
    obj["sha_after"] = None
    save(run_dir, skill, obj)
    print(f"rewrite_harness rollback: skill={skill} revision={revision}")


def stage_status(obj: dict[str, Any], name: str) -> str:
    value = obj.get("stages", {}).get(name)
    if value is None:
        return "-"
    if not isinstance(value, dict):
        raise ValueError(f"{obj['skill']}.stages.{name} must be an object")
    status = value.get("status", "-")
    if not isinstance(status, str):
        raise ValueError(f"{obj['skill']}.stages.{name}.status must be a string")
    return status


def print_status(run_dir: Path) -> None:
    rows = [
        (
            obj["skill"],
            obj["tier"],
            stage_status(obj, "rewrite"),
            stage_status(obj, "review"),
        )
        for obj in all_skills(run_dir)
        if obj.get("tier") in {"T2", "T3"}
    ]
    rows.sort(key=lambda row: (0 if row[1] == "T3" else 1, row[0]))
    print("| skill | tier | rewrite | review |")
    print("|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(markdown_cell(str(value)) for value in row) + " |")
    if not rows:
        print("\nNo T2/T3 skills.")


def main() -> int:
    args = parse_args()
    try:
        root = args.root.expanduser().absolute()
        run_dir = args.run_dir.expanduser().absolute()
        if args.command == "propose":
            propose(root, run_dir, args.skill, args.from_dir)
        elif args.command == "apply":
            apply_proposal(root, run_dir, args.skill)
        elif args.command == "approve":
            approve(run_dir, args.skill, args.reviewer)
        elif args.command == "reject":
            reject(run_dir, args.skill, args.reason)
        elif args.command == "rollback":
            rollback(root, run_dir, args.skill, args.commit)
        elif args.command == "status":
            print_status(run_dir)
        else:
            raise ValueError(f"unknown command: {args.command}")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR rewrite_harness: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
