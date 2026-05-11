# PLAN-0080 — Intelligence-Layer LLM Tools (Narratives, Paths, Health, Bundle)

> **PRD**: derived from `/investigate` 2026-05-07 — issue A-4 (the intelligence layer is the differentiator; it MUST be tool-callable)
> **Status**: completed
> **Created**: 2026-05-07
> **Last revised**: 2026-05-09
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

Re-verified 2026-05-09 (PLAN-0066 ✅ 2026-05-08, PLAN-0067 ✅ 2026-05-08, PLAN-0074 ✅ 2026-05-08).
Items tagged **NEW** do not exist yet and will be created by this plan's Wave A.

| Name | Type | Exists? | Source |
|------|------|---------|--------|
| `get_entity_narrative` | tool name (manifest + handler) | NO — NEW (Wave A) | — |
| `get_entity_paths` | tool name (manifest + handler) | NO — NEW (Wave A) | — |
| `get_entity_health` | tool name (manifest + handler) | NO — NEW (Wave A) | — |
| `get_entity_intelligence` | tool name (manifest + handler) | NO — NEW (Wave A) | — |
| `S7IntelligencePort` | new Protocol port extension | NO — NEW (Wave A) | — |
| `EntityContext` | value object | YES — PLAN-0067 done | `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:109` |
| `ToolExecutorFactory` | class | YES — PLAN-0067 done | `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:140` |
| `ToolExecutorFactory.for_request(...)` | method | YES — PLAN-0067 done | `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:167` |
| `ToolExecutor` | class | YES — PLAN-0066 done | `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:200` |
| `capability_manifest.yaml` | file | YES — PLAN-0066 done | `libs/tools/src/tools/capability_manifest.yaml` |
| `S7Port` | Protocol port | YES | `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py:165` |
| `GET /api/v1/entities/{id}/intelligence` | S7 + S9 endpoint | YES — PLAN-0074 Wave G done | `services/api-gateway/src/api_gateway/routes/proxy.py:2023` |
| `GET /api/v1/entities/{id}/paths` | S7 + S9 endpoint | YES — PLAN-0074 Wave G done | `services/api-gateway/src/api_gateway/routes/proxy.py:2198` |
| `GET /api/v1/entities/{id}/narratives` | S7 + S9 endpoint | YES — PLAN-0074 Wave G done | `services/api-gateway/src/api_gateway/routes/proxy.py:2102` |
| `tests/architecture/test_tool_manifest_sync.py` | architecture test | NO — NEW (Wave A, see B-001) | — |

**Still NEW (Wave A creates these)**: all 4 tool names, `S7IntelligencePort`, `test_tool_manifest_sync.py`.
**Confirmed existing (no creation needed)**: `EntityContext`, `ToolExecutorFactory`, `ToolExecutor`, `capability_manifest.yaml`, all 3 S9 proxy routes.

---

## 2. Tools

| Tool name | Purpose | Backed by | EntityContext-respecting |
|---|---|---|---|
| `get_entity_narrative` (NEW — Wave A) | Retrieve current LLM-generated narrative for an entity (markdown) | S9 proxy → S7 `GET /api/v1/entities/{id}/narratives` (latest version) | YES — auto-injects entity_id when scope is set |
| `get_entity_paths` (NEW — Wave A) | Top-N pre-computed multi-hop paths anchored on an entity (composite_score-ranked) | S9 proxy → S7 `GET /api/v1/entities/{id}/paths` | YES |
| `get_entity_health` (NEW — Wave A) | Health score + key_metrics + source_distribution + 90-day confidence trend | S9 proxy → S7 `GET /api/v1/entities/{id}/intelligence` (subset) | YES |
| `get_entity_intelligence` (NEW — Wave A) | Full intelligence bundle (narrative + paths + health + relations summary) — single call when user asks "tell me everything about X" | S9 proxy → S7 `GET /api/v1/entities/{id}/intelligence` | YES |

## 3. Scope

