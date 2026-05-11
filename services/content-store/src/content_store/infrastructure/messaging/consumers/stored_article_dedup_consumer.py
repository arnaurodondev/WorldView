"""H-5 Stage C streaming near-duplicate cluster writer.

Consumes ``content.article.stored.v1`` events emitted by the S5 outbox
dispatcher AFTER each article has been cleaned and written to MinIO silver.
For each event this consumer:

  1. Fetches the new doc's MinHash signature from ``minhash_signatures``.
  2. Loads recent corpus signatures (last 14 days, up to 500 docs).
  3. Computes pairwise Jaccard similarity (estimated via equal-hash count).
  4. Writes any pair whose similarity >= JACCARD_THRESHOLD into
     ``duplicate_clusters`` using ``ON CONFLICT DO NOTHING`` for idempotency.

The consumer group ID is ``content-store-dedup-consumer`` — separate from
the raw-article consumer group so both consumers can process ``stored.v1``
events independently (the article consumer writes to ``raw.v1``, not
``stored.v1``).

Performance notes
-----------------
- 500 corpus signatures x 128 integers ~= 250 KB fetched per message.
  At a sustained 5 msg/s that is ~1.25 MB/s DB read — negligible.
- Each Jaccard computation is O(128) integer comparisons — microseconds.
- Only docs within the last 14 days are compared; older docs are irrelevant
  for near-duplicate news detection.

Idempotency
-----------
- ``processed_events`` table: prevents reprocessing the same event_id.
- ``uq_duplicate_clusters_pair`` unique constraint: prevents duplicate rows
  even if the consumer is restarted mid-batch.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import structlog

from content_store.infrastructure.db.repositories.dedup import (
    DuplicateClusterRepository,
    MinHashCorpusRepository,
)
from content_store.infrastructure.db.repositories.minhash import MinHashRepository
from content_store.infrastructure.db.repositories.processed_events import ProcessedEventsRepository
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_SCHEMA_DIR = find_schema_dir()

# Topic this consumer reads from — the S5 outbox dispatcher output.
_INPUT_TOPIC = "content.article.stored.v1"

# Minimum Jaccard similarity (estimated) to be recorded as a near-duplicate.
# 0.65 matches the threshold used in the backfill script (scripts/ops/).
JACCARD_THRESHOLD = 0.65

# How many recent corpus signatures to fetch per message.  Larger values give
# better recall but increase per-message DB read latency.
_CORPUS_LIMIT = 500

# How far back in time (days) to scan the corpus for candidates.
_CORPUS_WINDOW_DAYS = 14


# ── Unit of Work ──────────────────────────────────────────────────────────────


class _SessionUnitOfWork(UnitOfWorkProtocol):
    """SQLAlchemy AsyncSession UoW — identical to ArticleConsumer's pattern.

    SA-1 fix (BP-443): Explicit close() in __aexit__ prevents MissingGreenlet.

    Root cause: when the session was returned to the asyncpg pool via
    ``_session_cm.__aexit__`` only (no prior ``close()``), SQLAlchemy's pool
    would try to reset the raw connection (issue a ROLLBACK) on check-in.
    That reset fires an ``await_only()`` call from inside the pool's
    ``_reset_agent`` pathway, which is NOT running inside a greenlet spawned by
    ``greenlet_spawn`` — triggering:

        RuntimeError: greenlet_spawn has not been called; can't call
        await_only() here. Was IO attempted in an unexpected place?

    The fix: explicitly ``await session.close()`` while we are still inside a
    normal asyncio coroutine frame (which SQLAlchemy treats as a valid async
    context).  This causes SQLAlchemy to issue the final ROLLBACK/reset via its
    own ``greenlet_spawn`` machinery, cleanly returning the connection to the
    pool with no pending reset needed.  We also ensure ``self.session`` is
    cleared so it cannot be touched after ``__aexit__`` returns.

    Both ``close()`` and the ``_session_cm.__aexit__`` call are guarded with
    ``try/except`` so a pool error during teardown never propagates to the
    consumer loop.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.session: AsyncSession | None = None
        self._session_cm: Any = None

    async def __aenter__(self) -> _SessionUnitOfWork:
        self._session_cm = self._session_factory()
        self.session = await self._session_cm.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        # Explicitly close the session while we are inside a proper asyncio
        # coroutine.  This lets SQLAlchemy's greenlet_spawn machinery issue the
        # final ROLLBACK/reset synchronously, so the pool check-in has nothing
        # left to reset asynchronously — eliminating the MissingGreenlet error.
        session = self.session
        self.session = None  # prevent any further access through self.session
        if session is not None:
            # Pool teardown errors are non-fatal; log nothing here to avoid
            # recursive noise — the pool already emits its own warning.
            with contextlib.suppress(Exception):
                await session.close()
        # Delegate to the session context-manager to release resources.
        if self._session_cm is not None:
            with contextlib.suppress(Exception):
                await self._session_cm.__aexit__(*args)

    async def commit(self) -> None:
        if self.session is not None:
            await self.session.commit()

    async def rollback(self) -> None:
        if self.session is not None:
            await self.session.rollback()


