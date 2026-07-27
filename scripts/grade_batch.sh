#!/usr/bin/env bash
# grade_batch.sh — Phase C: grade every ledgered skill with Codex (gpt-5.6-sol).
#
# Shards ungraded skills into batches of $BATCH (default 10) and runs one
# `codex exec` per batch. Each result is validated as JSON and written into
# ledger/<skill>.json under "grade". Resumable: skills with an existing grade
# are skipped, so re-running continues where it stopped.
#
# Usage: grade_batch.sh [--run-dir DIR] [--root DIR] [--batch N] [--max-batches N]
set -uo pipefail

RUN_DIR="$HOME/.claude/skill-revamp-runs/current"
ROOT="$HOME/.claude/skills"
BATCH=10
MAX_BATCHES=0   # 0 = no limit
while [ $# -gt 0 ]; do
  case "$1" in
    --run-dir) RUN_DIR="$2"; shift 2 ;;
    --root) ROOT="$2"; shift 2 ;;
    --batch) BATCH="$2"; shift 2 ;;
    --max-batches) MAX_BATCHES="$2"; shift 2 ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done

RUBRIC="$RUN_DIR/references/rubric.md"
SCHEMA="$RUN_DIR/references/grade-schema.json"
LOG="$RUN_DIR/grade-batch.log"
[ -f "$RUBRIC" ] || { echo "missing $RUBRIC" >&2; exit 1; }
[ -f "$SCHEMA" ] || { echo "missing $SCHEMA" >&2; exit 1; }

# Ungraded skills, stable order.
PENDING=$(python3 - "$RUN_DIR" <<'PY'
import json, os, sys
run = sys.argv[1]
led = os.path.join(run, "ledger")
out = []
for f in sorted(os.listdir(led)):
    if not f.endswith(".json") or f.startswith("_"):
        continue
    d = json.load(open(os.path.join(led, f)))
    if not d.get("grade"):
        out.append(d["skill"])
print("\n".join(out))
PY
)
TOTAL=$(printf '%s\n' "$PENDING" | grep -c . || true)
echo "[grade_batch] pending: $TOTAL skills, batch size $BATCH" | tee -a "$LOG"
[ "$TOTAL" -eq 0 ] && exit 0

BATCH_NUM=0
printf '%s\n' "$PENDING" | xargs -n "$BATCH" | while read -r -a GROUP; do
  BATCH_NUM=$((BATCH_NUM + 1))
  if [ "$MAX_BATCHES" -gt 0 ] && [ "$BATCH_NUM" -gt "$MAX_BATCHES" ]; then break; fi
  LIST=""
  for s in "${GROUP[@]}"; do LIST+="- $s: $ROOT/$s/SKILL.md (flags: $RUN_DIR/ledger/$s.json)"$'\n'; done
  # Name output by content, not position: positional numbering collides with prior
  # runs' files on resume, silently skipping still-ungraded batches.
  GROUP_HASH=$(printf '%s' "${GROUP[*]}" | shasum | cut -c1-10)
  OUT="$RUN_DIR/grades/batch-$GROUP_HASH.json"
  mkdir -p "$RUN_DIR/grades"
  [ -s "$OUT" ] && continue

  PROMPT="Grade these ${#GROUP[@]} Claude Code skills against the rubric at $RUBRIC (read it first).
For each skill read the full SKILL.md at the listed path, plus the 'flags' object in its ledger JSON.
Apply the auto-0 rule for evidence_reality when cooked_* flags are >=0.9.
Write ONLY a JSON array (no prose, no markdown fences) to the file $OUT
matching the schema at $SCHEMA: one object per skill; include a one-line note for every
dim scored <=1 and a verbatim worst_quote.
Skills:
$LIST
If a file is unreadable, still emit the skill's object with all dims 0 and a note saying
exactly what you inspected and what failed."

  # </dev/null: codex must not inherit the while-loop's piped stdin or it consumes
  # the remaining skill list and the loop ends after one live batch.
  codex exec -s workspace-write -c 'mcp_servers={}' "$PROMPT" < /dev/null >> "$LOG" 2>&1
  if [ -s "$OUT" ] && python3 -c "import json,sys; json.load(open('$OUT'))" 2>/dev/null; then
    python3 - "$RUN_DIR" "$OUT" <<'PY'
import json, os, sys
run, outfile = sys.argv[1], sys.argv[2]
grades = json.load(open(outfile))
for g in grades:
    lp = os.path.join(run, "ledger", g["skill"] + ".json")
    if not os.path.exists(lp):
        continue
    d = json.load(open(lp))
    d["grade"] = {"model": "gpt-5.6-sol", "run": os.path.basename(outfile),
                  "dims": g["dims"], "notes": g.get("notes", {}),
                  "worst_quote": g.get("worst_quote", "")}
    d.setdefault("stages", {})["grade"] = {"status": "done"}
    tmp = lp + ".tmp"
    json.dump(d, open(tmp, "w"), indent=1)
    os.replace(tmp, lp)
print(f"applied {len(grades)} grades from {os.path.basename(outfile)}")
PY
    echo "[grade_batch] batch $BATCH_NUM ok (${#GROUP[@]} skills)" | tee -a "$LOG"
  else
    echo "[grade_batch] batch $BATCH_NUM FAILED (no valid JSON at $OUT)" | tee -a "$LOG"
  fi
done
echo "[grade_batch] done" | tee -a "$LOG"
