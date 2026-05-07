# PLAN-0080 — Intelligence-Layer LLM Tools (Narratives, Paths, Health, Bundle)

> **PRD**: derived from `/investigate` 2026-05-07 — issue A-4 (the intelligence layer is the differentiator; it MUST be tool-callable)
> **Status**: stub
> **Created**: 2026-05-07
> **Last revised**: 2026-05-07 (BP-405 name-verification + architecture compliance audit)
> **Owner**: TBD
> **Estimated effort**: ~1.5 dev-days (1 wave, ~6 tasks)
> **Critical path**: single wave
> **Hard dependencies**:
>   - PLAN-0074 Wave G **MUST BE COMPLETE** — provides S9 proxy routes for `/api/v1/entities/{id}/intelligence`, `/api/v1/entities/{id}/paths`, `/api/v1/entities/{id}/narratives`. Wave G is the ONLY acceptable upstream; S8 tool handlers must NOT call S7 directly (R14: frontend/internal→S9 only, same rule applies to internal service-to-service calls through the public gateway). Until Wave G lands, there are NO routable endpoints to wrap.
>   - PLAN-0067 W11-3 **MUST BE COMPLETE** — provides `ToolExecutorFactory` (NEW — created in PLAN-0067 W11-3), `ToolExecutor` (NEW — created in PLAN-0066 Wave H, extended in W11-3), `EntityContext` value object (NEW — created in PLAN-0067 W11-3), and `capability_manifest.yaml` v1 (NEW — created in PLAN-0066 Wave H).
>   - PLAN-0066 Wave H **MUST BE COMPLETE** — provides `capability_manifest.yaml`, `ToolRegistry`, `ToolSpec` base classes.
> **Blocks**: PLAN-0081, PLAN-0082 (manifest version conventions)

---

## §0 Why this plan exists

PLAN-0074 ships entity narratives, multi-hop path insights, health scores, and an intelligence bundle as REST endpoints — but does not register them in `capability_manifest.yaml`. For a long-term Bloomberg competitor, these ARE the differentiators; the chat LLM must be able to reach for them.

This plan adds 4 tools to the catalog and the corresponding `ToolExecutor` handlers.

---

## §1 BP-405 Name Verification

The following names were mechanically verified via `grep` against the current codebase on 2026-05-07.
Items tagged **NEW** do not exist yet and will be created by the indicated plan/wave.

| Name | Type | Exists now? | Source |
|------|------|-------------|--------|
| `get_entity_narrative` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `get_entity_paths` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `get_entity_health` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `get_entity_intelligence` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `EntityContext` | value object | NO — NEW (PLAN-0067 W11-3) | — |
| `ToolExecutorFactory` | class | NO — NEW (PLAN-0067 W11-3) | — |
| `ToolExecutorFactory.for_request(...)` | method | NO — NEW (PLAN-0067 W11-3) | — |
| `ToolExecutor` | class | NO — NEW (PLAN-0066 Wave H) | — |
| `capability_manifest.yaml` | file | NO — NEW (PLAN-0066 Wave H) | — |
| `S7Port` | Protocol port | YES | `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py:154` |
| `S7IntelligencePort` | new Protocol port extension | NO — NEW (this plan Wave A) | — |
| `GET /api/v1/entities/{id}/intelligence` | S7 endpoint | YES (PLAN-0074 Wave C) | `services/knowledge-graph/` |
| `GET /api/v1/entities/{id}/paths` | S7 endpoint | YES (PLAN-0074 Wave D) | `services/knowledge-graph/` |
| `GET /api/v1/entities/{id}/narratives` | S7 endpoint | YES (PLAN-0074 Wave B) | `services/knowledge-graph/` |
| S9 proxy for `/api/v1/entities/{id}/intelligence` | S9 gateway route | NO — NEW (PLAN-0074 Wave G) | — |
| S9 proxy for `/api/v1/entities/{id}/paths` | S9 gateway route | NO — NEW (PLAN-0074 Wave G) | — |
| S9 proxy for `/api/v1/entities/{id}/narratives` | S9 gateway route | NO — NEW (PLAN-0074 Wave G) | — |

**Verification passes**: S7Port, S7Port.get_egocentric_graph (existing method shape).
**Verification fails (all are NEW and correctly tagged above)**: all 4 tool names, EntityContext, ToolExecutorFactory, capability_manifest.yaml.

---

## 2. Tools

