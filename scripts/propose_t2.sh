#!/usr/bin/env bash
# propose_t2.sh — Phase E lane 1: draft description rewrites for every T2 skill.
#
# Proposal-only: Codex writes a complete SKILL.md per skill into
# <run-dir>/proposals/<skill>/SKILL.md with ONLY the frontmatter description changed
# (byte-identical body — enforced later by apply_t2.py, which refuses anything else).
# Resumable: skills with an existing proposal file are skipped.
set -uo pipefail

RUN_DIR="$HOME/.claude/skill-revamp-runs/current"
ROOT="$HOME/.claude/skills"
BATCH=15
MAX_BATCHES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --run-dir) RUN_DIR="$2"; shift 2 ;;
    --root) ROOT="$2"; shift 2 ;;
    --batch) BATCH="$2"; shift 2 ;;
    --max-batches) MAX_BATCHES="$2"; shift 2 ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
LOG="$RUN_DIR/propose-t2.log"

PENDING=$(python3 - "$RUN_DIR" <<'PY'
import json, os, sys
run = sys.argv[1]
led = os.path.join(run, "ledger")
out = []
for f in sorted(os.listdir(led)):
    if not f.endswith(".json") or f.startswith("_"):
        continue
    d = json.load(open(os.path.join(led, f)))
    if d.get("tier") == "T2" and not os.path.exists(
        os.path.join(run, "proposals", d["skill"], "SKILL.md")
    ):
        out.append(d["skill"])
print("\n".join(out))
PY
)
TOTAL=$(printf '%s\n' "$PENDING" | grep -c . || true)
echo "[propose_t2] pending: $TOTAL skills, batch $BATCH" | tee -a "$LOG"
[ "$TOTAL" -eq 0 ] && exit 0

BATCH_NUM=0
printf '%s\n' "$PENDING" | xargs -n "$BATCH" | while read -r -a GROUP; do
  BATCH_NUM=$((BATCH_NUM + 1))
  if [ "$MAX_BATCHES" -gt 0 ] && [ "$BATCH_NUM" -gt "$MAX_BATCHES" ]; then break; fi
  LIST=""
  for s in "${GROUP[@]}"; do
    mkdir -p "$RUN_DIR/proposals/$s"
    LIST+="- $s: read $ROOT/$s/SKILL.md ; write $RUN_DIR/proposals/$s/SKILL.md"$'\n'
  done

  PROMPT="Rewrite ONLY the frontmatter \`description:\` of these ${#GROUP[@]} skills. For each,
read the full SKILL.md at the listed path first, then write the COMPLETE file to the
listed output path with ONLY the description changed — the body and every other
frontmatter key must be byte-identical (an automated check rejects any other change).
Description rules (from $RUN_DIR/references/rubric.md dim 1):
- Trigger conditions ONLY, third person: 'Use when the user says X / situation Y', with
  the skill's real concrete trigger phrases. NEVER summarise the workflow or process.
- Keep short routing boundaries ('Route X to skill-y') — they are trigger information.
- Single-line flat YAML string. Target <=350 chars, hard cap 500. Cut biography,
  methodology lists, deliverables, marketing language.
House-style exemplar:
  'Edit recorded footage through a conversational, transcript-led workflow. Use when the
   user says \"edit this video with me\", \"cut the filler from my recording\", \"color grade
   this interview\". Route direct FFmpeg recipes to video-editor, music-led editing to
   music-to-video.'
Skills:
$LIST
If a file is unreadable, skip it and state exactly which and why."

  codex exec -s workspace-write -c 'mcp_servers={}' "$PROMPT" < /dev/null >> "$LOG" 2>&1
  WROTE=0
  for s in "${GROUP[@]}"; do [ -s "$RUN_DIR/proposals/$s/SKILL.md" ] && WROTE=$((WROTE+1)); done
  echo "[propose_t2] batch $BATCH_NUM: $WROTE/${#GROUP[@]} proposals written" | tee -a "$LOG"
done
echo "[propose_t2] done" | tee -a "$LOG"
