"""Resumable backfill: classify polarity for existing prediction exposures.

Context (PLAN-0056 Wave C3 completion):
  ``entity_event_exposures.polarity`` is filled by the
  ``PredictionEnrichedConsumer`` at write time — BUT that consumer is FORWARD-ONLY
  (``auto_offset_reset=latest``): it only classifies polarity for prediction
  markets it sees AFTER the Wave-C3 classifier was wired.  Every exposure written
  before that (or written while the DeepInfra key was absent/inert) keeps
  ``polarity = NULL`` forever, because a forward-only consumer never re-reads the
  historical enriched docs.  This is the ``exposure polarity 0/N`` prod WARN.

  This script re-classifies those NULL-polarity prediction exposures in place,
  using the SAME ``MarketPolarityClassifier`` the consumer uses, so the persisted
  verdict is identical to what a live re-processing would have produced.

Resumability:
  Keyset pagination on ``exposure_id`` (a UUIDv7 monotonic key) with the cursor
  persisted to Valkey (``kg:v1:prediction_polarity_backfill:cursor``).  A crash /
  pod-roll resumes from the last committed cursor rather than re-scanning.  The
  cursor advances past EVERY visited row (even ones we cannot classify — missing
  question or entity name), so an unclassifiable row can never wedge the loop.

Root-cause note (why NULL and not 'neutral'):
  The classifier returns ``('neutral', 0.0)`` on ANY failure (401/404/timeout),
  so a row that was actually processed by a live-but-failing classifier would read
  ``'neutral'``, not NULL.  A wall of NULLs therefore means the classifier NEVER
  RAN for those rows — i.e. they predate the wiring / were written key-less.  This
  script is the correct remedy; it is a no-op once the key is configured AND new
  docs flow, but existing rows still need this one pass.

How to run::

    docker exec worldview-knowledge-graph-prediction-enriched-consumer-1 \\
        python -m scripts.backfill_prediction_polarity

Options (env vars, all optional)::

    BACKFILL_BATCH_SIZE=200        # rows per SELECT batch
    BACKFILL_MAX_ROWS=0            # cap total rows visited (0 = all)
    BACKFILL_DRY_RUN=false         # when true, only print the candidate count
    BACKFILL_RESET_CURSOR=false    # when true, ignore any stored Valkey cursor

Exit codes::

    0   — successful backfill (or dry-run)
    1   — fatal wiring error (DB unreachable, or no DeepInfra key → classifier inert)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)  # type: ignore[no-any-return]

# UUID zero — the keyset cursor start (every real exposure_id sorts after it).
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
_CURSOR_KEY = "kg:v1:prediction_polarity_backfill:cursor"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw in {"true", "yes", "1", "on"} if raw else default


async def _read_cursor(valkey: Any) -> str:
    """Return the stored cursor (or the zero-UUID start). Best-effort."""
    if valkey is None:
        return _ZERO_UUID
    with contextlib.suppress(Exception):
        raw = await valkey.get(_CURSOR_KEY)
        if raw:
            return raw.decode() if isinstance(raw, bytes) else str(raw)
    return _ZERO_UUID


async def _write_cursor(valkey: Any, cursor: str) -> None:
    """Persist the cursor (best-effort — a lost write only re-does one batch)."""
    if valkey is None:
        return
    with contextlib.suppress(Exception):
        await valkey.set(_CURSOR_KEY, cursor)


async def main() -> int:
    """Classify polarity for NULL-polarity prediction exposures (resumable)."""
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-backfill-prediction-polarity",
        level=settings.log_level,
        json=settings.log_json,
    )

    batch_size = _env_int("BACKFILL_BATCH_SIZE", 200)
    max_rows = _env_int("BACKFILL_MAX_ROWS", 0)
    dry_run = _env_bool("BACKFILL_DRY_RUN", False)
    reset_cursor = _env_bool("BACKFILL_RESET_CURSOR", False)

    # The classifier is MANDATORY for a backfill — without a key it is inert and
    # would stamp everything 'neutral', defeating the purpose. Fail loudly instead.
    deepinfra_key = settings.deepinfra_api_key.get_secret_value()
    if not deepinfra_key:
        logger.error(
            "backfill_prediction_polarity_no_key",
            reason="DEEPINFRA_API_KEY empty — the polarity classifier is inert. "
            "Configure the key on this deployment before backfilling.",
        )
        return 1

    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    from knowledge_graph.infrastructure.intelligence_db.usage_log_factory import (
        SessionScopedKgUsageLogger,
    )
    from knowledge_graph.infrastructure.llm.market_polarity_classifier import (
        MarketPolarityClassifier,
    )

    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    classifier = MarketPolarityClassifier(
        api_key=deepinfra_key,
        api_base_url=settings.polarity_classifier_base_url,
        model_id=settings.polarity_classifier_model_id,
        timeout_seconds=settings.polarity_classifier_timeout_seconds,
        usage_logger=SessionScopedKgUsageLogger(write_factory),
    )
    valkey = None
    with contextlib.suppress(Exception):
        valkey = create_valkey_client_from_url(settings.valkey_url)

    try:
        async with write_factory() as session:
            count = await session.execute(
                text(
                    "SELECT count(*) FROM entity_event_exposures eee "
                    "JOIN temporal_events te ON te.event_id = eee.event_id "
                    "WHERE te.event_type = 'prediction' AND eee.polarity IS NULL"
                )
            )
            candidates = int(count.scalar_one())
        logger.info("backfill_prediction_polarity_candidates", rows=candidates, dry_run=dry_run)
        if dry_run or candidates == 0:
            return 0

        cursor = _ZERO_UUID if reset_cursor else await _read_cursor(valkey)
        processed = 0
        classified = 0
        while True:
            if max_rows and processed >= max_rows:
                break
            limit = batch_size if not max_rows else min(batch_size, max_rows - processed)
            cursor, visited, updated = await _process_batch(write_factory, classifier, cursor, limit)
            if visited == 0:
                break
            processed += visited
            classified += updated
            await _write_cursor(valkey, cursor)
            logger.info(
                "backfill_prediction_polarity_progress",
                processed=processed,
                classified=classified,
                cursor=cursor,
            )

        logger.info(
            "backfill_prediction_polarity_complete",
            processed=processed,
            classified=classified,
        )
        return 0
    finally:
        with contextlib.suppress(Exception):
            if valkey is not None:
                await valkey.aclose()
        await _engine.dispose()
        with contextlib.suppress(Exception):
            await _read_engine.dispose()


async def _process_batch(
    write_factory: Callable[[], Any],
    classifier: Any,
    cursor: str,
    limit: int,
) -> tuple[str, int, int]:
    """Classify + UPDATE one keyset page. Returns (new_cursor, visited, updated).

    Two phases so NO DB session is held across the LLM HTTP calls (R24):
      1. Read a page of NULL-polarity prediction exposures (+ question + entity
         name) in a short session, then release it.
      2. Classify each row over HTTP (no session held).
      3. Re-open a session and UPDATE the classified rows.
    The cursor advances to the LAST visited exposure_id regardless of whether it
    was classifiable, so an unclassifiable row cannot wedge the loop.
    """
    # Phase 1 — read (session released before any HTTP call).
    async with write_factory() as session:
        rows = (
            await session.execute(
                text("""
