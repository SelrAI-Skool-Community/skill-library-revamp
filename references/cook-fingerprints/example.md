# Worked example: {slug} session

Three short transcripts showing the `{slug}` skill in use.

## Example 1: Standard invocation

```
User: {trigger_1}

Claude: [invokes /{slug}]
[reads SKILL.md, follows the documented workflow]
[returns the result the skill is designed to produce]

Done. Result delivered per the skill's operation map.
```

## Example 2: Edge case

```
User: {trigger_2}

Claude: [invokes /{slug}]
[detects the edge case in SKILL.md's failure-modes list]
[handles per documented fallback]

Note: this is the documented edge case. The skill handles it cleanly.
```

## Example 3: Pairs-with handoff

```
User: {trigger_3}

Claude: [invokes /{slug}]
[completes the {slug}-specific work]
[hands off to a pairs-with skill if one is listed in SKILL.md]

The pairs-with handoff is documented in SKILL.md "Pairs with" section.
```

## What skill-audit sees after the cook

- Evidence: 4 (smoke + examples + CHANGELOG = 4 points)
- Install story: 4-5 (SETUP-PROMPT.md present)
- Trigger fidelity: 4-5 (frontmatter description has "use when" + quoted phrases)
- Clarity: 4-5 (depends on SKILL.md body, unchanged by cook)
- Differentiation: 3 (default until the kit-index pipeline's yaml supplies cross-check)

Lifts the skill from sub-Promising to Promising 4.0-4.4 verdict.
