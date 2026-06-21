"""Alert service REST and WebSocket routes.

Endpoints:
  POST   /api/v1/alerts                           — create a user-initiated alert rule (PLAN-0082 Wave B)
  GET    /api/v1/alerts/pending                   — list unacknowledged alerts for the authenticated user
  DELETE /api/v1/alerts/{alert_id}/ack            — acknowledge a per-user pending alert
  PATCH  /api/v1/alerts/{alert_id}/acknowledge    — tenant-level alert ack (PLAN-0051 T-D-4-02)
  PATCH  /api/v1/alerts/{alert_id}/snooze         — set snooze_until (PLAN-0051 T-D-4-02)
  GET    /api/v1/alerts/history                   — paginated tenant history (PLAN-0051 T-D-4-02)
  WS     /api/v1/alerts/stream                    — WebSocket real-time alert stream
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import jwt
from fastapi import APIRouter, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from alert.domain.enums import RuleType

from alert.api.dependencies import (
    AckAlertUseCaseDep,
    AckUseCaseDep,
    CreateAlertUseCaseDep,
    CreateRuleUseCaseDep,
    CurrentUserIdDep,
    DbSessionDep,
    DeleteRuleUseCaseDep,
    GetPendingAlertsUseCaseDep,
    GetRuleUseCaseDep,
    HistoryUseCaseDep,
    ListRulesUseCaseDep,
    ReadDbSessionDep,
    SnoozeUseCaseDep,
    TenantUserDep,
    UpdateRuleUseCaseDep,
)
from alert.api.schemas import (
    AcknowledgeAlertRequest,
    ActiveAlertFlagResponse,
    AlertCreatedResponse,
    AlertHistoryResponse,
    AlertResponse,
    AlertRuleCreateRequest,
    AlertRuleListResponse,
    AlertRuleResponse,
    AlertRuleUpdateRequest,
    CreateAlertRequest,
    PendingAlertResponse,
    PendingAlertsResponse,
    SnoozeAlertRequest,
)
from alert.application.use_cases.active_alert_flag import GetActiveAlertFlagUseCase
from alert.application.use_cases.create_alert import CreateAlertRequest as CreateAlertInput
from alert.domain.entities import Alert
from alert.domain.enums import AlertSeverity
from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/api/v1", tags=["alerts"])

# PLAN-0094 follow-up: a second router with the /internal/v1 prefix so the
# service-caller endpoint lives outside the public /api/v1 namespace. Both
# routers are included in app.py and share the same InternalJWTMiddleware.
internal_router = APIRouter(prefix="/internal/v1", tags=["alerts-internal"])


# ── REST: GET /internal/v1/instruments/{instrument_id}/active-alert-flag ──────
# PLAN-0089 Wave L-5a T-WL5A-02: per-entity active-alert summary for the
# screener S3-side sync worker (Wave L-5b). Aggregates across all users —
# "active" means any non-acked, non-snoozed alert row exists for the entity.


@internal_router.get(
    "/instruments/{instrument_id}/active-alert-flag",
    response_model=ActiveAlertFlagResponse,
)
async def get_active_alert_flag(
    instrument_id: UUID,
    session: ReadDbSessionDep,
) -> ActiveAlertFlagResponse:
    """Return whether any user has an active alert for ``instrument_id``."""
    flag = await GetActiveAlertFlagUseCase().execute(
        session=session,
        instrument_id=instrument_id,
    )
    return ActiveAlertFlagResponse(
        instrument_id=instrument_id,
        has_active_alert=flag.has_active_alert,
        active_alert_count=flag.active_alert_count,
    )


# ── REST: GET /api/v1/alerts/pending ─────────────────────────────────────────


@router.get("/alerts/pending", response_model=PendingAlertsResponse)
async def get_pending_alerts(
    request: Request,
    uc: GetPendingAlertsUseCaseDep,
    user_id: CurrentUserIdDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_severity: str | None = Query(default=None, description="Minimum severity: low|medium|high|critical"),
) -> PendingAlertsResponse:
    """Return paginated unacknowledged alerts for the authenticated user.

    ``user_id`` is extracted from the RS256 internal JWT set by InternalJWTMiddleware
    (PRD-0025 §T-D-1-10). The caller must not pass user_id as a query parameter.

    Optional ``min_severity`` filter returns only alerts at or above the
    given tier (e.g. ``?min_severity=high`` returns HIGH and CRITICAL only).
    """
    severity_filter: AlertSeverity | None = None
    if min_severity is not None:
        try:
            severity_filter = AlertSeverity(min_severity)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid min_severity: must be low|medium|high|critical",
            ) from None

    pairs = await uc.execute(user_id=user_id, limit=limit, offset=offset, min_severity=severity_filter)

    alert_responses = [
        PendingAlertResponse(
            pending_id=p.pending_id,
            alert_id=p.alert_id,
            entity_id=alert.entity_id,
            alert_type=str(alert.alert_type),
            source_topic=alert.source_topic,
            payload=alert.payload,
            created_at=p.created_at,
            severity=str(alert.severity),
            # PLAN-0049 T-D-4-04: pass enrichment columns through so the frontend
            # never has to fall back to "<SEVERITY> signal" labels (F-D-006).
            title=alert.title,
            ticker=alert.ticker,
            entity_name=alert.entity_name,
            signal_label=alert.signal_label,
        )
        for p, alert in pairs
    ]

    return PendingAlertsResponse(
        alerts=alert_responses,
        total=len(alert_responses),
        limit=limit,
        offset=offset,
    )


# ── REST: POST /api/v1/alerts ────────────────────────────────────────────────


@router.post("/alerts", response_model=AlertCreatedResponse, status_code=201)
async def create_alert(
    body: CreateAlertRequest,
    uc: CreateAlertUseCaseDep,
    session: DbSessionDep,
    tenant_user: TenantUserDep,
) -> AlertCreatedResponse:
    """Create a user-initiated alert rule (PLAN-0082 Wave B).

    Writes an Alert row + OutboxEvent in a single transaction (R8 outbox
    pattern).  The OutboxDispatcher publishes ``alert.created.v1`` to Kafka
    asynchronously so the response does not wait on Kafka availability.

    ``tenant_id`` and ``user_id`` are extracted from the RS256 internal JWT
    set by InternalJWTMiddleware (PRD-0025 §T-D-1-10).  Callers must never
    pass them in the request body — they are injected from the verified JWT.

    Returns 201 + AlertCreatedResponse on success.
    Returns 409 if a duplicate alert rule exists for the same entity + condition
    within the dedup window (5 minutes).
    """
    from alert.domain.errors import DuplicateAlertError

    tenant_id, user_id = tenant_user

    try:
        result = await uc.execute(
            CreateAlertInput(
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                entity_id=str(body.entity_id),
                condition=body.condition,
                threshold=dict(body.threshold),
                severity=body.severity,
                source="llm_tool",  # REST path — same source label as LLM tool path
            )
        )
    except DuplicateAlertError:
        raise HTTPException(
            status_code=409,
            detail="A duplicate alert rule for this entity and condition already exists",
        ) from None

    # Commit both the Alert row and OutboxEvent row atomically (R8). The use case
    # flushes but does not commit — commit ownership stays in the route layer so
    # the transaction boundary is explicit and visible to the caller.
    await session.commit()

    logger.info(  # type: ignore[no-any-return]
        "alert_rule_created_via_api",
        alert_id=result.alert_id,
        entity_id=result.entity_id,
        condition=result.condition,
        user_id=str(user_id),
        tenant_id=str(tenant_id),
    )
    return AlertCreatedResponse(
        alert_id=UUID(result.alert_id),
        entity_id=UUID(result.entity_id),
        condition=result.condition,
        threshold=result.threshold,
        severity=result.severity,
        created_at=result.created_at,
    )


# ── REST: DELETE /api/v1/alerts/{alert_id}/ack ───────────────────────────────


@router.delete("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: UUID,
    request: Request,
    uc: AckUseCaseDep,
    user_id: CurrentUserIdDep,
) -> dict[str, str]:
    """Acknowledge (mark delivered) an alert for the authenticated user.

    ``user_id`` is extracted from the RS256 internal JWT set by InternalJWTMiddleware
    (PRD-0025 §T-D-1-10).

    Returns 200 on success.  Returns 404 — not 403 — when the alert
    does not exist OR belongs to a different user (avoids user enumeration).

    The use case commits the DB session on success (N-04); the route must NOT
    call ``session.commit()``.
    """
    updated = await uc.execute(user_id, alert_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")

    logger.debug(  # type: ignore[no-any-return]
        "alert_acknowledged",
        alert_id=str(alert_id),
        user_id=str(user_id),
    )
    return {"status": "acknowledged"}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _alert_to_response(alert: Alert) -> AlertResponse:
    """Map a domain Alert to the wire AlertResponse schema.

    Centralised so ack/snooze/history routes all serialise consistently.
    """
    return AlertResponse(
        alert_id=alert.alert_id,
        entity_id=alert.entity_id,
        alert_type=str(alert.alert_type),
        source_topic=alert.source_topic,
        payload=alert.payload,
        created_at=alert.created_at,
        severity=str(alert.severity),
        tenant_id=alert.tenant_id,
        title=alert.title,
        ticker=alert.ticker,
        entity_name=alert.entity_name,
        signal_label=alert.signal_label,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by_user_id=alert.acknowledged_by_user_id,
        snooze_until=alert.snooze_until,
    )


# ── REST: PATCH /api/v1/alerts/{alert_id}/acknowledge (PLAN-0051 T-D-4-02) ───


@router.patch("/alerts/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert_entity(
    alert_id: UUID,
    uc: AckAlertUseCaseDep,
    tenant_user: TenantUserDep,
    body: AcknowledgeAlertRequest | None = None,
) -> AlertResponse:
    """Acknowledge an alert at the tenant level (sets ``acknowledged_at``).

    Idempotent: re-acking returns the existing acknowledged_at + user_id
    untouched (no overwrite). Returns 404 if the alert is missing or belongs
    to a different tenant (we collapse 403 → 404 to avoid alert-existence
    enumeration).
    """
    # body is currently informational; reserved for a future audit log table.
    _ = body
    tenant_id, user_id = tenant_user
    outcome, alert = await uc.execute(alert_id, user_id, tenant_id)

    if outcome == "not_found" or outcome == "forbidden":
        # Collapse 403 → 404: don't leak alert existence to other tenants.
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert is None:
        # Defensive — should be unreachable when outcome is "ok"/"already".
        raise HTTPException(status_code=500, detail="Alert vanished mid-request")

    logger.debug(  # type: ignore[no-any-return]
        "alert_entity_acknowledged",
        alert_id=str(alert_id),
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        outcome=outcome,
    )
    return _alert_to_response(alert)


# ── REST: PATCH /api/v1/alerts/{alert_id}/snooze (PLAN-0051 T-D-4-02) ────────


@router.patch("/alerts/{alert_id}/snooze", response_model=AlertResponse)
async def snooze_alert_entity(
    alert_id: UUID,
    body: SnoozeAlertRequest,
    uc: SnoozeUseCaseDep,
    tenant_user: TenantUserDep,
) -> AlertResponse:
    """Snooze an alert until a future timestamp (max 30 days out).

    Returns 422 when ``until`` is in the past, naive (no tz), or > 30 days
    out. Returns 404 when the alert is missing OR belongs to a different
    tenant (same enumeration-avoidance policy as acknowledge).
    """
    tenant_id, _user_id = tenant_user
    outcome, alert = await uc.execute(alert_id, body.until, tenant_id)

    if outcome == "invalid":
        raise HTTPException(
            status_code=422,
            detail="snooze_until must be timezone-aware, in the future, and <= 30 days out",
        )
    if outcome == "not_found" or outcome == "forbidden":
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert is None:
        raise HTTPException(status_code=500, detail="Alert vanished mid-request")

    logger.debug(  # type: ignore[no-any-return]
        "alert_entity_snoozed",
        alert_id=str(alert_id),
        snooze_until=body.until.isoformat(),
        tenant_id=str(tenant_id),
    )
    return _alert_to_response(alert)


# ── REST: GET /api/v1/alerts/history (PLAN-0051 T-D-4-02) ────────────────────


@router.get("/alerts/history", response_model=AlertHistoryResponse)
async def list_alert_history(
    uc: HistoryUseCaseDep,
    tenant_user: TenantUserDep,
    severity: str | None = Query(default=None, description="low|medium|high|critical"),
    entity_id: UUID | None = Query(default=None),
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    status: str = Query(default="all", description="active|acknowledged|snoozed|all"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AlertHistoryResponse:
    """Return paginated, tenant-scoped alert history.

    Read-only — uses ``ReadOnlyUnitOfWork`` (R27) via the read replica.
    Tenant filtering is enforced by the use case using the JWT-derived
    ``tenant_id`` (never a header — F-CRIT-001 / PRD-0025).
    """
    tenant_id, _user_id = tenant_user

    # Validate severity enum; keep a helpful 422 instead of silently filtering
    # out everything when the caller mistypes a tier.
    severity_filter: AlertSeverity | None = None
    if severity is not None:
        try:
            severity_filter = AlertSeverity(severity)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid severity: must be low|medium|high|critical",
            ) from None

    # Validate status enum the same way (forward-compat: use case will fall
    # back to "all" but we surface a 422 here to give callers explicit feedback).
    if status not in ("active", "acknowledged", "snoozed", "all"):
        raise HTTPException(
            status_code=422,
            detail="Invalid status: must be active|acknowledged|snoozed|all",
        )

    alerts, total = await uc.execute(
        tenant_id,
        status=status,
        severity=severity_filter,
        entity_id=entity_id,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
        offset=offset,
    )

    # WHY total is the universe (not page size): QA-iter1 C-3 — the frontend
    # computes ``hasMore = rows.length < total`` to decide whether to render
    # "Load more". With page-size semantics that condition is always False
    # and pagination was unreachable. ``has_more`` is now derived consistently
    # from offset + page rows vs the universe size.
    return AlertHistoryResponse(
        alerts=[_alert_to_response(a) for a in alerts],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(alerts) < total,
    )


# ── Alert Rules CRUD (PLAN-0113) ─────────────────────────────────────────────
#
# Routes call only use cases (R25). The discriminated ``condition`` is validated
# here at the boundary so we can return a precise 400/422; keying fields
# (entity_id / node_a / node_b) are derived from the validated condition.


def _rule_to_response(rule: object) -> AlertRuleResponse:
    """Map a domain AlertRule to the wire schema."""
    from alert.domain.entities import AlertRule

    assert isinstance(rule, AlertRule)
    return AlertRuleResponse(
        rule_id=rule.rule_id,
        tenant_id=rule.tenant_id,
        user_id=rule.user_id,
        rule_type=str(rule.rule_type),
        name=rule.name,
        entity_id=rule.entity_id,
        node_a_entity_id=rule.node_a_entity_id,
        node_b_entity_id=rule.node_b_entity_id,
        condition=rule.condition,
        severity=str(rule.severity),
        enabled=rule.enabled,
        cooldown_seconds=rule.cooldown_seconds,
        notify_in_app=rule.notify_in_app,
        notify_email=rule.notify_email,
        last_state=rule.last_state,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _parse_rule_type(raw: str) -> RuleType:
    from alert.domain.enums import RuleType

    try:
        return RuleType(raw)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="rule_type must be one of PRICE_CROSS|NEWS_COUNT|NEWS_MOMENTUM|KG_CONNECTION|FUNDAMENTAL_CROSS",
        ) from None


def _validate_condition_and_keys(rule_type_raw: str, condition_raw: dict) -> tuple[RuleType, dict, dict]:  # type: ignore[type-arg]
    """Validate the discriminated condition; derive keying fields.

    Returns ``(rule_type, validated_condition_dict, keying_kwargs)`` where
    keying_kwargs is one of ``{entity_id=...}`` or
    ``{node_a_entity_id=..., node_b_entity_id=...}``. Raises HTTPException 400
    on a bad shape, 422 on the node_a==node_b semantic violation.
    """
    from pydantic import ValidationError

    from alert.domain.enums import RuleType
    from alert.domain.rule_conditions import parse_condition

    rule_type = _parse_rule_type(rule_type_raw)
    try:
        condition = parse_condition(rule_type, condition_raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid condition: {exc.errors()}") from None

    cond_dict = condition.model_dump(mode="json")
    if rule_type is RuleType.KG_CONNECTION:
        if cond_dict["source_entity_id"] == cond_dict["target_entity_id"]:
            raise HTTPException(status_code=422, detail="source_entity_id must differ from target_entity_id")
        keys = {
            "node_a_entity_id": UUID(cond_dict["source_entity_id"]),
            "node_b_entity_id": UUID(cond_dict["target_entity_id"]),
        }
    else:
        key_field = "instrument_id" if "instrument_id" in cond_dict else "entity_id"
        keys = {"entity_id": UUID(cond_dict[key_field])}
    return rule_type, cond_dict, keys


async def _validate_metric_key(request: Request, rule_type: RuleType, cond_dict: dict) -> None:  # type: ignore[type-arg]
    """Allow-list ``FUNDAMENTAL_CROSS.metric_key`` against the S3 vocabulary.

    PRD-0113 §6.5.3/§9: the only semantic check that cannot live in the domain
    condition model (it needs the live S3 ``screen/fields`` catalogue). Without
    it, a typo'd ``metric_key`` is accepted and the rule then silently never
    fires (the evaluator's ``get_fundamental_metric`` returns None for an unknown
    metric) — exactly the silent-drop class this PRD set out to kill.

    Fail policy: reject (400) only when the catalogue is reachable AND the metric
    is definitively absent. If S3 is unreachable (vocab is ``None``), we
    fail-open (allow + log) so a transient S3 outage cannot block rule creation.
    """
    from alert.domain.enums import RuleType
    from alert.infrastructure.clients.s3_client import S3MarketDataClient

    if rule_type is not RuleType.FUNDAMENTAL_CROSS:
        return
    metric_key = cond_dict.get("metric_key")
    if not isinstance(metric_key, str):
        return  # shape already validated by the Pydantic condition model.

    s3_client = S3MarketDataClient(request.app.state.settings)
    try:
        vocab = await s3_client.get_fundamental_metric_keys()
    finally:
        await s3_client.close()

    if vocab is None:
        # Catalogue unreachable — allow but record the unverified creation.
        logger.warning("metric_key_unverified_s3_unreachable", metric_key=metric_key)  # type: ignore[no-any-return]
        return
    if metric_key not in vocab:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown metric_key '{metric_key}'. Must be one of the S3 fundamentals fields.",
        )


@router.post("/alert-rules", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(
    body: AlertRuleCreateRequest,
    uc: CreateRuleUseCaseDep,
    tenant_user: TenantUserDep,
    request: Request,
) -> AlertRuleResponse:
    """Create a standing alert rule (PLAN-0113).

    Validates the discriminated ``condition`` at the boundary, derives keying
    fields, and persists owner-scoped. Returns 400 (bad condition), 409
    (duplicate identical rule), 422 (node_a==node_b), 429 (per-user cap).
    """
    from alert.application.use_cases.manage_rules import CreateRuleInput
    from alert.domain.enums import AlertSeverity
    from alert.domain.errors import RuleLimitExceededError

    tenant_id, user_id = tenant_user
    rule_type, cond_dict, keys = _validate_condition_and_keys(body.rule_type, body.condition)
    # Semantic allow-list for FUNDAMENTAL_CROSS metric_key (S3 vocabulary).
    await _validate_metric_key(request, rule_type, cond_dict)

    try:
        severity = AlertSeverity(body.severity)
    except ValueError:
        raise HTTPException(status_code=400, detail="severity must be low|medium|high|critical") from None

    name = body.name or f"{rule_type.value} rule"
    try:
        rule = await uc.execute(
            CreateRuleInput(
                tenant_id=tenant_id,
                user_id=user_id,
                rule_type=rule_type,
                name=name,
                condition=cond_dict,
                severity=severity,
                enabled=body.enabled,
                cooldown_seconds=body.cooldown_seconds,
                notify_in_app=body.notify_in_app,
                notify_email=body.notify_email,
                **keys,
            )
        )
    except RuleLimitExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None

    logger.info("alert_rule_created", rule_id=str(rule.rule_id), rule_type=rule_type.value)  # type: ignore[no-any-return]
    return _rule_to_response(rule)


@router.get("/alert-rules", response_model=AlertRuleListResponse)
async def list_alert_rules(
    uc: ListRulesUseCaseDep,
    tenant_user: TenantUserDep,
    enabled: bool | None = Query(default=None),
    rule_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AlertRuleListResponse:
    """List the caller's alert rules (read replica, R27)."""
    tenant_id, user_id = tenant_user
    rt = _parse_rule_type(rule_type) if rule_type is not None else None
    rules, total = await uc.execute(tenant_id, user_id, enabled=enabled, rule_type=rt, limit=limit, offset=offset)
    return AlertRuleListResponse(items=[_rule_to_response(r) for r in rules], total=total)