| Tool name | Purpose | Backed by | EntityContext-respecting |
|---|---|---|---|
| `get_entity_narrative` (NEW — Wave A) | Retrieve current LLM-generated narrative for an entity (markdown) | S9 proxy → S7 `GET /api/v1/entities/{id}/narratives` (latest version) | YES — auto-injects entity_id when scope is set |
| `get_entity_paths` (NEW — Wave A) | Top-N pre-computed multi-hop paths anchored on an entity (composite_score-ranked) | S9 proxy → S7 `GET /api/v1/entities/{id}/paths` | YES |
| `get_entity_health` (NEW — Wave A) | Health score + key_metrics + source_distribution + 90-day confidence trend | S9 proxy → S7 `GET /api/v1/entities/{id}/intelligence` (subset) | YES |
| `get_entity_intelligence` (NEW — Wave A) | Full intelligence bundle (narrative + paths + health + relations summary) — single call when user asks "tell me everything about X" | S9 proxy → S7 `GET /api/v1/entities/{id}/intelligence` | YES |

## 3. Scope

| Wave | Title | Layer | Effort |
|------|-------|-------|--------|
| A | Manifest entries (4 tools, with `since: v2`); `S7IntelligencePort` Protocol extension (NEW — Wave A); `ToolExecutor` handlers wrapping S9 routes via `S7IntelligencePort`; request-scoped EntityContext auto-injection via `ToolExecutorFactory.for_request(...)` (already established by PLAN-0067 W11-3); tests + 5 golden-eval queries added to PLAN-0067 W11-4 | libs + S8 | 1.5 dev-days |

## 4. Hard Constraints

- **No new endpoints needed** — pure tool-handler layer over PLAN-0074's REST surface proxied through S9 (Wave G).
- **ABC/Protocol port requirement (R25)**: all 4 tool handlers MUST go through `S7IntelligencePort` (a `Protocol` port defined in `application/ports/upstream_clients.py`, extending `S7Port`). Tool handlers MUST NOT import from `infrastructure/clients/s7_client.py` directly. This follows the existing `S7Port` pattern at `upstream_clients.py:154`.
- **S9-only access (R14/R7)**: tool handlers call S9-proxied URLs, not S7 directly. The infrastructure adapter for `S7IntelligencePort` calls `app.state.s9_base_url` routes.
- **EntityContext enforcement (M-1)**: when `EntityContext.entity_id` is set on the request-scoped `ToolExecutor` (bound via `ToolExecutorFactory.for_request(entity_context=...)`), all 4 tools auto-filter to that entity_id. The LLM cannot pass a different `entity_id` argument when scope is set. If the LLM passes `entity_id` and scope is already set, the executor silently replaces with the scoped value and emits a `structlog` warning (never stdlib logging — R14 equivalent for logs, structlog only).
- **Trust scoring**: the resulting `RetrievedItem` flows through `TrustScorer` (PLAN-0079); `source_type="narrative"` gets a high authority (~0.88), reflecting that narratives are platform-curated.
- **Manifest versioning**: all 4 entries have `since: "v2"`. Manifest top-level version bumps to `v2` in the same Wave A commit.
- **R29 compliance**: `capability_manifest.yaml` MUST be updated atomically with the handler registration. Every new tool entry requires `name`, `description`, `parameters`, `since`, and at least 2 `example_queries`. The architecture test `tests/architecture/test_tool_manifest_sync.py` will fail otherwise.
- **UUIDs**: any entity IDs created by handlers use `common.ids.new_uuid7()` (R10). No `uuid.uuid4()`.
- **Timestamps**: any timestamps use `common.time.utc_now()` (R11). No naive datetimes.
- **structlog only**: all logging in handlers uses `structlog.get_logger()`, never `import logging` (R14-equivalent).
- **ReadOnlyUoW for reads (R27)**: all 4 tools are read-only. Their handlers MUST NOT acquire `UnitOfWork`; they call upstream services via HTTP only. No DB writes.

## 5. Cross-cutting

- Documentation: `docs/services/rag-chat.md` lists the 4 new tools in the "Tool Catalog" section.
- Tests: each tool gets a unit test for: (a) happy path, (b) EntityContext enforcement (scoped entity_id overrides LLM-supplied arg), (c) scope mismatch (entity_id from LLM differs from scope — verify override).
- No Alembic migrations required.

---

*Stub generated 2026-05-07. BP-405 audit 2026-05-07.*
