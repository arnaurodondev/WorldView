"""Block 12a — Graph materialization (PRD §6.7 Block 12 hot path).

Per enriched message:
  1. Advisory lock + upsert ``relations`` table (subject, type, object natural key).
  2. INSERT ``relation_evidence_raw`` (append-only; partition_key STORED — never in INSERT).
  3. INSERT ``events`` + ``event_entities`` (ON CONFLICT DO NOTHING).
  4. INSERT ``claims`` (ON CONFLICT DO NOTHING).
  5. Return ``entity_ids_to_dirty`` for caller to produce ``entity.dirtied.v1``
     AFTER session.commit() (PLAN-0031 C-1 post-commit ordering fix).
  6. Emit ``graph.state.changed.v1`` via outbox.

Aggregation worker (Wave D-3) skips rows where ``entity_provisional = true``.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.ids import new_uuid7, uuid5_from_parts  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.ports.repositories import (
    TOPIC_GRAPH_STATE_CHANGED,
)
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

# PLAN-0062 audit follow-up F-006: serialize the graph.state.changed.v1 outbox
# payload to Confluent-Avro wire format instead of JSON.
_GRAPH_STATE_CHANGED_SCHEMA_PATH = get_schema_path("graph.state.changed.v1.avsc")
_ENTITY_DIRTIED_SCHEMA_PATH = get_schema_path("entity.dirtied.v1.avsc")
_log = get_logger(__name__)  # type: ignore[no-any-return]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import (
        OutboxRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
        RelationRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
        RelationEvidenceRepository,
    )

# ---------------------------------------------------------------------------
# Protocol for direct Kafka produce (entity.dirtied.v1 bypasses outbox)
# ---------------------------------------------------------------------------


class DirectKafkaProducerProtocol:  # (mypy structural subtyping)
    """Protocol: ``produce_bytes(topic, key, value)``."""

    def produce_bytes(
        self,
        *,
        topic: str,
        key: bytes,
        value: bytes,
    ) -> None:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RawRelation:
    """A single extracted relation from the enriched article message."""

    subject_entity_id: UUID
    object_entity_id: UUID
    raw_type: str
    polarity: str = "positive"
    extraction_confidence: float = 0.5
    source_trust_weight: float = 1.0
    evidence_date: datetime = dataclasses.field(
        default_factory=lambda: __import__("common.time", fromlist=["utc_now"]).utc_now(),
    )
    is_backfill: bool = False
    entity_provisional: bool = False
    provisional_queue_id: UUID | None = None
    claim_id: UUID | None = None
    chunk_id: UUID | None = None
    evidence_text: str | None = None


@dataclasses.dataclass(frozen=True)
class RawEvent:
    """A single extracted event from the enriched article message."""

    subject_entity_id: UUID
    event_type: str
    event_text: str
    extraction_confidence: float = 0.5
    event_date: datetime | None = None
    participant_entity_ids: tuple[UUID, ...] = ()


@dataclasses.dataclass(frozen=True)
class RawClaim:
    """A single extracted claim from the enriched article message."""

    subject_entity_id: UUID
    claim_type: str
    polarity: str
    claim_text: str
    extraction_confidence: float = 0.5
    claimer_entity_id: UUID | None = None
    chunk_id: UUID | None = None
    is_backfill: bool = False


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class MaterializationSummary:
    """Counts of materialized artifacts for logging."""

    relations_upserted: int
    evidence_rows_inserted: int
    events_inserted: int
    claims_inserted: int
    entities_dirtied: int
    # PLAN-0031 C-1: entity IDs that need a ``entity.dirtied.v1`` Kafka produce.
    # The CALLER is responsible for producing AFTER session.commit() so that
    # Kafka messages are never emitted for rolled-back writes.
    entity_ids_to_dirty: frozenset[UUID] = dataclasses.field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Helpers — events + claims (raw SQL, S7 does not own intelligence_db DDL)
# ---------------------------------------------------------------------------


_DETERMINISTIC_CREATED_AT_FALLBACK = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
"""Stable ``created_at`` baseline for events whose ``event_date`` is None.

