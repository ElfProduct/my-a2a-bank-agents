#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

load_dotenv "$ROOT"
require_google_api_key

HARNESS="$(harness_dir "$ROOT")"
UV_BIN="$(find_uv)"
TASK_ID="${1:-}"

CMD=("$UV_BIN" run a2a-hack smoke --personal-url http://localhost:9001 --cs-url http://localhost:9002)
if [ -n "$TASK_ID" ]; then
  CMD+=(--task-id "$TASK_ID")
fi

printf 'Running smoke test from %s\n' "$HARNESS"
print_run "${CMD[@]}"
cd "$HARNESS"
"${CMD[@]}"

