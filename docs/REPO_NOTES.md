# Repo Notes

## Competition Contract

The submission starts from `a2anet/a2a-hackathon-template` and is evaluated by `a2anet/a2a-hackathon`.

Required services:

- `personal-agent` on port `9001`.
- `cs-agent` on port `9002`.
- `redis`.

Required environment variables:

- Shared: `ENV_API_URL`, `ENV_API_TOKEN`, `MODEL`, `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_API_KEY`.
- Personal only: `CS_AGENT_URL`.
- CS only: `REDIS_URL`.

Marked chat-agent model must remain `gemini-3.5-flash`. KB vector embeddings use `gemini-embedding-001`.

## Local Setup Notes

- The harness `pyproject.toml` points `tau2` at `../tau2-bench`.
- I resolved that local path dependency by cloning `https://github.com/sierra-research/tau2-bench.git` next to the harness.
- `uv` was not installed locally, so I installed the standalone binary to `/Users/williamgoefron/.local/bin/uv`.
- The harness sync completed with `uv sync` in `../a2a-hackathon`.
- `.env` was created from `.env.example`; `GOOGLE_API_KEY` is still the placeholder and must be replaced by William before model-backed smoke/train runs.

## What The Harness Sends To Personal-Agent

The harness builds a tau2 user simulator for each task. Each user simulator turn is sent to the personal agent through A2A `message/send` with:

- `role=user`
- one text part containing the simulated user's message
- `contextId=<session id>`

The harness bridge is stateless. The personal agent's ADK session state is keyed by the A2A `contextId`.

## What Personal-Agent Sends To CS-Agent

The personal agent has an `ask_customer_service` tool. It sends an A2A `message/send` to `CS_AGENT_URL` with:

- the personal agent's message as a text part
- the same `contextId` taken from `ctx.session.id`

In local and marked runs, `CS_AGENT_URL` points at the harness gateway (`/cs-agent`), not directly at the CS container. The gateway forwards to the real CS agent and records the personal-to-CS leg.

## How Final Text Is Extracted

The harness reads only final A2A reply text:

- If the A2A result is a `Message`, it joins text parts.
- If the A2A result is a `Task`, it joins artifact text parts and final `status.message` text.
- Tool calls and intermediate model events are not visible to the other participant unless the final reply repeats them.

## How ContextId Flows

One UUID is created per simulation. That UUID is:

- the A2A `contextId` sent to the personal agent
- the env API session id in `/sessions/{contextId}/tools`
- the personal agent's ADK `ctx.session.id`
- the `contextId` on personal-to-CS A2A calls
- the CS agent's ADK session id

Breaking this chain causes missing env tool calls or missing leg-2 capture.

## Tool Visibility

The env API scopes tools by bearer token:

- Personal agent uses the user token and sees only task user tools, such as `apply_for_credit_card` or `submit_referral`.
- CS agent uses the agent token and sees bank-side tools, such as identity verification, account lookup, referral history, and human transfer tools.
- Both agents fetch tools dynamically from `GET /sessions/{contextId}/tools`.
- Tool calls go through `POST /sessions/{contextId}/tools/{name}` with `{"arguments": {...}}`.

The CS agent also has KB search tools backed by Redis:

- `kb_search_bm25(query, top_k=5)`
- `kb_search_vector(query, top_k=5)`, available when embeddings can be built or loaded

## What Cannot Be Changed

- Compose service names and ports.
- Required environment variable contract.
- `contextId` discipline and statelessness across context IDs.
- Marked model choice.
- Harness tasks, env tools, simulated user, scoring, or private data.
- Dynamic env tool discovery.
- Personal-to-CS communication through `CS_AGENT_URL`.
- Public repo safety; no committed secrets.

## What Can Be Changed

- Prompts.
- Tool descriptions.
- Conversation flow between personal and CS.
- Internal helper tools.
- RAG search strategy, KB preprocessing, Redis index layout, and optional precomputed embeddings.
- Observability that does not expose secrets, hidden chain-of-thought, or unnecessary sensitive data.

## Feedback Task Summaries

### task_006

Principle: product recommendation tasks require broad comparison across relevant eligible products before the personal agent performs the user's requested action.

The customer wants the highest everyday cash back card with no annual fee unless unavoidable. The target action is user-side `apply_for_credit_card` for `Gold Rewards Card` with the real customer details and `rho_bank_subscription=true`.

### task_009

Principle: protected account changes require verification using policy-defined identity factors, and unresolved identity failures should escalate with the most specific reason code.

The customer wants to change account email, can provide email and phone, but cannot provide address or date of birth. The target action is CS-side `transfer_to_human_agents` with reason `account_ownership_dispute`.

### task_053

Principle: referral optimization requires comparing all relevant account programs, checking eligibility and rolling-window limits, then letting the personal agent execute the user-side referral tool only after a recommendation.

The customer wants the best combined referral bonus for a friend depositing about $600. The target path verifies identity, checks referral history, compares account referral bonuses, recommends `Blue Account`, and uses user-side `submit_referral` with the real user id.

## Initial Improvement Hypotheses

- Personal prompt should make role boundaries sharper: personal assistant owns user tools and user-facing follow-up; CS owns bank-side facts, verification, policy, and escalation.
- CS prompt should be more procedural: search KB before policy/product answers, verify before protected operations, compare all candidate products, and select exact transfer reasons.
- RAG should expose a combined search path that searches multiple phrasings, deduplicates results, and returns concise snippets before the model commits to an answer.
- Observability should log context IDs, tool discovery counts, KB search counts, and CS-call previews without logging secrets or full sensitive data.

## Baseline Commands

From `my-a2a-bank-agents`:

```bash
docker compose up --build
```

In another shell, after replacing the placeholder `GOOGLE_API_KEY`:

```bash
scripts/check_contract.sh
scripts/smoke.sh
scripts/run_feedback.sh
scripts/run_train_small.sh
```

Full train run when stable:

```bash
scripts/run_train.sh
```