The events table is partitioned monthly starting at 2024-01 (see migration
0001), so a literal 2024-01-01 timestamp ALWAYS lands inside a pre-seeded
partition — no risk of ``no partition of relation \"events\" found for row``.

Using a constant here (rather than e.g. epoch=0 which would be 1970-01-01 and
fall outside the partition window) makes replays both idempotent AND insertable
when the upstream extraction omits an explicit event_date.
"""


async def _insert_event_and_entities(
    session: AsyncSession,
    doc_id: UUID,
    event: RawEvent,
) -> UUID:
    """INSERT into ``events`` (ON CONFLICT DO NOTHING) and ``event_entities``.

    DEF-025 (PLAN-0076 Wave A-3 + QA fix): the event_id is now derived
    deterministically from ``(doc_id, subject_entity_id, event_type)`` AND we
    bind a deterministic ``created_at`` so the ``ON CONFLICT (event_id,
    created_at)`` clause actually matches on replay.

    Why we MUST bind ``created_at`` explicitly:
      * ``events`` is RANGE-partitioned by ``created_at`` and the unique
        constraint is (event_id, created_at) — a partitioned-table unique
        constraint MUST include all partition-key columns.
      * If we let ``created_at`` default to ``now()`` server-side, every Kafka
        replay produces a different ``created_at``, so ON CONFLICT NEVER
        matches and we INSERT a duplicate row with the same event_id but a
        fresh ``created_at``.  The deterministic event_id buys us nothing in
        that case (BP-397).
      * Binding ``created_at`` to a stable function of the input message
        (event.event_date, falling back to the migration-aligned 2024-01-01
        baseline when the event has no date) closes the loop: the same Kafka
        message produces the same (event_id, created_at) tuple on every
        attempt and the ON CONFLICT clause matches as intended.

    The ``event_entities`` INSERT does NOT need a deterministic created_at —
    its unique key is (event_id, entity_id) which is already stable.
    """
    from sqlalchemy import text

    # Deterministic UUID5 — same (doc_id, subject_entity_id, event_type)
    # always yields the same event_id (BP-316 fix).  The fields are passed
    # as strings (uuid5_from_parts accepts *str), so we stringify the UUID
    # inputs explicitly.
    event_id_str = uuid5_from_parts(
        str(doc_id),
        str(event.subject_entity_id),
        event.event_type,
    )
    # Deterministic created_at — see docstring above (BP-397).  Prefer the
    # extracted event_date when present (it is the most semantically meaningful
    # timestamp for this event); fall back to a stable migration-aligned
    # baseline so a missing date does not break partition routing.
    created_at_value: datetime = (
        event.event_date if event.event_date is not None else _DETERMINISTIC_CREATED_AT_FALLBACK
    )
    await session.execute(
        text("""
INSERT INTO events
    (event_id, created_at, doc_id, subject_entity_id, event_type,
     event_date, event_text, extraction_confidence)
VALUES
    (:event_id, :created_at, :doc_id, :subject_entity_id, :event_type,
     :event_date, :event_text, :extraction_confidence)
ON CONFLICT (event_id, created_at) DO NOTHING
"""),
        {
            "event_id": event_id_str,
            # Bind ``created_at`` from a deterministic source so replays of
            # the same enriched-article message produce the same partition-key
            # value AND the same conflict-target tuple.  Without this bind the
            # column defaults to server-side ``now()`` and every replay creates
            # a fresh duplicate row.
            "created_at": created_at_value,
            "doc_id": str(doc_id),
            "subject_entity_id": str(event.subject_entity_id),
            "event_type": event.event_type,
            "event_date": event.event_date,
            "event_text": event.event_text,
            "extraction_confidence": event.extraction_confidence,
        },
    )
    # Observability: log every event insert so replays are traceable in logs.
    # ``event_id_deterministic=True`` flags this row as derived via
    # uuid5_from_parts — useful when grepping logs to confirm the DEF-025
    # rollout reached production code paths.
    _log.debug(
        "event_inserted",
        event_id=event_id_str,
        doc_id=str(doc_id),
        subject_entity_id=str(event.subject_entity_id),
        event_type=event.event_type,
        event_id_deterministic=True,
        created_at=created_at_value.isoformat(),
    )
    # event_entities — subject with role "subject", participants with role "participant"
    all_pairs = [(event.subject_entity_id, "subject")] + [
        (eid, "participant") for eid in event.participant_entity_ids if eid != event.subject_entity_id
    ]
    for entity_id, role in all_pairs:
        await session.execute(
            text("""
