"""Knowledge-base search tools backed by Redis (RediSearch).

kb_search_bm25: full-text BM25 search (OR-semantics keyword query).
kb_search_vector: HNSW vector search over gemini-embedding-001 embeddings
(available only when the index was built with embeddings).

Replies are parsed via execute_command so both the classic array reply and
the Redis 8 map-style reply work regardless of redis-py version."""

import os
import json
import re
import struct
from functools import lru_cache
from pathlib import Path

import redis

from observability import finish_observation, start_observation

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
KB_INDEX = "kb_idx"
DOC_PREFIX = "doc:"
KB_DOCUMENTS_DIR = Path(os.environ.get("KB_DOCUMENTS_DIR", "/app/kb/documents"))
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
AGENT_NAME = "cs"

_client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
_genai_client = None

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "get",
    "have",
    "help",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "need",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "there",
    "they",
    "this",
    "to",
    "use",
    "user",
    "what",
    "when",
    "with",
    "you",
}

_WORKFLOW_HINTS = [
    (
        ("email", "address", "profile", "ownership"),
        "email change identity verification account ownership dispute transfer human agent",
    ),
    (
        ("verify", "verification", "identity", "dob", "birth", "phone"),
        "identity verification log_verification date birth email phone address user",
    ),
    (
        ("refer", "referral", "bonus", "roommate", "friend"),
        "referral bonus referrer referred deposit annual limit rolling window submit_referral",
    ),
    (
        ("credit", "card", "cashback", "cash", "rewards", "apr"),
        "credit card rewards cash back annual fee Rho-Bank+ eligibility application",
    ),
    (
        ("checking", "account", "atm", "foreign", "currency"),
        "checking account monthly fee ATM foreign transaction currency debit card",
    ),
    (
        ("savings", "apy", "interest", "yield", "withdrawal"),
        "savings APY interest balance tier boost withdrawal minimum deposit",
    ),
    (
        ("decline", "declined", "pin", "locked", "code"),
        "card declined decline code pin lock fraud risk transfer unlock",
    ),
    (
        ("dispute", "fraud", "unauthorized", "charge", "transaction"),
        "transaction dispute fraud unauthorized charge provisional credit evidence",
    ),
    (
        ("transfer", "human", "agent", "escalate", "supervisor"),
        "transfer human agent escalation account ownership dispute security review",
    ),
]