SELECT eee.exposure_id, eee.entity_id, te.title AS question, te.region AS condition_id,
       ce.canonical_name
FROM entity_event_exposures eee
JOIN temporal_events te ON te.event_id = eee.event_id AND te.event_type = 'prediction'
LEFT JOIN canonical_entities ce ON ce.entity_id = eee.entity_id
WHERE eee.polarity IS NULL AND eee.exposure_id > CAST(:cursor AS uuid)
ORDER BY eee.exposure_id
LIMIT :lim
"""),
                {"cursor": cursor, "lim": limit},
            )
        ).fetchall()
    if not rows:
        return cursor, 0, 0

    # Phase 2 — classify (HTTP, no session held).
    verdicts: list[tuple[str, str, float]] = []  # (exposure_id, polarity, confidence)
    for row in rows:
        exposure_id = str(row[0])
        entity_id = row[1]
        question = row[2]
        condition_id = row[3]
        entity_name = row[4]
        if not question or not entity_name:
            continue  # unclassifiable — leave NULL, but the cursor still advances past it
        polarity, confidence = await classifier.classify(
            question=str(question),
            entity_name=str(entity_name),
            outcomes=None,
            condition_id=str(condition_id) if condition_id else None,
            entity_id=UUID(str(entity_id)),
        )
        verdicts.append((exposure_id, polarity, confidence))

    # Phase 3 — UPDATE (guarded by ``polarity IS NULL`` so a concurrent live write wins).
    updated = 0
    if verdicts:
        async with write_factory() as session:
            for exposure_id, polarity, confidence in verdicts:
                res = await session.execute(
                    text(
                        "UPDATE entity_event_exposures "
                        "SET polarity = :p, polarity_confidence = :pc "
                        "WHERE exposure_id = CAST(:eid AS uuid) AND polarity IS NULL"
                    ),
                    {"p": polarity, "pc": confidence, "eid": exposure_id},
                )
                updated += max(res.rowcount, 0)
            await session.commit()

    new_cursor = str(rows[-1][0])
    return new_cursor, len(rows), updated


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
