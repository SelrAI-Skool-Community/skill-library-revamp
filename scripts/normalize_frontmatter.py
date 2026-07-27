#!/usr/bin/env python3
"""Normalize the permitted top-level SKILL.md frontmatter fields."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from ledger import all_skills, atomic_write_text, save, utc_iso


TOP_LEVEL_KEY = re.compile(r"^([A-Za-z0-9_-]+)(\s*:\s*)(.*)$")
BLOCK_STYLES = {"|", "|-", "|+", ">", ">-", ">+"}
CHANGE_TYPES = (
    "user_invocable",
    "name",
    "description",
    "trailing_whitespace",
)


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        help="report fixes without changing files or ledgers (default)",
    )
    mode.add_argument(
        "--apply",
        dest="apply",
        action="store_true",
        help="write normalized frontmatter and update ledgers",
    )
    parser.set_defaults(apply=False)
    return parser.parse_args()


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def split_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\n", "\r")):
        return line[:-1], line[-1]
    return line, ""


def line_content(line: str) -> str:
    return split_ending(line)[0]


def split_frontmatter(text: str, skill: str) -> tuple[list[str], str]:
    lines = text.splitlines(keepends=True)
    if not lines:
        raise ValueError(f"SKILL.md is empty for {skill}")
    first = line_content(lines[0]).lstrip("\ufeff")
    if first.strip() != "---":
        raise ValueError(f"SKILL.md frontmatter missing for {skill}")
    end = next(
        (
            index
            for index in range(1, len(lines))
            if line_content(lines[index]).strip() == "---"
        ),
        None,
    )
    if end is None:
        raise ValueError(f"SKILL.md frontmatter is unclosed for {skill}")
    return lines[: end + 1], "".join(lines[end + 1 :])


def skill_dir_for(obj: dict[str, Any], root: Path) -> Path:
    skill = obj.get("skill")
    raw_path = obj.get("path")
    if not isinstance(skill, str) or not skill:
        raise ValueError("ledger field 'skill' must be a non-empty string")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"ledger path missing for {skill}")

    skill_dir = Path(raw_path).expanduser().absolute()
    resolved_root = root.expanduser().resolve()
    resolved_skill = skill_dir.resolve()
    try:
        resolved_skill.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"ledger path for {skill} is outside skills root: {skill_dir}"
        ) from exc
    if skill_dir.name != skill:
        raise ValueError(
            f"ledger path dirname mismatch for {skill}: {skill_dir.name!r}"
        )
    return skill_dir


def normalized_scalar(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def safe_flat_scalar(value: str) -> str:
    if not value:
        return '""'
    unsafe_start = "-?:,[]{}#&*!|>'\"%@`"
    if (
        value[0] in unsafe_start
        or ": " in value
        or " #" in value
        or value.endswith(":")
    ):
        return json.dumps(value, ensure_ascii=False)
    return value


def change_record(change_type: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"type": change_type, "detail": detail, **extra}


def normalize(
    text: str, skill: str
) -> tuple[str, list[dict[str, Any]], Counter[str]]:
    frontmatter, body = split_frontmatter(text, skill)
    original_contents = [line_content(line) for line in frontmatter]
    trailing_lines = sum(
        content != content.rstrip(" \t") for content in original_contents
    )

    content_lines = original_contents[1:-1]
    endings = [split_ending(line)[1] for line in frontmatter]
    default_ending = next((ending for ending in endings if ending), "\n")

    key_positions: dict[str, list[int]] = {}
    for index, content in enumerate(content_lines):
        match = TOP_LEVEL_KEY.match(content) if content == content.lstrip() else None
        if match is not None:
            key_positions.setdefault(match.group(1), []).append(index)

    for key in ("name", "description", "user-invocable", "user_invocable"):
        if len(key_positions.get(key, [])) > 1:
            raise ValueError(f"duplicate top-level {key!r} key for {skill}")
    if key_positions.get("user-invocable") and key_positions.get("user_invocable"):
        raise ValueError(
            f"both 'user-invocable' and 'user_invocable' are present for {skill}"
        )

    changes: list[dict[str, Any]] = []
    counts: Counter[str] = Counter({key: 0 for key in CHANGE_TYPES})
    output: list[str] = []
    index = 0
    name_seen = False
    while index < len(content_lines):
        content = content_lines[index]
        match = TOP_LEVEL_KEY.match(content) if content == content.lstrip() else None
        if match is None:
            output.append(content.rstrip(" \t"))
            index += 1
            continue

        key, separator, raw_value = match.groups()
        next_index = index + 1
        while next_index < len(content_lines):
            candidate = content_lines[next_index]
            candidate_match = (
                TOP_LEVEL_KEY.match(candidate)
                if candidate == candidate.lstrip()
                else None
            )
            if candidate_match is not None:
                break
            next_index += 1

        if key == "user-invocable":
            output.append(f"user_invocable{separator}{raw_value}".rstrip(" \t"))
            changes.append(
                change_record(
                    "user_invocable",
                    "rename user-invocable to user_invocable",
                    old_key="user-invocable",
                    new_key="user_invocable",
                )
            )
            counts["user_invocable"] += 1
        elif key == "name":
            name_seen = True
            old_value = raw_value.strip()
            if old_value != skill:
                output.append(f"name{separator}{skill}".rstrip(" \t"))
                changes.append(
                    change_record(
                        "name",
                        f"set name to {skill}",
                        before=old_value,
                        after=skill,
                    )
                )
                counts["name"] += 1
            else:
                output.append(content.rstrip(" \t"))
        elif key == "description" and raw_value.strip() in BLOCK_STYLES:
            parts = [
                content_lines[position].strip()
                for position in range(index + 1, next_index)
            ]
            flat = normalized_scalar(parts)
            output.append(f"description: {safe_flat_scalar(flat)}")
            changes.append(
                change_record(
                    "description",
                    "collapse multiline description",
                )
            )
            counts["description"] += 1
            index = next_index
            continue
        else:
            output.append(content.rstrip(" \t"))

        for position in range(index + 1, next_index):
            output.append(content_lines[position].rstrip(" \t"))
        index = next_index

    if not name_seen:
        output.insert(0, f"name: {skill}")
        changes.append(
            change_record(
                "name",
                f"add name {skill}",
                before=None,
                after=skill,
            )
        )
        counts["name"] += 1

    if trailing_lines:
        changes.append(
            change_record(
                "trailing_whitespace",
                f"strip trailing whitespace from {trailing_lines} frontmatter line(s)",
                lines=trailing_lines,
            )
        )
        counts["trailing_whitespace"] += trailing_lines

    opening_content, opening_ending = split_ending(frontmatter[0])
    closing_content, closing_ending = split_ending(frontmatter[-1])
    opening = opening_content.rstrip(" \t") + (opening_ending or default_ending)
    middle = "".join(line + default_ending for line in output)
    closing = closing_content.rstrip(" \t") + closing_ending
    return opening + middle + closing + body, changes, counts


def mark_applied(obj: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    stages = obj.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise ValueError(f"ledger stages must be an object for {obj['skill']}")
    stages["normalize"] = {
        "status": "done",
        "ts": utc_iso(),
        "changes": changes,
    }


def run(
    root: Path, run_dir: Path, apply: bool
) -> tuple[int, int, Counter[str], int]:
    root = root.expanduser().absolute()
    run_dir = run_dir.expanduser().absolute()
    if not root.is_dir():
        raise NotADirectoryError(f"skills root not found: {root}")

    ledgers = list(all_skills(run_dir))
    planned: list[
        tuple[dict[str, Any], Path, str, list[dict[str, Any]], Counter[str]]
    ] = []
    totals: Counter[str] = Counter({key: 0 for key in CHANGE_TYPES})
    changed_skills = 0
    for obj in ledgers:
        skill_dir = skill_dir_for(obj, root)
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            raise FileNotFoundError(f"SKILL.md missing for {obj['skill']}: {skill_md}")
        normalized, changes, counts = normalize(
            read_text(skill_md), obj["skill"]
        )
        totals.update(counts)
        changed_skills += int(bool(changes))
        planned.append((obj, skill_md, normalized, changes, counts))

    for obj, _skill_md, _normalized, changes, _counts in planned:
        for change in changes:
            print(
                f"{'FIXED' if apply else 'WOULD FIX'} "
                f"{obj['skill']}: {change['detail']}"
            )

    if apply:
        for obj, skill_md, normalized, changes, _counts in planned:
            if changes:
                atomic_write_text(skill_md, normalized)
            mark_applied(obj, changes)
            save(run_dir, obj["skill"], obj)

    total = sum(totals.values())
    print(
        "normalize_frontmatter summary: "
        f"mode={'apply' if apply else 'dry-run'} "
        f"scanned={len(ledgers)} "
        f"changed_skills={changed_skills} "
        f"user_invocable={totals['user_invocable']} "
        f"name={totals['name']} "
        f"description={totals['description']} "
        f"trailing_whitespace={totals['trailing_whitespace']} "
        f"total={total}"
    )
    return len(ledgers), changed_skills, totals, total


def main() -> int:
    args = parse_args()
    try:
        run(args.root, args.run_dir, args.apply)
    except (OSError, ValueError) as exc:
        print(f"ERROR normalize_frontmatter: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