@router.get("/alert-rules/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(
    rule_id: UUID,
    uc: GetRuleUseCaseDep,
    tenant_user: TenantUserDep,
) -> AlertRuleResponse:
    """Get a single owned rule (404 if missing or cross-owner)."""
    from alert.domain.errors import RuleNotFoundError

    tenant_id, user_id = tenant_user
    try:
        rule = await uc.execute(rule_id, tenant_id, user_id)
    except RuleNotFoundError:
        raise HTTPException(status_code=404, detail="Rule not found") from None
    return _rule_to_response(rule)


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    rule_id: UUID,
    body: AlertRuleUpdateRequest,
    get_uc: GetRuleUseCaseDep,
    uc: UpdateRuleUseCaseDep,
    tenant_user: TenantUserDep,
    request: Request,
) -> AlertRuleResponse:
    """Partial-update an owned rule. Changing ``condition`` re-arms (last_state=null).

    ``rule_type`` is immutable; a ``condition`` change is validated against the
    rule's existing type.
    """
    from alert.application.use_cases.manage_rules import UpdateRuleInput
    from alert.domain.enums import AlertSeverity
    from alert.domain.errors import RuleNotFoundError

    tenant_id, user_id = tenant_user

    severity: AlertSeverity | None = None
    if body.severity is not None:
        try:
            severity = AlertSeverity(body.severity)
        except ValueError:
            raise HTTPException(status_code=400, detail="severity must be low|medium|high|critical") from None

    patch = UpdateRuleInput(
        name=body.name,
        severity=severity,
        enabled=body.enabled,
        cooldown_seconds=body.cooldown_seconds,
        notify_in_app=body.notify_in_app,
        notify_email=body.notify_email,
    )

    if body.condition is not None:
        # Resolve the rule's immutable type, then validate the new condition.
        try:
            existing = await get_uc.execute(rule_id, tenant_id, user_id)
        except RuleNotFoundError:
            raise HTTPException(status_code=404, detail="Rule not found") from None
        rt, cond_dict, keys = _validate_condition_and_keys(str(existing.rule_type), body.condition)
        # Re-validate metric_key when the condition changes (same allow-list as create).
        await _validate_metric_key(request, rt, cond_dict)
        patch.condition = cond_dict
        patch.entity_id = keys.get("entity_id")
        patch.node_a_entity_id = keys.get("node_a_entity_id")
        patch.node_b_entity_id = keys.get("node_b_entity_id")

    try:
        rule = await uc.execute(rule_id, tenant_id, user_id, patch)
    except RuleNotFoundError:
        raise HTTPException(status_code=404, detail="Rule not found") from None
    return _rule_to_response(rule)


