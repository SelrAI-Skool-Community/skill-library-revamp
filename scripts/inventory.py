#!/usr/bin/env python3
"""Inventory top-level skills and seed one ledger per included skill."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from ledger import atomic_write_json, load, save, stage_done, utc_iso


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / ".claude/skills",
        help="top-level skills directory",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path.home() / ".claude/skill-revamp-runs/current",
        help="pipeline run directory",
    )
    return parser.parse_args()


def read_name_list(path: Path) -> set[str]:
    if not path.is_file():
        raise FileNotFoundError(f"required vendored-pack reference missing: {path}")
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def find_repo(start: Path) -> Path | None:
    current = start.absolute()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def git_blob_sha(repo: Path | None, skill_md: Path) -> str | None:
    if repo is None:
        return None
    try:
        relative = skill_md.absolute().relative_to(repo.absolute())
    except ValueError:
        return None
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"HEAD:{relative.as_posix()}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def run(root: Path, run_dir: Path) -> tuple[int, int]:
    root = root.expanduser().absolute()
    run_dir = run_dir.expanduser().absolute()
    if not root.is_dir():
        raise NotADirectoryError(f"skills root not found: {root}")

    vendored = read_name_list(run_dir / "references/vendored-packs.txt")
    repo = find_repo(root)
    included: list[Path] = []
    excluded: list[dict[str, str]] = []

    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if not entry.is_dir() or not (entry / "SKILL.md").is_file():
            continue
        reason: str | None = None
        if entry.name in vendored:
            reason = "vendored pack"
        elif entry.is_symlink():
            reason = "symlink"
        elif entry.name.startswith(("_", ".")):
            reason = "reserved name"
        if reason is not None:
            excluded.append(
                {"skill": entry.name, "path": str(entry.absolute()), "reason": reason}
            )
        else:
            included.append(entry)

    for entry in included:
        obj = load(run_dir, entry.name)
        obj["skill"] = entry.name
        obj["path"] = str(entry.absolute())
        obj["sha_before"] = git_blob_sha(repo, entry / "SKILL.md")
        stage_done(obj, "inventory")
        save(run_dir, entry.name, obj)

    atomic_write_json(
        run_dir / "ledger/_excluded.json",
        {
            "excluded": excluded,
            "stage": {
                "status": "done",
                "ts": utc_iso(),
                "included": len(included),
                "excluded": len(excluded),
            },
        },
    )
    return len(included), len(excluded)


def main() -> int:
    args = parse_args()
    try:
        included, excluded = run(args.root, args.run_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR inventory: {exc}", file=sys.stderr)
        return 1
    print(f"inventory: included={included} excluded={excluded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
