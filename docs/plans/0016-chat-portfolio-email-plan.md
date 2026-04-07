---
id: PLAN-0016
prd: PRD-0016
title: "Chat Enhancements: GENERAL Intent + Context Window + Portfolio Risk Email Digest"
status: in-progress
created: 2026-04-06
updated: 2026-04-07
plans: 5
waves: 11
tasks: 44
---

# PLAN-0016: Chat Enhancements + Portfolio Risk Email Digest

## Overview

**PRD Reference**: [PRD-0016](../specs/0016-chat-enhancements-portfolio-risk-digest.md)
**Goal**: Add GENERAL intent + 9 intent-specific prompt modules + 3-layer context management to S8; add weekly portfolio risk email digest with provider-agnostic email adapter to S10; route email preferences through S9.
**Total Scope**: 5 sub-plans, 11 waves, 44 tasks

---

## Plan Dependency Graph

```
Sub-Plan A: S8 Intent Prompts + Context Mgmt ──┐
                                                 ├──→ Sub-Plan B: S8 GENERAL + Briefing
Sub-Plan C: S10 Email Provider + Prefs  ────────┘         │
                                                           └──→ Sub-Plan D: S10 Scheduler
Sub-Plan E: S9 Gateway Routes (depends on C + partial A)
S1 internal endpoint (Wave E-1)
```

**Execution Order**:
1. Sub-Plan A (S8 prompts + context management) — no dependencies
2. Sub-Plan B (S8 GENERAL intent + briefing endpoint) — depends on A
3. Sub-Plan C (S10 email provider + prefs) — no dependencies, parallel with A
4. Sub-Plan D (S10 scheduler + digest) — depends on B + C
5. Sub-Plan E (S9 gateway + S1 endpoint) — depends on C (email prefs route)

---

## Sub-Plan A: S8 RAG/Chat — Intent Prompts + Context Management

### Context
S8 currently uses a single generic prompt for all 8 query intents. PRD-0016 requires 9 intent-specific prompt modules (8 existing + GENERAL) and a 3-layer context management system (chunk cache + turn summaries + bounded context assembly). This sub-plan delivers the prompt infrastructure and context management.

### Pre-Read (agent must read before any wave)
- `services/rag-chat/.claude-context.md`
- `services/rag-chat/src/rag_chat/domain/enums.py`
- `services/rag-chat/src/rag_chat/application/pipeline/prompt_builder.py`
- `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py`
- `services/rag-chat/src/rag_chat/infrastructure/config/settings.py`
- `docs/BUG_PATTERNS.md`

---

### Wave A-1: GENERAL Intent + 9 Intent-Specific Prompt Modules ✅

**Goal**: Add GENERAL as 9th QueryIntent value and create 9 intent-specific prompt module functions that replace the single generic prompt.
**Depends on**: none
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-04-06 · 18 tests pass · ruff + mypy clean

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-A-1-01 | Add `GENERAL = "GENERAL"` to `QueryIntent` StrEnum | impl | `services/rag-chat/src/rag_chat/domain/enums.py` | 9 values; existing tests still pass |
| T-A-1-02 | Update intent classifier keyword dict and prompt to include GENERAL | impl | `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py` | `_VALID_INTENTS` includes GENERAL; classifier returns GENERAL; fallback heuristic updated |
| T-A-1-03 | Create `application/pipeline/prompts/` package with 9 intent modules | impl | `services/rag-chat/src/rag_chat/application/pipeline/prompts/__init__.py`, `intent_prompts.py` | Each intent has a distinct system_prompt string + `get_system_prompt(intent)` factory |
| T-A-1-04 | Update `PromptBuilder.build()` to accept `intent` and use intent-specific prompt | impl | `services/rag-chat/src/rag_chat/application/pipeline/prompt_builder.py` | `build(intent=...)` routes to correct module; all 9 intents produce distinct prompts |
| T-A-1-05 | Unit tests: intent enum, prompt selection, keyword classifier fallback | test | `services/rag-chat/tests/unit/pipeline/test_intent_prompts.py`, `tests/unit/domain/test_enums.py` | 18+ tests pass covering all 9 intents |

