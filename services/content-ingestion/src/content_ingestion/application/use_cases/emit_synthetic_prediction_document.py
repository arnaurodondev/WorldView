"""Synthetic-document emitter for prediction markets (PLAN-0056 Wave B2).

A Polymarket market *question* is a natural-language artifact.  Rather than teach
S6 (nlp-pipeline) about prediction markets, we route the question through the
existing ``content.article.raw.v1`` rails as a **synthetic document** so S6's NER
links the question to the entities it mentions — for free, with zero S6 change
(PRD-0033 §7).

Two documents are emitted over a market's lifetime:

1. **First-sight** — one doc when the market is first seen, deduped on
   ``url_hash = sha256("polymarket:<condition_id>")``.
2. **Resolution** — one more doc when the market resolves, deduped on
   ``url_hash = sha256("polymarket:<condition_id>:resolved")`` and carrying the
   resolved outcome in the body.

Only these two events generate documents — price snapshots do NOT — so the
lifetime document volume is bounded (≈ one/two per market, not per snapshot).

Each document is written as an atomic ``article_fetch_log`` + ``outbox_events``
transaction (R8 — never DB write + Kafka publish separately).  The emit result is
always committed, never merely returned/logged (audit-return-persistence
guardrail).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import common.ids
import common.time as ct
from content_ingestion.application.use_cases.fetch_and_write import build_raw_article_payload
from contracts.enums import ContentSourceType  # type: ignore[import-untyped]
from messaging.topics import CONTENT_ARTICLE_RAW  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

    from content_ingestion.application.ports.repositories import FetchLogPort, OutboxPort
    from content_ingestion.domain.entities import PredictionMarketFetchResult

logger = get_logger(__name__)  # type: ignore[no-any-return]

# HTTP status recorded on the synthetic fetch_log row.  There is no real HTTP
# fetch behind a synthetic document, but the column is NOT NULL — 200 is the
# honest "synthesised OK" sentinel (mirrors how other in-process producers log).
_SYNTHETIC_HTTP_STATUS = 200


def synthetic_first_sight_url_hash(condition_id: str) -> str:
    """Return the dedup ``url_hash`` for a market's first-sight synthetic document."""
    return hashlib.sha256(f"polymarket:{condition_id}".encode()).hexdigest()


def synthetic_resolution_url_hash(condition_id: str) -> str:
    """Return the dedup ``url_hash`` for a market's resolution synthetic document."""
    return hashlib.sha256(f"polymarket:{condition_id}:resolved".encode()).hexdigest()


def _synthetic_source_url(result: PredictionMarketFetchResult) -> str:
    """Build a stable, human-meaningful source URL for the synthetic document.

    Prefers the Polymarket event URL when a slug is available; otherwise falls
    back to the ``polymarket:<condition_id>`` external-id form.  This value is
    stored on ``article_fetch_log.url`` and echoed as the event ``source_url``.
    """
    if result.market_slug:
        return f"https://polymarket.com/event/{result.market_slug}"
    return f"polymarket:{result.market_id}"


def build_synthetic_document_body(
    result: PredictionMarketFetchResult,
    *,
    resolved: bool = False,
    event_name: str | None = None,
) -> str:
    """Render the natural-language body S6 will run NER over (PRD-0033 §7).

    Layout::

        <question>

        - <outcome name>: <implied %>
        - <outcome name>: <implied %>
        Market closes <close_time>
        Category: <category>
        Belongs to event: <event_name>          # only when event_name is given
        This market has resolved. ...            # only when resolved=True

    Args:
        result: The parsed market snapshot.
        resolved: When True, append the resolved-outcome sentence (resolution doc).
        event_name: Parent Polymarket event/group name, when known.  Omitted from
            the body when None/empty (the market-stream result does not carry it;
            reserved for a later wiring that has the event context).
    """
    # The question is the title AND the first body line so NER sees it verbatim.
    lines: list[str] = [result.question, ""]

    # Each outcome as an implied probability, e.g. "- Yes: 60.0%".
    for outcome in result.outcomes:
        lines.append(f"- {outcome.name}: {outcome.price * 100:.1f}%")

    if result.close_time is not None:
        lines.append(f"Market closes {ct.to_iso8601(result.close_time)}")
    if result.category:
        lines.append(f"Category: {result.category}")
    if event_name:
        lines.append(f"Belongs to event: {event_name}")

    if resolved:
        # resolved_answer may be absent even for a resolved market; state it plainly.
        answer = result.resolved_answer or "unknown"
        lines.append(f"This market has resolved. Resolved outcome: {answer}")

    return "\n".join(lines)


@dataclass(frozen=True)
class SyntheticDocumentEmitSummary:
    """Outcome of emitting synthetic documents for a single market."""

    emitted: int = 0
    skipped: int = 0
    failed: int = 0


