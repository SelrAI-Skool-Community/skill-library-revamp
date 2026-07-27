# Operator runbook — skill-library-revamp

Sequence for a full library revamp. Every script takes `--run-dir <ops-dir>` and reads
its inputs from that dir's `references/`; only `inventory.py` uses `--root <skills-dir>`
(later stages take paths from the ledger). Nothing is hardcoded. Read sync-hazards.md FIRST.

## 0. Setup
- `scripts/setup_run_dir.sh --run-dir <dir>` — creates the run dir + `references/` and
  seeds every input the pipeline reads. It refuses to run over a non-empty `ledger/`.
- Required run-dir inputs (all seeded by the script, all edited in the RUN DIR):
  - `references/rubric.md` — grading dimensions (Phase C).
  - `references/grade-schema.json` — grade JSON contract.
  - `references/tier-criteria.md` — T0–T4 rules (Phase D).
  - `references/codex-prompts.md` — cheap-model prompt templates.
  - `references/cook-fingerprints/` — `setup-prompt.md`, `example.md`, `smoke.sh`,
    `changelog.md`; `detect_cooked_filler.py` hard-fails without all four.
  - `references/vendored-packs.txt` — exact dirnames to exclude. Edit for this library.
  - `references/client-facing-prefixes.txt` — dirname prefixes needing high-taste review.
    Must be non-empty; the seeded `zzz-none-` placeholder matches nothing.
  - `references/standard-keys.txt` — OPTIONAL. Lines here are ADDED to
    `scan_frontmatter.py`'s built-in key set, so a library's own frontmatter convention
    stops showing up as nonstandard.
- One run dir per library — a shared dir merges ledgers.
- Baseline: repo pack size, tree du, description char total, fresh-session context cost.
- Backup: `git bundle create --all` + full copy. Pause auto-committers; tag.

## A. Deterministic scans (read-only, minutes)
`inventory.py` → `scan_frontmatter.py` → `detect_cooked_filler.py` → `metrics.py` →
`overlap_candidates.py` → `assign_client_facing.py` → `rollup.py`.
Review ROLLUP.md before anything writes.

## B. Mechanical fixes (dry-run → eyeball → apply → commit)
`strip_cooked_filler.py --dry-run` (spot-open 2-3 flagged files yourself — verify they
really are template junk) then `--apply`. Same for `normalize_frontmatter.py`.
Regenerate any router/index your library derives from frontmatter. Commit.

## C. Grading (cheap model, unattended)
`grade_batch.sh` — 10 skills/call, resumable, content-hash batch names. It shells out to
the Codex CLI. **No Codex?** Run the same batches as subagent tasks: paste the grading
prompt from references/codex-prompts.md, 10 skills at a time, and have each subagent
write its JSON array to `<run-dir>/grades/batch-<anything>.json`, then run
`apply_grades.py --run-dir <dir> --model <name>` to fold them into the ledgers. The rest
of the pipeline does not care which model produced them.
**Calibration gate:** after ~100 grades, re-grade a stratified sample yourself
(worst/best/family/random). Accept, or tighten references/rubric.md and regrade.
Families with deliberate house patterns get family lanes — note them in tier-criteria.md.

## D. Tiers + adjudication
`assign_tiers.py --summary`. Sanity-check the distribution: T3 (full rewrite) should be
the exception; if it swallows a third of the library your criteria are too loose — T3 is
for STRUCTURAL rot, desc/body problems are T2's lane. Work QUEUE-adjudication.md; every
T4 goes to the library owner as a yes/no.

## E. Rewrites (proposal → verify → apply)
- T2 descriptions: `propose_t2.sh` (byte-identical-body contract) → `apply_t2.py`
  (mechanical verification) → spot-read a random sample for taste → `--apply` → commit.
- T3: one skill per proposal via `rewrite_harness.py`; technical skills drafted by the
  cheap model, client-facing written by the orchestrator; cross-model review before apply.
- Retirements: move to a retired dir with a ledger row. Never `rm`.

## F. Verify + close
- Structural lint clean; router/index regenerated zero-warning; parity checks green.
- Library-level deltas vs baseline (description chars, context cost).
- Behavioural spot-checks: fresh subagent gets a paraphrased trigger request; pass = it
  selects the skill and its first action matches the body. T3s run against the pre-revamp
  version as control — worse than the ancestor = revert.
- Idempotency: re-run A+B expecting zero proposed changes.
- Resume auto-committers only after everything above is green.

## R. Report + visual map (any time, read-only)
`ecosystem_map.py --root <skills-dir> --run-dir <dir> --out <dir> [--baseline <json>]`
writes three files. `--run-dir` is optional — without it the script scans the library
alone and skips the tier/grade sections.

- **`REPORT.html` — the primary output.** A single self-contained page (inline CSS, JS
  and SVG, zero network) built for a non-technical owner: hero health score, KPI tiles,
  an A→B before/after section, library composition, then deeper sections for request
  flow, families, description distribution, health issue cards with the exact fix
  command, and tier/grade charts. Light and dark aware, readable on a phone. Open it in
  a browser — this is the one to show someone.
- `REPORT.md` — the same stats as tables, for diffing and for agents.
- `ECOSYSTEM.md` — three mermaid diagrams (request flow, on-disk layout, skill anatomy).

**Before/after.** Every run writes a `baseline.json` snapshot into the output dir, so a
first run automatically becomes the baseline for the next one and the A→B section
appears from run two onward. Pass `--baseline <json>` to compare against a specific
snapshot instead; it accepts any subset of `desc_chars`, `skill_lines`,
`context_tokens`, `content_bytes`, `repo_bytes`, `junk_files`. With no baseline the
page shows current state and says to run again after a cleanup.

Run it before Phase A for a baseline and again after Phase F for the delta.
