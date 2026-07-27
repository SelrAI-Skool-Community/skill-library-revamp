# skill-library-revamp

Audit and revamp any Claude Code skill library. Point it at your skills folder and it
produces a visual health report — what's bloated, what's duplicated, what's fake, what
it's costing you in context — then gives you a phased pipeline to fix it, with
before/after numbers once you do.

Read-only by default. The audit never touches your skills.

## Who it's for

Anyone whose skills folder grew faster than they could maintain it. Ten skills or six
hundred. Especially useful if you inherited a library, mass-generated skills with an
older model, or have no idea which of your skills still earn their place.

## Install and run

Paste this into Claude Code:

```
Install and run the skill-library-revamp skill for me.

1. Clone it into my skills directory:
   git clone https://github.com/lukeselr/skill-library-revamp.git ~/.claude/skills/skill-library-revamp
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

Prefer the terminal? `bash scripts/quickstart.sh` does the same thing.
Add `--root /path/to/skills` if your library lives somewhere unusual.

## What you get

- **A visual health report** — `REPORT.html`, one self-contained page, no network calls.
  Health score, KPI tiles, library composition, request flow, per-issue cards with the
  exact command that fixes each one. Readable on a phone, light and dark aware.
- **Junk detection** — finds template-generated "evidence" files (fake examples, fake
  smoke tests, fake changelogs) that exist only to game a file-presence audit, by
  fingerprint-matching them against the generator that produced them.
- **Description tuning** — flags frontmatter that narrates a workflow instead of naming
  triggers, which is why the right skill doesn't fire when you need it, plus every
  description long enough to be eating context in every single session.
- **Duplicate and overlap detection** — TF-IDF similarity across the whole library,
  ranked pairs, so near-identical skills stop competing with each other.
- **21 documented rot patterns** — a taxonomy from real library revamps: what breaks,
  how to detect it, how to fix it, and whether the fix can be automated.
- **Before/after** — every run snapshots the numbers, so the next run shows the delta.
- **A full revamp pipeline** — scan, mechanical fixes, grading, tiering, rewrite,
  verify. Resumable per-skill ledger, dry-run before every write, git-revertable.

## Requirements

- Claude Code
- python3 (3.9+, standard library only — nothing to `pip install`)
- git

macOS and Linux. On Windows, run it under WSL or Git Bash.

## What's in here

| Path | What |
|---|---|
| `SKILL.md` | the skill itself — phases, gotchas, where scripts read from |
| `scripts/quickstart.sh` | one command: scan the library and open the report |
| `scripts/` | the pipeline — scanners, fixers, tiering, rewrite harness |
| `references/runbook.md` | the operator sequence for a full revamp |
| `references/patterns.md` | the rot taxonomy |
| `references/rubric.md` | the 6-dimension grading rubric |

## Licence

MIT. See LICENSE.