#### Pre-Read
- `services/rag-chat/src/rag_chat/domain/enums.py`
- `services/rag-chat/src/rag_chat/application/pipeline/prompt_builder.py`
- `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py`

#### Validation Gate
- [x] `ruff check services/rag-chat/src/rag_chat/domain/enums.py services/rag-chat/src/rag_chat/application/pipeline/` passes
- [x] `mypy services/rag-chat/src --config-file mypy.ini` passes
- [x] `python -m pytest services/rag-chat/tests -m "unit" -v` passes
- [x] Domain layer has zero infrastructure imports

#### Regression Guardrails
- Check `tests/unit/pipeline/test_intent_classifier.py` — `_VALID_INTENTS` frozenset is used by the parser; adding GENERAL must not break the existing 7-intent parse path

---

### Wave A-2: ConversationContext + TurnSummary Domain Entities + DB Schema ✅

**Goal**: Define `ConversationContext` and `TurnSummary` in-memory domain entities; add `context_valkey_key` and `summary_valkey_key` nullable columns to the `messages` ORM model + Alembic migration.
**Depends on**: Wave A-1
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-04-07 · 203 tests pass · ruff + mypy clean

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-A-2-01 | Create `ConversationContext` frozen dataclass (PRD §6.5) | impl | `services/rag-chat/src/rag_chat/domain/entities/context.py` | All 8 attributes; invariant `total_token_estimate ≤ 6000`; raises ValueError if violated |
| T-A-2-02 | Create `TurnSummary` frozen dataclass (PRD §6.5) | impl | `services/rag-chat/src/rag_chat/domain/entities/context.py` | 3 attributes: `summary_text`, `entities_referenced`, `intent` |
| T-A-2-03 | Add `context_valkey_key` + `summary_valkey_key` nullable TEXT columns to `MessageModel` | impl | `services/rag-chat/src/rag_chat/infrastructure/db/models/message.py` | Columns nullable, mapped to SQLAlchemy Text, no migration failure on existing rows |
| T-A-2-04 | Alembic migration: add 2 nullable columns to `messages` table | migration | `services/rag-chat/alembic/versions/0002_add_context_valkey_keys.py` | `upgrade()` adds columns; `downgrade()` drops them; no data loss |
| T-A-2-05 | Unit tests: ConversationContext invariant, TurnSummary construction | test | `services/rag-chat/tests/unit/domain/test_context_entities.py` | Token budget enforcement tested; >6000 raises ValueError |

#### Validation Gate
- [x] `ruff check` + `mypy` pass
- [x] Migration file is forward-compatible (new columns have `nullable=True`, no column removals)
- [x] `python -m pytest services/rag-chat/tests -m "unit" -v` passes
- [x] Run DDL alignment test if it exists for this service

---

### Wave A-3: 3-Layer Context Manager (Chunk Cache + Turn Summary + Assembly) ✅

**Goal**: Implement `ContextManager` application service: chunk cache read/write (Valkey), async turn summary generation, and bounded `ConversationContext` assembly.
**Depends on**: Wave A-2
**Estimated effort**: 60–90 minutes
**Status**: **DONE** — 2026-04-07 · 254 tests pass · ruff + mypy clean

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-A-3-01 | Create `ChunkCachePort` Protocol in ports layer | impl | `services/rag-chat/src/rag_chat/application/ports/chunk_cache.py` | `get(key)`, `set(key, value, ttl)` async methods |
| T-A-3-02 | Create `ValkeyChunkCacheAdapter` implementing `ChunkCachePort` | impl | `services/rag-chat/src/rag_chat/infrastructure/cache/valkey_chunk_cache.py` | Reads/writes chunks as JSON; TTL 4h for chunks, 24h for summaries |
| T-A-3-03 | Create `ContextManager` application service with 3-condition cache reuse logic | impl | `services/rag-chat/src/rag_chat/application/pipeline/context_manager.py` | Triple condition: entity_overlap>50%, same intent, query_sim>0.85; assembles ConversationContext ≤6000 tokens |
| T-A-3-04 | Add `generate_turn_summary()` async method (fires post-stream, non-blocking) | impl | `services/rag-chat/src/rag_chat/application/pipeline/context_manager.py` | Summary stored in Valkey `s8:ctx:summary:{thread_id}:{turn_num}` with 24h TTL; async task; errors logged not raised |
| T-A-3-05 | Add S8 Prometheus metrics: chunk cache hits/misses + context token histogram | impl | `services/rag-chat/src/rag_chat/infrastructure/metrics/prometheus.py` | 4 new counters/histograms from PRD §13 |
| T-A-3-06 | Unit tests: cache reuse conditions, context assembly token budget, entity overlap | test | `services/rag-chat/tests/unit/pipeline/test_context_manager.py` | 12+ tests; all 3 cache bypass conditions tested |