@router.delete("/alert-rules/{rule_id}", status_code=204)
async def delete_alert_rule(
    rule_id: UUID,
    uc: DeleteRuleUseCaseDep,
    tenant_user: TenantUserDep,
) -> Response:
    """Delete an owned rule (204; 404 if missing or cross-owner)."""
    from alert.domain.errors import RuleNotFoundError

    tenant_id, user_id = tenant_user
    try:
        await uc.execute(rule_id, tenant_id, user_id)
    except RuleNotFoundError:
        raise HTTPException(status_code=404, detail="Rule not found") from None
    return Response(status_code=204)


# ── WebSocket: /api/v1/alerts/stream ─────────────────────────────────────────


@router.websocket("/alerts/stream")
async def alerts_stream(
    websocket: WebSocket,
) -> None:
    """WebSocket endpoint — pushes real-time alerts to a connected user.

    ``user_id`` is extracted from ``websocket.state.user_id`` set by
    InternalJWTMiddleware on the HTTP upgrade request (PRD-0025 §T-D-1-10).
    The JWT must be passed via the ``X-Internal-JWT`` header on the upgrade
    request (S9 injects this after validating the client token).

    Architecture (cross-process fan-out):
    - The standalone ``intelligence_consumer_main`` process publishes alerts to
      Valkey channel ``alert:{user_id}`` via ``ValkeyNotificationPublisher``.
    - This handler subscribes to that channel and forwards each message to the
      connected WebSocket client.
    - The in-process ``ConnectionManager`` is retained for direct pushes from
      within the API process (e.g., integration tests, future in-process paths).

    Delivery is best-effort: if no client is connected when a message arrives,
    the message is dropped.  On reconnect, clients catch up via GET /alerts/pending.
    """
    # WHY inline JWT validation: BaseHTTPMiddleware skips dispatch() for WebSocket
    # ASGI scopes (scope["type"] != "http"), so InternalJWTMiddleware never runs
    # for WS connections. websocket.state.user_id is therefore never populated.
    # We validate the ws-token directly here instead.
    #
    # P0-1 (PLAN-0088): The api-gateway issues this token via ``issue_ws_jwt`` with
    # ``aud=worldview-internal`` and ``scope=alerts:stream``. PyJWT >= 2.0 raises
    # ``InvalidAudienceError`` whenever a token contains an ``aud`` claim and the
    # ``jwt.decode`` call does NOT pass ``audience=`` — that bug was making every
    # WebSocket upgrade close with 4001/403. We now mirror the canonical decode
    # parameters from ``InternalJWTMiddleware.dispatch`` exactly: same issuer,
    # same audience, same algorithm. We additionally enforce the ``alerts:stream``
    # scope so a token issued for a different purpose cannot subscribe to the
    # alert WebSocket.
    token = websocket.query_params.get("token")
    if not token:
        # 4401 = unauthorized application close code (see RFC 6455 §7.4.2 +
        # IANA WebSocket Close Code registry). Distinct from 4001 so that
        # operators / tests can tell "no token" apart from "service down (1011)".
        await websocket.close(code=4401, reason="missing token")
        return

    public_key = getattr(websocket.app.state, "_internal_jwt_public_key", None)
    skip_verification = getattr(websocket.app.state, "_internal_jwt_skip_verification", False)

    if public_key is None and not skip_verification:
        # Fail-closed: JWKS not yet loaded (only possible during startup race).
        await websocket.close(code=1011, reason="jwks not loaded")
        return

    try:
        if skip_verification:
            # Test/dev mode only — InternalJWTMiddleware was configured with
            # skip_verification=True (no JWKS endpoint available).
            payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256", "RS256"])
        else:
            # public_key is fetched from the JWKS cache as Any | None; in this
            # branch we already verified it is not None, but mypy can't narrow
            # ``Any | None`` to the cryptography union type pyjwt expects.
            payload = jwt.decode(
                token,
                public_key,  # type: ignore[arg-type]
                algorithms=["RS256"],
                issuer="worldview-gateway",
                # P0-1: audience=worldview-internal must match the ``aud`` claim
                # set by ``issue_ws_jwt`` in api-gateway/jwt_utils.py. Without
                # this, PyJWT raises InvalidAudienceError → close(4401).
                audience="worldview-internal",
                options={"require": ["sub", "exp", "iss", "aud"]},
            )
        user_id = UUID(payload["sub"])

        # P0-1: enforce the OAuth2-style ``scope`` claim. ws-tokens are issued with
        # exactly ``scope="alerts:stream"``; reject anything else so a token minted
        # for an unrelated purpose can't subscribe to the alert stream.
        # We accept either the OAuth2 ``scope`` (space-delimited string) or the
        # less-common ``scopes`` (list) shape so we stay compatible with future
        # token formats.
        raw_scope = payload.get("scope")
        scope_list: list[str]
        if isinstance(raw_scope, str):
            scope_list = raw_scope.split()
        elif isinstance(raw_scope, list):
            scope_list = [str(s) for s in raw_scope]
        else:
            # Skip-verification path historically uses tokens with no scope claim;
            # we keep the dev/test path permissive there to avoid breaking unit
            # tests. In production (skip_verification=False) the token always
            # has scope=alerts:stream because issue_ws_jwt sets it unconditionally.
            scope_list = []
        if not skip_verification and "alerts:stream" not in scope_list:
            logger.warning(  # type: ignore[no-any-return]
                "ws_scope_missing",
                user_id=str(user_id),
                scopes=scope_list,
            )
            await websocket.close(code=4401, reason="missing scope")
            return
    except jwt.InvalidAudienceError:
        # Surface this as its own log so the P0-1 regression is visible if
        # the token issuer ever changes audience again.
        logger.warning("ws_invalid_audience", token_prefix=token[:12])  # type: ignore[no-any-return]
        await websocket.close(code=4401, reason="invalid audience")
        return
    except jwt.ExpiredSignatureError:
        logger.debug("ws_token_expired", token_prefix=token[:12])  # type: ignore[no-any-return]
        await websocket.close(code=4401, reason="token expired")
        return
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        logger.debug("ws_token_invalid", error=str(exc))  # type: ignore[no-any-return]
        await websocket.close(code=4401, reason="invalid token")
        return

    manager = websocket.app.state.ws_manager
    valkey = websocket.app.state.valkey
    channel = f"alert:{user_id}"

    await manager.connect(user_id, websocket)
    try:
        async with valkey.subscribe(channel) as pubsub:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                if message is None:
                    # 30 s elapsed with no alert — send a ping to detect stale connections.
                    # If the client has disconnected, send_text raises and we exit cleanly.
                    try:
                        await websocket.send_text('{"type":"ping"}')
                    except (WebSocketDisconnect, Exception):
                        break
                elif message.get("type") == "message":
                    try:
                        await websocket.send_text(message["data"])
                    except WebSocketDisconnect:
                        break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning(  # type: ignore[no-any-return]
            "websocket_subscribe_failed",
            user_id=str(user_id),
            exc_info=True,
        )
        # Inform the client before closing; suppress errors if already disconnected.
        try:
            await websocket.send_json({"error": "service_unavailable", "code": 1011})
            await websocket.close(code=1011)
        except Exception:  # noqa: S110
            pass
    finally:
        manager.disconnect(user_id)
