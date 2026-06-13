#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULT_DIR="${1:-$ROOT/../a2a-hackathon/results/feedback}"

python3 "$ROOT/scripts/summarize_results.py" "$RESULT_DIR"
