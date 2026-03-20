> **STATUS: PENDING** — This wave has not yet been implemented. Wave-02 depends on wave-01 being completed first (architecture decisions in D-015 and D-018 determine the target behavior for S4–S8). When all tasks in this wave are completed and merged, update this flag to `IMPLEMENTED` and also update the plan file `0008-exec-wave-cross-service-consistency-remediation-plan.md` to `IMPLEMENTED`.

# Execution Prompt 0007 — cross-service-consistency-remediation wave 02

## Context (read first)

- **Source**: Cross-service consistency audit: `docs/ai-interactions/agent-responses/0007-response-20260319-cross-service-consistency-audit.md`
- **Wave plan**: `docs/ai-interactions/agent-prompts/0008-exec-wave-cross-service-consistency-remediation-plan.md`
- **Prerequisite**: Wave-01 must be completed. In particular: ADR-0006 (S8 persistence decision) and ADR-0007 (ID policy) must be committed, since they define target behavior for S4–S8 truth-alignment in this wave.
- **Goal**: Align S4–S8 documentation with scaffold reality (or implement documented APIs), add Alembic migrations for documented DB schemas, close test gaps for S4–S8 services, and implement the D-017 test alignment for services whose docs claimed test depth that doesn't exist.

---

## Assigned agent profile(s)

- `.claude/agents/backend-engineer.md`
- `.claude/agents/qa-test-engineer.md`
- `.claude/agents/architecture-decision-lead.md`

---

## Mandatory pre-read

