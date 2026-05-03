"""Query use cases for the NLP Pipeline REST API (S6).

Uses port interfaces (ABCs) from application.ports — never imports from
infrastructure directly (R25 / IG-LAYER-002 compliance).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from nlp_pipeline.application.ports.repositories import (
        NewsQueryPort,
        RankedArticleData,
        SignalsQueryPort,
    )

_log = get_logger(__name__)  # type: ignore[no-any-return]


# ── Application-layer result dataclasses ──────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class SignalData:
    signal_id: UUID
    doc_id: UUID
    entity_id: UUID
    signal_type: str
    confidence: float
    evidence_text: str
    detected_at: datetime
    market_impact_score: float = 0.0


@dataclasses.dataclass(frozen=True)
class EntitySearchData:
    entity_id: UUID
    canonical_name: str
    entity_type: str
    mention_count: int


@dataclasses.dataclass(frozen=True)
class EntityDetailData:
    entity_id: UUID
    canonical_name: str
    entity_type: str
    mention_count: int
    resolved_count: int
    provisional_count: int


@dataclasses.dataclass(frozen=True)
class VectorSearchHitData:
    doc_id: UUID
    section_id: UUID
    score: float
    snippet: str


# ── Use case classes ───────────────────────────────────────────────────────────


class ListSignalsUseCase:
    """List outbox events for the nlp.signal.detected.v1 topic."""

    async def execute(
        self,
        repo: SignalsQueryPort,
        limit: int,
        offset: int,
        doc_id: UUID | None,
        min_impact_score: float = 0.0,
        order_by: str = "created_at",
    ) -> tuple[list[SignalData], int]:
        rows, total = await repo.list_signal_events(
            limit=limit,
            offset=offset,
            doc_id=doc_id,
            min_impact_score=min_impact_score,
            order_by=order_by,
        )

        items: list[SignalData] = []
        for row in rows:
            try:
                # PLAN-0062 F-006 read-side compatibility: outbox rows written
                # *after* the producer migration carry Confluent-Avro framed
                # bytes (5-byte ``\x00<schema-id>`` header + Avro body).
                # Pre-migration rows are still raw JSON bytes — sniff the magic
                # byte and dispatch.  The Avro branch is preferred; the JSON
                # fallback exists only until legacy rows drain.
                # TODO PLAN-0062-followup: drop JSON branch once legacy outbox rows drain.
                raw = row["payload_avro"]
                if isinstance(raw, bytes | bytearray) and raw[:1] == b"\x00":
                    from messaging.kafka.schema_paths import (  # type: ignore[import-untyped]
                        get_schema_path,
                    )
                    from messaging.kafka.serialization_utils import (  # type: ignore[import-untyped]
                        deserialize_confluent_avro,
                    )

                    payload = deserialize_confluent_avro(
                        get_schema_path("nlp.signal.detected.v1.avsc"),
                        bytes(raw),
                    )
                else:
                    payload = json.loads(raw)
                items.append(
                    SignalData(
                        signal_id=UUID(payload.get("event_id", str(row["event_id"]))),
                        doc_id=UUID(payload.get("doc_id", row["partition_key"])),
                        entity_id=UUID(
                            str(
                                payload.get("claimer_entity_id")
                                or payload.get(
                                    "subject_entity_id",
                                    "00000000-0000-0000-0000-000000000000",
                                ),
                            ),
                        ),
                        signal_type=str(payload.get("claim_type", "unknown")),
                        confidence=float(payload.get("extraction_confidence", 0.0)),
                        evidence_text=str(payload.get("claim_id", "")),
                        detected_at=datetime.fromisoformat(payload["occurred_at"])
                        if "occurred_at" in payload
                        else row["created_at"],
                        market_impact_score=float(row.get("impact_score") or 0.0),
                    ),
                )
            except Exception:
                # PLAN-0062 F-006: silent drops are unacceptable for produced
                # signals — promote to ``warning`` with a stable event name so
                # the metric is observable in production logs.
                _log.warning(
                    "signals_list_skip_malformed_payload",
                    exc_info=True,
                )
                continue

        return items, int(total)


class SearchEntitiesUseCase:
    """Search entities by mention text substring."""

    async def execute(
        self,
        repo: SignalsQueryPort,
        q: str,
        limit: int,
        offset: int,
    ) -> tuple[list[EntitySearchData], int]:
        rows, total = await repo.search_entity_mentions(q=q, limit=limit, offset=offset)
        return [
            EntitySearchData(
                entity_id=UUID(str(row["resolved_entity_id"])),
                canonical_name=str(row["mention_text"]),
                entity_type=str(row["mention_class"]),
                mention_count=int(row["mention_count"]),
            )
            for row in rows
        ], int(total)


class GetEntityDetailUseCase:
    """Retrieve entity detail with mention resolution counts."""

    async def execute(
        self,
        repo: SignalsQueryPort,
        entity_id: UUID,
    ) -> EntityDetailData | None:
        row = await repo.get_entity_detail(entity_id)
        if row is None:
            return None

        total = int(row["total"])
        resolved = int(row.get("resolved") or 0)
        return EntityDetailData(
            entity_id=entity_id,
            canonical_name=str(row["mention_text"]),
            entity_type=str(row["mention_class"]),
            mention_count=total,
            resolved_count=resolved,
            provisional_count=total - resolved,
        )


class GetEntityArticlesUseCase:
    """List articles mentioning a given entity, with full scoring fields (PRD-0026 §6.7 Flow D)."""

    async def execute(
        self,
        repo: NewsQueryPort,
        entity_id: UUID,
        start_date: datetime,
        end_date: datetime,
        order_by: str,
        limit: int,
        offset: int,
        tenant_id: str | None = None,
    ) -> tuple[list[RankedArticleData], int]:
        """Return ranked articles for an entity within the given date range.

        Delegates entirely to the port — the SQL CTE computes display_relevance_score
        and all window scores at query time.  Returns an empty list (not 404) when the
        entity has no articles in the date range.

        F-009 Option B: tenant_id is passed through to the port for tenant-scoped
        entity_mentions filtering.
        """
        return await repo.get_entity_articles(
            entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            order_by=order_by,
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
        )


class GetTopNewsUseCase:
    """Return globally top-ranked articles within a rolling time window (PRD-0026 §6.7 Flow C)."""

    async def execute(
        self,
        repo: NewsQueryPort,
        hours: int,
        limit: int,
        offset: int,
        min_display_score: float | None,
        routing_tier: str | None,
    ) -> tuple[list[RankedArticleData], int]:
        """Return articles ranked by display_relevance_score.

        Delegates entirely to the port — the 3-CTE SQL computes all scores at query time.
        """
        return await repo.get_top_news(
            hours=hours,
            limit=limit,
            offset=offset,
            min_display_score=min_display_score,
            routing_tier=routing_tier,
        )


class VectorSearchUseCase:
    """Semantic section search (keyword ILIKE fallback until ML client injected)."""

    async def execute(
        self,
        repo: SignalsQueryPort,
        query: str,
        limit: int,
    ) -> list[VectorSearchHitData]:
        rows = await repo.vector_search_sections(query=query, limit=limit)
        return [
            VectorSearchHitData(
                doc_id=row["doc_id"],
                section_id=row["section_id"],
                score=float(row["score"]),
                snippet=str(row["snippet"]),
            )
            for row in rows
        ]


class ReprocessArticleUseCase:
    """Enqueue a reprocess event for an article.

    Returns True when the article was found and the event was queued,
    False when no routing decision exists for the article.
    """

    async def execute(
        self,
        repo: SignalsQueryPort,
        article_id: UUID,
    ) -> bool:
        exists = await repo.find_routing_decision(article_id)
        if not exists:
            return False

        payload = json.dumps(
            {
                "event_id": str(new_uuid7()),
                "event_type": "nlp.reprocess.requested",
                "occurred_at": utc_now().isoformat(),
                "doc_id": str(article_id),
            },
        ).encode()
        await repo.insert_outbox_event(
            event_id=new_uuid7(),
            topic="nlp.reprocess.v1",
            partition_key=str(article_id),
            payload_avro=payload,
        )
        return True
