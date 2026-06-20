import core


def register(mcp) -> None:
    @mcp.tool
    async def mint_info() -> dict:
        """Get FoundryNet Data Network info + MINT Protocol attestation details. FREE.

        Returns how to attest your agent's fact-verification results with MINT
        Protocol for verifiable on-chain proof, the MINT MCP endpoint, and the sister
        data servers across the full FoundryNet Data Network (financial-signals,
        cyber-intel, patent-intel, gov-contracts, compliance, brand-intel,
        weather-intel, academic-intel, oss-intel, social-intel).
        """
        return core.mint_info()
