# Content-grading rubric — skill-library-revamp

Six dimensions, scored 0–3. 0 = broken, 1 = poor, 2 = acceptable, 3 = exemplary.
For ANY score ≤1 the grader MUST include a one-line note AND a verbatim quote from the
skill as evidence. Grades are advisory input to tier assignment — deterministic flags
(ledger `flags`) always override where they conflict.

Grounded in the superpowers plugin's writing-skills, where that is the library's
authoring standard. Swap in your own standard and the dimensions still apply.

## 1. description_discipline
Does the frontmatter description state ONLY triggering conditions?
- 3: "Use when …" style, third person, concrete triggers/symptoms/user phrases, no
  workflow summary, ≤500 chars.
- 2: trigger-focused but wordy (500–1000 chars) or missing concrete phrases.
- 1: summarises the skill's process/workflow ("This skill owns… then… finally"), or
  first person, or vague ("For async testing").
- 0: missing, misleading, or describes a different skill.
Why workflow summaries score ≤1: agents follow the description instead of reading the
body — the body becomes documentation agents skip.

## 2. body_economy
- 3: technique/pattern skills <500 words; no repeated paragraphs; details pushed to
  `--help`/cross-refs; ONE excellent example; zero redundancy with cross-referenced skills.
- 2: mostly tight; some repeated boilerplate or a second redundant example.
- 1: >2× its type budget without reference-file justification; repeated paragraphs;
  multi-language example dilution; narrates what commands obviously do.
- 0: unreadably bloated (e.g. same paragraph pasted 5+ times).
Reference-type skills get a bigger budget ONLY via progressive disclosure (dim 3 covers it).

## 3. form_matches_failure
Per writing-skills "Match the Form to the Failure":
- 3: prohibitions/rationalization tables appear ONLY where the failure is discipline
  (agent knows the rule, skips it under pressure); output-shaping guidance is a positive
  recipe/contract; required elements are structural slots; conditions keyed to observable
  predicates; no nuance clauses ("unless it matters"), no exemption clauses.
- 2: right form overall, a few stray SHOUTY imperatives.
- 1: prohibition walls (NEVER/MUST/STOP stacks) in a how-to skill; nuance clauses;
  "You are an expert…" persona priming.
- 0: the skill is mostly prohibitions with no recipe at all.

## 4. progressive_disclosure
- 3: SKILL.md is the map — heavy reference (100+ lines) in separate files under
  references/, reusable code in scripts/, cross-refs by skill NAME (with REQUIRED marker
  when mandatory), never @-force-loads, never absolute paths to other skills.
- 2: minor misplacement (a 60-line reference table inline, or root-level REFERENCE.md).
- 1: 300+ lines of reference/code inlined in SKILL.md while references/ sits unused, or
  cross-refs by fragile path.
- 0: everything inline in a 600+ line SKILL.md with no separation at all.

## 5. evidence_reality
- 3: examples come from real use (concrete, adaptable, commented for WHY); every
  referenced file/script exists and is plausibly runnable; no narrative session
  storytelling ("In session 2025-10-03 we found…").
- 2: examples real but thin.
- 1: generic fill-in-the-blank templates presented as examples; smoke tests that only
  assert files exist.
- 0: fabricated/cooked evidence (AUTO-0 if the ledger's cooked_* flags are ≥0.9 —
  do not spend effort re-judging those files).

## 6. freshness
- 3: no stale counts/dates, no dead tool references, routing boundaries name skills that
  exist, no superseded-sibling drift.
- 2: minor staleness (an old date, a superseded flag name).
- 1: references retired tools/skills (Playwright MCP as primary, retired skill names,
  dead endpoints) or hardcoded facts that have a single source of truth elsewhere
  (brand hex/fonts belong to the library's brand source-of-truth skill).
- 0: the skill's core instructions no longer work as written.

## Complementary vocabulary (from mattpocock/skills `writing-for-agents`)

Useful lenses when grading or rewriting — same trade-offs, sharper names:
- **Context load vs cognitive load** — every always-loaded line (description, CLAUDE.md/AGENTS.md
  entry) spends the agent's window; every user-invoked skill spends the human's memory of
  what exists. Most split/inline/point decisions are this one trade in different places.
  These rules apply to ANY document an agent consumes, not just skills.
- **Leading words** — replace a paragraph of restatement with one compact concept the model
  already knows ("tracer bullet", "tight"). Hunt restatements a single word can retire.
- **Failure modes** — *sediment* (dead accretions nobody prunes), *sprawl* (content that
  outgrew its home), *no-op* (a sentence whose deletion changes nothing — delete it),
  *premature completion* (weak done-conditions let the agent stop early). Dims 2 and 5
  are largely these, named.
