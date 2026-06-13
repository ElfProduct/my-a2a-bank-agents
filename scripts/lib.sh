#!/usr/bin/env bash

set -euo pipefail

repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

load_dotenv() {
  local root="$1"
  if [ -f "$root/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$root/.env"
    set +a
  fi
}

find_uv() {
  if [ -n "${UV:-}" ] && command -v "$UV" >/dev/null 2>&1; then
    printf '%s\n' "$UV"
    return
  fi
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return
  fi
  if [ -x "$HOME/.local/bin/uv" ]; then
    printf '%s\n' "$HOME/.local/bin/uv"
    return
  fi
  printf 'uv not found. Install uv or set UV=/path/to/uv.\n' >&2
  exit 1
}

harness_dir() {
  local root="$1"
  local dir="$root/../a2a-hackathon"
  if [ ! -d "$dir" ]; then
    printf 'Harness repo not found at %s\n' "$dir" >&2
    exit 1
  fi
  cd "$dir" && pwd
}

require_google_api_key() {
  if [ -z "${GOOGLE_API_KEY:-}" ] || [ "$GOOGLE_API_KEY" = "..." ]; then
    printf 'GOOGLE_API_KEY is missing or still set to the placeholder in .env.\n' >&2
    printf 'Set a real Vertex AI API key before running model-backed evaluations.\n' >&2
    exit 1
  fi
}

print_run() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
}

