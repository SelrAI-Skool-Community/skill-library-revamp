# Sync hazards checklist — before batch-editing any skill library in a synced repo

1. **Find every auto-committer.** launchd/cron/CI jobs that `git add -A && commit && push`
   on a timer will ship half-finished batches. Grep LaunchAgents/crontabs for the repo path.
2. **Pause them for the session.** Unload the LaunchAgent / comment the crontab line, or
   use whatever gate your repo already has. Resume only after commit + one observed clean
   cycle, and never on a dirty tree.
3. **Tag before the first write**: `git tag revamp-pre-<date> && git push origin <tag>`.
4. **Other machines revert you.** A teammate Mac with a stale dirty copy of a file will
   autostash-rebase and push its version over your fix minutes later. After batch applies,
   re-verify a sample the next day; fleet-wide fixes need the other machines clean or paused.
5. **History rewrites need a resurrection fence** before the force-push: block pushes
   >N commits ahead in the sync script, or a stale clone will rebase the entire old
   history onto the new one and push 30+ GiB back.
6. **Detached background jobs writing into the repo** (grading loops, proposal runs) must
   finish before any directory swap/move — mv breaks their absolute paths mid-write.
