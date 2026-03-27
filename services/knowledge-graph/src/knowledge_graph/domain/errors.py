"""Domain error hierarchy for the Knowledge Graph service (S7)."""

from __future__ import annotations


class KnowledgeGraphError(Exception):
    """Base error for all S7 domain exceptions."""


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
