# Setup prompt

Paste this whole block into Claude Code. It installs the skill, runs the audit, and
explains the results back to you. Nothing in your skill library gets changed.

```
Install and run the skill-library-revamp skill for me.

1. Clone it into my skills directory:
   git clone https://github.com/Mr-heka/skill-library-revamp.git ~/.claude/skills/skill-library-revamp
   If ~/.claude/skills doesn't exist on this machine, find where Claude Code keeps skills
   here and clone it there instead. If a skill-library-revamp folder is already there,
   rename it to skill-library-revamp.backup first, then clone.

2. Run the audit:
   bash ~/.claude/skills/skill-library-revamp/scripts/quickstart.sh
   (adjust the path if you cloned somewhere else). It only reads my skills — it changes
   nothing. If it stops with an error, read the error, fix the cause, and run it again.

3. Open the REPORT.html it prints at the end, then walk me through my library's health in
   plain English — worst problems first. For each one: what it is, why it costs me
   something, and what the fix would take. No jargon, and don't change any files yet.
```

## What happens next

The report writes a snapshot of today's numbers. Once you clean things up and run the
audit again, the report grows a before/after section showing exactly what moved.

To go past the read-only audit and actually revamp the library, ask Claude to read
`references/runbook.md` in the skill and work the phases in order.
