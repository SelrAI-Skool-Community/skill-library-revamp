#!/usr/bin/env bash
# Seed a run dir with every reference the pipeline scripts read at runtime.
# Scripts resolve rubric/tier-criteria/cook-fingerprints from <run-dir>/references/,
# never from the skill, so this must run before inventory.py.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$SKILL_DIR/references"
RUN_DIR=""

usage() {
  cat <<EOF
usage: setup_run_dir.sh --run-dir <dir>

Creates <dir>/references/ and copies in rubric.md, grade-schema.json,
tier-criteria.md, codex-prompts.md, cook-fingerprints/, plus starting
vendored-packs.txt and client-facing-prefixes.txt (edit those two before scanning).
Refuses to touch a run dir that already holds a ledger.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --run-dir) RUN_DIR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$RUN_DIR" ]; then
  echo "ERROR: --run-dir <dir> is required" >&2
  usage >&2
  exit 2
fi

if [ -d "$RUN_DIR/ledger" ] && [ -n "$(ls -A "$RUN_DIR/ledger" 2>/dev/null)" ]; then
  cat >&2 <<EOF
ERROR: $RUN_DIR/ledger is not empty.
Re-seeding a used run dir merges two libraries into one ledger and re-runs stale
per-skill state. Use a fresh --run-dir for this library, or archive the old ledger
(mv "$RUN_DIR/ledger" "$RUN_DIR/ledger.bak") if you really mean to restart it.
EOF
  exit 1
fi

mkdir -p "$RUN_DIR/references"

for item in rubric.md grade-schema.json tier-criteria.md codex-prompts.md cook-fingerprints; do
  if [ ! -e "$SRC/$item" ]; then
    echo "ERROR: missing skill reference: $SRC/$item" >&2
    exit 1
  fi
  rm -rf "${RUN_DIR:?}/references/$item"
  cp -R "$SRC/$item" "$RUN_DIR/references/$item"
  echo "seeded   references/$item"
done

# The smoke fingerprint ships as .fingerprint (it contains {{slug}} placeholders and is
# not valid bash, which trips shell linters); the detector expects it named smoke.sh.
if [ -f "$RUN_DIR/references/cook-fingerprints/smoke.sh.fingerprint" ]; then
  mv "$RUN_DIR/references/cook-fingerprints/smoke.sh.fingerprint" "$RUN_DIR/references/cook-fingerprints/smoke.sh"
fi

for name in vendored-packs.txt client-facing-prefixes.txt; do
  dest="$RUN_DIR/references/$name"
  if [ -e "$dest" ]; then
    echo "kept     references/$name (already edited)"
  else
    cp "$SRC/templates/$name.example" "$dest"
    echo "seeded   references/$name (from template — edit for this library)"
  fi
done

cat <<EOF

Run dir ready: $RUN_DIR
Edit references/vendored-packs.txt and references/client-facing-prefixes.txt first.

Next:
  python3 $SKILL_DIR/scripts/inventory.py --root <skills-dir> --run-dir $RUN_DIR
EOF
