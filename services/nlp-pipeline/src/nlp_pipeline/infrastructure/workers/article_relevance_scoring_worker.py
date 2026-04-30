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
import hashlib
import json
import time
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# PLAN-0055 C-2: bump this constant whenever the LLM prompt template changes so
# downstream consumers (replay worker, materialized view) treat scores from the
# new prompt as a different lineage.
_RELEVANCE_PROMPT_VERSION: str = "v1"

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Prompt sent to the LLM for relevance scoring + sentiment classification.
#
# F-Q1-07 fix (PLAN-0050 QA iter-1): appended "sentiment" field extraction to
# the SAME LLM call so we write both llm_relevance_score and sentiment in one
# round-trip rather than adding a separate SentimentClassifierWorker.
# The sentiment token set is constrained to four values so the LLM cannot
# hallucinate a non-enum value — the writer validates before persisting.
# Adding "sentiment" alongside (not instead of) "score" keeps the relevance
# scoring contract (PRD-0026 §6.5) unchanged.
_SYSTEM_PROMPT = (
    "You are a financial news relevance assessor. "
    "Rate the market impact of this news article from 0.0 to 1.0.\n"
    "0.0 = completely irrelevant (celebrity news, sports, weather)\n"
    "0.3 = mildly relevant (broad economy, far sector)\n"
    "0.6 = moderately relevant (sector news, indirect exposure)\n"
    "0.9 = highly relevant (direct earnings, M&A, regulatory action)\n"
    "1.0 = critical (halted trading, major earnings miss, bankruptcy)\n"
    "If the title is absent, vague, or ambiguous, return score 0.3 as a conservative default.\n"
    "Also classify the market sentiment: "
    '"positive" (good news for investors), '
    '"negative" (bad news for investors), '
    '"neutral" (factual/no clear direction), '
    '"mixed" (contains both positive and negative signals).\n'
    "Respond with ONLY valid JSON: "
    '{"score": <float 0.0-1.0>, "reason": "<max 10 words in English>", '
    '"sentiment": "positive"|"negative"|"neutral"|"mixed"}'
)

# Valid sentiment enum values — reject anything the LLM hallucinates.
_VALID_SENTIMENTS = frozenset({"positive", "negative", "neutral", "mixed"})


