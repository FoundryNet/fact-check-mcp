"""fact-check-mcp — fact verification for autonomous agents.

Part of the FoundryNet Data Network. Verifies a claim by classifying its domain and
cross-referencing the relevant network data source (brand-intel, financial-signals,
patent-intel, compliance) plus a general web search, returning a verdict
(supported | disputed | unverifiable) with confidence + cited sources. On-demand
with 24h caching. 5 tools + free mint_info. Free tier 10/day, then x402 (USDC on
Solana). Transport: Streamable HTTP at /mcp (+ /sse).
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

import config
import core
import daily_curator
import fact_sources as src
import identity
import payment_gate
import supa
import tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fact.mcp")

if not supa.configured():
    logger.warning("SUPABASE_SERVICE_KEY not set — cache + free-tier ledger disabled until configured.")

mcp = FastMCP("fact-check")

if payment_gate.is_active():
    logger.info(f"pay-per-query ARMED → {config.PAYMENT_RECIPIENT} after {config.FREE_TIER_DAILY}/day free")
else:
    logger.info("pay-per-query INERT — all tools free")

tools.register_all(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok", "service": "fact-check-mcp", "transport": "streamable-http",
        "network": "FoundryNet Data Network",
        "tools": ["verify_claim", "batch_verify", "source_check", "daily_brief", "mint_info"],
        "cache": "supabase:fact_checks" if supa.configured() else "unconfigured",
        "sources": "web_search + foundrynet-data-network siblings",
        "web_search": "set" if src.web_search_configured() else "unset",
        "x402_enabled": config.X402_ENABLED,
        "query_payment": "armed" if payment_gate.is_active() else "free",
        "free_tier_daily": config.FREE_TIER_DAILY,
        "payment_recipient": config.PAYMENT_RECIPIENT,
    })


@mcp.custom_route("/ping", methods=["GET"])
async def ping(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ── REST surface ─────────────────────────────────────────────────────────────
_ERR = {"bad_request": 400, "not_configured": 503, "not_found": 404, "payment_required": 402}


def _resp(d: dict) -> JSONResponse:
    if "error" not in d:
        return JSONResponse(d, status_code=200)
    err = str(d.get("error") or "")
    code = _ERR.get(err, 502 if err in ("network", "non_json_response", "unreachable") else 400)
    if err.startswith("http_") and err[5:].isdigit():
        code = int(err[5:])
    return JSONResponse(d, status_code=code)


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def _akey(request: Request, body: dict) -> str:
    return identity.resolve_agent_key(body.get("agent_id"), request=request)


@mcp.custom_route("/v1/verify", methods=["POST"])
async def rest_verify(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_verify_claim(b.get("claim", ""), b.get("context"),
                                            agent_key=_akey(request, b),
                                            payment_tx=b.get("payment_tx"),
                                            api_key=identity.bearer(request)))


@mcp.custom_route("/v1/batch-verify", methods=["POST"])
async def rest_batch(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_batch_verify(b.get("claims") or [],
                                            agent_key=_akey(request, b),
                                            payment_tx=b.get("payment_tx"),
                                            api_key=identity.bearer(request)))


@mcp.custom_route("/v1/source-check", methods=["POST"])
async def rest_source(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_source_check(b.get("url", ""), agent_key=_akey(request, b),
                                            payment_tx=b.get("payment_tx"),
                                            api_key=identity.bearer(request)))


@mcp.custom_route("/v1/daily-brief", methods=["POST"])
async def rest_brief(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_daily_brief(b.get("date"), agent_key=_akey(request, b),
                                           payment_tx=b.get("payment_tx"),
                                           api_key=identity.bearer(request)))


@mcp.custom_route("/v1/mint-info", methods=["GET", "POST"])
async def rest_mint(request: Request) -> JSONResponse:
    return JSONResponse(core.mint_info())


@mcp.custom_route("/admin/curate", methods=["POST"])
async def admin_curate(request: Request) -> JSONResponse:
    import os
    tok = os.environ.get("ADMIN_TOKEN", "")
    if not tok or request.headers.get("x-admin-token") != tok:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    qp = request.query_params
    date = qp.get("date") or None
    if qp.get("wait") == "1":
        return JSONResponse(await daily_curator.run_curation(date))
    asyncio.create_task(daily_curator.run_curation(date))
    return JSONResponse({"started": True, "date": date})


# ── Discovery ────────────────────────────────────────────────────────────────
_TAGLINE = "Fact verification for agents — verdict, confidence, and cited sources for any claim."
_DESC = ("Fact verification for agents: verify a claim against the FoundryNet Data Network "
         "(brand-intel, financial-signals, patent-intel, compliance) plus a general web search, "
         "returning a verdict (supported/disputed/unverifiable) with confidence and cited "
         "sources. Includes batch verification, source-credibility checks, and a daily brief. "
         "Part of the FoundryNet Data Network — attest results with MINT Protocol.")
_KEYWORDS = ["fact checking", "fact verification", "claim verification", "misinformation",
             "source credibility", "citation checking", "verification"]

_AGENT_CARD = {
    "name": "Fact Verification MCP",
    "description": ("Verify factual claims with a verdict, confidence score, and cited "
                    "sources — cross-referencing web search and the FoundryNet data "
                    "network; supports batch verification and source-trust checks."),
    "url": config.PUBLIC_MCP_URL,
    "version": "1.0.0",
    "capabilities": {"tools": ["verify_claim", "batch_verify", "source_check",
                               "daily_brief", "mint_info"]},
    "provider": {"name": "FoundryNet", "url": "https://foundrynet.io"},
    "network": "FoundryNet Data Network",
    "attestation": {"protocol": "MINT Protocol",
                    "endpoint": "https://mint-mcp-production.up.railway.app/mcp",
                    "verified_outputs": True, "live_feed": "https://mint.foundrynet.io/feed", "feed_api": "https://mint-mcp-production.up.railway.app/v1/feed"},
    "protocols": {"mcp": {"endpoint": config.PUBLIC_MCP_URL, "transport": "streamable-http", "tools_count": 5},
                  "x402": {"supported": True, "currency": "USDC", "network": "solana"}},
    "see_also": config.SISTER_SERVERS, "mint_protocol": config.MINT_MCP_URL,
    "contact": "hello@foundrynet.io",
}


@mcp.custom_route("/.well-known/agent-card.json", methods=["GET"])
async def agent_card(request: Request) -> JSONResponse:
    return JSONResponse(_AGENT_CARD, headers={"Cache-Control": "public, max-age=300"})


@mcp.custom_route("/.well-known/mcp", methods=["GET"])
async def mcp_endpoints(request: Request) -> JSONResponse:
    return JSONResponse({"endpoints": [{"url": config.PUBLIC_MCP_URL, "transport": "streamable-http",
                                        "name": "Fact Verification MCP"}]},
                        headers={"Cache-Control": "public, max-age=300"})


async def _live_tools() -> list:
    res = mcp.list_tools()
    if inspect.iscoroutine(res):
        res = await res
    return [{"name": t.name, "description": (getattr(t, "description", "") or "").strip(),
             "inputSchema": getattr(t, "parameters", None) or {"type": "object"}} for t in res]


@mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"])
async def server_card(request: Request) -> JSONResponse:
    live = await _live_tools()
    return JSONResponse({
        "serverInfo": {"name": "Fact Verification MCP", "version": "1.0.0"},
        "authentication": {"type": "http", "scheme": "bearer",
                           "description": ("mint_info is free; other tools give 10 free "
                                           "verifications/day then take an fnet_ Bearer key OR x402 USDC.")},
        "tools": live, "version": "1.0", "name": "Fact Verification MCP",
        "tagline": _TAGLINE, "description": _DESC,
        "serverUrl": config.PUBLIC_MCP_URL, "transport": "streamable-http",
        "tools_count": len(live),
        "categories": ["research", "fact-checking", "data", "verification", "trust"],
        "keywords": _KEYWORDS, "network": "FoundryNet Data Network",
        "see_also": config.SISTER_SERVERS,
        "pricing": {"model": "metered",
                    "free_tier": f"{config.FREE_TIER_DAILY} verifications/day + free mint_info",
                    "paid_from": f"{config.PRICE_SOURCE_CHECK} USDC per query (x402)"},
    }, headers={"Cache-Control": "public, max-age=300"})


_FREE_TOOL_NAMES = {"mint_info", "macro_dashboard", "cve_detail", "detail",
                    "domain_age", "convert", "rates", "market_overview", "price",
                    "quote", "batch_quote", "sector_performance"}


@mcp.custom_route("/.well-known/mcp.json", methods=["GET"])
async def wellknown_mcp_json(request: Request) -> JSONResponse:
    """Machine-discovery card (emerging standard) for AI clients/crawlers."""
    live = await _live_tools()
    names = [t["name"] for t in live]
    return JSONResponse({
        "name": _AGENT_CARD["name"],
        "description": _AGENT_CARD["description"],
        "url": config.PUBLIC_MCP_URL,
        "transport": ["streamable-http"],
        "tools": names,
        "pricing": {"model": "per-query", "free_tier": True,
                    "paid_tools": [n for n in names if n not in _FREE_TOOL_NAMES]},
        "attestation": {"enabled": True, "protocol": "MINT Protocol",
                        "feed": "https://mint.foundrynet.io/feed"},
        "network": {"name": "FoundryNet Data Network", "servers": 17,
                    "homepage": "https://foundrynet.io"},
    }, headers={"Cache-Control": "public, max-age=300"})


def build_dual_app():
    main_app = mcp.http_app(transport="http", path="/mcp")
    sse_app = mcp.http_app(transport="sse", path="/sse")
    for r in sse_app.routes:
        if getattr(r, "path", None) in ("/sse", "/messages"):
            main_app.router.routes.append(r)
    main_life, sse_life = main_app.router.lifespan_context, sse_app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _dual_lifespan(app):
        async with main_life(app):
            async with sse_life(app):
                # On-demand server: only the daily curator loop runs in-process
                # (no cron aggregator).
                brief_task = asyncio.create_task(daily_curator.curator_loop())
                try:
                    yield
                finally:
                    brief_task.cancel()
                    with contextlib.suppress(Exception):
                        await brief_task
    main_app.router.lifespan_context = _dual_lifespan
    return main_app


if __name__ == "__main__":
    import uvicorn
    logger.info(f"fact-check-mcp starting on 0.0.0.0:{config.PORT} "
                f"(cache={'supabase' if supa.configured() else 'off'}, x402={config.X402_ENABLED})")
    uvicorn.run(build_dual_app(), host="0.0.0.0", port=config.PORT, log_level="warning")
