#!/usr/bin/env python3
"""Assign deterministic client-facing flags from the configured dirname prefixes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from ledger import all_skills, save, stage_done


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


def read_prefixes(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        raise FileNotFoundError(f"required client-facing reference missing: {path}")
    prefixes = tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not prefixes:
        raise ValueError(f"client-facing prefix list is empty: {path}")
    return prefixes


def run(root: Path, run_dir: Path) -> tuple[int, int]:
    del root
    prefixes = read_prefixes(run_dir / "references/client-facing-prefixes.txt")
    total = 0
    client_facing = 0
    for obj in all_skills(run_dir):
        matches = obj["skill"].startswith(prefixes)
        obj.setdefault("flags", {})["client_facing"] = matches
        stage_done(obj, "assign_client_facing")
        save(run_dir, obj["skill"], obj)
        total += 1
        client_facing += int(matches)
    return total, client_facing


def main() -> int:
    args = parse_args()
    try:
        total, client_facing = run(args.root, args.run_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR assign_client_facing: {exc}", file=sys.stderr)
        return 1
    print(f"assign_client_facing: scanned={total} client_facing={client_facing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