class ArticleRelevanceScoringWorker:
    """Background worker that scores articles with LLM-based relevance using Qwen2.5:3b.

    When *api_key* is non-empty the worker calls DeepInfra (OpenAI-compatible chat
    completions) instead of the local Ollama instance.  The Ollama path remains fully
    intact as the fallback when *api_key* is empty (default — backward compatible).
    """

    def __init__(
        self,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        ollama_url: str,
        model: str,
        batch_size: int = 50,
        timeout_seconds: int = 30,
        cycle_seconds: int = 1800,
        *,
        api_key: str = "",
        api_base_url: str = "https://api.deepinfra.com/v1/openai",
        api_model_id: str = "Qwen/Qwen2.5-0.5B-Instruct",
        usage_logger: LlmUsageLogProtocol | None = None,
    ) -> None:
        self._nlp_sf = nlp_session_factory
        self._ollama_url = ollama_url.rstrip("/")
        self._model = model
        self._batch_size = batch_size
        self._timeout = float(timeout_seconds)
        self._cycle_seconds = cycle_seconds
        # DeepInfra / OpenAI-compat provider fields (empty → use Ollama)
        self._api_key = api_key
        self._api_base_url = api_base_url.rstrip("/")
        self._api_model_id = api_model_id
        # PLAN-0057 A-5 / F-CRIT-03: optional cost/latency logger.  When wired,
        # every Ollama / DeepInfra HTTP call (success OR failure) appends one
        # row to nlp_db.llm_usage_log so we can audit pipeline LLM spend.
        self._usage_logger = usage_logger

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

        # ── Phase 2 — Score: call LLM for each article (no open DB sessions) ────
        # Branches on api_key: DeepInfra OpenAI-compat endpoint when set, Ollama otherwise.
        # F-Q1-07: each scored tuple now carries (doc_id, score, sentiment | None)
        # so we can persist both fields in a single write call.
        # PLAN-0055 C-2: also carry input_hash so the append-only ledger can verify
        # exact input lineage. We hash (title, source_type) since the LLM prompt is
        # deterministic on those (title-only prompt — see PRD-0026).
        scored: list[tuple[UUID, float, str | None, str]] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for doc_id, title, source_type in articles:
                    if self._api_key:
                        result = await self._call_external_api(client, title, source_type, doc_id)
                    else:
                        result = await self._call_ollama(client, title, source_type, doc_id)
                    if result is not None:
                        score, sentiment = result
                        input_hash = hashlib.sha256(f"{title}\x00{source_type or ''}".encode()).hexdigest()
                        scored.append((doc_id, score, sentiment, input_hash))
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            # Provider unavailable — skip the entire cycle; try again next interval
            logger.warning(  # type: ignore[no-any-return]
                "relevance_scoring_provider_unavailable",
                error=str(exc),
            )
            return 0

        if not scored:
            return 0

        # ── Phase 3 — Write: persist scores in a fresh session ───────────────
        # PLAN-0055 C-2: dual-write. Legacy UPDATE keeps the news read path
        # working until Wave C-3 wires the materialized view; the append-only
        # INSERT establishes the audit trail going forward.
        model_id_for_provenance = self._api_model_id if self._api_key else self._model
        async with self._nlp_sf() as session:
            await self._write_scores(session, scored)
            await self._append_provenance(session, scored, model_id_for_provenance)
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
        # F-DP1-04 (PLAN-0050 QA deep iter-1): RoutingTier StrEnum stores
        # lowercase values ('medium', 'deep') — see domain/enums.py:50.  Earlier
        # this filter compared against uppercase 'MEDIUM'/'DEEP', matching zero
        # rows so the worker silently idled across all 2,956 articles.
        # WHY case-insensitive: be defensive against either future enum changes
        # or migrations that normalize to a different case.
        stmt = text(
            """
            SELECT dsm.doc_id, dsm.title, dsm.source_type
            FROM document_source_metadata dsm
            JOIN routing_decisions rd ON rd.doc_id = dsm.doc_id
            WHERE dsm.llm_relevance_score IS NULL
              AND LOWER(COALESCE(rd.final_routing_tier, rd.routing_tier)) IN ('medium', 'deep')
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
    ) -> tuple[float, str | None] | None:
        """Phase 2 helper: POST one article to Ollama and parse score + sentiment.

        F-Q1-07: returns (score, sentiment) tuple so both values are written in
        Phase 3.  Sentiment is None if the LLM omits the field or returns an
        unexpected value (write is still performed with sentiment=NULL in that case).

        Returns None on JSON parse failure (article skipped, cycle continues).
        Raises httpx.ConnectError or httpx.TimeoutException → caller skips cycle.
        """
        prompt = _SYSTEM_PROMPT + f"\nUser: Title: {title or 'Unknown'}\nSource: {source_type or 'Unknown'}"
        # PLAN-0057 A-5: capture latency for the usage log; wall-clock perf_counter
        # is sufficient because the call is bounded by httpx timeout above.
        t0 = time.perf_counter()
        resp = await client.post(
            f"{self._ollama_url}/api/generate",
            # BP-231: qwen3 is a thinking model — "think": False disables reasoning mode,
            # dropping inference from 90-146s to ~2-5s on CPU. Required for non-chat use cases.
            json={
                "model": self._model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "think": False,
                # BP-121 variant: qwen3:0.6b defaults to n_ctx=32768 → GGML_ASSERT abort on CPU.
                # Relevance prompts are title+source_type, always < 100 tokens; 512 is ample.
                # WHY 768 (up from 512): the extended prompt (with sentiment instruction) is
                # ~50 tokens longer; 768 provides enough headroom without enabling full reasoning.
                "options": {"num_ctx": 768},
            },
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        raw = resp.text
        # success-from-status: HTTP 2xx implies the *transport* succeeded.  JSON-parse
        # success is reflected separately by the return value (None = parse failure).
        http_success = 200 <= resp.status_code < 300
        try:
            data = json.loads(raw)
            # Ollama wraps the model output in a "response" field when format=json
            inner = data.get("response", raw)
            parsed = json.loads(inner) if isinstance(inner, str) else inner
            score = float(parsed["score"])
            # F-Q1-07: extract sentiment — default to None if missing or not a valid enum.
            raw_sentiment = parsed.get("sentiment", "")
            sentiment: str | None = raw_sentiment if raw_sentiment in _VALID_SENTIMENTS else None
            await self._record_usage(
                provider="ollama",
                model_id=self._model,
                latency_ms=latency_ms,
                success=http_success,
                tokens_in=len(prompt.split()),
                tokens_out=len(raw.split()),
                doc_id=doc_id,
            )
            return max(0.0, min(1.0, score)), sentiment
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.warning(  # type: ignore[no-any-return]
                "relevance_scoring_json_parse_error",
                article_id=str(doc_id),
                error=str(exc),
                raw_response=raw[:200],
            )
            await self._record_usage(
                provider="ollama",
                model_id=self._model,
                latency_ms=latency_ms,
                success=False,
                tokens_in=len(prompt.split()),
                tokens_out=0,
                doc_id=doc_id,
                error_code="model_error",
            )
            return None

    async def _call_external_api(
        self,
        client: httpx.AsyncClient,
        title: str | None,
        source_type: str | None,
        doc_id: UUID,
    ) -> tuple[float, str | None] | None:
        """Phase 2 helper: POST one article to DeepInfra (OpenAI-compat) and parse score + sentiment.

        F-Q1-07: returns (score, sentiment) tuple.  Sentiment is None when the LLM
        omits the field or returns an invalid value.

        Uses the chat/completions endpoint with response_format=json_object so the model
        returns a JSON payload directly (no "response" wrapper like Ollama uses).

        Returns None on JSON parse failure (article skipped, cycle continues).
        Raises httpx.ConnectError or httpx.TimeoutException → caller skips cycle.
        """
        user_content = _SYSTEM_PROMPT + f"\nUser: Title: {title or 'Unknown'}\nSource: {source_type or 'Unknown'}"
        # PLAN-0057 A-5: latency captured around the network call only; if
        # raise_for_status() throws, latency_ms still reflects the wall-clock
        # round-trip duration so the log row is accurate.
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                f"{self._api_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._api_model_id,
                    "messages": [{"role": "user", "content": user_content}],
                    # Force JSON output — avoids free-form prose wrapping the score object.
                    "response_format": {"type": "json_object"},
                    "temperature": 0.0,
                    # WHY 96 (up from 64): the extended response includes sentiment token
                    # (~10 extra characters in the JSON).  96 provides headroom without waste.
                    "max_tokens": 96,
                },
            )
            resp.raise_for_status()
            latency_ms = int((time.perf_counter() - t0) * 1000)
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            score = float(parsed["score"])
            # F-Q1-07: extract sentiment — default to None if missing or invalid enum.
            raw_sentiment = parsed.get("sentiment", "")
            sentiment: str | None = raw_sentiment if raw_sentiment in _VALID_SENTIMENTS else None
            await self._record_usage(
                provider="deepinfra",
                model_id=self._api_model_id,
                latency_ms=latency_ms,
                success=True,
                tokens_in=len(user_content.split()),
                tokens_out=len(content.split()),
                doc_id=doc_id,
            )
            return max(0.0, min(1.0, score)), sentiment
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            logger.warning(  # type: ignore[no-any-return]
                "relevance_scoring_json_parse_error",
                article_id=str(doc_id),
                error=str(exc),
            )
            await self._record_usage(
                provider="deepinfra",
                model_id=self._api_model_id,
                latency_ms=latency_ms,
                success=False,
                tokens_in=len(user_content.split()),
                tokens_out=0,
                doc_id=doc_id,
                error_code="model_error",
            )
            return None

    async def _record_usage(
        self,
        *,
        provider: str,
        model_id: str,
        latency_ms: int,
        success: bool,
        tokens_in: int,
        tokens_out: int,
        doc_id: UUID,
        error_code: str | None = None,
    ) -> None:
        """PLAN-0057 A-5: append one llm_usage_log row per LLM call.

        Best-effort wrapper around ``self._usage_logger.log()`` — if the logger
        is None (unit-test default) or its log() raises, the call returns
        silently so the scoring path is never disrupted.

        Token counts are word-split estimates (the protocol allows estimates;
        no provider returns exact counts on this code path).
        """
        if self._usage_logger is None:
            return
        try:
            await self._usage_logger.log(
                model_id=model_id,
                provider=provider,
                capability="classification",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                estimated_cost_usd=0.0,
                success=success,
                error_code=error_code,
                doc_id=doc_id,
            )
        except Exception as exc:  # belt-and-braces — protocol forbids raising
            logger.warning(  # type: ignore[no-any-return]
                "relevance_scoring_usage_log_failed",
                article_id=str(doc_id),
                error=str(exc),
                exc_info=True,
            )

    @staticmethod
    async def _write_scores(
        session: AsyncSession,
        scored: list[tuple[UUID, float, str | None, str]],
    ) -> None:
        """Phase 3a: legacy UPDATE on document_source_metadata (PLAN-0055 C-2 dual-write).

        Removed in Wave C-3 once ``document_source_llm_latest`` materialized view
        is the canonical read path. Until then, the news read path still SELECTs
        ``llm_relevance_score`` directly so we keep this UPDATE alive.
        """
        stmt = text(
            """
            UPDATE document_source_metadata
            SET llm_relevance_score = :score,
                sentiment           = :sentiment,
                llm_scored_at       = NOW()
            WHERE doc_id = :doc_id
            """,
        )
        for doc_id, score, sentiment, _input_hash in scored:
            await session.execute(stmt, {"doc_id": str(doc_id), "score": score, "sentiment": sentiment})

    @staticmethod
    async def _append_provenance(
        session: AsyncSession,
        scored: list[tuple[UUID, float, str | None, str]],
        model_id: str,
    ) -> None:
        """Phase 3b: append-only INSERT into document_source_llm_scores (PLAN-0055 C-2).

        Two rows per article: one for ``relevance`` (with score_value), one for
        ``sentiment`` (with score_label, score_value=NULL). ON CONFLICT DO NOTHING
        on ``uq_dsls_dedup`` makes re-runs safe.
        """
        from nlp_pipeline.infrastructure.nlp_db.repositories.llm_score import SqlaLLMScoreRepository

        repo = SqlaLLMScoreRepository(session)
        for doc_id, score, sentiment, input_hash in scored:
            await repo.append(
                doc_id=doc_id,
                score_type="relevance",
                score_value=score,
                score_label=None,
                model_id=model_id,
                prompt_version=_RELEVANCE_PROMPT_VERSION,
                input_hash=input_hash,
            )
            if sentiment is not None:
                # Skip writing a sentiment row when the LLM gave an unrecognized value.
                await repo.append(
                    doc_id=doc_id,
                    score_type="sentiment",
                    score_value=None,
                    score_label=sentiment,
                    model_id=model_id,
                    prompt_version=_RELEVANCE_PROMPT_VERSION,
                    input_hash=input_hash,
                )
