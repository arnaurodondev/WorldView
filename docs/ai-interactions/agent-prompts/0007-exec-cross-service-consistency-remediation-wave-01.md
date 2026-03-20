> **STATUS: PENDING** — This wave has not yet been implemented. When all tasks in this wave are completed and merged, update this flag to `IMPLEMENTED`. When the final wave of this scope (wave-02) is also completed, update the plan file `0008-exec-wave-cross-service-consistency-remediation-plan.md` and that wave file to `IMPLEMENTED` as well.

# Execution Prompt 0007 — cross-service-consistency-remediation wave 01

## Context (read first)

- **Source**: Cross-service consistency audit conducted 2026-03-19. Full audit report: `docs/ai-interactions/agent-responses/0007-response-20260319-cross-service-consistency-audit.md`
- **Wave plan**: `docs/ai-interactions/agent-prompts/0008-exec-wave-cross-service-consistency-remediation-plan.md`
- **Goal**: Resolve architecture decision blockers, fix safety-critical gateway contract mismatches, correct stale documentation (ports, paths, DB names, compose scope), and establish canonical ID policy. These fixes unblock wave-02's large S4–S8 truth-alignment work.

---

## Assigned agent profile(s)

- `.claude/agents/backend-engineer.md`
- `.claude/agents/architecture-decision-lead.md`

---

## Mandatory pre-read

Read **all** of these before writing any code or docs:

1. `AGENTS.md` — coding standards, naming conventions, architecture patterns
2. `CLAUDE.md` — fail-fast validation loop, task-scoped gates, no deferred fixes
3. `RULES.md` — ID policy, event standards
4. `docs/MASTER_PLAN.md` — canonical architecture reference
5. `docs/ai-interactions/agent-responses/0007-response-20260319-cross-service-consistency-audit.md` — full divergence evidence
6. `services/api-gateway/src/api_gateway/routes.py` — current route definitions
7. `services/api-gateway/src/api_gateway/clients.py` — downstream call paths
8. `services/api-gateway/src/api_gateway/middleware.py` — current auth implementation
9. `services/api-gateway/src/api_gateway/config.py` — current settings
10. `services/market-data/src/market_data/api/routers/` — all router files (verify actual paths)
11. `infra/compose/docker-compose.yml` — current compose service coverage
12. `docs/ai-interactions/BUG_PATTERNS.md` — scan before any code changes

---

## Scope & Bounded write paths

Only touch files listed per task. Do not refactor surrounding code.

---

## Task scope for this wave

**Tasks: D-001, D-002, D-003, D-004, D-011, D-012, D-013, D-014, D-015, D-016, D-018**

### Parallel group A — Documentation-only baseline corrections (no code dependency)

| Task ID | Short title | Files to change |
|---------|-------------|-----------------|
| D-001 | Fix AGENTS.md service entry-point table | `AGENTS.md` |
| D-002 | Fix Portfolio doc header port | `docs/services/portfolio.md` |
| D-003 | Fix Market Ingestion doc (paths, port, command) | `docs/services/market-ingestion.md` |
| D-004 | Fix RAG/Chat doc (module path root, port) | `docs/services/rag-chat.md` |

These four tasks have no code dependency and can be executed in any order or in parallel.

### Parallel group B — Architecture/policy decisions (ADR creation, no code change)

| Task ID | Short title | Files to change |
|---------|-------------|-----------------|
| D-015 | Create ADR: S8 stateless vs stateful persistence | `docs/adr/ADRNNN-rag-chat-persistence.md` |
| D-018 | Create ADR: canonical ID policy (UUIDv7 vs UUID/ULID) | `docs/adr/ADRNNN-id-policy.md`, `RULES.md`, `AGENTS.md`, `docs/libs/common.md` |

### Sequential group — Gateway contract fixes (must follow group B for D-015 awareness)

| Task ID | Short title | Files to change | Depends on |
|---------|-------------|-----------------|------------|
| D-013 | Align API Gateway env example with consumed settings | `services/api-gateway/configs/dev.local.env.example`, `services/api-gateway/src/api_gateway/config.py`, `docs/services/api-gateway.md` | none |
| D-011 | Align API Gateway route prefix and auth model | `services/api-gateway/src/api_gateway/routes.py`, `docs/services/api-gateway.md` | D-013 |
| D-012 | Fix S9↔S3 downstream call path mismatch + contract tests | `services/api-gateway/src/api_gateway/clients.py`, `services/market-data/src/market_data/api/routers/`, tests | D-011 |

