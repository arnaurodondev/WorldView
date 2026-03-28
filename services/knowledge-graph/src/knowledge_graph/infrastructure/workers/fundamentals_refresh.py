"""Worker 13D-3: Fundamentals+OHLCV state embedding refresh (PRD §6.7 Block 13D-3).

30-day schedule.  Only processes ticker entities.

Source text: calls S3 (market-data service) REST API:
  GET /api/v1/fundamentals/{id}
  GET /api/v1/ohlcv/{id}?timeframe=monthly&limit=12
  GET /api/v1/ohlcv/{id}?timeframe=weekly&limit=12

Builds narrative via ``build_fundamentals_narrative()`` (deterministic, no LLM).
S3 down → skip entity (retry next cycle — next_refresh_at not updated).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.utils.fundamentals_narrative import build_fundamentals_narrative
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    VIEW_FUNDAMENTALS,
    sha256_hex,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_REFRESH_INTERVAL_DAYS = 30
_BATCH_LIMIT = 50
_EMBED_MODEL_ID = "nomic-embed-text"


class FundamentalsRefreshWorker:
    """Refreshes fundamentals+OHLCV embeddings for ticker entities (Worker 13D-3).

    Args:
        session_factory: Read/write sessionmaker for intelligence_db.
        llm_client:      FallbackChainClient (embedding path).
        market_data_base_url: Base URL for market-data service REST API.
        http_client:     Optional httpx.AsyncClient (injected for testing).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        market_data_base_url: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._sf = session_factory
        self._llm = llm_client
        self._market_data_url = market_data_base_url.rstrip("/")
        self._http = http_client

    async def run(self) -> None:
        """Refresh fundamentals embeddings due for refresh."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        refreshed = 0
        skipped = 0
        async with self._sf() as session:
            emb_repo = EntityEmbeddingStateRepository(session)
            due = await emb_repo.get_due_for_refresh(VIEW_FUNDAMENTALS, _BATCH_LIMIT)

            for row in due:
                entity_id: UUID = row["entity_id"]  # type: ignore[assignment]
                ticker: str | None = row.get("ticker")  # type: ignore[assignment]
                if not ticker:
                    skipped += 1
                    continue

                narrative = await self._build_fundamentals_narrative(entity_id, str(ticker), row)
                if narrative is None:
                    logger.warning(  # type: ignore[no-any-return]
                        "fundamentals_refresh_market_data_unavailable",
                        entity_id=str(entity_id),
                        ticker=ticker,
                    )
                    continue  # Don't update next_refresh_at — will retry next cycle

                source_hash = sha256_hex(narrative)
                from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

                inp = EmbeddingInput(text=narrative, model_id=_EMBED_MODEL_ID)
                outputs = await self._llm.embed([inp], entity_id=entity_id)
                embedding = outputs[0].embedding if outputs else None

                await emb_repo.upsert(
                    entity_id,
                    VIEW_FUNDAMENTALS,
                    embedding=embedding,
                    model_id=_EMBED_MODEL_ID if embedding else None,
                    source_text=narrative,
                    source_hash=source_hash,
                    next_refresh_at=utc_now() + timedelta(days=_REFRESH_INTERVAL_DAYS),  # type: ignore[no-any-return, operator]
                )
                refreshed += 1

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "fundamentals_refresh_worker_complete",
            refreshed=refreshed,
            skipped_non_ticker=skipped,
        )

    async def _build_fundamentals_narrative(
        self,
        entity_id: UUID,
        ticker: str,
        entity_row: dict[str, Any],
    ) -> str | None:
        """Fetch market data and build the narrative string."""
        import httpx

        http = self._http or httpx.AsyncClient(timeout=10.0)
        try:
            fundamentals = await self._fetch_json(http, f"{self._market_data_url}/api/v1/fundamentals/{entity_id}")
            if fundamentals is None:
                return None

            return build_fundamentals_narrative(
                canonical_name=str(entity_row.get("canonical_name", ticker)),
                entity_type=str(entity_row.get("entity_type", "financial_instrument")),
                revenue_usd_millions=_safe_float(fundamentals, "revenue_usd_millions"),
                gross_margin_pct=_safe_float(fundamentals, "gross_margin_pct"),
                net_margin_pct=_safe_float(fundamentals, "net_margin_pct"),
                pe_ratio=_safe_float(fundamentals, "pe_ratio"),
                price=_safe_float(fundamentals, "price"),
                week_52_high=_safe_float(fundamentals, "week_52_high"),
                week_52_low=_safe_float(fundamentals, "week_52_low"),
                description=fundamentals.get("description"),
            )
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_refresh_http_error",
                entity_id=str(entity_id),
                error=str(exc),
            )
            return None
        finally:
            if self._http is None:
                await http.aclose()

    @staticmethod
    async def _fetch_json(http: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
        try:
            resp = await http.get(url)
            if resp.status_code != 200:
                return None
            return resp.json()  # type: ignore[no-any-return]
        except Exception:
            return None


def _safe_float(d: dict[str, Any], key: str) -> float | None:
    val = d.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
