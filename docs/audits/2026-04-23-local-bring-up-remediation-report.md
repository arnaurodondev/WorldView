# Audit Report: Local Platform Bring-Up Remediation

**Date**: 2026-04-23
**Branch**: `feat/content-ingestion-wave-a1`
**Investigator**: Claude Code (remediation skill)
**Scope**: Full remediation of all defects found in the first full local bring-up investigation.
**Verdict**: **READY** — all critical defects resolved, platform healthy, full test suite green.

---

## 1. Defect Matrix

| ID | Defect | Root Cause | Fix Applied | Status |
|----|--------|------------|-------------|--------|
| D-01 | `rag-chat` crashes at startup — `ArgumentError: Could not parse SQLAlchemy URL from string ''` | `RAG_CHAT_DATABASE_URL_READ=` (empty) → pydantic-settings parses as `SecretStr("")` not `None`; `is not None` guard bypassed; empty string passed to `create_async_engine` | `session.py:75` — `if read_url is None or` → `if not read_url or` (BP-179) | ✅ FIXED |
| D-02 | `nlp-pipeline-unresolved-resolution-worker` restart loop — `UndefinedColumnError: column "resolution_outcome" does not exist` | Running Docker image predated migrations 0006–0009; `nlp_db.entity_mentions` at schema version 0005 | Rebuilt `nlp-pipeline` + `nlp-pipeline-migrate` images; re-ran migration container; DB advanced 0005→0009 | ✅ FIXED |
| D-03 | `GET /v1/news/top` returns 404 | (a) Running api-gateway image had old proxy route (→ S5); (b) Running nlp-pipeline image lacked `api.routes.news` module | Rebuilt both `api-gateway` and `nlp-pipeline` images; both now include current source | ✅ FIXED |
| D-04 | `GET /v1/news/top` returns 500 — `AmbiguousParameterError: could not determine data type of parameter $2/$3` | asyncpg cannot infer type for nullable params in `IS NULL` checks inside CTEs; needs explicit `CAST` | `news_query.py` — wrapped `:routing_tier` and `:min_display_score` in `CAST(:x AS TEXT)` / `CAST(:x AS DOUBLE PRECISION)` (BP-180) | ✅ FIXED |
| D-05 | Alert service startup logs duplicate `InternalJWTMiddleware` behavior | Lifespan `jwt_mw` created without `skip_verification=settings.internal_jwt_skip_verification`; inconsistent behavior when skip=True | `alert/app.py` — added `skip_verification=settings.internal_jwt_skip_verification` to lifespan instance | ✅ FIXED |
| D-06 | `rag-chat` crashes after D-01 fix — `ModuleNotFoundError: No module named 'ml_clients'` | `services/rag-chat/Dockerfile` missing `libs/ml-clients` COPY + install + PYTHONPATH | Added `ml-clients` to rag-chat Dockerfile build stage and PYTHONPATH (BP-181) | ✅ FIXED |
| D-07 | `claim.extracted.v1-value` schema missing from Schema Registry | `claim.extracted.v1` topic created in Kafka but no `.avsc` file existed; `register-schemas.py` only registers files present in `infra/kafka/schemas/` | Created `infra/kafka/schemas/claim.extracted.v1.avsc`; re-ran schema-registry-init | ✅ FIXED |
| D-08 | Intelligence-migrations Ollama 404s during relation-type embedding | Ollama running but no model loaded at first boot (404 = model-not-found, not connectivity) | Expected behavior at cold start; seeds retry on next intelligence-migrations run. Not a blocking defect. | ✅ DOCUMENTED |

---

## 2. Bootstrap Sequence Validated

**Confirmed local dev bootstrap** (no external dependencies required):
1. `docker.env` files are gitignored but present from prior `setup-dev.sh` run (worldview-gitops)
2. `make fetch-secrets` target does NOT exist in Makefile — CLAUDE.md reference is stale documentation
3. `worldview-gitops/bootstrap/generate-secrets.sh` is DEPRECATED and K8s-only — not needed for local dev
4. `make dev` works directly once `docker.env` files are present

**No K8s secrets infrastructure needed for local dev.**

---

## 3. Platform Health Summary

Post-remediation container status (2026-04-23):

