"""fact-check-mcp tools — one per file.

  verify_claim  ($0.02)        verify a claim → verdict + confidence + sources
  batch_verify  ($0.01/claim)  verify many claims at once (min $0.05/batch)
  source_check  ($0.01)        assess a source URL's credibility (age/trust/bias)
  daily_brief   ($5)           curated daily fact-check brief (premium, attested)
  mint_info     (free)         FoundryNet Data Network + MINT cross-promo
"""
from . import verify as verify_tool
from . import batch as batch_tool
from . import source as source_tool
from . import daily_brief as daily_brief_tool
from . import mint as mint_tool


def register_all(mcp) -> None:
    for m in (verify_tool, batch_tool, source_tool, daily_brief_tool, mint_tool):
        m.register(mcp)
