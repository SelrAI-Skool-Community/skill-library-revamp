#!/usr/bin/env python3
"""Visual HTML dashboard + table report + ecosystem map for a skill library.

Read-only, stdlib only. Writes REPORT.html (primary), REPORT.md and ECOSYSTEM.md.
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

MIN_FAMILY = 3
MAX_FAMILIES = 12
CHARS_PER_TOKEN = 4
LABEL_DROP = re.compile(r"[\"'`]")
LABEL_SPACE = re.compile(r"[()\[\]{}|;#<>&\\]")
KEY_LINE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")


# ---------------------------------------------------------------- scanning


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, required=True, help="top-level skills directory"
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="pipeline run dir; its ledger/ and references/ enrich the report",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output dir (default: --run-dir, else ./ecosystem-report)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="JSON of earlier metrics for the before/after section "
        "(default: baseline.json in the output dir, written by the previous run)",
    )
    return parser.parse_args()


def read_name_list(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    key: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = KEY_LINE.match(line)
        if match:
            key = match.group(1)
            fields[key] = match.group(2).strip()
        elif key is not None and line.strip():
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return {k: v.strip().strip("'\"") for k, v in fields.items()}


def scan(root: Path, vendored: set[str]) -> tuple[list[dict], Counter]:
    skills: list[dict] = []
    excluded: Counter = Counter()
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if not entry.is_dir() or not (entry / "SKILL.md").is_file():
            continue
        if entry.name in vendored:
            excluded["reference pack"] += 1
            continue
        if entry.is_symlink():
            excluded["symlink"] += 1
            continue
        if entry.name.startswith(("_", ".")):
            excluded["reserved name"] += 1
            continue
        text = (entry / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        front = parse_frontmatter(text)
        refs = sorted(
            p.name for p in (entry / "references").glob("*.md")
        ) if (entry / "references").is_dir() else []
        scripts = sorted(
            p.name
            for p in (entry / "scripts").iterdir()
            if p.is_file() and not p.name.startswith(".")
        ) if (entry / "scripts").is_dir() else []
        skills.append(
            {
                "dirname": entry.name,
                "name": front.get("name", ""),
                "description": front.get("description", ""),
                "lines": len(text.splitlines()),
                "references": refs,
                "scripts": scripts,
            }
        )
    return skills, excluded


# ---------------------------------------------------------------- families


def family_candidates(names: list[str]) -> list[tuple[str, str, str]]:
    """(label, kind, token) candidates ordered by member count then label."""
    counts: Counter = Counter()
    for name in names:
        parts = name.split("-")
        if len(parts) < 2:
            continue
        counts[("prefix", parts[0])] += 1
        counts[("suffix", parts[-1])] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0][1]))
    out = []
    for (kind, token), _count in ordered:
        label = f"{token}-*" if kind == "prefix" else f"*-{token}"
        out.append((label, kind, token))
    return out


def group_families(skills: list[dict]) -> tuple[list[dict], list[dict]]:
    """Greedily claim skills into the largest name families. Returns (families, other)."""
    names = [s["dirname"] for s in skills]
    by_name = {s["dirname"]: s for s in skills}
    claimed: set[str] = set()
    families: list[dict] = []
    for label, kind, token in family_candidates(names):
        if len(families) >= MAX_FAMILIES:
            break
        members = [
            name
            for name in names
            if name not in claimed
            and (
                name.split("-")[0] == token
                if kind == "prefix"
                else name.split("-")[-1] == token
            )
            and len(name.split("-")) > 1
        ]
        if len(members) < MIN_FAMILY:
            continue
        claimed.update(members)
        families.append(
            {"label": label, "members": [by_name[name] for name in sorted(members)]}
        )
    families.sort(key=lambda fam: (-len(fam["members"]), fam["label"]))
    other = [by_name[name] for name in names if name not in claimed]
    return families, other


# ---------------------------------------------------------------- ledger


def load_ledger(run_dir: Path | None) -> list[dict]:
    if run_dir is None:
        return []
    ledger_dir = run_dir / "ledger"
    if not ledger_dir.is_dir():
        return []
    rows = []
    for path in sorted(ledger_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return rows


# ---------------------------------------------------------------- report


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def mark(ok: bool, watch: bool) -> str:
    if ok:
        return "✅ healthy"
    return "⚠️ watch" if watch else "❌ fix"


def build_report(
    root: Path,
    skills: list[dict],
    excluded: Counter,
    families: list[dict],
    other: list[dict],
    ledger: list[dict],
) -> str:
    total = len(skills)
    desc_chars = [len(s["description"]) for s in skills]
    total_desc = sum(desc_chars)
    over_500 = [s for s in skills if len(s["description"]) > 500]
    no_desc = [s for s in skills if not s["description"]]
    mismatch = [s for s in skills if s["name"] and s["name"] != s["dirname"]]
    with_scripts = [s for s in skills if s["scripts"]]
    with_refs = [s for s in skills if s["references"]]
    total_lines = sum(s["lines"] for s in skills)
    packs = excluded.get("reference pack", 0)

    lines = [
        "# Skill library report",
        "",
        f"Library root: `{root}`",
        "",
        "## Header stats",
        "",
        "| Metric | Value | Verdict |",
        "|---|---|---|",
        f"| Skills scanned | {total} | {mark(total > 0, False)} |",
        f"| SKILL.md lines total | {total_lines:,} | "
        f"{mark(total_lines / max(total, 1) <= 200, total_lines / max(total, 1) <= 320)} |",
        f"| Description chars total | {total_desc:,} "
        f"(~{round(total_desc / CHARS_PER_TOKEN):,} tokens always loaded) | "
        f"{mark(total_desc <= 120000, total_desc <= 200000)} |",
        f"| Description chars mean | {mean(desc_chars):.0f} | "
        f"{mark(mean(desc_chars) <= 350, mean(desc_chars) <= 500)} |",
        f"| Descriptions over 500 chars | {len(over_500)} | "
        f"{mark(not over_500, len(over_500) <= total * 0.1)} |",
        f"| Skills with scripts/ | {len(with_scripts)} | {mark(True, False)} |",
        f"| Skills with references/ | {len(with_refs)} | {mark(True, False)} |",
        f"| Reference packs skipped | {packs} | {mark(True, False)} |",
        "",
    ]
    if excluded:
        skipped = ", ".join(f"{v} {k}" for k, v in sorted(excluded.items()))
        lines += [f"Skipped entries: {skipped}.", ""]

    lines += [
        "## Name families",
        "",
        "Buckets are the largest shared name prefixes and suffixes, detected from",
        "directory names. No hardcoded category list.",
        "",
        "| Family | Skills | Avg description chars | Avg SKILL.md lines |",
        "|---|---|---|---|",
    ]
    for fam in families:
        members = fam["members"]
        lines.append(
            f"| `{fam['label']}` | {len(members)} | "
            f"{mean([len(m['description']) for m in members]):.0f} | "
            f"{mean([float(m['lines']) for m in members]):.0f} |"
        )
    if other:
        lines.append(
            f"| _ungrouped_ | {len(other)} | "
            f"{mean([len(m['description']) for m in other]):.0f} | "
            f"{mean([float(m['lines']) for m in other]):.0f} |"
        )
    lines.append("")

    lines += [
        "## Health",
        "",
        "| Check | Count | Verdict |",
        "|---|---|---|",
        f"| Frontmatter name differs from folder name | {len(mismatch)} | "
        f"{mark(not mismatch, len(mismatch) <= 5)} |",
        f"| Descriptions over 500 chars | {len(over_500)} | "
        f"{mark(not over_500, len(over_500) <= total * 0.1)} |",
        f"| Skills with no description | {len(no_desc)} | "
        f"{mark(not no_desc, False)} |",
        "",
    ]
    if mismatch:
        sample = ", ".join(f"`{s['dirname']}` -> `{s['name']}`" for s in mismatch[:10])
        lines += [f"Mismatches: {sample}.", ""]

    lines += [
        "### Largest 10 skills by SKILL.md lines",
        "",
        "| Skill | Lines | Description chars | Verdict |",
        "|---|---|---|---|",
    ]
    for skill in sorted(skills, key=lambda s: -s["lines"])[:10]:
        desc_len = len(skill["description"])
        lines.append(
            f"| `{skill['dirname']}` | {skill['lines']} | {desc_len} | "
            f"{mark(skill['lines'] <= 200 and desc_len <= 500, skill['lines'] <= 400 and desc_len <= 700)} |"
        )
    lines.append("")

    lines += ledger_section(ledger)
    lines += [
        "Regenerate with `scripts/ecosystem_map.py --root <skills-dir>`.",
        "",
    ]
    return "\n".join(lines)


def ledger_section(ledger: list[dict]) -> list[str]:
    if not ledger:
        return [
            "## Ledger",
            "",
            "No run dir ledger supplied. Pass `--run-dir` after Phase A to add tier and",
            "grade tables.",
            "",
        ]
    tiers = Counter(row.get("tier") for row in ledger if row.get("tier"))
    dims: dict[str, list[int]] = defaultdict(list)
    graded = 0
    for row in ledger:
        grade = row.get("grade") or {}
        values = grade.get("dims") or {}
        if not values:
            continue
        graded += 1
        for key, value in values.items():
            if isinstance(value, (int, float)):
                dims[key].append(value)

    out = ["## Tiers and grades", "", f"Ledger rows: {len(ledger)}.", ""]
    if tiers:
        out += ["| Tier | Skills | Share |", "|---|---|---|"]
        total = sum(tiers.values())
        for tier, count in sorted(tiers.items()):
            out.append(f"| {tier} | {count} | {count * 100 / total:.0f}% |")
        out.append("")
    if dims:
        out += [
            f"Graded skills: {graded}.",
            "",
            "| Dimension | Mean score | Scored 0-1 | Verdict |",
            "|---|---|---|---|",
        ]
        for key in sorted(dims):
            values = dims[key]
            low = sum(1 for v in values if v <= 1)
            avg = mean([float(v) for v in values])
            out.append(
                f"| {key.replace('_', ' ')} | {avg:.2f} | {low} | "
                f"{mark(avg >= 3.0, avg >= 2.0)} |"
            )
        out.append("")
    return out


# ---------------------------------------------------------------- diagrams


def label(text: str, limit: int = 58) -> str:
    clean = LABEL_DROP.sub("", str(text))
    clean = LABEL_SPACE.sub(" ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > limit:
        clean = clean[: limit - 1].rstrip() + "…"
    return clean


def validate_mermaid(block: str) -> None:
    """Node labels must carry no mermaid-hostile characters. <br/> is the one exception."""
    for found in re.findall(r'\["([^"]*)"\]', block):
        bare = found.replace("<br/>", " ")
        if LABEL_SPACE.search(bare) or LABEL_DROP.search(bare):
            raise ValueError(f"unsafe mermaid label: {found!r}")
    if block.count('"') % 2:
        raise ValueError("unbalanced quotes in mermaid block")


def fence(body: str) -> str:
    validate_mermaid(body)
    return "```mermaid\n" + body.rstrip() + "\n```"


def diagram_question(skills: list[dict], families: list[dict]) -> str:
    total = len(skills)
    desc_tokens = round(sum(len(s["description"]) for s in skills) / CHARS_PER_TOKEN)
    with_refs = sum(1 for s in skills if s["references"])
    with_scripts = sum(1 for s in skills if s["scripts"])
    avg_lines = mean([float(s["lines"]) for s in skills])
    fam = families[0]["label"] if families else "any family"
    rows = [
        "flowchart LR",
        '  q["You ask a question"]',
        f'  d["Claude scans every skill description<br/>{total} always loaded, '
        f'~{desc_tokens:,} tokens"]',
        f'  p["One description matches<br/>example: {label(fam)}"]',
        f'  s["Loads that SKILL.md only<br/>~{avg_lines:.0f} lines average"]',
        f'  r["Optional: reads references/*.md<br/>{with_refs} skills have them"]',
        f'  x["Optional: runs scripts/*<br/>{with_scripts} skills have them"]',
        '  a["Answer, grounded in the skill"]',
        "  q --> d --> p --> s",
        "  s --> r --> a",
        "  s --> x --> a",
        "  s --> a",
    ]
    return "\n".join(rows)


def diagram_layout(
    root: Path, skills: list[dict], families: list[dict], other: list[dict]
) -> str:
    example = max(
        skills,
        key=lambda s: (
            bool(s["references"] and s["scripts"]),
            len(s["references"]) + len(s["scripts"]),
        ),
        default=None,
    )
    rows = ["flowchart TD", f'  root["{label(root.name)}/ root, {len(skills)} skills"]']
    for index, fam in enumerate(families):
        rows.append(
            f'  f{index}["{label(fam["label"])}, {len(fam["members"])} skills"]'
        )
        rows.append(f"  root --> f{index}")
    if other:
        rows.append(f'  fo["everything else, {len(other)} skills"]')
        rows.append("  root --> fo")
    if example is not None:
        rows += [
            f'  ex["{label(example["dirname"])}/, one skill"]',
            '  exm["SKILL.md, always-loaded description plus body"]',
            f'  exr["references/, {len(example["references"])} files read on demand"]',
            f'  exs["scripts/, {len(example["scripts"])} files run on demand"]',
            "  root --> ex",
            "  ex --> exm",
            "  ex --> exr",
            "  ex --> exs",
        ]
    return "\n".join(rows)


def diagram_anatomy(skills: list[dict]) -> tuple[str, str]:
    example = max(
        skills, key=lambda s: (len(s["references"]), len(s["scripts"])), default=None
    )
    if example is None:
        return "flowchart LR\n  none[\"empty library\"]", "none"
    rows = [
        "flowchart LR",
        f'  md["{label(example["dirname"])}/SKILL.md<br/>{example["lines"]} lines"]',
    ]
    refs = example["references"][:10]
    for index, name in enumerate(refs):
        rows.append(f'  r{index}["references/{label(name, 40)}"]')
        rows.append(f"  md --> r{index}")
    if len(example["references"]) > len(refs):
        extra = len(example["references"]) - len(refs)
        rows.append(f'  rmore["plus {extra} more reference files"]')
        rows.append("  md --> rmore")
    scripts = example["scripts"][:8]
    for index, name in enumerate(scripts):
        rows.append(f'  s{index}["scripts/{label(name, 40)}"]')
        rows.append(f"  md --> s{index}")
    if len(example["scripts"]) > len(scripts):
        extra = len(example["scripts"]) - len(scripts)
        rows.append(f'  smore["plus {extra} more scripts"]')
        rows.append("  md --> smore")
    return "\n".join(rows), example["dirname"]


def build_ecosystem(
    root: Path, skills: list[dict], families: list[dict], other: list[dict]
) -> str:
    anatomy, example_name = diagram_anatomy(skills)
    total = len(skills)
    desc_tokens = round(sum(len(s["description"]) for s in skills) / CHARS_PER_TOKEN)
    return "\n".join(
        [
            "# Skill ecosystem map",
            "",
            f"`{root}` holds {total} skills. ~{desc_tokens:,} tokens of description load",
            "into every conversation before you type anything.",
            "",
            "## 1. What happens when you ask a question",
            "",
            "Descriptions are the only part that is always in context. Everything else",
            "loads when the matching skill is picked, so short descriptions and thin",
            "SKILL.md bodies are what keep the library cheap.",
            "",
            fence(diagram_question(skills, families)),
            "",
            "## 2. How the library is organised on disk",
            "",
            "Families are the biggest shared name prefixes and suffixes in this library,",
            "detected from folder names. One skill is expanded to show the shape every",
            "skill folder follows.",
            "",
            fence(diagram_layout(root, skills, families, other)),
            "",
            "## 3. Skill anatomy",
            "",
            f"`{example_name}` carries the most reference files in this library, so it",
            "shows progressive disclosure at full stretch: a small SKILL.md pointing at",
            "detail that is only read when needed.",
            "",
            fence(anatomy),
            "",
        ]
    )


# ---------------------------------------------------------------- metrics

JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
JUNK_SUFFIXES = (".bak", ".orig", ".rej", ".swp", "~")
JUNK_MARKER = re.compile(r"\.bak-|\.backup\b|\.old$")
DOC_SUFFIX = ".md"
# Dependency and build caches are not library content — never counted, never scolded about.
PRUNE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".cache",
    "dist", "build", ".next", ".pytest_cache", ".mypy_cache", "vendor",
}
DESC_GOOD = 350
DESC_LIMIT = 500
BODY_GOOD = 200
BODY_LIMIT = 400


def measure_tree(root: Path, skills: list[dict]) -> tuple[int, int]:
    """(bytes of .md instruction text, count of junk files) inside the skill folders."""
    doc_bytes = 0
    junk = 0
    for skill in skills:
        folder = root / skill["dirname"]
        for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
            for name in filenames:
                if name in JUNK_NAMES or name.endswith(JUNK_SUFFIXES) or JUNK_MARKER.search(name):
                    junk += 1
                if name.endswith(DOC_SUFFIX):
                    try:
                        doc_bytes += os.lstat(os.path.join(dirpath, name)).st_size
                    except OSError:
                        continue
    return doc_bytes, junk


def measure_repo(root: Path) -> int:
    """Bytes of the nearest enclosing git store, else of the library tree itself.

    Resolves symlinks first — a skills dir is often a link into the real repo.
    """
    real = root.resolve()
    for parent in [real, *real.parents]:
        git = parent / ".git"
        if git.is_dir() and (git / "objects").is_dir():
            total = 0
            for dirpath, _dirnames, filenames in os.walk(git, followlinks=False):
                for name in filenames:
                    try:
                        total += os.lstat(os.path.join(dirpath, name)).st_size
                    except OSError:
                        continue
            return total
    total = 0
    for dirpath, dirnames, filenames in os.walk(real, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total


def health_checks(skills: list[dict], junk: int) -> list[dict]:
    """Weighted plain-English checks. Each carries its own fix command."""
    total = max(len(skills), 1)
    descs = [len(s["description"]) for s in skills]
    avg_desc = mean(descs)
    avg_lines = mean([float(s["lines"]) for s in skills])
    over = [s for s in skills if len(s["description"]) > DESC_LIMIT]
    empty = [s for s in skills if not s["description"]]
    mismatch = [s for s in skills if s["name"] and s["name"] != s["dirname"]]
    fat = [s for s in skills if s["lines"] > BODY_LIMIT]
    return [
        {
            "key": "desc_mean",
            "title": "Descriptions are short enough",
            "count": round(avg_desc),
            "unit": "characters on average",
            "ok": avg_desc <= DESC_GOOD,
            "watch": avg_desc <= DESC_LIMIT,
            "plain": "Every description is read before every single conversation. "
            f"The guide is {DESC_GOOD} characters; past {DESC_LIMIT} it is costing you "
            "memory on every chat, whether or not the skill is used.",
            "fix": "scripts/assign_tiers.py --run-dir <dir> --summary",
        },
        {
            "key": "desc_over",
            "title": "No description is oversized",
            "count": len(over),
            "unit": f"over {DESC_LIMIT} characters",
            "ok": not over,
            "watch": len(over) <= total * 0.05,
            "plain": "These are the worst offenders. Each one is a paragraph your AI "
            "re-reads at the start of every conversation, forever.",
            "fix": "scripts/rewrite_harness.py propose --run-dir <dir>",
        },
        {
            "key": "desc_empty",
            "title": "Every skill has a description",
            "count": len(empty),
            "unit": "with no description",
            "ok": not empty,
            "watch": False,
            "plain": "A skill with no description can never be picked. It is dead "
            "weight sitting in the folder doing nothing.",
            "fix": "scripts/normalize_frontmatter.py --run-dir <dir> --dry-run",
        },
        {
            "key": "name_mismatch",
            "title": "Folder names match skill names",
            "count": len(mismatch),
            "unit": "mismatched",
            "ok": not mismatch,
            "watch": len(mismatch) <= 5,
            "plain": "The folder says one thing and the skill calls itself another. "
            "Tools that look a skill up by name will miss these.",
            "fix": "scripts/normalize_frontmatter.py --run-dir <dir> --apply",
        },
        {
            "key": "body_fat",
            "title": "Skill bodies stay thin",
            "count": len(fat),
            "unit": f"over {BODY_LIMIT} lines",
            "ok": avg_lines <= BODY_GOOD and not fat,
            "watch": avg_lines <= 320,
            "plain": "A long skill file is slow to load and buries its own point. "
            "Detail belongs in reference files that get read only when needed.",
            "fix": "scripts/rewrite_harness.py propose --run-dir <dir>",
        },
        {
            "key": "junk",
            "title": "No leftover junk files",
            "count": junk,
            "unit": "junk files",
            "ok": junk == 0,
            "watch": junk <= 10,
            "plain": "Backup copies, editor droppings and OS clutter left inside skill "
            "folders. Harmless individually, noise in bulk.",
            "fix": "scripts/strip_cooked_filler.py --run-dir <dir> --dry-run",
        },
    ]


HEALTH_WEIGHTS = {
    "desc_mean": 30,
    "desc_over": 20,
    "desc_empty": 15,
    "name_mismatch": 15,
    "body_fat": 15,
    "junk": 5,
}


def health_score(checks: list[dict]) -> int:
    score = 0.0
    for check in checks:
        weight = HEALTH_WEIGHTS.get(check["key"], 0)
        if check["ok"]:
            score += weight
        elif check["watch"]:
            score += weight * 0.5
    return round(score)


def verdict_for(score: int) -> tuple[str, str, str]:
    """(label, status-key, what it means and what to do)."""
    if score >= 85:
        return (
            "Healthy",
            "good",
            "Nothing here needs your attention. Descriptions are short, skill files "
            "are thin, and there is no clutter. Run this again after your next batch "
            "of changes.",
        )
    if score >= 60:
        return (
            "Needs a trim",
            "warning",
            "The library works, but it is heavier than it needs to be — you are "
            "paying for that on every conversation. Work down the cards in the "
            "health section, biggest count first.",
        )
    return (
        "Fix this",
        "critical",
        "Enough is out of shape that your AI is slower and less accurate than it "
        "should be. Start at the top card in the health section and work down.",
    )


def collect_metrics(root: Path, skills: list[dict], doc_bytes: int, junk: int, score: int) -> dict:
    desc_chars = sum(len(s["description"]) for s in skills)
    return {
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "skills": len(skills),
        "desc_chars": desc_chars,
        "context_tokens": round(desc_chars / CHARS_PER_TOKEN),
        "skill_lines": sum(s["lines"] for s in skills),
        "content_bytes": doc_bytes,
        "repo_bytes": measure_repo(root),
        "junk_files": junk,
        "health_score": score,
    }


def load_baseline(explicit: Path | None, out: Path) -> tuple[dict, Path | None]:
    path = explicit if explicit else out / "baseline.json"
    if not path.is_file():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    return (data, path) if isinstance(data, dict) else ({}, None)


# ---------------------------------------------------------------- humanising


def human_int(value: float) -> str:
    value = float(value)
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= cut:
            scaled = value / cut
            text = f"{scaled:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return f"{round(value):,}"


def human_bytes(value: float) -> str:
    value = float(value)
    for cut, suffix in ((1e9, "GB"), (1e6, "MB"), (1e3, "KB")):
        if abs(value) >= cut:
            return f"{value / cut:.1f} {suffix}"
    return f"{round(value):,} B"


def esc(text: object) -> str:
    return html_mod.escape(str(text), quote=True)


def tilde(path: Path) -> str:
    """Render a path against ~ so reports never carry an account name."""
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


# ---------------------------------------------------------------- svg charts

CHART_W = 760


def bar_h(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    """Horizontal bar: square at the baseline, rounded at the data end."""
    r = min(r, max(w, 0.0), h / 2)
    if w <= r or r <= 0:
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0.5):.1f}" height="{h:.1f}"/>'
    return (
        f'<path d="M{x:.1f},{y:.1f} H{x + w - r:.1f} A{r:.1f},{r:.1f} 0 0 1 '
        f'{x + w:.1f},{y + r:.1f} V{y + h - r:.1f} A{r:.1f},{r:.1f} 0 0 1 '
        f'{x + w - r:.1f},{y + h:.1f} H{x:.1f} Z"/>'
    )


def bar_v(x: float, base: float, w: float, h: float, r: float = 4.0) -> str:
    """Column: square at the baseline, rounded at the top."""
    r = min(r, w / 2, max(h, 0.0))
    if h <= r or r <= 0:
        top = base - max(h, 0.5)
        return f'<rect x="{x:.1f}" y="{top:.1f}" width="{w:.1f}" height="{max(h, 0.5):.1f}"/>'
    top = base - h
    return (
        f'<path d="M{x:.1f},{base:.1f} V{top + r:.1f} A{r:.1f},{r:.1f} 0 0 1 '
        f'{x + r:.1f},{top:.1f} H{x + w - r:.1f} A{r:.1f},{r:.1f} 0 0 1 '
        f'{x + w:.1f},{top + r:.1f} V{base:.1f} Z"/>'
    )


def svg_open(width: int, height: int, label: str) -> str:
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" '
        f'height="{height}" preserveAspectRatio="xMinYMin meet" role="img" '
        f'aria-label="{esc(label)}">'
    )


def fit(text: str, box: float, size: float) -> bool:
    """Rough width test — only label inside a mark when it comfortably fits."""
    return len(text) * size * 0.58 + 16 <= box


def svg_paired(rows: list[dict]) -> str:
    """Before vs after, one pair per row, each pair scaled to its own values.

    Title and caption sit on their own full-width lines above each pair, so long
    captions can never collide with the series labels.
    """
    row_h = 96
    top = 10
    height = top + row_h * len(rows) + 8
    lab_x, plot_x = 8, 66
    plot_w = CHART_W - plot_x - 96
    parts = [svg_open(CHART_W, height, "Before and after comparison")]
    for index, row in enumerate(rows):
        y = top + index * row_h
        before, after = float(row["before"]), float(row["after"])
        peak = max(before, after, 1.0)
        parts.append(
            f'<text class="t-pri b" x="{lab_x}" y="{y + 15}" font-size="14">{esc(row["title"])}</text>'
        )
        parts.append(
            f'<text class="t-mut" x="{lab_x}" y="{y + 32}" font-size="11.5">{esc(row["caption"])}</text>'
        )
        for slot, (value, cls, key) in enumerate(
            ((before, "shade-a", "Before"), (after, "shade-b", "After"))
        ):
            bar_y = y + 42 + slot * 22
            width = max(plot_w * (value / peak), 2.0)
            parts.append(
                f'<g class="{cls}">{bar_h(plot_x, bar_y, width, 16)}'
                f'<title>{esc(row["title"])} {esc(key.lower())}: {esc(row["fmt"](value))}</title></g>'
            )
            parts.append(
                f'<text class="t-mut" x="{plot_x - 10}" y="{bar_y + 12}" font-size="11" '
                f'text-anchor="end">{esc(key)}</text>'
            )
            parts.append(
                f'<text class="t-pri num" x="{plot_x + width + 8:.1f}" y="{bar_y + 12}" '
                f'font-size="12.5">{esc(row["fmt"](value))}</text>'
            )
        if index < len(rows) - 1:
            parts.append(
                f'<line class="grid" x1="{lab_x}" y1="{y + row_h - 10}" '
                f'x2="{CHART_W - 8}" y2="{y + row_h - 10}"/>'
            )
    parts.append("</svg>")
    return "".join(parts)


def svg_composition(segments: list[tuple[str, int, str]]) -> str:
    """One 100% stacked bar — part-to-whole across detected families."""
    total = max(sum(count for _label, count, _cls in segments), 1)
    height, bar_y, bar_h_px = 96, 14, 34
    x0, plot_w = 8, CHART_W - 16
    parts = [svg_open(CHART_W, height, "Library composition by family")]
    cursor = float(x0)
    for name, count, cls in segments:
        width = plot_w * count / total
        drawn = max(width - 2, 1.0)
        parts.append(f'<g class="{cls}"><rect x="{cursor:.1f}" y="{bar_y}" '
                     f'width="{drawn:.1f}" height="{bar_h_px}" rx="2">'
                     f"<title>{esc(name)}: {count} skills</title></rect></g>")
        share = f"{count * 100 / total:.0f}%"
        if fit(share, drawn, 11):
            parts.append(
                f'<text class="on-fill" x="{cursor + drawn / 2:.1f}" y="{bar_y + 22}" '
                f'font-size="11" text-anchor="middle">{esc(share)}</text>'
            )
        cursor += width
    legend_y = bar_y + bar_h_px + 26
    lx = float(x0)
    for name, count, cls in segments:
        text = f"{name} ({count})"
        parts.append(f'<g class="{cls}"><rect x="{lx:.1f}" y="{legend_y - 9}" '
                     f'width="10" height="10" rx="2"/></g>')
        parts.append(
            f'<text class="t-sec" x="{lx + 16:.1f}" y="{legend_y}" font-size="11.5">{esc(text)}</text>'
        )
        lx += 26 + len(text) * 6.1
        if lx > CHART_W - 120:
            lx = float(x0)
            legend_y += 20
    parts.append("</svg>")
    return "".join(parts)


def svg_hbars(
    rows: list[tuple[str, float]],
    fmt=human_int,
    series: str = "s1",
    guides: list[tuple[float, str]] | None = None,
    label_w: int = 210,
) -> str:
    """Single-series horizontal bars: one hue, direct-labelled, optional guide lines."""
    row_h, top = 28, 14
    height = top + row_h * len(rows) + 30
    plot_x = label_w
    plot_w = CHART_W - plot_x - 78
    peak = max([value for _name, value in rows] + [g[0] for g in (guides or [])] + [1.0])
    parts = [svg_open(CHART_W, height, "Bar chart")]
    for index, (name, value) in enumerate(rows):
        y = top + index * row_h
        width = max(plot_w * value / peak, 1.0)
        parts.append(
            f'<text class="t-sec" x="{plot_x - 10}" y="{y + 15}" font-size="12" '
            f'text-anchor="end">{esc(name)}</text>'
        )
        parts.append(
            f'<g class="{series}">{bar_h(plot_x, y + 3, width, 16)}'
            f"<title>{esc(name)}: {esc(fmt(value))}</title></g>"
        )
        parts.append(
            f'<text class="t-pri num" x="{plot_x + width + 8:.1f}" y="{y + 15}" '
            f'font-size="12">{esc(fmt(value))}</text>'
        )
    base_y = top + row_h * len(rows)
    for value, caption in guides or []:
        gx = plot_x + plot_w * value / peak
        parts.append(f'<line class="guide" x1="{gx:.1f}" y1="{top - 6}" x2="{gx:.1f}" y2="{base_y}"/>')
        parts.append(
            f'<text class="t-mut" x="{gx:.1f}" y="{base_y + 16}" font-size="10.5" '
            f'text-anchor="middle">{esc(caption)}</text>'
        )
    parts.append(f'<line class="axis" x1="{plot_x}" y1="{base_y}" x2="{CHART_W - 78}" y2="{base_y}"/>')
    parts.append("</svg>")
    return "".join(parts)


def svg_histogram(bins: list[tuple[str, int]], guides: list[tuple[float, str]]) -> str:
    """Distribution of description lengths, with the guide lines drawn in."""
    height, top, base = 262, 36, 206
    x0 = 44
    plot_w = CHART_W - x0 - 16
    band = plot_w / max(len(bins), 1)
    peak = max([count for _name, count in bins] + [1])
    parts = [svg_open(CHART_W, height, "Description length distribution")]
    for step in range(5):
        gy = base - (base - top) * step / 4
        parts.append(f'<line class="grid" x1="{x0}" y1="{gy:.1f}" x2="{CHART_W - 16}" y2="{gy:.1f}"/>')
        parts.append(
            f'<text class="t-mut num" x="{x0 - 8}" y="{gy + 4:.1f}" font-size="10.5" '
            f'text-anchor="end">{esc(f"{round(peak * step / 4):,}")}</text>'
        )
    for index, (name, count) in enumerate(bins):
        thickness = min(24.0, band - 10)
        bx = x0 + band * index + (band - thickness) / 2
        bar_height = (base - top) * count / peak
        parts.append(
            f'<g class="s1">{bar_v(bx, base, thickness, bar_height)}'
            f"<title>{esc(name)} characters: {count} skills</title></g>"
        )
        parts.append(
            f'<text class="t-mut" x="{bx + thickness / 2:.1f}" y="{base + 16}" '
            f'font-size="10" text-anchor="middle">{esc(name)}</text>'
        )
        if count:
            parts.append(
                f'<text class="t-sec num" x="{bx + thickness / 2:.1f}" '
                f'y="{base - bar_height - 6:.1f}" font-size="10.5" '
                f'text-anchor="middle">{count}</text>'
            )
    for value, caption in guides:
        gx = x0 + plot_w * value / 1200
        parts.append(f'<line class="guide" x1="{gx:.1f}" y1="{top - 12}" x2="{gx:.1f}" y2="{base}"/>')
        parts.append(
            f'<text class="t-mut" x="{gx:.1f}" y="{top - 16}" font-size="10.5" '
            f'text-anchor="middle">{esc(caption)}</text>'
        )
    parts.append(f'<line class="axis" x1="{x0}" y1="{base}" x2="{CHART_W - 16}" y2="{base}"/>')
    parts.append(
        f'<text class="t-mut" x="{x0}" y="{base + 36}" font-size="10.5">'
        "characters in the description &#8594;</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def svg_meters(rows: list[tuple[str, float]], top_score: float) -> str:
    """Score bars against a same-hue track — the meter form."""
    row_h, top = 30, 12
    height = top + row_h * len(rows) + 26
    plot_x, plot_w = 210, CHART_W - 210 - 78
    parts = [svg_open(CHART_W, height, "Average score by dimension")]
    for index, (name, value) in enumerate(rows):
        y = top + index * row_h
        parts.append(
            f'<text class="t-sec" x="{plot_x - 10}" y="{y + 16}" font-size="12" '
            f'text-anchor="end">{esc(name)}</text>'
        )
        parts.append(f'<g class="track">{bar_h(plot_x, y + 4, plot_w, 16)}</g>')
        width = max(plot_w * value / top_score, 1.0)
        parts.append(
            f'<g class="s1">{bar_h(plot_x, y + 4, width, 16)}'
            f"<title>{esc(name)}: {value:.2f} out of {top_score:.0f}</title></g>"
        )
        parts.append(
            f'<text class="t-pri num" x="{plot_x + plot_w + 8}" y="{y + 16}" '
            f'font-size="12">{value:.2f}</text>'
        )
    base_y = top + row_h * len(rows)
    parts.append(
        f'<text class="t-mut" x="{plot_x}" y="{base_y + 14}" font-size="10.5">'
        f"0 &#8212; worst &#183; {top_score:.0f} &#8212; best</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def svg_box(uid: str, x: float, y: float, w: float, h: float, lines: list[str], accent: bool) -> str:
    cls = "node accent" if accent else "node"
    parts = [f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8"/>']
    start = y + h / 2 - (len(lines) - 1) * 8
    for index, text in enumerate(lines):
        style = "t-pri b" if index == 0 else "t-mut"
        size = 13 if index == 0 else 11
        parts.append(
            f'<text class="{style}" x="{x + w / 2:.1f}" y="{start + index * 16 + 4:.1f}" '
            f'font-size="{size}" text-anchor="middle">{esc(text)}</text>'
        )
    return f'<g id="{uid}">' + "".join(parts) + "</g>"


def arrow(uid: str, x1: float, y1: float, x2: float, y2: float) -> str:
    return f'<path class="edge" marker-end="url(#{uid})" d="M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}"/>'


def marker_def(uid: str) -> str:
    return (
        f'<defs><marker id="{uid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse">'
        '<path class="edge-head" d="M0,1 L9,5 L0,9 z"/></marker></defs>'
    )


def svg_flow(skills: list[dict], families: list[dict]) -> str:
    total = len(skills)
    tokens = round(sum(len(s["description"]) for s in skills) / CHARS_PER_TOKEN)
    refs = sum(1 for s in skills if s["references"])
    scripts = sum(1 for s in skills if s["scripts"])
    avg_lines = mean([float(s["lines"]) for s in skills])
    example = families[0]["label"] if families else "a matching skill"
    mid = CHART_W / 2
    parts = [svg_open(CHART_W, 486, "How a question flows through the library"), marker_def("ar1")]
    parts.append(svg_box("n1", mid - 150, 8, 300, 44, ["You ask a question"], False))
    parts.append(arrow("ar1", mid, 52, mid, 76))
    parts.append(
        svg_box(
            "n2",
            mid - 250,
            78,
            500,
            62,
            [
                "Your AI reads every skill description",
                f"all {total:,} of them, ~{human_int(tokens)} tokens, before you type a word",
            ],
            True,
        )
    )
    parts.append(arrow("ar1", mid, 140, mid, 164))
    parts.append(
        svg_box("n3", mid - 200, 166, 400, 58, ["One description matches", f"for example {example}"], False)
    )
    parts.append(arrow("ar1", mid, 224, mid, 248))
    parts.append(
        svg_box(
            "n4",
            mid - 220,
            250,
            440,
            58,
            ["It opens that one skill file", f"~{avg_lines:.0f} lines on average, nothing else"],
            False,
        )
    )
    parts.append(f'<path class="edge" marker-end="url(#ar1)" d="M{mid - 110},308 V330 H{mid - 300} V{352}"/>')
    parts.append(f'<path class="edge" marker-end="url(#ar1)" d="M{mid + 110},308 V330 H{mid + 300} V{352}"/>')
    parts.append(arrow("ar1", mid, 308, mid, 400))
    parts.append(
        svg_box("n5", mid - 372, 354, 216, 52, ["Only if needed: notes", f"{refs} skills carry them"], False)
    )
    parts.append(
        svg_box("n6", mid + 156, 354, 216, 52, ["Only if needed: scripts", f"{scripts} skills carry them"], False)
    )
    parts.append(f'<path class="edge" marker-end="url(#ar1)" d="M{mid - 264},406 V430 H{mid - 130} V{440}"/>')
    parts.append(f'<path class="edge" marker-end="url(#ar1)" d="M{mid + 264},406 V430 H{mid + 130} V{440}"/>')
    parts.append(svg_box("n7", mid - 150, 434, 300, 44, ["You get the answer"], False))
    parts.append("</svg>")
    return "".join(parts)


def svg_tree(root: Path, skills: list[dict], families: list[dict], other: list[dict]) -> str:
    example = max(
        skills,
        key=lambda s: (bool(s["references"] and s["scripts"]), len(s["references"]) + len(s["scripts"])),
        default=None,
    )
    rows: list[tuple[int, str, str]] = [(0, f"{tilde(root)}/", f"{len(skills):,} skills")]
    for fam in families[:8]:
        rows.append((1, fam["label"], f'{len(fam["members"])} skills'))
    if len(families) > 8:
        spill = sum(len(f["members"]) for f in families[8:])
        rows.append((1, "other name families", f"{spill} skills"))
    if other:
        rows.append((1, "everything else", f"{len(other)} skills"))
    if example is not None:
        rows.append((1, f'{example["dirname"]}/', "one skill folder, expanded"))
        rows.append((2, "SKILL.md", f'{example["lines"]} lines, description always loaded'))
        rows.append((2, "references/", f'{len(example["references"])} files, read on demand'))
        rows.append((2, "scripts/", f'{len(example["scripts"])} files, run on demand'))
    row_h, top = 32, 10
    height = top + row_h * len(rows) + 8
    parts = [svg_open(CHART_W, height, "How the library sits on disk")]
    for index, (depth, name, note) in enumerate(rows):
        y = top + index * row_h
        x = 8 + depth * 34
        if depth:
            parts.append(f'<path class="edge-plain" d="M{x - 18},{y - 8} V{y + 15} H{x - 6}"/>')
        parts.append(f'<rect class="node" x="{x}" y="{y}" width="{CHART_W - x - 8}" height="24" rx="6"/>')
        parts.append(f'<text class="t-pri b" x="{x + 12}" y="{y + 16}" font-size="12.5">{esc(name)}</text>')
        parts.append(
            f'<text class="t-mut" x="{CHART_W - 20}" y="{y + 16}" font-size="11" '
            f'text-anchor="end">{esc(note)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- html page

CSS = """
*,*::before,*::after{box-sizing:border-box}
body{margin:0}
.viz-root{
  color-scheme:light;
  --page:#f9f9f7; --card:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300;
  --other:#c3c2b7; --shade-a:#86b6ef; --shade-b:#2a78d6; --track:#cde2fb;
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
  --up-good:#006300;
  --font:system-ui,-apple-system,"Segoe UI",sans-serif;
  background:var(--page); color:var(--ink); font-family:var(--font);
  -webkit-font-smoothing:antialiased; line-height:1.55;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])) .viz-root{
    color-scheme:dark;
    --page:#0d0d0d; --card:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300;
    --other:#52514e; --shade-a:#1c5cab; --shade-b:#3987e5; --track:#0d366b;
    --up-good:#0ca30c;
  }
}
:root[data-theme="dark"] .viz-root{
  color-scheme:dark;
  --page:#0d0d0d; --card:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300;
  --other:#52514e; --shade-a:#1c5cab; --shade-b:#3987e5; --track:#0d366b;
  --up-good:#0ca30c;
}
.wrap{max-width:1040px;margin:0 auto;padding:0 20px 96px}
header.top{position:sticky;top:0;z-index:9;background:var(--page);
  border-bottom:1px solid var(--border);padding:14px 0 10px;margin-bottom:28px}