### Parallel group C — Config/infra hygiene (independent of gateway group)

| Task ID | Short title | Files to change |
|---------|-------------|-----------------|
| D-014 | Canonicalize S2 DB name across docs/config/init scripts | `docs/MASTER_PLAN.md`, `services/market-ingestion/src/market_ingestion/config.py` or `infra/postgres/init/init-databases.sh`, `docs/services/market-ingestion.md` |
| D-016 | Clarify infra/compose scope | `infra/compose/docker-compose.yml`, `docs/workflows/local-dev.md` |

---

## Implementation instructions

---

### D-001 — Fix AGENTS.md service entry-point table

**Why:** The service entry-point table in AGENTS.md section 8 lists stale ports and module paths that do not match any current Makefile `run` target.

**How:**
1. For each service, read its `Makefile` run target (`make run` or `make dev`) to get the actual `--port` and the actual module path (e.g. `uvicorn market_ingestion.app:app`).
2. Replace the AGENTS.md Section 8 table with a freshly generated table: columns `Service`, `Port`, `Module path`, `Profile`.
3. Ensure the table matches all 9 services (Portfolio, Market Ingestion, Market Data, Content Ingestion, Content Store, NLP Pipeline, Knowledge Graph, RAG/Chat, API Gateway).

**Tests:** No code tests. Manually verify: pick 3 services and confirm the port in AGENTS.md matches `grep -r "port" services/<svc>/Makefile`.

**Documentation:** AGENTS.md is itself the documentation.

---

### D-002 — Fix Portfolio doc header port

**Why:** `docs/services/portfolio.md` line 3 states port 8000 but `services/portfolio/Makefile` run target uses port 8001.

**How:**
1. Open `docs/services/portfolio.md`, find the port reference in the header/overview section.
2. Change `8000` → `8001`.
3. Scan the rest of the file for any other `8000` references in the context of portfolio and fix them.

**Tests:** None needed — docs-only fix.

**Documentation:** docs/services/portfolio.md is the target.

---

### D-003 — Fix Market Ingestion doc (paths, port, command)

**Why:** `docs/services/market-ingestion.md` contains stale module path tree (`src/app` instead of `src/market_ingestion`), stale API server command, and wrong local run port.

**How:**
1. In `docs/services/market-ingestion.md`:
   - Replace every occurrence of `src/app` with `src/market_ingestion` in the module tree diagram/table (lines ~126, ~189, ~259).
   - Update the API server start command to match `services/market-ingestion/Makefile`.
   - Update the local run port to `8002`.
2. Do not change any domain description — only fix structural/path/port accuracy.

**Tests:** None needed — docs-only fix.

**Documentation:** `docs/services/market-ingestion.md` is the target.

---

### D-004 — Fix RAG/Chat doc (module path root, port)

**Why:** `docs/services/rag-chat.md` contains `src/app` as module root and a wrong local run port.

**How:**
1. In `docs/services/rag-chat.md`:
   - Replace module tree root from `src/app` to `src/rag_chat` (lines ~149, ~208).
   - Update local run port to `8008` (from `services/rag-chat/Makefile`).
2. Add a prominent note at the top of the service doc: `> **Implementation status**: Scaffold-only. The API endpoints documented below are planned but not yet implemented. See ADR for S8 persistence decision.`

**Tests:** None needed — docs-only fix.

**Documentation:** `docs/services/rag-chat.md` is the target.

---

### D-015 — Create ADR: S8 RAG/Chat persistence model

**Why:** MASTER_PLAN claims S8 is stateless but `services/rag-chat/src/rag_chat/config.py` defines `rag_db`. This ambiguity blocks the wave-02 truth-alignment for S8. An ADR is required before any code or docs changes.

**How:**
1. Create `docs/adr/ADR-0006-rag-chat-persistence-model.md` (use next available ADR number; check `docs/adr/` for current count).
2. ADR must cover:
   - **Context**: Current state (config.py defines `rag_db`; MASTER_PLAN says stateless).
   - **Decision**: Choose one:
     - Option A: True stateless — remove `rag_db` from config and init scripts; S8 delegates storage to S5/S7.
     - Option B: Stateful — update MASTER_PLAN to acknowledge persistence; `rag_db` is legitimate.
   - **Consequences**: Document downstream impact (init scripts, docker-compose, service docs).
