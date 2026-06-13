#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

load_dotenv "$ROOT"
require_google_api_key

HARNESS="$(harness_dir "$ROOT")"
UV_BIN="$(find_uv)"
SAVE_TO="${1:-results/feedback}"

CMD=(
  "$UV_BIN" run a2a-hack run
  --personal-url http://localhost:9001
  --cs-url http://localhost:9002
  --tasks feedback
  --save-to "$SAVE_TO"
  --auto-resume
)

printf 'Running feedback split from %s\n' "$HARNESS"
print_run "${CMD[@]}"
cd "$HARNESS"
"${CMD[@]}"

