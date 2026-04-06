"""Domain enumerations for the Knowledge Graph service (S7)."""

from __future__ import annotations

from enum import StrEnum


class SemanticMode(StrEnum):
    """Two semantic modes that govern how evidence ages and contradictions resolve (PRD §6.7 Block 11).

    RELATION_STATE — active/inactive; event-triggered invalidation; decay via decay_class_config.
    TEMPORAL_CLAIM — historically anchored; not validity-gated; decay via decay_class_config.
    """

    RELATION_STATE = "RELATION_STATE"
    TEMPORAL_CLAIM = "TEMPORAL_CLAIM"


class DecayClass(StrEnum):
    """Meta decay class used in the confidence formula.

    STANDARD — use the decay_alpha from the relation's decay_class_config row.
    TEMPORAL — override with 0.02310 (30-day half-life, regardless of relation type).

    Note: The underlying DB stores fine-grained decay classes (PERMANENT, DURABLE, SLOW,
    MEDIUM, FAST, EPHEMERAL).  This enum captures the *formula-level* distinction.
    """

    STANDARD = "STANDARD"
    TEMPORAL = "TEMPORAL"


class RelationType(StrEnum):
    """8 well-known relation types for typed application code (PRD §6.7 Block 11).

    The full registry lives in ``relation_type_registry`` (20 seed rows).
    These are the most commonly referenced types in domain logic.
    """

    EMPLOYS = "employs"
    BOARD_MEMBER_OF = "board_member_of"
    SUBSIDIARY_OF = "subsidiary_of"
    ACQUIRED_BY = "acquired_by"
    LISTED_ON = "listed_on"
    SUPPLIER_OF = "supplier_of"
    PARTNER_OF = "partner_of"
    COMPETES_WITH = "competes_with"