# ── Consumer ──────────────────────────────────────────────────────────────────


def _estimate_jaccard(sig_a: list[int], sig_b: list[int]) -> float:
    """Estimate Jaccard similarity from two 128-perm MinHash signatures.

    The estimate is: (number of equal hash values) / len(sig_a).
    Both signatures must have the same number of permutations (128).

    Returns a float in [0.0, 1.0].  Returns 0.0 if either signature is empty.
    """
    if not sig_a or not sig_b or len(sig_a) != len(sig_b):
        return 0.0
    # Count equal positions — each equal position indicates a shared minhash.
    equal = sum(1 for a, b in zip(sig_a, sig_b, strict=False) if a == b)
    return equal / len(sig_a)


class StoredArticleDedupConsumer(BaseKafkaConsumer[dict]):  # type: ignore[type-arg]
    """Kafka consumer for content.article.stored.v1 -> duplicate_clusters writer.

    Reads the output topic of the S5 outbox dispatcher (not the raw input
    topic) so it only sees articles that have already been cleaned, deduped at
    Stage A/B, and written to MinIO silver.

    For each stored article this consumer computes pairwise MinHash Jaccard
    similarity against the recent corpus and writes near-duplicate pairs into
    the ``duplicate_clusters`` table.
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        group_id: str,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        consumer_config = ConsumerConfig(
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            topics=[_INPUT_TOPIC],
        )
        super().__init__(consumer_config)
        self._session_factory = session_factory
        self._current_uow: _SessionUnitOfWork | None = None

    # ── Abstract: duplicate guard ─────────────────────────────────────────────

    async def is_duplicate(self, event_id: str) -> bool:
        """Check processed_events for prior handling of this event."""
        if self._current_uow is not None and self._current_uow.session is not None:
            return await ProcessedEventsRepository(self._current_uow.session).is_duplicate(event_id)
        async with self._session_factory() as session:
            return await ProcessedEventsRepository(session).is_duplicate(event_id)

    async def mark_processed(self, event_id: str) -> None:
        """Mark event as processed in the current UoW session."""
        assert self._current_uow is not None and self._current_uow.session is not None
        await ProcessedEventsRepository(self._current_uow.session).mark_processed(event_id)

    # ── Abstract: failure handling ────────────────────────────────────────────

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:  # type: ignore[type-arg]
        record = {"event_id": failure.event_id, "topic": failure.topic, "error": str(failure.last_error)}
        logger.warning("stored_article_dedup_consumer_failure", **record)
        return record

    async def update_failure(self, failure: FailureInfo[dict]) -> None:  # type: ignore[type-arg]
        pass  # No retry table — failures are logged and skipped.

    async def get_pending_retries(self) -> list[FailureInfo[dict]]:  # type: ignore[type-arg]
        return []

    async def process_message_from_failure(self, failure: FailureInfo[dict]) -> None:  # type: ignore[type-arg]
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[dict]) -> None:  # type: ignore[type-arg]
        """Log dead-letter events — this consumer has no DLQ table of its own.

        Near-dup detection failures are non-critical: a missed pair means the
        ``duplicate_clusters`` table simply won't have that row.  The backfill
        script (scripts/ops/backfill_duplicate_clusters.py) can fill gaps.
        We log at ERROR so operators can see repeated failures in dashboards.
        """
        logger.error(
            "stored_article_dedup_dead_letter",
            event_id=failure.event_id,
            topic=failure.topic,
            error=str(failure.last_error),
        )

    # ── Abstract: UoW ─────────────────────────────────────────────────────────

    async def get_unit_of_work(self) -> _SessionUnitOfWork:
        uow = _SessionUnitOfWork(self._session_factory)
        self._current_uow = uow
        return uow

    # ── Abstract: deserialization ─────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Avro-encoded stored-article event; fall back to JSON."""
        if schema_path:
            try:
                return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
            except Exception:
                logger.debug("avro_deserialize_failed_falling_back_to_json", schema_path=schema_path)
        return cast("dict[str, Any]", json.loads(raw.decode()))

    def get_schema_path(self, topic: str) -> str | None:
        """Return the filesystem path to content.article.stored.v1.avsc."""
        path = _SCHEMA_DIR / f"{topic}.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value["event_id"])

    # ── Abstract: message processing ─────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Find and write near-duplicate pairs for the stored article.

        Steps:
          1. Parse doc_id from the event payload.
          2. Fetch this doc's MinHash signature from the DB.
          3. If no signature exists (e.g. doc was marked as duplicate at Stage A/B
             and never hashed) — skip silently.
          4. Fetch recent corpus signatures (last 14 days, <=500 docs).
          5. For each corpus entry estimate Jaccard similarity.
          6. Insert all pairs with similarity >= JACCARD_THRESHOLD.

        Args:
            key: Kafka message key (unused).
            value: Deserialized content.article.stored.v1 Avro dict.
            headers: Kafka message headers (unused).
        """
        uow = self._current_uow
        assert uow is not None and uow.session is not None
        session = uow.session

        # 1. Parse doc_id.
        doc_id = UUID(str(value["doc_id"]))

        # 2. Fetch this doc's MinHash signature.
        minhash_repo = MinHashRepository(session)
        sig_model = await minhash_repo.get_signature_by_doc_id(doc_id)
        if sig_model is None:
            # Doc was deduplicated at Stage A/B (exact duplicate) and never
            # assigned a MinHash signature — nothing to compare.
            logger.debug(
                "stored_article_dedup_no_signature",
                doc_id=str(doc_id),
                dedup_result=value.get("dedup_result"),
            )
            return

        new_sig: list[int] = sig_model.signature

        # 3. Fetch recent corpus signatures for pairwise comparison.
        corpus_repo = MinHashCorpusRepository(session)
        corpus = await corpus_repo.get_recent_signatures(
            exclude_doc_id=doc_id,
            within_days=_CORPUS_WINDOW_DAYS,
            limit=_CORPUS_LIMIT,
        )

        if not corpus:
            # First document in the corpus — no pairs to write.
            logger.debug("stored_article_dedup_empty_corpus", doc_id=str(doc_id))
            return

        # 4. Compute pairwise Jaccard and collect near-duplicate pairs.
        cluster_repo = DuplicateClusterRepository(session)
        pairs_written = 0

        for corpus_doc_id, corpus_sig in corpus:
            similarity = _estimate_jaccard(new_sig, corpus_sig)
            if similarity >= JACCARD_THRESHOLD:
                await cluster_repo.insert_pair(
                    primary_doc_id=doc_id,
                    duplicate_doc_id=corpus_doc_id,
                    similarity=similarity,
                )
                pairs_written += 1

        if pairs_written:
            logger.info(
                "stored_article_dedup_pairs_written",
                doc_id=str(doc_id),
                pairs=pairs_written,
                corpus_size=len(corpus),
            )
        else:
            logger.debug(
                "stored_article_dedup_no_pairs",
                doc_id=str(doc_id),
                corpus_size=len(corpus),
            )
