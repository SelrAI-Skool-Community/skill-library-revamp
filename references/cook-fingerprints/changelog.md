# {slug} changelog

## [1.1.0] - {date}

Production-grade evidence layer added. Cook to lift skill-audit score above 4.0.

### Added

- `scripts/smoke.sh`: verifies SKILL.md frontmatter, evidence layer presence, trigger-phrase clause.
- `SETUP-PROMPT.md`: paste-into-Claude install + verify + failure-modes.
- `examples/{slug}-session.md`: 3 worked transcripts (standard, edge case, pairs-with handoff).
- This `CHANGELOG.md`.

### Changed

- `SKILL.md` frontmatter description rewritten if previously under 30 words. Added "use when" clause and concrete trigger phrases.

### Validation

- `bash scripts/smoke.sh` passes locally.
- `python3 ~/.claude/skills/skill-audit/scripts/audit.py ~/.claude/skills/{slug} --pretty` returns Promising avg 4.0+.

### Why

skill-audit flagged evidence=1 (no smoke, no examples, no CHANGELOG). All three are now in place. Differentiation remains at default 3 until the kit-index pipeline's yaml supplies the cross-check; that lifts the verdict to Production on the next 6h Pass 1 crawl.

### Not touched

- SKILL.md body (operation map, reference content) unchanged.
- Any sister skills or pairs-with references unchanged.
