# Skill-rot taxonomy — patterns found in real library revamps

Curated from run ledgers (grows with every library this skill is run on).
Format: pattern | detector | fix | automatable.

## Content rot

- **P-001 Template-generated evidence** — SETUP-PROMPT.md / examples / smoke.sh /
  CHANGELOG files mass-produced by a batch "improver" to game file-presence audit scores.
  Found 509 files across 132 of 611 skills (2026-07 run); smoke tests only asserted files
  exist. Detector: line-overlap similarity vs the generator's templates (≥0.90 = strip).
  Fix: delete; git history is the archive. Automatable: yes (`detect_cooked_filler.py` +
  `strip_cooked_filler.py`). Also delete the generator itself.
- **P-002 Description-as-workflow-summary** — frontmatter narrates the skill's process,
  so agents follow the description and skip the body. Detector: sequential-verb heuristic
  + grading dim 1. Fix: trigger-conditions-only rewrite (T2 lane). Automatable: propose
  via cheap model, verify body-byte-identical mechanically.
- **P-003 Prohibition walls in how-to skills** — NEVER/MUST/STOP stacks (one file pasted
  the same 32-word STOP paragraph 10×). Backfires on shaping problems. Fix: positive
  recipe/contract — "match the form to the failure" (the superpowers plugin's
  writing-skills states this rule, if you have it installed).
- **P-004 Brand/config facts duplicated** — hex codes, fonts, prices hardcoded in dozens
  of skills while a single source-of-truth skill exists. Detector: literal grep.
  Fix: pointer to the SSOT skill.
- **P-005 2023-era persona priming** — "You are an expert X." Delete; adds nothing on
  modern models.
- **P-006 Stale counts/refs** — "140+ skills", retired tool names, dead sibling routes.
  Fix: derive counts from generated indexes; lint for retired names.

## Structural rot

- **P-101 Identity theft / name drift** — frontmatter `name` ≠ dirname; worst case a
  container pack carrying a copy-pasted description of a different skill entirely.
  Found 15 in one library. Detector: trivial equality check — add it to your linter.
- **P-102 Mis-shelved containers** — a pack of 837 nested skills counted as one skill by
  the router. Fix: container-pack class in the index generator, not physical moves.
- **P-103 Multiple graveyards** — _archive/, _quarantine/, retired/ accumulating in
  parallel. Fix: one retired dir with one ledger README.
- **P-104 Fragile symlinks** — absolute-path symlinks to sibling repos break on moves.
- **P-105 Everything-inline** — 600+ line SKILL.md with unused references/ dir.

## Operator traps (the pipeline's own failure modes)

- **P-510 stdin-eating loops** — `codex exec` (any interactive CLI) inside `while read`
  consumes the pending list; run ends silently after one live batch. Fix: `< /dev/null`.
- **P-511 House doctrine misread as bloat** — families with deliberate shared boilerplate
  (connector packs with mandated comms rules) grade poorly but are correct; calibrate
  with the library's rule files before rewriting. Fix: family lanes.
- **P-512 Weak usage signals** — local-transcript invocation mining misses other
  machines, other agents, and Read-loading. Retire only on superseded-with-named-
  replacement, not on zero local use.
- **P-513 Positional batch filenames** — batch-0001.json collides on resume and silently
  skips ungraded work. Name outputs by content hash.
- **P-514 Cross-machine reverts** — a teammate's stale dirty copy auto-syncs over your
  fix minutes after you push. Re-verify samples next day; see sync-hazards.md.
- **P-515 Tier inflation** — "any 2 dims low → full rewrite" swallowed 350/611 skills;
  full rewrites are for structural rot only, desc/body lowness is the cheap lane.
- **P-516 Wedged model calls** — one hung rewrite call stalled a whole overnight run for
  3h40m. Every model call in a loop needs a watchdog (`perl -e 'alarm N; exec @ARGV'` on
  macOS) and `< /dev/null`.
- **P-517 Executable claims cut both ways** — an author's "tests pass" AND a reviewer's
  "tests fail" both need reproduction: one reviewer's failure was its own sandbox blocking
  a /tmp write. Read the reviewer's full log, not just its verdict; the apply gate runs
  every runnable artifact itself.
- **P-518 PII hides in inherited support files** — example walkthroughs carried real
  emails/phone numbers even when SKILL.md was clean. Scrub examples/ before any public ship.
- **P-519 Credential-doctrine gaps** — connectors persisted tokens to local 0600 files,
  "violating" a vault-first doctrine that assumed machines the end users don't have.
  Doctrine needs explicit lanes per machine class, not one absolute rule.
- **P-520 Cross-platform latent bugs** — install flows used Wayland clipboard commands
  (wl-paste) in macOS-targeted skills. Fix with command fallbacks, not assumptions.
- **P-521 Cheap-model rewrites fabricate currency** — invented package names, version
  bumps, tool renames, and "X is retired" claims, then asserted them in rewritten smoke
  tests so the fabrication became the gate. Rule: never change a version/tool fact without
  a dated source; smoke tests may only assert strings present in live or references.
  Adversarial cross-review by a different model catches this class reliably.
