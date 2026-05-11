"""Domain error hierarchy for the Knowledge Graph service (S7)."""

from __future__ import annotations


class DomainError(Exception):
    """Base error for all S7 domain exceptions (R21 canonical name)."""


class KnowledgeGraphError(DomainError):
    """Descriptive alias for S7 errors, extends DomainError."""


# ---------------------------------------------------------------------------
# Alembic guard
# ---------------------------------------------------------------------------


class IntelligenceDbAlembicError(KnowledgeGraphError):
    """Raised when ALEMBIC_ENABLED=true is detected for intelligence_db.

    S7 must NEVER run Alembic against intelligence_db — DDL is exclusively
    owned by the intelligence-migrations init container.
    """


# ---------------------------------------------------------------------------
# Relation errors
# ---------------------------------------------------------------------------


class RelationError(KnowledgeGraphError):
    """Base for relation-domain errors."""


class RelationNotFoundError(RelationError):
    """Raised when a relation cannot be found by its natural key."""


class RelationTypeUnknownError(RelationError):
    """Raised when a canonical_type is not present in relation_type_registry."""


class RelationTypeProposeRequired(RelationError):  # noqa: N818
    """Raised when a relation type is unknown and must be proposed via outbox."""


# ---------------------------------------------------------------------------
# Confidence errors
# ---------------------------------------------------------------------------


class ConfidenceError(KnowledgeGraphError):
    """Base for confidence-formula errors."""


class ConfidenceBoundsViolation(ConfidenceError):  # noqa: N818
    """Raised when computed confidence components violate invariants."""


# ---------------------------------------------------------------------------
# Entity errors
# ---------------------------------------------------------------------------


class EntityError(KnowledgeGraphError):
    """Base for entity-domain errors."""


class EntityNotFoundError(EntityError):
    """Raised when a canonical entity cannot be found."""


class EntityAliasCollisionError(EntityError):
    """Raised when an alias would collide with a different entity."""


# ---------------------------------------------------------------------------
# Contradiction errors
# ---------------------------------------------------------------------------


class ContradictionError(KnowledgeGraphError):
    """Base for contradiction-detection errors."""


# ---------------------------------------------------------------------------
# Embedding errors
# ---------------------------------------------------------------------------


class EmbeddingNotAvailableError(EntityError):
    """Raised when an entity has no embedding for the requested view type.

    Typically occurs when ``entity_type != 'financial_instrument'`` and the
    caller requests a ``fundamentals_ohlcv`` embedding (PRD-0017 §6.5).
    """

    def __init__(self, entity_id: object, view_type: str) -> None:
        super().__init__(f"No embedding available for entity {entity_id!r}, view_type={view_type!r}")


# ---------------------------------------------------------------------------
# Enrichment errors (PRD-0073 §9.5, §13)
# ---------------------------------------------------------------------------


class EnrichmentError(KnowledgeGraphError):
    """Base for Worker 13J enrichment errors."""


class RetryableEnrichmentError(EnrichmentError):
    """Transient failure — Kafka consumer should redeliver; enrichment_attempts NOT incremented.

    Used for: HTTP 429 (rate limit), HTTP 503, asyncio.TimeoutError on LLM call.
    """


class FatalEnrichmentError(EnrichmentError):
    """Non-retryable failure — enrichment_attempts IS incremented.

    Used for: LLM response < 20 chars, JSON parse error, persistent 400 from EODHD.
    """