_SNIPPET_CHARS = 700
_BUSINESS_TERMS = {
    "business",
    "businesses",
    "commercial",
    "corporate",
    "corporation",
    "llc",
    "paydex",
    "startup",
}
_INTENT_TERMS = {
    "credit_card": ("credit", "card", "cards", "cashback", "rewards", "apr"),
    "checking": ("checking", "debit", "atm", "wire", "overdraft"),
    "savings": ("savings", "apy", "interest", "yield", "withdrawal"),
    "referral": ("refer", "referral", "referrals", "bonus", "roommate", "friend"),
    "verification": ("verify", "verification", "identity", "dob", "birth", "phone", "email"),
    "transfer": ("transfer", "human", "agent", "escalate", "supervisor"),
    "dispute": ("dispute", "fraud", "unauthorized", "charge", "transaction"),
}
_CATALOG_TEXT_LIMIT = 4000
_REFERRER_BONUS_PATTERNS = [
    r"you earn(?:s)?(?:\:)?\s*\$([0-9,]+)",
    r"you earn\s*\|\s*\$([0-9,]+)",
    r"your reward(?:\:)?\s*\$([0-9,]+)",
    r"your bonus(?:\:)?\s*\$([0-9,]+)",
    r"your bonus\s*\|\s*\$([0-9,]+)",
    r"you receive(?:\:)?\s*\$([0-9,]+)",
    r"referrer bonus(?:\:)?\s*\$([0-9,]+)",
    r"referrer bonus\s*\|\s*\$([0-9,]+)",
    r"referral bonus(?:\:)?\s*\$([0-9,]+) for each successful referral",
    r"earn \$([0-9,]+) for each successful referral",
    r"referral bonus \(you earn\)\s*\|\s*\$([0-9,]+)",
]
_REFERRED_BONUS_PATTERNS = [
    r"person you refer receives \$([0-9,]+)",
    r"they receive(?:\:)?\s*\$([0-9,]+)",
    r"they receive\s*\|\s*\$([0-9,]+)",
    r"their bonus(?:\:)?\s*\$([0-9,]+)",
    r"their bonus\s*\|\s*\$([0-9,]+)",
    r"they earn\s*\|\s*\$([0-9,]+)",
    r"new member reward(?:\:)?\s*\$([0-9,]+)",
    r"new member bonus(?:\:)?\s*\$([0-9,]+)",
    r"new member bonus\s*\|\s*\$([0-9,]+)",
    r"welcome bonus(?:\:)?\s*\$([0-9,]+)",
    r"welcome bonus\s*\|\s*\$([0-9,]+)",
    r"new members receive \$([0-9,]+)",
    r"referral bonus \(they receive\)\s*\|\s*\$([0-9,]+)",
]
_REQUIRED_DEPOSIT_PATTERNS = [
    r"deposit at least \$([0-9,]+)",
    r"required deposit\s*\|\s*\$([0-9,]+)",
    r"minimum deposit\s*\|\s*\$([0-9,]+)",
    r"qualifying deposit(?: required)?(?:\:)?\s*\$([0-9,]+)",
    r"qualifying deposit\s*\|\s*\$([0-9,]+)",
    r"qualifying requirement(?:\:)?\s*referred person must deposit \$([0-9,]+)",
    r"must deposit(?: at least)? \$([0-9,]+)",
]
_ANNUAL_LIMIT_PATTERNS = [
    r"annual limit(?:\:)?\s*([0-9]+)",
    r"annual cap\s*\|\s*([0-9]+)",
    r"annual maximum(?:\:)?\s*([0-9]+)",
    r"max(?:imum)? referrals(?: per year)?(?:\:)?\s*([0-9]+)",
    r"max per year\s*\|\s*([0-9]+)",
    r"up to ([0-9]+) referral bonuses per calendar year",
    r"earn up to ([0-9]+) referral bonuses per calendar year",
]
_DEPOSIT_WINDOW_PATTERNS = [
    r"within ([0-9]+) days of (?:opening|account opening)",
    r"deposit window\s*\|\s*([0-9]+)\s*days",
    r"deposit deadline\s*\|\s*([0-9]+)\s*days",
]
_TENURE_PATTERNS = [
    r"minimum banking relationship of ([0-9]+) days",
    r"checking relationship must span at least ([0-9]+) days",
    r"referrer tenure\s*\|\s*([0-9]+)\s*days",
    r"tenure required\s*\|\s*([0-9]+)\s*days",
    r"customer tenure\s*\|\s*([0-9]+)\s*days",
    r"participation requires ([0-9]+) days",
    r"account tenure requirement(?:\:)?\s*([0-9]+) days",
    r"at least ([0-9]+) days prior",
]
_CARD_NAMES_BY_DOC_SLUG = {
    "bronze_rewards_card": "Bronze Rewards Card",
    "silver_rewards_card": "Silver Rewards Card",
    "gold_rewards_card": "Gold Rewards Card",
    "platinum_rewards_card": "Platinum Rewards Card",
    "diamond_elite_card": "Diamond Elite Card",
    "crypto-cash_back": "Crypto-Cash Back Card",
    "ecocard": "EcoCard",
    "green_rewards_card": "Green Rewards Card",
}
_ANNUAL_FEE_PATTERNS = [
    r"annual fee(?:\:)?\s*\$([0-9,]+(?:\.[0-9]+)?)",
    r"annual fee\s*\|\s*\$([0-9,]+(?:\.[0-9]+)?)",
]
_FLAT_CASHBACK_PATTERNS = [
    r"cash back on all purchases(?:\:)?\s*([0-9]+(?:\.[0-9]+)?)%",
    r"([0-9]+(?:\.[0-9]+)?)%\s+cash back on all(?: eligible)? purchases",
    r"earn rewards at\s*([0-9]+(?:\.[0-9]+)?)%",
    r"purchases outside top categories earn\s*([0-9]+(?:\.[0-9]+)?)%\s+back",
]
_MIN_CREDIT_SCORE_PATTERNS = [
    r"minimum credit score(?: required)?(?: to apply)?(?:\:)?\s*\$?([0-9]+)",
    r"minimum score requirement is\s*\$?([0-9]+)",
]


def _get_genai_client():
    """Reused genai client (one connection pool, not a new one per search)."""
    global _genai_client
    if _genai_client is None:
        from google import genai

        _genai_client = genai.Client()
    return _genai_client


def _embed(texts: list[str]) -> list[list[float]]:
    """Embed texts with gemini-embedding-001 via google-genai."""
    from google.genai import types

    span = start_observation(
        "gemini.embed",
        AGENT_NAME,
        model=EMBEDDING_MODEL,
        batch_size=len(texts),
    )
    try:
        # Reduced-dim output is unnormalized; the index uses COSINE, so that's fine.
        result = _get_genai_client().models.embed_content(
            model=EMBEDDING_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
        )
    except Exception as exc:
        finish_observation(span, success=False, exception=exc)
        raise
    embeddings = [e.values for e in result.embeddings]
    finish_observation(span, success=True, embedding_count=len(embeddings))
    return embeddings


