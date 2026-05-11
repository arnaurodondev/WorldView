# PLAN-0082 — Action Tools (Alerts) + Prompt-Injection Safety Hardening

> **PRD**: derived from `/investigate` 2026-05-07 — issues A-4, I-7
> **Status**: completed (Wave A done 2026-05-09; Wave B done 2026-05-09; Wave C done 2026-05-09)
> **Created**: 2026-05-07
> **Last revised**: 2026-05-09 (Wave C: 30 adversarial prompt-injection tests for create_alert — all 30 pass, ruff + mypy clean)
> **Owner**: TBD
> **Estimated effort**: ~2.5 dev-days (3 waves, ~12 tasks)
> **Hard dependencies**:
>   - PLAN-0067 W11-4 **MUST BE COMPLETE** — provides adversarial-eval baseline (10 attempts, I-7). `create_alert` ships ONLY after W11-4 adversarial baseline is at 100% safe-refusal.
>   - PLAN-0081 **MUST BE COMPLETE** — establishes manifest v3 that this plan extends to v4.
>   - PLAN-0080 **MUST BE COMPLETE** — establishes manifest v2 conventions.
> **Blocks**: none

---

## §0 Why this plan exists

PLAN-0067 ships read-only retrieval tools. Bloomberg-grade users will eventually want write actions through the LLM ("set an alert when AAPL drops below 200"). Read tools have a small blast radius if abused; **write tools do not**. Before exposing any action tool, we need:

1. A demonstrated baseline for prompt-injection resistance (PLAN-0067 W11-4 adversarial-eval, 10 attempts).
2. Per-tool authorization checks at the executor layer, not just at the upstream service.
3. A confirmation surface in the UI ("LLM wants to create this alert — approve?") for any tool with side-effects.

This plan adds 2 tools — `get_alerts` (read), `create_alert` (write) — and the safety scaffolding around `create_alert`.

---

## §1 BP-405 Name Verification

The following names were mechanically verified via `grep` against the current codebase on 2026-05-07.
Items tagged **NEW** do not exist yet and will be created by the indicated plan/wave.

| Name | Type | Exists now? | Source |
|------|------|-------------|--------|
| `get_alerts` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `create_alert` | tool name (manifest + handler) | NO — NEW (this plan Wave B) | — |
| `pending_action` | SSE event type | NO — NEW (this plan Wave B); must be added to `SSEEmitter` | — |
| `action_executed` | SSE event type | NO — NEW (this plan Wave B); must be added to `SSEEmitter` | — |
| `action_rejected` | SSE event type | NO — NEW (this plan Wave B); must be added to `SSEEmitter` | — |
| `SSEEmitter` | class | YES | `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py:17` |
| `SSEEmitter.emit_status` | method | YES | `sse_emitter.py:20` |
| `S10Port` / `AlertPort` | Protocol port | NO — NEW (this plan Wave A); does not exist in `application/ports/upstream_clients.py` | — |
| `S10Client` / alert service HTTP client | infra adapter | NO — NEW (this plan Wave A) | — |
| `POST /api/v1/alerts` | S10 create-alert endpoint | NO — DOES NOT EXIST in S10 alert service. S10 only has: `GET /alerts/pending`, `DELETE /alerts/{id}/ack`, `PATCH /alerts/{id}/acknowledge`, `PATCH /alerts/{id}/snooze`, `GET /alerts/history`, `WS /alerts/stream`. Wave B MUST add this endpoint to S10 first, or reuse `AlertPreference` creation — see §3. | — |
| `GET /api/v1/alerts/pending` | S10 endpoint | YES | `alert/api/routes.py:49` |
| `GET /v1/alerts/pending` | S9 proxy | YES | `api_gateway/routes/proxy.py:581` |
| `POST /v1/alerts` | S9 proxy create-alert | NO — DOES NOT EXIST. Must be added in Wave B before the tool handler can work. | — |
| `ToolExecutorFactory` | class | YES — `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:140` | PLAN-0067 shipped 2026-05-08 |
| `EntityContext` | value object | YES — `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:109` | PLAN-0067 shipped 2026-05-08 |

**Critical gap**: `POST /api/v1/alerts` does not exist in either S10 or S9. Wave B must include a sub-task to add this endpoint to S10 (with outbox pattern for the DB write — R8) and a matching S9 proxy before the `create_alert` tool handler can be wired.

