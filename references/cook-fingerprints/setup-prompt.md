# SETUP-PROMPT.md

Paste into Claude Code to install + verify the `{slug}` skill.

```
Install + verify the {slug} skill on this machine.

1. Confirm the skill exists at ~/.claude/skills/{slug}/.
2. Run smoke: bash ~/.claude/skills/{slug}/scripts/smoke.sh. Expect SMOKE PASS.
3. Read SKILL.md to understand the trigger phrases and intended use cases.
4. Once verified, the skill is ready.
```

## What this skill does

See `SKILL.md` for the full operation map and reference content. Trigger phrases are listed in the frontmatter description.

## Failure modes

| Symptom | Fix |
|---|---|
| Smoke FAIL on SKILL.md frontmatter | Check `name:` and `description:` keys are present |
| Smoke FAIL on evidence layer | Re-run cook: this file, examples/<slug>-session.md, CHANGELOG.md all need to exist |
| Skill not triggering on user phrases | Description may need richer trigger-phrase list. Edit frontmatter via /skill-creator |

## Pairs with

- `/skill-audit` — audits this skill against Pass 1 rubric
- `/skill-creator` — refactor or extend the SKILL.md
