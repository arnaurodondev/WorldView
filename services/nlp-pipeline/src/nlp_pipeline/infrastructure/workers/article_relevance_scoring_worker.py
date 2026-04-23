"""ArticleRelevanceScoringWorker — LLM-based article relevance scorer (PRD-0026 §6.7 Flow B).

Periodically fetches unscored articles (MEDIUM/DEEP routing tier, no llm_relevance_score)
from nlp_db and uses Qwen2.5:3b via Ollama to assign a 0-1 relevance score stored back
in document_source_metadata.

Key design invariants:
  - R24: DB session closed BEFORE any Ollama HTTP call.
  - Score clamped to [0.0, 1.0] always.
  - JSON parse failures skip the article (not the cycle).
  - httpx.ConnectError or timeout skips the ENTIRE cycle (Ollama unavailable).
  - Uses COALESCE(rd.final_routing_tier, rd.routing_tier) for tier check.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING
from uuid import UUID

import httpx

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sqlalchemy import text

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Prompt sent to Ollama for relevance scoring (PRD-0026 §6.5 exact spec)
_SYSTEM_PROMPT = (
    "You are a financial news relevance assessor. "
    "Rate the market impact of this news article from 0.0 to 1.0.\n"
    "0.0 = completely irrelevant (celebrity news, sports, weather)\n"
    "0.3 = mildly relevant (broad economy, far sector)\n"
    "0.6 = moderately relevant (sector news, indirect exposure)\n"
    "0.9 = highly relevant (direct earnings, M&A, regulatory action)\n"
    "1.0 = critical (halted trading, major earnings miss, bankruptcy)\n"
    'Respond with ONLY valid JSON: {"score": <float 0.0-1.0>, "reason": "<max 10 words>"}'
)


class ArticleRelevanceScoringWorker:
    """Background worker that scores articles with LLM-based relevance using Qwen2.5:3b."""

    def __init__(
        self,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        ollama_url: str,
        model: str,
        batch_size: int = 50,
        timeout_seconds: int = 30,
        cycle_seconds: int = 1800,
    ) -> None:
        self._nlp_sf = nlp_session_factory
        self._ollama_url = ollama_url.rstrip("/")
        self._model = model
        self._batch_size = batch_size
        self._timeout = float(timeout_seconds)
        self._cycle_seconds = cycle_seconds

    # ── Public API ────────────────────────────────────────────────────────────

    async def scoring_cycle(self) -> int:
        """Run one scoring cycle.

        Returns the number of articles scored and written.
        """
        # ── Phase 1 — Read: fetch unscored articles (session closed before HTTP) ──
        async with self._nlp_sf() as session:
            articles = await self._fetch_unscored_articles(session)
        # Session is closed here — DB released BEFORE any Ollama HTTP calls (R24).

        if not articles:
            return 0

        # ── Phase 2 — Score: call Ollama for each article (no open DB sessions) ───
        scored: list[tuple[UUID, float]] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for doc_id, title, source_type in articles:
                    score = await self._call_ollama(client, title, source_type, doc_id)
                    if score is not None:
                        scored.append((doc_id, score))
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            # Ollama unavailable — skip the entire cycle; try again next interval
            logger.warning(  # type: ignore[no-any-return]
                "relevance_scoring_ollama_unavailable",
                error=str(exc),
            )
            return 0

        if not scored:
            return 0

        # ── Phase 3 — Write: persist scores in a fresh session ───────────────
        async with self._nlp_sf() as session:
            await self._write_scores(session, scored)
            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "relevance_scoring_cycle_done",
            articles_scored=len(scored),
            articles_fetched=len(articles),
        )
        return len(scored)

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Run scoring cycles until *stop* is set."""
        while not stop.is_set():
            try:
                count = await self.scoring_cycle()
                if count:
                    logger.info(  # type: ignore[no-any-return]
                        "relevance_scoring_batch_done",
                        count=count,
                    )
            except Exception as exc:
                logger.warning(  # type: ignore[no-any-return]
                    "relevance_scoring_poll_error",
                    error=str(exc),
                    exc_info=True,
                )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._cycle_seconds)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _fetch_unscored_articles(
        self,
        session: AsyncSession,
    ) -> list[tuple[UUID, str | None, str | None]]:
        """Phase 1: fetch MEDIUM/DEEP-tier articles without llm_relevance_score."""
        stmt = text(
            """
            SELECT dsm.doc_id, dsm.title, dsm.source_type
            FROM document_source_metadata dsm
            JOIN routing_decisions rd ON rd.doc_id = dsm.doc_id
            WHERE dsm.llm_relevance_score IS NULL
              AND COALESCE(rd.final_routing_tier, rd.routing_tier) IN ('MEDIUM', 'DEEP')
            ORDER BY dsm.published_at DESC
            LIMIT :batch_size
            """,
        )
        result = await session.execute(stmt, {"batch_size": self._batch_size})
        return [(UUID(str(row.doc_id)), row.title, row.source_type) for row in result.fetchall()]

    async def _call_ollama(
        self,
        client: httpx.AsyncClient,
        title: str | None,
        source_type: str | None,
        doc_id: UUID,
    ) -> float | None:
        """Phase 2 helper: POST one article to Ollama and parse the score.

        Returns None on JSON parse failure (article skipped, cycle continues).
        Raises httpx.ConnectError or httpx.TimeoutException → caller skips cycle.
        """
        prompt = _SYSTEM_PROMPT + f"\nUser: Title: {title or 'Unknown'}\nSource: {source_type or 'Unknown'}"
        resp = await client.post(
            f"{self._ollama_url}/api/generate",
            json={"model": self._model, "prompt": prompt, "format": "json", "stream": False},
        )
        raw = resp.text
        try:
            data = json.loads(raw)
            # Ollama wraps the model output in a "response" field when format=json
            inner = data.get("response", raw)
            parsed = json.loads(inner) if isinstance(inner, str) else inner
            score = float(parsed["score"])
            return max(0.0, min(1.0, score))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.warning(  # type: ignore[no-any-return]
                "relevance_scoring_json_parse_error",
                article_id=str(doc_id),
                error=str(exc),
                raw_response=raw[:200],
            )
            return None

    @staticmethod
    async def _write_scores(
        session: AsyncSession,
        scored: list[tuple[UUID, float]],
    ) -> None:
        """Phase 3: write llm_relevance_score + llm_scored_at for each scored article."""
        stmt = text(
            """
            UPDATE document_source_metadata
            SET llm_relevance_score = :score,
                llm_scored_at       = NOW()
            WHERE doc_id = :doc_id
            """,
        )
        for doc_id, score in scored:
            await session.execute(stmt, {"doc_id": str(doc_id), "score": score})