INSERT INTO event_entities (event_id, entity_id, role)
VALUES (:event_id, :entity_id, :role)
ON CONFLICT (event_id, entity_id) DO NOTHING
"""),
            # Reuse the deterministic event_id_str from the events INSERT above —
            # this keeps the FK target identical and lets event_entities also
            # benefit from idempotent replay (the ON CONFLICT (event_id, entity_id)
            # path matches because event_id is now stable across replays).
            {"event_id": event_id_str, "entity_id": str(entity_id), "role": role},
        )
    # Caller treats the return as a UUID (signature: ``-> UUID``).  Parse the
    # deterministic string back to UUID exactly once here so the rest of the
    # codebase keeps the existing typed-UUID contract.
    return UUID(event_id_str)


async def _insert_claim(
    session: AsyncSession,
    doc_id: UUID,
    raw_claim: RawClaim,
    extraction_model_id: str | None = None,
) -> UUID:
    """INSERT a claim record.  Returns the new claim_id.

    ``extraction_model_id`` is the LLM model that produced this claim
    (PLAN-0031 B-2).  When None the DB server_default='unknown' applies.
    """
    from sqlalchemy import text

    claim_id = new_uuid7()
    await session.execute(
        text("""
INSERT INTO claims
    (claim_id, doc_id, chunk_id, claimer_entity_id, subject_entity_id,
     claim_type, polarity, claim_text, extraction_confidence, is_backfill,
     extraction_model_id)
VALUES
    (:claim_id, :doc_id, :chunk_id, :claimer_entity_id, :subject_entity_id,
     :claim_type, :polarity, :claim_text, :extraction_confidence, :is_backfill,
     :extraction_model_id)