#### Validation Gate
- [x] `ruff check` + `mypy` pass
- [x] `python -m pytest services/rag-chat/tests -m "unit" -v` passes (254 tests)
- [x] No blocking I/O in async code path (scan for `socket.`, `requests.`)

---

## Sub-Plan B: S8 RAG/Chat — GENERAL Intent + Internal Briefing Endpoint

### Context
GENERAL intent has special routing (light ANN + LLM general knowledge + follow-up suggestions). The internal briefing endpoint is required by S10 to request AI narrative for digest emails. Both require the prompt modules from Sub-Plan A.

### Pre-Read
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_plan_builder.py`
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`
- `services/rag-chat/src/rag_chat/api/routes/chat.py`
- `services/rag-chat/src/rag_chat/infrastructure/config/settings.py`

---

### Wave B-1: GENERAL Intent Handler + Retrieval Plan Integration

**Goal**: Wire GENERAL intent through the retrieval plan builder and chat orchestrator; add follow-up suggestions to GENERAL responses.
**Depends on**: Wave A-1
**Estimated effort**: 45–60 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-B-1-01 | Update `RetrievalPlanBuilder` to handle GENERAL intent (light ANN, no Cypher, no financial) | impl | `services/rag-chat/src/rag_chat/application/pipeline/retrieval_plan_builder.py` | GENERAL → `use_chunks=True`, others=False; entity_ids from resolved entities if any |
| T-B-1-02 | Update `ChatOrchestrator` to append 2–3 follow-up suggestions for GENERAL responses | impl | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` | Follow-ups appended to LLM output for GENERAL intent only |
| T-B-1-03 | Update intent classifier classification prompt + examples to include GENERAL | impl | `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py` | Classification prompt has GENERAL example; keyword fallback returns GENERAL for ambiguous queries |
| T-B-1-04 | Unit tests: GENERAL retrieval plan, follow-up injection, classifier GENERAL output | test | `services/rag-chat/tests/unit/pipeline/test_general_intent.py` | Tests for entity-present and entity-absent GENERAL paths |

#### Validation Gate
- [ ] `ruff check` + `mypy` pass
- [ ] `python -m pytest services/rag-chat/tests -m "unit" -v` passes

---

### Wave B-2: Internal Briefing Endpoint + Model Config Env Vars

**Goal**: Add `POST /internal/v1/briefings` endpoint with `X-Internal-Token` auth; add `RAG_CHAT_COMPLETION_MODEL` and `RAG_CHAT_COMPLETION_PROVIDER` config fields; EMAIL_DEEP_BRIEF prompt mode.
**Depends on**: Wave A-1
**Estimated effort**: 60–75 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-B-2-01 | Add `completion_provider`, `completion_model`, `internal_service_token` fields to `RagChatSettings` | impl | `services/rag-chat/src/rag_chat/infrastructure/config/settings.py` | Env vars `RAG_CHAT_COMPLETION_PROVIDER`, `RAG_CHAT_COMPLETION_MODEL`, `RAG_CHAT_INTERNAL_SERVICE_TOKEN` |
| T-B-2-02 | Add `EMAIL_DEEP_BRIEF` prompt module to intent_prompts.py (exhaustive, no truncation) | impl | `services/rag-chat/src/rag_chat/application/pipeline/prompts/intent_prompts.py` | Distinct from PORTFOLIO; assumes no follow-up; prompt instructs exhaustive HTML-ready narrative |
| T-B-2-03 | Create `BriefingRequest` + `BriefingResponse` Pydantic schemas (PRD §6.2) | impl | `services/rag-chat/src/rag_chat/api/schemas.py` | All fields from PRD §6.2; portfolio_context typed as dict; market_snapshots as list[dict] |
| T-B-2-04 | Create `GenerateBriefingUseCase` — validates auth, calls LLM with EMAIL_DEEP_BRIEF prompt | impl | `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` | Validates X-Internal-Token via `hmac.compare_digest`; returns narrative + risk_summary + citations |
| T-B-2-05 | Add `POST /internal/v1/briefings` route with 100/day per-user rate limit | impl | `services/rag-chat/src/rag_chat/api/routes/briefings.py`, update `app.py` | 401 for missing/wrong token; 400 for invalid body; 503 if LLM unavailable |
| T-B-2-06 | Unit tests: auth check, briefing use case, rate limit enforcement | test | `services/rag-chat/tests/unit/api/test_briefings.py` | Auth failure = 401; valid token = 200; rate limit = 429 |

#### Validation Gate
- [ ] `ruff check` + `mypy` pass
- [ ] `python -m pytest services/rag-chat/tests -m "unit" -v` passes
- [ ] Security: `hmac.compare_digest` used (not `==`) for token comparison
- [ ] No hardcoded tokens (env var only)

---

## Sub-Plan C: S10 Alert — Email Provider + Preferences API

### Context
S10 needs a provider-agnostic email interface, email_preferences table, email_log table, and GET/PUT API endpoints for user email preferences. This sub-plan is independent of Sub-Plan A/B.

### Pre-Read
- `services/alert/src/alert/config.py`
- `services/alert/src/alert/domain/`
- `services/alert/src/alert/infrastructure/db/models.py`
- `services/alert/src/alert/api/routes.py`
- `docs/BUG_PATTERNS.md`

---

### Wave C-1: Domain + DB Schema (EmailPreference + EmailLog)

**Goal**: Create `EmailPreference` domain entity; Alembic migration for `email_preferences` + `email_log` tables; `EmailProvider` Protocol.
**Depends on**: none
**Estimated effort**: 45–60 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-C-1-01 | Create `EmailPreference` domain entity (PRD §6.5) | impl | `services/alert/src/alert/domain/entities.py` | All attributes; `send_day_of_week` 0–6 invariant; `send_hour_utc` 0–23 invariant |
| T-C-1-02 | Create `EmailProvider` Protocol (PRD §6.5) + `EmailProviderError` exception | impl | `services/alert/src/alert/domain/email_provider.py` | Protocol with `async def send(to, subject, html_body, text_body, from_address) -> str` |
| T-C-1-03 | Add `EmailPreferenceModel` + `EmailLogModel` SQLAlchemy ORM models | impl | `services/alert/src/alert/infrastructure/db/models.py` | Columns match PRD §6.4; indexes: `(tenant_id, weekly_digest_enabled, send_day_of_week)` + `(user_id, sent_at DESC)` |
| T-C-1-04 | Alembic migration: create `email_preferences` + `email_log` tables | migration | `services/alert/alembic/versions/NNNN_add_email_tables.py` | `upgrade()` creates both tables; `downgrade()` drops them; check constraints for day (0–6) and hour (0–23) |
| T-C-1-05 | Unit tests: EmailPreference invariants, EmailProvider Protocol structural check | test | `services/alert/tests/unit/domain/test_email_preference.py` | Invalid day/hour raise ValueError; protocol satisfied by a stub |

#### Validation Gate
- [ ] `ruff check` + `mypy` pass
- [ ] `python -m pytest services/alert/tests -m "unit" -v` passes
- [ ] Migration is forward-compatible
- [ ] Domain layer has zero infrastructure imports

---

### Wave C-2: Email Provider Adapters (Resend + SendGrid + SMTP) + Factory

**Goal**: Implement 3 email provider adapters and a factory function selected by `ALERT_EMAIL_PROVIDER` env var.
**Depends on**: Wave C-1
**Estimated effort**: 60–75 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-C-2-01 | `ResendEmailAdapter` — HTTP call to `api.resend.com/emails` | impl | `services/alert/src/alert/infrastructure/email/resend_adapter.py` | Uses `httpx.AsyncClient`; raises `EmailProviderError` on non-2xx; returns `provider_message_id` |
| T-C-2-02 | `SendGridEmailAdapter` — HTTP call to SendGrid v3 API | impl | `services/alert/src/alert/infrastructure/email/sendgrid_adapter.py` | Same interface; raises `EmailProviderError` on failure |
| T-C-2-03 | `SMTPEmailAdapter` — async SMTP via `aiosmtplib` | impl | `services/alert/src/alert/infrastructure/email/smtp_adapter.py` | Uses `aiosmtplib`; supports Mailhog in dev; returns empty string as provider_message_id |
| T-C-2-04 | `build_email_provider(settings) -> EmailProvider` factory | impl | `services/alert/src/alert/infrastructure/email/__init__.py` | Selects adapter from `ALERT_EMAIL_PROVIDER` env var (`resend`\|`sendgrid`\|`smtp`); raises `ValueError` for unknown |
| T-C-2-05 | Add email config fields to `AlertSettings` | impl | `services/alert/src/alert/config.py` | `email_provider`, `email_from_address`, `resend_api_key`, `sendgrid_api_key`, `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password` |
| T-C-2-06 | Unit tests: ResendEmailAdapter mock, factory selection, SMTP adapter | test | `services/alert/tests/unit/infrastructure/test_email_adapters.py` | Mock httpx responses; factory returns correct type; provider error raised on 4xx/5xx |

#### Validation Gate
- [ ] `ruff check` + `mypy` pass
- [ ] `python -m pytest services/alert/tests -m "unit" -v` passes
- [ ] No API keys or SMTP passwords hardcoded (env vars only)
- [ ] `aiosmtplib` added to `services/alert/pyproject.toml` dependencies

---

### Wave C-3: Email Preferences Repository + API Routes

**Goal**: Implement `EmailPreferenceRepository`, `GetEmailPreferencesUseCase`, `UpdateEmailPreferencesUseCase`, and GET/PUT `/api/v1/email/preferences` + POST `/admin/email/digest/trigger` routes.
**Depends on**: Wave C-1
**Estimated effort**: 60–75 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-C-3-01 | `EmailPreferenceRepository` port + SQLAlchemy adapter | impl | `services/alert/src/alert/application/ports/repositories.py`, `services/alert/src/alert/infrastructure/db/repositories/email_preference.py` | `get_by_user`, `upsert`, `list_scheduled_users(day, hour)` async methods |
| T-C-3-02 | `GetEmailPreferencesUseCase` — returns preferences (creates default if not exists) | impl | `services/alert/src/alert/application/use_cases/email_preferences.py` | Returns 404 replaced by default creation; reads from `ReadOnlyUnitOfWork` (R27) |
| T-C-3-03 | `UpdateEmailPreferencesUseCase` — validates and upserts preferences | impl | `services/alert/src/alert/application/use_cases/email_preferences.py` | Validates user_id ownership; validates day 0–6, hour 0–23; upserts |
| T-C-3-04 | Pydantic schemas: `EmailPreferencesResponse`, `UpdateEmailPreferencesRequest` | impl | `services/alert/src/alert/api/schemas.py` | Match PRD §6.2 field types; email_address validates format |
| T-C-3-05 | API routes: `GET /api/v1/email/preferences`, `PUT /api/v1/email/preferences`, `POST /admin/email/digest/trigger` | impl | `services/alert/src/alert/api/routes.py` | Auth via X-Tenant-ID + X-User-ID; admin route via X-Admin-Token; 400 for invalid day/hour |
| T-C-3-06 | Unit tests for use cases + routes | test | `services/alert/tests/unit/use_cases/test_email_preferences.py`, `tests/unit/api/test_email_routes.py` | Ownership isolation tested; 404 returns default prefs; auth failures return 401 |

#### Validation Gate
- [ ] `ruff check` + `mypy` pass
- [ ] API layer uses only use cases (R25 / IG-LAYER-002)
- [ ] Read use cases use `ReadOnlyUnitOfWork` (R27)
- [ ] `python -m pytest services/alert/tests -m "unit" -v` passes

---

## Sub-Plan D: S10 Alert — Email Scheduler + Digest Flow

### Context
The weekly email digest is S10's main new process: a scheduler that queries email_preferences, orchestrates calls to S1/S3/S8, renders an HTML template, sends the email, logs the result, and produces a Kafka event via outbox.

### Pre-Read
- `services/alert/src/alert/infrastructure/` (existing consumer/outbox patterns)
- `infra/kafka/schemas/` (existing Avro schemas)
- `docs/services/alert.md`

---

### Wave D-1: EmailScheduler Process + S1/S3/S8 Orchestration

**Goal**: Implement `EmailScheduler` background process that reads preferences, calls S1/S3/S8 HTTP clients, and builds the digest data package.
**Depends on**: Wave B-2 (briefing endpoint), Wave C-1 (email_preferences table)
**Estimated effort**: 75–90 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-D-1-01 | `S8BriefingClient` HTTP client — calls `POST /internal/v1/briefings` + add `s8_internal_token` field to `AlertSettings` (env var `ALERT_S8_INTERNAL_TOKEN`) | impl | `services/alert/src/alert/infrastructure/clients/s8_client.py`, `services/alert/src/alert/config.py` | Sets `X-Internal-Token` from `settings.s8_internal_token`; handles 401/503 with `BriefingClientError`; 90s timeout |
| T-D-1-02 | `S3MarketDataClient` — `GET /api/v1/ohlcv/bulk` + `GET /api/v1/fundamentals` | impl | `services/alert/src/alert/infrastructure/clients/s3_client.py` | Returns structured dicts; handles 503 gracefully (returns empty) |
| T-D-1-03 | `EmailScheduler` — queries DB for today's users, orchestrates digest flow per user | impl | `services/alert/src/alert/infrastructure/email/scheduler.py` | Sequential per-user processing; retry 3× on email send with exponential backoff (1s, 2s, 4s); inserts email_log row |
| T-D-1-04 | `EmailScheduler` main entrypoint (process entry) | impl | `services/alert/src/alert/infrastructure/email/scheduler_main.py` | Runs daily via APScheduler at configured day+hour; `asyncio.run()` entrypoint |
| T-D-1-05 | Unit tests: scheduler orchestration with mocked clients, retry logic, log insertion | test | `services/alert/tests/unit/infrastructure/test_email_scheduler.py` | S1 503 → skip user; S8 503 → send partial email; retry backoff tested |

#### Validation Gate
- [ ] `ruff check` + `mypy` pass
- [ ] `python -m pytest services/alert/tests -m "unit" -v` passes
- [ ] No synchronous blocking calls in async scheduler loop

---

### Wave D-2: HTML Email Template + Avro Schema + Outbox Event

**Goal**: Create HTML email template renderer; add `alert.email.sent.v1` Avro schema + outbox event production.
**Depends on**: Wave D-1
**Estimated effort**: 45–60 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-D-2-01 | `alert.email.sent.v1` Avro schema | schema | `infra/kafka/schemas/alert.email.sent.v1.avsc` | All fields from PRD §6.3; forward-compatible; `provider_message_id` nullable union |
| T-D-2-02 | `EmailSentEvent` contract model + outbox production in scheduler | impl | `services/alert/src/alert/infrastructure/messaging/schemas/email_sent.py`, update `scheduler.py` | Outbox pattern (same transaction as email_log INSERT); topic `alert.email.sent.v1` |
| T-D-2-03 | HTML email template renderer (Jinja2 or f-string; no external deps preferred) | impl | `services/alert/src/alert/infrastructure/email/template.py` | Sections: Risk Overview, Portfolio Positions, Recent News, Market Fundamentals; valid HTML; plaintext fallback |
| T-D-2-04 | Update `services/alert/pyproject.toml` if Jinja2 added | config | `services/alert/pyproject.toml` | Dependency pinned |
| T-D-2-05 | Unit tests: template rendering with sample data, Avro schema validation | test | `services/alert/tests/unit/infrastructure/test_email_template.py` | Template renders all 4 sections; missing OHLCV section still renders; no XSS from portfolio data |
| T-D-2-06 | Contract test: alert.email.sent.v1 schema alignment | test | `services/alert/tests/contract/test_email_sent_schema.py` | Schema validates with fastavro; forward-compatible |

#### Validation Gate
- [ ] `ruff check` + `mypy` pass
- [ ] Avro schema validates with fastavro
- [ ] `python -m pytest services/alert/tests -m "unit" -v` passes
- [ ] Outbox pattern used (not dual-write)
- [ ] XSS prevention: portfolio data XML-wrapped, never injected as raw HTML

---

## Sub-Plan E: S9 API Gateway + S1 Internal Endpoint

### Context
S9 needs to proxy `/api/v1/email/preferences` to S10. S1 needs a new internal endpoint `GET /internal/v1/users/{user_id}` returning user email for digest delivery.

### Pre-Read
- `services/api-gateway/src/` (existing gateway routing patterns)
- `services/portfolio/src/` (S1 internal endpoint patterns)

---

### Wave E-1: S9 Email Preferences Route + S1 Internal User Endpoint

**Goal**: Add email preferences proxy route to S9; add `GET /internal/v1/users/{user_id}` to S1 with X-Internal-Token auth.
**Depends on**: Wave C-3 (email prefs API exists)
**Estimated effort**: 45–60 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-E-1-01 | S9: Add proxy route `GET+PUT /api/v1/email/preferences` → S10 `:8010` | impl | `services/api-gateway/src/` (relevant router file) | Passes X-Tenant-ID + X-User-ID headers; handles S10 4xx/5xx transparently |
| T-E-1-02 | S1: `GET /internal/v1/users/{user_id}` endpoint — returns user email | impl | `services/portfolio/src/portfolio/api/routes/internal.py` (or new file) | Validates `X-Internal-Token` via `hmac.compare_digest`; returns user_id, tenant_id, email_address, username, created_at; 404 if not found; 401 if bad token |
| T-E-1-03 | S1: config field `PORTFOLIO_S10_INTERNAL_TOKEN` (validated via `ALERT_S1_INTERNAL_TOKEN` in S10) | impl | `services/portfolio/src/portfolio/config.py` | Env var reads from `PORTFOLIO_S10_INTERNAL_TOKEN`; validated against request header via hmac |
| T-E-1-04 | Unit tests: S9 proxy route, S1 internal endpoint auth + 404 + response shape | test | relevant test files | Auth failure = 401; missing user = 404; correct response schema |

#### Validation Gate
- [ ] `ruff check` + `mypy` pass
- [ ] `python -m pytest` on affected services passes
- [ ] Token comparison uses `hmac.compare_digest` (not `==`)

---

## Cross-Cutting Concerns

### Contract Changes
| Type | Item | Compatibility | Test |
|------|------|--------------|------|
| Avro | `alert.email.sent.v1.avsc` | New topic — no existing consumers | `services/alert/tests/contract/test_email_sent_schema.py` |
| REST | `POST /internal/v1/briefings` (S8) | New endpoint | Unit test with auth |
| REST | `GET+PUT /api/v1/email/preferences` (S10) | New endpoints | Unit + integration test |
| REST | `GET /internal/v1/users/{user_id}` (S1) | New endpoint | Unit test |
| DB | `messages.context_valkey_key`, `messages.summary_valkey_key` | Backward compatible (nullable) | Migration upgrade/downgrade |
| DB | `email_preferences`, `email_log` tables | New tables | Migration |

### Migrations
| Service | Migration | Description | Order |
|---------|-----------|-------------|-------|
| rag-chat (S8) | `0002_add_context_valkey_keys.py` | Adds 2 nullable columns to `messages` | After Wave A-2 |
| alert (S10) | `NNNN_add_email_tables.py` | Creates `email_preferences` + `email_log` | After Wave C-1 |

### Configuration
| Service | Env Var | Default | Purpose |
|---------|---------|---------|---------|
| S8 | `RAG_CHAT_COMPLETION_PROVIDER` | `deepinfra` | LLM provider selection |
| S8 | `RAG_CHAT_COMPLETION_MODEL` | `deepseek-r1-distill-qwen-32b` | LLM model ID |
| S8 | `RAG_CHAT_INTERNAL_SERVICE_TOKEN` | required | Briefing endpoint auth |
| S10 | `ALERT_EMAIL_PROVIDER` | `resend` | Email adapter selection |
| S10 | `ALERT_EMAIL_FROM_ADDRESS` | required | Sender address |
| S10 | `ALERT_RESEND_API_KEY` | — | Resend.com API key |
| S10 | `ALERT_SENDGRID_API_KEY` | — | SendGrid API key |
| S10 | `ALERT_SMTP_HOST` | `localhost` | SMTP relay host |
| S10 | `ALERT_SMTP_PORT` | `587` | SMTP port |
| S10 | `ALERT_S8_BASE_URL` | `http://rag-chat:8008` | S8 briefing endpoint URL |
| S10 | `ALERT_S8_INTERNAL_TOKEN` | required | Token S10 sends in X-Internal-Token header to S8 briefing endpoint (must match `RAG_CHAT_INTERNAL_SERVICE_TOKEN`) |
| S10 | `ALERT_S1_INTERNAL_TOKEN` | required | Token for S1 user endpoint |
| S10 | `ALERT_SMTP_USER` | — | SMTP auth username (optional for unauthenticated relays) |
| S10 | `ALERT_SMTP_PASSWORD` | — | SMTP auth password |
| S1 | `PORTFOLIO_S10_INTERNAL_TOKEN` | required | Validates S10 requests to S1 |

