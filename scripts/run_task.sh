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
SAVE_TO="${2:-}"

if [ -z "$TASK_ID" ]; then
  printf 'Usage: scripts/run_task.sh <task_id> [result-dir]\n' >&2
  printf 'Example: scripts/run_task.sh task_053 results/task_053-dev\n' >&2
  exit 1
fi

if [ -z "$SAVE_TO" ]; then
  SAVE_TO="results/${TASK_ID}-dev"
fi

CMD=(
  "$UV_BIN" run a2a-hack run
  --personal-url http://localhost:9001
  --cs-url http://localhost:9002
  --tasks "$TASK_ID"
  --save-to "$SAVE_TO"
  --concurrency 1
  --auto-resume
)

printf 'Running single task from %s\n' "$HARNESS"
print_run "${CMD[@]}"
cd "$HARNESS"
"${CMD[@]}"