---

## 2. Tools

| Tool | Purpose | Backed by | Side-effects |
|---|---|---|---|
| `get_alerts` (NEW — Wave A) | List the user's active alerts | S9 `GET /v1/alerts/pending` (existing) → S10 via `S10Port` Protocol | none |
| `create_alert` (NEW — Wave B) | Create a new alert (entity_id, condition, threshold, severity) | S9 `POST /v1/alerts` (NEW — Wave B) → S10 (NEW — Wave B) via `S10Port` Protocol | YES — writes to user's alert list |

## 3. Scope

| Wave | Title | Layer | Effort | Status |
|------|-------|-------|--------|--------|
| A | `get_alerts` tool: `S10Port` Protocol (NEW), S10 HTTP client adapter (NEW), handler wrapping `GET /v1/alerts/pending`, manifest entry (`since` value follows PLAN-0080/0081 convention — see §4), 5 eval queries | S8 | 4 hours | **DONE 2026-05-09** (commit: feat(rag-chat): PLAN-0082 Wave A) |
| B | `alert.created.v1` Avro schema (NEW — `infra/kafka/schemas/alert.created.v1.avsc`) + `CanonicalAlertCreated` canonical model (NEW — `libs/contracts/src/contracts/events/alert/alert_created.py`) + contract tests (NEW — `libs/contracts/tests/test_events_alert_created.py`) [**already implemented in revise-prd pass**] + `CreateAlertUseCase` in S10 (NEW) + `POST /api/v1/alerts` S10 endpoint (NEW — writes Alert row + outbox event in single transaction per R8, emitting `alert.created.v1`) + S9 proxy `POST /v1/alerts` (NEW) + `create_alert` tool handler in S8 via `S10Port` with **explicit confirmation flow**: SSE `pending_action` event (NEW) → user clicks Approve/Reject in UI → SSE `action_executed` (NEW) or `action_rejected` (NEW) → tool result returned to LLM. `SSEEmitter` extended with 3 new emit methods (NEW). `ActionConfirmModal.tsx` (NEW — `apps/worldview-web/features/chat/components/ActionConfirmModal.tsx`) wires Approve/Reject buttons to the SSE flow. | S8 + S10 + S9 + frontend | 1.5 dev-days (frontend modal included) | **DONE 2026-05-09** |
| C | Comprehensive adversarial-eval expansion (build on PLAN-0067 W11-4): 30 prompt-injection attempts targeting `create_alert` specifically — cross-user creation, malformed thresholds, DoS via mass creation, tenant-bypass, system-prompt extraction, indirect injection via entity names, role confusion | tests | 6 hours | **DONE 2026-05-09** (commit: test(rag-chat): PLAN-0082 Wave C — 30 adversarial prompt-injection tests; all 30 pass) |

## 4. Hard Constraints