### Documentation Updates
| Document | Update Required |
|----------|----------------|
| `docs/services/alert.md` | New tables, email provider, scheduler process, API endpoints |
| `docs/services/rag-chat.md` | GENERAL intent, context management, briefing endpoint, prompt modules |
| `docs/services/portfolio.md` | New internal endpoint |
| `services/alert/.claude-context.md` | New entities, endpoints, email scheduler process |
| `services/rag-chat/.claude-context.md` | GENERAL intent, context manager, briefing endpoint |

---

## Risk Assessment

### Critical Path
Sub-Plan A Wave A-1 → Wave B-2 (briefing endpoint) → Wave D-1 (scheduler orchestration) — this chain is the longest dependency chain and must complete before digest flow can be integrated.

### Highest Risk
| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Turn summary async task crashes before write | Medium | Next turn loses one compressed turn (graceful degradation) | Log exception; don't propagate; test crash path |
| Email provider API rate limit / downtime | Medium | Users miss weekly digest | Retry 3× with exponential backoff; log status=failed; skip user rather than fail batch |
| Context token budget exceeded for long conversations | Low | LLM context overflow | Hard cap at 6000 tokens enforced in ConversationContext invariant |
| SMTP adapter blocking event loop | Medium | Request timeouts | Use `aiosmtplib` (async native) not stdlib `smtplib` |

