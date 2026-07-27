# Tier criteria — skill-library-revamp

Applied by `assign_tiers.py` over ledger flags + grades. Deterministic flags beat grades.
Every T3/T4, every boundary case (within 1 point of a tier line), and every skill with
overlap_candidates goes to the orchestrator adjudication queue — tiers are proposals,
`tier_source: auto` until a human/orchestrator confirms or overrides.

IMPORTANT evidence discount: if `stages.strip_filler.removed` is non-empty, the cooked
files are already gone — ignore `evidence_reality` ≤ grades caused solely by cooked flags
(grader was told to auto-0 on the flag, which describes the pre-strip state).

| Tier | Criteria (first match wins, evaluated top-down) | Action |
|---|---|---|
| T0 skip | excluded at inventory (vendored pack, symlink, retired) | none |
| T4 retire/merge | confirmed semantic twin (overlap ≥0.55 AND adjudicator confirms same job), OR superseded per freshness note naming a live replacement | skill-hygiene git-mv + ledger; merges fold unique content into survivor. NEVER auto — always adjudicated, batch to the library owner |
| T3 full rewrite | a STRUCTURAL dim (form_matches_failure or progressive_disclosure) ≤1 AND ≥2 core dims ≤1, OR prohibition_density >0.8 AND form_matches_failure ≤1, OR lines >600 without reference-file structure (has_references_dir=false). Recalibrated 2026-07-26: desc+body-only lowness routes to T2 | full rewrite per writing-skills; client_facing → orchestrator writes; technical → Codex proposal + orchestrator review |
| T2 desc+trim | desc_chars >700, OR desc_workflow_summary, OR description_discipline ≤1, OR any number of non-structural dims ≤1 | Codex-drafted description rewrite + targeted trim; batch diff review before apply |
| T1 mechanical-only | everything else (all dims ≥2, desc ≤700) | Phase B fixes only — done |

Escalation is monotonic: a T2 whose rewrite reveals rot is re-tiered T3 in the ledger
with a note; never silently expanded in place.

## Family lanes (adjudicated 2026-07-26 calibration)

- **Connector family (49 skills):** graded scores are advisory only. These follow the
  deliberate house pattern in `the library's house connector doctrine (rules file)` (Claude drives the browser,
  plain-English comms rules, phase structure). Rewrite as a FAMILY: extract the shared
  boilerplate ("Communication rules for Phase 1" etc.) into one shared reference under
  `.claude/skills/connector-scaffold/references/`, then trim each connector to its
  service-specific delta + a REQUIRED pointer. Do not delete the doctrine.
- Calibration result: Codex grades accepted (worst observed drift: form_matches_failure
  -1 on connectors, explained above). No rubric regrade.