| Wave | Title | Layer | Effort | Status |
|------|-------|-------|--------|--------|
| A ✅ | (1) `capability_manifest.yaml` — add 4 tool entries with `since: "v2"`; bump top-level `version:` from `"1"` → `"2"`. (2) `S7IntelligencePort` Protocol extension (NEW) in `application/ports/upstream_clients.py`. (3) `ToolExecutor` — add 4 `_handle_*` methods dispatching via `S7IntelligencePort`; add handlers to the `execute()` dispatch table. (4) **`build_default_registry()`** (`tool_executor.py`) — register all 4 new `ToolSpec` entries (required for the LLM system-prompt; without this the tools are dead code). (5) **`sse_emitter.py _TOOL_LABELS`** — add UI labels for all 4 tools. (6) **`tests/architecture/test_tool_manifest_sync.py`** (NEW — R29 enforcement; see §4) — asserts every YAML tool name has a corresponding registration in `build_default_registry()`. (7) Unit tests (happy path + EntityContext enforcement + scope mismatch). (8) 5 golden-eval queries added to `tests/eval/golden/`. | libs + S8 | 1.5 dev-days | **DONE** — 2026-05-09 · 33 unit tests + 4 arch tests pass · ruff + mypy clean |

## 4. Hard Constraints

- **No new endpoints needed** — pure tool-handler layer over PLAN-0074's REST surface proxied through S9 (Wave G).
- **ABC/Protocol port requirement (R25)**: all 4 tool handlers MUST go through `S7IntelligencePort` (a `Protocol` port defined in `application/ports/upstream_clients.py`, extending `S7Port`). Tool handlers MUST NOT import from `infrastructure/clients/s7_client.py` directly. This follows the existing `S7Port` pattern at `upstream_clients.py:165`.
- **S9-only access (R14/R7)**: tool handlers call S9-proxied URLs, not S7 directly. The infrastructure adapter for `S7IntelligencePort` calls `app.state.s9_base_url` routes.
- **EntityContext enforcement (M-1)**: when `EntityContext.entity_id` is set on the request-scoped `ToolExecutor` (bound via `ToolExecutorFactory.for_request(entity_context=...)`), all 4 tools auto-filter to that entity_id. The LLM cannot pass a different `entity_id` argument when scope is set. If the LLM passes `entity_id` and scope is already set, the executor silently replaces with the scoped value and emits a `structlog` warning (never stdlib logging — R14 equivalent for logs, structlog only).
- **Trust scoring**: the resulting `RetrievedItem` flows through `TrustScorer` (PLAN-0079); `source_type="narrative"` gets a high authority (~0.88), reflecting that narratives are platform-curated.
- **Manifest versioning**: all 4 entries have `since: "v2"` (with `v` prefix — consistent with existing `since: "v1"` pattern). Manifest top-level `version:` field bumps from `"1"` → `"2"` (no `v` prefix — consistent with current format).
- **R29 compliance**: `capability_manifest.yaml` MUST be updated atomically with handler registration and `build_default_registry()`. Every new tool entry requires `name`, `description`, `parameters`, `since`, and at least 2 `example_queries`. Wave A MUST CREATE `tests/architecture/test_tool_manifest_sync.py` to enforce this going forward — this test does not yet exist (confirmed 2026-05-09 audit). It should load `ToolRegistry.load_manifest()` and assert every YAML tool name has a corresponding `ToolSpec` in `build_default_registry()`'s registry.
- **UUIDs**: any entity IDs created by handlers use `common.ids.new_uuid7()` (R10). No `uuid.uuid4()`.
- **Timestamps**: any timestamps use `common.time.utc_now()` (R11). No naive datetimes.
- **structlog only**: all logging in handlers uses `structlog.get_logger()`, never `import logging` (R14-equivalent).
- **ReadOnlyUoW for reads (R27)**: all 4 tools are read-only. Their handlers MUST NOT acquire `UnitOfWork`; they call upstream services via HTTP only. No DB writes.

## 5. Cross-cutting

- Documentation: `docs/services/rag-chat.md` lists the 4 new tools in the "Tool Catalog" section.
- **`sse_emitter.py _TOOL_LABELS`**: add 4 entries (e.g. `"get_entity_narrative": "Loading narrative..."`, `"get_entity_paths": "Tracing entity paths..."`, `"get_entity_health": "Computing health score..."`, `"get_entity_intelligence": "Loading intelligence bundle..."`). Without entries the UI fallback renders raw tool names with `...` suffix.
- Tests: each tool gets a unit test for: (a) happy path, (b) EntityContext enforcement (scoped entity_id overrides LLM-supplied arg), (c) scope mismatch (entity_id from LLM differs from scope — verify override).
- Architecture test: `tests/architecture/test_tool_manifest_sync.py` (NEW — created in Wave A per R29; see §4).
- No Alembic migrations required.

---

*Stub generated 2026-05-07. BP-405 audit 2026-05-07. Revised 2026-05-09 (revise-prd): stale name table updated, B-001 test scope added, B-002 registry scope added, N-001/002/003 fixed.*