Read **all** of these before writing any code or docs:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/ai-interactions/agent-responses/0007-response-20260319-cross-service-consistency-audit.md` — Section 3 divergence log (D-005 through D-010, D-017)
4. `docs/adr/ADR-0006-*.md` — S8 persistence decision from wave-01 (MUST be read first)
5. `docs/ai-interactions/BUG_PATTERNS.md` — scan before touching Alembic or test code
6. Each scaffold service's `app.py` and `config.py`:
   - `services/content-ingestion/src/content_ingestion/`
   - `services/content-store/src/content_store/`
   - `services/nlp-pipeline/src/nlp_pipeline/`
   - `services/knowledge-graph/src/knowledge_graph/`
   - `services/rag-chat/src/rag_chat/`
7. Each scaffold service's `alembic/env.py` (to confirm `target_metadata = None`)
8. Each scaffold service's existing test file (`tests/test_health.py`)

---

## Scope & Strategy decision

Wave-01's architecture decisions determine whether each S4–S8 service should be **implemented** or **marked scaffold**. For the thesis scope, apply the following default strategy unless ADR-0006 or a wave-01 output explicitly overrides it:

- **S4 Content Ingestion, S5 Content Store, S6 NLP Pipeline, S7 Knowledge Graph**: Mark docs as scaffold/planned. Do NOT attempt to implement the full documented API in this wave (too large; out of scope). Instead:
  - Update each service doc with a prominent `> Implementation status: Scaffold — planned for future milestone.` banner.
  - Remove or clearly gate all concrete SQL DDL, route tables, and messaging diagrams as `[Planned]`.
  - Add real `target_metadata` to Alembic env so that `alembic check` does not fail on import errors (scaffold model can be empty `Base`).
- **S8 RAG/Chat**: Follow ADR-0006 (if Option A/stateless was chosen, remove `rag_db` from config and init scripts; update docs to remove persistence claims).
- **Test gaps (D-017)**: For scaffold services, update docs to explicitly say tests only cover health/readiness (removing false domain coverage claims). Do not add domain tests for unimplemented code.

If a service's ADR-0006 decision resulted in a different strategy, follow that ADR.

---

## Task scope for this wave

**Tasks: D-005, D-006, D-007, D-008, D-009, D-010, D-017**

### Parallel group A — S4–S7 docs + Alembic scaffold alignment

All four tasks are independent of each other and can be run in parallel.

| Task ID | Short title | Files to change |
|---------|-------------|-----------------|
| D-005 | Content Ingestion: align docs to scaffold; fix Alembic | `docs/services/content-ingestion.md`, `services/content-ingestion/alembic/env.py`, `services/content-ingestion/src/content_ingestion/app.py` |
| D-006 | Content Store: align docs to scaffold; fix Alembic | `docs/services/content-store.md`, `services/content-store/alembic/env.py`, `services/content-store/src/content_store/app.py` |
| D-007 | NLP Pipeline: align docs to scaffold; fix Alembic | `docs/services/nlp-pipeline.md`, `services/nlp-pipeline/alembic/env.py`, `services/nlp-pipeline/src/nlp_pipeline/app.py` |
| D-008 | Knowledge Graph: align docs to scaffold; fix Alembic | `docs/services/knowledge-graph.md`, `services/knowledge-graph/alembic/env.py`, `services/knowledge-graph/src/knowledge_graph/app.py` |

### Sequential — S8 RAG/Chat alignment (after reading ADR-0006)

| Task ID | Short title | Files to change | Depends on |
|---------|-------------|-----------------|------------|
| D-009 | RAG/Chat: align docs + code to ADR-0006 decision | `docs/services/rag-chat.md`, `services/rag-chat/src/rag_chat/config.py`, `infra/postgres/init/init-databases.sh`, `services/rag-chat/alembic/env.py` | ADR-0006 from wave-01 |

### Parallel group B — Alembic migration files (after group A fixes env.py)

| Task ID | Short title | Files to change | Depends on |
|---------|-------------|-----------------|------------|
| D-010 | Add scaffold Alembic initial migrations for S4–S8 | `services/{content-ingestion,content-store,nlp-pipeline,knowledge-graph,rag-chat}/alembic/versions/` | D-005 through D-009 |

### Test gap closure (D-017) — parallel with group B

| Task ID | Short title | Files to change |
|---------|-------------|-----------------|
| D-017 | Close test-documentation gap for S4–S8 | `docs/services/{content-ingestion,content-store,nlp-pipeline,knowledge-graph,rag-chat}.md` test sections |

---

## Implementation instructions

---

### D-005 — Content Ingestion: docs to scaffold + Alembic fix

**Why:** Docs describe full API, domain, and messaging; code is scaffold-only (`app.py` with health/readiness only). `alembic/env.py` has `target_metadata = None`, which means `alembic check` fails.

**How:**
1. Add scaffold banner to `docs/services/content-ingestion.md` top:
   ```
   > **Implementation status**: Scaffold. API, messaging, and domain behavior documented below
   > are **planned** and not yet implemented. Only `/health` and `/readiness` endpoints are active.
   ```
2. In the API Surface section, prefix each non-health route with `[Planned]`.
3. In the Kafka section, prefix all producer/consumer descriptions with `[Planned]`.
4. In the DB Schema section, prefix the DDL block with `[Planned — not yet migrated]`.
5. Fix `services/content-ingestion/alembic/env.py`:
   - Create a minimal `Base = declarative_base()` in a new file `services/content-ingestion/src/content_ingestion/infrastructure/db/base.py` (or equivalent scaffold path).
   - Set `target_metadata = Base.metadata` in `env.py`.
   - Run `alembic check` — it should report "No new upgrade operations detected" (empty scaffold schema).

**Tests:**
- `make test` in `services/content-ingestion` must pass (only health test).
- `alembic check` must exit 0.

**Documentation:** `docs/services/content-ingestion.md`.

---

### D-006 — Content Store: docs to scaffold + Alembic fix

**Why:** Same pattern as D-005 for Content Store.

**How:** Same steps as D-005, applied to `services/content-store/` and `docs/services/content-store.md`.

**Tests:** `make test` (health only). `alembic check` exits 0.

**Documentation:** `docs/services/content-store.md`.

---

### D-007 — NLP Pipeline: docs to scaffold + Alembic fix

**Why:** Same pattern as D-005 for NLP Pipeline.

**How:** Same steps as D-005, applied to `services/nlp-pipeline/` and `docs/services/nlp-pipeline.md`.

**Tests:** `make test` (health only). `alembic check` exits 0.

**Documentation:** `docs/services/nlp-pipeline.md`.

---

### D-008 — Knowledge Graph: docs to scaffold + Alembic fix

**Why:** Same pattern as D-005 for Knowledge Graph. Note: KG uses Apache AGE extension for graph storage — the scaffold `Base` should not attempt to create AGE-specific schemas; keep the scaffold metadata empty.

**How:** Same steps as D-005, applied to `services/knowledge-graph/` and `docs/services/knowledge-graph.md`. Add an additional note in the DB Schema section: `[Planned — requires Apache AGE extension; see infra/postgres/Dockerfile for AGE installation]`.

**Tests:** `make test` (health only). `alembic check` exits 0.

**Documentation:** `docs/services/knowledge-graph.md`.

---

### D-009 — RAG/Chat: align code and docs to ADR-0006

**Why:** Depending on the ADR-0006 decision:
- **If Option A (stateless)**: `rag_db` must be removed from config and init scripts; docs must remove persistence claims.
- **If Option B (stateful)**: `rag_db` is legitimate; docs must acknowledge DB dependency; Alembic must have real metadata.

**How (Option A — recommended):**
1. In `services/rag-chat/src/rag_chat/config.py`, remove `rag_db` field (or make it unused/commented with `# Removed per ADR-0006`).
2. In `infra/postgres/init/init-databases.sh`, remove the `rag_db` database creation.
3. In `docs/services/rag-chat.md`, remove any DB schema sections or mark them as `[Removed per ADR-0006]`.
4. Fix `services/rag-chat/alembic/env.py` to have `target_metadata = Base.metadata` (empty scaffold) — service may still have Alembic for future use even if stateless today.
5. Update `docs/MASTER_PLAN.md` to confirm S8 is stateless and reference ADR-0006.