def _decode(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _terms(query: str) -> list[str]:
    return re.findall(r"\w+", query.lower())


def _important_terms(query: str) -> list[str]:
    terms = [term for term in _terms(query) if len(term) > 2 and term not in _STOPWORDS]
    return terms or _terms(query)


def _hint_text(query: str) -> str:
    lower = query.lower()
    hints = []
    for triggers, text in _WORKFLOW_HINTS:
        if any(trigger in lower for trigger in triggers):
            hints.append(text)
    return " ".join(dict.fromkeys(" ".join(hints).split()))


def _bm25_query(query: str) -> str:
    terms = _important_terms(query)
    return "|".join(dict.fromkeys(terms))


def _expanded_bm25_queries(query: str) -> list[str]:
    queries = [query]
    hints = _hint_text(query)
    if hints:
        queries.append(f"{query} {hints}")
        queries.append(hints)
    return list(dict.fromkeys(q for q in queries if q.strip()))


def _phrases(terms: list[str]) -> list[str]:
    phrases = []
    for i in range(len(terms) - 1):
        phrases.append(f"{terms[i]} {terms[i + 1]}")
    return phrases


def _query_profile(query: str) -> dict:
    query_terms = _important_terms(query)
    hint_terms = _important_terms(_hint_text(query))
    terms = set(query_terms)
    return {
        "query_terms": query_terms,
        "hint_terms": hint_terms,
        "all_terms": list(dict.fromkeys(query_terms + hint_terms)),
        "phrases": _phrases(query_terms),
        "business": bool(terms & _BUSINESS_TERMS),
        "credit_card": any(term in terms for term in _INTENT_TERMS["credit_card"]),
        "checking": any(term in terms for term in _INTENT_TERMS["checking"]),
        "savings": any(term in terms for term in _INTENT_TERMS["savings"]),
        "referral": any(term in terms for term in _INTENT_TERMS["referral"]),
        "verification": any(term in terms for term in _INTENT_TERMS["verification"]),
        "transfer": any(term in terms for term in _INTENT_TERMS["transfer"]),
        "dispute": any(term in terms for term in _INTENT_TERMS["dispute"]),
    }


def _load_doc(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    title = str(payload.get("title", ""))
    content = str(payload.get("content", ""))
    if not title and not content:
        return None
    return {
        "doc_id": f"{DOC_PREFIX}{path.stem}",
        "title": title,
        "content": content[:_CATALOG_TEXT_LIMIT],
        "_source": "bm25_catalog",
    }


@lru_cache(maxsize=1)
def _public_doc_catalog() -> tuple[tuple[tuple[str, str], ...], ...]:
    docs = []
    if not KB_DOCUMENTS_DIR.exists():
        return tuple()
    for path in KB_DOCUMENTS_DIR.glob("*.json"):
        doc = _load_doc(path)
        if doc:
            docs.append(tuple((key, str(value)) for key, value in doc.items()))
    return tuple(docs)


def _catalog_doc_matches(doc: dict, profile: dict) -> bool:
    doc_id = doc.get("doc_id", "").lower()
    title = doc.get("title", "").lower()
    content = doc.get("content", "").lower()
    doc_text = f"{title} {content}"
    business_doc = _doc_is_business(doc_id, title)
    if business_doc and not profile["business"]:
        return False

    if profile["credit_card"] and "doc:doc_credit_cards_" in doc_id:
        return (
            doc_id.endswith("_001")
            or doc_id.endswith("_002")
            or "apply" in title
            or "eligibility" in title
            or "cash back" in doc_text
            or "annual fee" in doc_text
        )
    if profile["referral"] and profile["checking"]:
        return (
            ("doc:doc_checking_accounts_" in doc_id or "doc:doc_bank_accounts_" in doc_id)
            and "referral" in doc_text
        )
    if profile["checking"] and "doc:doc_checking_accounts_" in doc_id:
        return (
            doc_id.endswith("_001")
            or "at a glance" in title
            or "foreign atm" in doc_text
            or "direct deposit" in doc_text
            or (profile["referral"] and "referral" in doc_text)
        )
    if profile["savings"] and "doc:doc_savings_accounts_" in doc_id:
        return doc_id.endswith("_001") or "apy" in doc_text or "minimum deposit" in doc_text
    return False


def _catalog_candidates(query: str) -> list[dict]:
    profile = _query_profile(query)
    if not (
        profile["credit_card"]
        or profile["checking"]
        or profile["savings"]
        or profile["referral"]
    ):
        return []
    docs = []
    for row in _public_doc_catalog():
        doc = dict(row)
        if _catalog_doc_matches(doc, profile):
            docs.append(doc)
    return docs


def _term_hits(text: str, terms: list[str]) -> int:
    return sum(1 for term in terms if term and term in text)


def _content_hits(text: str, terms: list[str]) -> int:
    return sum(min(text.count(term), 3) for term in terms if term)


def _doc_is_business(doc_id: str, title: str) -> bool:
    haystack = f"{doc_id} {title}".lower()
    return "business_" in haystack or "business " in haystack


def _money_value(value: str) -> float:
    return float(value.replace(",", ""))


def _first_money(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _money_value(match.group(1))
    return None


def _first_int(text: str, patterns: list[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _first_float(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def _query_deposit_amount(terms: list[str]) -> float | None:
    amounts = []
    for term in terms:
        if term.isdigit():
            value = float(term)
            if value >= 50:
                amounts.append(value)
    return max(amounts) if amounts else None


def _referral_numeric_boost(content_l: str, profile: dict) -> float:
    referrer = _first_money(content_l, _REFERRER_BONUS_PATTERNS)
    referred = _first_money(content_l, _REFERRED_BONUS_PATTERNS)
    if referrer is None and referred is None:
        return 0.0

    boost = ((referrer or 0.0) + (referred or 0.0)) / 2
    requested_deposit = _query_deposit_amount(profile["query_terms"])
    required_deposit = _first_money(content_l, _REQUIRED_DEPOSIT_PATTERNS)
    if requested_deposit is not None and required_deposit is not None:
        if required_deposit <= requested_deposit:
            boost += 25
        else:
            boost -= 35
    return boost


def _account_type_from_doc(doc: dict) -> str | None:
    title = re.sub(r"^faq:\s*", "", doc.get("title", ""), flags=re.IGNORECASE).strip()
    match = re.search(
        r"\b([A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*\s+Account\s*\([^)]+\))",
        title,
    )
    if match:
        return match.group(1).strip()

    match = re.search(
        r"\b([A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*\s+Account(?:\s*\([^)]+\))?)\b",
        title,
    )
    if match:
        return match.group(1).strip()

    doc_id = doc.get("doc_id", "")
    match = re.search(r"doc_checking_accounts_(.+?)_\d+$", doc_id)
    if not match:
        return None
    words = match.group(1).replace("_", " ").split()
    if not words:
        return None
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _referral_facts(content: str) -> dict:
    return {
        "referrer_bonus": _first_money(content, _REFERRER_BONUS_PATTERNS),
        "referred_bonus": _first_money(content, _REFERRED_BONUS_PATTERNS),
        "required_deposit": _first_money(content, _REQUIRED_DEPOSIT_PATTERNS),
        "annual_limit": _first_int(content, _ANNUAL_LIMIT_PATTERNS),
        "deposit_window_days": _first_int(content, _DEPOSIT_WINDOW_PATTERNS),
        "referrer_tenure_days": _first_int(content, _TENURE_PATTERNS),
    }


def _referral_options(query: str, docs: list[dict]) -> list[dict]:
    profile = _query_profile(query)
    if not profile["referral"] or profile["business"]:
        return []

    requested_deposit = _query_deposit_amount(profile["query_terms"])
    by_account: dict[str, dict] = {}
    for doc in docs:
        doc_id = doc.get("doc_id", "")
        title = doc.get("title", "")
        content = doc.get("content", "")
        doc_text = f"{title} {content}".lower()
        if _doc_is_business(doc_id, title) or "doc_checking_accounts_" not in doc_id:
            continue
        if "referral" not in doc_text and "refer" not in doc_text:
            continue

        account_type = _account_type_from_doc(doc)
        if not account_type:
            continue

        facts = _referral_facts(content)
        if not any(value is not None for value in facts.values()):
            continue

        option = by_account.setdefault(
            account_type,
            {
                "account_type": account_type,
                "referrer_bonus": None,
                "referred_bonus": None,
                "combined_bonus": 0.0,
                "required_deposit": None,
                "eligible_for_requested_deposit": None,
                "annual_limit": None,
                "deposit_window_days": None,
                "referrer_tenure_days": None,
                "source_doc_ids": [],
                "source_titles": [],
            },
        )
        for key in (
            "referrer_bonus",
            "referred_bonus",
            "required_deposit",
            "annual_limit",
            "deposit_window_days",
            "referrer_tenure_days",
        ):
            if option[key] is None and facts[key] is not None:
                option[key] = facts[key]
        if doc_id not in option["source_doc_ids"]:
            option["source_doc_ids"].append(doc_id)
        if title and title not in option["source_titles"]:
            option["source_titles"].append(title)

    options = []
    for option in by_account.values():
        option["combined_bonus"] = round(
            (option["referrer_bonus"] or 0.0) + (option["referred_bonus"] or 0.0),
            2,
        )
        if requested_deposit is not None and option["required_deposit"] is not None:
            option["eligible_for_requested_deposit"] = (
                option["required_deposit"] <= requested_deposit
            )
        options.append(option)

    options = [
        option
        for option in options
        if option["referrer_bonus"] is not None or option["referred_bonus"] is not None
    ]

    def sort_key(option: dict) -> tuple:
        eligible = option["eligible_for_requested_deposit"]
        return (
            0 if eligible is True else 1 if eligible is None else 2,
            -option["combined_bonus"],
            option["required_deposit"] or 999999999,
            option["account_type"],
        )

    return sorted(options, key=sort_key)[:8]


def _card_name_from_doc(doc: dict) -> str | None:
    title = doc.get("title", "")
    title_match = re.search(
        r"\b([A-Z][A-Za-z0-9-]*(?:[- ][A-Z][A-Za-z0-9-]*)*\s+Card)\b",
        title,
    )
    if title_match:
        return title_match.group(1).strip()
    if title.startswith("EcoCard"):
        return "EcoCard"
    if title.startswith("Crypto-Cash Back"):
        return "Crypto-Cash Back Card"

    doc_id = doc.get("doc_id", "")
    match = re.search(r"doc_credit_cards_(.+?)_\d+$", doc_id)
    if not match:
        return None
    return _CARD_NAMES_BY_DOC_SLUG.get(match.group(1))


def _has_yes_after(text_l: str, label: str) -> bool | None:
    label_l = label.lower()
    if label_l not in text_l:
        return None
    match = re.search(re.escape(label_l) + r"[^.\n|:]*[:|]?\s*(yes|no)\b", text_l)
    if match:
        return match.group(1) == "yes"
    return None


def _card_facts(content: str) -> dict:
    content_l = content.lower()
    return {
        "flat_cashback_percent": _first_float(content, _FLAT_CASHBACK_PATTERNS),
        "annual_fee": _first_float(content, _ANNUAL_FEE_PATTERNS),
        "minimum_credit_score": _first_int(content, _MIN_CREDIT_SCORE_PATTERNS),
        "rho_bank_plus_required": (
            True
            if "rho" in content_l
            and "bank+" in content_l
            and "subscription required" in content_l
            and "yes" in content_l
            else None
        ),
        "invitation_only": _has_yes_after(content_l, "membership is by invitation only"),
        "virtual_card_management": _has_yes_after(
            content_l, "virtual card management available"
        ),
    }


def _credit_card_options(query: str, docs: list[dict]) -> list[dict]:
    profile = _query_profile(query)
    if not profile["credit_card"] or profile["business"]:
        return []

    query_l = query.lower()
    no_annual_fee_required = (
        "no annual fee" in query_l
        or "avoid annual fee" in query_l
        or "without annual fee" in query_l
        or "$0 annual fee" in query_l
        or "zero annual fee" in query_l
    )
    subscription_available = (
        "rho-bank+" in query_l
        or "rho bank+" in query_l
        or "rho‑bank+" in query_l
        or "premium subscription" in query_l
    ) and any(
        term in query_l
        for term in ("have", "has", "active", "through", "provided", "company", "subscription")
    )

    by_card: dict[str, dict] = {}
    for doc in docs:
        doc_id = doc.get("doc_id", "")
        title = doc.get("title", "")
        content = doc.get("content", "")
        if "doc_credit_cards_" not in doc_id or _doc_is_business(doc_id, title):
            continue
        if "general" in doc_id or "logistics" in doc_id or "virtual_card" in doc_id:
            continue

        card_type = _card_name_from_doc(doc)
        if not card_type:
            continue

        facts = _card_facts(content)
        if not any(value is not None for value in facts.values()):
            continue

        option = by_card.setdefault(
            card_type,
            {
                "card_type": card_type,
                "flat_cashback_percent": None,
                "annual_fee": None,
                "rho_bank_plus_required": None,
                "minimum_credit_score": None,
                "invitation_only": None,
                "virtual_card_management": None,
                "fits_no_annual_fee_preference": None,
                "subscription_condition_satisfied_by_user_statement": None,
                "source_doc_ids": [],
                "source_titles": [],
            },
        )
        for key, value in facts.items():
            if option[key] is None and value is not None:
                option[key] = value
        if doc_id not in option["source_doc_ids"]:
            option["source_doc_ids"].append(doc_id)
        if title and title not in option["source_titles"]:
            option["source_titles"].append(title)

    options = []
    for option in by_card.values():
        fee = option["annual_fee"]
        option["fits_no_annual_fee_preference"] = fee == 0 if fee is not None else None
        if option["rho_bank_plus_required"] is True:
            option["subscription_condition_satisfied_by_user_statement"] = (
                True if subscription_available else None
            )
        options.append(option)

    def sort_key(option: dict) -> tuple:
        fee_fits = option["fits_no_annual_fee_preference"]
        if no_annual_fee_required:
            fee_rank = 0 if fee_fits is True else 1 if fee_fits is None else 2
        else:
            fee_rank = 0
        return (
            fee_rank,
            -float(option["flat_cashback_percent"] or 0.0),
            1 if option["invitation_only"] else 0,
            option["annual_fee"] if option["annual_fee"] is not None else 999999999,
            option["card_type"],
        )

    return sorted(options, key=sort_key)[:8]


def _doc_score(doc: dict, profile: dict) -> float:
    doc_id = doc.get("doc_id", "")
    title = doc.get("title", "")
    content = doc.get("content", "")
    doc_key = f"{doc_id} {title}".lower()
    title_l = title.lower()
    content_l = content.lower()
    score = 0.0

    score += 8 * _term_hits(title_l, profile["query_terms"])
    score += 2 * _content_hits(content_l, profile["query_terms"])
    score += 3 * _term_hits(title_l, profile["hint_terms"])
    score += 0.5 * _content_hits(content_l, profile["hint_terms"])

    for phrase in profile["phrases"]:
        if phrase in title_l:
            score += 12
        if phrase in content_l:
            score += 4

    is_business = _doc_is_business(doc_id, title)
    if is_business and not profile["business"]:
        score -= 160
    elif is_business and profile["business"]:
        score += 10

    if profile["credit_card"]:
        if "doc_credit_cards_" in doc_key:
            score += 14
        if "doc_credit_cards_" in doc_key and " card:" in title_l:
            score += 20
        if "doc_business_credit_cards_" in doc_key and not profile["business"]:
            score -= 18
        if "credit card" in title_l:
            score += 8
        if "doc_credit_cards_credit_cards_(general)" in doc_key:
            score -= 16
        if "doc_credit_cards_credit_card_account_logistics" in doc_key:
            score -= 16
        if "internal:" in title_l:
            score -= 18
    if profile["checking"]:
        if "doc_checking_accounts_" in doc_key:
            score += 12
        if "doc_bank_accounts_bank_accounts_(general)" in doc_key:
            score += 5
        if "checking" in title_l:
            score += 8
    if profile["savings"]:
        if "doc_savings_accounts_" in doc_key:
            score += 12
        if "savings" in title_l:
            score += 8
    if profile["referral"]:
        if "referral" in title_l:
            score += 24
        if "referral program" in content_l or "referral bonus" in content_l:
            score += 12
        if (
            "referral" in content_l
            and ("faq:" in title_l or "at a glance" in title_l)
        ):
            score += 50
        if "submit_referral" in content_l:
            score += 14
        score += _referral_numeric_boost(content_l, profile)
    elif "referral" in title_l:
        score -= 20
    if profile["verification"]:
        if "log_verification" in content_l:
            score += 18
        if "identity verification" in content_l or "verify" in title_l:
            score += 10
    if profile["transfer"]:
        if "transfer reason" in title_l or "human agent transfer" in title_l:
            score += 24
        if "transfer_to_human_agents" in content_l:
            score += 18
    if "ownership" in profile["all_terms"] and "account_ownership_dispute" in content_l:
        score += 28
    if "email" in profile["all_terms"] and "email" in content_l:
        score += 6
    if profile["dispute"] and "dispute" in title_l:
        score += 10

    if "atm" not in profile["all_terms"] and "atm" in title_l:
        score -= 8
    if "sweep" not in profile["all_terms"] and "automatic_sweep" in doc_key:
        score -= 8

    return score


def _dedupe_and_rank(docs: list[dict], query: str) -> list[dict]:
    profile = _query_profile(query)
    best_by_id = {}
    for position, doc in enumerate(docs):
        doc_id = doc.get("doc_id")
        if not doc_id:
            continue
        if _doc_is_business(doc_id, doc.get("title", "")) and not profile["business"]:
            continue
        scored = dict(doc)
        scored["_rank_score"] = _doc_score(doc, profile)
        scored["_rank_position"] = position
        previous = best_by_id.get(doc_id)
        if previous is None or scored["_rank_score"] > previous["_rank_score"]:
            best_by_id[doc_id] = scored
    return sorted(
        best_by_id.values(),
        key=lambda item: (-item["_rank_score"], item["_rank_position"]),
    )


def _parse_search_reply(reply) -> list[dict]:
    """Normalize an FT.SEARCH reply (array or map shape) to result dicts."""
    if isinstance(reply, dict):
        results = reply.get(b"results", reply.get("results")) or []
        out = []
        for row in results:
            attrs = row.get(b"extra_attributes", row.get("extra_attributes")) or {}
            doc = {"doc_id": _decode(row.get(b"id", row.get("id", "")))}
            doc.update({_decode(k): _decode(v) for k, v in attrs.items()})
            out.append(doc)
        return out
    out = []
    for i in range(1, len(reply) - 1, 2):
        doc = {"doc_id": _decode(reply[i])}
        fields = reply[i + 1]
        for j in range(0, len(fields) - 1, 2):
            doc[_decode(fields[j])] = _decode(fields[j + 1])
        out.append(doc)
    return out


@lru_cache(maxsize=512)
def _bm25_cached(or_query: str, top_k: int) -> tuple[tuple[tuple[str, str], ...], ...]:
    reply = _client.execute_command(
        "FT.SEARCH", KB_INDEX, or_query,
        "LIMIT", "0", str(top_k),
        "RETURN", "2", "title", "content",
    )
    docs = _parse_search_reply(reply)
    return tuple(
        tuple((key, str(value)) for key, value in doc.items())
        for doc in docs
    )


def _from_cached(rows: tuple[tuple[tuple[str, str], ...], ...]) -> list[dict]:
    return [dict(row) for row in rows]


def _strip_score(docs: list[dict]) -> list[dict]:
    for doc in docs:
        doc.pop("score", None)
    return docs


def _snippet(content: str, query_terms: list[str], max_chars: int = _SNIPPET_CHARS) -> str:
    if len(content) <= max_chars:
        return content.strip()
    lower = content.lower()
    hits = [lower.find(term) for term in query_terms if term and lower.find(term) >= 0]
    center = min(hits) if hits else 0
    start = max(0, center - max_chars // 4)
    end = min(len(content), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet += "..."
    return snippet


def _compact_results(docs: list[dict], query: str, source: str, top_k: int) -> list[dict]:
    profile = _query_profile(query)
    results = []
    for doc in _dedupe_and_rank(docs, query):
        doc_id = doc.get("doc_id")
        if not doc_id:
            continue
        results.append(
            {
                "doc_id": doc_id,
                "title": doc.get("title", ""),
                "source": doc.get("_source", source),
                "rank_score": round(doc.get("_rank_score", 0.0), 1),
                "snippet": _snippet(doc.get("content", ""), profile["all_terms"]),
            }
        )
        if len(results) >= top_k:
            break
    return results


def kb_search_bm25(query: str, top_k: int = 5) -> list[dict]:
    """Full-text (BM25) search over the Rho-Bank knowledge base.

    Args:
        query: Keywords or a short phrase to search for. Matching is ranked,
            so extra keywords help rather than hurt.
        top_k: Number of documents to return.

    Returns:
        Matching documents with doc_id, title, and full content.
    """
    terms = _important_terms(query)
    span = start_observation(
        "rag.bm25",
        AGENT_NAME,
        query_chars=len(query),
        term_count=len(terms),
        top_k=top_k,
    )
    if not terms:
        finish_observation(span, success=True, result_count=0)
        return []
    try:
        # OR-join: RediSearch defaults to AND, which zeroes out long queries.
        results = _from_cached(_bm25_cached("|".join(dict.fromkeys(terms)), int(top_k)))
    except Exception as exc:
        finish_observation(span, success=False, exception=exc)
        raise
    finish_observation(span, success=True, result_count=len(results))
    return results


def kb_search_vector(query: str, top_k: int = 5) -> list[dict]:
    """Semantic (vector) search over the Rho-Bank knowledge base.

    Better than kb_search_bm25 when the query is a natural-language question
    rather than exact keywords.

    Args:
        query: A natural-language question or description.
        top_k: Number of documents to return.

    Returns:
        Matching documents with doc_id, title, and full content; or an error
        entry telling you to fall back to kb_search_bm25.
    """
    span = start_observation(
        "rag.vector", AGENT_NAME, query_chars=len(query), top_k=top_k
    )
    try:
        vector = struct.pack(f"{EMBEDDING_DIM}f", *_embed([query])[0])
        reply = _client.execute_command(
            "FT.SEARCH", KB_INDEX, f"*=>[KNN {top_k} @embedding $vec AS score]",
            "PARAMS", "2", "vec", vector,
            "SORTBY", "score",
            "LIMIT", "0", str(top_k),
            "RETURN", "3", "title", "content", "score",
            "DIALECT", "2",
        )
        results = _strip_score(_parse_search_reply(reply))
        finish_observation(span, success=True, result_count=len(results))
        return results
    except Exception as e:
        finish_observation(span, success=False, exception=e)
        return [
            {
                "error": f"Vector search unavailable ({type(e).__name__}). "
                "Use kb_search_bm25 with keywords instead."
            }
        ]


def kb_search(query: str, top_k: int = 8, use_vector_fallback: bool = True) -> dict:
    """BM25-first compact search over the Rho-Bank public knowledge base.

    Use this as the default KB tool. It searches cheap keyword/BM25 indexes
    first with general workflow vocabulary, deduplicates documents, and returns
    short snippets. It only calls vector search when BM25 returns too few
    candidates.

    Args:
        query: Specific policy, product, procedure, or tool question.
        top_k: Maximum number of snippets to return.
        use_vector_fallback: Whether to use semantic vector search if BM25 is
            insufficient.

    Returns:
        A dict with strategy metadata and compact document snippets.
    """
    top_k = max(1, min(int(top_k or 6), 10))
    span = start_observation(
        "rag.combined",
        AGENT_NAME,
        query_chars=len(query),
        top_k=top_k,
        use_vector_fallback=use_vector_fallback,
    )
    try:
        docs = []
        bm25_queries = _expanded_bm25_queries(query)
        candidate_limit = min(max(top_k * 8, 20), 60)
        for expanded in bm25_queries:
            or_query = _bm25_query(expanded)
            if not or_query:
                continue
            docs.extend(_from_cached(_bm25_cached(or_query, candidate_limit)))
        catalog_docs = _catalog_candidates(query)
        docs.extend(catalog_docs)
        referral_options = _referral_options(query, docs)
        credit_card_options = _credit_card_options(query, docs)
        results = _compact_results(docs, query, "bm25", top_k)
        used_vector = False
        min_needed = min(3, top_k)
        best_score = results[0]["rank_score"] if results else 0
        bm25_insufficient = len(results) < min_needed or best_score < 10
        specific_terms = _important_terms(query)
        # Embeddings are high-latency and have mostly hurt short follow-up
        # searches. Keep vector fallback for substantial natural-language gaps.
        vector_allowed = len(specific_terms) >= 4 and len(query.strip()) >= 40
        vector_skipped_reason = None
        if use_vector_fallback and bm25_insufficient and vector_allowed:
            vector_docs = kb_search_vector(query, top_k=top_k)
            if vector_docs and "error" not in vector_docs[0]:
                used_vector = True
                existing = {item["doc_id"] for item in results}
                for item in _compact_results(vector_docs, query, "vector", top_k):
                    if item["doc_id"] not in existing:
                        results.append(item)
                        existing.add(item["doc_id"])
                    if len(results) >= top_k:
                        break
        elif use_vector_fallback and bm25_insufficient:
            vector_skipped_reason = "query_too_short_or_underspecified"
        finish_observation(
            span,
            success=True,
            result_count=len(results),
            bm25_query_count=len(bm25_queries),
            catalog_candidate_count=len(catalog_docs),
            referral_option_count=len(referral_options),
            credit_card_option_count=len(credit_card_options),
            used_vector=used_vector,
            vector_skipped_reason=vector_skipped_reason,
            best_bm25_score=best_score,
            bm25_insufficient=bm25_insufficient,
        )
        return {
            "strategy": "bm25_first_vector_fallback",
            "used_vector": used_vector,
            "bm25_query_count": len(bm25_queries),
            "catalog_candidate_count": len(catalog_docs),
            "best_bm25_score": best_score,
            "bm25_insufficient": bm25_insufficient,
            "vector_skipped_reason": vector_skipped_reason,
            "result_count": len(results),
            "results": results,
            "referral_options": referral_options,
            "best_referral_option": referral_options[0] if referral_options else None,
            "credit_card_options": credit_card_options,
            "best_credit_card_option": (
                credit_card_options[0] if credit_card_options else None
            ),
            "guidance": (
                "Use these snippets as evidence. If they answer the policy/tool "
                "question, stop searching and act. If they are insufficient, run "
                "one more specific kb_search query. If referral_options is present, "
                "use that structured table for the numeric referral comparison and "
                "do not run more KB searches for the same account comparison. If "
                "credit_card_options is present, use that structured table for "
                "card comparisons against the user's stated constraints."
            ),
        }
    except Exception as exc:
        finish_observation(span, success=False, exception=exc)
        raise
