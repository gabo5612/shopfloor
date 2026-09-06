#!/usr/bin/env bash
# The real evaluation gate. It runs HERE, not in GitHub CI, because the local
# model is the system: measuring shopfloor on a hosted runner without Qwen
# would gate something that never ships.
#
#   ./scripts/eval.sh                 # gate against eval/baseline.json
#   ./scripts/eval.sh --rebaseline    # accept the current run as the new floor
#
# Exit codes come from `groundcheck gate`: 0 pass · 1 regression · 2 could not
# compare (golden set moved, or k changed).
set -euo pipefail

GROUNDCHECK_DIR="${GROUNDCHECK_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../groundcheck" && pwd)}"
SUITE="${SUITE:-suites/shopfloor-v2.yaml}"
API="${API:-http://127.0.0.1:8080/api/ask}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASELINE="$HERE/eval/baseline.json"

command -v curl >/dev/null || { echo "curl no está"; exit 2; }
[ -d "$GROUNDCHECK_DIR" ] || { echo "no encuentro groundcheck en $GROUNDCHECK_DIR"; exit 2; }

if ! curl -fsS -m 5 -o /dev/null "${API%/api/ask}/api/docs"; then
  echo "shopfloor no responde en $API"
  echo "  docker-compose up -d"
  echo "  .venv/bin/python -m uvicorn shopfloor.api.main:app --host 0.0.0.0 --port 8080"
  exit 2
fi

cd "$GROUNDCHECK_DIR"
GC=".venv/bin/groundcheck"; [ -x "$GC" ] || GC="groundcheck"

# --out runs/ is gitignored in groundcheck on purpose: what gets versioned is
# the baseline, not every ad-hoc run.
"$GC" run --suite "$SUITE" --system "$API" --mapping adapters/shopfloor.yaml --out runs/ --quiet
RUN="$(ls -t runs/*.json | head -1)"

if [ "${1:-}" = "--rebaseline" ]; then
  # Deliberate act, never automatic: a baseline that moves on its own measures
  # nothing. The diff prints first so whoever runs this sees what they accept.
  "$GC" diff "$BASELINE" "$RUN" || true
  "$GC" report "$RUN" --json > "$BASELINE"
  echo "baseline reescrito: $BASELINE"
  exit 0
fi

"$GC" report "$RUN"
"$GC" gate "$RUN" --against "$BASELINE"
