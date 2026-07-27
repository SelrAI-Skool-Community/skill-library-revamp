#!/usr/bin/env python3
"""Parse SKILL.md frontmatter and flag metadata and description problems."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from ledger import all_skills, save, stage_done


STANDARD_KEYS = {
    "name",
    "description",
    "metadata",
    "allowed-tools",
    "license",
    "version",
    "tags",
    "source",
    "category",
    "risk",
    "date_added",
    "requires",
    "argument-hint",
    "user_invocable",
    "disable-model-invocation",
}
TOP_LEVEL_KEY = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path.home() / ".claude/skills"
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path.home() / ".claude/skill-revamp-runs/current",
    )
    return parser.parse_args()


def load_standard_keys(run_dir: Path) -> set[str]:
    """Built-in keys plus any extras listed in <run-dir>/references/standard-keys.txt."""
    keys = set(STANDARD_KEYS)
    extra = run_dir / "references/standard-keys.txt"
    if extra.is_file():
        keys.update(
            line.strip()
            for line in extra.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return keys


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
        return parsed if isinstance(parsed, str) else value
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def parse_frontmatter(text: str) -> tuple[list[str], dict[str, str]]:
    """Parse top-level YAML-like keys, including block and folded values."""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return [], {}
    end = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if end is None:
        return [], {}

    body = lines[1:end]
    keys: list[str] = []
    values: dict[str, str] = {}
    index = 0
    while index < len(body):
        line = body[index]
        match = TOP_LEVEL_KEY.match(line) if line == line.lstrip() else None
        if match is None:
            index += 1
            continue
        key, raw_value = match.groups()
        keys.append(key)
        index += 1
        continuation: list[str] = []
        while index < len(body):
            candidate = body[index]
            if candidate == candidate.lstrip() and TOP_LEVEL_KEY.match(candidate):
                break
            if candidate.startswith((" ", "\t")) or not candidate.strip():
                continuation.append(candidate)
            index += 1

        style = raw_value.strip()
        if style in {"|", "|-", "|+", ">", ">-", ">+"}:
            stripped = [part.strip() for part in continuation]
            if style.startswith(">"):
                value = " ".join(part for part in stripped if part)
            else:
                value = "\n".join(stripped).strip()
        else:
            value = _unquote(raw_value)
            extra = [part.strip() for part in continuation if part.strip()]
            if extra:
                value = " ".join([value, *extra]).strip()
        values[key] = value
    return keys, values


def is_workflow_summary(description: str) -> bool:
    lowered = description.lower()
    if re.search(
        r"\bthis skill\s+(?:owns|walks|runs|performs)\b.*?(?:then|→|->|\bstep\b)",
        lowered,
        flags=re.DOTALL,
    ):
        return True
    if sum(bool(re.search(rf"\b{word}\b", lowered)) for word in ("first", "then", "finally")) >= 2:
        return True
    markers = re.findall(
        r"\b(?:first|then|next|finally|after that)\b|(?:^|\s)\d+[.)]\s+|→|->",
        lowered,
        flags=re.MULTILINE,
    )
    return len(markers) >= 3


def run(root: Path, run_dir: Path) -> int:
    del root  # Paths come from the inventory ledger; the CLI remains pipeline-consistent.
    standard_keys = load_standard_keys(run_dir)
    count = 0
    for obj in all_skills(run_dir):
        skill_path = Path(obj["path"]) / "SKILL.md"
        if not skill_path.is_file():
            raise FileNotFoundError(f"SKILL.md missing for {obj['skill']}: {skill_path}")
        text = skill_path.read_text(encoding="utf-8")
        keys, values = parse_frontmatter(text)
        description = values.get("description", "")
        flags: dict[str, Any] = obj.setdefault("flags", {})
        flags["frontmatter_keys"] = keys
        flags["frontmatter_keys_nonstd"] = [
            key for key in keys if key not in standard_keys
        ]
        flags["name_dirname_mismatch"] = values.get("name") != obj["skill"]
        flags["desc_chars"] = len(description)
        flags["desc_workflow_summary"] = is_workflow_summary(description)
        stage_done(obj, "scan_frontmatter")
        save(run_dir, obj["skill"], obj)
        count += 1
    return count


def main() -> int:
    args = parse_args()
    try:
        count = run(args.root, args.run_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR scan_frontmatter: {exc}", file=sys.stderr)
        return 1
    print(f"scan_frontmatter: scanned={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
