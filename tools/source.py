from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def source_check(
        url: str,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Check a source URL's credibility and trustworthiness for source verification
        — domain age (via RDAP), trust signals, bias indicators, and publication
        history. Use it to weight whether a citation is trustworthy. Results carry a
        MINT provenance attestation and are cached for 24h.

        PAID: $0.01 USDC per check after the daily free allowance (10/day). On a 402,
        pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            url: the source URL or domain to assess, e.g. "https://reuters.com/...".
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_source_check(url, agent_key=identity.resolve_agent_key(agent_id),
                                          payment_tx=payment_tx, api_key=identity.bearer())
