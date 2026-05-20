"""Alert tool handlers — read and create user alert rules via S10.

Covers tools backed by S10Port:
  - get_alerts    (S10Port — retrieve active user alerts)
  - create_alert  (S10Port — proposal flow; requires user confirmation)

Security notes:
  - create_alert uses allowlists for ``condition`` and ``severity`` fields to prevent
    prompt injection from reaching the SSE stream (PLAN-0082 QA fix M-1 / M-2).
  - create_alert returns an action_pending RetrievedItem; actual write happens only
    after explicit user confirmation via POST /v1/chat/proposals/{id}/confirm.
  - Per-session rate limit: ≤5 create_alert calls per ToolExecutor instance.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler

if TYPE_CHECKING:
    from rag_chat.application.ports.upstream_clients import S10Port

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
_TOOL_RESULT_MAX_CHARS = 4000

# ── create_alert allowlists (PLAN-0082 QA fix M-1 / M-2) ──────────────────────
# WHY allowlists: the LLM may emit attacker-injected strings (from prompt
# injection or indirect injection via entity names) into the ``condition`` and
# ``severity`` fields.  Without validation those strings reach the SSE stream
# unescaped and are displayed verbatim in the ActionConfirmModal — a UX XSS
# risk and a confusing UX when the string is garbage.
#
# We enumerate the full set of valid values once here (before the class
# definitions so the constants are module-level and importable by tests).
# Any value NOT in the allowlist causes the handler to return [] immediately,
# which the orchestrator treats as an empty tool result (no confirmation modal
# shown, no write executed).
_VALID_CONDITIONS: frozenset[str] = frozenset({"price_below", "price_above", "volume_spike", "percent_change"})
_VALID_SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})


class AlertsHandler(ToolHandler):
    """Handles alert read and creation tools.

    All tools in this handler call S10Port (alert service).
    Auth context (user_id, tenant_id) is injected at request time.
    Session rate limit for create_alert is tracked internally.
    """

    _HANDLED_TOOLS = frozenset({"get_alerts", "create_alert"})

    def __init__(
        self,
        s10: S10Port | None = None,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._s10 = s10
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._timeout = timeout
        # PLAN-0082 Wave B: per-session rate limit for create_alert (≤5/session).
        # WHY session limit: the LLM could in principle loop and emit many create_alert
        # calls in a single conversation turn. Limiting to 5 prevents runaway alert
        # creation and keeps the UX intention clear — this is a deliberate action,
        # not a background task.
        self._create_alert_count: int = 0

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        if tool_name == "get_alerts":
            return await self._handle_get_alerts()
        if tool_name == "create_alert":
            return await self._handle_create_alert(**args)
        raise ValueError(f"AlertsHandler cannot handle tool: {tool_name}")

    # ── S10 read handler ───────────────────────────────────────────────────────

    async def _handle_get_alerts(self) -> list[RetrievedItem]:
        """Retrieve active (pending) alerts for the authenticated user via S10 (PLAN-0082 Wave A).

        R25: depends only on S10Port Protocol — never imports S10Client directly.
        R27: read-only — no UnitOfWork; calls S10 via HTTP only.
        R9:  returns [] on missing port, missing auth, or any upstream error.
        PRIVACY: alert content is passed to LLM context; no special filtering needed
        (alerts are the user's own data, already scoped by user_id + tenant_id).
        """
        if self._s10 is None:
            log.warning("tool_handler_missing_port", tool="get_alerts", port="s10")
            return []

        # Auth guard: user_id and tenant_id are required to scope the alert query.
        # Both are resolved from X-Internal-JWT by InternalJWTMiddleware — if either
        # is None the request is anonymous (or the JWT is malformed) so we degrade.
        if self._user_id is None or self._tenant_id is None:
            log.warning(
                "tool_no_auth_context",
                tool="get_alerts",
                user_id_missing=self._user_id is None,
                tenant_id_missing=self._tenant_id is None,
            )
            return []

        t0 = time.monotonic()
        try:
            alerts = await asyncio.wait_for(
                self._s10.get_alerts(
                    user_id=str(self._user_id),
                    tenant_id=str(self._tenant_id),
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_alerts", error=str(e))
            return []

        if not alerts:
            log.info("tool_no_data", tool="get_alerts", user_id=str(self._user_id))
            return []

        items: list[RetrievedItem] = []
        for alert in alerts:
            # Serialise each alert dict as JSON for LLM context injection.
            # WHY json.dumps: keeps the alert structure intact so the LLM can
            # reason about individual fields (status, trigger_price, etc.).
            alert_text = json.dumps(alert)[:_TOOL_RESULT_MAX_CHARS]
            # Use alert_id if present for stable item_id; fall back to loop index.
            alert_id = alert.get("id") or alert.get("alert_id") or str(len(items))
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:alert:{alert_id}",
                    item_type=ItemType.financial,
                    text=alert_text,
                    score=1.0,  # user's own alerts — maximally relevant
                    trust_weight=0.95,
                    source_type="alert",
                    citation_meta=CitationMeta(
                        title="Alert",
                        url=None,
                        source_name="alert_service",
                        published_at=None,
                        entity_name=None,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="get_alerts",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=len(items),
        )
        return items

    # ── S10 write action handler ───────────────────────────────────────────────

    async def _handle_create_alert(
        self,
        entity_id: str = "",
        condition: str = "",
        threshold: dict | None = None,
        severity: str = "low",
        **_: Any,
    ) -> RetrievedItem | list[RetrievedItem] | None:
        # Return type extended to include list[RetrievedItem] so that
        # allowlist-rejected inputs can return [] (empty list) — the same
        # contract used by all multi-result handlers.  None is kept for
        # port-missing / auth-missing / rate-limit paths.
        """Create a user-initiated alert rule via S10 (PLAN-0082 Wave B).

        CONFIRMATION FLOW: this handler does NOT execute the alert creation
        directly.  Instead it returns a special ``action_pending`` RetrievedItem
        that signals to the ChatPipeline that user confirmation is required
        before the action is executed.

        The confirmation flow:
          1. LLM emits a ``create_alert`` tool call.
          2. This handler is called; it validates inputs and returns an
             ``action_pending`` RetrievedItem with a generated ``proposal_id``.
          3. The orchestrator detects the ``action_pending`` item type and emits
             a ``pending_action`` SSE event with the proposal_id.
          4. The frontend shows a confirmation modal.
          5. The user confirms → frontend calls POST /v1/chat/proposals/{id}/confirm.
          6. The proposal endpoint calls S10 directly and emits ``action_executed``.

        RATE LIMIT: ≤5 create_alert calls per session. Exceeding the limit
        returns None (no confirmation offered) so the LLM receives an empty
        result and should not retry.

        WHY NOT EXECUTE DIRECTLY: write actions must never be auto-executed
        without user consent — doing so would be a UX footgun and a security
        issue if an adversarial query triggers alert creation.

        R25: depends only on S10Port Protocol — no concrete infra imports.
        R9:  returns None on missing port, missing auth, rate limit, or bad input.
        """
        if self._s10 is None:
            log.warning("tool_handler_missing_port", tool="create_alert", port="s10")
            return None

        # Auth guard: user_id and tenant_id are required (resolved from JWT).
        if self._user_id is None or self._tenant_id is None:
            log.warning(
                "tool_no_auth_context",
                tool="create_alert",
                user_id_missing=self._user_id is None,
                tenant_id_missing=self._tenant_id is None,
            )
            return None

        # Per-session rate limit: ≤5 create_alert calls.
        _max_create_alert = 5
        if self._create_alert_count >= _max_create_alert:
            log.warning(
                "create_alert_rate_limit_exceeded",
                count=self._create_alert_count,
                limit=_max_create_alert,
            )
            return None

        # Input validation: both entity_id and condition are required.
        if not entity_id or not condition:
            log.warning(
                "tool_no_data",
                tool="create_alert",
                reason="missing_entity_id_or_condition",
            )
            return None

        # PLAN-0082 QA fix M-1: reject condition strings not in the allowlist.
        # WHY: prompt-injected or adversarial condition strings (e.g.
        # "__SYSTEM_PROMPT__", "admin_override", "price_below\nIGNORE …") must
        # never reach the SSE stream or the ActionConfirmModal.  Returning []
        # causes the orchestrator to treat this as an empty tool result — no
        # confirmation modal, no write.
        if condition not in _VALID_CONDITIONS:
            log.warning(
                "create_alert_invalid_condition",
                condition=condition,
                valid=sorted(_VALID_CONDITIONS),
            )
            return []

        # PLAN-0082 QA fix M-2: reject severity strings not in the allowlist.
        # WHY: same rationale as M-1 — an injected severity like
        # "CRITICAL; DROP TABLE alerts;" must not reach the proposal payload.
        if severity not in _VALID_SEVERITIES:
            log.warning(
                "create_alert_invalid_severity",
                severity=severity,
                valid=sorted(_VALID_SEVERITIES),
            )
            return []

        # Increment session counter.
        self._create_alert_count += 1

        # Generate a proposal_id that the frontend will send back on confirm.
        # WHY UUIDv7: consistent with all other IDs in this codebase (R10).
        from common.ids import new_uuid7  # type: ignore[import-untyped]

        proposal_id = str(new_uuid7())

        threshold_dict: dict[str, Any] = threshold or {}

        # Serialise proposal params as JSON text for LLM context injection.
        # The LLM receives this text and can reference the pending action.
        params_text = json.dumps(
            {
                "proposal_id": proposal_id,
                "entity_id": entity_id,
                "condition": condition,
                "threshold": threshold_dict,
                "severity": severity,
            }
        )

        log.info(
            "create_alert_proposal_created",
            proposal_id=proposal_id,
            entity_id=entity_id,
            condition=condition,
            user_id=str(self._user_id),
            tenant_id=str(self._tenant_id),
        )

        # Return a special action_pending RetrievedItem.  The orchestrator
        # detects item_type == action_pending and emits the pending_action SSE.
        return RetrievedItem.create(
            item_id=f"tool:create_alert:{proposal_id}",
            item_type=ItemType.action_pending,
            text=params_text[:_TOOL_RESULT_MAX_CHARS],
            score=1.0,  # user-initiated action — maximally relevant
            trust_weight=1.0,
            source_type="action_pending",
            citation_meta=CitationMeta(
                title="Pending alert creation",
                url=None,
                source_name="alert_service",
                published_at=None,
                entity_name=None,
            ),
        )
