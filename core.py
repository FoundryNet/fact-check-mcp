"""Shared logic behind the MCP tools + REST routes: 5 operations + x402 gating.

mint_info is free; verify_claim ($0.02), batch_verify ($0.01/claim, min $0.05),
source_check ($0.01) and daily_brief ($5) run payment_gate.precheck(price) first.
verify_claim classifies a claim's domain, cross-references the relevant FoundryNet
Data Network sibling + a general web search, builds a verdict, caches it (24h), and
attaches a MINT provenance attestation. Results are additive — attestation never
blocks delivery (fail-open).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone

import config
import daily_curator
import fact_sources as src
import mint_integration
import payment_gate
import supa

logger = logging.getLogger("fact.core")


def _billing(d):
    g = d.get("gate")
    if g == "free":
        cap, cnt = d.get("cap"), d.get("count")
        return {"tier": "free", "used_today": cnt, "daily_free": cap,
                "remaining_today": (cap - cnt) if (cap is not None and cnt is not None) else None}
    if g == "paid":
        return {"tier": "paid", "charged_usdc": d.get("amount_usdc")}
    if g == "api_key":
        return {"tier": "api_key", "note": "billed to your Forge account"}
    return {"tier": "free", "note": "gating inert"}


def _normalize_claim(claim: str) -> str:
    return re.sub(r"\s+", " ", (claim or "").strip().lower())


def _claim_hash(claim: str, context: str = "") -> str:
    blob = _normalize_claim(claim) + "||" + _normalize_claim(context)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _url_hash(url: str) -> str:
    return hashlib.sha256((url or "").strip().lower().encode("utf-8")).hexdigest()


# ── verify_claim ──────────────────────────────────────────────────────────────
async def _verify_one(claim: str, context: str = "") -> dict:
    """Verify a single claim (no gating, no provenance). Cache-first."""
    claim = (claim or "").strip()
    if not claim:
        return {"error": "bad_request", "detail": "claim is required"}

    chash = _claim_hash(claim, context)
    cached = await supa.fact_check_by_hash(chash, ttl_hours=config.CACHE_TTL_HOURS)
    if cached and cached.get("result"):
        out = dict(cached["result"])
        out["cached"] = True
        return out

    domain = src.classify_claim(claim, context)

    # Source 1: relevant FoundryNet Data Network sibling.
    sibling = await src.corroborate(domain, claim)

    # Source 2: general web search.
    web = await src.web_search(f"{claim} {context}".strip())

    sources, agree, disagree = [], 0, 0
    if sibling.get("queried") and sibling.get("hit"):
        agree += 1
        sources.append({"title": f"{sibling['server']} corroboration",
                        "url": config.SISTER_SERVERS.get(sibling["server"]),
                        "relevance": "high"})
    for item in (web.get("results") or [])[:5]:
        sources.append({"title": item.get("title"), "url": item.get("url"),
                        "relevance": "medium"})
    web_hits = len(web.get("results") or [])
    if web_hits:
        agree += min(web_hits, 3)

    # Verdict synthesis from source agreement.
    if not web.get("configured") and not (sibling.get("queried") and sibling.get("hit")):
        verdict, confidence = "unverifiable", 10
        explanation = ("No search backend is configured (set WEB_SEARCH_API_KEY) and no "
                       "FoundryNet sibling could corroborate this claim, so it cannot be "
                       "verified.")
    elif agree == 0:
        verdict, confidence = "unverifiable", 20
        explanation = ("No corroborating sources were found for this claim across the web "
                       f"search and the {domain} data sources checked.")
    elif disagree > agree:
        verdict, confidence = "disputed", min(60 + 10 * disagree, 95)
        explanation = "Sources disagree with the claim more than they support it."
    else:
        confidence = min(40 + 12 * agree + (15 if sibling.get("hit") else 0), 95)
        verdict = "supported" if confidence >= 55 else "unverifiable"
        parts = []
        if sibling.get("hit"):
            parts.append(f"the {sibling['server']} data source corroborates it")
        if web_hits:
            parts.append(f"{web_hits} web source(s) reference it")
        explanation = ("Verdict from source agreement: " + "; ".join(parts) + "."
                       if parts else "Limited corroboration found.")

    result = {
        "claim": claim, "domain": domain, "verdict": verdict,
        "confidence": int(confidence), "sources": sources,
        "explanation": explanation,
        "checked_at": supa.now_iso(), "cached": False,
    }

    # Cache (best-effort; never blocks delivery).
    await supa.upsert_fact_check({
        "claim_hash": chash, "claim": claim[:2000], "domain": domain,
        "verdict": verdict, "confidence": int(confidence), "result": result,
    })
    return result


async def do_verify_claim(claim, context=None, *, agent_key, payment_tx=None, api_key=None):
    if not (claim or "").strip():
        return {"error": "bad_request", "detail": "claim is required"}
    dec = await payment_gate.precheck("verify_claim", {"claim": claim, "context": context or ""},
                                      config.TOOL_PRICES["verify_claim"], agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    result = await _verify_one(claim, context or "")
    if "error" in result:
        return result
    result["billing"] = _billing(dec)
    result["provenance"] = await asyncio.to_thread(
        mint_integration.attest_data, result, "analysis", f"verify_claim: {result['verdict']}")
    return result


# ── batch_verify ──────────────────────────────────────────────────────────────
def _batch_charge(n: int) -> float:
    return round(max(config.BATCH_MIN_CHARGE, config.BATCH_PER_CLAIM * max(n, 1)), 6)


async def do_batch_verify(claims, *, agent_key, payment_tx=None, api_key=None):
    claims = [c for c in (claims or []) if isinstance(c, str) and c.strip()]
    if not claims:
        return {"error": "bad_request", "detail": "claims (non-empty array of strings) is required"}
    if len(claims) > 50:
        return {"error": "bad_request", "detail": "batch_verify accepts at most 50 claims"}

    # Gate at the table price (consistent with the other paid tools); surface the
    # real per-batch min-charge in the response so the agent sees what it owes.
    charge = _batch_charge(len(claims))
    dec = await payment_gate.precheck("batch_verify", {"claims": claims},
                                      config.TOOL_PRICES["batch_verify"], agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        body = dict(dec["body"])
        body["batch_pricing"] = {"per_claim_usdc": config.BATCH_PER_CLAIM,
                                 "min_charge_usdc": config.BATCH_MIN_CHARGE,
                                 "claims": len(claims), "computed_charge_usdc": charge}
        return body

    results = [await _verify_one(c, "") for c in claims]
    out = {"count": len(results), "results": results,
           "pricing": {"per_claim_usdc": config.BATCH_PER_CLAIM,
                       "min_charge_usdc": config.BATCH_MIN_CHARGE,
                       "computed_charge_usdc": charge},
           "billing": _billing(dec)}
    out["provenance"] = await asyncio.to_thread(
        mint_integration.attest_data, out, "analysis", f"batch_verify: {len(results)} claims")
    return out


# ── source_check ──────────────────────────────────────────────────────────────
async def do_source_check(url, *, agent_key, payment_tx=None, api_key=None):
    url = (url or "").strip()
    if not url:
        return {"error": "bad_request", "detail": "url is required"}
    dec = await payment_gate.precheck("source_check", {"url": url},
                                      config.TOOL_PRICES["source_check"], agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]

    uhash = _url_hash(url)
    cached = await supa.source_check_by_url(uhash, ttl_hours=config.CACHE_TTL_HOURS)
    if cached and cached.get("result"):
        out = dict(cached["result"])
        out["cached"] = True
        out["billing"] = _billing(dec)
        return out

    from urllib.parse import urlparse
    host = (urlparse(url if "://" in url else f"http://{url}").hostname or url).lower()
    age = await src.domain_age(host)
    heur = src.trust_and_bias(url, age.get("age_days"))

    result = {
        "url": url, "domain": host,
        "domain_age": {"registered": age.get("registered"), "age_days": age.get("age_days"),
                       "source": age.get("source")},
        "trust_signals": heur["trust_signals"], "trust_score": heur["trust_score"],
        "bias_indicators": heur["bias_indicators"],
        "publication_history": {"domain_age_days": age.get("age_days"),
                                "registered": age.get("registered"),
                                "note": "derived from RDAP registration + domain heuristics"},
        "checked_at": supa.now_iso(), "cached": False,
    }
    await supa.upsert_source_check({"url_hash": uhash, "url": url[:2000], "domain": host,
                                    "trust_score": heur["trust_score"], "result": result})
    result["billing"] = _billing(dec)
    result["provenance"] = await asyncio.to_thread(
        mint_integration.attest_data, result, "analysis", f"source_check: {host}")
    return result


# ── daily_brief (premium, curated) ────────────────────────────────────────────
async def do_daily_brief(date, *, agent_key, payment_tx=None, api_key=None):
    day = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    dec = await payment_gate.precheck("daily_brief", {"date": day},
                                      config.TOOL_PRICES["daily_brief"], agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    brief = await daily_curator.get_brief(day)
    if not brief:
        return {"error": "not_available",
                "detail": f"No brief for {day} (not yet generated, or expired at midnight UTC). "
                          f"Briefs are curated daily at {config.BRIEF_HOUR_UTC:02d}:00 UTC.",
                "billing": _billing(dec)}
    await daily_curator.bump_purchase(day)
    return {**brief, "billing": _billing(dec)}


def mint_info():
    return {
        "network": "FoundryNet Data Network", **mint_integration.network_feed_block(),
        "message": "Attest your agent's fact-verification results with MINT Protocol for verifiable proof.",
        "mint_protocol": {"mcp_endpoint": config.MINT_MCP_URL, "info_url": config.MINT_INFO_URL,
                          "tools": ["mint_register", "mint_attest", "mint_verify",
                                    "mint_rate", "mint_recommend", "mint_discover"]},
        "see_also": config.SISTER_SERVERS,
    }


# ── Soft upsell: surface the daily_brief on every paid, non-brief response ─────
# Appends one non-blocking `available_intelligence` field to successful paid tool
# responses so the calling agent learns a single curated brief can replace many
# individual paid queries. Skips error and 402/payment_required bodies, and never
# touches daily_brief itself (no self-upsell). Brief status is cached 5 min, so
# this adds no per-call DB latency. Added 2026-06-20 (seller_agent v2 upsell hook).
import time as _upsell_time

_brief_upsell_cache = {"day": None, "ts": 0.0, "available": False, "count": 0}


async def _brief_status_cached() -> tuple[bool, int]:
    day = _upsell_time.strftime("%Y-%m-%d", _upsell_time.gmtime())
    now = _upsell_time.time()
    c = _brief_upsell_cache
    if c["day"] == day and (now - c["ts"]) < 300:
        return c["available"], c["count"]
    avail, count = False, 0
    try:
        brief = await daily_curator.get_brief(day)
        if brief:
            avail, count = True, int(brief.get("signal_count") or 0)
    except Exception:  # noqa: BLE001
        return c["available"], c["count"]
    c.update(day=day, ts=now, available=avail, count=count)
    return avail, count


async def _available_intelligence() -> dict:
    avail, count = await _brief_status_cached()
    return {"daily_brief": {
        "available": avail,
        "signal_count": count,
        "price_usd": config.PRICE_DAILY_BRIEF,
        "tool": "daily_brief",
        "note": "Curated daily intelligence — more efficient than individual queries",
    }}


def _make_upsell(_fn):
    import functools

    @functools.wraps(_fn)
    async def _wrapped(*a, **k):
        result = await _fn(*a, **k)
        if isinstance(result, dict) and "error" not in result and "payment_required" not in result:
            try:
                result["available_intelligence"] = await _available_intelligence()
            except Exception:  # noqa: BLE001
                pass
            try:
                import asyncio as _aio, mint_integration as _mint
                result["foundrynet_network"] = await _aio.to_thread(_mint.network_heartbeat)
            except Exception:  # noqa: BLE001
                pass
        return result

    return _wrapped


for _upsell_fn in ("do_verify_claim", "do_batch_verify", "do_source_check",):
    if _upsell_fn in globals():
        globals()[_upsell_fn] = _make_upsell(globals()[_upsell_fn])
