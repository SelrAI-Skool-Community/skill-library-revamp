#!/usr/bin/env python3
"""Remove evidence files positively matched to the retired cook templates."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

sys.dont_write_bytecode = True

from ledger import all_skills, atomic_write_text, save, utc_iso


CATEGORIES = ("setup_prompt", "examples", "smoke", "changelog")
SCALAR_FLAGS = {
    "setup_prompt": ("cooked_setup_prompt", "SETUP-PROMPT.md"),
    "smoke": ("cooked_smoke", "scripts/smoke.sh"),
    "changelog": ("cooked_changelog", "CHANGELOG.md"),
}


def threshold_value(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("threshold must be a number") from exc
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError("threshold must be between 0 and 1")
    return value


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
    parser.add_argument(
        "--threshold",
        type=threshold_value,
        default=0.90,
        help="minimum cook-template similarity to remove (default: 0.90)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        help="report removals without changing the skills tree (default)",
    )
    mode.add_argument(
        "--apply",
        dest="apply",
        action="store_true",
        help="remove matched files and update ledgers",
    )
    parser.set_defaults(apply=False)
    return parser.parse_args()


def numeric_score(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number or null")
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{label} is outside 0..1: {score}")
    return score


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


def safe_example_path(skill: str, raw_file: Any) -> str:
    if not isinstance(raw_file, str) or not raw_file:
        raise ValueError(f"cooked example file missing for {skill}")
    relative = PurePosixPath(raw_file)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) < 2
        or relative.parts[0] != "examples"
    ):
        raise ValueError(f"unsafe cooked example path for {skill}: {raw_file!r}")
    return relative.as_posix()


def candidates_for(
    obj: dict[str, Any], root: Path, threshold: float
) -> list[dict[str, Any]]:
    skill = obj["skill"]
    skill_dir = skill_dir_for(obj, root)
    flags = obj.get("flags")
    if not isinstance(flags, dict):
        raise ValueError(f"ledger flags must be an object for {skill}")

    candidates: list[dict[str, Any]] = []
    for category, (flag_name, relative) in SCALAR_FLAGS.items():
        score = numeric_score(flags.get(flag_name), f"{skill}.{flag_name}")
        if score is not None and score >= threshold:
            candidates.append(
                {
                    "category": category,
                    "file": relative,
                    "path": skill_dir / relative,
                    "sim": score,
                }
            )

    examples = flags.get("cooked_examples", [])
    if not isinstance(examples, list):
        raise ValueError(f"{skill}.cooked_examples must be an array")
    for index, item in enumerate(examples):
        if not isinstance(item, dict):
            raise ValueError(f"{skill}.cooked_examples[{index}] must be an object")
        relative = safe_example_path(skill, item.get("file"))
        score = numeric_score(
            item.get("sim"), f"{skill}.cooked_examples[{index}].sim"
        )
        if score is not None and score >= threshold:
            candidates.append(
                {
                    "category": "examples",
                    "file": relative,
                    "path": skill_dir.joinpath(*PurePosixPath(relative).parts),
                    "sim": score,
                }
            )

    return sorted(
        candidates,
        key=lambda item: (CATEGORIES.index(item["category"]), item["file"]),
    )


def append_patterns(run_dir: Path, lines: list[str]) -> None:
    if not lines:
        return
    path = run_dir / "PATTERNS.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    atomic_write_text(path, prefix + "\n".join(lines) + "\n")


def mark_applied(
    obj: dict[str, Any], removed: list[dict[str, Any]]
) -> None:
    stages = obj.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise ValueError(f"ledger stages must be an object for {obj['skill']}")
    previous = stages.get("strip_filler", {})
    if not isinstance(previous, dict):
        raise ValueError(
            f"ledger stages.strip_filler must be an object for {obj['skill']}"
        )
    prior_removed = previous.get("removed", [])
    if not isinstance(prior_removed, list):
        raise ValueError(
            f"ledger stages.strip_filler.removed must be an array for {obj['skill']}"
        )
    stages["strip_filler"] = {
        "status": "done",
        "ts": utc_iso(),
        "removed": [*prior_removed, *removed],
    }


def run(
    root: Path, run_dir: Path, threshold: float, apply: bool
) -> tuple[int, Counter[str], int]:
    root = root.expanduser().absolute()
    run_dir = run_dir.expanduser().absolute()
    if not root.is_dir():
        raise NotADirectoryError(f"skills root not found: {root}")

    ledgers = list(all_skills(run_dir))
    planned: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    counts: Counter[str] = Counter({category: 0 for category in CATEGORIES})
    for obj in ledgers:
        candidates = candidates_for(obj, root, threshold)
        for candidate in candidates:
            if not candidate["path"].is_file():
                raise FileNotFoundError(
                    f"flagged file missing for {obj['skill']}: {candidate['path']}"
                )
            counts[candidate["category"]] += 1
        planned.append((obj, candidates))

    pattern_lines: list[str] = []
    for obj, candidates in planned:
        for candidate in candidates:
            relative = f"{obj['skill']}/{candidate['file']}"
            verb = "REMOVED" if apply else "WOULD REMOVE"
            print(f"{verb} {relative} (sim={candidate['sim']:.2f})")
            pattern_lines.append(
                "P-001 | detect_cooked_filler | template-generated evidence file "
                f"| {relative} sim={candidate['sim']:.2f} "
                "| removed | yes (strip_cooked_filler.py)"
            )

    if apply:
        for obj, candidates in planned:
            removed: list[dict[str, Any]] = []
            for candidate in candidates:
                os.remove(candidate["path"])
                removed.append(
                    {
                        "file": candidate["file"],
                        "sim": candidate["sim"],
                        "removed_at": utc_iso(),
                    }
                )
            if any(item["category"] == "examples" for item in candidates):
                examples_dir = Path(obj["path"]) / "examples"
                if examples_dir.is_dir() and not any(examples_dir.iterdir()):
                    examples_dir.rmdir()
            mark_applied(obj, removed)
            save(run_dir, obj["skill"], obj)

    append_patterns(run_dir, pattern_lines)
    total = sum(counts.values())
    print(
        "strip_cooked_filler summary: "
        f"mode={'apply' if apply else 'dry-run'} "
        f"scanned={len(ledgers)} "
        f"threshold={threshold:.2f} "
        f"setup_prompt={counts['setup_prompt']} "
        f"examples={counts['examples']} "
        f"smoke={counts['smoke']} "
        f"changelog={counts['changelog']} "
        f"total={total}"
    )
    return len(ledgers), counts, total


def main() -> int:
    args = parse_args()
    try:
        run(args.root, args.run_dir, args.threshold, args.apply)
    except (OSError, ValueError) as exc:
        print(f"ERROR strip_cooked_filler: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
