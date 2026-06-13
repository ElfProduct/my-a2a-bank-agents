#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

load_dotenv "$ROOT"
require_google_api_key

HARNESS="$(harness_dir "$ROOT")"
UV_BIN="$(find_uv)"
TASKS="${1:-task_006,task_009,task_053}"
SAVE_TO="${2:-results/train-small}"

CMD=(
  "$UV_BIN" run a2a-hack run
  --personal-url http://localhost:9001
  --cs-url http://localhost:9002
  --tasks "$TASKS"
  --save-to "$SAVE_TO"
  --auto-resume
)

printf 'Running small train sample from %s\n' "$HARNESS"
print_run "${CMD[@]}"
cd "$HARNESS"
"${CMD[@]}"

