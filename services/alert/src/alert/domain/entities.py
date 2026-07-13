"""Domain entities for the Alert service (S10).

All entities are plain dataclasses — no infrastructure imports.
IDs are UUIDv7 (``common.ids.new_uuid7``), timestamps UTC-only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from alert.domain.enums import (
    AlertSeverity,
    AlertType,
    DeliveryChannel,
    DeliveryStatus,
    DLQStatus,
    OutboxStatus,
    RuleType,
)
from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

# Per-type cooldown defaults (seconds) — PRD-0113 §6.5.2. KG_CONNECTION uses 0
# because it latches on ``connected=true`` and fires exactly once.
DEFAULT_COOLDOWN_SECONDS: dict[RuleType, int] = {
    RuleType.PRICE_CROSS: 3600,
    RuleType.NEWS_COUNT: 21600,
    RuleType.NEWS_MOMENTUM: 21600,
    RuleType.KG_CONNECTION: 0,
    RuleType.FUNDAMENTAL_CROSS: 86400,
    # PLAN-0056 Wave D3 — prediction signals can arrive in bursts (a market
    # moving in steps); a 1h cooldown collapses a run of moves into one alert
    # per rule, mirroring the fanout path's 300s dedup at a coarser cadence.
    RuleType.PREDICTION: 3600,
}

# ---------------------------------------------------------------------------
# SeverityThresholds — value object for market_impact_score classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeverityThresholds:
    """Classifies a market_impact_score float into an AlertSeverity tier (PRD-0021 §6.5).

    Invariant: ``critical > high > medium >= 0.0``; raises ValueError otherwise.
    """

    critical: float = 0.85
    high: float = 0.65
    medium: float = 0.40

    def __post_init__(self) -> None:
        if self.medium < 0.0:
            raise ValueError(f"medium threshold must be >= 0.0, got {self.medium}")
        if not (self.critical > self.high > self.medium):
            raise ValueError(
                f"Thresholds must satisfy critical > high > medium; "
                f"got critical={self.critical}, high={self.high}, medium={self.medium}"
            )

    def classify(self, market_impact_score: float) -> AlertSeverity:
        """Return the severity tier for a given market_impact_score."""
        if market_impact_score >= self.critical:
            return AlertSeverity.CRITICAL
        if market_impact_score >= self.high:
            return AlertSeverity.HIGH
        if market_impact_score >= self.medium:
            return AlertSeverity.MEDIUM
        return AlertSeverity.LOW


# ---------------------------------------------------------------------------
# Alert — the core entity persisted in ``alerts`` table
# ---------------------------------------------------------------------------


@dataclass
class Alert:
    """A materialised alert created when a signal affects a watched entity.

    ``dedup_key`` is ``sha256(entity_id + alert_type + window_bucket)``
    where ``window_bucket = created_at_epoch // dedup_window_seconds``.
    A UNIQUE constraint on ``dedup_key`` prevents duplicate noise (AD-9).
    """

    alert_id: UUID = field(default_factory=new_uuid7)
    entity_id: UUID = field(default_factory=new_uuid7)
    alert_type: AlertType = AlertType.SIGNAL
    severity: AlertSeverity = AlertSeverity.LOW
    source_event_id: UUID = field(default_factory=new_uuid7)
    source_topic: str = ""
    payload: dict[str, object] = field(default_factory=dict)
    dedup_key: str = ""
    created_at: datetime = field(default_factory=utc_now)
    tenant_id: UUID | None = field(default=None)
    # ── Enrichment fields (PLAN-0049 T-A-1-02) ────────────────────────────────
    # All four nullable / Optional so existing constructors and existing DB rows
    # remain valid — these are forward-compatible additions (BP-007, BP-019).
    # Source of truth for the user-facing alert subject. ``title`` is composed
    # in AlertFanoutUseCase from ``signal_label`` + ``entity_name`` / ``ticker``.
    title: str | None = None
    ticker: str | None = None
    entity_name: str | None = None
    signal_label: str | None = None
    # ── Acknowledgement + snooze fields (PLAN-0051 T-D-4-01) ──────────────────
    # All three nullable / Optional so existing constructors and existing DB rows
    # remain valid — these are forward-compatible additions (BP-007, BP-019).
    # ``acknowledged_at`` and ``acknowledged_by_user_id`` are set together by
    # the AcknowledgeAlertUseCase; idempotent (subsequent acks are no-ops).
    # ``snooze_until`` is a future UTC timestamp at which the alert reappears
    # in the active list. SnoozeAlertUseCase enforces (now < until <= now+30d).
    acknowledged_at: datetime | None = None
    acknowledged_by_user_id: UUID | None = None
    snooze_until: datetime | None = None

    @staticmethod
    def compute_dedup_key(
        entity_id: UUID,
        alert_type: AlertType,
        created_at: datetime,
        window_seconds: int = 300,
        discriminator: str | None = None,
    ) -> str:
        """Compute dedup key per AD-9: sha256(entity_id + alert_type + window_bucket).

        ``source_event_id`` is intentionally excluded so that multiple events
        about the same entity+type within one window are deduplicated (the
        intended per-entity+type collapse for SIGNAL/GRAPH/CONTRADICTION).

        ``discriminator`` (PLAN-0056 QA) is an optional extra key component that
        splits the dedup bucket further. For PREDICTION alerts the fanout passes
        ``market_id`` (+ ``trigger``) here so that two DISTINCT prediction
        markets referencing the SAME entity within one window each raise their
        own alert instead of one silently suppressing the other. When ``None``
        the key is identical to the historical per-entity+type key, so existing
        collapse behaviour for the other alert types is unchanged.
        """
        epoch = int(created_at.replace(tzinfo=UTC).timestamp())
        window_bucket = epoch // window_seconds
        raw = f"{entity_id}:{alert_type}:{window_bucket}"
        if discriminator:
            raw = f"{raw}:{discriminator}"
        return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# PendingAlert — per-user pending delivery row
# ---------------------------------------------------------------------------


@dataclass
class PendingAlert:
    """A pending alert awaiting acknowledgement by a user."""

    pending_id: UUID = field(default_factory=new_uuid7)
    user_id: UUID = field(default_factory=new_uuid7)
    alert_id: UUID = field(default_factory=new_uuid7)
    created_at: datetime = field(default_factory=utc_now)
    delivered_at: datetime | None = None


# ---------------------------------------------------------------------------
# AlertDelivery — tracks per-user delivery
# ---------------------------------------------------------------------------


@dataclass
class AlertDelivery:
    """Records that an alert was delivered to a user on a specific channel."""

    delivery_id: UUID = field(default_factory=new_uuid7)
    alert_id: UUID = field(default_factory=new_uuid7)
    user_id: UUID = field(default_factory=new_uuid7)
    channel: DeliveryChannel = DeliveryChannel.WEBSOCKET
    status: DeliveryStatus = DeliveryStatus.DELIVERED
    delivered_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# AlertSubscription — user→entity subscription
# ---------------------------------------------------------------------------


@dataclass
class AlertSubscription:
    """User subscription to alerts for a specific entity via a watchlist."""

    subscription_id: UUID = field(default_factory=new_uuid7)
    user_id: UUID = field(default_factory=new_uuid7)
    entity_id: UUID = field(default_factory=new_uuid7)
    watchlist_id: UUID = field(default_factory=new_uuid7)
    alert_types: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    deleted_at: datetime | None = None


# ---------------------------------------------------------------------------
# OutboxEvent — transactional outbox row
# ---------------------------------------------------------------------------


@dataclass
class OutboxEvent:
    """Outbox event for reliable Kafka publishing."""

    event_id: UUID = field(default_factory=new_uuid7)
    topic: str = ""
    partition_key: str = ""
    # b"" sentinel: serialization failed; original message payload is lost. See BP-040.
    payload_avro: bytes = b""
    status: OutboxStatus = OutboxStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    dispatched_at: datetime | None = None
    retry_count: int = 0
    failed_at: datetime | None = None


# ---------------------------------------------------------------------------
# DeadLetterEntry — DLQ row
# ---------------------------------------------------------------------------


@dataclass
class DeadLetterEntry:
    """Dead-letter queue entry for failed outbox dispatches."""

    dlq_id: UUID = field(default_factory=new_uuid7)
    original_event_id: UUID = field(default_factory=new_uuid7)
    topic: str = ""
    # b"" sentinel: serialization failed; original message payload is lost. See BP-040.
    payload_avro: bytes = b""
    error_detail: str | None = None
    status: DLQStatus = DLQStatus.FAILED
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: datetime | None = None
    resolution_note: str | None = None


# ---------------------------------------------------------------------------
# EmailPreference — user email notification settings (PRD-0016 §6.5)
# ---------------------------------------------------------------------------


@dataclass
class EmailPreference:
    """User preferences for the weekly portfolio risk email digest.

    ``send_day_of_week`` is 0=Monday to 6=Sunday.
    ``send_hour_utc`` is 0-23.
    ``email_address`` is nullable - falls back to the user's account email
    fetched from S1 ``GET /internal/v1/users/{user_id}`` at send time.
    """

    user_id: UUID = field(default_factory=new_uuid7)
    tenant_id: UUID = field(default_factory=new_uuid7)
    weekly_digest_enabled: bool = True
    send_day_of_week: int = 6  # Sunday
    send_hour_utc: int = 8
    email_address: str | None = None
    last_digest_sent_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not (0 <= self.send_day_of_week <= 6):
            raise ValueError(f"send_day_of_week must be 0-6, got {self.send_day_of_week}")
        if not (0 <= self.send_hour_utc <= 23):
            raise ValueError(f"send_hour_utc must be 0-23, got {self.send_hour_utc}")


# ---------------------------------------------------------------------------
# EvalResult — value object produced by a RuleEvaluator (PLAN-0113 §6.5.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalResult:
    """A single evaluation observation for a rule.

    One evaluator populates whichever fields its rule type cares about:
      - PRICE_CROSS / FUNDAMENTAL_CROSS → ``value``
      - NEWS_COUNT                      → ``count``
      - NEWS_MOMENTUM                   → ``delta_pct`` + ``count``
      - KG_CONNECTION                   → ``connected``

    The shared ``AlertRule.should_fire`` / ``next_state`` turn an ``EvalResult``
    into a fire/no-fire decision + the new ``last_state`` (edge + cooldown).
    """

    observed_at: datetime
    value: float | None = None
    count: int | None = None
    delta_pct: float | None = None
    connected: bool | None = None


# ---------------------------------------------------------------------------
# AlertRule — standing-rule aggregate persisted in ``alert_rules`` (PLAN-0113)
# ---------------------------------------------------------------------------


@dataclass
class AlertRule:
    """A user's standing alert rule (one row in ``alert_rules``).

    ``last_state`` is the edge-trigger memory persisted as JSONB. Recognised keys
    (all optional): ``was_above`` (bool), ``last_value`` (float), ``last_count``
    (int), ``connected`` (bool), ``last_fired_at`` (ISO str),
    ``last_checked_at`` (ISO str).

    Invariants (enforced in ``create``):
      - KG_CONNECTION needs ``node_a_entity_id`` ≠ ``node_b_entity_id`` (both set);
      - all other types need ``entity_id`` set.
    """

    rule_type: RuleType
    name: str
    tenant_id: UUID
    user_id: UUID
    condition: dict[str, object] = field(default_factory=dict)
    rule_id: UUID = field(default_factory=new_uuid7)
    entity_id: UUID | None = None
    node_a_entity_id: UUID | None = None
    node_b_entity_id: UUID | None = None
    severity: AlertSeverity = AlertSeverity.MEDIUM
    enabled: bool = True
    cooldown_seconds: int = 0
    notify_in_app: bool = True
    notify_email: bool = False
    last_state: dict[str, object] | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        rule_type: RuleType,
        name: str,
        tenant_id: UUID,
        user_id: UUID,
        condition: dict[str, object],
        entity_id: UUID | None = None,
        node_a_entity_id: UUID | None = None,
        node_b_entity_id: UUID | None = None,
        severity: AlertSeverity = AlertSeverity.MEDIUM,
        enabled: bool = True,
        cooldown_seconds: int | None = None,
        notify_in_app: bool = True,
        notify_email: bool = False,
    ) -> AlertRule:
        """Factory that enforces the keying invariant + per-type cooldown default."""
        if rule_type is RuleType.KG_CONNECTION:
            if node_a_entity_id is None or node_b_entity_id is None:
                raise ValueError("KG_CONNECTION requires both node_a_entity_id and node_b_entity_id")
            if node_a_entity_id == node_b_entity_id:
                raise ValueError("KG_CONNECTION node_a_entity_id must differ from node_b_entity_id")
        elif entity_id is None:
            raise ValueError(f"{rule_type} requires entity_id")

        if cooldown_seconds is None:
            cooldown_seconds = DEFAULT_COOLDOWN_SECONDS[rule_type]
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        now = utc_now()
        return cls(
            rule_type=rule_type,
            name=name,
            tenant_id=tenant_id,
            user_id=user_id,
            condition=condition,
            entity_id=entity_id,
            node_a_entity_id=node_a_entity_id,
            node_b_entity_id=node_b_entity_id,
            severity=severity,
            enabled=enabled,
            cooldown_seconds=cooldown_seconds,
            notify_in_app=notify_in_app,
            notify_email=notify_email,
            created_at=now,
            updated_at=now,
        )

    # ── Edge-trigger + cooldown ──────────────────────────────────────────────

    def _in_cooldown(self, now: datetime) -> bool:
        """True if a fire occurred within ``cooldown_seconds`` of ``now``."""
        if self.cooldown_seconds <= 0:
            return False
        last_fired = self._last_fired_at()
        if last_fired is None:
            return False
        return (now - last_fired).total_seconds() < self.cooldown_seconds

    def _last_fired_at(self) -> datetime | None:
        if not self.last_state:
            return None
        raw = self.last_state.get("last_fired_at")
        if not isinstance(raw, str):
            return None
        return datetime.fromisoformat(raw)

    def _current_above(self, result: EvalResult) -> bool:
        """For cross rules: is the observed value on the 'fired' side of the threshold?"""
        target = float(self.condition["value"])  # type: ignore[arg-type]
        observed = result.value if result.value is not None else target
        operator = self.condition.get("operator", "above")
        return observed >= target if operator == "above" else observed <= target

    def should_fire(self, result: EvalResult, now: datetime) -> bool:
        """Return True iff this observation is a *new* trigger edge (not in cooldown).

        Edge semantics per type:
          - cross types (price/fundamental): fire on the no→yes transition of the
            operator condition (``was_above`` flips from False/None to True).
          - count types: fire when count first reaches threshold (re-arms below).
          - momentum: fire when delta_pct ≥ threshold AND count ≥ min_count, on edge.
          - kg_connection: latch — fire once when ``connected`` first becomes True.
        """
        if self._in_cooldown(now):
            return False

        if self.rule_type in (RuleType.PRICE_CROSS, RuleType.FUNDAMENTAL_CROSS):
            if result.value is None:
                return False
            was_above = bool(self.last_state.get("was_above")) if self.last_state else False
            return self._current_above(result) and not was_above

        if self.rule_type == RuleType.NEWS_COUNT:
            if result.count is None:
                return False
            threshold = int(self.condition["threshold"])  # type: ignore[call-overload]
            last_above = (
                int(self.last_state["last_count"]) >= threshold  # type: ignore[call-overload]
                if self.last_state and self.last_state.get("last_count") is not None
                else False
            )
            return result.count >= threshold and not last_above

        if self.rule_type == RuleType.NEWS_MOMENTUM:
            if result.delta_pct is None or result.count is None:
                return False
            min_delta = float(self.condition["delta_pct"])  # type: ignore[arg-type]
            min_count = int(self.condition.get("min_count", 2))  # type: ignore[call-overload]
            currently = result.delta_pct >= min_delta and result.count >= min_count
            was = bool(self.last_state.get("was_above")) if self.last_state else False
            return currently and not was

        if self.rule_type == RuleType.KG_CONNECTION:
            if not result.connected:
                return False
            already = bool(self.last_state.get("connected")) if self.last_state else False
            return not already

        if self.rule_type == RuleType.PREDICTION:
            # A prediction signal carries its gating score in ``result.value``
            # (the event's ``market_impact_score``, already adverse-boosted by
            # S7 D2). Fire when the score clears the rule's ``min_impact_score``
            # floor. Bursts are collapsed by the per-type cooldown above rather
            # than an edge flag — each qualifying signal is an independent
            # observation, unlike the held-state cross rules.
            if result.value is None:
                return False
            floor = float(self.condition.get("min_impact_score", 0.0))  # type: ignore[arg-type]
            return result.value >= floor

        return False

    def next_state(self, result: EvalResult, now: datetime, *, fired: bool) -> dict[str, object]:
        """Compute the new ``last_state`` dict after an evaluation.

        ``last_checked_at`` always advances; ``last_fired_at`` advances only when
        the rule fired this cycle.
        """
        state: dict[str, object] = dict(self.last_state or {})
        state["last_checked_at"] = now.isoformat()

        if self.rule_type in (RuleType.PRICE_CROSS, RuleType.FUNDAMENTAL_CROSS):
            if result.value is not None:
                state["last_value"] = result.value
                state["was_above"] = self._current_above(result)
        elif self.rule_type == RuleType.NEWS_COUNT:
            if result.count is not None:
                state["last_count"] = result.count
        elif self.rule_type == RuleType.NEWS_MOMENTUM:
            if result.delta_pct is not None and result.count is not None:
                min_delta = float(self.condition["delta_pct"])  # type: ignore[arg-type]
                min_count = int(self.condition.get("min_count", 2))  # type: ignore[call-overload]
                state["was_above"] = result.delta_pct >= min_delta and result.count >= min_count
        elif self.rule_type == RuleType.KG_CONNECTION and result.connected is not None:
            state["connected"] = result.connected
        elif self.rule_type == RuleType.PREDICTION and result.value is not None:
            state["last_value"] = result.value

        if fired:
            state["last_fired_at"] = now.isoformat()
        return state

    def is_due(self, now: datetime, cadence_seconds: int) -> bool:
        """Poller throttle: True if at least ``cadence_seconds`` elapsed since last check."""
        if not self.last_state:
            return True
        raw = self.last_state.get("last_checked_at")
        if not isinstance(raw, str):
            return True
        last_checked = datetime.fromisoformat(raw)
        return (now - last_checked).total_seconds() >= cadence_seconds
