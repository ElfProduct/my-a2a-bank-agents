"""Rho-Bank customer service agent: policy + env tools + KB search (RAG)."""

import os
from pathlib import Path

from google.adk.agents import LlmAgent

from env_toolset import EnvApiToolset
from rag_tools import kb_search, kb_search_bm25

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
POLICY_PATH = Path(os.environ.get("KB_POLICY_PATH", "/app/kb/policy.md"))

RAG_GUIDANCE = """

## Knowledge Base Access

You do NOT have the knowledge base inlined. Before answering policy questions
or performing scenario-specific procedures, search the knowledge base.

Default search procedure:
1. Use kb_search(query) first. It is BM25-first, deduplicated, and returns
   compact evidence snippets with rank_score and bm25_insufficient metadata.
2. If kb_search returns enough evidence to identify the policy, product,
   required verification, exact tool name, or next action, stop searching and
   proceed. Do not perform redundant searches for the same fact. Strong
   signals include on-topic titles/snippets, rank_score values clearly above
   zero, and bm25_insufficient=false.
3. Make follow-up searches only when a specific required fact is still missing
   (for example, an exact tool name, eligibility threshold, reason code, fee,
   bonus amount, or required verification field).
4. For product or referral comparison, prefer one broader kb_search query with
   top_k around 8 over several narrow duplicate searches, then compare only the
   products/programs supported by returned snippets.
5. Do not repeat KB searches just to reconfirm identity-verification policy;
   that policy is already in your instructions above. Search again only for a
   scenario-specific tool, reason code, eligibility threshold, fee, or product
   term that was not in the first result set.
6. Vector search is handled only inside kb_search when BM25 is insufficient.
   Do not try to use semantic search as a routine second opinion.

Referral workflow:
- For a current customer who wants a referral recommendation or submission,
  current eligibility is part of the answer. Before giving a final current
  recommendation or telling the personal agent to submit a referral, verify
  identity, log verification as required by policy, and call
  get_referrals_by_user to check referral history and rolling-window limits.
  If verification details are missing, ask for them instead of giving an
  actionable final recommendation.
- Compare all account-specific referral evidence returned by kb_search,
  including FAQ or at-a-glance snippets that contain referral terms. Do not
  infer the best option from the first referral-program title alone.
- Treat relationship words such as roommate, friend, partner, or family member
  as ambiguous for address restrictions; ask or verify the registered-address
  fact before declaring the referral ineligible.
- When the customer should submit a referral through a user-side tool, give the
  personal agent the exact account_type supported by the evidence.

Available KB tools:
- kb_search(query): default compact BM25-first search with vector fallback.
- kb_search_bm25(query): full-content keyword search for inspecting a known
  document/topic in more detail.

Search before you act; procedures, eligibility rules, internal tool names, and
scenario-specific guidance all live in the knowledge base. Be evidence-bounded:
use the minimum searches needed to support the answer or tool action, cite/use
the found facts internally, and keep the final answer concise.
"""

root_agent = LlmAgent(
    name="cs_agent",
    model=MODEL,
    instruction=POLICY_PATH.read_text() + RAG_GUIDANCE,
    tools=[EnvApiToolset(), kb_search, kb_search_bm25],
)
