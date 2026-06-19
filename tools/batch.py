from typing import List, Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def batch_verify(
        claims: List[str],
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Verify many factual claims in one call. Returns an array of verify_claim
        results (verdict + confidence + sources + explanation) plus the batch
        pricing, with a MINT provenance attestation over the whole batch. Each claim
        is cached for 24h, so repeats are cheap.

        PAID: $0.01 USDC per claim, minimum $0.05 USDC per batch, after the daily
        free allowance (10/day). On a 402, pay the returned Solana memo and re-call
        with the SAME args plus payment_tx=<signature>. An Authorization: Bearer
        fnet_ key bypasses it.

        Args:
            claims: array of claim strings (1-50).
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_batch_verify(claims,
                                          agent_key=identity.resolve_agent_key(agent_id),
                                          payment_tx=payment_tx, api_key=identity.bearer())