**How (Option B — if ADR-0006 chose stateful):**
1. Keep `rag_db` in config and init scripts.
2. Create a real SQLAlchemy `Base` with the intended schema and set `target_metadata = Base.metadata`.
3. Create a scaffold initial migration (`0001_initial_schema.py`) covering the planned tables.
4. Update docs to remove the "stateless" claim and reference ADR-0006.

**Tests:** `make test` in `services/rag-chat` (health only). `alembic check` exits 0.

**Documentation:** `docs/services/rag-chat.md`, `docs/MASTER_PLAN.md`.

---

### D-010 — Scaffold Alembic initial migrations for S4–S8

**Why:** `services/{content-ingestion,content-store,nlp-pipeline,knowledge-graph,rag-chat}/alembic/versions/` contain only `.gitkeep` (no migration files). After D-005 through D-009 fix `env.py`, `alembic check` should already pass with empty metadata. This task creates a minimal `0001_initial_schema.py` to make the migration history non-empty and to document that "scaffold migration" is intentional.

**How:**
For each of the five services (S4, S5, S6, S7, S8):
1. Run `alembic revision --autogenerate -m "scaffold_initial"` in the service directory (or create manually).
2. If autogenerate produces an empty migration (expected for empty `Base`), that is correct — keep it.
3. Add a comment at the top of the generated migration file: `# Scaffold migration — no tables defined yet. See service docs for planned schema.`
4. Run `alembic upgrade head` and `alembic check` — both must succeed.

**Tests:** `alembic upgrade head` and `alembic check` exit 0 for each of the 5 services.

**Documentation:** No doc changes — this is infrastructure hygiene.

---

### D-017 — Close test-documentation gap for S4–S8

**Why:** `docs/services/content-ingestion.md`, `content-store.md`, `nlp-pipeline.md`, `knowledge-graph.md`, and `rag-chat.md` all claim domain and integration test coverage that does not exist (only `test_health.py` is present). After D-005 through D-009, docs already have scaffold banners. This task specifically aligns the **Testing section** of each doc.

**How:**
For each of the five service docs:
1. Find the Testing section (it may be labelled "Tests", "Testing", or "Test Suite").
2. Replace or update the test coverage claim to:
   ```
   ## Testing

   Current test suite covers health and readiness endpoints only (scaffold scope).
   Domain, application, and integration tests are planned and will be added when
   the service implementation progresses beyond scaffold.

   Run existing tests: `make test`
   ```
3. Remove any bullet lists or tables claiming domain/integration/contract test coverage.

**Tests:** None — docs-only.

