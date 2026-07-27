#!/usr/bin/env python3
"""Write grade JSON files from <run-dir>/grades/ into the per-skill ledgers.

grade_batch.sh applies each batch as it finishes. Use this when the grades were
produced some other way — a subagent task, a re-run of a failed batch, a hand
edit — or to re-apply the whole grades/ dir after fixing one file.

Each file in <run-dir>/grades/*.json is a JSON array matching
references/grade-schema.json: one object per skill with "skill", "dims", and
optional "notes" / "worst_quote".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from ledger import load, save, stage_done


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir", type=Path, default=Path.home() / ".claude/skill-revamp-runs/current"
    )
    parser.add_argument(
        "--model",
        default="unknown",
        help="label recorded on each grade, e.g. the model that produced it",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace grades that are already in the ledger (default: skip them)",
    )
    return parser.parse_args()


def run(run_dir: Path, model: str, overwrite: bool) -> tuple[int, int]:
    grades_dir = run_dir / "grades"
    if not grades_dir.is_dir():
        raise FileNotFoundError(f"no grades dir: {grades_dir}")
    applied = 0
    skipped = 0
    for path in sorted(grades_dir.glob("*.json")):
        try:
            batch = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"SKIP {path.name}: not valid JSON ({exc})", file=sys.stderr)
            continue
        if not isinstance(batch, list):
            print(f"SKIP {path.name}: expected a JSON array", file=sys.stderr)
            continue
        for entry in batch:
            slug = entry.get("skill")
            if not slug or not (run_dir / "ledger" / f"{slug}.json").is_file():
                print(f"SKIP {path.name}: no ledger for {slug!r}", file=sys.stderr)
                skipped += 1
                continue
            obj = load(run_dir, slug)
            if obj.get("grade") and not overwrite:
                skipped += 1
                continue
            obj["grade"] = {
                "model": model,
                "run": path.name,
                "dims": entry.get("dims", {}),
                "notes": entry.get("notes", {}),
                "worst_quote": entry.get("worst_quote", ""),
            }
            stage_done(obj, "grade")
            save(run_dir, slug, obj)
            applied += 1
    return applied, skipped


def main() -> int:
    args = parse_args()
    try:
        applied, skipped = run(args.run_dir, args.model, args.overwrite)
    except OSError as exc:
        print(f"ERROR apply_grades: {exc}", file=sys.stderr)
        return 1
    print(f"apply_grades: applied={applied} skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