| Category | Count | Status |
|----------|-------|--------|
| Running (healthy) | 54 | ✅ All green |
| One-shot exits (code 0) | 10+ | ✅ Expected |
| Restarting | 0 | ✅ None |
| Crashed | 0 | ✅ None |

All previously-crashing/restarting services are now healthy:
- `worldview-rag-chat-1` → **Up (healthy)**
- `worldview-nlp-pipeline-unresolved-resolution-worker-1` → **Up (healthy)**
- `worldview-nlp-pipeline-1` → **Up (healthy)** (news routes included)

---

## 4. Endpoints Verified

| Endpoint | Before | After |
|----------|--------|-------|
| `GET /v1/news/top` | 404 (stale gateway) → 500 (ambiguous param) | **200 OK** `{"articles": [], "total": 0}` |
| `GET /readyz` (all services) | mixed | **200 OK** (all) |
| Schema Registry subjects | missing `claim.extracted.v1-value` | **Registered** |

---

## 5. Database Migrations

| Service | DB | Before | After |
|---------|-----|--------|-------|
| nlp-pipeline | `nlp_db` | `0005` | **`0009`** (0006: ner_model_id, 0007: resolution_outcome, 0008: llm_usage_log, 0009: article_impact_windows) |

---

## 6. Test Results

| Suite | Count | Result |
|-------|-------|--------|
| All service unit tests | 511 (nlp-pipeline) + all others | ✅ PASS |
| Lib unit tests | 6 lib suites, 79+ tests | ✅ PASS |
| Ruff lint | All changed files | ✅ PASS |

Detailed per-service counts (unchanged from last QA):
- alert: 345 ✅ | rag-chat: 378 ✅ | nlp-pipeline: 511 ✅

---

## 7. New Bug Patterns Added

| Pattern | Summary |
|---------|---------|
| **BP-179** | pydantic-settings `Optional[SecretStr]` + `is not None` guard broken for `KEY=` empty env vars |
| **BP-180** | asyncpg `AmbiguousParameterError` for nullable params in `IS NULL` checks — requires explicit `CAST` |
| **BP-181** | Service Dockerfile missing shared lib (ml-clients) — `ModuleNotFoundError` at startup |

---

## 8. Files Changed

| File | Change |
|------|--------|
| `services/rag-chat/src/rag_chat/infrastructure/db/session.py` | Fix BP-179: `not read_url` instead of `read_url is None` |
| `services/rag-chat/Dockerfile` | Add ml-clients: COPY + install + PYTHONPATH (BP-181) |
| `services/alert/src/alert/app.py` | Pass `skip_verification=settings.internal_jwt_skip_verification` to lifespan jwt_mw |
| `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py` | Fix BP-180: `CAST(:routing_tier AS TEXT)` and `CAST(:min_display_score AS DOUBLE PRECISION)` |
| `services/nlp-pipeline/tests/unit/infrastructure/test_news_query_repo.py` | Update test assertion to match new CAST-based SQL pattern |
| `infra/kafka/schemas/claim.extracted.v1.avsc` | New file: Avro schema for claim.extracted.v1 topic |
| `docs/BUG_PATTERNS.md` | Added BP-179, BP-180, BP-181 |

---

## 9. Open Items (Non-Blocking)

| Item | Notes |
|------|-------|
| `make fetch-secrets` missing from Makefile | Stale CLAUDE.md reference. Local dev works without it. Fix: remove from CLAUDE.md or add dummy target. |
| Intelligence-migrations Ollama 404s at cold start | Expected: Ollama boots but model not pre-loaded. Seeds only affect `relation_type_embeddings`. No impact on core platform. |
| `gateway_db` and `kg_db` in `init-databases.sh` | Both are legitimate: `gateway_db` is for future stateful S9 features; `kg_db` has Apache AGE for the knowledge graph. Both kept. |
| `claim.extracted` topic name mismatch | Code uses `claim.extracted` (no `.v1`); Kafka creates `claim.extracted.v1`. Kafka auto-creates topics on produce. Low-priority alignment task. |
| No consumer for `claim.extracted` | Claims are produced to Kafka but no service consumes them. Pipeline is incomplete for this stage. |

---

## 10. Verdict

**READY** — the platform cold-starts without crashes, all 54 containers are healthy, `/v1/news/top` serves correctly, and the full unit test suite is green. Five code defects and one Dockerfile defect were fixed; three new bug patterns catalogued.