3. For the thesis scope, **recommend Option A (stateless)** unless there is a clear reason for Option B.
4. After creating the ADR, update `docs/MASTER_PLAN.md` to add a reference to the ADR at the relevant section.
5. Also update `docs/services/rag-chat.md` header to reference the ADR.

**Tests:** None — docs-only.

**Documentation:** `docs/adr/ADR-0006-rag-chat-persistence-model.md`, `docs/MASTER_PLAN.md`, `docs/services/rag-chat.md`.

---

### D-018 — Create ADR: Canonical ID policy

**Why:** RULES.md mandates UUIDv7 everywhere; AGENTS.md and `docs/libs/common.md` mention UUIDv4/ULID. The inconsistency means developers cannot determine the correct ID type without auditing all documents.

**How:**
1. Create `docs/adr/ADR-0007-id-policy.md`:
   - **Context**: Current inconsistency across RULES, AGENTS, common docs.
   - **Decision**: Define policy by scope:
     - Entity IDs (DB primary keys): UUIDv7 (monotonic, time-ordered, compatible with PostgreSQL UUID column).
     - Event IDs (Kafka event `event_id` field): UUIDv7 (same rationale — ordering + uniqueness).
     - External IDs (FIGI, ISIN, etc.): pass-through strings, no policy.
   - **Rationale**: UUIDv7 everywhere simplifies the mental model and the `libs/common/ids.py` implementation.
   - **Consequences**: Any code using `uuid4()` for entity or event IDs must be migrated. Verify `libs/common/src/common/ids.py` uses UUIDv7 generator.
2. Update `RULES.md` (ID policy section) to reference the ADR and state the two-scope rule clearly.
3. Update `AGENTS.md` (ID section) to match.
4. Update `docs/libs/common.md` to state `new_id()` produces UUIDv7 and give a one-line example.

**Tests:** Unit test in `libs/common/tests/` — assert `new_id()` produces a UUIDv7 (version byte == 7). If such a test already exists, verify it passes; if not, add it.

**Documentation:** `docs/adr/ADR-0007-id-policy.md`, `RULES.md`, `AGENTS.md`, `docs/libs/common.md`.

---

### D-013 — Align API Gateway env example with consumed settings

**Why:** `services/api-gateway/configs/dev.local.env.example` declares DB/Kafka/SchemaRegistry/Storage variables that `config.py` does not consume; the downstream URL vars that `config.py` actually uses (`portfolio_url`, `market_data_url`, etc.) are absent from the example.

**How:**
1. Read `services/api-gateway/src/api_gateway/config.py` to get the complete list of `Settings` fields.
2. Rewrite `services/api-gateway/configs/dev.local.env.example`:
   - Remove unused variable declarations (DB, Kafka, SchemaRegistry, Storage).
   - Add all actually consumed vars (downstream service URLs, JWT secret if used, port, debug).
   - Use `GATEWAY_` prefix (matching the `env_prefix` in config).
   - Add a comment block at the top: `# Required environment variables for API Gateway (dev only)`.
3. Update `docs/services/api-gateway.md` Configuration section to list the actual env vars.

**Tests:** None needed for this task alone. D-011 tests will cover config loading.

**Documentation:** `docs/services/api-gateway.md` (Configuration section).

---

### D-011 — Align API Gateway route prefix and auth model

**Why:** `docs/services/api-gateway.md` documents `/api/v1/*` public routes and API-key auth; implementation exposes `/v1/*` routes with JWT middleware. The mismatch means the doc is unusable as a contract reference.

**How:**
1. Read `services/api-gateway/src/api_gateway/routes.py` and `middleware.py` to confirm current prefixes and auth model.
2. Make a decision (document as ADR comment in this wave, full ADR can be deferred):
   - **Option A (preferred for thesis scope)**: Update `docs/services/api-gateway.md` to reflect current `/v1/*` prefix and JWT middleware. No code change.
   - **Option B**: Move code to `/api/v1/*` and update docs. Only choose B if there is a strong contract reason.
