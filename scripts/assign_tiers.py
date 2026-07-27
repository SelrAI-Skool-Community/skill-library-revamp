#!/usr/bin/env python3
"""Assign proposed rewrite tiers and build the adjudication queue."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from ledger import all_skills, atomic_write_text, save, stage_done


GRADE_DIMS = (
    "description_discipline",
    "body_economy",
    "form_matches_failure",
    "progressive_disclosure",
    "evidence_reality",
    "freshness",
)
TIER_DIMS = (
    "description_discipline",
    "body_economy",
    "form_matches_failure",
    "progressive_disclosure",
)
BODY_DIMS = (
    "body_economy",
    "form_matches_failure",
    "progressive_disclosure",
)
TIER_ORDER = ("T4", "T3", "T2", "T1", "Ungraded")
COOKED_NOTE = re.compile(
    r"\b(?:auto-?0|cook(?:ed)?|fingerprint|template(?:d)?)\b", re.IGNORECASE
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
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print tier counts, including inventory exclusions and ungraded skips",
    )
    return parser.parse_args()


def grade_dims(obj: dict[str, Any]) -> dict[str, int] | None:
    grade = obj.get("grade")
    if grade is None:
        return None
    if not isinstance(grade, dict):
        raise ValueError(f"{obj['skill']}.grade must be an object or null")
    raw_dims = grade.get("dims")
    if not isinstance(raw_dims, dict):
        raise ValueError(f"{obj['skill']}.grade.dims must be an object")

    dims: dict[str, int] = {}
    for name in GRADE_DIMS:
        value = raw_dims.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{obj['skill']}.grade.dims.{name} must be an integer")
        if not 0 <= value <= 3:
            raise ValueError(
                f"{obj['skill']}.grade.dims.{name} is outside 0..3: {value}"
            )
        dims[name] = value
    return dims


def cooked_only_evidence(obj: dict[str, Any], dims: dict[str, int]) -> bool:
    if dims["evidence_reality"] > 1:
        return False
    strip_stage = obj.get("stages", {}).get("strip_filler", {})
    if not isinstance(strip_stage, dict):
        raise ValueError(f"{obj['skill']}.stages.strip_filler must be an object")
    removed = strip_stage.get("removed", [])
    if not isinstance(removed, list):
        raise ValueError(
            f"{obj['skill']}.stages.strip_filler.removed must be an array"
        )
    if not removed:
        return False

    grade = obj["grade"]
    notes = grade.get("notes", {})
    if not isinstance(notes, dict):
        raise ValueError(f"{obj['skill']}.grade.notes must be an object")
    note = notes.get("evidence_reality", "")
    if not isinstance(note, str):
        raise ValueError(
            f"{obj['skill']}.grade.notes.evidence_reality must be a string"
        )
    return not note or bool(COOKED_NOTE.search(note))


def effective_dims(obj: dict[str, Any], dims: dict[str, int]) -> dict[str, int]:
    effective = dict(dims)
    if cooked_only_evidence(obj, dims):
        del effective["evidence_reality"]
    return effective


def numeric_flag(flags: dict[str, Any], name: str, skill: str) -> float:
    value = flags.get(name, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{skill}.flags.{name} must be a number")
    return float(value)


def integer_flag(flags: dict[str, Any], name: str, skill: str) -> int:
    value = flags.get(name, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{skill}.flags.{name} must be an integer")
    return value


def overlap_candidates(obj: dict[str, Any]) -> list[dict[str, Any]]:
    raw = obj.get("flags", {}).get("overlap_candidates", [])
    if not isinstance(raw, list):
        raise ValueError(f"{obj['skill']}.flags.overlap_candidates must be an array")
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(
                f"{obj['skill']}.flags.overlap_candidates[{index}] must be an object"
            )
        peer = item.get("peer")
        score = item.get("cos")
        if not isinstance(peer, str) or not peer:
            raise ValueError(
                f"{obj['skill']}.flags.overlap_candidates[{index}].peer "
                "must be a non-empty string"
            )
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError(
                f"{obj['skill']}.flags.overlap_candidates[{index}].cos "
                "must be a number"
            )
        if not 0.0 <= float(score) <= 1.0:
            raise ValueError(
                f"{obj['skill']}.flags.overlap_candidates[{index}].cos "
                f"is outside 0..1: {score}"
            )
        candidates.append(item)
    return candidates


def confirmed_overlap(obj: dict[str, Any]) -> str | None:
    confirmation_keys = (
        "confirmed_same_job",
        "adjudicator_confirms_same_job",
        "same_job",
    )
    for candidate in overlap_candidates(obj):
        if float(candidate["cos"]) < 0.55:
            continue
        confirmed = any(candidate.get(key) is True for key in confirmation_keys)
        confirmed = confirmed or candidate.get("adjudication") in {
            "same_job",
            "confirmed_same_job",
        }
        if confirmed:
            return candidate["peer"]
    return None


def live_replacement(
    obj: dict[str, Any], live_by_name: dict[str, Path]
) -> str | None:
    grade = obj.get("grade", {})
    notes = grade.get("notes", {}) if isinstance(grade, dict) else {}
    if not isinstance(notes, dict):
        raise ValueError(f"{obj['skill']}.grade.notes must be an object")
    note = notes.get("freshness", "")
    if not isinstance(note, str):
        raise ValueError(f"{obj['skill']}.grade.notes.freshness must be a string")
    if not re.search(r"\b(?:supersed|replac)", note, flags=re.IGNORECASE):
        return None
    for name, skill_dir in sorted(live_by_name.items()):
        if name == obj["skill"] or not (skill_dir / "SKILL.md").is_file():
            continue
        if re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])",
            note,
            flags=re.IGNORECASE,
        ):
            return name
    return None


def tier_for(
    obj: dict[str, Any],
    dims: dict[str, int],
    live_by_name: dict[str, Path],
) -> tuple[str, str]:
    skill = obj["skill"]
    flags = obj.get("flags", {})
    if not isinstance(flags, dict):
        raise ValueError(f"{skill}.flags must be an object")

    twin = confirmed_overlap(obj)
    if (
        twin is not None
        and twin in live_by_name
        and (live_by_name[twin] / "SKILL.md").is_file()
    ):
        return "T4", f"confirmed semantic twin of {twin}"
    replacement = live_replacement(obj, live_by_name)
    if replacement is not None:
        return "T4", f"freshness note names live replacement {replacement}"

    low_core = [name for name in TIER_DIMS if dims[name] <= 1]
    prohibition = numeric_flag(flags, "prohibition_density", skill)
    lines = integer_flag(flags, "lines", skill)
    has_references = flags.get("has_references_dir", False)
    if not isinstance(has_references, bool):
        raise ValueError(f"{skill}.flags.has_references_dir must be a boolean")

    # T3 is for STRUCTURAL rot (wrong form, no disclosure) — recalibrated 2026-07-26
    # after the first pass swept 350 skills in via "any 2 dims <=1": overlong
    # descriptions + bloated bodies are T2's job (desc rewrite + trim), not a full
    # rewrite. A structural dim must be low for T3.
    structural_low = [d for d in ("form_matches_failure", "progressive_disclosure") if dims[d] <= 1]
    if structural_low and len(low_core) >= 2:
        return "T3", f"structural dim(s) {'+'.join(structural_low)} <=1 with {len(low_core)} core dims <=1"
    if prohibition > 0.8 and dims["form_matches_failure"] <= 1:
        return "T3", "prohibition density >0.8 and form_matches_failure <=1"
    if lines > 600 and not has_references:
        return "T3", "more than 600 lines without a references directory"
    if len(low_core) >= 2:
        return "T2", f"{len(low_core)} non-structural dims <=1 (desc/body lane)"

    desc_chars = integer_flag(flags, "desc_chars", skill)
    workflow_summary = flags.get("desc_workflow_summary", False)
    if not isinstance(workflow_summary, bool):
        raise ValueError(f"{skill}.flags.desc_workflow_summary must be a boolean")
    low_body = [name for name in BODY_DIMS if name in dims and dims[name] <= 1]
    if desc_chars > 700:
        return "T2", "description exceeds 700 characters"
    if workflow_summary:
        return "T2", "description contains a workflow summary"
    if dims["description_discipline"] <= 1:
        return "T2", "description_discipline <=1"
    if len(low_body) == 1:
        return "T2", f"one body dimension scores <=1 ({low_body[0]})"
    return "T1", "all tier dimensions acceptable and description <=700"


def worst_dims(dims: dict[str, int]) -> list[str]:
    minimum = min(dims.values())
    return [name for name in GRADE_DIMS if name in dims and dims[name] == minimum]


def is_boundary_case(
    obj: dict[str, Any],
    dims: dict[str, int],
    tier: str,
    live_by_name: dict[str, Path],
) -> bool:
    for name in worst_dims(dims):
        raised = dict(dims)
        raised[name] = min(3, raised[name] + 1)
        proposed, _reason = tier_for(obj, raised, live_by_name)
        if proposed != tier:
            return True
    return False


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def overlap_text(obj: dict[str, Any]) -> str:
    return ", ".join(
        f"{candidate['peer']} ({float(candidate['cos']):.4f})"
        for candidate in overlap_candidates(obj)
    ) or "-"


def render_queue(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Skill tier adjudication queue",
        "",
        "Auto-assigned proposals requiring orchestrator review.",
        "",
    ]
    if not rows:
        lines.extend(["No skills require adjudication.", ""])
        return "\n".join(lines)

    for tier in TIER_ORDER:
        tier_rows = [row for row in rows if row["tier"] == tier]
        if not tier_rows:
            continue
        tier_rows.sort(
            key=lambda row: (
                row["worst_score"],
                row["score_sum"],
                row["skill"],
            )
        )
        lines.extend(
            [
                f"## {tier}",
                "",
                (
                    "| skill | proposed tier | trigger (why) | "
                    "worst dims | overlap peers |"
                ),
                "|---|---|---|---|---|",
            ]
        )
        for row in tier_rows:
            lines.append(
                "| "
                + " | ".join(
                    markdown_cell(str(value))
                    for value in (
                        row["skill"],
                        row["tier"],
                        "; ".join(row["triggers"]),
                        row["worst"],
                        row["overlaps"],
                    )
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def excluded_count(run_dir: Path) -> int:
    path = run_dir / "ledger/_excluded.json"
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or not isinstance(raw.get("excluded"), list):
        raise ValueError(f"invalid inventory exclusion ledger: {path}")
    return len(raw["excluded"])


def run(root: Path, run_dir: Path) -> tuple[Counter[str], int, int]:
    root = root.expanduser().absolute()
    run_dir = run_dir.expanduser().absolute()
    if not root.is_dir():
        raise NotADirectoryError(f"skills root not found: {root}")

    ledgers = list(all_skills(run_dir))
    live_by_name: dict[str, Path] = {}
    for obj in ledgers:
        raw_path = obj.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError(f"{obj['skill']}.path must be a non-empty string")
        live_by_name[obj["skill"]] = Path(raw_path).expanduser().absolute()

    counts: Counter[str] = Counter({tier: 0 for tier in TIER_ORDER})
    skipped = 0
    queue_rows: list[dict[str, Any]] = []
    for obj in ledgers:
        overlaps = overlap_candidates(obj)
        dims = grade_dims(obj)
        if dims is None:
            skipped += 1
            if overlaps:
                queue_rows.append(
                    {
                        "skill": obj["skill"],
                        "tier": "Ungraded",
                        "triggers": [
                            "grade pending; tier not assigned",
                            "overlap candidates require adjudication",
                        ],
                        "worst": "-",
                        "worst_score": 4,
                        "score_sum": 24,
                        "overlaps": overlap_text(obj),
                    }
                )
            continue

        effective = effective_dims(obj, dims)
        tier, reason = tier_for(obj, effective, live_by_name)
        boundary = is_boundary_case(obj, effective, tier, live_by_name)
        triggers: list[str] = []
        if tier in {"T3", "T4"}:
            triggers.append(reason)
        if boundary:
            triggers.append("single +1 on a worst dimension changes the tier")
        if overlaps:
            triggers.append("overlap candidates require adjudication")

        obj["tier"] = tier
        obj["tier_source"] = "auto"
        stage_done(obj, "tier")
        save(run_dir, obj["skill"], obj)
        counts[tier] += 1

        if triggers:
            worst = worst_dims(effective)
            queue_rows.append(
                {
                    "skill": obj["skill"],
                    "tier": tier,
                    "triggers": triggers,
                    "worst": ", ".join(f"{name}={effective[name]}" for name in worst),
                    "worst_score": min(effective.values()),
                    "score_sum": sum(effective.values()),
                    "overlaps": overlap_text(obj),
                }
            )

    atomic_write_text(run_dir / "QUEUE-adjudication.md", render_queue(queue_rows))
    return counts, len(ledgers) - skipped, skipped


def main() -> int:
    args = parse_args()
    try:
        counts, tiered, skipped = run(args.root, args.run_dir)
        excluded = excluded_count(args.run_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR assign_tiers: {exc}", file=sys.stderr)
        return 1

    print(f"assign_tiers: tiered={tiered} skipped={skipped}")
    if args.summary:
        print(
            "tier counts: "
            f"T0={excluded} "
            + " ".join(f"{tier}={counts[tier]}" for tier in ("T1", "T2", "T3", "T4"))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
