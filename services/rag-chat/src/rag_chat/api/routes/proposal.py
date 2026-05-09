"""Proposal confirmation endpoint — POST /api/v1/chat/proposals/{proposal_id}/confirm.

PLAN-0082 Wave B — action tool confirmation flow.

WHY THIS ENDPOINT EXISTS:
When the LLM calls a write-action tool (e.g. ``create_alert``), the
ToolExecutor does NOT execute the action directly.  Instead it returns an
``action_pending`` RetrievedItem containing a ``proposal_id``.  The
ChatPipeline emits a ``pending_action`` SSE event with that ID AND the
full action parameters (entity_id, condition, threshold, severity).

The frontend shows a confirmation modal.  If the user confirms, the frontend
calls this endpoint, passing the proposal params from the SSE event in the
request body.  This endpoint calls S10 to execute the action and streams
SSE events back (action_executed or action_rejected).

WHY PARAMS IN REQUEST BODY (NOT VALKEY):
Storing proposals server-side in Valkey would require passing Valkey into
the ToolExecutor or the ChatPipeline — neither has Valkey access in the
current architecture.  Passing params back in the request body is equally
safe:
  - The proposal_id acts as a correlation token for logging / idempotency.
  - The params are non-secret (entity_id, condition, threshold, severity).
  - The action is still gated behind authentication — a malicious caller
    cannot execute write actions without a valid JWT.

WHY SSE RESPONSE (NOT JSON):
Mirrors the chat stream pattern for consistency.  Future multi-step
confirmations (e.g. create + notify) will naturally extend this as
additional SSE events.

R14: calls S10 via S9-proxied route (/v1/alerts), never S10 directly.
R25: route uses app.state adapters (no infra imports at module level).
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from rag_chat.api.dependencies import AuthContextDep
from rag_chat.application.pipeline.sse_emitter import SSEEmitter

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/api/v1", tags=["proposals"])

# ── In-memory idempotency guard (PLAN-0082 QA fix M-3) ────────────────────────
# WHY: the same proposal_id can be submitted multiple times (network retries,
# double-click) which would create duplicate alerts.  S10 has a 5-minute dedup
# window on (entity_id, alert_type) but NOT on (condition) — so two
# "price_below" alerts with different thresholds for the same entity would both
# be created.
#
# We store confirmed proposal IDs in a module-level set.  This is sufficient
# for the thesis single-instance deployment.  In a multi-replica setup, move
# this to Valkey (key: `s8:proposals:confirmed:{proposal_id}`, TTL 1h).
#
# Growth guard: evict the oldest half when the set exceeds _MAX_CONFIRMED_CACHE
# entries.  FIFO ordering is not required; any 500-entry eviction is safe here.
_CONFIRMED_PROPOSALS: set[str] = set()
_MAX_CONFIRMED_CACHE = 1000  # prevent unbounded growth in long-running instances


# ── Request schema ─────────────────────────────────────────────────────────────


class ConfirmProposalRequest(BaseModel):
    """Request body for ``POST /api/v1/chat/proposals/{proposal_id}/confirm``.

    The frontend sends this body after the user confirms the pending action
    in the ActionConfirmModal.  Fields mirror the ``params`` dict from the
    ``pending_action`` SSE event emitted during the chat stream.

    ``tool_name`` identifies which write-action tool to execute.  Currently
    only ``"create_alert"`` is supported, but the schema is forward-compatible
    for additional action types.
    """

    tool_name: str = Field(default="create_alert", description="Write-action tool to execute")
    entity_id: str = Field(description="Entity UUID to watch")
    condition: str = Field(
        description="Alert condition: price_below | price_above | volume_spike | percent_change",
        min_length=1,
        max_length=100,
    )
    threshold: dict = Field(  # type: ignore[type-arg]
        default_factory=dict,
        description="Condition threshold parameters, e.g. {'value': 200.0}",
    )
    severity: str = Field(default="low", description="low | medium | high | critical")


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("/chat/proposals/{proposal_id}/confirm")
async def confirm_proposal(
    proposal_id: str,
    body: ConfirmProposalRequest,
    request: Request,
    auth: AuthContextDep,
) -> EventSourceResponse:
    """Execute a pending write-action proposal after user confirmation.

    The frontend calls this endpoint when the user clicks "Confirm" in the
    ActionConfirmModal.  The proposal_id is a correlation token from the
    ``pending_action`` SSE event; it is logged for audit but NOT looked up
    server-side (the action params come from the request body — see module
    docstring for rationale).

    Flow:
      1. Validate auth context (tenant_id + user_id from JWT — PRD-0025).
      2. Execute the action (e.g. call S10 POST /v1/alerts).
      3. Stream SSE: ``action_executed`` on success, ``action_rejected`` on error.

    Returns 401 if the JWT is invalid (handled by InternalJWTMiddleware).
    Returns 422 if the request body fails Pydantic validation.
    """
    # PLAN-0082 QA fix M-3: idempotency guard — reject duplicate confirmations.
    # Check BEFORE acquiring the SSE stream so we can return a plain 409 JSON
    # response instead of streaming an error event (simpler for the frontend to
    # handle — no SSE reader needed for the error path).
    if proposal_id in _CONFIRMED_PROPOSALS:
        log.warning(  # type: ignore[no-any-return]
            "proposal_duplicate_confirmation",
            proposal_id=proposal_id,
        )
        raise HTTPException(status_code=409, detail="Proposal already confirmed")

    emitter = SSEEmitter()
    # auth is (tenant_id, user_id) from JWT — validated by AuthContextDep
    _tenant_id, _user_id = auth

    async def _stream() -> Any:  # type: ignore[misc]
        # ── Execute the confirmed action ───────────────────────────────────
        if body.tool_name != "create_alert":
            # Unknown action type — reject immediately.
            log.warning(  # type: ignore[no-any-return]
                "proposal_unknown_tool",
                proposal_id=proposal_id,
                tool_name=body.tool_name,
                user_id=str(_user_id),
            )
            yield emitter.emit_action_rejected(
                proposal_id=proposal_id,
                tool_name=body.tool_name,
                reason="unknown_tool",
            )
            return

        s10 = getattr(request.app.state, "s10_client", None)
        if s10 is None:
            log.warning("proposal_s10_unavailable", proposal_id=proposal_id)  # type: ignore[no-any-return]
            yield emitter.emit_action_rejected(
                proposal_id=proposal_id,
                tool_name=body.tool_name,
                reason="service_unavailable",
            )
            return

        # Retrieve the internal JWT for forwarding to S10 (PRD-0025 §T-D-1-10).
        # BaseUpstreamClient._post() injects it from auth_context automatically,
        # but we pass it explicitly as a fallback for the confirmation context.
        internal_jwt = getattr(request.state, "internal_jwt_raw", None)

        try:
            result = await s10.create_alert(
                entity_id=body.entity_id,
                condition=body.condition,
                threshold=dict(body.threshold),
                severity=body.severity,
                internal_jwt=internal_jwt,
            )
        except Exception as exc:
            log.warning(  # type: ignore[no-any-return]
                "proposal_execution_failed",
                proposal_id=proposal_id,
                tool_name=body.tool_name,
                error=str(exc),
            )
            yield emitter.emit_action_rejected(
                proposal_id=proposal_id,
                tool_name=body.tool_name,
                reason="execution_failed",
            )
            return

        if result is None:
            log.warning("proposal_execution_returned_none", proposal_id=proposal_id)  # type: ignore[no-any-return]
            yield emitter.emit_action_rejected(
                proposal_id=proposal_id,
                tool_name=body.tool_name,
                reason="execution_failed",
            )
            return

        # ── Emit action_executed ───────────────────────────────────────────
        log.info(  # type: ignore[no-any-return]
            "proposal_executed",
            proposal_id=proposal_id,
            tool_name=body.tool_name,
            alert_id=result.get("alert_id"),
            user_id=str(_user_id),
            tenant_id=str(_tenant_id),
        )

        # PLAN-0082 QA fix M-3: mark this proposal as confirmed so that any
        # subsequent duplicate submission returns 409 instead of creating a
        # second alert.  We record AFTER the S10 call succeeds — a failed
        # call does NOT consume the idempotency slot (the caller may retry).
        _CONFIRMED_PROPOSALS.add(proposal_id)
        if len(_CONFIRMED_PROPOSALS) > _MAX_CONFIRMED_CACHE:
            # Evict the oldest half to prevent unbounded growth.  List
            # iteration order is insertion order in CPython 3.7+ (set is
            # unordered, but we just need to evict ~half, not strict FIFO).
            _to_remove = list(_CONFIRMED_PROPOSALS)[: _MAX_CONFIRMED_CACHE // 2]
            for _k in _to_remove:
                _CONFIRMED_PROPOSALS.discard(_k)

        yield emitter.emit_action_executed(
            proposal_id=proposal_id,
            tool_name=body.tool_name,
            result={
                "alert_id": result.get("alert_id"),
                "entity_id": result.get("entity_id"),
                "condition": result.get("condition"),
                "severity": result.get("severity"),
                "created_at": result.get("created_at"),
            },
        )
        yield emitter.emit_done()

    return EventSourceResponse(_stream())
