# Cheap-model prompt templates — skill-library-revamp

The grading and rewrite passes are bulk work: hundreds of near-identical judgements. Run
them on the cheapest capable model you have. The shipped scripts drive the Codex CLI
(`codex exec`); the prompts themselves are model-agnostic.

## No Codex? Use subagents

Every template below works as a Claude subagent task. Dispatch one subagent per batch
with the prompt text as its instruction, and tell it to write its JSON or file output to
the exact path the template names — the pipeline scripts read the path, not the model.
Batch sizes stay the same (grading 10 skills per task, T2 descriptions 15, T3 rewrites
one). `grade_batch.sh` and `propose_t2.sh` / `propose_t3.sh` shell out to Codex, so
without it you drive Phase C and Phase E by hand: dispatch the batch, save the output,
then let the apply scripts (`apply_t2.py`, `apply_t3.py`, `rewrite_harness.py`) do the
rest unchanged.

## Rules for every Codex invocation in this pipeline
- `codex exec -s <read-only|workspace-write> -c 'mcp_servers={}'` — the MCP override is
  mandatory (a dead-auth MCP server kills codex exec silently).
- `< /dev/null` whenever the call sits inside a shell loop reading stdin.
- Every prompt ends with: "If you find nothing, say so explicitly and state exactly what
  you inspected."
- Reference rubric/schema/spec files by absolute path; never inline them.
- Output contract: files at stated paths or pure JSON — never prose mixed with data.

## T2 description rewrite (proposal mode, 15 skills per call)

```
Rewrite ONLY the frontmatter `description:` of these skills. For each, read the full
SKILL.md first. Rules (from <run-dir>/references/rubric.md dim 1):
- Trigger conditions ONLY: "Use when the user says X / situation Y". Third person.
- NEVER summarise the skill's workflow or process — no "this skill owns... then...".
- Keep concrete user phrases and routing boundaries ("Route X to skill-y") — boundaries
  are trigger information, keep them short.
- Target <=350 chars, hard cap 500. Keep the skill's genuine scope; cut biography,
  methodology, deliverables lists, marketing.
Write one file per skill: <run-dir>/proposals/<skill>/SKILL.md — the COMPLETE file with
only the description changed (byte-identical body).
Exemplar of the house style (from a prior accepted rewrite):
  "Edit recorded footage through a conversational, transcript-led workflow. Use when the
   user says 'edit this video with me', 'cut the filler from my recording', 'color grade
   this interview'. Route direct FFmpeg recipes to video-editor, picture-led selects to
   vision-roughcut, music-led editing to music-to-video."
Skills: <list of paths>
If a file is unreadable, skip it and say exactly which and why.
```

## T3 technical rewrite (proposal mode, 1 skill per call)

```
Rewrite this skill to the authoring standard at <abs path to your standard, e.g. the
superpowers plugin's writing-skills SKILL.md — omit this clause if you have none>
and the rubric at <run-dir>/references/rubric.md. Read both, then the entire skill dir.
Grade notes to address: <paste grade.notes>.
Constraints:
- Keep every fact, command, path, and hard-won gotcha — this is compression and
  re-forming, never information loss. Move heavy reference (100+ lines) to references/,
  reusable code stays in scripts/.
- Form matches failure: recipes/contracts for shaping, prohibitions only for discipline.
- Description: trigger-conditions only, <=350 chars.
- Brand facts (hex codes, fonts) become a pointer to the library's brand source-of-truth skill (if one exists).
Write the complete proposed skill dir to <run-dir>/proposals/<skill>/ (every file, even
unchanged ones). Do not touch the live skill.
```
