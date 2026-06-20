"""Env-driven configuration for fact-check-mcp.

Fact verification for autonomous agents: cross-references a claim against the
FoundryNet Data Network (brand-intel, financial-signals, patent-intel, compliance,
…) plus a general web search, and returns a verdict (supported / disputed /
unverifiable) with confidence + cited sources. On-demand with caching, in its own
standalone Supabase project. 5 tools, x402 metered. Part of the FoundryNet Data
Network.

Required to be useful:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   the standalone fact-check project.
Optional:
  WEB_SEARCH_API_KEY / BRAVE_API_KEY   general web-search backend; degrades to
                                       "unverifiable" with a note when unset.
  PORT, REQUEST_TIMEOUT
  X402_ENABLED, SOLANA_WALLET, PAYMENT_RECIPIENT, PAYMENT_VERIFY_RPC,
  PAYMENT_USDC_MINT, PAYMENT_EXPIRY_SECONDS
  FREE_TIER_DAILY      default 10
  CACHE_TTL_HOURS      fact-check cache freshness window, default 24
  PRICE_*              per-tool USDC prices
"""
from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _flag(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


SUPABASE_URL         = _env("SUPABASE_URL", "https://kpfxkkpqmbabdkzznhaa.supabase.co").rstrip("/")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")

PORT            = int(_env("PORT", "8080"))
REQUEST_TIMEOUT = int(_env("REQUEST_TIMEOUT", "30"))

# ── Sources ──────────────────────────────────────────────────────────────────
# General web search backend (optional). Brave Search API by default; any keyless
# fallback degrades gracefully to "unverifiable" with a note.
WEB_SEARCH_API     = _env("WEB_SEARCH_API", "https://api.search.brave.com/res/v1/web/search")
WEB_SEARCH_API_KEY = _env("WEB_SEARCH_API_KEY") or _env("BRAVE_API_KEY")
SOURCE_USER_AGENT  = _env("SOURCE_USER_AGENT", "FoundryNet Data Network hello@foundrynet.io")
# RDAP for domain-age lookups in source_check (keyless).
RDAP_BOOTSTRAP     = _env("RDAP_BOOTSTRAP", "https://rdap.org/domain")

CACHE_TTL_HOURS = int(_env("CACHE_TTL_HOURS", "24"))

# ── x402 per-tool pricing ────────────────────────────────────────────────────
X402_ENABLED      = _flag("X402_ENABLED", True)
SOLANA_WALLET     = _env("SOLANA_WALLET", "wUumjWWvtFEr69qkTw3wHNVQVxLA8DTyJSyVgGmLThd")
PAYMENT_RECIPIENT = _env("PAYMENT_RECIPIENT", SOLANA_WALLET).strip()
PAYMENT_VERIFY_RPC = _env("PAYMENT_VERIFY_RPC", "https://api.mainnet-beta.solana.com").rstrip("/")
PAYMENT_USDC_MINT  = _env("PAYMENT_USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").strip()
PAYMENT_EXPIRY_SECONDS = int(_env("PAYMENT_EXPIRY_SECONDS", "300"))

FREE_TIER_DAILY = int(_env("FREE_TIER_DAILY", "10"))

PRICE_VERIFY_CLAIM = float(_env("PRICE_VERIFY_CLAIM", "0.02"))
PRICE_BATCH_VERIFY = float(_env("PRICE_BATCH_VERIFY", "0.05"))   # representative; per-claim min computed in core
PRICE_SOURCE_CHECK = float(_env("PRICE_SOURCE_CHECK", "0.01"))
PRICE_DAILY_BRIEF  = float(_env("PRICE_DAILY_BRIEF", "5"))
# Batch min-charge floor + per-claim rate (real charge surfaced in the result).
BATCH_PER_CLAIM    = float(_env("BATCH_PER_CLAIM", "0.01"))
BATCH_MIN_CHARGE   = float(_env("BATCH_MIN_CHARGE", "0.05"))

# Per-tool price table (mirrors the gate's price-threading convention).
TOOL_PRICES = {
    "verify_claim": PRICE_VERIFY_CLAIM,
    "batch_verify": PRICE_BATCH_VERIFY,
    "source_check": PRICE_SOURCE_CHECK,
    "daily_brief":  PRICE_DAILY_BRIEF,
    "mint_info":    0.0,
}

# ── Daily curated brief ──────────────────────────────────────────────────────
BRIEF_HOUR_UTC = int(_env("BRIEF_HOUR_UTC", "5"))   # curator runs at 05:00 UTC
SERVER_SLUG    = "fact-check"
# Cross-network brief catalog (server -> price) for related_briefs.
NETWORK_BRIEFS = {
    "financial-signals": "$25", "cyber-intel": "$15", "patent-intel": "$10",
    "gov-contracts": "$10", "compliance": "$10", "brand-intel": "$5", "weather-intel": "$5",
    "fact-check": "$5", "oss-intel": "$5", "social-intel": "$5",
}

# ── FoundryNet Data Network cross-promo ──────────────────────────────────────
MINT_MCP_URL  = _env("MINT_MCP_URL", "https://mint-mcp-production.up.railway.app/mcp")
MINT_INFO_URL = _env("MINT_INFO_URL", "https://mint.foundrynet.io")
# All OTHER network servers verify_claim can cross-reference (and cross-promo).
SISTER_SERVERS = {
    "mint-mcp":                "https://mint-mcp-production.up.railway.app/mcp",
    "foundrynet-mcp":          "https://foundrynet-mcp-production.up.railway.app/mcp",
    "gov-contracts-mcp":       "https://gov-contracts-mcp-production.up.railway.app/mcp",
    "brand-intel-mcp":         "https://brand-intel-mcp-production.up.railway.app/mcp",
    "patent-intel-mcp":        "https://patent-intel-mcp-production.up.railway.app/mcp",
    "financial-signals-mcp":   "https://financial-signals-mcp-production.up.railway.app/mcp",
    "weather-intel-mcp":       "https://weather-intel-mcp-production.up.railway.app/mcp",
    "cyber-intel-mcp":         "https://cyber-intel-mcp-production.up.railway.app/mcp",
    "compliance-mcp":          "https://compliance-mcp-production.up.railway.app/mcp",
    "academic-intel-mcp":      "https://academic-intel-mcp-production.up.railway.app/mcp",
    "oss-intel-mcp":           "https://oss-intel-mcp-production.up.railway.app/mcp",
    "social-intel-mcp":        "https://social-intel-mcp-production.up.railway.app/mcp",
    "crypto-intel-mcp":        "https://crypto-intel-mcp-production.up.railway.app/mcp",
    "market-data-mcp":         "https://market-data-mcp-production.up.railway.app/mcp",
    "email-verify-mcp":        "https://email-verify-mcp-production.up.railway.app/mcp",
    "currency-intel-mcp":      "https://currency-intel-mcp-production.up.railway.app/mcp",
}

PUBLIC_MCP_URL = _env("PUBLIC_MCP_URL", "https://fact-check-mcp-production.up.railway.app/mcp")
