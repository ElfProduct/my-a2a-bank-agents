#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

load_dotenv "$ROOT"

cd "$ROOT"

if [ -z "${GOOGLE_API_KEY:-}" ] || [ "$GOOGLE_API_KEY" = "..." ]; then
  printf 'Warning: GOOGLE_API_KEY is missing or placeholder; smoke/train scripts will fail until it is set.\n' >&2
fi

printf 'Checking docker compose services...\n'
SERVICES="$(docker compose config --services)"
for service in personal-agent cs-agent redis; do
  if ! printf '%s\n' "$SERVICES" | grep -qx "$service"; then
    printf 'Missing compose service: %s\n' "$service" >&2
    exit 1
  fi
done

printf 'Checking compose contract text...\n'
CONFIG="$(docker compose config)"
printf '%s\n' "$CONFIG" | grep -q 'target: 9001' || { printf 'personal-agent target port 9001 is not mapped.\n' >&2; exit 1; }
printf '%s\n' "$CONFIG" | grep -q 'published: "9001"' || { printf 'personal-agent published port 9001 is not mapped.\n' >&2; exit 1; }
printf '%s\n' "$CONFIG" | grep -q 'target: 9002' || { printf 'cs-agent target port 9002 is not mapped.\n' >&2; exit 1; }
printf '%s\n' "$CONFIG" | grep -q 'published: "9002"' || { printf 'cs-agent published port 9002 is not mapped.\n' >&2; exit 1; }
printf '%s\n' "$CONFIG" | grep -q 'CS_AGENT_URL' || { printf 'CS_AGENT_URL is missing from compose config.\n' >&2; exit 1; }
printf '%s\n' "$CONFIG" | grep -q 'gemini-3.5-flash' || { printf 'gemini-3.5-flash default is missing from compose config.\n' >&2; exit 1; }

printf 'Checking agent source contract...\n'
grep -R 'gemini-3.5-flash' personal_agent cs_agent >/dev/null || { printf 'Model default not found in agent source.\n' >&2; exit 1; }
grep -R 'session_id(tool_context)' personal_agent cs_agent >/dev/null || { printf 'Env tool calls do not obviously use session_id(tool_context).\n' >&2; exit 1; }
grep -R 'context_id=session_id(tool_context)' personal_agent >/dev/null || { printf 'ask_customer_service does not obviously propagate contextId.\n' >&2; exit 1; }

printf 'Checking reachable agent cards on localhost...\n'
for port in 9001 9002; do
  if curl -fsS "http://localhost:${port}/.well-known/agent-card.json" >/dev/null; then
    printf 'Port %s agent-card endpoint is reachable.\n' "$port"
  elif curl -fsS "http://localhost:${port}/.well-known/agent.json" >/dev/null; then
    printf 'Port %s agent.json endpoint is reachable.\n' "$port"
  else
    printf 'No reachable A2A agent card on localhost:%s. Are containers running?\n' "$port" >&2
    exit 1
  fi
done

printf 'Contract check passed.\n'
