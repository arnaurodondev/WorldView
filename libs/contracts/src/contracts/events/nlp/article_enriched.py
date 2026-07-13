"""Canonical model for the ``nlp.article.enriched.v1`` event.

PLAN-0062 Wave B.  Mirrors the Avro schema at
``infra/kafka/schemas/nlp.article.enriched.v1.avsc`` field-for-field.

The schema includes three nullable JSON-string fields
(``raw_relations_json``, ``raw_events_json``, ``raw_claims_json``) that
transport the rich extraction payload (lists of relation/event/claim dicts)
without requiring nested Avro record schemas — the KG ``enriched_consumer``
JSON-decodes these back into ``RawRelation`` / ``RawEvent`` / ``RawClaim``
dataclasses.

Field-alignment is asserted in
``libs/contracts/tests/test_events_nlp_article_enriched.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from observability import get_logger  # type: ignore[import-untyped]

_logger = get_logger(__name__)  # type: ignore[no-any-return]

# QA-iter1 (PLAN-0062): cap the JSON blob at ~16 MB.  Kafka's default
# max.message.bytes is 1 MB but operators may raise it; the cap is a
# defence-in-depth bound on the unbounded ``json.loads`` read.  Anything
# legitimate from the producer fits well under this — relation/event/claim
# arrays for one article are typically < 50 KB.
_MAX_RAW_ARRAY_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class CanonicalNlpArticleEnriched:
    """Trigger event published by S6 after full article enrichment.

    The KG ``EnrichedArticleConsumer`` materialises the knowledge graph from
    the ``raw_relations``/``raw_events``/``raw_claims`` payloads, which are
    transported through the ``*_json`` Avro string fields.
    """

    event_id: str
    occurred_at: str
    doc_id: str
    source_type: str
    routing_tier: str
    routing_score: float
    section_count: int
    chunk_count: int
    mention_count: int
    resolved_entity_ids: tuple[str, ...] = ()
    # D-INIT-6 (2026-05-09): added so evidence-row provenance flows producer→consumer
    # in the event payload itself.  KG enriched_consumer used to fall back to a query
    # against ``document_source_metadata`` (an nlp_db table) from its intelligence_db
    # session pool — that lookup was both an R7 cross-service-DB violation and a
    # guaranteed UndefinedTableError because the table only lives in nlp_db.
    # Nullable + default None keeps the schema forward-compatible (R5).
    source_name: str | None = None
    published_at: str | None = None
    is_backfill: bool = False
    relation_count: int = 0
    claim_count: int = 0
    event_count: int = 0
    provisional_entity_count: int = 0
    extraction_model_id: str | None = None
    raw_relations_json: str | None = None
    raw_events_json: str | None = None
    raw_claims_json: str | None = None
    correlation_id: str | None = None
    tenant_id: str | None = None
    # PLAN-0056 QA (BP-720): external_id/source_title are declared LAST among the
    # data fields to mirror the Avro record's END-appended order.  The wire schema
    # is decoded positionally by fastavro (schemaless, no Schema Registry), so
    # additive fields MUST sit at the tail of the record or a rolling deploy where
    # the producer ships new bytes before a consumer upgrades misreads every field
    # after the insertion point.  (Serialization is by-name via to_dict(), so this
    # declaration order is for consistency/readability with the .avsc — the bytes
    # come out identical regardless.)
    # PLAN-0056 Wave C2b (2026-07-10): stable upstream market/source identity
    # threaded S4→S5→S6 verbatim (e.g. "polymarket:<condition_id>").  Nullable +
    # default None keeps the schema forward-compatible (R5); legacy producers
    # that pre-date the field decode to None.  KG PredictionEnrichedConsumer
    # parses the condition_id out of it so temporal events resolve to a real
    # market instead of an anonymous doc_id.
    external_id: str | None = None
    # PLAN-0056 Wave C3 (2026-07-10): upstream document title copied verbatim from
    # content.article.stored.v1.title (S6 pure passthrough — no NER change).  For a
    # Polymarket synthetic doc this IS the market question, which S7's
    # PredictionEnrichedConsumer uses both as the temporal-event title and as the
    # input to MarketPolarityClassifier.  Nullable + default None keeps the schema
    # forward-compatible (R5); legacy producers decode to None.
    source_title: str | None = None
    event_type: str = field(default="nlp.article.enriched")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalNlpArticleEnriched:
        """Build the canonical model from a deserialized Avro/JSON dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            doc_id=str(d["doc_id"]),
            source_type=str(d["source_type"]),
            routing_tier=str(d["routing_tier"]),
            routing_score=float(d["routing_score"]),
            section_count=int(d["section_count"]),
            chunk_count=int(d["chunk_count"]),
            mention_count=int(d["mention_count"]),
            resolved_entity_ids=tuple(str(e) for e in d.get("resolved_entity_ids", []) or []),
            # D-INIT-6: source_name is optional on the wire (Avro default=null) and on
            # legacy events that pre-date the field; cast only when actually present.
            source_name=(str(d["source_name"]) if d.get("source_name") is not None else None),
            # PLAN-0056 Wave C2b: optional on the wire (Avro default=null) and on
            # legacy events; cast only when present.
            external_id=(str(d["external_id"]) if d.get("external_id") is not None else None),
            # PLAN-0056 Wave C3: optional on the wire (Avro default=null) and on
            # legacy events; cast only when present.
            source_title=(str(d["source_title"]) if d.get("source_title") is not None else None),
            published_at=(str(d["published_at"]) if d.get("published_at") is not None else None),
            is_backfill=bool(d.get("is_backfill", False)),
            relation_count=int(d.get("relation_count", 0)),
            claim_count=int(d.get("claim_count", 0)),
            event_count=int(d.get("event_count", 0)),
            provisional_entity_count=int(d.get("provisional_entity_count", 0)),
            extraction_model_id=(str(d["extraction_model_id"]) if d.get("extraction_model_id") is not None else None),
            raw_relations_json=(str(d["raw_relations_json"]) if d.get("raw_relations_json") is not None else None),
            raw_events_json=(str(d["raw_events_json"]) if d.get("raw_events_json") is not None else None),
            raw_claims_json=(str(d["raw_claims_json"]) if d.get("raw_claims_json") is not None else None),
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            tenant_id=(str(d["tenant_id"]) if d.get("tenant_id") is not None else None),
            event_type=str(d.get("event_type", "nlp.article.enriched")),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict matching the Avro schema field set."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "doc_id": self.doc_id,
            "source_type": self.source_type,
            # D-INIT-6: emit source_name even when None so the Avro union picks the
            # null branch rather than complaining about a missing field.
            "source_name": self.source_name,
            "published_at": self.published_at,
            "is_backfill": self.is_backfill,
            "routing_tier": self.routing_tier,
            "routing_score": self.routing_score,
            "section_count": self.section_count,
            "chunk_count": self.chunk_count,
            "mention_count": self.mention_count,
            "resolved_entity_ids": list(self.resolved_entity_ids),
            "relation_count": self.relation_count,
            "claim_count": self.claim_count,
            "event_count": self.event_count,
            "provisional_entity_count": self.provisional_entity_count,
            "extraction_model_id": self.extraction_model_id,
            "raw_relations_json": self.raw_relations_json,
            "raw_events_json": self.raw_events_json,
            "raw_claims_json": self.raw_claims_json,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            # PLAN-0056 QA (BP-720): emit external_id/source_title LAST to mirror the
            # END-appended Avro record order.  Emitted even when None so the Avro
            # union picks the null branch rather than reporting a missing field.
            "external_id": self.external_id,
            "source_title": self.source_title,
        }