class SyntheticDocumentEmitter:
    """Emit synthetic ``content.article.raw.v1`` documents for prediction markets.

    Args:
        fetch_log_repo: Article fetch-log repository (url_hash dedup + row write).
        outbox_repo: Transactional outbox repository.
        commit_fn: Async callable committing the shared DB session.
        rollback_fn: Async callable rolling the session back so a single failed
            document does not poison the session for subsequent markets.
    """

    def __init__(
        self,
        fetch_log_repo: FetchLogPort,
        outbox_repo: OutboxPort,
        commit_fn: Callable[[], Coroutine[Any, Any, None]],
        rollback_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        self._fetch_log = fetch_log_repo
        self._outbox = outbox_repo
        self._commit_fn = commit_fn
        self._rollback_fn = rollback_fn

    async def emit(
        self,
        result: PredictionMarketFetchResult,
        *,
        event_name: str | None = None,
    ) -> SyntheticDocumentEmitSummary:
        """Emit the first-sight (and, if resolved, resolution) documents for *result*.

        Idempotent: a re-polled market whose documents already exist emits 0.

        Args:
            result: The parsed market snapshot.
            event_name: Optional parent-event name to include in the body.
        """
        condition_id = result.market_id
        if not condition_id:
            # Without a stable condition id the dedup key would collide across
            # markets — refuse to emit rather than risk cross-market dedup.
            logger.warning("synthetic_document_skipped_no_condition_id")
            return SyntheticDocumentEmitSummary()

        emitted = 0
        skipped = 0
        failed = 0

        # 1. First-sight document (always attempted; dedup-guarded).
        fs_hash = synthetic_first_sight_url_hash(condition_id)
        outcome = await self._emit_one(result, url_hash=fs_hash, resolved=False, event_name=event_name)
        emitted += outcome[0]
        skipped += outcome[1]
        failed += outcome[2]

        # 2. Resolution document (only once the market has resolved).
        if result.resolution_status == "resolved":
            res_hash = synthetic_resolution_url_hash(condition_id)
            outcome = await self._emit_one(result, url_hash=res_hash, resolved=True, event_name=event_name)
            emitted += outcome[0]
            skipped += outcome[1]
            failed += outcome[2]

        return SyntheticDocumentEmitSummary(emitted=emitted, skipped=skipped, failed=failed)

    async def _emit_one(
        self,
        result: PredictionMarketFetchResult,
        *,
        url_hash: str,
        resolved: bool,
        event_name: str | None,
    ) -> tuple[int, int, int]:
        """Emit one synthetic document; return ``(emitted, skipped, failed)`` counts.

        Writes ``article_fetch_log`` + ``outbox_events`` in a single transaction
        and commits.  On any error the session is rolled back so the caller can
        continue with the next market (the shared session is left clean).
        """
        # Cheap first-pass dedup; the url_hash UNIQUE constraint is the real guard
        # against a concurrent worker racing the same market.
        if await self._fetch_log.exists_by_url_hash(url_hash):
            return (0, 1, 0)

        try:
            body = build_synthetic_document_body(result, resolved=resolved, event_name=event_name)
            raw_bytes = body.encode()
            source_url = _synthetic_source_url(result)
            published_at = ct.to_iso8601(result.close_time) if result.close_time else None

            # Atomic transaction: fetch_log + outbox (R8 — outbox pattern).
            fetch_log_id = common.ids.new_uuid7()
            await self._fetch_log.create(
                url=source_url,
                url_hash=url_hash,
                source_id=None,
                http_status=_SYNTHETIC_HTTP_STATUS,
                byte_size=len(raw_bytes),
                fetched_at=result.fetched_at,
                published_at=result.close_time,
                is_backfill=False,
                row_id=fetch_log_id,
            )

            payload = build_raw_article_payload(
                doc_id=common.ids.new_uuid7(),
                # source_type='polymarket' so S6 treats it like any other article.
                source_type=ContentSourceType.POLYMARKET.value,
                source_url=source_url,
                # Reuse the snapshot's bronze key — the raw market JSON already lives
                # there; the synthetic body is derived from the same object.
                minio_bronze_key=result.minio_bronze_key or "",
                raw_bytes=raw_bytes,
                fetch_id=fetch_log_id,
                # published_at = close date so temporal decay anchors on the market horizon.
                published_at=published_at,
                is_backfill=False,
                title=result.question,
            )
            await self._outbox.append(
                aggregate_type="article",
                aggregate_id=result.id,
                event_type="content.article.raw.v1",
                topic=CONTENT_ARTICLE_RAW,
                payload=payload,
            )
            await self._commit_fn()
            logger.info(
                "synthetic_document_emitted",
                market_id=result.market_id,
                resolved=resolved,
                url_hash=url_hash,
            )
            return (1, 0, 0)
        except Exception as exc:
            # Roll back so the shared session is usable for the next market (M-02).
            await self._rollback_fn()
            logger.error(
                "synthetic_document_emit_failed",
                market_id=result.market_id,
                resolved=resolved,
                error=type(exc).__name__,
            )
            return (0, 0, 1)
