#!/usr/bin/env bash
# propose_t3.sh — Phase E lane 2: full-rewrite proposals for technical T3 skills.
# One codex call per skill (these are structural rewrites, not batchable).
# Proposal-only: complete proposed skill dir written to <run-dir>/proposals/<skill>/.
# Client-facing T3s are EXCLUDED — the orchestrator writes those by hand.
set -uo pipefail

RUN_DIR="$HOME/.claude/skill-revamp-runs/current"
ROOT="$HOME/.claude/skills"
# Optional external authoring standard. The rewrite contract below is complete on its
# own; if you have a standard you want enforced (e.g. the superpowers plugin's
# writing-skills SKILL.md), pass --standard <path> and it is appended to the prompt.
STANDARD=""
MAX=0
SHARD=""   # "k/n": process skills where index % n == k (parallel workers)
CALL_TIMEOUT=720
while [ $# -gt 0 ]; do
  case "$1" in
    --run-dir) RUN_DIR="$2"; shift 2 ;;
    --root) ROOT="$2"; shift 2 ;;
    --standard) STANDARD="$2"; shift 2 ;;
    --max) MAX="$2"; shift 2 ;;
    --shard) SHARD="$2"; shift 2 ;;
    --timeout) CALL_TIMEOUT="$2"; shift 2 ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
LOG="$RUN_DIR/propose-t3${SHARD:+-shard${SHARD%%/*}}.log"

STANDARD_CLAUSE=""
if [ -n "$STANDARD" ]; then
  if [ ! -f "$STANDARD" ]; then
    echo "ERROR: --standard file not found: $STANDARD" >&2
    echo "Pass --standard <path to your authoring standard>, or omit it — the rewrite" >&2
    echo "contract in this script is self-contained and needs no external standard." >&2
    exit 2
  fi
  STANDARD_CLAUSE="Also conform to the authoring standard at $STANDARD — read it first.
"
fi

PENDING=$(python3 - "$RUN_DIR" "$SHARD" <<'PY'
import json, os, sys
run = sys.argv[1]
shard = sys.argv[2]
led = os.path.join(run, "ledger")
out = []
for f in sorted(os.listdir(led)):
    if not f.endswith(".json") or f.startswith("_"):
        continue
    d = json.load(open(os.path.join(led, f)))
    s = d["skill"]
    # connectors are the family-refactor lane, never individual T3 rewrites
    if s.endswith("-connector") or s.startswith("connect-"):
        continue
    if (d.get("tier") == "T3"
            and not d["flags"].get("client_facing")
            and not os.path.exists(os.path.join(run, "proposals", s, "SKILL.md"))):
        out.append(s)
if shard:
    k, n = (int(x) for x in shard.split("/"))
    out = [s for i, s in enumerate(out) if i % n == k]
print("\n".join(out))
PY
)
TOTAL=$(printf '%s\n' "$PENDING" | grep -c . || true)
echo "[propose_t3] pending technical T3: $TOTAL" | tee -a "$LOG"
[ "$TOTAL" -eq 0 ] && exit 0

N=0
printf '%s\n' "$PENDING" | while read -r SKILL; do
  [ -n "$SKILL" ] || continue
  N=$((N + 1))
  if [ "$MAX" -gt 0 ] && [ "$N" -gt "$MAX" ]; then break; fi
  NOTES=$(python3 -c "
import json
d = json.load(open('$RUN_DIR/ledger/$SKILL.json'))
g = d.get('grade') or {}
print(json.dumps({'dims': g.get('dims'), 'notes': g.get('notes')}))")
  mkdir -p "$RUN_DIR/proposals/$SKILL"

  PROMPT="Rewrite the Claude Code skill at $ROOT/$SKILL/. Read its SKILL.md fully (skim its
support files only enough to know what exists — do not read large reference files line
by line). Do not read any other documents.
Grade notes to address: $NOTES
${STANDARD_CLAUSE}The rewrite contract (complete on its own):
1. Frontmatter description: trigger conditions ONLY, third person, target <=350 chars,
   hard cap 500. 'Use when the user says X / situation Y' with real trigger phrases.
   NEVER summarise the skill's workflow in the description.
2. SKILL.md body target <500 words: overview (1-2 sentences), when to use / when NOT,
   the core recipe or quick-reference table, common mistakes. It is a MAP, not a warehouse.
3. Move any reference block over ~100 lines into references/<topic>.md files.
4. Keep EVERY fact: commands, paths, config keys, numbers, credential-record NAMES,
   gates, gotchas. Compression and re-forming only — never information loss. Unsure if
   something is load-bearing? Keep it.
5. Form: positive recipes/contracts for output shaping; prohibition lists ONLY for
   genuine discipline gates (money/publish/destructive). No 'You are an expert' priming,
   no nuance clauses ('unless it matters'), no repeated paragraphs, ONE good example.
6. Brand values (hex codes, fonts, prices) -> one pointer to the library's brand source-of-truth skill (if one exists),
   except inside runnable config examples.
7. Cross-reference other skills by NAME, never by filesystem path.
Write ONLY the files you change or add to $RUN_DIR/proposals/$SKILL/ (SKILL.md always;
new references/*.md as needed). Unchanged files are inherited at apply time — do NOT
copy them. To DELETE a live file, list its relative path in
$RUN_DIR/proposals/$SKILL/DELETIONS.txt (one per line). Do NOT touch $ROOT/$SKILL/.
If any file is unreadable, say so explicitly and state exactly what you inspected."

  # perl-alarm watchdog: macOS has no `timeout`; a single wedged call must not
  # stall the whole run (P-516: one call hung 3h40m overnight).
  perl -e 'alarm shift; exec @ARGV or die "exec: $!"' "$CALL_TIMEOUT" \
    codex exec -s workspace-write -c 'mcp_servers={}' "$PROMPT" < /dev/null >> "$LOG" 2>&1
  RC=$?
  if [ -s "$RUN_DIR/proposals/$SKILL/SKILL.md" ]; then
    echo "[propose_t3] $SKILL ok" | tee -a "$LOG"
  elif [ "$RC" -eq 142 ] || [ "$RC" -gt 128 ]; then
    echo "[propose_t3] $SKILL TIMEOUT (${CALL_TIMEOUT}s)" | tee -a "$LOG"
  else
    echo "[propose_t3] $SKILL FAILED-EMPTY" | tee -a "$LOG"
  fi
done
echo "[propose_t3] done" | tee -a "$LOG"