def encode_raw_array(items: list[dict] | None) -> str | None:
    """Encode a raw_* list into the JSON string used by the Avro schema.

    Returns None for empty / None inputs so the Avro union picks the ``null``
    branch.  ``default=str`` handles UUID and datetime values that may appear
    in the dicts produced by S6.
    """
    if not items:
        return None
    return json.dumps(items, default=str)


def decode_raw_array(blob: str | None) -> list[dict]:
    """Decode a raw_*_json string back into a list of dicts.

    Returns an empty list on None / empty / malformed / oversized input.
    Callers always iterate, so a forgiving decode keeps the consumer
    resilient to legacy or schema-mismatched producers — but every
    silent-drop branch emits a structlog warning so the failure mode is
    observable (per QA-iter1 of PLAN-0062, addresses memory feedback
    "audit-returned-value-persistence" — silent drops were the failure
    pattern that previously masked 80% of S6 extraction loss).
    """
    if not blob:
        return []
    if len(blob) > _MAX_RAW_ARRAY_BYTES:
        _logger.warning(  # type: ignore[no-any-return]
            "raw_array_decode_oversized",
            blob_bytes=len(blob),
            cap_bytes=_MAX_RAW_ARRAY_BYTES,
        )
        return []
    try:
        decoded = json.loads(blob)
    except (TypeError, ValueError) as exc:
        _logger.warning(  # type: ignore[no-any-return]
            "raw_array_decode_json_error",
            error=str(exc),
            blob_prefix=blob[:60] if isinstance(blob, str) else None,
        )
        return []
    if not isinstance(decoded, list):
        _logger.warning(  # type: ignore[no-any-return]
            "raw_array_decode_not_list",
            decoded_type=type(decoded).__name__,
        )
        return []
    filtered = [item for item in decoded if isinstance(item, dict)]
    if len(filtered) != len(decoded):
        _logger.warning(  # type: ignore[no-any-return]
            "raw_array_decode_dropped_non_dict_items",
            received=len(decoded),
            kept=len(filtered),
        )
    return filtered
