# Fact Verification MCP

**Fact verification for AI agents** — give it a claim, get a **verdict**
(`supported` / `disputed` / `unverifiable`) with a **0-100 confidence** and **cited
sources**. It classifies each claim's domain and cross-references the FoundryNet
Data Network plus a general web search.

> Part of the **FoundryNet Data Network**. Attest your agent's verification results
> with [MINT Protocol](https://mint-mcp-production.up.railway.app/mcp). See also:
> **financial-signals-mcp**, **cyber-intel-mcp**, **patent-intel-mcp**,
> **gov-contracts-mcp**, **compliance-mcp**, **brand-intel-mcp**,
> **weather-intel-mcp**, **academic-intel-mcp**, **oss-intel-mcp**,
> **social-intel-mcp**.

## Connect

- **MCP endpoint** (Streamable HTTP): `https://fact-check-mcp-production.up.railway.app/mcp`
- **Registry:** `io.github.FoundryNet/fact-check-mcp`
- **Agent card:** `https://fact-check-mcp-production.up.railway.app/.well-known/agent-card.json`

### Claude Desktop / Cursor / Claude Code

```bash
claude mcp add --transport http fact-check https://fact-check-mcp-production.up.railway.app/mcp
```

```json
{ "mcpServers": { "fact-check": { "url": "https://fact-check-mcp-production.up.railway.app/mcp" } } }
```

## Tools

| Tool | Price | What it does |
|---|---|---|
| `verify_claim` | $0.02 | Verify a claim → verdict, confidence, cited sources, explanation |
| `batch_verify` | $0.01/claim (min $0.05) | Verify many claims in one call |
| `source_check` | $0.01 | Assess a source URL — domain age (RDAP), trust signals, bias indicators |
| `daily_brief` | $5 | Curated daily brief — top disputed/most-verified claims, trending topics |
| `mint_info` | **free** | FoundryNet Data Network + MINT Protocol |

**Free tier:** 10 verifications/day per agent. Then x402: the tool returns an
HTTP-402 with a Solana USDC payment memo — pay it, re-call with the same args plus
`payment_tx=<signature>`. An `Authorization: Bearer fnet_…` key bypasses the paywall.

## How it works

Each claim is classified by domain and cross-referenced against the most relevant
FoundryNet data source **and** a general web search:

- **company** claims → `brand-intel-mcp`
- **finance** claims → `financial-signals-mcp`
- **patents** claims → `patent-intel-mcp`
- **regulation** claims → `compliance-mcp`

The verdict is synthesized from source agreement and returned with the citations
that drove it. Results are **cached for 24h** (keyed by a normalized-claim hash) and
carry a **MINT provenance attestation** so a buyer can verify the result was produced
by this server, unaltered.

> The general web-search backend needs a `WEB_SEARCH_API_KEY` (Brave Search API).
> Without it, claims with no FoundryNet corroboration return `unverifiable` with a
> note rather than a guess.

## Sources

On demand: a general **web search** (Brave Search API) + the **FoundryNet Data
Network** sibling servers (called over their public MCP endpoints). Source-credibility
checks use keyless **RDAP** for domain age. Cached in a standalone Supabase project.

## Discovery

MCP registry: `io.github.FoundryNet/fact-check-mcp`

Built by [FoundryNet](https://foundrynet.io) · hello@foundrynet.io

## Live network activity

**Live feed:** [mint.foundrynet.io/feed](https://mint.foundrynet.io/feed)  
Real-time verified work across 13 servers and autonomous agents, anchored on Solana via [MINT Protocol](https://mint.foundrynet.io).