ON CONFLICT (claim_id, created_at) DO NOTHING
"""),
        {
            "claim_id": str(claim_id),
            "doc_id": str(doc_id),
            "chunk_id": str(raw_claim.chunk_id) if raw_claim.chunk_id else None,
            "claimer_entity_id": (str(raw_claim.claimer_entity_id) if raw_claim.claimer_entity_id else None),
            "subject_entity_id": str(raw_claim.subject_entity_id),
            "claim_type": raw_claim.claim_type,
            "polarity": raw_claim.polarity,
            "claim_text": raw_claim.claim_text,
            "extraction_confidence": raw_claim.extraction_confidence,
            "is_backfill": raw_claim.is_backfill,
            "extraction_model_id": extraction_model_id,
        },
    )
    return claim_id  # type: ignore[return-value]


def _build_entity_dirtied_payload(
    entity_id: UUID,
    source_doc_id: UUID,
    correlation_id: str | None,
) -> bytes:
    """Serialize ``entity.dirtied.v1`` as a Confluent-Avro wire-format payload.

    PLAN-0062 R28 fix: migrated from json.dumps to serialize_confluent_avro so
    that entity.dirtied.v1 uses the Confluent 5-byte wire-format header,
    consistent with all other producer paths.
    """
    from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

    return serialize_confluent_avro(
        _ENTITY_DIRTIED_SCHEMA_PATH,
        {
            "event_id": str(new_uuid7()),
            "event_type": "entity.dirtied",
            "schema_version": 1,
            "occurred_at": utc_now().isoformat(),
            "entity_id": str(entity_id),
            "dirty_reason": "new_evidence",
            "source_doc_id": str(source_doc_id),
            "correlation_id": correlation_id,
        },
    )


# ---------------------------------------------------------------------------
# Main block function
# ---------------------------------------------------------------------------


async def materialize_graph(
    *,
    doc_id: UUID,
    source_type: str,
    is_backfill: bool,
    relations: list[RawRelation],
    canonical_types: list[str | None],
    canonical_semantic_modes: list[str | None],
    canonical_decay_classes: list[str | None],
    canonical_decay_alphas: list[float | None],
    canonical_base_confidences: list[float | None],
    events: list[RawEvent],
    claims: list[RawClaim],
    session: AsyncSession,
    relation_repo: RelationRepository,
    evidence_repo: RelationEvidenceRepository,
    outbox_repo: OutboxRepository,
    correlation_id: str | None = None,
    extraction_model_id: str | None = None,
    source_name: str | None = None,
    source_type_metadata: str | None = None,
) -> MaterializationSummary:
    """Materialize graph from a single enriched article message.

    ``canonical_types`` must be the same length as ``relations`` and contain
    the canonicalized type for each relation (``None`` if proposed/unknown —
    those relations are still written with ``canonical_type=None``).

    Metadata arrays (semantic mode, decay class/alpha, base confidence) must
    be the same length/order as ``relations`` as returned by Block 11.

    Advisory lock + upsert + evidence are written atomically within the
    caller-managed *session* transaction.  The caller must commit/rollback.

    .. note:: PLAN-0031 C-1 — this function does NOT produce
       ``entity.dirtied.v1`` Kafka messages.  It returns the set of entity
       IDs that need dirtying via ``MaterializationSummary.entity_ids_to_dirty``.
       The **caller** must produce those messages AFTER ``session.commit()``
       to prevent orphaned Kafka events for rolled-back writes.

    Args:
    ----
        doc_id: Source document ID.
        source_type: Source type string (e.g. ``"news"``).
        is_backfill: Whether this is a backfill message.
        relations: Raw relation objects extracted from the document.
        canonical_types: Canonicalized types (same order as *relations*).
        canonical_semantic_modes: Canonical semantic modes per relation.
        canonical_decay_classes: Canonical decay classes per relation.
        canonical_decay_alphas: Canonical decay alphas per relation.
        canonical_base_confidences: Canonical base confidence per relation.
        events: Raw event objects extracted from the document.
        claims: Raw claim objects extracted from the document.
        session: Intelligence_db async session (caller-managed transaction).
        relation_repo: For advisory lock + upsert.
        evidence_repo: For insert_raw.
        outbox_repo: For graph.state.changed.v1 outbox append.
        correlation_id: Propagated correlation ID.
        extraction_model_id: LLM model ID that produced the extraction
            (PLAN-0031 B-2).  Stored on each ``claims`` row so downstream
            consumers know which model version produced the claim.

    Returns:
    -------
        :class:`MaterializationSummary` with counts and ``entity_ids_to_dirty``.

    """
    now = utc_now()
    dirtied_entities: set[UUID] = set()
    evidence_count = 0
    event_count = 0
    claim_count = 0
    relation_ids: list[str] = []
    affected_entity_ids: set[UUID] = set()

    # ------------------------------------------------------------------
    # 1+2 — Relations: advisory lock + upsert + insert relation_evidence_raw
    # ------------------------------------------------------------------
    for (
        rel,
        canonical_type,
        semantic_mode,
        decay_class,
        decay_alpha,
        base_confidence,
    ) in zip(
        relations,
        canonical_types,
        canonical_semantic_modes,
        canonical_decay_classes,
        canonical_decay_alphas,
        canonical_base_confidences,
        strict=True,
    ):
        # ── Self-loop guard (BP-385) ──────────────────────────────────────
        # graphology is initialised with allowSelfLoops=false; self-loop
        # triples also pollute the KG with tautological statements.
        # Skip both the relation upsert AND the evidence insert so these
        # are not stored at all. The check runs on fully-resolved UUIDs so
        # it catches loops introduced by entity merges inside S7, not just
        # those from S6 extraction.
        if rel.subject_entity_id == rel.object_entity_id:
            _log.warning(
                "relation_self_loop_skipped",
                entity_id=str(rel.subject_entity_id),
                raw_type=rel.raw_type,
            )
            continue

        # ── P0 claim_id fix (2026-06-11) ─────────────────────────────────
        # ``relation_evidence_raw.claim_id`` is NOT NULL (migration 0047,
        # PLAN-0093 T-B-3-01) but S6 cannot supply a real claim_id: claims
        # are not persisted in nlp_db (legacy claims topic removed in
        # PLAN-0057 D-1) and LLM extraction returns relations and claims as
        # UNLINKED arrays. The writer guard added on 2026-05-23 therefore
        # rejected every news-path evidence row — relation_evidence_raw was
        # dead for news since then. The original T-B-3-02 intent is restored
        # here: when the relation carries no claim_id, mint a REAL ``claims``
        # row from the relation's own evidence and link the evidence row to
        # it, keeping the relation → evidence → claim provenance chain intact
        # (F-DB-008). Never fabricate a UUID that points at nothing.
        evidence_claim_id = rel.claim_id
        if evidence_claim_id is None:
            backing_claim = RawClaim(
                subject_entity_id=rel.subject_entity_id,
                # Prefer the canonicalized type; fall back to the raw LLM
                # predicate so the claim is still queryable by type.
                claim_type=(canonical_type or rel.raw_type or "RELATION_EVIDENCE")[:100],
                polarity=rel.polarity,
                # claims.claim_text is NOT NULL — use the evidence sentence,
                # falling back to a structured triple description.
                claim_text=rel.evidence_text or f"{rel.subject_entity_id} {rel.raw_type} {rel.object_entity_id}",
                extraction_confidence=rel.extraction_confidence,
                chunk_id=rel.chunk_id,
                is_backfill=rel.is_backfill or is_backfill,
            )
            evidence_claim_id = await _insert_claim(
                session,
                doc_id,
                backing_claim,
                extraction_model_id=extraction_model_id,
            )
            claim_count += 1
            _log.debug(
                "evidence_claim_autocreated",
                doc_id=str(doc_id),
                claim_id=str(evidence_claim_id),
                raw_type=rel.raw_type,
            )

        # ── chunk_id fallback (backlog replay only) ──────────────────────
        # New producer messages (2026-06-11 onward) carry a real nlp_db
        # chunk_id matched against the evidence text. Messages produced
        # between 2026-05-23 and the producer fix have NO chunk_id key, yet
        # the column is NOT NULL. There is no chunks table in intelligence_db
        # and reading nlp_db would violate R9 (no cross-service DB access),
        # so for those legacy messages we derive a DETERMINISTIC doc-scoped
        # placeholder (uuid5 of doc_id) — stable across replays (idempotent)
        # and clearly flagged in logs. It does not resolve to an nlp_db chunk
        # row; provenance for legacy rows is anchored by source_document_id.
        evidence_chunk_id = rel.chunk_id
        if evidence_chunk_id is None:
            evidence_chunk_id = UUID(uuid5_from_parts(str(doc_id), "missing_chunk_fallback"))
            _log.warning(
                "evidence_chunk_id_fallback",
                doc_id=str(doc_id),
                chunk_id=str(evidence_chunk_id),
                message="legacy enriched message lacks chunk_id; using deterministic doc-scoped fallback",
            )

        # Skip provisional entities from the aggregation worker perspective,
        # but still INSERT the raw evidence row (entity_provisional=true rows
        # are held until entity.canonical.created.v1 resolves them).
        if canonical_type is not None:
            relation_id = await relation_repo.upsert(
                subject_entity_id=rel.subject_entity_id,
                object_entity_id=rel.object_entity_id,
                canonical_type=canonical_type,
                semantic_mode=semantic_mode or "RELATION_STATE",
                decay_class=decay_class or "DURABLE",
                decay_alpha=decay_alpha if decay_alpha is not None else 0.000950,
                base_confidence=base_confidence if base_confidence is not None else rel.extraction_confidence,
            )
            relation_ids.append(str(relation_id))
        else:
            # Unknown type — still stage the evidence; canonical_type stays NULL
            relation_id = None  # type: ignore[assignment]

        await evidence_repo.insert_raw(
            subject_entity_id=rel.subject_entity_id,
            object_entity_id=rel.object_entity_id,
            source_document_id=doc_id,
            extraction_confidence=rel.extraction_confidence,
            source_trust_weight=rel.source_trust_weight,
            evidence_date=rel.evidence_date,
            canonical_type=canonical_type,
            polarity=rel.polarity,
            # P0 fix: always a real claims-row UUID (incoming or auto-created).
            claim_id=evidence_claim_id,
            chunk_id=evidence_chunk_id,
            is_backfill=rel.is_backfill or is_backfill,
            entity_provisional=rel.entity_provisional,
            provisional_queue_id=rel.provisional_queue_id,
            evidence_text=rel.evidence_text,
            # T-B-03: propagate source metadata from the enriched event.
            source_name=source_name,
            source_type=source_type_metadata,
        )
        evidence_count += 1
        affected_entity_ids.add(rel.subject_entity_id)
        affected_entity_ids.add(rel.object_entity_id)

        # Dirty both entities (aggregation worker will recompute confidence)
        dirtied_entities.add(rel.subject_entity_id)
        dirtied_entities.add(rel.object_entity_id)

    # ------------------------------------------------------------------
    # 3 — Events + event_entities (ON CONFLICT DO NOTHING)
    # ------------------------------------------------------------------
    for event in events:
        await _insert_event_and_entities(session, doc_id, event)
        event_count += 1
        affected_entity_ids.add(event.subject_entity_id)

    # ------------------------------------------------------------------
    # 4 — Claims (ON CONFLICT DO NOTHING)
    # ------------------------------------------------------------------
    for raw_claim in claims:
        await _insert_claim(session, doc_id, raw_claim, extraction_model_id=extraction_model_id)
        claim_count += 1
        affected_entity_ids.add(raw_claim.subject_entity_id)

    # ------------------------------------------------------------------
    # 5 — entity.dirtied.v1: accumulate IDs for post-commit produce
    # ------------------------------------------------------------------
    # PLAN-0031 C-1: Previously produced here INSIDE the transaction.
    # Now returned to the caller who produces AFTER session.commit().
    # See _build_entity_dirtied_payload() for the message builder.

    # ------------------------------------------------------------------
    # 6 — graph.state.changed.v1 via outbox
    # ------------------------------------------------------------------
    # PLAN-0062 F-006: serialise via Confluent-Avro wire format (5-byte magic
    # header + Avro body) BEFORE the outbox append.  All preceding DB writes
    # (relations, evidence, events, claims) have already happened; failing the
    # outbox row here would orphan those rows from S10 fan-out.  Keeping the
    # serialise→append ordering tight (no DB calls between them) keeps the
    # failure mode "outbox row never inserted" rather than "outbox row inserted
    # with garbage bytes", which the dispatcher cannot recover from.
    if affected_entity_ids or relations or events:
        primary_entity_id = str(next(iter(affected_entity_ids))) if affected_entity_ids else str(doc_id)
        state_payload: dict[str, Any] = {
            "event_id": str(new_uuid7()),
            "event_type": "graph.state.changed",
            "schema_version": 1,
            "occurred_at": now.isoformat(),
            "primary_entity_id": primary_entity_id,
            "affected_entity_ids": [str(e) for e in affected_entity_ids],
            "change_type": "new_evidence",
            "relation_ids": relation_ids,
            "canonical_types": [t for t in canonical_types if t is not None],
            "source_doc_id": str(doc_id),
            "is_backfill": is_backfill,
            "correlation_id": correlation_id,
        }

        from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

        state_bytes = serialize_confluent_avro(_GRAPH_STATE_CHANGED_SCHEMA_PATH, state_payload)
        # Outbox requires an explicit event_id for idempotent replay (see
        # OutboxRepository.append). A UUID7 is monotonic + unique per call.
        await outbox_repo.append(
            topic=TOPIC_GRAPH_STATE_CHANGED,
            partition_key=primary_entity_id,
            payload_avro=state_bytes,
            event_id=new_uuid7(),
        )

    return MaterializationSummary(
        relations_upserted=len([c for c in canonical_types if c is not None]),
        evidence_rows_inserted=evidence_count,
        events_inserted=event_count,
        claims_inserted=claim_count,
        entities_dirtied=len(dirtied_entities),
        entity_ids_to_dirty=frozenset(dirtied_entities),
    )
