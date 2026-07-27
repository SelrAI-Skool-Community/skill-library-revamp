#!/usr/bin/env python3
"""Collect deterministic size, code, prohibition, structure, and brand metrics."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from ledger import all_skills, save, stage_done


CODE_SUFFIXES = {".sh", ".py", ".js", ".mjs", ".ts"}
EXCLUDED_CODE_DIRS = {"node_modules", ".venv"}
PROHIBITION = re.compile(
    r"\b(?:NEVER|MUST|STOP|DO NOT|ALWAYS|CRITICAL|FORBIDDEN)\b"
)
WORDS = re.compile(r"\b[\w'-]+\b", flags=re.UNICODE)
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b")


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


def line_count(text: str) -> int:
    return len(text.splitlines())


def load_brand_tokens(run_dir: Path) -> list[str]:
    """Brand values this library does not want baked into skill bodies.

    Optional: one token per line in <run-dir>/references/brand-tokens.txt (hex
    codes, font names, anything). With no file, any 6-digit hex colour counts.
    """
    path = run_dir / "references/brand-tokens.txt"
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def has_brand_hardcode(text: str, tokens: list[str]) -> bool:
    if tokens:
        lowered = text.lower()
        return any(token.lower() in lowered for token in tokens)
    return bool(HEX_COLOR.search(text))


def code_metrics(skill_dir: Path) -> tuple[int, int]:
    files = 0
    lines = 0
    for current, dirnames, filenames in os.walk(skill_dir, followlinks=False):
        dirnames[:] = [
            name for name in dirnames if name not in EXCLUDED_CODE_DIRS
        ]
        current_path = Path(current)
        for filename in filenames:
            path = current_path / filename
            if path.suffix.lower() not in CODE_SUFFIXES:
                continue
            files += 1
            lines += line_count(path.read_text(encoding="utf-8", errors="replace"))
    return files, lines


def run(root: Path, run_dir: Path) -> int:
    del root
    brand_tokens = load_brand_tokens(run_dir)
    count = 0
    for obj in all_skills(run_dir):
        skill_dir = Path(obj["path"])
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            raise FileNotFoundError(f"SKILL.md missing for {obj['skill']}: {skill_md}")
        text = skill_md.read_text(encoding="utf-8")
        lines = line_count(text)
        code_files, code_lines = code_metrics(skill_dir)
        flags = obj.setdefault("flags", {})
        flags["lines"] = lines
        flags["words"] = len(WORDS.findall(text))
        flags["code_files"] = code_files
        flags["code_lines"] = code_lines
        flags["prohibition_density"] = round(
            (len(PROHIBITION.findall(text)) * 100 / lines) if lines else 0.0,
            2,
        )
        flags["has_references_dir"] = (skill_dir / "references").is_dir()
        flags["has_scripts_dir"] = (skill_dir / "scripts").is_dir()
        flags["brand_hardcode"] = has_brand_hardcode(text, brand_tokens)
        stage_done(obj, "metrics")
        save(run_dir, obj["skill"], obj)
        count += 1
    return count


def main() -> int:
    args = parse_args()
    try:
        count = run(args.root, args.run_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR metrics: {exc}", file=sys.stderr)
        return 1
    print(f"metrics: scanned={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
