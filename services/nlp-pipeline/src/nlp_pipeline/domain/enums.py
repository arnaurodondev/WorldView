"""Domain enumerations for the NLP Pipeline service."""

from __future__ import annotations

from enum import StrEnum


class WindowType(StrEnum):
    """Price-impact window types for ArticleImpactWindow (PRD-0026 §6.5).

    Four active daily-proxy windows are computed now; two intraday windows
    are reserved for future use when intraday OHLCV data becomes available.
    """

    DAY_T0 = "day_t0"  # Publication-day OHLCV bar (open → close); cap 5%
    DAY_T1 = "day_t1"  # Following-day bar; cap 5%
    DAY_T2 = "day_t2"  # 2-day cumulative (close_t0 → close_t2); cap 7.5%
    DAY_T5 = "day_t5"  # 5-trading-day cumulative (close_t0 → close_t5); cap 10%
    INTRADAY_1H = "intraday_1h"  # Reserved; not computed in v1
    INTRADAY_4H = "intraday_4h"  # Reserved; not computed in v1


class DataQuality(StrEnum):
    """Source quality for price measurements (PRD-0026 §6.5).

    All rows in the current implementation use DAILY_PROXY. EXACT_INTRADAY
    is reserved for future intraday OHLCV data that does not exist yet.
    """

    DAILY_PROXY = "daily_proxy"  # Computed from daily OHLCV bar (current)
    EXACT_INTRADAY = "exact_intraday"  # Reserved: true intraday price window


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
    """Entity resolution outcome per mention (PRD §6.7 Block 9 + PLAN-0033).

    Block 9 outcomes (initial processing):
      AUTO_RESOLVED — composite score ≥ 0.72; resolved_entity_id set
      PROVISIONAL   — 0.45 ≤ composite < 0.72; queued in provisional_entity_queue
      UNRESOLVED    — composite < 0.45; mention preserved, never discarded

    UnresolvedResolutionWorker outcomes (two-phase re-resolution):
      ESCALATED     — mention is currently being processed by the worker (transient
                      lock state; reset by recover_stale_escalated() if stuck > 30 min)
      ENTITY_CREATED — LLM confirmed genuine entity; provisional_entity_queue row inserted
      NOISE          — LLM classified mention as not a real entity; kept for audit trail
    """

    # ── Block 9 initial outcomes ──────────────────────────────────────────────
    AUTO_RESOLVED = "auto_resolved"  # composite ≥ 0.72
    PROVISIONAL = "provisional"  # 0.45 ≤ composite < 0.72
    UNRESOLVED = "unresolved"  # < 0.45 — NEVER discarded

    # ── UnresolvedResolutionWorker outcomes (PLAN-0033 Wave 3) ───────────────
    ESCALATED = "escalated"  # transient: worker claimed the mention
    ENTITY_CREATED = "entity_created"  # LLM: genuine entity → provisional queue
    NOISE = "noise"  # LLM: not a real entity → kept for audit