**Documentation:** Five service doc Testing sections.

---

## Task-scoped fail-fast gate (mandatory)

After **each** task:

1. Run `alembic check` in every service modified (must exit 0).
2. Run `make test` in every service modified (health tests must pass).
3. Run `ruff check` on any changed Python files.

Fix any failure before starting the next task.

---

## Regression guardrails

Before marking wave-02 done:

1. For each of S4–S8: `make test` passes and `alembic check` exits 0.
2. No service doc claims "fully tested" or lists integration test files that do not exist.
3. Grep `docs/services/rag-chat.md` for `rag_db` — if ADR-0006 chose Option A, must return no matches.
4. Grep each S4–S7 service doc for concrete un-gated DDL (`CREATE TABLE`) — must be 0 matches or all marked `[Planned]`.
5. `make test` passes in `services/market-data` and `services/api-gateway` (no regressions from wave-01).

---

## Documentation updates (mandatory)

| Document | Required changes |
|----------|------------------|
| `docs/services/content-ingestion.md` | Scaffold banner, [Planned] markers, Testing section (D-005, D-017) |
| `docs/services/content-store.md` | Same (D-006, D-017) |
| `docs/services/nlp-pipeline.md` | Same (D-007, D-017) |
| `docs/services/knowledge-graph.md` | Same (D-008, D-017) |
| `docs/services/rag-chat.md` | Scaffold/stateless alignment per ADR-0006, Testing section (D-009, D-017) |
| `docs/MASTER_PLAN.md` | S8 stateless/stateful confirmation + ADR-0006 reference (D-009) |

---

## Done criteria (wave-02 complete when all pass)

- [ ] S4–S7 service docs have scaffold banners and `[Planned]` markers on all unimplemented sections.
- [ ] S8 RAG/Chat doc and code aligned to ADR-0006 decision.
- [ ] `alembic check` exits 0 for all five scaffold services.
- [ ] `make test` passes for all five scaffold services (health tests green).
- [ ] Testing sections in S4–S8 docs describe scaffold scope only.
- [ ] `docs/MASTER_PLAN.md` consistent with ADR-0006 S8 decision.
- [ ] No regressions in S1–S3 or S9 test suites.
- [ ] All documentation quality criteria met (no orphan docs, no false implementation claims).

---

## Handoff evidence required

1. Task IDs completed and changed files per task.
2. `alembic check` output for each of the 5 scaffold services (exit code).
3. `make test` output for each of the 5 scaffold services (pass count).
4. Confirmation that S1–S3 and S9 test suites pass (no regressions).
5. **Documentation quality checklist:**

| Criterion | Status | Notes |
|-----------|--------|-------|
| Scaffold banners present on S4–S8 docs | ✓ | |
| [Planned] markers on all unimplemented API/messaging/schema sections | ✓ | |
| Testing sections accurate (no false coverage claims) | ✓ | |
| ADR-0006 consistently referenced | ✓ | |
| No orphan documentation | ✓ | |

6. Proposed commit message.

---

## Proposed commit message (template)

```
fix(cross-service): S4-S8 scaffold alignment, Alembic hygiene, test-doc gap closure

- Mark S4-S7 (content-ingestion, content-store, nlp-pipeline, knowledge-graph)
  docs as scaffold with [Planned] markers; fix Alembic env.py for all 4 services.
- Align S8 (rag-chat) code/docs to ADR-0006 persistence decision.
- Add scaffold initial migrations (0001_initial_schema) for S4-S8.
- Update Testing sections in S4-S8 docs to reflect health-only coverage.

Validated: alembic check exits 0 for all 5 services; health tests pass.
```

---

## Full scope completion note

When **both wave-01 and wave-02** are completed and merged, update the following files to `IMPLEMENTED`:
- `docs/ai-interactions/agent-prompts/0007-exec-cross-service-consistency-remediation-wave-01.md` (top-of-file STATUS flag)
- `docs/ai-interactions/agent-prompts/0007-exec-cross-service-consistency-remediation-wave-02.md` (this file)
- `docs/ai-interactions/agent-prompts/0008-exec-wave-cross-service-consistency-remediation-plan.md` (plan overview)