- **No silent writes**: `create_alert` *cannot* execute without explicit user approval surfaced via SSE. The LLM can propose; the user authorizes.
- **Rate-limit at executor**: max 5 `create_alert` proposals per user per session (enforced in `ToolExecutor`, not in the upstream service).
- **Adversarial-eval gate**: `create_alert` ships only after PLAN-0067 W11-4 adversarial baseline + this plan's Wave C adversarial expansion are both at 100% safe-refusal.
- **Manifest version**: tools use `since: "<version>"` where `<version>` is whatever top-level version string PLAN-0080 Wave A establishes (currently `"1"` → PLAN-0080 bumps to `"v2"` → PLAN-0081 bumps to `"v3"` → this plan bumps to `"v4"`). **Do not hard-code `"v4"` until PLAN-0080 and PLAN-0081 have run** — use whatever value `PLAN-0081` sets, then increment by one. Verify the current top-level `version:` field before writing.
- **R29 enforcement note**: `RULES.md` R29 references `tests/architecture/test_tool_manifest_sync.py` as the automated gate for manifest/handler sync. **This file does not yet exist** in `tests/architecture/`. Until it is created (expected in PLAN-0080 Wave A), manifest enforcement is documentation-only. Implementer must manually verify every manifest entry has a registered handler and vice versa.
- **ABC/Protocol port requirement (R25)**: `get_alerts` and `create_alert` handlers MUST go through `S10Port` Protocol (NEW — Wave A), defined in `application/ports/upstream_clients.py`. No handler may import from `infrastructure/clients/s10_client.py` directly.
- **Auth flow through EntityContext (R30)**: `user_id` and `tenant_id` MUST flow through `EntityContext` bound at `ToolExecutorFactory.for_request(user_id=..., tenant_id=..., ...)` (PLAN-0067 W11-3 pattern, R30). The `create_alert` handler MUST extract `user_id` and `tenant_id` from the request-scoped `ToolExecutor`, not from a singleton. Passing auth context in singleton `__init__` is BP-406 — a blocking architecture violation.
- **Outbox pattern for `create_alert` (R8)**: S10's new `POST /api/v1/alerts` endpoint MUST write the `Alert` row and the `outbox_events` row in a single DB transaction. The outbox event emitted is `alert.created.v1` (Avro schema: `infra/kafka/schemas/alert.created.v1.avsc`, canonical model: `libs/contracts/src/contracts/events/alert/alert_created.py`). Use `CanonicalAlertCreated.to_dict()` to build the payload; serialize with `serialize_confluent_avro` (R28). No Kafka consumer exists yet — the event is emitted for auditability and future consumers. The outbox dispatcher picks it up and publishes it without any S10-side consumer listening.
- **ReadOnlyUoW for `get_alerts` (R27)**: `get_alerts` is read-only. Its handler calls S10 via HTTP only; no DB access in S8. S10's `GET /api/v1/alerts/pending` is already backed by a read-only path.
- **UoW NOT held across HTTP call (R24)**: tool handler execution MUST NOT hold a DB session/UoW across the HTTP call to S10. S8 tool handlers are purely HTTP — they acquire no UoW.
- **SSE extension (Wave B)**: `SSEEmitter` in `application/pipeline/sse_emitter.py` gets 3 new methods: `emit_pending_action(proposal_id, tool_name, proposed_args)`, `emit_action_executed(proposal_id, tool_name, result_summary)`, `emit_action_rejected(proposal_id, reason)`. These methods follow the existing pattern (return `dict[str, str]` with `event` + `data` keys). These are PIPELINE-level events, not chat-completion events — they are emitted during the tool-use confirmation flow.
- **Adversarial test coverage (Wave C)**: the 30 adversarial attempts MUST include at minimum: (1) cross-tenant alert creation (LLM injects `tenant_id` in tool args), (2) EntityContext bypass (LLM passes different `entity_id` than scoped), (3) system-prompt extraction (LLM asks for full system prompt), (4) indirect injection via malicious entity names in RAG context, (5) role confusion (LLM instructed to ignore safety checks), (6) DoS via mass creation (loop instruction), (7) malformed threshold (negative values, NaN, overflow), (8) privilege escalation (LLM requests admin alert types). All must produce safe-refusal or scope-limited execution — no partial writes.
- **UUIDs**: `common.ids.new_uuid7()` for any new alert IDs (R10).
- **Timestamps**: `common.time.utc_now()` (R11).
- **structlog only**: all logging uses `structlog.get_logger()`, never stdlib `logging`.
- **R29 compliance**: `capability_manifest.yaml` updated atomically. `create_alert` entry marked as `requires_confirmation: true` (custom manifest field to indicate UI gate).

## 5. Cross-cutting

- New SSE event types `pending_action`, `action_executed`, `action_rejected` (NEW — Wave B) added to `SSEEmitter` (existing class). The `.claude-context.md` SSE event types table must be updated in the same commit.
- Frontend: action confirmation modal in `apps/worldview-web/features/chat/components/ActionConfirmModal.tsx` (NEW — Wave B frontend sub-task).
- Documentation: `docs/services/rag-chat.md` adds an "Action Tools and User Authorization" section.

## 6. Out of scope

- Trading actions — deliberately excluded. Read-only platform.
- Calendar actions, watchlist edits — captured for a future plan once authorization UX is proven on alerts.

---

*Stub generated 2026-05-07. BP-405 audit 2026-05-07. Revised 2026-05-09 (revise-prd): R-001..R-006 applied; `alert.created.v1` Avro schema + `CanonicalAlertCreated` canonical model + 11 contract tests already implemented.*