3. Implement chosen option:
   - If Option A: Update every path reference in `docs/services/api-gateway.md` from `/api/v1/` to `/v1/`.
   - If Option B: In `routes.py`, change the `prefix` on the main `APIRouter` to `/api/v1`; update tests and docs.
4. In the same pass, confirm the auth model section in `docs/services/api-gateway.md` accurately describes the JWT middleware (not API-key).

**Tests:**
- If Option B: run `make test` in `services/api-gateway`; all existing tests must pass with new prefix.
- If Option A: docs-only; no test change needed.

**Documentation:** `docs/services/api-gateway.md` — route prefix table, auth model section.

---

### D-012 — Fix S9↔S3 downstream call path mismatch and add contract tests

**Why:** `services/api-gateway/src/api_gateway/clients.py` calls Market Data at paths that do not match the actual routes in `services/market-data/src/market_data/api/routers/`. This means all gateway→market-data proxied requests return 404 at runtime.

**How:**
1. List the actual Market Data routes by reading all router files in `services/market-data/src/market_data/api/routers/`.
2. In `clients.py`, update each downstream URL path to match the actual Market Data route (including prefix, resource name, and parameter names).
3. Add contract tests in `services/api-gateway/tests/` (or a new `tests/contract/` directory):
   - Create `test_market_data_client_contract.py`.
   - For each gateway→market-data call in `clients.py`, assert the path constructed by the client matches a path that the Market Data router actually registers. Use `app.routes` or a route-discovery helper rather than hardcoding strings. This ensures future route renames are caught immediately.
4. Run `make test` in both `services/api-gateway` and `services/market-data` to confirm no regressions.

**Tests:**
- `services/api-gateway/tests/contract/test_market_data_client_contract.py` — new file.
- All existing tests in both services must continue to pass.

**Documentation:** `docs/services/api-gateway.md` — update the downstream route table/composition matrix to reflect corrected paths.

---

### D-014 — Canonicalize S2 DB name

**Why:** `docs/MASTER_PLAN.md` calls the market ingestion DB `market_ingestion_db`; `services/market-ingestion/src/market_ingestion/config.py` and `infra/postgres/init/init-databases.sh` use `ingestion_db`. One of the two must become the canonical name.

**How:**
1. Choose canonical name: **`ingestion_db`** (already used in code and init scripts; fewer files to change).
2. In `docs/MASTER_PLAN.md`, find and replace `market_ingestion_db` → `ingestion_db` (lines ~128, ~252).
3. In `docs/services/market-ingestion.md`, update any DB name references to `ingestion_db`.
4. Verify `services/market-ingestion/src/market_ingestion/config.py` and `infra/postgres/init/init-databases.sh` already use `ingestion_db` (no change needed if they do).

**Tests:** None — docs-only fix.

**Documentation:** `docs/MASTER_PLAN.md`, `docs/services/market-ingestion.md`.

---

### D-016 — Clarify infra/compose scope

**Why:** `infra/compose/docker-compose.yml` has a header comment implying it covers all services, but the file only contains infra + S1–S3. The mismatch misleads developers expecting a full-stack compose.

**How:**
1. Update the header comment in `infra/compose/docker-compose.yml` to state explicitly: `# Partial stack: infra (Kafka, Postgres, MinIO, Valkey) + S1 (Portfolio), S2 (Market Ingestion), S3 (Market Data). S4-S9 not yet included.`
2. In `docs/workflows/local-dev.md`:
   - Add a note in the "Starting the stack" section: "The compose file currently starts infra + S1–S3. S4–S9 are scaffold-only and not yet wired into compose."
   - Remove or update any instructions that imply a full-system startup is possible with this compose file.

**Tests:** None — docs/comments only.

**Documentation:** `infra/compose/docker-compose.yml` (header comment), `docs/workflows/local-dev.md`.

---

## Task-scoped fail-fast gate (mandatory)

After **each** task:

1. If code was changed: run `ruff check` on changed paths.
2. If code was changed: run `mypy` on changed package(s).
3. If tests were added (D-012): run `make test` in affected services.

Fix any failure before starting the next task.

---

## Regression guardrails

Before marking wave-01 done:

