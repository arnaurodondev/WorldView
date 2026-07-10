"""Market-sizing tool handler — curated TAM / market-size reference lookup.

Area-2 P3 (chat-enhancement-roadmap): the ``get_market_sizing`` tool exposes a
small, hand-curated, DATED reference table (``market_sizing_reference.yaml``) of
total-addressable-market / served-market-size / segment-share estimates for the
sectors the projection questions touch (semiconductor segments, smartphone,
cloud). It lets a projection GROUND its scenario parameter on a sourced analyst
estimate instead of a bare parametric assumption.

Unlike every other handler this one has NO upstream port — the data is static
curated reference data read from a packaged YAML file. It still returns
``RetrievedItem`` rows exactly like any other tool, so citation resolution +
grounding treat a sizing row like any real tool result:
``[get_market_sizing row N]``.

IMPORTANT — no overclaiming: each returned row is explicitly framed as an
analyst estimate with an as-of date (both in the row text and the source_name),
so the synthesis turn presents it as a dated estimate, never a live spot figure.
"""

from __future__ import annotations

from typing import Any

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler, filter_kwargs_to_signature
from .market_sizing_data import load_market_sizing_reference

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_TOOL_RESULT_MAX_CHARS = 4000

# Trust weight for curated reference data: high enough that a grounded scenario
# parameter is preferred over pretraining memory, but BELOW live/primary tool
# data (e.g. query_fundamentals at 0.88+) because it is a dated analyst estimate,
# not a first-party current figure.
_MARKET_SIZING_TRUST_WEIGHT = 0.72


class MarketSizingHandler(ToolHandler):
    """Handles the ``get_market_sizing`` reference-lookup tool (Area-2 P3).

    Self-contained: reads the packaged curated reference table via
    ``load_market_sizing_reference()`` (cached). No ports, no network.
    """

    _HANDLED_TOOLS = frozenset({"get_market_sizing"})

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        if tool_name != "get_market_sizing":
            raise ValueError(f"MarketSizingHandler cannot handle tool: {tool_name}")
        # BP-622 systemic fix: drop unknown LLM kwargs instead of crashing.
        known, _unknown = filter_kwargs_to_signature(self._handle_get_market_sizing, tool_name, args)
        return await self._handle_get_market_sizing(**known)

    async def _handle_get_market_sizing(
        self,
        query: str | None = None,
        category: str | None = None,
        limit: int = 5,
    ) -> list[RetrievedItem]:
        """Return curated TAM / market-size reference rows matching ``query``.

        Returns [] (graceful) when no curated row matches — the synthesis turn
        then falls back to a labelled low-high assumption (the pre-existing
        behaviour). Never raises on no-match.
        """
        try:
            reference = load_market_sizing_reference()
        except Exception as e:  # pragma: no cover — packaging regression guard
            log.warning("tool_failed", tool="get_market_sizing", error=str(e))
            return []

        rows = reference.search(query=query, category=category, limit=limit)
        if not rows:
            log.info("tool_no_data", tool="get_market_sizing", query=query, category=category)
            return []

        items: list[RetrievedItem] = []
        for row in rows:
            text = row.to_display_text(reference.disclaimer)[:_TOOL_RESULT_MAX_CHARS]
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:market_sizing:{row.id}",
                    item_type=ItemType.financial,
                    text=text,
                    # High relevance (curated to the query) but the TRUST weight
                    # below marks it as estimate-grade, not primary data.
                    score=0.85,
                    trust_weight=_MARKET_SIZING_TRUST_WEIGHT,
                    citation_meta=CitationMeta(
                        title=f"Market sizing (analyst estimate): {row.segment}",
                        url=None,
                        # source_name carries the estimate framing so the citation
                        # chip itself reads as reference data, not a live feed.
                        source_name="market_sizing_reference",
                        published_at=None,
                        entity_name=row.segment,
                    ),
                    grounding_fields=row.grounding_pairs(),
                )
            )

        log.info(
            "tool_executed",
            tool="get_market_sizing",
            query=query,
            category=category,
            rows_returned=len(items),
        )
        return items
