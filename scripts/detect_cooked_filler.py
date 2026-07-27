#!/usr/bin/env python3
"""Measure generated evidence files against recovered cook-template fingerprints."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True

from ledger import all_skills, save, stage_done
from scan_frontmatter import parse_frontmatter


FINGERPRINT_FILES = {
    "setup": "setup-prompt.md",
    "example": "example.md",
    "smoke": "smoke.sh",
    "changelog": "changelog.md",
}


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


def load_fingerprints(run_dir: Path) -> dict[str, str]:
    base = run_dir / "references/cook-fingerprints"
    fingerprints: dict[str, str] = {}
    for key, filename in FINGERPRINT_FILES.items():
        path = base / filename
        if not path.is_file():
            raise FileNotFoundError(f"required cook fingerprint missing: {path}")
        fingerprints[key] = path.read_text(encoding="utf-8")
    return fingerprints


def render_template(template: str, slug: str) -> str:
    name = slug.replace("-", " ").replace("_", " ")
    replacements = {
        "{slug}": slug,
        "{trigger_1}": f"use {name}",
        "{trigger_2}": f"run {name}",
        "{trigger_3}": f"start {name}",
        "{date}": "<date>",
    }
    rendered = template
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    return rendered.replace("{{", "{").replace("}}", "}")


def normalized_lines(text: str, names: list[str]) -> list[str]:
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "<date>", text)
    for name in sorted({item for item in names if item}, key=len, reverse=True):
        normalized = re.sub(re.escape(name), "<skill>", normalized, flags=re.IGNORECASE)
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in normalized.splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]


def similarity(actual: str, template: str, slug: str, name: str) -> float:
    actual_lines = normalized_lines(actual, [slug, name])
    template_lines = normalized_lines(render_template(template, slug), [slug, name])
    denominator = max(len(actual_lines), len(template_lines))
    if denominator == 0:
        return 1.0
    overlap = sum((Counter(actual_lines) & Counter(template_lines)).values())
    return round(overlap / denominator, 4)


def score_file(
    path: Path, template: str, slug: str, name: str
) -> float | None:
    if not path.is_file():
        return None
    return similarity(path.read_text(encoding="utf-8"), template, slug, name)


def run(root: Path, run_dir: Path) -> int:
    del root
    fingerprints = load_fingerprints(run_dir)
    count = 0
    for obj in all_skills(run_dir):
        skill_dir = Path(obj["path"])
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            raise FileNotFoundError(f"SKILL.md missing for {obj['skill']}: {skill_md}")
        _, values = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        name = values.get("name", obj["skill"])
        flags = obj.setdefault("flags", {})
        flags["cooked_setup_prompt"] = score_file(
            skill_dir / "SETUP-PROMPT.md",
            fingerprints["setup"],
            obj["skill"],
            name,
        )
        flags["cooked_examples"] = [
            {
                "file": path.relative_to(skill_dir).as_posix(),
                "sim": similarity(
                    path.read_text(encoding="utf-8"),
                    fingerprints["example"],
                    obj["skill"],
                    name,
                ),
            }
            for path in sorted((skill_dir / "examples").glob("*.md"))
        ] if (skill_dir / "examples").is_dir() else []
        flags["cooked_smoke"] = score_file(
            skill_dir / "scripts/smoke.sh",
            fingerprints["smoke"],
            obj["skill"],
            name,
        )
        flags["cooked_changelog"] = score_file(
            skill_dir / "CHANGELOG.md",
            fingerprints["changelog"],
            obj["skill"],
            name,
        )
        stage_done(obj, "detect_cooked_filler")
        save(run_dir, obj["skill"], obj)
        count += 1
    return count


def main() -> int:
    args = parse_args()
    try:
        count = run(args.root, args.run_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR detect_cooked_filler: {exc}", file=sys.stderr)
        return 1
    print(f"detect_cooked_filler: scanned={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