1. `make test` passes in `services/api-gateway` with corrected gateway client paths.
2. `make test` passes in `services/market-data`.
3. The ID policy ADR and RULES update are consistent — grep for `uuid4` in `libs/common/src/` and verify it is not used for entity or event IDs (or confirm the ADR documents the migration plan).
4. Grep `docs/services/market-ingestion.md` for `8000` or `src/app` — must return no matches.
5. Grep `docs/services/portfolio.md` for `port: 8000` or `: 8000` — must return no matches.

---

## Documentation updates (mandatory)

| Document | Required changes |
|----------|------------------|
| `AGENTS.md` | Service entry-point table (D-001, D-018) |
| `RULES.md` | ID policy section (D-018) |
| `docs/MASTER_PLAN.md` | S2 DB name (D-014), ADR reference for S8 persistence (D-015) |
| `docs/services/portfolio.md` | Port fix (D-002) |
| `docs/services/market-ingestion.md` | Path tree, port, DB name (D-003, D-014) |
| `docs/services/rag-chat.md` | Module path root, port, ADR reference (D-004, D-015) |
| `docs/services/api-gateway.md` | Route prefix, auth model, env vars, downstream route table (D-011, D-012, D-013) |
| `docs/workflows/local-dev.md` | Compose scope note (D-016) |
| `docs/libs/common.md` | ID policy (D-018) |
| `docs/adr/ADR-0006-*.md` | New ADR: S8 persistence (D-015) |
| `docs/adr/ADR-0007-*.md` | New ADR: ID policy (D-018) |
| `infra/compose/docker-compose.yml` | Header comment (D-016) |

---

## Done criteria (wave-01 complete when all pass)

- [ ] AGENTS.md service table reflects current Makefile ports and module paths for all 9 services.
- [ ] `docs/services/portfolio.md` header shows port 8001.
- [ ] `docs/services/market-ingestion.md` has no `src/app` references; shows port 8002.
- [ ] `docs/services/rag-chat.md` has no `src/app` references; shows port 8008; references ADR-0006.
- [ ] ADR-0006 (S8 persistence decision) exists in `docs/adr/` with decision and consequences.
- [ ] ADR-0007 (ID policy) exists in `docs/adr/`; RULES.md and AGENTS.md reference it.
- [ ] `docs/libs/common.md` states `new_id()` produces UUIDv7.
- [ ] Unit test for `new_id()` returning UUIDv7 passes.
- [ ] `services/api-gateway/configs/dev.local.env.example` contains only vars consumed by `config.py`.
- [ ] `docs/services/api-gateway.md` route prefix and auth model match implementation.
- [ ] `services/api-gateway/src/api_gateway/clients.py` paths match actual Market Data routes.
- [ ] Contract tests in `services/api-gateway/tests/contract/test_market_data_client_contract.py` pass.
- [ ] `docs/MASTER_PLAN.md` uses `ingestion_db` consistently.
- [ ] `infra/compose/docker-compose.yml` header clarifies partial stack scope.
- [ ] `make test` passes in `services/api-gateway` and `services/market-data`.
- [ ] All documentation quality criteria met (accuracy, no orphans, no stale claims).

---

## Handoff evidence required

1. List of task IDs completed and changed files per task.
2. Ruff and mypy output for all changed code paths (exit codes).
3. Test output for `services/api-gateway` and `services/market-data` (command + pass count).
4. ADR file paths created.
5. **Documentation quality checklist:**

| Criterion | Status | Notes |
|-----------|--------|-------|
| Accuracy — all changed docs match implementation | ✓ / N/A | |
| No orphan documentation | ✓ | |
| ADRs created for both architecture decisions | ✓ | |
| Contract tests added for gateway↔market-data | ✓ | |
| Service docs reflect final state | ✓ | List sections updated |

6. Proposed commit message.

---

## Proposed commit message (template)

```
fix(cross-service): gateway contract alignment, stale doc corrections, ADRs for ID policy and S8

- Align api-gateway client paths with market-data routes; add contract tests.
- Correct stale ports/paths in portfolio, market-ingestion, rag-chat docs.
- Fix AGENTS.md service entry-point table from Makefile sources of truth.
- Create ADR-0006 (S8 persistence decision) and ADR-0007 (canonical ID policy).
- Canonicalize ingestion_db name in master plan; clarify compose partial scope.

Validated: gateway+market-data tests pass; ID policy unit test passes.
```
