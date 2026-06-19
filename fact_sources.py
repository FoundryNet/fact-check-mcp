"""Fact-verification sources.

Two source families, both async via request_json (defensive — never raise):

  1. General web search (Brave Search API if WEB_SEARCH_API_KEY is set; otherwise
     degrades gracefully — the caller turns "no backend" into an "unverifiable"
     verdict with an explanatory note).
  2. The FoundryNet Data Network siblings — verify_claim classifies a claim's
     domain (company / finance / patents / regulation) and calls the relevant
     sibling MCP server's tool over its public /mcp endpoint (JSON-RPC 2.0 tools/
     call) to corroborate. Best-effort: a sibling that's down just contributes no
     signal.

source_check derives a domain's age via RDAP (keyless) and computes simple,
transparent trust / bias heuristics from the domain.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import config
from http_util import request_json

logger = logging.getLogger("fact.src")

_UA = {"User-Agent": config.SOURCE_USER_AGENT}

# ── claim domain classification ───────────────────────────────────────────────
# Maps a coarse claim domain to the sibling server + the tool to call on it.
_DOMAIN_SERVERS = {
    "company":    ("brand-intel-mcp", "domain_profile"),
    "finance":    ("financial-signals-mcp", "company_signals"),
    "patents":    ("patent-intel-mcp", "search_patents"),
    "regulation": ("compliance-mcp", "search_regulations"),
}

_DOMAIN_KEYWORDS = {
    "finance": ("stock", "shares", "revenue", "earnings", "market cap", "ipo",
                "nasdaq", "nyse", "valuation", "profit", "ebitda", "dividend",
                "quarterly", "fiscal", "sec filing", "ticker"),
    "patents": ("patent", "patented", "invention", "uspto", "intellectual property",
                "trademark filing", "prior art"),
    "regulation": ("fda", "regulation", "recall", "compliance", "approved by",
                   "federal register", "cpsc", "regulatory", "sanction", "banned by"),
    "company": ("company", "founded", "headquarter", "ceo", "acquired", "startup",
                "corporation", "inc.", "ltd", "employees", "domain", "website",
                "owned by", "based in"),
}


def classify_claim(claim: str, context: str = "") -> str:
    """Coarse domain of a claim → one of company|finance|patents|regulation|general."""
    text = f"{claim} {context}".lower()
    best, best_hits = "general", 0
    # finance/patents/regulation are checked before the broad "company" bucket.
    for domain in ("finance", "patents", "regulation", "company"):
        hits = sum(1 for kw in _DOMAIN_KEYWORDS[domain] if kw in text)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best


# ── web search ────────────────────────────────────────────────────────────────
def web_search_configured() -> bool:
    return bool(config.WEB_SEARCH_API_KEY)


async def web_search(query: str, limit: int = 5) -> dict:
    """General web search. Returns {"configured": bool, "results": [{title,url,snippet}]}.

    Uses the Brave Search API when WEB_SEARCH_API_KEY is set. Degrades to an empty
    result set (configured=False) otherwise — the caller maps that to an
    "unverifiable" verdict rather than guessing.
    """
    if not config.WEB_SEARCH_API_KEY:
        return {"configured": False, "results": []}
    headers = {**_UA, "Accept": "application/json",
               "X-Subscription-Token": config.WEB_SEARCH_API_KEY}
    r = await request_json("GET", config.WEB_SEARCH_API, headers=headers,
                           params={"q": query[:400], "count": str(max(1, min(limit, 20)))},
                           timeout=config.REQUEST_TIMEOUT)
    results = []
    if isinstance(r, dict):
        for item in ((r.get("web") or {}).get("results") or [])[:limit]:
            results.append({"title": item.get("title"), "url": item.get("url"),
                            "snippet": item.get("description") or item.get("snippet")})
    return {"configured": True, "results": results}


# ── sibling FoundryNet Data Network servers (MCP JSON-RPC over HTTP) ──────────
async def call_sibling(server: str, tool: str, arguments: dict) -> dict:
    """Call a sibling MCP server's tool via JSON-RPC 2.0 `tools/call` over its /mcp
    Streamable-HTTP endpoint. Best-effort — returns {"error": …} on any failure so
    the caller can treat the sibling as simply contributing no signal."""
    url = config.SISTER_SERVERS.get(server)
    if not url:
        return {"error": "unknown_server", "detail": server}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}}
    headers = {**_UA, "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    r = await request_json("POST", url, headers=headers, body=body,
                           timeout=config.REQUEST_TIMEOUT)
    if not isinstance(r, dict) or r.get("error"):
        return {"error": "sibling_unreachable", "detail": str(r)[:200], "server": server}
    # MCP tools/call result → {result: {content: [{type:text, text: "..."}], ...}}
    result = r.get("result") or {}
    payload = None
    for block in (result.get("content") or []):
        if block.get("type") == "text" and block.get("text"):
            payload = block["text"]
            break
    return {"server": server, "tool": tool, "structured": result.get("structuredContent"),
            "text": payload}


async def corroborate(domain: str, claim: str) -> dict:
    """Query the sibling server relevant to a claim's domain. Returns a signal dict
    {"server","queried":bool,"hit":bool,"detail"}. `hit` = the sibling returned
    usable corroborating data; failures/empties are non-hits, not disputes."""
    mapping = _DOMAIN_SERVERS.get(domain)
    if not mapping:
        return {"server": None, "queried": False, "hit": False, "detail": "no sibling for domain"}
    server, tool = mapping
    args = _sibling_args(domain, claim)
    res = await call_sibling(server, tool, args)
    if res.get("error"):
        return {"server": server, "queried": True, "hit": False, "detail": res.get("detail")}
    hit = bool(res.get("structured") or res.get("text"))
    return {"server": server, "queried": True, "hit": hit,
            "detail": (res.get("text") or "")[:500] if hit else "no data",
            "structured": res.get("structured")}


def _sibling_args(domain: str, claim: str) -> dict:
    """Best-effort argument shaping for each sibling tool from the raw claim."""
    if domain == "company":
        d = _extract_domain(claim)
        return {"domain": d} if d else {"domain": _first_proper_noun(claim) or claim[:60]}
    if domain == "finance":
        return {"query": claim[:120]}
    if domain == "patents":
        return {"query": claim[:120], "limit": 5}
    if domain == "regulation":
        return {"query": claim[:120], "limit": 5}
    return {"query": claim[:120]}


def _extract_domain(text: str) -> str | None:
    m = re.search(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", text.lower())
    return m.group(1) if m else None


def _first_proper_noun(text: str) -> str | None:
    for tok in re.findall(r"\b[A-Z][A-Za-z0-9&.\-]+\b", text):
        if tok.lower() not in ("the", "a", "an", "this", "that", "is", "was"):
            return tok
    return None


# ── source_check: domain age (RDAP) + heuristics ─────────────────────────────
_HIGH_TRUST_TLDS = {"gov", "edu", "mil", "int"}
_LOW_TRUST_TLDS  = {"info", "biz", "xyz", "top", "click", "buzz", "work"}
_REPUTABLE_HINTS = ("reuters", "apnews", "ap.org", "bbc", "nytimes", "wsj", "npr",
                    "nature", "science", "nih", "who.int", "europa.eu", "gov")
_BIAS_HINTS_HIGH = ("blog", "opinion", "wordpress", "medium.com", "substack",
                    "tumblr", "rumble", "telegram")


async def domain_age(domain: str) -> dict:
    """RDAP lookup for the registration date → age in days. Keyless, best-effort."""
    domain = (domain or "").strip().lower()
    if not domain:
        return {"registered": None, "age_days": None, "source": None}
    url = f"{config.RDAP_BOOTSTRAP.rstrip('/')}/{domain}"
    r = await request_json("GET", url, headers={**_UA, "Accept": "application/rdap+json"},
                           timeout=config.REQUEST_TIMEOUT)
    if not isinstance(r, dict) or r.get("error"):
        return {"registered": None, "age_days": None, "source": "rdap_unavailable"}
    registered = None
    for ev in (r.get("events") or []):
        if ev.get("eventAction") in ("registration", "registered"):
            registered = ev.get("eventDate")
            break
    age_days = None
    if registered:
        try:
            dt = datetime.fromisoformat(registered.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).days
        except Exception:  # noqa: BLE001
            pass
    return {"registered": registered, "age_days": age_days, "source": "rdap"}


def trust_and_bias(url: str, age_days: int | None) -> dict:
    """Transparent heuristic trust signals + bias indicators from a URL/domain."""
    host = (urlparse(url if "://" in url else f"http://{url}").hostname or url or "").lower()
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    trust_signals, bias_indicators = [], []

    if tld in _HIGH_TRUST_TLDS:
        trust_signals.append(f"authoritative TLD .{tld}")
    if tld in _LOW_TRUST_TLDS:
        bias_indicators.append(f"low-reputation TLD .{tld}")
    if any(h in host for h in _REPUTABLE_HINTS):
        trust_signals.append("recognized reputable outlet")
    if any(h in host for h in _BIAS_HINTS_HIGH):
        bias_indicators.append("personal-publishing / opinion platform")
    if age_days is not None:
        if age_days > 3650:
            trust_signals.append("domain >10y old")
        elif age_days < 180:
            bias_indicators.append("domain registered <6 months ago")
    if url.startswith("https://") or "://" not in url:
        trust_signals.append("https")
    else:
        bias_indicators.append("no TLS (http)")

    # 0-100 trust score, transparent and bounded.
    score = 50 + 12 * len(trust_signals) - 15 * len(bias_indicators)
    score = max(0, min(100, score))
    return {"host": host, "tld": tld, "trust_score": score,
            "trust_signals": trust_signals or ["none detected"],
            "bias_indicators": bias_indicators or ["none detected"]}
