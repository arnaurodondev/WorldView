"""FireRuleAlertUseCase — the shared firing path for standing rules (PLAN-0113 §6.5.5).

Given a ``(rule, eval_result)`` pair that already passed ``rule.should_fire``,
this use case materialises one alert for the rule's *owner only* (never a
watchlist fan-out — that is the key difference from ``AlertFanoutUseCase``):

  In one DB transaction:
    1. ``alerts`` row  (alert_type='user_rule', severity=rule.severity,
       payload={rule_type, rule_id, observed, condition_snapshot},
       dedup_key=sha256(rule_id:transition_signature))
    2. ``pending_alerts`` row for ``rule.user_id``
    3. ``outbox_events`` row (R8 — outbox, never a separate Kafka write)

  Then, *after commit*:
    4. WebSocket push over the existing Valkey channel (best-effort)
    5. advance ``rule.last_state`` (incl. ``last_fired_at``) — persisted only on
       commit, so a rolled-back transaction never advances the cooldown clock.

The ``dedup_key`` includes ``rule_id`` so two different rules observing the same
entity in the same window never collide (PRD §6.4). The transition signature is
the per-fire discriminator (rule type + observed value + a coarse time bucket)
so a genuine re-fire after cooldown gets a fresh key, while a same-cycle retry
(idempotent replay) collapses onto the existing alert.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from alert.domain.entities import Alert, OutboxEvent, PendingAlert
from alert.domain.enums import AlertType
from alert.domain.errors import DuplicateAlertError
from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from alert.application.ports.notification import INotificationPublisher
    from alert.application.ports.repositories import (
        AlertSaveRepositoryPort,
        IAlertRuleRepository,
        OutboxRepositoryPort,
        PendingAlertRepositoryPort,
    )
    from alert.domain.entities import AlertRule, EvalResult

    class RuleFireRepoFactory:
        """Builds the repos this use case needs from a single session."""

        def __call__(
            self,
            session: AsyncSession,
        ) -> tuple[
            AlertSaveRepositoryPort,
            PendingAlertRepositoryPort,
            OutboxRepositoryPort,
            IAlertRuleRepository,
        ]: ...


logger = get_logger(__name__)  # type: ignore[no-any-return]

# The alert_type for user-rule alerts (AlertType.USER_RULE == "user_rule",
# PLAN-0082 Wave B), distinct from SIGNAL / GRAPH_CHANGE / CONTRADICTION.
_USER_RULE_ALERT_TYPE = AlertType.USER_RULE.value


@dataclass
class FireResult:
    """Outcome of one :meth:`FireRuleAlertUseCase.execute` call."""

    fired: bool = False
    suppressed: bool = False
    suppression_reason: str = ""  # "dedup" | ""
    alert_id: UUID | None = None


def _observed_value(rule_type: str, result: EvalResult) -> Any:
    """Extract the single observed scalar for the alert payload + signature."""
    if result.value is not None:
        return result.value
    if result.delta_pct is not None:
        return result.delta_pct
    if result.count is not None:
        return result.count
    if result.connected is not None:
        return result.connected
    return None


def _transition_signature(rule: AlertRule, result: EvalResult, now: object) -> str:
    """A per-fire discriminator folded into the dedup key.

    Combines the rule type, the observed scalar, and a coarse 60-second time
    bucket. Two firings far apart in time (a re-fire after cooldown) produce
    distinct signatures → distinct alerts; an idempotent same-cycle retry
    collapses onto the same key (the dedup_key unique constraint rejects it).
    """
    observed = _observed_value(str(rule.rule_type), result)
    bucket = int(result.observed_at.timestamp()) // 60
    return f"{rule.rule_type}:{observed}:{bucket}"


class FireRuleAlertUseCase:
    """Fire one owner-targeted alert for a standing rule (PRD §6.5.5)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        notification_publisher: INotificationPublisher,
        repo_factory: RuleFireRepoFactory,
        alert_delivered_topic: str = "alert.delivered.v1",
    ) -> None:
        self._sf = session_factory
        self._notification_publisher = notification_publisher
        self._repo_factory = repo_factory
        self._alert_delivered_topic = alert_delivered_topic

    async def execute(self, rule: AlertRule, result: EvalResult) -> FireResult:
        """Persist + deliver one alert for ``rule``; advance ``last_state`` on commit.

        Mutates ``rule.last_state`` in place (to the post-fire state) **only after**
        a successful commit, so callers (poller/consumer) can persist the rule with
        the advanced ``last_fired_at`` knowing the alert is durable.
        """
        now = utc_now()
        signature = _transition_signature(rule, result, now)
        raw = f"{rule.rule_id}:{signature}"
        dedup_key = hashlib.sha256(raw.encode()).hexdigest()

        # The entity_id stamped on the alert row: the keyed entity for poll types,
        # node_a for KG rules (both nodes live in condition_snapshot anyway).
        entity_id = rule.entity_id or rule.node_a_entity_id or new_uuid7()

        observed = _observed_value(str(rule.rule_type), result)
        payload: dict[str, Any] = {
            "rule_type": str(rule.rule_type),
            "rule_id": str(rule.rule_id),
            "observed": observed,
            "observed_at": result.observed_at.isoformat(),
            "condition_snapshot": dict(rule.condition),
            # Carried for the UI alert title (mirrors AlertFanoutUseCase payload keys).
            "alert_type": _USER_RULE_ALERT_TYPE,
        }

        alert = Alert(
            entity_id=entity_id,
            alert_type=AlertType.USER_RULE,
            severity=rule.severity,
            source_event_id=new_uuid7(),
            source_topic=_USER_RULE_ALERT_TYPE,
            payload=payload,
            dedup_key=dedup_key,
            created_at=now,
            tenant_id=rule.tenant_id,
            title=rule.name,
        )

        async with self._sf() as session:
            alert_repo, pending_repo, outbox_repo, rule_repo = self._repo_factory(session)
            try:
                await alert_repo.save(alert)
            except DuplicateAlertError:
                # Idempotent replay (same rule + same transition window): another
                # cycle already wrote this alert. Rollback to clear the aborted
                # asyncpg connection (BP-137) and report suppression.
                await session.rollback()
                logger.info("fire_rule_alert.dedup", rule_id=str(rule.rule_id), dedup_key=dedup_key)
                return FireResult(suppressed=True, suppression_reason="dedup")

            await pending_repo.save(PendingAlert(user_id=rule.user_id, alert_id=alert.alert_id))

            payload_avro = _serialize_alert_delivered(alert, rule.user_id)
            await outbox_repo.append(
                OutboxEvent(
                    topic=self._alert_delivered_topic,
                    partition_key=str(rule.user_id),
                    payload_avro=payload_avro,
                ),
            )

            # Advance last_state INSIDE the txn so the rule row + the alert commit
            # atomically — last_fired_at can never advance without a durable alert.
            new_state = rule.next_state(result, now, fired=True)
            rule.last_state = new_state
            await rule_repo.update(rule)

            await session.commit()

        # ── Post-commit WebSocket push (never inside the transaction) ───────────
        ws_payload = {
            "alert_id": str(alert.alert_id),
            "entity_id": str(entity_id),
            "alert_type": _USER_RULE_ALERT_TYPE,
            "rule_type": str(rule.rule_type),
            "severity": str(rule.severity),
            "occurred_at": now.isoformat(),
        }
        try:
            await self._notification_publisher.send_to_user(rule.user_id, ws_payload)
        except Exception:
            logger.warning("fire_rule_alert.ws_push_error", rule_id=str(rule.rule_id), exc_info=True)

        logger.info(
            "fire_rule_alert.fired",
            rule_id=str(rule.rule_id),
            rule_type=str(rule.rule_type),
            user_id=str(rule.user_id),
            alert_id=str(alert.alert_id),
        )
        return FireResult(fired=True, alert_id=alert.alert_id)


# ── Avro serialisation (reuses the alert.delivered schema, as AlertFanoutUseCase) ──


def _serialize_alert_delivered(alert: Alert, user_id: UUID) -> bytes:
    """Serialize an ``alert.delivered`` event to Avro bytes (schemaless).

    Imported lazily from the fanout module's helper to avoid duplicating the
    schema-loading logic (BP-119: schema loaded from .avsc, never inline).
    """
    from alert.application.use_cases.alert_fanout import _serialize_alert_delivered as _ser

    return _ser(alert, user_id, None)
