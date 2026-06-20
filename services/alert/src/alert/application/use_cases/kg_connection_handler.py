"""KgConnectionEventHandler — the consumer-side driver for KG_CONNECTION rules (PLAN-0113 T-3-02).

The intelligence consumer already fans ``graph.state.changed.v1`` out to watchlist
watchers (AlertType.GRAPH_CHANGE). This handler is the ADDITIVE second branch: on
each graph event it evaluates standing KG_CONNECTION rules and fires owner-targeted
alerts when two pinned entities first become connected.

Flow per event:
  1. **Backfill suppression** (AD-10): a backfill replay must not retro-fire alerts
     for connections that "appeared" only because we re-ingested history. Skip.
  2. **Cheap pre-filter**: collect the event's affected entity ids
     (``affected_entity_ids`` + ``primary_entity_id``); only rules whose
     *node_a OR node_b* is in that set can plausibly have changed → evaluate those.
     (We do NOT require *both* nodes in the event — a single new edge touching one
     endpoint can complete a multi-hop path the rule cares about; S7 confirms the
     full path. This is the spec's "node_a and/or node_b" pre-filter.)
  3. **Confirm + fire**: run ``KgConnectionEvaluator.evaluate`` (S7 confirm,
     fail-closed) → ``should_fire`` latches the first ``connected=true`` → fire via
     the shared ``FireRuleAlertUseCase``. A no-fire still persists ``next_state``
     so the ``connected`` edge memory advances.

Idempotency: deduplication is twofold — the consumer's Valkey ``event_id`` dedup
skips re-delivered events, and ``FireRuleAlertUseCase``'s ``dedup_key`` (includes
``rule_id``) collapses any same-window double-fire. The KG latch (``connected``
flag in ``last_state``) is the durable guard that a rule fires exactly once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from alert.domain.enums import RuleType
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from alert.application.rules.registry import EvalContext, RuleEvaluator
    from alert.application.use_cases.fire_rule_alert import FireRuleAlertUseCase
    from alert.domain.entities import AlertRule

    # Builds the rule repository from a session (write path for state persistence).
    RuleRepoFactory = Callable[[AsyncSession], Any]
    # Returns the enabled KG_CONNECTION rules (read path).
    EnabledRulesLoader = Callable[[], Awaitable[list[AlertRule]]]

logger = get_logger(__name__)  # type: ignore[no-any-return]


class KgConnectionEventHandler:
    """Drives KG_CONNECTION rule evaluation off each graph-state event."""

    def __init__(
        self,
        evaluator: RuleEvaluator,
        eval_ctx: EvalContext,
        fire_use_case: FireRuleAlertUseCase,
        load_enabled_rules: EnabledRulesLoader,
        write_session_factory: async_sessionmaker[AsyncSession],
        rule_repo_factory: RuleRepoFactory,
    ) -> None:
        self._evaluator = evaluator
        self._ctx = eval_ctx
        self._fire = fire_use_case
        self._load_enabled_rules = load_enabled_rules
        self._sf = write_session_factory
        self._rule_repo_factory = rule_repo_factory

    async def handle(self, event: dict[str, Any]) -> int:
        """Evaluate KG rules for one graph event. Returns the number of rules fired.

        Never raises: a per-rule failure is logged + skipped (fail-soft) so the KG
        branch can never break the consumer's existing GRAPH_CHANGE fan-out path.
        """
        # ── 1. Backfill suppression (AD-10) ──────────────────────────────────
        if bool(event.get("is_backfill", False)):
            logger.debug("kg_connection_handler.backfill_suppressed", event_id=event.get("event_id"))
            return 0

        affected = self._affected_entities(event)
        if not affected:
            return 0

        # ── 2. Load enabled KG rules + cheap pre-filter ──────────────────────
        try:
            rules = await self._load_enabled_rules()
        except Exception:
            logger.warning("kg_connection_handler.load_rules_failed", exc_info=True)
            return 0

        candidates = [r for r in rules if self._touches(r, affected)]
        if not candidates:
            return 0

        # ── 3. Confirm + fire per candidate ──────────────────────────────────
        now = utc_now()
        fired = 0
        for rule in candidates:
            try:
                result = await self._evaluator.evaluate(rule, self._ctx)
                if result is None:
                    continue  # skip — no observation, leave state untouched
                if rule.should_fire(result, now):
                    fire_result = await self._fire.execute(rule, result)
                    if fire_result.fired:
                        fired += 1
                else:
                    # Persist advanced edge memory (e.g. connected recorded) even
                    # when not firing, so re-deliveries / future events diff
                    # against the latest state.
                    await self._persist_no_fire_state(rule, result, now)
            except Exception:
                # Fail-soft per rule: never let one rule sink the branch (and
                # certainly never the existing fan-out path).
                logger.error(
                    "kg_connection_handler.rule_failed",
                    rule_id=str(rule.rule_id),
                    exc_info=True,
                )
        if fired:
            logger.info("kg_connection_handler.fired", count=fired, event_id=event.get("event_id"))
        return fired

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _affected_entities(event: dict[str, Any]) -> set[UUID]:
        """Collect the event's affected entity ids (affected_entity_ids + primary)."""
        ids: set[UUID] = set()
        for raw in event.get("affected_entity_ids", []) or []:
            parsed = _uuid(raw)
            if parsed is not None:
                ids.add(parsed)
        primary = _uuid(event.get("primary_entity_id"))
        if primary is not None:
            ids.add(primary)
        return ids

    @staticmethod
    def _touches(rule: AlertRule, affected: set[UUID]) -> bool:
        """True if either of the rule's two nodes appears in the affected set."""
        return rule.node_a_entity_id in affected or rule.node_b_entity_id in affected

    async def _persist_no_fire_state(self, rule: AlertRule, result: Any, now: Any) -> None:
        """Advance ``last_state`` (connected memory) without firing, in its own txn."""
        rule.last_state = rule.next_state(result, now, fired=False)
        async with self._sf() as session:
            repo = self._rule_repo_factory(session)
            await repo.update(rule)
            await session.commit()


def _uuid(raw: object) -> UUID | None:
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


# The rule type this handler manages (re-exported for the consumer wiring).
KG_RULE_TYPE = RuleType.KG_CONNECTION
