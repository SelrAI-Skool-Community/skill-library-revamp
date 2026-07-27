#!/usr/bin/env bash
# quickstart.sh — one command, whole read-only audit, visual report opened.
#
# Seeds a dated run dir, runs every Phase A scanner, then builds REPORT.html and
# opens it. Nothing in the skill library is modified: every step here only reads
# the library and writes into the run dir.
#
# usage: quickstart.sh [--root <skills-dir>] [--run-dir <dir>] [--no-open]
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="$SKILL_DIR/scripts"
ROOT="$HOME/.claude/skills"
RUN_DIR=""
OPEN_REPORT=1

usage() {
  cat <<EOF
usage: quickstart.sh [--root <skills-dir>] [--run-dir <dir>] [--no-open]

  --root      skills directory to audit   (default: \$HOME/.claude/skills)
  --run-dir   where results are written   (default: <skill>/.runs/<today>)
  --no-open   write the report, do not open a browser

Read-only: your skills are never modified.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="${2:-}"; shift 2 ;;
    --run-dir) RUN_DIR="${2:-}"; shift 2 ;;
    --no-open) OPEN_REPORT=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

die() { echo "" >&2; echo "ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------- preflight
command -v python3 >/dev/null 2>&1 || die "python3 is not installed.
The scanners are plain Python 3 (no packages needed). Install it, then re-run:
  macOS   : xcode-select --install     (or: brew install python)
  Ubuntu  : sudo apt install python3
  Windows : install Python 3 from python.org, then run this under WSL or Git Bash"

PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) \
  || die "python3 is present but will not run. Try: python3 --version"
case "$PYV" in
  3.[0-8]) die "Python $PYV is too old — these scripts need Python 3.9 or newer." ;;
esac

[ -d "$SCRIPTS" ] || die "cannot find the skill's scripts/ dir at $SCRIPTS.
Run this script from inside the cloned skill, e.g.
  bash ~/.claude/skills/skill-library-revamp/scripts/quickstart.sh"

if [ ! -d "$ROOT" ]; then
  die "no skills directory at: $ROOT
Point at the right one with --root, e.g.
  bash $SCRIPTS/quickstart.sh --root /path/to/your/skills"
fi

SKILL_COUNT=$(find "$ROOT" -mindepth 2 -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')
if [ "$SKILL_COUNT" -eq 0 ]; then
  die "no skills found in $ROOT (looked for */SKILL.md).
Point at the directory that holds your skill folders with --root."
fi

if [ -z "$RUN_DIR" ]; then
  RUN_DIR="$SKILL_DIR/.runs/$(date +%Y-%m-%d)"
fi
mkdir -p "$RUN_DIR" || die "cannot create the run dir: $RUN_DIR"

echo "Skill library : $ROOT ($SKILL_COUNT skills)"
echo "Results       : $RUN_DIR"
echo ""

step() { echo "-> $1"; }

run_py() {
  local script="$1"; shift
  step "$script"
  python3 "$SCRIPTS/$script" "$@" || die "$script failed (see the message above).
Everything written so far is in $RUN_DIR — fix the cause and re-run quickstart."
}

# ---------------------------------------------------------------- phase 0
if [ -d "$RUN_DIR/ledger" ] && [ -n "$(ls -A "$RUN_DIR/ledger" 2>/dev/null)" ]; then
  echo "-> reusing today's run dir (ledger already seeded)"
else
  step "setup_run_dir.sh"
  bash "$SCRIPTS/setup_run_dir.sh" --run-dir "$RUN_DIR" >/dev/null \
    || die "setup_run_dir.sh failed. Run it directly to see why:
  bash $SCRIPTS/setup_run_dir.sh --run-dir $RUN_DIR"
fi

# ---------------------------------------------------------------- phase A
run_py inventory.py --root "$ROOT" --run-dir "$RUN_DIR"
run_py scan_frontmatter.py --run-dir "$RUN_DIR"
run_py detect_cooked_filler.py --run-dir "$RUN_DIR"
run_py metrics.py --run-dir "$RUN_DIR"
run_py overlap_candidates.py --run-dir "$RUN_DIR"
run_py assign_client_facing.py --run-dir "$RUN_DIR"
run_py rollup.py --run-dir "$RUN_DIR"

# ---------------------------------------------------------------- phase R
run_py ecosystem_map.py --root "$ROOT" --run-dir "$RUN_DIR" --out "$RUN_DIR"

REPORT="$RUN_DIR/REPORT.html"
[ -s "$REPORT" ] || die "ecosystem_map.py finished but wrote no REPORT.html in $RUN_DIR."

echo ""
echo "Done. Reports in $RUN_DIR"
echo "  REPORT.html   visual health dashboard   <- start here"
echo "  REPORT.md     the same numbers as tables"
echo "  ECOSYSTEM.md  diagrams of how the library fits together"
echo "  ROLLUP.md     raw per-flag counts and worst-offender lists"
echo ""

if [ -s "$RUN_DIR/baseline.json" ]; then
  echo "Snapshot saved as baseline.json — clean something up, run this again, and the"
  echo "report grows a before/after section on its own."
  echo ""
fi

if [ "$OPEN_REPORT" -eq 1 ] && command -v open >/dev/null 2>&1; then
  open "$REPORT" && exit 0
fi
if [ "$OPEN_REPORT" -eq 1 ] && command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$REPORT" >/dev/null 2>&1 && exit 0
fi
echo "Open this file in a browser:"
echo "  $REPORT"