.top-in{max-width:1040px;margin:0 auto;padding:0 20px;display:flex;gap:16px;
  align-items:center;flex-wrap:wrap}
.brand{font-weight:650;font-size:15px;letter-spacing:-0.01em;margin-right:auto;flex:none}
nav{display:flex;gap:14px;flex:1 1 auto;min-width:0;overflow-x:auto;
  justify-content:flex-end;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav a{color:var(--ink-2);text-decoration:none;font-size:12.5px;
  white-space:nowrap;border-bottom:1px solid transparent;padding-bottom:2px}
nav a:hover{color:var(--ink);border-bottom-color:var(--axis)}
button.theme{font:inherit;font-size:12.5px;color:var(--ink-2);background:var(--card);
  border:1px solid var(--border);border-radius:999px;padding:5px 13px;cursor:pointer;flex:none}
button.theme:hover{color:var(--ink)}
h1{font-size:30px;line-height:1.2;letter-spacing:-0.02em;margin:8px 0 6px;font-weight:680}
h2{font-size:20px;letter-spacing:-0.01em;margin:0 0 6px;font-weight:650}
h3{font-size:14px;margin:0 0 4px;font-weight:620}
p.sub{color:var(--ink-2);margin:0 0 22px;font-size:14px;max-width:74ch}
p.note{color:var(--muted);font-size:12.5px;margin:10px 0 0;max-width:78ch}
section{margin:0 0 44px;scroll-margin-top:78px}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:22px}
.grid{display:grid;gap:14px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.cards2{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.tile{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px}
.tile .lab{color:var(--ink-2);font-size:12.5px;margin:0 0 8px}
.tile .val{font-size:38px;line-height:1.05;font-weight:660;letter-spacing:-0.025em;
  display:block;color:var(--ink)}
.tile .val .unit{font-size:16px;font-weight:550;color:var(--ink-2);letter-spacing:0;
  margin-left:6px}
.tile .cap{color:var(--muted);font-size:11.5px;margin:9px 0 0;line-height:1.45}
.hero{background:var(--card);border:1px solid var(--border);border-radius:16px;
  padding:26px;display:flex;gap:26px;align-items:flex-start;flex-wrap:wrap;margin-bottom:14px}
.hero .figure{font-size:60px;font-weight:680;letter-spacing:-0.03em;line-height:1}
.hero .body{flex:1 1 320px;min-width:260px}
.pill{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:5px 13px;
  font-size:12.5px;font-weight:600;border:1px solid var(--border);background:var(--page)}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
.good .dot,.dot.good{background:var(--good)} .warning .dot,.dot.warning{background:var(--warning)}
.critical .dot,.dot.critical{background:var(--critical)} .serious .dot,.dot.serious{background:var(--serious)}
.delta{display:inline-flex;align-items:center;gap:6px;font-size:20px;font-weight:650;
  letter-spacing:-0.02em}
.delta.down{color:var(--up-good)} .delta.up{color:var(--critical)} .delta.flat{color:var(--muted)}
.delta .word{font-size:12px;font-weight:550;color:var(--ink-2);letter-spacing:0}
.ab{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(184px,1fr));margin:20px 0 6px}
.ab .item{border:1px solid var(--border);border-radius:12px;padding:14px 16px;background:var(--page)}
.ab .item .lab{font-size:12px;color:var(--ink-2);margin:0 0 7px}
.ab .item .line{font-size:11.5px;color:var(--muted);margin:8px 0 0;line-height:1.45}
.chart-scroll{overflow-x:auto;margin:4px 0 0;-webkit-overflow-scrolling:touch}
svg.chart{display:block;min-width:600px;font-family:var(--font)}
svg .t-pri{fill:var(--ink)} svg .t-sec{fill:var(--ink-2)} svg .t-mut{fill:var(--muted)}
svg .b{font-weight:620} svg .num{font-variant-numeric:tabular-nums}
svg .grid{stroke:var(--grid);stroke-width:1} svg .axis{stroke:var(--axis);stroke-width:1}
svg .guide{stroke:var(--serious);stroke-width:1}
svg .s1{fill:var(--s1)} svg .s2{fill:var(--s2)} svg .s3{fill:var(--s3)}
svg .s4{fill:var(--s4)} svg .s5{fill:var(--s5)} svg .s6{fill:var(--s6)}
svg .other{fill:var(--other)} svg .track{fill:var(--track)}
svg .shade-a{fill:var(--shade-a)} svg .shade-b{fill:var(--shade-b)}
svg .on-fill{fill:#ffffff;font-weight:600}
svg .node{fill:var(--page);stroke:var(--border);stroke-width:1}
svg .node.accent{stroke:var(--s1);stroke-width:1.5}
svg .edge,svg .edge-plain{stroke:var(--axis);stroke-width:1.5;fill:none}
svg .edge-head{fill:var(--axis)}
svg g[class]:hover rect,svg g[class]:hover path{opacity:0.82}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--ink-2);font-weight:600;font-size:12px}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
  background:var(--page);border:1px solid var(--border);border-radius:6px;padding:2px 6px;
  word-break:break-word}
