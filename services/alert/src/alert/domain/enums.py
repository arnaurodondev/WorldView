"""Domain enumerations for the Alert service (S10)."""

from __future__ import annotations

from enum import StrEnum


class AlertSeverity(StrEnum):
    """Severity tier of an alert, derived from market_impact_score (PRD-0021 §6.5)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(StrEnum):
    """The four signal categories that trigger alerts (PRD §6.5.5).

    USER_RULE was added in PLAN-0082 Wave B for user-initiated alert rules
    created via the LLM ``create_alert`` tool or the REST API.  The value
    ``"user_rule"`` (lowercase) intentionally diverges from the UPPER_CASE
    convention of the legacy types — it matches the ``source`` field value
    ``"llm_tool"`` style used throughout the alert.created.v1 Avro schema.
    Because ``alert_type`` is stored as VARCHAR(100) in Postgres (not a PG
    enum), no ALTER TYPE migration is required.
    """

    SIGNAL = "SIGNAL"
    GRAPH_CHANGE = "GRAPH_CHANGE"
    CONTRADICTION = "CONTRADICTION"
    USER_RULE = "user_rule"


class RuleType(StrEnum):
    """The 5 user-creatable standing-rule types (PLAN-0113 §6.5.1).

    Stored as VARCHAR(50) in ``alert_rules.rule_type`` (BP-007 — never a PG
    enum, so future rule types add zero DDL).  Each value pairs with a
    discriminated-union ``condition`` value object (``rule_conditions.py``)
    and a ``RuleEvaluator`` registered in ``application/rules/registry.py``.

    Keying (PRD §6.5.1):
      - PRICE_CROSS / NEWS_COUNT / NEWS_MOMENTUM / FUNDAMENTAL_CROSS → ``entity_id``
      - KG_CONNECTION → ``node_a_entity_id`` + ``node_b_entity_id`` (A ≠ B)
    """

    PRICE_CROSS = "PRICE_CROSS"
    NEWS_COUNT = "NEWS_COUNT"
    NEWS_MOMENTUM = "NEWS_MOMENTUM"
    KG_CONNECTION = "KG_CONNECTION"
    FUNDAMENTAL_CROSS = "FUNDAMENTAL_CROSS"


class OutboxStatus(StrEnum):
    """Lifecycle status of an outbox event row."""

    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"


class DeliveryChannel(StrEnum):
    """Alert delivery channel."""

    WEBSOCKET = "websocket"


class DeliveryStatus(StrEnum):
    """Status of a single alert delivery to a user."""

    PENDING = "pending"
    DELIVERED = "delivered"


class DLQStatus(StrEnum):
    """Status of a dead-letter-queue entry."""

    FAILED = "failed"
    RESOLVED = "resolved"
