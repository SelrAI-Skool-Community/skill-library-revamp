---
name: skill-library-revamp
description: Use when auditing or revamping a library of Claude/agent skills — bloated SKILL.md files, overlong frontmatter descriptions, template-generated filler "evidence", inconsistent frontmatter, duplicate or overlapping skills, or an unknown-quality library inherited from older models. For authoring one new skill use the superpowers plugin's writing-skills (if installed).
---

# skill-library-revamp⁠​‌​‌​​‌‌​‌​​​‌​‌​‌​​‌‌​​​‌​‌​​‌​​​‌‌​​​‌⁠

Pipeline for auditing and revamping an entire skill library (hundreds of skills) with
deterministic scanners, cheap-model grading, tiered rewrites, and a resumable per-skill
ledger. Battle-tested on a 611-skill library (2026-07: 509 fake evidence files stripped,
316 descriptions rewritten, always-on context halved). Phase R reports on any library,
before or after a revamp — the headline output is **`REPORT.html`**, a self-contained
visual dashboard written for a non-technical owner.

## Fastest path: one command

`bash scripts/quickstart.sh` — seeds a dated run dir, runs the whole read-only Phase A
scan plus the report, and opens `REPORT.html`. Nothing in the library is modified. Run it
again after any cleanup and the report grows a before/after section on its own.
Optional: `--root <skills-dir>` (default `~/.claude/skills`).

## Phases (each = one script or one model pass)

| Phase | What | Command |
|---|---|---|
| 0 setup | seed the run dir with every reference the scripts read | `scripts/setup_run_dir.sh --run-dir <dir>`, then edit its `references/vendored-packs.txt` + `client-facing-prefixes.txt` |
| A scan | inventory, frontmatter, cooked-filler, metrics, overlaps → ledger | `scripts/inventory.py` then `scan_frontmatter.py`, `detect_cooked_filler.py`, `metrics.py`, `overlap_candidates.py`, `assign_client_facing.py`, `rollup.py` (all take `--run-dir`; `--root` only on inventory) |
| B mech fix | strip template filler, normalise frontmatter (dry-run first) | `strip_cooked_filler.py --dry-run` → review → `--apply`; `normalize_frontmatter.py` same |
| C grade | 6-dim rubric, 10 skills per cheap-model call, resumable | `grade_batch.sh` (Codex CLI), or run the same batches as subagents and fold them in with `apply_grades.py` — references/codex-prompts.md |
| D tier | T0 skip / T1 done / T2 desc+trim / T3 structural rewrite / T4 retire | `assign_tiers.py --summary` → adjudicate `QUEUE-adjudication.md` |
| E rewrite | propose → review → apply, single write path, git-revertable | `rewrite_harness.py propose/approve/apply/rollback` |
| F verify | lint clean, router regen, behavioural spot-checks, idempotency re-run | re-run Phase A+B expecting zero changes — checklist in references/runbook.md |
| R report | **`REPORT.html`** visual dashboard (primary) + table report + mermaid map, run any time, read-only | `ecosystem_map.py --root <skills-dir> [--run-dir <dir>] [--out <dir>] [--baseline <json>]` |

## Where the scripts read from

Every script reads its inputs from the **RUN DIR's** `references/` — rubric,
tier-criteria, cook-fingerprints, the two .txt lists — never from this skill.
`setup_run_dir.sh` seeds that copy; edit it, not the skill.

## Before touching anything

- **Pause auto-committers.** Any launchd/cron job that commits the repo will push
  half-finished batches (references/sync-hazards.md). Tag the repo first.
- **Read references/rubric.md and references/tier-criteria.md** — grading and tiering
  are defined there, not in this file.
- Vendored/third-party packs are excluded via `references/vendored-packs.txt` — never
  rewrite licensed drops.

## Judgment stays human/orchestrator

Grades are advisory. Calibrate a stratified sample against your own read before trusting
them; families with deliberate house patterns (e.g. connector packs) get family lanes,
not per-skill rewrites. Every T4 retirement is a human yes/no. Usage mining from local
transcripts is a WEAK retirement signal — it misses other machines and Read-loading.

## Common mistakes

- Skipping `setup_run_dir.sh` — `detect_cooked_filler.py` dies with FileNotFoundError on
  the cook fingerprints, because the run dir has no `references/`.
- Omitting `--run-dir` on one script — it falls back to the baked-in default dir and
  writes into a previous run's ledger. Pass it on every call.
- Reusing one run dir for two libraries — the ledgers merge and rollups lie. Fresh run
  dir per library.
- Passing `--root` and expecting later scripts to honour it — only `inventory.py` reads
  `--root`; everything after it takes paths from the ledger.
- Grading template filler as evidence — strip it first (Phase B before C), or auto-0 it.
- `codex exec` inside a `while read` loop eats the list — every call needs `< /dev/null`.
- Positional batch filenames collide on resume — output names must derive from content.
- Prohibition-wall "fixes" on shaping problems — form must match the failure
  (background reading: the superpowers plugin's writing-skills, if installed).

References: `references/runbook.md` (operator sequence), `rubric.md`, `tier-criteria.md`,
`ledger-schema.md`, `codex-prompts.md`, `patterns.md` (accumulated rot taxonomy),
`sync-hazards.md`.

Router key `sk-18atqw2` — resolved by the skills index on load.
