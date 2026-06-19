"""Supabase PostgREST client for fact-check-mcp (standalone project)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import config
from http_util import request_json

logger = logging.getLogger("fact.supa")


def configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _headers(extra: Optional[dict] = None) -> dict:
    h = {"apikey": config.SUPABASE_SERVICE_KEY,
         "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
         "Content-Type": "application/json", "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


def _url(path: str) -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{path}"


async def select(table: str, params: dict) -> list:
    if not configured():
        return []
    r = await request_json("GET", _url(table), headers=_headers(), params=params,
                           timeout=config.REQUEST_TIMEOUT)
    return r if isinstance(r, list) else []


async def rpc(fn: str, body: dict):
    if not configured():
        return None
    return await request_json("POST", _url(f"rpc/{fn}"), headers=_headers(), body=body,
                              timeout=config.REQUEST_TIMEOUT)


async def upsert(table: str, rows: list, on_conflict: str) -> dict:
    if not configured() or not rows:
        return {"data": []}
    r = await request_json("POST", _url(table),
                           headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                           params={"on_conflict": on_conflict},
                           body=rows, timeout=max(config.REQUEST_TIMEOUT, 60))
    if isinstance(r, dict) and r.get("error"):
        return r
    return {"data": rows}


async def recent_since(table: str, since_iso: str, *, ts_col: str = "created_at",
                       select_cols: str = "*", order: Optional[str] = None,
                       limit: int = 200) -> list:
    """Rows in `table` with ts_col >= since_iso (used by the daily curator)."""
    p = {"select": select_cols, ts_col: f"gte.{since_iso}", "limit": str(limit)}
    p["order"] = order or f"{ts_col}.desc.nullslast"
    return await select(table, p)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


# ── fact_checks cache ─────────────────────────────────────────────────────────
async def fact_check_by_hash(claim_hash: str, *, ttl_hours: int) -> Optional[dict]:
    """Return a cached fact_check row if it exists and is still fresh, else None."""
    rows = await select("fact_checks", {"select": "*", "claim_hash": f"eq.{claim_hash}",
                                        "order": "checked_at.desc.nullslast", "limit": "1"})
    if not rows:
        return None
    row = rows[0]
    checked = row.get("checked_at")
    if checked:
        try:
            dt = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - dt > timedelta(hours=ttl_hours):
                return None
        except Exception:  # noqa: BLE001
            return None
    return row


async def upsert_fact_check(row: dict) -> dict:
    row = {**row, "checked_at": row.get("checked_at") or now_iso()}
    return await upsert("fact_checks", [row], "claim_hash")


# ── source_checks cache ───────────────────────────────────────────────────────
async def source_check_by_url(url_hash: str, *, ttl_hours: int) -> Optional[dict]:
    rows = await select("source_checks", {"select": "*", "url_hash": f"eq.{url_hash}",
                                          "order": "checked_at.desc.nullslast", "limit": "1"})
    if not rows:
        return None
    row = rows[0]
    checked = row.get("checked_at")
    if checked:
        try:
            dt = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - dt > timedelta(hours=ttl_hours):
                return None
        except Exception:  # noqa: BLE001
            return None
    return row


async def upsert_source_check(row: dict) -> dict:
    row = {**row, "checked_at": row.get("checked_at") or now_iso()}
    return await upsert("source_checks", [row], "url_hash")


# ── free-tier + payments ──────────────────────────────────────────────────────
async def claim_free_query(agent_key: str, day: str, cap: int) -> Optional[dict]:
    r = await rpc("fact_claim_free_query", {"p_agent_key": agent_key, "p_day": day, "p_cap": cap})
    if isinstance(r, dict) and "allowed" in r:
        return r
    if isinstance(r, list) and r and isinstance(r[0], dict):
        return r[0]
    return None


async def payment_tx_used(tx_signature: str) -> bool:
    rows = await select("fact_payments", {"tx_signature": f"eq.{tx_signature}",
                                          "select": "tx_signature", "limit": "1"})
    return bool(rows)


async def insert_payment(row: dict) -> dict:
    if not configured():
        return {"error": "not_configured"}
    r = await request_json("POST", _url("fact_payments"),
                           headers=_headers({"Prefer": "return=minimal"}),
                           body=row, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, dict) and r.get("error"):
        return r
    return {"data": [row]}
