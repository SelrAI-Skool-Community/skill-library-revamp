#!/usr/bin/env python3
"""Build the Phase A markdown rollup from all per-skill ledgers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

sys.dont_write_bytecode = True

from ledger import all_skills, atomic_write_text, save, stage_done, utc_iso


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


def cooked_scores(flags: dict[str, Any]) -> list[float]:
    scores = [
        value
        for key in (
            "cooked_setup_prompt",
            "cooked_smoke",
            "cooked_changelog",
        )
        if isinstance((value := flags.get(key)), (int, float))
    ]
    scores.extend(
        item["sim"]
        for item in flags.get("cooked_examples", [])
        if isinstance(item, dict) and isinstance(item.get("sim"), (int, float))
    )
    return scores


def max_cooked(flags: dict[str, Any]) -> float | None:
    scores = cooked_scores(flags)
    return max(scores) if scores else None


def unique_overlap_pairs(ledgers: list[dict[str, Any]]) -> list[tuple[str, str, float]]:
    pairs: dict[tuple[str, str], float] = {}
    for obj in ledgers:
        for candidate in obj.get("flags", {}).get("overlap_candidates", []):
            peer = candidate.get("peer")
            score = candidate.get("cos")
            if not isinstance(peer, str) or not isinstance(score, (int, float)):
                continue
            if score < 0.55:
                continue
            key = tuple(sorted((obj["skill"], peer)))
            pairs[key] = max(pairs.get(key, 0.0), float(score))
    return sorted(
        ((left, right, score) for (left, right), score in pairs.items()),
        key=lambda item: (-item[2], item[0], item[1]),
    )


def table(headers: list[str], rows: Iterable[Iterable[Any]]) -> list[str]:
    rendered_rows = [list(row) for row in rows]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---:" if index else "---" for index in range(len(headers))) + "|",
    ]
    lines.extend(
        "| "
        + " | ".join(str(value).replace("|", "\\|") for value in row)
        + " |"
        for row in rendered_rows
    )
    if not rendered_rows:
        lines.extend(["", "No findings."])
    return lines


def top_skills(
    ledgers: list[dict[str, Any]],
    value: Callable[[dict[str, Any]], float | int | None],
    include: Callable[[dict[str, Any]], bool] | None = None,
) -> list[tuple[str, float | int]]:
    rows: list[tuple[str, float | int]] = []
    for obj in ledgers:
        if include is not None and not include(obj):
            continue
        metric = value(obj)
        if metric is None:
            continue
        rows.append((obj["skill"], metric))
    rows.sort(key=lambda item: (-float(item[1]), item[0]))
    return rows[:20]


def render_rollup(ledgers: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    flags = [obj.get("flags", {}) for obj in ledgers]
    overlap_pairs = unique_overlap_pairs(ledgers)
    cooked_maxima = [max_cooked(item) for item in flags]
    counts = {
        "total": len(ledgers),
        "nonstd": sum(bool(item.get("frontmatter_keys_nonstd")) for item in flags),
        "mismatches": sum(bool(item.get("name_dirname_mismatch")) for item in flags),
        "desc_500": sum(item.get("desc_chars", 0) > 500 for item in flags),
        "desc_700": sum(item.get("desc_chars", 0) > 700 for item in flags),
        "desc_1000": sum(item.get("desc_chars", 0) > 1000 for item in flags),
        "workflow": sum(bool(item.get("desc_workflow_summary")) for item in flags),
        "cooked_high": sum(
            value is not None and value >= 0.9 for value in cooked_maxima
        ),
        "cooked_medium": sum(
            value is not None and 0.6 <= value < 0.9 for value in cooked_maxima
        ),
        "prohibition": sum(
            item.get("prohibition_density", 0.0) > 0.8 for item in flags
        ),
        "overlaps": len(overlap_pairs),
        "client_facing": sum(bool(item.get("client_facing")) for item in flags),
        "code_files": sum(int(item.get("code_files", 0)) for item in flags),
        "code_lines": sum(int(item.get("code_lines", 0)) for item in flags),
    }
    count_rows = [
        ("Total skills", counts["total"]),
        ("Nonstandard frontmatter keys", counts["nonstd"]),
        ("Name mismatches", counts["mismatches"]),
        ("Descriptions >500 chars", counts["desc_500"]),
        ("Descriptions >700 chars", counts["desc_700"]),
        ("Descriptions >1000 chars", counts["desc_1000"]),
        ("Workflow-summary descriptions", counts["workflow"]),
        ("Cooked fingerprints >=0.90", counts["cooked_high"]),
        ("Cooked fingerprints 0.60-0.89", counts["cooked_medium"]),
        ("Prohibition density >0.8", counts["prohibition"]),
        ("Overlap pairs >=0.55", counts["overlaps"]),
        ("Client-facing", counts["client_facing"]),
        ("Code files", counts["code_files"]),
        ("Code lines", counts["code_lines"]),
    ]

    sections: list[str] = [
        "# Skill library Phase A rollup",
        "",
        f"Generated: {utc_iso()}",
        "",
        "## Counts",
        "",
        *table(["Metric", "Count"], count_rows),
        "",
        "## Top 20 longest descriptions",
        "",
        *table(
            ["Skill", "Description chars"],
            top_skills(ledgers, lambda obj: obj["flags"].get("desc_chars", 0)),
        ),
        "",
        "## Top 20 nonstandard frontmatter",
        "",
        *table(
            ["Skill", "Nonstandard key count"],
            top_skills(
                ledgers,
                lambda obj: len(obj["flags"].get("frontmatter_keys_nonstd", [])),
                lambda obj: bool(obj["flags"].get("frontmatter_keys_nonstd")),
            ),
        ),
        "",
        "## Top 20 workflow-summary descriptions",
        "",
        *table(
            ["Skill", "Description chars"],
            top_skills(
                ledgers,
                lambda obj: obj["flags"].get("desc_chars", 0),
                lambda obj: bool(obj["flags"].get("desc_workflow_summary")),
            ),
        ),
        "",
        "## Top 20 cooked-filler similarities",
        "",
        *table(
            ["Skill", "Max similarity"],
            [
                (skill, f"{score:.4f}")
                for skill, score in top_skills(
                    ledgers, lambda obj: max_cooked(obj["flags"])
                )
            ],
        ),
        "",
        "## Top 20 prohibition densities",
        "",
        *table(
            ["Skill", "Per 100 lines"],
            top_skills(
                ledgers,
                lambda obj: obj["flags"].get("prohibition_density", 0.0),
            ),
        ),
        "",
        "## Top 20 overlap pairs",
        "",
        *table(
            ["Skill A", "Skill B", "Cosine"],
            [
                (left, right, f"{score:.4f}")
                for left, right, score in overlap_pairs[:20]
            ],
        ),
        "",
        "## Top 20 code volume",
        "",
        *table(
            ["Skill", "Code lines"],
            top_skills(ledgers, lambda obj: obj["flags"].get("code_lines", 0)),
        ),
        "",
        "## Top 20 code file counts",
        "",
        *table(
            ["Skill", "Code files"],
            top_skills(ledgers, lambda obj: obj["flags"].get("code_files", 0)),
        ),
        "",
        "## Name mismatches",
        "",
        *table(
            ["Skill", "Mismatch"],
            (
                (obj["skill"], "true")
                for obj in ledgers
                if obj["flags"].get("name_dirname_mismatch")
            ),
        ),
        "",
        "## Client-facing skills (first 20)",
        "",
        *table(
            ["Skill"],
            ([obj["skill"]] for obj in ledgers if obj["flags"].get("client_facing")),
        )[:22],
        "",
    ]
    return "\n".join(sections), counts


def run(root: Path, run_dir: Path) -> dict[str, int]:
    del root
    ledgers = list(all_skills(run_dir))
    for obj in ledgers:
        stage_done(obj, "rollup")
        save(run_dir, obj["skill"], obj)
    content, counts = render_rollup(ledgers)
    atomic_write_text(run_dir / "ROLLUP.md", content)
    return counts


def main() -> int:
    args = parse_args()
    try:
        counts = run(args.root, args.run_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR rollup: {exc}", file=sys.stderr)
        return 1
    print(
        "rollup: "
        f"skills={counts['total']} "
        f"overlap_pairs={counts['overlaps']} "
        f"code_files={counts['code_files']} "
        f"code_lines={counts['code_lines']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
