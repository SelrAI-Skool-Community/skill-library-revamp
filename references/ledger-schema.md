# Ledger schema + scan-stage contracts

(Original build spec — the ledger JSON schema and per-scanner contracts.)

# Spec: Phase A scan scripts for the skill-library-revamp pipeline

Build 7 Python 3 scripts (stdlib only, no pip installs) in
`the skill's scripts/ directory`.
They are the deterministic scan layer of a 615-skill revamp pipeline and will later ship
as a reusable team skill, so: **zero hardcoded paths** — every script takes
`--root <skills-dir>` (default `~/.claude/skills`) and `--run-dir <ops-dir>`
(default `~/.claude/skill-revamp-runs/current`). All are read-only over the
skills tree; they write ONLY into `<run-dir>/ledger/` and `<run-dir>/ROLLUP.md`.

## Shared library: `ledger.py`
- `load(run_dir, skill)` / `save(run_dir, skill, obj)` — one JSON file per skill at
  `<run-dir>/ledger/<dirname>.json`, atomic write (tmp+rename).
- `all_skills(run_dir)` iterator.
- Schema (create with these keys; scripts fill their own sections and must not clobber
  other sections — read-modify-write):
```json
{"skill": "", "path": "", "sha_before": null, "sha_after": null,
 "flags": {}, "grade": null, "tier": null, "tier_source": null,
 "stages": {}, "verify": {}, "patterns_emitted": []}
```
- Every script, on completion, sets `stages.<stagename> = {"status":"done","ts":"<utc iso>"}`.

## 1. `inventory.py`
- Enumerate top-level dirs of `--root` that contain `SKILL.md`.
- EXCLUDE (record in `<run-dir>/ledger/_excluded.json` with reason, do not create ledgers):
  - the vendored/container packs listed in `<run-dir>/references/vendored-packs.txt`
    (one name per line — read it; if missing, error loudly)
  - symlinked entries (`os.path.islink`)
  - names starting with `_` or `.`
- For each included skill: seed the ledger file with skill, path, and
  `sha_before` = `git -C <repo> rev-parse HEAD:<relpath>/SKILL.md` (repo = walk up from root
  to find .git; if not a repo, null).
- Print a one-line summary: counts included/excluded.

## 2. `scan_frontmatter.py`
For each ledger skill, parse SKILL.md frontmatter (handle YAML block/folded multiline
values by folding indented continuation lines) and set flags:
- `frontmatter_keys` (list), `frontmatter_keys_nonstd` (anything outside
  {name, description, metadata, allowed-tools, license, version, tags, source, category,
  risk, date_added, requires, argument-hint, user_invocable, disable-model-invocation})
- `name_dirname_mismatch` (bool)
- `desc_chars` (int)
- `desc_workflow_summary` (bool) — heuristic: description contains 3+ sequential imperative
  workflow verbs ("then", "after that", numbered steps) OR matches
  r"This skill (owns|walks|runs|performs).*(then|→|->|step)" OR contains 2+ of
  ["first", "then", "finally"] — tune to catch descriptions that summarise HOW the skill
  works rather than WHEN to trigger it.

## 3. `detect_cooked_filler.py`
- Fingerprint corpus: the template text of whatever generator mass-produced the filler.
  Shipped fingerprints live in `references/cook-fingerprints/` and are seeded into the run
  dir by `setup_run_dir.sh`. If your library's filler came from a different generator,
  replace them: recover the generator from git history if it was deleted
  (`git log --oneline --diff-filter=D -- <path>`, then `git show <sha>^:<path>`), or paste
  two or three of the near-identical files themselves and replace the skill name with
  `{slug}`. Four files are required: SETUP-PROMPT.md, example.md, smoke.sh, changelog.md.
- For each skill's `SETUP-PROMPT.md`, `examples/*.md`, `CHANGELOG.md`, `scripts/smoke.sh`:
  compute a similarity score vs the matching template = line-overlap ratio after replacing
  the skill's name/slug with a placeholder in both texts (normalise whitespace).
- Flags: `cooked_setup_prompt` (float or null), `cooked_examples` (list of
  {file, sim}), `cooked_smoke` (float or null), `cooked_changelog` (float or null).

## 4. `metrics.py`
Flags per skill: `lines` (SKILL.md), `words`, `code_files` (count of .sh/.py/.js/.mjs/.ts
under the skill dir, excluding node_modules/.venv), `code_lines`,
`prohibition_density` (occurrences of NEVER/MUST/STOP/DO NOT/ALWAYS/CRITICAL/FORBIDDEN
as whole uppercase words per 100 SKILL.md lines, 2dp), `has_references_dir`, `has_scripts_dir`,
`brand_hardcode` (bool: SKILL.md bakes in brand values — any token listed in the optional
`<run-dir>/references/brand-tokens.txt`, or with no such file, any `#rrggbb` colour).

## 5. `overlap_candidates.py`
- Corpus per skill: name + description + H2 headings from SKILL.md.
- TF-IDF (implement with stdlib: math + collections) cosine similarity across all pairs.
- For pairs ≥ 0.55: append {peer, cos} to BOTH skills' `flags.overlap_candidates`.
- Also write `<run-dir>/OVERLAPS.md` — table of pairs sorted desc, for human review.

## 6. `assign_client_facing.py`
Set `flags.client_facing = true` when dirname matches any prefix in
`<run-dir>/references/client-facing-prefixes.txt` — else false. Seed it with the prefixes
of skills whose output a customer sees (e.g. carousel-, email-, content-, copywriting,
brandkit, workshop-, testimonial-, humanizer); the shipped template explains the format.

## 7. `rollup.py`
Read all ledgers → write `<run-dir>/ROLLUP.md`: counts table (total skills, per-flag
counts: nonstd keys, name mismatches, desc >500 / >700 / >1000, workflow-summary descs,
cooked ≥0.9 / 0.6-0.89, prohibition_density >0.8, overlap pairs ≥0.55, client-facing,
code totals) + top-20 worst lists per dimension. Plain markdown tables.

## Conventions
- Each script: `#!/usr/bin/env python3`, argparse, `main()`, exit 0 on success, non-zero
  with a clear message on any error. No silent excepts.
- Idempotent: re-running overwrites that script's own flags/stage only.
- Also create `<run-dir>/references/vendored-packs.txt` listing every third-party pack
  dropped into the library verbatim (plugin caches, marketplace packs, licensed drops).
  `setup_run_dir.sh` seeds a starter list from the template — extend it for your library.
- After building all scripts, RUN the full Phase A sequence (inventory → scans → rollup)
  against the real library and include the ROLLUP.md summary numbers in your final report.
- If any step finds nothing or fails, say so explicitly and state exactly what you inspected.