details{margin:14px 0 0}
summary{cursor:pointer;font-size:12.5px;color:var(--ink-2);list-style:none;
  display:inline-flex;align-items:center;gap:7px}
summary::-webkit-details-marker{display:none}
summary::before{content:"";width:0;height:0;border-left:5px solid var(--muted);
  border-top:4px solid transparent;border-bottom:4px solid transparent;transition:transform .15s}
details[open] summary::before{transform:rotate(90deg)}
summary:hover{color:var(--ink)}
.table-scroll{overflow-x:auto;margin-top:10px}
.issue{border:1px solid var(--border);border-radius:14px;padding:18px 20px;background:var(--card)}
.issue .head{display:flex;align-items:baseline;gap:10px;margin-bottom:8px;flex-wrap:wrap}
.issue .cnt{font-size:26px;font-weight:660;letter-spacing:-0.02em}
.issue .unit{font-size:12px;color:var(--muted)}
.issue p{margin:0 0 12px;font-size:13px;color:var(--ink-2)}
.issue .fixlab{font-size:11px;color:var(--muted);margin:0 0 6px;text-transform:uppercase;
  letter-spacing:0.06em}
footer{color:var(--muted);font-size:12px;border-top:1px solid var(--border);padding-top:18px}
@media (max-width:640px){
  h1{font-size:24px} .hero .figure{font-size:46px} .tile .val{font-size:31px}
  .wrap{padding:0 14px 72px} .top-in{padding:0 14px} .card{padding:17px}
  header.top{position:static} section{scroll-margin-top:12px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
(function(){
  var r=document.documentElement,b=document.getElementById('themeBtn');
  if(!b)return;
  function set(m){r.setAttribute('data-theme',m);b.textContent=m==='dark'?'Light mode':'Dark mode';}
  b.addEventListener('click',function(){
    var dark=r.getAttribute('data-theme')==='dark'||(!r.getAttribute('data-theme')&&
      window.matchMedia('(prefers-color-scheme: dark)').matches);
    set(dark?'light':'dark');
  });
  b.textContent=window.matchMedia('(prefers-color-scheme: dark)').matches?'Light mode':'Dark mode';
})();
"""


def table(headers: list[str], rows: list[list[str]], numeric: set[int] | None = None) -> str:
    numeric = numeric or set()
    head = "".join(
        f'<th class="n">{esc(h)}</th>' if i in numeric else f"<th>{esc(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="n">{cell}</td>' if i in numeric else f"<td>{cell}</td>"
            for i, cell in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-scroll"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def table_view(headers: list[str], rows: list[list[str]], numeric: set[int] | None = None,
               label: str = "Show these numbers as a table") -> str:
    return f"<details><summary>{esc(label)}</summary>{table(headers, rows, numeric)}</details>"


DELTA_COPY = {
    "context_tokens": (
        "Always-on context cost",
        "what your AI reads before every single conversation",
        human_int,
        "Your AI now starts every chat with {pct}% more free memory.",
        "Your AI now starts every chat with {pct}% less free memory.",
    ),
    "desc_chars": (
        "Description size",
        "the one-line summary every skill carries",
        human_int,
        "The index it reads first is {pct}% shorter.",
        "The index it reads first grew {pct}%.",
    ),
    "skill_lines": (
        "Content size",
        "total lines across every skill file",
        human_int,
        "There is {pct}% less to wade through when a skill gets opened.",
        "There is {pct}% more to wade through when a skill gets opened.",
    ),
    "content_bytes": (
        "Written material",
        "every instruction file in the library",
        human_bytes,
        "The library carries {pct}% less written material.",
        "The library carries {pct}% more written material.",
    ),
    "junk_files": (
        "Junk files",
        "backups and clutter left inside skill folders",
        human_int,
        "{moved} dead files cleared out of the library.",
        "{moved} dead files have crept back in.",
    ),
    "repo_bytes": (
        "Project size on disk",
        "the whole project folder, history included",
        human_bytes,
        "The project takes {pct}% less space on your machine.",
        "The project takes {pct}% more space on your machine.",
    ),
}
DELTA_ORDER = ["context_tokens", "desc_chars", "skill_lines", "content_bytes", "junk_files", "repo_bytes"]


def delta_rows(baseline: dict, current: dict) -> list[dict]:
    rows = []
    for key in DELTA_ORDER:
        if key not in baseline or key not in current:
            continue
        try:
            before = float(baseline[key])
            after = float(current[key])
        except (TypeError, ValueError):
            continue
        title, caption, fmt, better, worse = DELTA_COPY[key]
        pct = (after - before) / before * 100 if before else 0.0
        moved = human_int(abs(before - after))
        if abs(pct) < 0.5 and before == after:
            line = "No change since the last run."
            direction = "flat"
        elif after < before:
            line = better.format(pct=f"{abs(pct):.0f}", moved=moved)
            direction = "down"
        else:
            line = worse.format(pct=f"{abs(pct):.0f}", moved=moved)
            direction = "up"
        rows.append(
            {
                "key": key,
                "title": title,
                "caption": caption,
                "fmt": fmt,
                "before": before,
                "after": after,
                "pct": pct,
                "line": line,
                "direction": direction,
            }
        )
    return rows


def hist_bins(descs: list[int]) -> list[tuple[str, int]]:
    edges = [(index * 100, index * 100 + 99) for index in range(11)]
    bins = []
    for low, high in edges:
        bins.append((f"{low // 100 * 100}", sum(1 for d in descs if low <= d <= high)))
    bins.append(("1100+", sum(1 for d in descs if d >= 1100)))
    return bins


def desc_note(chars: int) -> str:
    if chars > 1000:
        return "Very long. A paragraph re-read on every chat — cut it to one sentence."
    if chars > DESC_LIMIT:
        return "Over the guide. Trim to when-to-use plus what it covers."
    if chars > DESC_GOOD:
        return "A little long, but workable."
    return "Within range."


def build_html(
    root: Path,
    skills: list[dict],
    excluded: Counter,
    families: list[dict],
    other: list[dict],
    ledger: list[dict],
    checks: list[dict],
    metrics: dict,
    baseline: dict,
    baseline_src: Path | None,
) -> str:
    total = len(skills)
    descs = [len(s["description"]) for s in skills]
    score = metrics["health_score"]
    label, status, meaning = verdict_for(score)
    rows = delta_rows(baseline, metrics)
    generated = datetime.now().strftime("%d %b %Y")

    out = [
        '<div class="viz-root">',
        '<header class="top"><div class="top-in">',
        '<span class="brand">Skill library report</span><nav>',
        '<a href="#overview">Overview</a><a href="#flow">How it works</a>',
        '<a href="#glance">At a glance</a><a href="#descriptions">Descriptions</a>',
        '<a href="#health">Health</a>',
    ]
    if ledger:
        out.append('<a href="#tiers">Cleanup work</a>')
    out += [
        '</nav><button class="theme" id="themeBtn" type="button">Dark mode</button>',
        "</div></header>",
        '<div class="wrap">',
        '<section id="overview">',
        f"<h1>Your skill library, in plain numbers</h1>",
        f'<p class="sub">{esc(tilde(root))} &#183; scanned {esc(generated)}. '
        "A skill is a folder of written instructions your AI can pick up when it "
        "matches what you asked for.</p>",
        f'<div class="hero"><div><div class="figure">{score}</div>'
        f'<div class="pill {status}" style="margin-top:12px"><span class="dot"></span>'
        f"{esc(label)}</div></div>",
        f'<div class="body"><h2>Health score: {esc(label)}</h2>'
        f"<p style=\"margin:0;color:var(--ink-2);font-size:14px\">{esc(meaning)}</p>"
        '<p class="note">Scored out of 100 across six checks: description length, '
        "oversized descriptions, missing descriptions, name mismatches, file length "
        "and leftover junk.</p></div></div>",
    ]

    content = human_bytes(metrics["content_bytes"]).split(" ")
    tiles = [
        (
            "Skills in the library",
            f"{total:,}",
            "",
            "Folders your AI can choose from when you ask it something.",
        ),
        (
            "Always-on context cost",
            human_int(metrics["context_tokens"]),
            "tokens",
            "What your AI reads before every single conversation. Lower is cheaper "
            "and sharper.",
        ),
        (
            "Written material",
            content[0],
            content[1] if len(content) > 1 else "",
            "Every instruction file across the library, read only when a skill is used.",
        ),
        (
            "Junk files",
            f"{metrics['junk_files']:,}",
            "",
            "Backups, editor droppings and OS clutter sitting inside skill folders.",
        ),
    ]
    out.append('<div class="grid kpis">')
    for lab, value, unit, cap in tiles:
        suffix = f'<span class="unit">{esc(unit)}</span>' if unit else ""
        out.append(
            f'<div class="tile"><p class="lab">{esc(lab)}</p>'
            f'<span class="val">{esc(value)}{suffix}</span>'
            f'<p class="cap">{esc(cap)}</p></div>'
        )
    out.append("</div>")

    if rows:
        source = f" Baseline read from <code>{esc(baseline_src.name)}</code>." if baseline_src else ""
        out += [
            '<div class="card" style="margin-top:26px">',
            "<h2>Before and after</h2>",
            '<p class="sub" style="margin-bottom:0">What changed between the earlier '
            f"snapshot and today.{source} Each pair is scaled to its own two values &#8212; "
            "compare within a row, not across rows.</p>",
            '<div class="ab">',
        ]
        for row in rows:
            arrow_glyph = "&#8595;" if row["direction"] == "down" else (
                "&#8593;" if row["direction"] == "up" else "&#8212;"
            )
            word = {"down": "smaller", "up": "bigger", "flat": "unchanged"}[row["direction"]]
            pct_text = "0%" if row["direction"] == "flat" else f"{abs(row['pct']):.0f}%"
            out.append(
                f'<div class="item"><p class="lab">{esc(row["title"])}</p>'
                f'<span class="delta {row["direction"]}">{arrow_glyph} {esc(pct_text)}'
                f'<span class="word">{esc(word)}</span></span>'
                f'<p class="line">{esc(row["line"])}</p></div>'
            )
        out.append("</div>")
        out.append('<div class="chart-scroll">' + svg_paired(rows) + "</div>")
        out.append(
            table_view(
                ["Measure", "Before", "After", "Change"],
                [
                    [
                        esc(r["title"]),
                        esc(r["fmt"](r["before"])),
                        esc(r["fmt"](r["after"])),
                        esc(f"{r['pct']:+.0f}%"),
                    ]
                    for r in rows
                ],
                numeric={1, 2, 3},
            )
        )
        out.append("</div>")
    else:
        out += [
            '<div class="card" style="margin-top:26px"><h2>Before and after</h2>',
            '<p class="sub" style="margin-bottom:0">No earlier snapshot to compare against, '
            "so this is a current-state report. A snapshot has just been saved as "
            "<code>baseline.json</code> next to this file &#8212; run this again after a "
            "cleanup to see your before and after.</p></div>",
        ]

    top_families = families[:5]
    tail = sum(len(f["members"]) for f in families[5:])
    segments = [
        (f["label"], len(f["members"]), f"s{index + 1}")
        for index, f in enumerate(top_families)
    ]
    if tail:
        segments.append(("smaller groups", tail, "s6"))
    if other:
        segments.append(("no shared naming", len(other), "other"))
    out += [
        '<div class="card" style="margin-top:26px">',
        "<h2>What the library is made of</h2>",
        '<p class="sub">Groups are detected from folder names &#8212; the biggest shared '
        "prefixes and suffixes. Nothing is hardcoded, so these are your own naming "
        "habits reflected back. The grey slice is every skill whose name it shares with "
        "nothing else.</p>",
        '<div class="chart-scroll">' + svg_composition(segments) + "</div>",
        table_view(
            ["Group", "Skills", "Share"],
            [
                [esc(name), f"{count:,}", f"{count * 100 / max(total, 1):.0f}%"]
                for name, count, _cls in segments
            ],
            numeric={1, 2},
        ),
        "</div>",
    ]

    out += [
        '<div class="card" style="margin-top:26px"><h2>The verdicts, in plain English</h2>',
        '<div class="grid cards2" style="margin-top:16px">',
    ]
    for check in checks:
        state = "good" if check["ok"] else ("warning" if check["watch"] else "critical")
        word = "Healthy" if check["ok"] else ("Needs a trim" if check["watch"] else "Fix this")
        out.append(
            f'<div class="issue"><div class="head"><span class="cnt">{esc(format(check["count"], ","))}</span>'
            f'<span class="unit">{esc(check["unit"])}</span></div>'
            f'<h3>{esc(check["title"])}</h3>'
            f'<div class="pill {state}" style="margin:6px 0 10px"><span class="dot"></span>'
            f"{esc(word)}</div>"
            f'<p>{esc(check["plain"])}</p></div>'
        )
    out.append("</div></div></section>")

    out += [
        '<section id="flow"><h2>How a question flows</h2>',
        '<p class="sub">Only the descriptions are always in memory. Everything else is '
        "opened on demand, which is why short descriptions and thin skill files are what "
        "keep a big library cheap.</p>",
        '<div class="card"><div class="chart-scroll">' + svg_flow(skills, families) + "</div></div>",
        "</section>",
    ]

    fam_rows = [(f["label"], float(len(f["members"]))) for f in families]
    desc_rows = [
        (f["label"], mean([float(len(m["description"])) for m in f["members"]])) for f in families
    ]
    residual = (
        f" The {len(other):,} skills that share a name with nothing else are left out of "
        "these two charts so the groups stay readable &#8212; they are in the table below."
        if other
        else ""
    )
    out += [
        '<section id="glance"><h2>Your library at a glance</h2>',
        '<p class="sub">Two views of the same groups: how many skills each holds, and how '
        "wordy their descriptions are. Two separate charts on purpose &#8212; counts and "
        f"characters do not belong on one scale.{residual}</p>",
        '<div class="card"><h3 style="margin-bottom:12px">Skills per group</h3>',
        '<div class="chart-scroll">' + svg_hbars(fam_rows) + "</div>",
        f'<h3 style="margin:26px 0 12px">Average description length per group</h3>',
        '<div class="chart-scroll">'
        + svg_hbars(
            desc_rows,
            fmt=lambda v: f"{round(v):,}",
            series="s2",
            guides=[(float(DESC_GOOD), f"{DESC_GOOD} guide"), (float(DESC_LIMIT), f"{DESC_LIMIT} limit")],
        )
        + "</div>",
        table_view(
            ["Group", "Skills", "Avg description characters", "Avg file lines"],
            [
                [
                    esc(f["label"]),
                    f'{len(f["members"]):,}',
                    f'{mean([float(len(m["description"])) for m in f["members"]]):.0f}',
                    f'{mean([float(m["lines"]) for m in f["members"]]):.0f}',
                ]
                for f in families
            ]
            + (
                [
                    [
                        "everything else",
                        f"{len(other):,}",
                        f'{mean([float(len(m["description"])) for m in other]):.0f}',
                        f'{mean([float(m["lines"]) for m in other]):.0f}',
                    ]
                ]
                if other
                else []
            ),
            numeric={1, 2, 3},
        ),
        "</div>",
        '<div class="card" style="margin-top:20px"><h3 style="margin-bottom:12px">'
        "How it sits on disk</h3>",
        '<div class="chart-scroll">' + svg_tree(root, skills, families, other) + "</div>",
        "</div></section>",
    ]

    longest = sorted(skills, key=lambda s: -len(s["description"]))[:10]
    out += [
        '<section id="descriptions"><h2>Descriptions, up close</h2>',
        '<p class="sub">Every bar is a count of skills. The further right a skill sits, the '
        "more it costs you on every conversation, used or not.</p>",
        '<div class="card"><div class="chart-scroll">'
        + svg_histogram(
            hist_bins(descs),
            [(float(DESC_GOOD), f"{DESC_GOOD} guide"), (float(DESC_LIMIT), f"{DESC_LIMIT} limit")],
        )
        + "</div>",
        table_view(
            ["Description length", "Skills"],
            [[esc(name), f"{count:,}"] for name, count in hist_bins(descs)],
            numeric={1},
        ),
        f'<h3 style="margin:26px 0 10px">The ten wordiest descriptions</h3>',
        table(
            ["Skill", "Characters", "What to do"],
            [
                [f"<code>{esc(s['dirname'])}</code>", f"{len(s['description']):,}",
                 esc(desc_note(len(s["description"])))]
                for s in longest
            ],
            numeric={1},
        ),
        "</div></section>",
    ]

    largest = sorted(skills, key=lambda s: -s["lines"])[:10]
    out += [
        '<section id="health"><h2>Health, issue by issue</h2>',
        '<p class="sub">Each card is one class of problem: how many, what it actually costs '
        "you, and the exact command that fixes it. Swap <code>&lt;dir&gt;</code> for your run "
        "directory.</p>",
        '<div class="grid cards2">',
    ]
    for check in sorted(checks, key=lambda c: (c["ok"], c["watch"], -c["count"])):
        state = "good" if check["ok"] else ("warning" if check["watch"] else "critical")
        word = "Healthy" if check["ok"] else ("Needs a trim" if check["watch"] else "Fix this")
        out.append(
            f'<div class="issue"><div class="head"><span class="cnt">{esc(format(check["count"], ","))}</span>'
            f'<span class="unit">{esc(check["unit"])}</span></div>'
            f'<h3>{esc(check["title"])}</h3>'
            f'<div class="pill {state}" style="margin:6px 0 10px"><span class="dot"></span>'
            f"{esc(word)}</div>"
            f'<p>{esc(check["plain"])}</p>'
            f'<p class="fixlab">The fix</p><code>{esc(check["fix"])}</code></div>'
        )
    out += [
        "</div>",
        '<div class="card" style="margin-top:20px"><h3 style="margin-bottom:6px">'
        "The ten longest skill files</h3>",
        '<p class="note" style="margin:0 0 12px">Long files are slow to load and bury their '
        "own point. Detail belongs in reference files that get read only when needed.</p>",
        '<div class="chart-scroll">'
        + svg_hbars(
            [(s["dirname"], float(s["lines"])) for s in largest],
            fmt=lambda v: f"{round(v):,}",
            guides=[(float(BODY_GOOD), f"{BODY_GOOD} guide"), (float(BODY_LIMIT), f"{BODY_LIMIT} limit")],
            label_w=240,
        )
        + "</div>",
        table_view(
            ["Skill", "Lines", "Description characters"],
            [
                [f"<code>{esc(s['dirname'])}</code>", f"{s['lines']:,}", f"{len(s['description']):,}"]
                for s in largest
            ],
            numeric={1, 2},
        ),
        "</div></section>",
    ]

    out.append(ledger_html(ledger))

    skipped = ", ".join(f"{v} {k}" for k, v in sorted(excluded.items())) or "none"
    out += [
        f"<footer>Skipped while scanning: {esc(skipped)}. "
        f"Regenerate with <code>scripts/ecosystem_map.py --root {esc(tilde(root))}</code>. "
        "A fresh <code>baseline.json</code> was written next to this file, so the next run "
        "shows the change.</footer>",
        "</div></div>",
        f"<script>{JS}</script>",
    ]
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Skill library report</title>"
        f"<style>{CSS}</style></head><body>" + "".join(out) + "</body></html>"
    )


TIER_MEANING = {
    "T0": "Skipped, out of scope for this pass.",
    "T1": "Already in good shape, left alone.",
    "T2": "Description rewritten, body trimmed.",
    "T3": "Rebuilt properly, structure and wording.",
    "T4": "Retired, no longer earning its place.",
}
TIER_SHORT = {
    "T0": "skipped",
    "T1": "left alone",
    "T2": "description rewritten",
    "T3": "rebuilt",
    "T4": "retired",
}


def ledger_html(ledger: list[dict]) -> str:
    if not ledger:
        return ""
    tiers = Counter(row.get("tier") for row in ledger if row.get("tier"))
    dims: dict[str, list[float]] = defaultdict(list)
    graded = 0
    for row in ledger:
        values = (row.get("grade") or {}).get("dims") or {}
        if not values:
            continue
        graded += 1
        for key, value in values.items():
            if isinstance(value, (int, float)):
                dims[key].append(float(value))

    order = ["T0", "T1", "T2", "T3", "T4"]
    ranked = sorted(tiers.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
    total = sum(tiers.values()) or 1
    out = [
        '<section id="tiers"><h2>The cleanup work</h2>',
        f'<p class="sub">{len(ledger):,} skills were assessed and sorted into how much work '
        "each needed. This is the record of that pass.</p>",
        '<div class="card"><h3 style="margin-bottom:12px">How much work each skill needed</h3>',
        '<div class="chart-scroll">'
        + svg_hbars(
            [
                (f'{tier} — {TIER_SHORT.get(tier, "")}', float(count))
                for tier, count in ranked
            ],
            fmt=lambda v: f"{round(v):,}",
            label_w=230,
        )
        + "</div>",
        table_view(
            ["Band", "What it means", "Skills", "Share"],
            [
                [esc(tier), esc(TIER_MEANING.get(tier, "")), f"{count:,}", f"{count * 100 / total:.0f}%"]
                for tier, count in ranked
            ],
            numeric={2, 3},
        ),
        "</div>",
    ]
    if dims:
        top_score = max([max(v) for v in dims.values()] + [5.0])
        rows = sorted(
            ((key.replace("_", " "), mean(values)) for key, values in dims.items()),
            key=lambda kv: kv[1],
        )
        out += [
            '<div class="card" style="margin-top:20px">',
            f'<h3 style="margin-bottom:6px">Average score by quality dimension</h3>',
            f'<p class="note" style="margin:0 0 12px">{graded:,} skills were graded. '
            "Lower bars are where the library was weakest going in.</p>",
            '<div class="chart-scroll">' + svg_meters(rows, top_score) + "</div>",
            table_view(
                ["Dimension", "Average score", "Scored 0 or 1"],
                [
                    [
                        esc(key.replace("_", " ")),
                        f"{mean(values):.2f}",
                        f"{sum(1 for v in values if v <= 1):,}",
                    ]
                    for key, values in sorted(dims.items())
                ],
                numeric={1, 2},
            ),
            "</div>",
        ]
    out.append("</section>")
    return "".join(out)


# ---------------------------------------------------------------- main


def run(
    root: Path, run_dir: Path | None, out: Path, baseline_arg: Path | None
) -> tuple[Path, Path, Path, int]:
    root = root.expanduser().absolute()
    if not root.is_dir():
        raise NotADirectoryError(f"skills root not found: {root}")
    run_dir = run_dir.expanduser().absolute() if run_dir else None
    out = out.expanduser().absolute()
    out.mkdir(parents=True, exist_ok=True)

    vendored = read_name_list(run_dir / "references/vendored-packs.txt") if run_dir else set()
    skills, excluded = scan(root, vendored)
    if not skills:
        raise ValueError(f"no skills found under {root}")
    families, other = group_families(skills)
    ledger = load_ledger(run_dir)

    baseline_arg = baseline_arg.expanduser().absolute() if baseline_arg else None
    baseline, baseline_src = load_baseline(baseline_arg, out)

    doc_bytes, junk = measure_tree(root, skills)
    checks = health_checks(skills, junk)
    metrics = collect_metrics(root, skills, doc_bytes, junk, health_score(checks))

    html_path = out / "REPORT.html"
    report_path = out / "REPORT.md"
    ecosystem_path = out / "ECOSYSTEM.md"
    html_path.write_text(
        build_html(
            root, skills, excluded, families, other, ledger,
            checks, metrics, baseline, baseline_src,
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        build_report(root, skills, excluded, families, other, ledger), encoding="utf-8"
    )
    ecosystem_path.write_text(
        build_ecosystem(root, skills, families, other), encoding="utf-8"
    )
    # Written last so this run becomes the baseline for the next one.
    (out / "baseline.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return html_path, report_path, ecosystem_path, len(skills)


def main() -> int:
    args = parse_args()
    out = args.out or args.run_dir or Path("ecosystem-report")
    try:
        page, report, ecosystem, count = run(args.root, args.run_dir, out, args.baseline)
    except (OSError, ValueError) as exc:
        print(f"ERROR ecosystem_map: {exc}", file=sys.stderr)
        return 1
    print(f"ecosystem_map: skills={count} html={page} report={report} map={ecosystem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