### Rollback Strategy
- S8 changes are additive (new prompt modules, new routes, new DB columns are nullable)
- S10 email tables: `alembic downgrade -1` drops tables
- Avro schema: new topic, no consumers to migrate
- S1 endpoint: additive (new route), rollback removes it

---

## Tracking

### Plan Status
| Sub-Plan | Status | Waves Done | Waves Total |
|----------|--------|-----------|-------------|
| A: S8 Intent Prompts + Context Mgmt | in-progress | 2 | 3 |
| B: S8 GENERAL Intent + Briefing | pending | 0 | 2 |
| C: S10 Email Provider + Prefs | pending | 0 | 3 |
| D: S10 Scheduler + Digest | pending | 0 | 2 |
| E: S9 Gateway + S1 Endpoint | pending | 0 | 1 |

### Wave Status
| Wave | Status | Tasks Done | Tasks Total | Blockers |
|------|--------|-----------|-------------|----------|
| A-1 | done | 5 | 5 | none |
| A-2 | done | 5 | 5 | none |
| A-3 | pending | 0 | 6 | A-2 |
| B-1 | pending | 0 | 4 | A-1 |
| B-2 | pending | 0 | 6 | A-1 |
| C-1 | pending | 0 | 5 | none |
| C-2 | pending | 0 | 6 | C-1 |
| C-3 | pending | 0 | 6 | C-1 |
| D-1 | pending | 0 | 5 | B-2, C-1 |
| D-2 | pending | 0 | 6 | D-1 |
| E-1 | pending | 0 | 4 | C-3 |
