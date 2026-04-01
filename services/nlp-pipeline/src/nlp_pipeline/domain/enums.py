"""Domain enumerations for the NLP Pipeline service."""

from __future__ import annotations

from enum import StrEnum


class MentionClass(StrEnum):
    """11-class NER ontology (PRD §6.7 Block 4)."""

    ORGANIZATION = "organization"
    GOVERNMENT_BODY = "government_body"
    REGULATORY_BODY = "regulatory_body"
    FINANCIAL_INSTITUTION = "financial_institution"
    PERSON = "person"
    FINANCIAL_INSTRUMENT = "financial_instrument"
    LOCATION = "location"
    COMMODITY = "commodity"
    INDEX = "index"
    CURRENCY = "currency"
    MACROECONOMIC_INDICATOR = "macroeconomic_indicator"


class RoutingTier(StrEnum):
    """Document routing tier (PRD §6.7 Block 5)."""

    DEEP = "deep"
    MEDIUM = "medium"
    LIGHT = "light"
    SUPPRESS = "suppress"


class EmbeddingStatus(StrEnum):
    """Embedding generation status."""

    READY = "ready"
    PENDING = "pending"
    FAILED = "failed"


class ResolutionOutcome(StrEnum):
    """Entity resolution outcome per mention (PRD §6.7 Block 9)."""

    AUTO_RESOLVED = "auto_resolved"  # composite ≥ 0.72
    PROVISIONAL = "provisional"  # 0.45 ≤ composite < 0.72
    UNRESOLVED = "unresolved"  # < 0.45 — NEVER discarded
