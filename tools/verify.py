from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def verify_claim(
        claim: str,
        context: Optional[str] = None,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Verify a factual claim. Classifies the claim's domain (company / finance /
        patents / regulation), cross-references the relevant FoundryNet Data Network
        source plus a general web search, and returns a verdict
        (supported | disputed | unverifiable) with a 0-100 confidence, the cited
        sources, and a short explanation. Results carry a MINT provenance attestation
        and are cached for 24h.

        PAID: $0.02 USDC per verification after a daily free allowance (10/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. agent_id scopes your allowance; an Authorization:
        Bearer fnet_ key bypasses it.

        Args:
            claim: the factual statement to verify, e.g. "Acme Corp was founded in 2009".
            context: optional extra context that disambiguates the claim.
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_verify_claim(claim, context,
                                          agent_key=identity.resolve_agent_key(agent_id),
                                          payment_tx=payment_tx, api_key=identity.bearer())
