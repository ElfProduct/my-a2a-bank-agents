#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

HARNESS="$(harness_dir "$ROOT")"
UV_BIN="$(find_uv)"
RESULT_DIR="${1:-}"

if [ -z "$RESULT_DIR" ]; then
  printf 'Usage: scripts/view_results.sh <result-dir>\n' >&2
  printf 'Example: scripts/view_results.sh results/feedback\n' >&2
  exit 1
fi

CMD=("$UV_BIN" run tau2 view "$RESULT_DIR")

printf 'Opening tau2 result viewer from %s\n' "$HARNESS"
print_run "${CMD[@]}"
cd "$HARNESS"
"${CMD[@]}"

