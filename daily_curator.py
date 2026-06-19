"""Daily curated brief — fact-check.

Runs once a day at BRIEF_HOUR_UTC (05:00 UTC) as an in-process background task. It
queries the last 24h of `fact_checks`, packages the most disputed / most verified
claims + trending checked topics, attests the package through MINT for verifiable
provenance, and upserts it into the `daily_briefs` table. The paid `daily_brief`
tool just reads that row back.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import config
import mint_integration
import supa

logger = logging.getLogger("fact.curator")

SERVER = config.SERVER_SLUG
PRICE = config.PRICE_DAILY_BRIEF

_STOPWORDS = {"the", "a", "an", "is", "was", "are", "were", "of", "to", "in", "on",
              "for", "and", "or", "that", "this", "with", "by", "at", "from", "as",
              "it", "its", "be", "has", "have", "had", "will", "not", "claim"}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _expires_at(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (d + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")


def related_briefs(exclude: str) -> list:
    return [{"server": s, "price": p, "tool": "daily_brief"}
            for s, p in config.NETWORK_BRIEFS.items() if s != exclude]


def _topics(claims: list[str]) -> list[dict]:
    words: Counter = Counter()
    for c in claims:
        for w in re.findall(r"[a-z0-9]{4,}", (c or "").lower()):
            if w not in _STOPWORDS:
                words[w] += 1
    return [{"topic": w, "mentions": n} for w, n in words.most_common(10)]


async def _curate_signals(since_iso: str) -> tuple[dict, int]:
    """Build the fact-check brief body from the last 24h. Returns (signals, count)."""
    rows = await supa.recent_since(
        "fact_checks", since_iso, ts_col="checked_at",
        select_cols="claim,domain,verdict,confidence,checked_at",
        order="checked_at.desc.nullslast", limit="500")

    disputed = [r for r in rows if r.get("verdict") == "disputed"]
    supported = [r for r in rows if r.get("verdict") == "supported"]
    unverifiable = [r for r in rows if r.get("verdict") == "unverifiable"]

    disputed.sort(key=lambda r: r.get("confidence") or 0, reverse=True)
    supported.sort(key=lambda r: r.get("confidence") or 0, reverse=True)

    top_disputed_claims = [{"claim": r.get("claim"), "domain": r.get("domain"),
                            "confidence": r.get("confidence")} for r in disputed[:10]]
    most_verified = [{"claim": r.get("claim"), "domain": r.get("domain"),
                      "confidence": r.get("confidence")} for r in supported[:10]]
    trending_topics_checked = _topics([r.get("claim") for r in rows])

    by_domain = Counter(r.get("domain") or "general" for r in rows)

    signals = {
        "top_disputed_claims": top_disputed_claims,
        "most_verified": most_verified,
        "trending_topics_checked": trending_topics_checked,
        "counts": {"total_checks": len(rows), "disputed": len(disputed),
                   "supported": len(supported), "unverifiable": len(unverifiable),
                   "by_domain": dict(by_domain)},
    }
    count = len(top_disputed_claims) + len(most_verified) + len(trending_topics_checked)
    return signals, count


async def run_curation(date_str: str | None = None) -> dict:
    """Generate, attest, and store today's brief. Idempotent per date (upsert)."""
    date_str = date_str or _today()
    since_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    signals, count = await _curate_signals(since_iso)

    brief = {
        "brief_date": date_str, "server": SERVER, "signal_count": count,
        "signals": signals, "expires_at": _expires_at(date_str),
        "related_briefs": related_briefs(SERVER),
    }
    # Attest for provenance (sync httpx → run off the event loop; fail-open).
    attestation = await asyncio.to_thread(
        mint_integration.attest_data, brief, "analysis",
        f"Daily {SERVER} brief: {count} signals")
    brief["provenance"] = attestation

    row = {
        "brief_date": date_str, "brief_data": brief, "signal_count": count,
        "attestation_hash": attestation.get("attestation_hash"),
        "expires_at": _expires_at(date_str),
    }
    res = await supa.upsert("daily_briefs", [row], "brief_date")
    if isinstance(res, dict) and res.get("error"):
        logger.warning(f"daily brief upsert failed: {str(res)[:200]}")
    else:
        logger.info(f"daily brief stored: {date_str} ({count} signals, "
                    f"attested={attestation.get('mint_verified')})")
    return brief


async def get_brief(date_str: str | None = None) -> dict | None:
    """Read a stored brief; None if missing or expired."""
    date_str = date_str or _today()
    rows = await supa.select("daily_briefs",
                             {"select": "*", "brief_date": f"eq.{date_str}", "limit": "1"})
    if not rows:
        return None
    row = rows[0]
    exp = row.get("expires_at")
    if exp:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(exp.replace("Z", "+00:00")):
                return None
        except Exception:  # noqa: BLE001
            pass
    return row.get("brief_data")


async def bump_purchase(date_str: str) -> None:
    """Best-effort purchase counter via RPC (no-op if the function is absent)."""
    try:
        await supa.rpc("increment_brief_purchase", {"p_brief_date": date_str})
    except Exception:  # noqa: BLE001
        pass


async def curator_loop() -> None:
    """Sleep until BRIEF_HOUR_UTC each day, then curate. Cancellable."""
    while True:
        now = datetime.now(timezone.utc)
        secs = now.hour * 3600 + now.minute * 60 + now.second
        wait = (config.BRIEF_HOUR_UTC * 3600 - secs) % 86400 or 86400
        try:
            await asyncio.sleep(wait)
            if supa.configured():
                await run_curation()
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"curator loop error: {e}")
            await asyncio.sleep(3600)
