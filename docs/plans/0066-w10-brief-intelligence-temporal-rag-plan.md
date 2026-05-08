# PLAN-0066 — W10 Brief Intelligence + Temporal RAG

> **PRD**: PRD-0034 §3 FR-T1-1 extensions + dai-backend TTYD investigation 2026-05-03
> **Status**: complete
> **Created**: 2026-05-03
> **Last revised**: 2026-05-08 (QA complete — all 8 waves done; R25 fix: BriefFeedbackPort + BriefFeedbackRepository extracted; 765 rag-chat unit + 656 arch PASS)
> **Owner agent**: Staff engineer / TPM
> **Estimated effort**: ~5 dev-days (8 waves, 28 tasks)
> **Critical path**: Wave A → Wave B → Wave C ∥ Wave D ∥ Wave E → Wave F (frontend) → Wave G → Wave H
> **Hard dependency**: PLAN-0062-W4 all waves must ship first; PLAN-0077 (chat-pipeline rename + decomposition) must land before Wave H.

---

## §0 Revision Log

**2026-05-07 — long-term consistency review** (post thesis-to-product pivot):

- **C-1 (class name)**: This plan refers to `ChatOrchestratorUseCase`. Code today has `ChatOrchestrator` (no suffix). PLAN-0077 renames + decomposes the monolithic `execute_streaming` into composable steps before Wave H starts. Treat every `ChatOrchestratorUseCase` reference as the post-PLAN-0077 class name.
- **I-4 (brief-implicit seed migration)**: Wave D Sub-Plan B introduces `RetrievalOrchestrator._fetch_brief_seed`. PLAN-0067 W11-3 will delete `RetrievalOrchestrator`. Wave D still ships the method as planned; **PLAN-0067 W11-3 must port the brief-seed logic** to one of: (a) system-prompt prefix injection, (b) auto-call of a `get_morning_brief` tool when same-day brief exists. This handoff is documented in PLAN-0067 §0.
- **A-1 (no fallback path)**: Wave H originally added `_tool_use_path` *alongside* the classical pipeline. PLAN-0067 hard-deletes the classical pipeline; Wave H is now framed as "establishes the path that becomes the only path." No feature flag retained.

**2026-05-07 — BP-405 name verification + architecture compliance pass**:

- **N-1 (uuid_generate_v7 DB default)**: `T-W10-A-01` SQL DDL shows `DEFAULT uuid_generate_v7()`. The `uuid_generate_v7()` PostgreSQL extension is NOT guaranteed to be installed in all rag_db environments. The established pattern in this repo is **app-side ID generation** via `new_uuid7()` from `libs/common`. The migration MUST NOT rely on a DB-level `uuid_generate_v7()` default. IDs must be generated in the Python ORM models, matching the pattern in `create_thread.py` and `persist_chat.py`. DDL corrected in T-W10-A-01 below.
- **N-2 (S3 router file)**: `T-W10-G-01` says to modify `services/market-data/src/market_data/api/routers/market.py`. All OHLCV routes live in `routers/ohlcv.py`, not `market.py`. Corrected in T-W10-G-01.
- **N-3 (OHLCV endpoint URL conflict)**: S3 already has `GET /api/v1/ohlcv/{instrument_id}` (bars with `start`/`end` date params) and `GET /api/v1/ohlcv/{instrument_id}/range` (returns min/max date range metadata). The plan's proposed `GET /api/v1/instruments/{id}/ohlcv` uses a different URL scheme (instruments-first). The new endpoint must use the `ohlcv/` prefix to stay consistent with existing routes. Corrected to `GET /api/v1/ohlcv/{instrument_id}/bars` in T-W10-G-01.
- **N-4 (SSEEmitter location)**: `T-W10-H-04` references `services/rag-chat/src/rag_chat/infrastructure/streaming/sse_emitter.py`. SSEEmitter actually lives in `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py`. Corrected.
- **N-5 (wiring/dependencies path)**: `T-W10-H-03` references `services/rag-chat/src/rag_chat/infrastructure/wiring/dependencies.py`. No `wiring/` subdirectory exists. The DI file is `services/rag-chat/src/rag_chat/api/dependencies.py`. Corrected.
- **N-6 (ChatOrchestratorUseCase method name)**: `T-W10-H-03` refers to `handle()` method. Post-PLAN-0077, the methods are `execute_streaming()` and `execute_sync()`. Corrected.
- **N-7 (RetrievedItem field `content` vs `text`)**: `T-W10-H-02` uses `RetrievedItem(content=...)`. The actual field is `text` (see `domain/entities/chat.py:139`). Corrected.
- **N-8 (libs/tools does not exist)**: `T-W10-H-01` creates `libs/tools/` — this lib does NOT exist yet. Tagged as `(NEW — created in Wave H)`.
- **N-9 (R-012 reference)**: `T-W10-H-02` cites `R-012` for structlog requirement. No such rule number. The rule is R-14 (sanitize logs) + the structlog-only convention documented in STANDARDS.md §5. Corrected to `(structlog only — STANDARDS.md §5)`.
- **N-10 (fundamentals history table)**: `T-W10-G-02` references a `fundamentals_records` table. S3 actually stores fundamentals in per-type tables (income_statement, balance_sheet, earnings_history, etc.). The use case must use the `earnings-history` endpoint (`GET /api/v1/fundamentals/{id}/earnings`) as the quarterly history source, not a non-existent `fundamentals_records` table. Corrected in T-W10-G-02.
- **N-11 (S3Port.get_ohlcv_range URL)**: `T-W10-G-03` S3Client calls `GET /api/v1/instruments/{id}/ohlcv`. After N-3 fix, the correct URL is `GET /api/v1/ohlcv/{id}/bars`. Corrected.
- **N-12 (proxy line numbers stale)**: Wave E and Wave B say "proxy.py lines 1660–1700". The file is 3242 lines; briefing proxy routes are at lines 1950–1990. References updated to "lines 1950–1990".

---

## 1. Scope

PLAN-0062-W4 (Structured AI Brief) establishes the schema and rendering infrastructure. This plan layers six product enhancements on top of it:

1. **Brief persistence** — store every generated brief in PostgreSQL so the system has a history to diff, seed, and archive. Currently all briefs are Valkey-cached with a 24h TTL; after expiry they are gone forever.
2. **Brief diff** — compare today's brief against yesterday's and surface a "What's new" badge on the morning brief card.
3. **Chat seeding** — a "Discuss in chat" button on the morning brief opens a chat thread pre-seeded with the brief's citations as priority RAG context.
4. **Brief-implicit RAG seed** — when a user chats on the same calendar day they generated a brief, the brief's citations are automatically injected as high-trust retrieval items, improving answer quality without requiring explicit seeding.
5. **Inline feedback** — per-bullet thumbs up/down and a brief-level rating (1–5 stars) stored in `brief_feedback` table; creates a future fine-tuning dataset.
6. **Alert creation from brief** — entity names in brief bullets carry a hover context menu with "Create alert for {ENTITY}" that opens the alert drawer pre-filled with entity_id + context from the bullet.

Plus a separate track from the **dai-backend TTYD investigation**:

7. **Temporal RAG via tool-use loop** — the current RAG has NO access to OHLCV time-series or fundamentals history; it can only retrieve the latest snapshot. This track adds S3 endpoints for OHLCV range and quarterly fundamentals history (Wave G), then exposes them as LLM-callable tools via a `ToolRegistry` + `ToolExecutor` (Wave H). The LLM sees a `capability_manifest.yaml`-derived tool catalog in its system prompt and emits typed `tool_use` blocks at generation time — no pre-classification step, no brittle `TemporalParamsExtractor`. This is the Option B (tool-use) architecture: the LLM decides at generation time whether to call `get_price_history` or `get_fundamentals_history`, passing ticker + date range as typed arguments. The existing intent classification + parallel retrieval pipeline is untouched and continues to handle classical RAG queries. PLAN-0067 will extend the manifest to expose all retrieval sources (chunks, relations, graph, claims, events) as tools, fully replacing the intent classifier.

**Out of scope**:
- Full NL→SQL (TTYD-style) over TimescaleDB — design notes in §2.7 below; deferred to a future ADR.
- Brief audio/TTS.
- Brief archive UI (history page) — only the API and data model; the UI can be a future wave.
- Brief customisation preferences (section weighting) — future.

---

## 2. Investigation Findings — Temporal RAG + dai-backend TTYD

### 2.1 Current RAG temporal capability

The retrieval orchestrator (`retrieval_orchestrator.py`) supports:
- **Chunks** (`_fetch_chunks`): `date_from`/`date_to` filtering already implemented via `ChunkSearchRequest.date_from/to`. Text-indexed documents (news, SEC filings) are **fully timeframe-aware today**.
- **Claims** (`_fetch_claims`): `date_from`/`date_to` in S7 API. Works.
- **Events** (`_fetch_events`): same. Works.
- **Financial** (`_fetch_financial`): calls `get_fundamentals_highlights` (point-in-time snapshot), `get_earnings` (flat blob), `get_quote` (current price). **No OHLCV history. No quarterly fundamentals history. No date filtering.**

**Conclusion**: The user's observation is correct. For text/news queries, timeframes already work. For structured financial data (OHLCV bars, quarterly revenue/EPS) the RAG is blind — it has a single snapshot per ticker with no way to ask "show me the last 3 months."

### 2.2 What the dai-backend TTYD system does

The `dai-backend` (`services/dai-backend/` in the worldview repo) is a production NL→SQL system built for an enterprise workforce analytics platform (Dashboards AI / Velora). Its pipeline:

1. **MDL (Model Definition Language)**: semantic schema metadata (table descriptions, column meanings, business context) stored in Qdrant.
2. **Schema retrieval**: embed the user query → Qdrant ANN search → top-k relevant tables.
3. **SQL generation**: GPT-4 generates SQL from question + retrieved schema context.
4. **3-level SQL validation**: sqlglot syntax → LocalTrinoValidator schema → NATS dry-run execution.
5. **Auto-correction**: on validation failure, ask GPT-4 to fix the SQL (1 retry).
6. **SQL execution**: NATS → Foundation platform → Trino.
7. **Answer generation**: GPT-4 generates a natural-language answer from the query result set.

This is the right long-term architecture for Worldview's structured data layer. It would enable queries like "Compare AAPL and MSFT revenue CAGR over the last 8 quarters" against TimescaleDB directly.

### 2.3 Why full TTYD integration is deferred (thesis MVP)

| Concern | Detail |
|---------|--------|
| **Complexity** | Requires MDL generation for S3's TimescaleDB tables, Qdrant schema collection, SQL validation against S3's DB, SQL execution proxy in S3 or S8 |
| **Security** | NL→SQL introduces SQL injection surface even with schema restriction; needs RULES.md R15-class validation |
| **Trino vs. PostgreSQL** | dai-backend targets Trino; Worldview uses TimescaleDB + PostgreSQL. SQL dialect differences (Trino's `INTERVAL` handling vs. PostgreSQL `INTERVAL`, `TIMESTAMPTZ` typing). |
| **Cost** | SQL generation + validation requires 3–4 LLM calls per query. At $0.14/1k tokens (DeepSeek-V4-Flash), cost is acceptable but adds latency. |
| **Thesis scope** | Parameterized endpoint dispatch covers 80% of the value at 10% of the complexity. |

**Decision**: Wave G adds two S3 endpoints for OHLCV range and fundamentals history. Wave H exposes them as LLM-callable tools via the Option B tool-use architecture — no separate intent classification step, no `TemporalParamsExtractor`. The LLM decides at generation time by emitting `tool_use` blocks. Full NL→SQL (TTYD path) is captured as an ADR candidate for a post-thesis milestone.

### 2.4 MVP temporal query approach (Waves G + H) — Option B tool-use

```
User: "What was AAPL's price trend over the last 3 months?"
          ↓
   ChatOrchestratorUseCase
   ├── (Path 1, unchanged) IntentClassifier → RetrievalPlanBuilder → ParallelOrchestrator
   │   → retrieved chunks / relations / claims injected as context
   └── (Path 2, new) system prompt includes capability manifest:
       tool: get_price_history(ticker, from_date, to_date, interval)
       tool: get_fundamentals_history(ticker, periods)
          ↓
   LLM generation — emits tool_use block:
   {"type": "tool_use", "name": "get_price_history",
    "input": {"ticker": "AAPL", "from_date": "2026-02-03", "to_date": "2026-05-03", "interval": "week"}}
          ↓
   SSE event: {"type": "tool_call", "tool": "get_price_history", "status": "running"}
   → UI shows: "Fetching AAPL price history..."
          ↓
   ToolExecutor.execute(tool_call)
   → S3Port.get_ohlcv_range(ticker="AAPL", from_date="2026-02-03", to_date="2026-05-03", interval="week")
   → S3 GET /api/v1/ohlcv/bars?symbol=AAPL&from_date=...&to_date=...&interval=week
   → S3 resolves AAPL → instrument_id internally (single round-trip)
   → formats as text table RetrievedItem
          ↓
   LLM continues with tool result injected
   → answers with actual price data, fully grounded in citations
```

**Key advantages over Option A (TemporalParamsExtractor)**:
- LLM extracts parameters natively — no separate mini-LLM call, lower latency
- Multi-tool in one turn: LLM can call `get_price_history` + `get_fundamentals_history` simultaneously
- No `QueryIntent.TEMPORAL_DATA` enum value needed — intent classification is not on the critical path
- Lays the groundwork for PLAN-0067 (all retrieval sources as tools)

---

## 3. Codebase State Verification

Read 2026-05-03.

| PRD / Feature Reference | Type | Service | Current state (from code) | Expected state | Delta |
|---|---|---|---|---|---|
| `user_briefs` table | DB | S8 | does not exist | `(id, user_id, tenant_id, type, generated_at, headline, lead, sections_json, confidence, citations_json)` | new Alembic migration 0004 |
| `brief_feedback` table | DB | S8 | does not exist | `(id, brief_id, user_id, scope: "brief"|"bullet", section_idx, bullet_idx, reaction, created_at)` | same migration 0004 |
| S8 Alembic versions | migration | S8 `alembic/versions/` | 3 versions: 0001, 0002, 0003 | add 0004 | new file |
| `generate_briefing.py` | use case | S8 | no persistence after LLM generation | persist to DB after generation | add persist hook |
| `GET /v1/briefings/morning/history` | endpoint | S8+S9 | does not exist | paginated list of `UserBrief` records | new route + proxy |
| `GET /v1/briefings/morning/diff` | endpoint | S8+S9 | does not exist | diff of today vs yesterday | new route + proxy |
| `POST /v1/briefings/feedback/bullet` | endpoint | S8+S9 | does not exist | create bullet feedback | new route + proxy |
| `POST /v1/briefings/feedback/brief` | endpoint | S8+S9 | does not exist | create brief feedback | new route + proxy |
| `POST /v1/briefings/chat/discuss` | endpoint | S8+S9 | does not exist | create chat thread seeded with brief context | new route + proxy |
| `ThreadModel.seed_brief_id` | column | S8 | does not exist | `UUID | NULL` FK to `user_briefs.id` | Alembic 0005 in Wave D |
| `RetrievalOrchestrator._fetch_brief_seed` | method | S8 | does not exist | injects brief citations as RetrievedItems | new method |
| `S3Port.get_ohlcv_range` | port method | S8 | does not exist | kw-only: `(*, from_date, to_date, interval, instrument_id=None, ticker=None, isin=None) -> list[dict]` — at least one identifier required | extend port |
| `S3Port.get_fundamentals_history` | port method | S8 | does not exist | kw-only: `(*, periods=8, instrument_id=None, ticker=None, isin=None) -> list[dict]` — at least one identifier required | extend port |
| `S3Client.get_ohlcv_range` | adapter | S8 | does not exist | calls `GET /api/v1/ohlcv/bars` with whichever identifier is set (priority: instrument_id > isin > ticker) | new method |
| `S3Client.get_fundamentals_history` | adapter | S8 | does not exist | calls `GET /api/v1/fundamentals/history` with whichever identifier is set | new method |
| `GET /api/v1/ohlcv/bars` | endpoint | S3 | does not exist (literal route; `/ohlcv/{id}` + `/range` exist but no interval resampling or multi-identifier support) | accepts `instrument_id`, `symbol`, `isin` query params (at least one); returns bars with interval resampling | new literal route in `routers/ohlcv.py` registered before `/{instrument_id}` catch-all |
| `GET /api/v1/fundamentals/history` | endpoint | S3 | does not exist | accepts `instrument_id`, `symbol`, `isin`; returns quarterly earnings_history records (N-10 — not fundamentals_records table) | new literal route in `routers/fundamentals.py` |
| `libs/tools/capability_manifest.yaml` | config | libs | does not exist | YAML tool catalog with 2 temporal tools | new file (Wave H) |
| `ToolRegistry` | class | libs | does not exist | maps tool names to `ToolSpec` (schema + source_type; trust_weight removed per PLAN-0067 §0 A-2) | new module (Wave H) |
| `ToolExecutor` | class | S8 | does not exist | executes `tool_use` blocks, calls S3Port methods, returns `RetrievedItem` | new (Wave H) |
| `ChatOrchestratorUseCase` | use case | S8 | no tool-use loop | include manifest in system prompt; run multi-turn tool loop after initial retrieval | modify (Wave H) |
| `MorningBriefCard.tsx` | frontend | worldview-web | no diff badge, no feedback, no "Discuss" button, no alert creation | all 4 added | Wave F |

**Deltas requiring migrations**:
- S8 Alembic 0004: `user_briefs` + `brief_feedback` tables
- S8 Alembic 0005: `threads.seed_brief_id` nullable FK column

**No Kafka / Avro / topic changes** — this plan is pure HTTP + PostgreSQL + frontend.

---

## 4. Wave Decomposition

8 waves. Each wave leaves the codebase green. Total ≈26 tasks.

| Wave | Title | Layer | Effort | Depends on |
|---|---|---|---|---|
| A | S8 DB schema (brief persistence tables) | DB migration + ORM | 60 min | PLAN-0062-W4 Wave A |
| B | S8 brief archive (repository + persistence hook + history endpoint) | application + API | 75 min | A |
| C | S8 brief diff + S8 brief feedback backend | application + API | 75 min | B |
| D | S8 chat seeding + implicit RAG seed | application | 75 min | B |
| E | S8 alert pre-fill endpoint + S9 proxies for all new routes | API + gateway | 60 min | C, D |
| F | Frontend: diff badge + chat seeding button + feedback UI + alert creation | UI | 90 min | E, PLAN-0062-W4 Wave E |
| G | S3 temporal endpoints (OHLCV + fundamentals history; accept UUID/ticker/ISIN) | S3 API + S8 port | 90 min | none (parallel-safe with A–F) |
| H | Temporal RAG integration (intent + extractor + orchestrator) | S8 application | 90 min | G |

---

## 5. Cross-Cutting Concerns

- **No Avro / Kafka changes** — all new communication is HTTP.
- **DB ownership respected** — S8 adds tables only to its own PostgreSQL. S3 adds routes to its own DB. R7 compliant.
- **ReadOnlyUoW** — `GET /v1/briefings/morning/history` and `GET /v1/briefings/morning/diff` use `ReadUoWDep`. All POST/feedback endpoints use `UoWDep`.
- **R22 independent processes** — no new background processes; all new logic is in-request or in use cases.
- **R10 UUIDv7** — all new entity IDs use `new_uuid7()` from `libs/common` (app-side generation — do NOT use `uuid_generate_v7()` DB default; see N-1 in §0 revision log). Pattern: `from common.ids import new_uuid7  # type: ignore[import-untyped]` in the use case / repository that creates the entity.
- **Configuration**: 1 new env var: `S3_OHLCV_MAX_DAYS=365` (cap on date range for OHLCV to prevent oversized responses; default 365).
- **Documentation**: `docs/services/rag-chat.md` (new endpoints), `docs/services/market-data.md` (OHLCV range + history endpoints).

---

## 6. Waves

---

### Wave A: S8 DB Schema — Brief Persistence Tables

**Goal**: Add `user_briefs` and `brief_feedback` ORM models and an Alembic migration so subsequent waves can write briefs and feedback.
**Depends on**: PLAN-0062-W4 Wave A (requires `BriefBullet`/`BriefCitation` to exist for serialisation shape, though this wave stores JSON blobs)
**Estimated effort**: 60 min
**Architecture layer**: infrastructure / DB schema

#### Pre-read
- `services/rag-chat/alembic/versions/0003_create_llm_usage_log.py` — pattern for the next migration
- `services/rag-chat/src/rag_chat/infrastructure/db/models/thread.py` — ORM model pattern (`Base`, `mapped_column`, UUIDv7)
- `libs/common/src/common/uuid7.py` — `uuid7()` helper

#### Tasks

##### T-W10-A-01: Alembic migration 0004 — `user_briefs` + `brief_feedback` tables
**Type**: schema
**depends_on**: none
**blocks**: T-W10-A-02
**Target files**:
- `services/rag-chat/alembic/versions/0004_add_user_briefs_and_feedback.py` (new)

**What to build**:
Single Alembic revision that creates both tables in one transaction. `user_briefs` is the brief archive; `brief_feedback` records per-bullet and per-brief reactions.

> **ARCH NOTE (N-1)**: IDs are NOT generated at the DB level. Do NOT use `DEFAULT uuid_generate_v7()` in DDL — that PostgreSQL extension is not guaranteed to be installed. IDs must be generated app-side in the ORM model (or use case) via `new_uuid7()` from `libs/common`, matching the pattern in `create_thread.py`. The migration uses `sa.Column("id", PgUUID(as_uuid=True), primary_key=True)` with NO server_default. The ORM model sets the default using `mapped_column(default=...)` (see `ThreadModel` as the canonical example).

> **ARCH NOTE (R10)**: In the ORM model (T-W10-A-02), the `id` column default must be: `id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid7)` — never `default=uuid4()` or a DB-level call.

> **ARCH NOTE (R11)**: `generated_at` and `created_at` must use UTC. In use cases: `from common.time import utc_now` → `now = utc_now()`. Never `datetime.utcnow()` (naive). Column type: `DateTime(timezone=True)`.

**Schema**:

`user_briefs`:
```sql
-- NOTE: No DEFAULT for id — generated app-side via new_uuid7() (R10, N-1)
CREATE TABLE user_briefs (
    id              UUID NOT NULL PRIMARY KEY,
    user_id         UUID NOT NULL,
    tenant_id       UUID NOT NULL,
    brief_type      VARCHAR(20) NOT NULL,          -- 'morning' | 'instrument'
    entity_id       UUID,                           -- NULL for morning briefs
    generated_at    TIMESTAMPTZ NOT NULL,
    headline        TEXT NOT NULL,
    lead            TEXT,
    sections_json   JSONB NOT NULL DEFAULT '[]',   -- serialised list[BriefSection] (with BriefBullet + BriefCitation)
    citations_json  JSONB NOT NULL DEFAULT '[]',   -- serialised top-level citations[]
    confidence      FLOAT NOT NULL DEFAULT 1.0,
    source_version  VARCHAR(10) NOT NULL DEFAULT 'v2'  -- cache key version stamp
);
CREATE INDEX ix_user_briefs_user_date ON user_briefs (user_id, generated_at DESC);
CREATE INDEX ix_user_briefs_tenant_date ON user_briefs (tenant_id, generated_at DESC);
```

`brief_feedback`:
```sql
-- NOTE: No DEFAULT for id — generated app-side via new_uuid7() (R10, N-1)
CREATE TABLE brief_feedback (
    id              UUID NOT NULL PRIMARY KEY,
    brief_id        UUID NOT NULL REFERENCES user_briefs(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,
    scope           VARCHAR(10) NOT NULL,   -- 'brief' | 'bullet'
    section_idx     SMALLINT,               -- NULL when scope='brief'
    bullet_idx      SMALLINT,               -- NULL when scope='brief'
    reaction        VARCHAR(20) NOT NULL,   -- 'helpful' | 'unhelpful' | '1'..'5' (stars)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_brief_feedback_brief_id ON brief_feedback (brief_id);
CREATE INDEX ix_brief_feedback_user ON brief_feedback (user_id, created_at DESC);
```

**Acceptance criteria**:
- [ ] `alembic upgrade head` applies cleanly against a fresh DB
- [ ] `alembic downgrade -1` reverts both tables cleanly
- [ ] NO `uuid_generate_v7()` DB function used — IDs are app-generated (N-1)
- [ ] Timestamps are `TIMESTAMPTZ` (R11)

---

##### T-W10-A-02: ORM models `UserBriefModel` + `BriefFeedbackModel`
**Type**: impl
**depends_on**: T-W10-A-01
**blocks**: T-W10-B-01
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/db/models/user_brief.py` (new)
- `services/rag-chat/src/rag_chat/infrastructure/db/models/__init__.py` (modify: add to `__all__`)

**What to build**:
SQLAlchemy `Mapped` ORM models for both tables. `UserBriefModel` uses `JSONB` columns for `sections_json` and `citations_json` (stored as Python `list[dict]` — no custom type needed, SQLAlchemy handles JSON ↔ Python dict natively).

**Key attributes — `UserBriefModel`**:
- `id: Mapped[UUID]` — primary key, `mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid7)` — app-side UUIDv7 (R10, N-1). Import: `from common.ids import new_uuid7  # type: ignore[import-untyped]`
- `user_id: Mapped[UUID]`
- `tenant_id: Mapped[UUID]`
- `brief_type: Mapped[str]` — `"morning"` | `"instrument"`
- `entity_id: Mapped[UUID | None]`
- `generated_at: Mapped[datetime]` — `DateTime(timezone=True)` (R11 — UTC-aware, never naive)
- `headline: Mapped[str]`
- `lead: Mapped[str | None]`
- `sections_json: Mapped[list]` — `JSONB`, default `[]`
- `citations_json: Mapped[list]` — `JSONB`, default `[]`
- `confidence: Mapped[float]`
- `source_version: Mapped[str]` — `"v2"`

**Key attributes — `BriefFeedbackModel`**:
- `id: Mapped[UUID]` — `mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid7)` — app-side UUIDv7 (R10, N-1)
- `brief_id: Mapped[UUID]` — FK to `user_briefs.id`
- `user_id: Mapped[UUID]`
- `scope: Mapped[str]` — `"brief"` | `"bullet"`
- `section_idx: Mapped[int | None]`
- `bullet_idx: Mapped[int | None]`
- `reaction: Mapped[str]`
- `created_at: Mapped[datetime]` — `DateTime(timezone=True)` (R11 — UTC-aware). Set in use case via `utc_now()` from `libs/common`.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_user_brief_model_defaults` | `UserBriefModel` created with minimal fields has `sections_json=[]`, `citations_json=[]`, `confidence=1.0` | unit |
| `test_brief_feedback_requires_brief_id` | `BriefFeedbackModel` without `brief_id` raises `IntegrityError` | unit |
| `test_user_brief_roundtrip_sections_json` | JSONB column stores and retrieves nested list of dicts unchanged | unit |

Minimum: 3 new tests.

**Downstream test impact**: none — new files only.

**Acceptance criteria**:
- [ ] Both models importable from `rag_chat.infrastructure.db.models`
- [ ] `sections_json` JSONB column roundtrips through SQLAlchemy correctly
- [ ] `ruff` + `mypy` clean

---

##### T-W10-A-03: S8 `BriefArchivePort` interface definition
**Type**: impl
**depends_on**: T-W10-A-02
**blocks**: T-W10-B-01
**Target files**:
- `services/rag-chat/src/rag_chat/application/ports/brief_archive.py` (new)

**What to build**:
Protocol port defining the contract between application layer and the brief archive repository. Follows the pattern in `application/ports/thread_repository.py`.

**Entities / Components**:
- **`BriefArchivePort`** (NEW — created in Wave A) (Protocol):
  - `async def save(self, brief: UserBriefRecord) -> None`
  - `async def get_latest(self, user_id: UUID, tenant_id: UUID, brief_type: str, limit: int = 2) -> list[UserBriefRecord]`
  - `async def get_history(self, user_id: UUID, tenant_id: UUID, brief_type: str, page: int, page_size: int) -> tuple[list[UserBriefRecord], int]`

> **ARCH NOTE (R25)**: `BriefArchivePort` is a `Protocol` in the APPLICATION layer (`application/ports/brief_archive.py`). Use cases MUST depend on `BriefArchivePort` (the port), never on `BriefArchiveRepository` (the concrete SQLAlchemy class in `infrastructure/`). API routes inject via `BriefArchiveRepositoryDep` (type alias wrapping the ABC), as with the existing `ThreadRepositoryDep` pattern.

- **`UserBriefRecord`** (NEW — created in Wave A) (dataclass in same file):
  - `id: UUID`, `user_id: UUID`, `tenant_id: UUID`, `brief_type: str`, `entity_id: UUID | None`
  - `generated_at: datetime` (UTC-aware — R11), `headline: str`, `lead: str | None`
  - `sections_json: list[dict]`, `citations_json: list[dict]`
  - `confidence: float`, `source_version: str`

**Acceptance criteria**:
- [ ] `BriefArchivePort` is a `Protocol` (not ABC) matching the pattern in `thread_repository.py`
- [ ] Use cases depend on `BriefArchivePort` (R25 — never import `BriefArchiveRepository` directly in application layer)
- [ ] `UserBriefRecord` is importable and constructable with no defaults required except `entity_id`

---

#### Validation Gate — Wave A
- [ ] `alembic upgrade head` + `alembic downgrade -1` pass
- [ ] `ruff check` + `mypy` pass on all new/changed files
- [ ] 3 new unit tests pass (T-W10-A-02 tests)
- [ ] No existing tests broken

#### Break Impact — Wave A
| Broken file | Why | Fix |
|---|---|---|
| `services/rag-chat/src/rag_chat/infrastructure/db/models/__init__.py` | new models must be added to `__all__` and registered with `Base.metadata` | add import + `__all__` entry |

#### Regression Guardrails — Wave A
- BP-019 (migration must be idempotent via `IF NOT EXISTS`): use `op.execute("CREATE TABLE IF NOT EXISTS …")` or rely on Alembic `create_table` which is idempotent on re-run.
- BP-032 (nullable FK cascades): `brief_feedback.brief_id` uses `ON DELETE CASCADE` — when a brief is deleted, its feedback rows are automatically removed.

---

### Wave B: S8 Brief Archive Backend

**Goal**: Implement the brief archive repository adapter, wire the persistence hook into `GenerateBriefingUseCase`, and expose `GET /v1/briefings/morning/history`.
**Depends on**: Wave A
**Estimated effort**: 75 min
**Architecture layer**: infrastructure + application + API

#### Pre-read
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` lines 1–200 (persistence hook insertion point)
- `services/rag-chat/src/rag_chat/infrastructure/db/repositories/thread_repository.py` — adapter pattern to follow
- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (EXISTS) — existing briefing route patterns

#### Tasks

##### T-W10-B-01: `BriefArchiveRepository` SQLAlchemy adapter
**Type**: impl
**depends_on**: T-W10-A-03
**blocks**: T-W10-B-02, T-W10-B-03
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/db/repositories/brief_archive_repository.py` (new)

**What to build**:
SQLAlchemy `AsyncSession`-based implementation of `BriefArchivePort`. Named `BriefArchiveRepository` (NEW — created in Wave B). The `save` method converts `UserBriefRecord` → `UserBriefModel`, adds to session, and commits. The `get_latest` method returns the 2 most recent records (needed for diff).

> **ARCH NOTE (R25)**: `BriefArchiveRepository` is in `infrastructure/` — it must NEVER be imported directly by use cases or API routes. Only `BriefArchivePort` (the Protocol) crosses the layer boundary.

> **ARCH NOTE (R27)**: Read-only operations (`get_latest`, `get_history`) MUST use `ReadOnlyUnitOfWork` / `ReadUoWDep` from the API route DI. Write operations (`save`) use `UnitOfWork` / `UoWDep`. The repository receives an already-entered session from the UoW (it does not open its own UoW). Route handlers inject the correct dep: `uow: ReadUoWDep` for GET endpoints, `uow: UoWDep` for POST/mutation endpoints.

> **ARCH NOTE (R26)**: `BriefArchiveRepository.save()` must NOT call `commit()` internally. The use case calls `await uow.commit()` explicitly after calling `save()`. The repository only calls `session.add(model)`.

> **ARCH NOTE (R10)**: `UserBriefModel.id` set via `new_uuid7()` in the use case before calling `save()`, or via ORM `default=new_uuid7` (consistent with `ThreadModel` pattern). Never relies on DB default.

> **ARCH NOTE (R11)**: `UserBriefRecord.generated_at` and `BriefFeedbackModel.created_at` must be UTC-aware datetimes, set via `utc_now()` from `libs/common`.

**Logic & Behavior**:
- `save`: `INSERT INTO user_briefs (…) VALUES (…) ON CONFLICT DO NOTHING` — idempotency guard keyed on `(user_id, generated_at, brief_type)` to prevent double-save on retry.
- `get_latest`: `SELECT … ORDER BY generated_at DESC LIMIT {limit}` on read replica session.
- `get_history`: `SELECT … ORDER BY generated_at DESC OFFSET (page * page_size) LIMIT page_size` + `SELECT COUNT(*)`.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_save_brief_persists_to_db` | saved `UserBriefRecord` is retrievable via `get_latest` | integration (async DB) |
| `test_save_brief_idempotent` | double-save of same brief does not raise | integration |
| `test_get_latest_returns_most_recent` | returns records sorted by `generated_at DESC` | integration |
| `test_get_history_pagination` | page 0 and page 1 return non-overlapping results | integration |

Minimum: 4 integration tests.

**Acceptance criteria**:
- [ ] `save` is idempotent on duplicate `(user_id, generated_at, brief_type)`
- [ ] `get_latest` returns at most `limit=2` records, most recent first
- [ ] GET endpoint uses `ReadUoWDep` (read replica session) — R27 compliance
- [ ] `BriefArchiveRepository` is in `infrastructure/` and is NEVER imported by application layer directly (R25)
- [ ] `save()` does not call `commit()` — use case calls `await uow.commit()` (R26)

---

##### T-W10-B-02: Persistence hook in `GenerateBriefingUseCase`
**Type**: impl
**depends_on**: T-W10-B-01
**blocks**: T-W10-B-03
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` (modify)

**What to build**:
After `execute_public_morning()` and `execute_public_instrument()` successfully build the `PublicBriefingResponse`, call `await self._brief_archive.save(record)`. The `_brief_archive: BriefArchivePort` dependency is injected via constructor (optional — defaults to a `NullBriefArchive` no-op adapter so the use case still works without DI wiring). `NullBriefArchive` (NEW — created in Wave B) is defined in the same file; `BriefArchiveRepository` is wired in `api/dependencies.py`.

> **ARCH NOTE (R25)**: `GenerateBriefingUseCase` holds `_brief_archive: BriefArchivePort` (the Protocol, from `application/ports/`). The constructor NEVER takes `BriefArchiveRepository` (the infra class). DI injects the concrete class from `api/dependencies.py`.

> **ARCH NOTE (structlog — STANDARDS.md §5)**: Use `structlog.get_logger(__name__)`. Never `import logging`.

**Logic & Behavior**:
1. Build `UserBriefRecord` from the response (serialise `sections` and `citations` to `list[dict]` via `.model_dump()`). Set `id = new_uuid7()` and `generated_at = utc_now()` (R10, R11).
2. `await self._brief_archive.save(record)` — fire-and-forget with `asyncio.shield` so a DB failure does NOT fail the brief response to the user.
3. Log `brief_persisted=True/False` at DEBUG level via structlog.

**Idempotency**: If Valkey cache serves a cached response, the brief is NOT re-saved (it was already saved when first generated). The `(user_id, generated_at, brief_type)` unique guard in the repository handles the rare case.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_persistence_called_on_morning_brief` | mock archive's `save` is awaited once after successful generation | unit |
| `test_persistence_failure_does_not_fail_brief` | if archive raises, `execute_public_morning` still returns response | unit |
| `test_cached_brief_does_not_call_archive` | when Valkey cache hits, archive is not called | unit |

Minimum: 3 unit tests.

**Acceptance criteria**:
- [ ] `asyncio.shield` wraps the archive `save` call
- [ ] `NullBriefArchive` is the default so existing unit tests requiring no DI don't break

---

##### T-W10-B-03: `GET /v1/briefings/morning/history` + S9 proxy
**Type**: impl
**depends_on**: T-W10-B-01
**blocks**: T-W10-E-01 (proxy needed before frontend can fetch history)
**Target files**:
- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (modify)
- `services/api-gateway/src/api_gateway/routes/proxy.py` (modify)
- `apps/worldview-web/lib/api/briefing.ts` (modify — add `getBriefHistory`)
- `apps/worldview-web/types/api.ts` (modify — add `BriefHistoryItem`)

**API Spec**:
```
GET /v1/briefings/morning/history?page=0&page_size=10
Authorization: Bearer {jwt}
Response: {
  items: [{id, generated_at, headline, lead, confidence}],
  total: int,
  page: int,
  page_size: int
}
```

**What to build**:
- S8 route: `ReadUoWDep` (R27) + `BriefArchiveRepositoryDep` → calls `get_history(user_id, tenant_id, "morning", page, page_size)`. Max page_size=50.
- S9 proxy: `GET /api/v1/briefings/morning/history` → S8 passthrough (same pattern as existing brief proxies at `proxy.py` lines 1950–1990 — `get_morning_briefing`/`get_instrument_briefing`).
- TS type `BriefHistoryItem` in `types/api.ts`: `{id: string, generated_at: string, headline: string, lead: string | null, confidence: number}`.
- `getBriefHistory(page: number)` in `lib/api/briefing.ts`.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_history_endpoint_returns_200` | `GET /v1/briefings/morning/history` with valid JWT returns 200 | unit (ASGI) |
| `test_history_endpoint_respects_pagination` | `?page=1&page_size=2` returns correct slice | unit |
| `test_history_requires_auth` | 401 without auth header | unit |

Minimum: 3 unit tests.

**Acceptance criteria**:
- [ ] `page_size` capped at 50 server-side
- [ ] Uses `ReadUoWDep` (read replica session)
- [ ] S9 proxy route added and tested (S9 contract test or curl-verifiable)

---

#### Validation Gate — Wave B
- [ ] `ruff` + `mypy` pass
- [ ] 10 new tests pass (A-01 × 4 integration + B-02 × 3 unit + B-03 × 3 unit)
- [ ] `alembic upgrade head` still clean
- [ ] Existing `test_generate_briefing*.py` tests pass (persistence defaults to `NullBriefArchive`)

#### Break Impact — Wave B
| Broken file | Why | Fix |
|---|---|---|
| `services/rag-chat/src/rag_chat/api/dependencies.py` | new `BriefArchiveRepositoryDep` dependency must be wired | add DI binding for `BriefArchiveRepository` |
| `services/rag-chat/src/rag_chat/app.py` (lifespan) | may need `BriefArchiveRepository` to be constructed at startup | verify — likely passed via DI, not lifespan |

#### Regression Guardrails — Wave B
- BP-314 (mark_processed before commit): archive `save` must commit AFTER the response is assembled, not before returning — use `asyncio.shield` so commit failure can't fail the HTTP response.
- R24 (no session held across I/O): the `asyncio.shield` call runs in the background; ensure the archive repository opens its own session scope.

---

### Wave C: S8 Brief Diff + Brief Feedback Backend ✓ DONE 2026-05-08

**Goal**: Implement the diff computation and feedback endpoints.
**Depends on**: Wave B
**Estimated effort**: 75 min
**Architecture layer**: application + API

#### Pre-read
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` — BriefSection, BriefBullet shapes (post PLAN-0062-W4 Wave A)
- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` — route pattern

#### Tasks

##### T-W10-C-01: `BriefDiffService` + diff endpoint
**Type**: impl
**depends_on**: T-W10-B-01
**blocks**: T-W10-E-01
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/brief_diff.py` (new)
- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (modify)

**What to build**:
`BriefDiffUseCase` (NEW — created in Wave C) — `application/use_cases/brief_diff.py`.

> **ARCH NOTE (R25)**: `BriefDiffUseCase` depends on `BriefArchivePort` (ABC Protocol), injected via constructor. Never imports `BriefArchiveRepository`.
> **ARCH NOTE (R27)**: `GET /v1/briefings/morning/diff` is read-only — route handler MUST use `ReadUoWDep`.
> **ARCH NOTE (structlog)**: Use `structlog.get_logger(__name__)` if logging is needed.

`BriefDiffUseCase.execute(user_id, tenant_id)`:
1. Fetch last 2 briefs via `BriefArchivePort.get_latest(limit=2)`.
2. If fewer than 2, return `{"status": "no_diff_available"}`.
3. Diff `sections_json[today]` vs `sections_json[yesterday]`:
   - `new_bullets`: bullets in today's brief not present in yesterday's (text-based comparison, normalised to lowercase strip).
   - `removed_bullets`: bullets in yesterday's brief absent today.
   - `changed_sections`: sections with same title but different bullet set.
   - `delta_summary`: "N new bullets, M removed since {yesterday_date}" as a plain string.
4. Return `BriefDiffResponse`.

**API**:
```
GET /v1/briefings/morning/diff
Response: {
  status: "diff_available" | "no_diff_available",
  today_generated_at: str | null,
  yesterday_generated_at: str | null,
  new_bullets: [{section_title, text, citations[]}],
  removed_bullets: [{section_title, text}],
  changed_sections: [str],  -- section titles
  delta_summary: str
}
```

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_diff_detects_new_bullets` | new bullet in today → appears in `new_bullets` | unit |
| `test_diff_detects_removed_bullets` | bullet in yesterday but not today → `removed_bullets` | unit |
| `test_diff_no_data_returns_no_diff` | fewer than 2 stored briefs → `status="no_diff_available"` | unit |
| `test_diff_identical_briefs_empty_delta` | same sections/bullets → `new_bullets=[]`, `removed_bullets=[]` | unit |

Minimum: 4 unit tests.

**Acceptance criteria**:
- [ ] Diff comparison is text-normalised (lowercase, strip whitespace) — not pointer-equality
- [ ] `GET /v1/briefings/morning/diff` uses `ReadUoWDep`

---

##### T-W10-C-02: Brief feedback backend (endpoints + use cases)
**Type**: impl
**depends_on**: T-W10-A-02
**blocks**: T-W10-E-01
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/brief_feedback.py` (new)
- `services/rag-chat/src/rag_chat/infrastructure/db/repositories/brief_feedback_repository.py` (new)
- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (modify — add 2 POST routes)

**API**:
```
POST /v1/briefings/feedback/bullet
Body: {brief_id: str, section_idx: int, bullet_idx: int, reaction: "helpful"|"unhelpful"}
Response: {id: str, created_at: str}

POST /v1/briefings/feedback/brief
Body: {brief_id: str, reaction: "1"|"2"|"3"|"4"|"5"}
Response: {id: str, created_at: str}
```

**Files to create**:
- `application/use_cases/brief_feedback.py` — `BriefFeedbackUseCase` (NEW — created in Wave C)
- `infrastructure/db/repositories/brief_feedback_repository.py` — `BriefFeedbackRepository` (NEW — created in Wave C)
- (optional) `application/ports/brief_feedback.py` — `BriefFeedbackPort` (NEW — created in Wave C) if a separate Protocol is desired; alternatively, inline the port on `BriefFeedbackUseCase`.

> **ARCH NOTE (R25)**: If a `BriefFeedbackPort` Protocol is defined, use cases depend on the port. If the use case is thin enough (just one method), the infra repo can be injected as the Protocol via structural subtyping.
> **ARCH NOTE (R10)**: New feedback `id` set via `new_uuid7()` from `libs/common` in the use case, not via DB default.
> **ARCH NOTE (R11)**: `BriefFeedbackModel.created_at` set via `utc_now()` from `libs/common`.
> **ARCH NOTE (R26)**: Use case calls `await uow.commit()` after `session.add(model)` — repository does not commit.

**Logic**:
- Validate `brief_id` exists in `user_briefs` for the requesting user (not a different user's brief) before inserting.
- `reaction` values: `"helpful"` / `"unhelpful"` for bullet scope; `"1"`–`"5"` for brief scope.
- No duplicate enforcement — Sam can change his mind by submitting another reaction (last-write-wins in the fine-tuning dataset).

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_bullet_feedback_creates_record` | POST with valid body returns 201 + record ID | unit (ASGI) |
| `test_brief_feedback_creates_record` | POST brief feedback returns 201 | unit |
| `test_feedback_rejects_invalid_brief_id` | brief_id not owned by user → 404 | unit |
| `test_bullet_feedback_invalid_reaction` | reaction not in allowed set → 422 | unit |

Minimum: 4 unit tests.

**Acceptance criteria**:
- [ ] `brief_id` ownership validated against requesting `user_id`
- [ ] `section_idx` and `bullet_idx` NULL when scope is `"brief"`
- [ ] Reaction enum enforced at Pydantic level

---

#### Validation Gate — Wave C
- [x] `ruff` + `mypy` pass
- [x] 8 new tests pass (756 total, up from 739)
- [x] Diff endpoint returns correct shape against two seeded `UserBriefModel` fixtures

#### Break Impact — Wave C
| Broken file | Why | Fix |
|---|---|---|
| `services/rag-chat/src/rag_chat/api/dependencies.py` | `BriefFeedbackRepository` + `BriefDiffUseCase` need DI | add bindings |

#### Regression Guardrails — Wave C
- BP-007 (FK without index): `brief_feedback.brief_id` has index `ix_brief_feedback_brief_id` — ensure it's in migration.

---

### Wave D: S8 Chat Seeding + Implicit RAG Seed ✓ DONE 2026-05-08

**Goal**: Wire the "Discuss in chat" flow — a `POST /v1/briefings/chat/discuss` endpoint that creates a thread seeded with the brief's citations, and an implicit seed that auto-injects today's brief into every chat retrieval for the same user.
**Depends on**: Wave B
**Estimated effort**: 75 min
**Architecture layer**: application + DB migration

#### Pre-read
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` — where retrieval is invoked
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` — `retrieve()` method signature
- `services/rag-chat/src/rag_chat/infrastructure/db/models/thread.py` — add `seed_brief_id` column

#### Tasks

##### T-W10-D-01: Alembic 0005 `threads.seed_brief_id` + `POST /v1/briefings/chat/discuss`
**Type**: impl + schema
**depends_on**: T-W10-B-01
**blocks**: T-W10-D-02, T-W10-E-01
**Target files**:
- `services/rag-chat/alembic/versions/0005_add_seed_brief_id_to_threads.py` (new)
- `services/rag-chat/src/rag_chat/infrastructure/db/models/thread.py` (modify — add `seed_brief_id`)
- `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (modify — add discuss route)

**Schema change**:
```sql
ALTER TABLE threads ADD COLUMN seed_brief_id UUID REFERENCES user_briefs(id) ON DELETE SET NULL;
```
Nullable; ON DELETE SET NULL (if brief is ever deleted, thread continues without seed).

**API**:
```
POST /v1/briefings/chat/discuss
Body: {brief_type: "morning"} -- future: instrument brief support
Response: {thread_id: str, seeded_with_brief_id: str}
```

**Logic**:
1. Fetch latest morning brief via `BriefArchivePort.get_latest(user_id, tenant_id, "morning", limit=1)`.
2. If none found → return 422 "No brief available to seed chat".
3. Create a new thread with `seed_brief_id=brief.id` via existing `CreateThreadUseCase` (extend it to accept optional `seed_brief_id`).
4. Return `{thread_id, seeded_with_brief_id}`.

> **ARCH NOTE (R25)**: The route handler for `POST /v1/briefings/chat/discuss` must depend on `BriefArchivePort` via DI — never import `BriefArchiveRepository` in the route or use case.
> **ARCH NOTE (R27)**: This POST endpoint WRITES (creates a thread) — use `UoWDep`, not `ReadUoWDep`.
> **ARCH NOTE (R10)**: New `thread_id` set via `new_uuid7()` in `CreateThreadUseCase` (already done in existing implementation — verify it persists `seed_brief_id` correctly).

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_discuss_creates_thread_with_seed` | new thread has `seed_brief_id` set to latest brief | unit |
| `test_discuss_fails_when_no_brief` | 422 when no brief persisted | unit |
| `test_seed_brief_id_nullable_migration` | `alembic upgrade head` + `alembic downgrade -1` clean | migration test |

Minimum: 3 tests.

**Acceptance criteria**:
- [x] Thread `seed_brief_id` FK is nullable
- [x] `CreateThreadUseCase` updated to accept and persist `seed_brief_id`
- [x] Route uses `UoWDep` (write path — R27)

---

##### T-W10-D-02: Implicit RAG seed (`_fetch_brief_seed` in `RetrievalOrchestrator`)
**Type**: impl
**depends_on**: T-W10-D-01
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` (modify)

**What to build**:
Two new methods on `ParallelRetrievalOrchestrator`:
1. `_fetch_brief_seed(user_id, tenant_id, seed_brief_id=None)` — fetches brief from archive (explicit seed) or checks for a same-day brief (implicit seed). Returns list of `RetrievedItem` derived from the brief's `citations_json`.
2. This method is called unconditionally at the top of `retrieve()` and its results are prepended to the items list with `trust_weight=0.95` (highest — user explicitly generated this brief today; it's the freshest signal).

**Logic**:
```python
# _fetch_brief_seed lives in ParallelRetrievalOrchestrator
# (class exists at services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py)
# _fetch_brief_seed is a NEW method (NEW — created in Wave D)
#
# ARCH NOTE (R25): self._archive is BriefArchivePort (ABC), never BriefArchiveRepository
# ARCH NOTE (structlog): use structlog.get_logger(__name__) for logging

async def _fetch_brief_seed(
    self, user_id: UUID, tenant_id: UUID, seed_brief_id: UUID | None = None
) -> list[RetrievedItem]:
    if seed_brief_id:
        brief = await self._archive.get_by_id(seed_brief_id)
    else:
        # implicit: check for a same-calendar-day brief
        briefs = await self._archive.get_latest(user_id, tenant_id, "morning", limit=1)
        brief = briefs[0] if briefs and is_same_day(briefs[0].generated_at) else None

    if not brief or not brief.citations_json:
        return []

    return [
        RetrievedItem.create(
            item_id=f"brief_seed:{brief.id}:{c.get('document_id', i)}",
            item_type=ItemType.chunk,
            text=c.get("snippet", c.get("title", "")),
            score=0.95,
            trust_weight=0.95,
            # CitationMeta constructor: CitationMeta(title, url, source_name, ...)
            # (see domain/entities/chat.py for actual CitationMeta fields)
            citation_meta=CitationMeta(
                title=c.get("title"),
                url=c.get("url"),
                source_name="Morning Brief",
            ),
        )
        for i, c in enumerate(brief.citations_json[:8])  # cap at 8 seed items
    ]
```

> **ARCH NOTE (R10/R11)**: `is_same_day()` helper compares `brief.generated_at.date()` (UTC) against `utc_now().date()` (R11 — avoid `datetime.today()` which uses local TZ).
> **ARCH NOTE (RetrievedItem)**: Use the `.create()` factory (never construct directly — `fusion_score` invariant enforced in `__post_init__`). The field is `text` (NOT `content`). `item_id` is a string (not UUID).

The `BriefArchivePort` needs a new `get_by_id(id)` method — add to the Protocol and adapter in Wave B's repository.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_explicit_seed_injects_brief_citations` | thread with `seed_brief_id` → retrieved items include brief citations | unit |
| `test_implicit_seed_injects_same_day_brief` | user with same-day brief and no explicit seed → brief citations injected | unit |
| `test_no_seed_when_brief_is_from_yesterday` | yesterday's brief (different calendar day) → NOT injected implicitly | unit |
| `test_seed_capped_at_8_items` | brief with 20 citations → only 8 RetrievedItems emitted | unit |

Minimum: 4 unit tests.

**Acceptance criteria**:
- [x] Explicit seed (`seed_brief_id`) always takes precedence over implicit seed
- [x] Implicit seed checks calendar-day equality in UTC (`date()` comparison)
- [x] Cap of 8 seed items prevents context overflow

---

##### T-W10-D-03: `BriefArchivePort.get_by_id` extension
**Type**: impl
**depends_on**: T-W10-A-03
**blocks**: T-W10-D-02
**Target files**:
- `services/rag-chat/src/rag_chat/application/ports/brief_archive.py` (modify — add `get_by_id`)
- `services/rag-chat/src/rag_chat/infrastructure/db/repositories/brief_archive_repository.py` (modify — implement `get_by_id`)

**What to build**: Add `async def get_by_id(self, brief_id: UUID) -> UserBriefRecord | None` (NEW — added in Wave D) to both `BriefArchivePort` (Protocol in `application/ports/brief_archive.py`) and the SQLAlchemy adapter (`BriefArchiveRepository`). Simple primary key lookup. `NullBriefArchive` must also implement `get_by_id` returning `None`.

Minimum: 1 unit test (`test_get_by_id_returns_none_for_unknown`).

**Acceptance criteria**:
- [x] Returns `None` (not exception) for unknown IDs (Wave A already confirmed)
- [x] `NullBriefArchive` returns `None` for `get_by_id` (Wave A already confirmed)

---

#### Validation Gate — Wave D
- [x] `ruff` + `mypy` pass (2026-05-08)
- [x] 8 new tests pass (756 total, 0 failed)
- [ ] `alembic upgrade head` clean with 0004 + 0005 (requires live DB)

#### Break Impact — Wave D
| Broken file | Why | Fix |
|---|---|---|
| `services/rag-chat/src/rag_chat/application/use_cases/create_thread.py` | must accept optional `seed_brief_id` | add `seed_brief_id: UUID | None = None` parameter + persist to `ThreadModel` |
| `services/rag-chat/tests/unit/application/test_create_thread.py` | new `seed_brief_id` field on use case signature | update fixtures |

#### Regression Guardrails — Wave D
- BP-316 (non-deterministic event_id): the `_fetch_brief_seed` method uses a stable `f"brief_seed:{brief.id}:{c['document_id']}"` as item_id — deterministic, idempotent.
- R27: `get_latest` / `get_by_id` use `ReadUoWDep` (no implicit write on read path).

---

### Wave E: S9 Proxies for All New S8 Routes

**Goal**: Wire S9 API Gateway proxy routes for all new S8 endpoints added in Waves B–D.
**Depends on**: Wave C, Wave D
**Estimated effort**: 60 min
**Architecture layer**: API Gateway

#### Pre-read
- `services/api-gateway/src/api_gateway/routes/proxy.py` lines 1950–1990 (existing brief proxy patterns — `get_morning_briefing` at line 1950, `get_instrument_briefing` at line 1972; file is 3242 lines total)

#### Tasks

##### T-W10-E-01: S9 proxy routes (6 new endpoints)
**Type**: impl
**depends_on**: T-W10-C-01, T-W10-C-02, T-W10-D-01
**blocks**: T-W10-F-01
**Target files**:
- `services/api-gateway/src/api_gateway/routes/proxy.py` (modify)

**Endpoints to proxy** (all follow existing passthrough pattern at lines 1950–1990):
```
GET  /api/v1/briefings/morning/history        → S8 GET /v1/briefings/morning/history
GET  /api/v1/briefings/morning/diff           → S8 GET /v1/briefings/morning/diff
POST /api/v1/briefings/feedback/bullet        → S8 POST /v1/briefings/feedback/bullet
POST /api/v1/briefings/feedback/brief         → S8 POST /v1/briefings/feedback/brief
POST /api/v1/briefings/chat/discuss           → S8 POST /v1/briefings/chat/discuss
POST /api/v1/briefings/{brief_id}/create-alert → S8 POST /v1/briefings/{brief_id}/create-alert
```

The last endpoint (alert creation pre-fill) is from Wave F backend; wire proxy in this wave as a placeholder (404 until Wave F ships S8 side, but the proxy route must exist for frontend E2E tests).

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_proxy_brief_history_passthrough` | S9 `GET /api/v1/briefings/morning/history` proxies to S8 | contract/unit |
| `test_proxy_brief_diff_passthrough` | S9 `GET /api/v1/briefings/morning/diff` proxies to S8 | contract/unit |
| `test_proxy_brief_feedback_bullet` | S9 `POST /api/v1/briefings/feedback/bullet` proxies | contract/unit |
| `test_proxy_brief_discuss` | S9 `POST /api/v1/briefings/chat/discuss` proxies | contract/unit |

Minimum: 4 contract tests.

**Acceptance criteria**:
- [ ] All 6 proxy routes added with correct HTTP method + path mapping
- [ ] Rate limiting consistent with existing briefing proxies

---

#### Validation Gate — Wave E
- [ ] `ruff` + `mypy` pass on S9
- [ ] 4 new S9 contract tests pass
- [ ] No existing S9 proxy tests broken

#### Break Impact — Wave E
None — additive proxy routes only.

#### Regression Guardrails — Wave E
- Existing briefing proxy routes at lines 1660–1700 must not be disturbed; insert new routes after them.

---

### Wave F: Frontend — Diff Badge + Chat Seeding + Feedback + Alert Creation

**Goal**: Surface all four new brief interactions in the UI.
**Depends on**: Wave E, PLAN-0062-W4 Wave E (MorningBriefCard must use `<StructuredBrief>`)
**Estimated effort**: 90 min
**Architecture layer**: UI

#### Pre-read
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (post PLAN-0062-W4 version — uses `<StructuredBrief>`)
- `apps/worldview-web/lib/api/briefing.ts` (existing API helpers)
- `apps/worldview-web/lib/query/keys.ts` (query key factory — add `briefHistory`, `briefDiff`)

#### Tasks

##### T-W10-F-01: `<BriefDiffBadge>` + `<BriefDiffPanel>` in `MorningBriefCard`
**Type**: impl
**depends_on**: T-W10-E-01
**blocks**: none
**Target files**:
- `apps/worldview-web/features/dashboard/components/BriefDiffBadge.tsx` (new)
- `apps/worldview-web/features/dashboard/components/BriefDiffPanel.tsx` (new)
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (modify)

**What to build**:
- `<BriefDiffBadge>`: small pill showing "N new" (amber) or "No changes" (muted). Clicking expands `<BriefDiffPanel>`.
- `<BriefDiffPanel>`: collapsible section showing `new_bullets` with green `+` prefix and `removed_bullets` with muted strikethrough. Delta summary at top. Uses `useQuery(qk.briefing.diff())`.
- Wire into `MorningBriefCard` expanded header row alongside the confidence badge.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_brief_diff_badge_shows_new_count` | `{new_bullets: [{...}]}` → badge shows "1 new" | unit |
| `test_brief_diff_badge_hidden_when_no_data` | `status="no_diff_available"` → badge hidden | unit |
| `test_brief_diff_panel_expands_on_click` | click badge → panel renders `new_bullets` | unit |

Minimum: 3 unit tests.

---

##### T-W10-F-02: "Discuss in Chat" button + `useBriefChatSeed` hook
**Type**: impl
**depends_on**: T-W10-E-01
**blocks**: none
**Target files**:
- `apps/worldview-web/features/dashboard/hooks/useBriefChatSeed.ts` (new)
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (modify)

**What to build**:
- `useBriefChatSeed()`: calls `POST /api/v1/briefings/chat/discuss`, navigates to `/chat?thread={thread_id}` on success.
- Button: "Discuss in Chat" (secondary variant, placed in MorningBriefCard actions row). Shows loading spinner while request is in-flight. On error, shows a toast "Could not open chat — please try again".
- The chat page must handle `?thread={id}` by pre-selecting the thread (already supported via `nuqs`).

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_discuss_button_navigates_to_chat` | mock POST returns `{thread_id}` → router.push called with `/chat?thread={id}` | unit |
| `test_discuss_button_shows_error_toast_on_failure` | mock POST 422 → toast rendered | unit |

Minimum: 2 unit tests.

---

##### T-W10-F-03: Per-bullet feedback (thumbs) + brief rating
**Type**: impl
**depends_on**: T-W10-E-01
**blocks**: none
**Target files**:
- `apps/worldview-web/features/dashboard/components/BulletFeedback.tsx` (new)
- `apps/worldview-web/features/dashboard/components/BriefRating.tsx` (new)
- `apps/worldview-web/components/briefing/StructuredBrief.tsx` (modify — add `briefId` prop + `onBulletFeedback` callback)

**What to build**:
- `<BulletFeedback briefId section_idx bullet_idx />`: renders two icon buttons (ThumbsUp / ThumbsDown) visible on hover over the bullet text. On click, calls `POST /api/v1/briefings/feedback/bullet`. After click, shows the selected icon in filled state (optimistic update).
- `<BriefRating briefId />`: 5-star rating shown at the bottom of the expanded brief. On click, calls `POST /api/v1/briefings/feedback/brief`. Stars fill in on hover using CSS `:hover` siblings.
- Wire `briefId` into `<StructuredBrief>` as an optional prop. When `briefId` is present, `<BulletFeedback>` is rendered inline after each bullet.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_bullet_thumbs_up_posts_feedback` | ThumbsUp click → `POST /api/v1/briefings/feedback/bullet` with correct body | unit |
| `test_bullet_feedback_optimistic_fill` | after click, icon switches to filled before API resolves | unit |
| `test_brief_rating_posts_5_stars` | 5-star click → `POST /api/v1/briefings/feedback/brief` with `reaction="5"` | unit |
| `test_brief_rating_hidden_without_brief_id` | no `briefId` prop → `<BriefRating>` not rendered | unit |

Minimum: 4 unit tests.

---

##### T-W10-F-04: Alert creation from brief mentions
**Type**: impl
**depends_on**: T-W10-E-01
**blocks**: none
**Target files**:
- `apps/worldview-web/features/dashboard/components/BriefEntityPill.tsx` (new)
- `apps/worldview-web/components/briefing/StructuredBrief.tsx` (modify — render entity pills in bullet text)

**What to build**:
- `<BriefEntityPill entityName entityId bulletContext />`: an inline chip within bullet text for recognized entity names (passed down from `BriefBullet.citations[]` where `source_type="entity"`). Shows a hover context menu with "Create Alert for {entityName}" action.
- "Create Alert" action: calls `POST /api/v1/briefings/{briefId}/create-alert` (Wave F backend — S8 endpoint) with `{section_idx, bullet_idx, entity_id}`. On success, opens the `<AlertCreateDrawer>` (already exists from PLAN-0051) pre-filled with `entity_id` and `context=bulletContext`.
- If entity name is plain text (not a citation), fallback: render as plain text — no pill.

**Alert pre-fill S8 endpoint** (backend, same wave):

New file: `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (add endpoint):
```
POST /v1/briefings/{brief_id}/create-alert
Body: {section_idx: int, bullet_idx: int, entity_id: str | null}
Response: {
  entity_id: str | null,
  entity_name: str | null,
  suggested_alert_type: str,   -- e.g. "PRICE_CHANGE", "NEWS"
  context_snippet: str          -- the bullet text, ≤200 chars
}
```

Logic: look up `brief_id` in `user_briefs`, find `sections_json[section_idx].bullets[bullet_idx]`, extract entity_id from first citation, suggest `alert_type="NEWS"` by default. Does NOT create an alert (that's S10's job) — just pre-fills the form.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_entity_pill_renders_for_citation` | bullet with entity citation → pill rendered | unit |
| `test_create_alert_action_opens_drawer` | "Create Alert" context menu → `AlertCreateDrawer` opened with pre-fill | unit |
| `test_create_alert_prefill_endpoint_returns_context` | POST to S8 → 200 with `context_snippet` = bullet text | unit (ASGI) |

Minimum: 3 unit tests.

---

#### Validation Gate — Wave F
- [x] `ruff` + `mypy` pass (frontend: `pnpm typecheck`)
- [x] `pnpm vitest` — all existing tests pass + 10 new tests (Wave F)
- [x] `pnpm build` succeeds
- [x] Diff badge + chat discuss button + feedback thumbs + entity pill all implemented

**Wave F completed 2026-05-08** — 10 frontend tests pass, 765 S8 unit tests pass, 7 S8 contract tests pass, `pnpm typecheck` and `pnpm build` both pass.

#### Break Impact — Wave F
| Broken file | Why | Fix |
|---|---|---|
| `apps/worldview-web/__tests__/morning-brief-card.test.tsx` | new `briefId` prop + diff badge + actions row | update test fixtures and snapshot |
| `apps/worldview-web/components/briefing/StructuredBrief.tsx` | new optional `briefId` prop | no breaking change — optional prop |

#### Regression Guardrails — Wave F
- PLAN-0062-W4 W9 coordination: `MorningBriefCard` token classes (`--muted-foreground`) must remain unchanged — only new JSX added to the actions row, not modifications to existing token assignments.
- Feedback thumbs must not appear in the `compact` variant of `<StructuredBrief>` (only in `full`).

---

### Wave G: S3 Temporal Endpoints

**Goal**: Add two new endpoints to the S3 (market-data) service that expose OHLCV time-series and quarterly fundamentals history, enabling the temporal RAG. Both endpoints accept any of three instrument identifiers — UUID, ticker symbol, or ISIN — so LLM tool handlers can pass a ticker directly without a pre-resolution round-trip.
**Depends on**: none (parallel-safe with Waves A–F)
**Estimated effort**: 90 min
**Architecture layer**: S3 market-data API

#### Pre-read
- `services/market-data/src/market_data/api/routers/ohlcv.py` — existing OHLCV routes (note literal routes `/ohlcv/bulk` registered before `/{instrument_id}` catch-all — follow same ordering)
- `services/market-data/src/market_data/api/routers/fundamentals.py` — existing fundamentals routes; UUID pattern guard on `{instrument_id}` path param
- `services/market-data/src/market_data/api/routers/instruments.py` — `GET /instruments/lookup` handler pattern: `InstrumentLookupUseCase.execute(id, isin, symbol)` — reuse this for resolution
- `services/market-data/src/market_data/application/use_cases/lookup_instrument.py` — `InstrumentLookupUseCase` (already exists; inject via DI)
- `services/market-data/src/market_data/domain/entities.py` — `Instrument`, `OHLCVBar` entities
- `services/market-data/src/market_data/infrastructure/db/` — TimescaleDB query patterns for OHLCV

#### Design decision: identifier resolution
All three identifiers (`instrument_id` UUID, `symbol` ticker, `isin`) are optional query params — none is in the path. At least one must be supplied (422 otherwise). Priority: `instrument_id` > `isin` > `symbol`. Resolution uses `InstrumentLookupUseCase` (already DI-wired in dependencies.py) and raises 404 if the instrument is unknown. This pattern is applied **only to the two new endpoints** — existing endpoints are UUID-path-param only and are not modified (no regression surface).

Route paths are literals registered **before** any `/{instrument_id}` catch-all routes in their respective routers, exactly as `/ohlcv/bulk` is registered before `/{instrument_id}`.

#### Tasks

##### T-W10-G-01: `GET /api/v1/ohlcv/bars` — OHLCV bars with interval resampling in S3
**Type**: impl
**depends_on**: none
**blocks**: T-W10-H-01
**Target files**:
- `services/market-data/src/market_data/api/routers/ohlcv.py` (modify — register new literal route **before** `/{instrument_id}` catch-alls)
- `services/market-data/src/market_data/application/use_cases/get_ohlcv_bars.py` (new) — `GetOHLCVBarsUseCase` (NEW — created in Wave G)

> **ARCH NOTE (N-2/N-3)**: All OHLCV routes live in `routers/ohlcv.py`, not `market.py`. The existing `GET /api/v1/ohlcv/{instrument_id}` returns bars with `start`/`end` filters but does NOT resample to week/month intervals. The new `/bars` endpoint adds interval resampling and accepts any of three identifiers. Register the new route immediately after `/ohlcv/bulk` so the literal path `/bars` is matched before the `/{instrument_id}` catch-all.

> **ARCH NOTE (R25)**: New route uses `Depends(get_ohlcv_bars_uc)` and `Depends(get_lookup_instrument_uc)` — never imports a repository or use case class directly in the router.
> **ARCH NOTE (R27)**: Read-only GET endpoint — must use `ReadUoWDep` (read replica session).

**API Spec**:
```
GET /api/v1/ohlcv/bars
  ?instrument_id=<UUID>         # optional — instrument UUID
  ?symbol=AAPL                  # optional — ticker symbol (e.g. "AAPL", "MSFT.US")
  ?isin=US0378331005            # optional — 12-char ISIN
  # At least one of the above three is required (422 if none supplied)
  ?from_date=2026-02-01         # ISO date, required
  ?to_date=2026-05-01           # ISO date, required
  ?interval=day                 # 'day' | 'week' | 'month', default 'day'
  ?max_bars=252                 # cap, default 252 (1 trading year of daily bars)

Response: {
  instrument_id: str,           -- resolved UUID (always present in response)
  ticker: str,                  -- resolved symbol
  interval: str,
  bars: [{date: str, open: float, high: float, low: float, close: float, volume: int}],
  bar_count: int
}

Errors:
  400  — none of instrument_id / symbol / isin supplied
  404  — instrument not found
  422  — invalid date range or interval; date range > S3_OHLCV_MAX_DAYS
```

**Router handler sketch**:
```python
# Register BEFORE /{instrument_id} routes
@router.get("/ohlcv/bars", response_model=OHLCVBarsResponse)
async def get_ohlcv_bars_flexible(
    instrument_id: Annotated[UUID | None, Query()] = None,
    symbol: Annotated[str | None, Query(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")] = None,
    isin: Annotated[str | None, Query(min_length=12, max_length=12, pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")] = None,
    from_date: date = ...,
    to_date: date = ...,
    interval: str = "day",
    max_bars: int = Query(default=252, ge=1, le=1000),
    uc: Annotated[GetOHLCVBarsUseCase, Depends(get_ohlcv_bars_uc)] = ...,
    lookup_uc: Annotated[InstrumentLookupUseCase, Depends(get_lookup_instrument_uc)] = ...,
) -> OHLCVBarsResponse:
    if instrument_id is None and symbol is None and isin is None:
        raise HTTPException(status_code=400, detail="At least one of instrument_id, symbol, or isin is required")
    ...
```

**Logic**:
1. **Resolve instrument**: pass `id=str(instrument_id)`, `symbol=symbol`, `isin=isin` to `InstrumentLookupUseCase.execute()`. Priority enforced inside `InstrumentLookupUseCase` (id > isin > symbol). Raise 404 on `InstrumentNotFoundError`.
2. **Validate date range**: `to_date - from_date ≤ S3_OHLCV_MAX_DAYS` (new env var, default 365). Return 422 if exceeded.
3. **Query**: pass resolved `instrument_id` (UUID) to `GetOHLCVBarsUseCase.execute()`. Resample to `interval` using TimescaleDB `time_bucket` (follow existing pattern in `ohlcv_queries.py`).
4. **Truncate**: if `bar_count > max_bars`, keep only the most recent `max_bars` bars.
5. **Response**: always include `instrument_id` (UUID) and `ticker` (resolved symbol) in response body.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_ohlcv_bars_resolves_by_symbol` | `?symbol=AAPL` → lookup called with symbol; resolved UUID used for query | unit |
| `test_ohlcv_bars_resolves_by_isin` | `?isin=US0378331005` → lookup called with isin; resolved UUID used | unit |
| `test_ohlcv_bars_uses_instrument_id_directly` | `?instrument_id=<UUID>` → lookup still called (id priority); no extra resolution | unit |
| `test_ohlcv_bars_returns_400_if_no_identifier` | no identifier params → 400 | unit |
| `test_ohlcv_bars_returns_404_if_not_found` | lookup raises `InstrumentNotFoundError` → 404 | unit |
| `test_ohlcv_bars_returns_bars_in_range` | bars outside `from_date`–`to_date` not returned | unit |
| `test_ohlcv_bars_rejects_excessive_date_range` | range > `S3_OHLCV_MAX_DAYS` → 422 | unit |
| `test_ohlcv_bars_weekly_resampling` | `interval=week` → bars grouped by week | unit |
| `test_ohlcv_bars_max_bars_truncation` | `max_bars=5` → only 5 bars returned (most recent) | unit |

Minimum: 9 unit tests.

**Acceptance criteria**:
- [ ] Literal route `/ohlcv/bars` registered before `/{instrument_id}` catch-all — no routing collision
- [ ] `time_bucket` query used for resampling (not application-side aggregation)
- [ ] Response always includes resolved `instrument_id` (UUID) and `ticker`
- [ ] Response `bars` ordered `date ASC`
- [ ] `S3_OHLCV_MAX_DAYS` env var documented in `env/dev/market-data.env.example`

---

##### T-W10-G-02: `GET /api/v1/fundamentals/history` — quarterly fundamentals history in S3
**Type**: impl
**depends_on**: none
**blocks**: T-W10-H-01
**Target files**:
- `services/market-data/src/market_data/api/routers/fundamentals.py` (modify — register new literal route **before** `/{instrument_id}` catch-all; note the existing UUID pattern guard on `/{instrument_id}` already prevents literal strings from being swallowed, but register early for clarity)
- `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py` (new) — `GetFundamentalsHistoryUseCase` (NEW — created in Wave G)

> **ARCH NOTE (N-10)**: There is no single `fundamentals_records` table. S3 stores fundamentals in per-type tables populated by `FundamentalsRecord`. The quarterly history source is the existing `earnings_history` table (same data source as `GET /fundamentals/{id}/earnings`). `GetFundamentalsHistoryUseCase` queries `IEarningsRepository` — check `application/ports/repositories.py` for the correct method.
> **ARCH NOTE (R25)**: New route uses `Depends(...)` DI — never imports a repository class directly in the router.
> **ARCH NOTE (R27)**: Read-only — use `ReadUoWDep`.

**API Spec**:
```
GET /api/v1/fundamentals/history
  ?instrument_id=<UUID>         # optional — instrument UUID
  ?symbol=AAPL                  # optional — ticker symbol
  ?isin=US0378331005            # optional — 12-char ISIN
  # At least one of the above three is required (400 if none supplied)
  ?periods=8                    # number of quarters, max 20, default 8

Response: {
  instrument_id: str,           -- resolved UUID (always present)
  ticker: str,                  -- resolved symbol
  periods: [{
    period: str,                -- e.g. "Q1 2026"
    period_end_date: str,
    revenue: float | null,
    gross_profit: float | null,
    net_income: float | null,
    eps: float | null,
    pe_ratio: float | null,
    market_cap: float | null
  }],
  period_count: int
}

Errors:
  400  — none of instrument_id / symbol / isin supplied
  404  — instrument not found
  422  — periods out of range (> 20)
```

**Router handler sketch** (same identifier-resolution pattern as T-W10-G-01):
```python
# Register near top of fundamentals.py (before /{instrument_id} routes)
@router.get("/fundamentals/history", response_model=FundamentalsHistoryResponse)
async def get_fundamentals_history_flexible(
    instrument_id: Annotated[UUID | None, Query()] = None,
    symbol: Annotated[str | None, Query(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")] = None,
    isin: Annotated[str | None, Query(min_length=12, max_length=12, pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")] = None,
    periods: int = Query(default=8, ge=1, le=20),
    uc: Annotated[GetFundamentalsHistoryUseCase, Depends(get_fundamentals_history_uc)] = ...,
    lookup_uc: Annotated[InstrumentLookupUseCase, Depends(get_lookup_instrument_uc)] = ...,
) -> FundamentalsHistoryResponse:
    if instrument_id is None and symbol is None and isin is None:
        raise HTTPException(status_code=400, detail="At least one of instrument_id, symbol, or isin is required")
    ...
```

**Logic**:
1. **Resolve instrument**: same as T-W10-G-01 — `InstrumentLookupUseCase.execute(id, isin, symbol)`. Raise 404 on `InstrumentNotFoundError`.
2. **Query**: pass resolved `instrument_id` (UUID) to `GetFundamentalsHistoryUseCase.execute()`. Query `IEarningsRepository` for the last `periods` records ordered `period_end_date DESC`, then return ordered `ASC`. Fields are nullable — include all 7 (null when absent). Do NOT query a `fundamentals_records` table (N-10).
3. **Response**: always include resolved `instrument_id` and `ticker`.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_fundamentals_history_resolves_by_symbol` | `?symbol=AAPL` → lookup called; resolved UUID used | unit |
| `test_fundamentals_history_resolves_by_isin` | `?isin=...` → lookup called with isin | unit |
| `test_fundamentals_history_returns_400_if_no_identifier` | no identifier params → 400 | unit |
| `test_fundamentals_history_returns_404_if_not_found` | lookup raises `InstrumentNotFoundError` → 404 | unit |
| `test_fundamentals_history_returns_n_periods` | `periods=4` → at most 4 period records | unit |
| `test_fundamentals_history_ordered_asc` | periods returned oldest-first | unit |
| `test_fundamentals_history_null_fields_present` | instruments with partial data (no EPS) → null fields in response, not absent | unit |

Minimum: 7 unit tests.

**Acceptance criteria**:
- [ ] `periods` capped at 20 (Query constraint, not application logic)
- [ ] Response includes all 7 financial fields (null when unavailable)
- [ ] Response always includes resolved `instrument_id` and `ticker`
- [ ] Literal route registered before `/{instrument_id}` catch-all

---

##### T-W10-G-03: S8 `S3Port` extension + `S3Client` implementation
**Type**: impl
**depends_on**: T-W10-G-01, T-W10-G-02
**blocks**: T-W10-H-02
**Target files**:
- `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` (modify — extend `S3Port`)
- `services/rag-chat/src/rag_chat/infrastructure/clients/s3_client.py` (modify — implement new methods)

**What to build**:
Add to `S3Port` Protocol (NEW methods — added in Wave G):

> **ARCH NOTE (R25)**: Methods are added to `S3Port` (Protocol in `application/ports/upstream_clients.py`). `S3Client` in `infrastructure/clients/s3_client.py` implements them. Use cases depend on `S3Port`, never on `S3Client` directly.

The port methods accept all three identifiers as keyword-only args. The caller (LLM tool handler) passes whichever it has — typically `ticker` from the LLM output. `S3Client` forwards them as query params; S3 resolves server-side. This eliminates the `find_instrument_by_ticker` pre-resolution call that would otherwise be needed from S8.

```python
async def get_ohlcv_range(
    self,
    *,
    from_date: date,
    to_date: date,
    interval: str = "day",
    instrument_id: str | None = None,   # UUID string
    ticker: str | None = None,          # e.g. "AAPL"
    isin: str | None = None,            # 12-char ISIN
) -> list[dict]:
    """Return OHLCV bars in date range. At least one of instrument_id/ticker/isin required.
    Returns [] on any HTTP error (safe degradation). Response includes resolved instrument_id."""
    ...

async def get_fundamentals_history(
    self,
    *,
    periods: int = 8,
    instrument_id: str | None = None,
    ticker: str | None = None,
    isin: str | None = None,
) -> list[dict]:
    """Return quarterly fundamentals history. At least one identifier required.
    Returns [] on any HTTP error (safe degradation)."""
    ...
```

`S3Client` implementation — build query params from whichever identifiers are set:
```python
async def get_ohlcv_range(self, *, from_date, to_date, interval="day",
                          instrument_id=None, ticker=None, isin=None) -> list[dict]:
    params: dict[str, str] = {
        "from_date": str(from_date),
        "to_date": str(to_date),
        "interval": interval,
    }
    if instrument_id:
        params["instrument_id"] = instrument_id
    elif isin:
        params["isin"] = isin
    elif ticker:
        params["symbol"] = ticker
    # S3 enforces at least one — if all None, S3 returns 400 → caught below → []
    return await self._get("/api/v1/ohlcv/bars", params=params)

async def get_fundamentals_history(self, *, periods=8,
                                   instrument_id=None, ticker=None, isin=None) -> list[dict]:
    params: dict[str, str] = {"periods": str(periods)}
    if instrument_id:
        params["instrument_id"] = instrument_id
    elif isin:
        params["isin"] = isin
    elif ticker:
        params["symbol"] = ticker
    return await self._get("/api/v1/fundamentals/history", params=params)
```

Both `_get` calls return `[]` on any HTTP error (4xx/5xx) via the existing base client error handling — safe degradation per port contract.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_s3_get_ohlcv_range_by_ticker` | `ticker="AAPL"` → `symbol=AAPL` in query params | unit (mock HTTP) |
| `test_s3_get_ohlcv_range_by_isin` | `isin=...` → `isin=...` in query params | unit (mock HTTP) |
| `test_s3_get_ohlcv_range_by_instrument_id` | `instrument_id=<UUID>` → `instrument_id=...` in query params | unit (mock HTTP) |
| `test_s3_get_ohlcv_range_returns_empty_on_404` | HTTP 404 → empty list, no exception | unit |
| `test_s3_get_ohlcv_range_returns_empty_on_400` | HTTP 400 (no identifier) → empty list, no exception | unit |
| `test_s3_get_fundamentals_history_by_ticker` | `ticker="MSFT"` → `symbol=MSFT` in query params | unit (mock HTTP) |
| `test_s3_get_fundamentals_history_parses_periods` | response `periods[]` parsed correctly | unit |

Minimum: 7 unit tests.

**Acceptance criteria**:
- [ ] Both methods added to `S3Port` Protocol (runtime-checkable)
- [ ] `S3Client` passes exactly one identifier param (priority: instrument_id > isin > ticker)
- [ ] `S3Client` returns `[]` (not raises) on any HTTP error

---

#### Validation Gate — Wave G
- [ ] `ruff` + `mypy` pass on S3 and S8
- [ ] 23 new tests pass (9 + 7 + 7)
- [ ] Existing S3 tests unaffected (new routes are additive; no existing endpoint modified)
- [ ] `GET /api/v1/ohlcv/bulk` still resolves correctly (literal route ordering not broken by new `/bars` literal)

#### Break Impact — Wave G
| Broken file | Why | Fix |
|---|---|---|
| `services/rag-chat/tests/unit/test_s3_client*.py` | `S3Port` Protocol gains 2 methods — any mock must implement them | add stub implementations returning `[]` |
| `services/market-data/env/dev/market-data.env.example` | new `S3_OHLCV_MAX_DAYS` env var | add with default `365` |
| `services/market-data/src/market_data/api/dependencies.py` | new `get_ohlcv_bars_uc` + `get_fundamentals_history_uc` DI providers needed | add provider functions (same pattern as existing providers) |

#### Regression Guardrails — Wave G
- BP-025/026/027 (external I/O): S3Client calls S3 market-data over HTTP; follows existing `_get()` base client pattern with `asyncio.wait_for(timeout=5.0)`.
- Literal route ordering: `/ohlcv/bars` must appear in the router registration list AFTER `/ohlcv/bulk` but BEFORE `/{instrument_id}`. Confirm with a route-ordering smoke test that `GET /ohlcv/bars?symbol=AAPL...` does not 422 with "Invalid instrument_id format".

---

### Wave H: Tool-Use Loop — Temporal RAG via Option B Architecture ✓ DONE 2026-05-08

**Goal**: Expose the new S3 temporal endpoints as LLM-callable tools. The LLM receives a capability manifest in its system prompt and emits typed `tool_use` blocks at generation time; `ToolExecutor` runs them and injects results before the final answer. The existing intent classification + parallel retrieval pipeline is untouched.
**Depends on**: Wave G (T-W10-G-03 — S3Port methods must exist)
**Estimated effort**: 90 min
**Architecture layer**: libs (ToolRegistry) + S8 application (ToolExecutor, ChatOrchestrator)

#### Pre-read
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` — `execute_streaming()` and `execute_sync()` methods (NOT `handle()` — N-6). Post-PLAN-0077, the use case takes a `ChatPipeline` constructor arg.
- `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` — `S3Port` Protocol (after Wave G)
- `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py` — existing SSE event format (NOT `infrastructure/streaming/` — N-4)
- `services/rag-chat/src/rag_chat/infrastructure/llm/` — existing LLM client, how tool_use blocks are parsed

#### Tasks

##### T-W10-H-01: `ToolSpec` + `ToolRegistry` + `capability_manifest.yaml`
**Type**: impl
**depends_on**: none
**blocks**: T-W10-H-02, T-W10-H-03
**Target files**:
- `libs/tools/__init__.py` (NEW — `libs/tools/` lib does NOT exist yet, must be created in Wave H — N-8)
- `libs/tools/tool_spec.py` (NEW — created in Wave H)
- `libs/tools/tool_registry.py` (NEW — created in Wave H)
- `libs/tools/capability_manifest.yaml` (NEW — created in Wave H — R29 entry)

> **ARCH NOTE**: `libs/tools/` is a new shared Python library. It needs: `pyproject.toml` (hatch packaging), `src/tools/__init__.py`, and must be added to `PYTHONPATH` in the rag-chat Dockerfile (same pattern as `libs/ml-clients`). See BP-181 — missing lib COPY+install in Dockerfile causes `ModuleNotFoundError` at startup.

**What to build**:

`ToolSpec` (dataclass in `tool_spec.py`):
```python
@dataclass
class ParameterSpec:
    name: str
    type: str                     # "string" | "date" | "integer"
    description: str
    required: bool = True
    enum: list[str] | None = None

@dataclass
class ToolSpec:
    name: str                     # matches tool_use block "name"
    description: str              # LLM sees this to decide when to call
    parameters: list[ParameterSpec]
    source_type: str              # used by TrustScorer (R29 note: trust_weight NOT stored on manifest entries — TrustScorer computes it at retrieval time from SOURCE_AUTHORITY × recency_decay × corroboration × extraction_confidence)
    example_queries: list[str]    # included in capability manifest for few-shot
```

> **ARCH NOTE (R29)**: Per R29 (updated 2026-05-07), per-tool `trust_weight` is NOT set on manifest entries. `TrustScorer` computes trust per-item at retrieval time. The manifest references `source_type` so `TrustScorer` can look up authority. The `ToolExecutor` handlers set `trust_weight` at result construction time based on the source authority lookup, not a manifest field.

`ToolRegistry` (in `tool_registry.py`):
```python
class ToolRegistry:
    def register(self, spec: ToolSpec, handler: Callable) -> None: ...
    def get_spec(self, name: str) -> ToolSpec | None: ...
    def get_handler(self, name: str) -> Callable | None: ...
    def all_specs(self) -> list[ToolSpec]: ...
    def to_system_prompt_section(self) -> str:
        """Render the manifest as a fenced YAML block for the system prompt."""
```

`capability_manifest.yaml` (R29 — every registered tool must have an entry):
```yaml
version: "1"
tools:
  - name: get_price_history
    description: >
      Fetches OHLCV (open/high/low/close/volume) bar history for a stock ticker
      over a specified date range. Use when the user asks about price movement,
      trend, range, or performance over a time period.
    parameters:
      - name: ticker
        type: string
        description: Stock ticker symbol (e.g. "AAPL")
        required: true
      - name: from_date
        type: date
        description: Start of date range (YYYY-MM-DD)
        required: true
      - name: to_date
        type: date
        description: End of date range (YYYY-MM-DD)
        required: true
      - name: interval
        type: string
        enum: [day, week, month]
        description: Bar granularity. Default "week".
        required: false
    source_type: ohlcv          # used by TrustScorer — trust_weight NOT stored here (PLAN-0067 §0 A-2)
    example_queries:
      - "How has AAPL performed over the last 3 months?"
      - "What was NVDA's price range in Q1 2026?"

  - name: get_fundamentals_history
    description: >
      Fetches quarterly fundamental metrics (revenue, gross profit, net income,
      EPS, P/E ratio, market cap) for a ticker over N periods. Use when the user
      asks about revenue trends, EPS growth, or multi-quarter financial performance.
    parameters:
      - name: ticker
        type: string
        description: Stock ticker symbol (e.g. "MSFT")
        required: true
      - name: periods
        type: integer
        description: Number of quarters to return (1–20). Default 8.
        required: false
    source_type: fundamentals   # used by TrustScorer — trust_weight NOT stored here (PLAN-0067 §0 A-2)
    example_queries:
      - "Show me MSFT's revenue trend over 8 quarters"
      - "What has AAPL's EPS been over the last 2 years?"
```

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_registry_get_spec_returns_registered_tool` | registered tool spec retrievable by name | unit |
| `test_registry_get_spec_unknown_returns_none` | unknown tool name → `None` | unit |
| `test_registry_to_system_prompt_section_contains_tool_names` | manifest section includes both tool names | unit |
| `test_manifest_yaml_has_entry_for_every_registered_tool` | architecture invariant: YAML entries ↔ registered tools match | unit (architecture) |

Minimum: 4 unit tests.

**Acceptance criteria**:
- [x] `capability_manifest.yaml` has entries for both tools (R29)
- [x] `ToolRegistry.to_system_prompt_section()` renders valid YAML block the LLM can parse
- [x] Architecture test `test_manifest_yaml_has_entry_for_every_registered_tool` passes

---

##### T-W10-H-02: `ToolExecutor` — runs `tool_use` blocks against S3Port
**Type**: impl
**depends_on**: T-W10-H-01, T-W10-G-03
**blocks**: T-W10-H-03
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py` (NEW — created in Wave H)

> **ARCH NOTE (R25)**: `ToolExecutor` is in the APPLICATION layer (`application/pipeline/`). It depends on `S3Port` (Protocol), never on `S3Client` (infra). Injected via constructor.
> **ARCH NOTE (structlog — N-9)**: Use `import structlog; log = structlog.get_logger(__name__)  # type: ignore[no-any-return]`. Never `import logging`. (The reference to `R-012` in earlier drafts was incorrect — there is no such rule number. The structlog requirement comes from STANDARDS.md §5.)

**What to build**:
```python
class ToolExecutor:
    def __init__(self, registry: ToolRegistry, s3: S3Port) -> None: ...

    async def execute(
        self,
        tool_call: ToolUseBlock,           # {"name": str, "input": dict}
    ) -> RetrievedItem | None:
        """
        Dispatches to the correct handler.
        Returns a RetrievedItem (trust_weight from ToolSpec), or None on any error.
        Never raises — errors are logged and swallowed (graceful degradation).
        """

    async def execute_all(
        self,
        tool_calls: list[ToolUseBlock],
    ) -> list[RetrievedItem]:
        """Run all tool calls concurrently (asyncio.gather). Cap at 5 calls."""
```

**Structured logging** (required — STANDARDS.md §5, structlog only):
```python
import structlog
log = structlog.get_logger(__name__)  # type: ignore[no-any-return]
```
Every `execute()` call must emit:
- `log.info("tool_executed", tool=call.name, latency_ms=round((t1-t0)*1000), items_returned=1 if result else 0)` on success
- `log.warning("tool_failed", tool=call.name, error=str(e))` on any exception
- `log.warning("unknown_tool_name", name=call.name)` when the tool name is not in the registry (instead of silently returning `None`) — this catches hallucinated tool names

**Handler implementations** (private methods on `ToolExecutor`):

`_TOOL_RESULT_MAX_CHARS = 4000` — class-level constant. Prevents context window overflow when OHLCV data (252 bars × ~50 chars ≈ 12,600 chars) or chunk results are injected into messages.

`_handle_get_price_history(ticker, from_date, to_date, interval="week")`:
1. `bars = await self._s3.get_ohlcv_range(ticker=ticker, from_date=from_date, to_date=to_date, interval=interval)` — S3Port accepts `ticker=` directly; S3 resolves server-side (Wave G). No pre-resolution call needed.
2. If `bars` is empty: `log.warning("tool_no_data", tool="get_price_history", ticker=ticker)` and return `None`.
3. Format as markdown table (truncate to `_TOOL_RESULT_MAX_CHARS`):
   ```
   AAPL price history (weekly, 2026-02-03 → 2026-05-03)
   | Date       | Close  | Volume |
   |------------|--------|--------|
   | 2026-02-07 | $185.2 | 52M    |
   ...
   ```
4. Return `RetrievedItem.create(item_id=f"tool:price_history:{ticker}", item_type=ItemType.financial, text=table_text[:_TOOL_RESULT_MAX_CHARS], score=0.88, trust_weight=0.90)` — CRITICAL: field is `text` NOT `content` (N-7); use `.create()` factory (never direct construction — `fusion_score` invariant); `trust_weight=0.90` is a sensible default pending `TrustScorer` wiring (R29).

`_handle_get_fundamentals_history(ticker, periods=8)`:
1. `data = await self._s3.get_fundamentals_history(ticker=ticker, periods=periods)` — same single-call pattern; S3 resolves server-side.
2. If `data` is empty: log warning and return `None`.
3. Format as markdown table (Period | Revenue | Gross Profit | Net Income | EPS | P/E).
4. Return `RetrievedItem.create(item_id=f"tool:fundamentals:{ticker}", item_type=ItemType.financial, text=table_text[:_TOOL_RESULT_MAX_CHARS], score=0.88, trust_weight=0.90)` — same `text` field note (N-7).

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_executor_price_history_passes_ticker_to_port` | `ticker="AAPL"` → `s3.get_ohlcv_range` called with `ticker="AAPL"` (no find_instrument_by_ticker call) | unit (mock S3) |
| `test_executor_price_history_formats_markdown_table` | bars → RetrievedItem text contains markdown table header | unit (mock S3) |
| `test_executor_returns_none_on_empty_bars` | `get_ohlcv_range` returns `[]` → `None` returned, warning logged | unit |
| `test_executor_returns_none_on_s3_error` | `get_ohlcv_range` raises → `None` returned, no exception propagated | unit |
| `test_executor_execute_all_runs_concurrently` | two tool calls → both handlers called (mock verify) | unit |
| `test_executor_execute_all_caps_at_5` | 8 tool_calls → only 5 executed | unit |
| `test_executor_fundamentals_formats_markdown_table` | periods → RetrievedItem with Period column | unit |
| `test_executor_unknown_tool_name_logs_warning` | unregistered tool name → `log.warning("unknown_tool_name")` emitted, `None` returned | unit |
| `test_executor_tool_result_truncated_at_max_chars` | formatter produces > 4000 chars → `RetrievedItem.text` ≤ 4000 chars (N-7: field is `text` not `content`) | unit |

Minimum: 9 unit tests.

**Acceptance criteria**:
- [x] `execute_all` uses `asyncio.gather` (not sequential)
- [x] `execute_all` cap at 5 tool calls (prevents runaway LLM behavior)
- [x] Any exception in a handler logs a `tool_failed` warning and returns `None` — never propagates
- [x] Unknown tool names log `unknown_tool_name` warning (observable in prod logs)
- [x] Tool result content truncated to `_TOOL_RESULT_MAX_CHARS = 4000` before returning

---

##### T-W10-H-03: `ChatOrchestratorUseCase` tool-use loop
**Type**: impl
**depends_on**: T-W10-H-01, T-W10-H-02
**blocks**: T-W10-H-04
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` (modify)
- `services/rag-chat/src/rag_chat/api/dependencies.py` (modify — inject `ToolExecutor`) — NOTE: no `infrastructure/wiring/` directory exists (N-5); DI file is `api/dependencies.py`

**What to build**:

Add `_tool_executor: ToolExecutor | None` as an optional constructor argument on `ChatOrchestratorUseCase`.

> **ARCH NOTE (N-6)**: Post-PLAN-0077, `ChatOrchestratorUseCase` has methods `execute_streaming()` and `execute_sync()` — NOT `handle()`. The tool-use loop is inserted in `execute_streaming()` (and optionally `execute_sync()`) after the initial retrieval context is assembled (via `ChatPipeline` steps).
> **ARCH NOTE (R30)**: `ToolExecutor` must NOT hold per-request state (no `user_id`, `tenant_id`, or `jwt` in `ToolExecutor.__init__`). These are passed at call time if needed (they aren't for S3 queries).

In `execute_streaming()`, after building the initial retrieval context (Path 1 unchanged):
1. Include `self._tool_executor._registry.to_system_prompt_section()` in the system prompt when `_tool_executor` is not `None`.
2. Call LLM (first turn). Parse the response for `tool_use` blocks.
3. If no `tool_use` blocks (typical classical query): stream answer directly (no change to existing flow).
4. If `tool_use` blocks present:
   ```python
   tool_items = await self._tool_executor.execute_all(tool_calls)
   # Inject non-None items into retrieved_items list
   retrieved_items.extend(i for i in tool_items if i is not None)
   # Second LLM call: same system prompt, same context + tool results appended
   final_response = await self._llm.generate(
       query, context=retrieved_items, prior_exchange=first_response
   )
   ```
5. Stream the final response.

**Max iterations**: cap the tool loop at 2 turns (1 tool call round + 1 final answer) for the MVP. Log a warning if the LLM emits tool_use again after the first tool round and treat the second response as the final answer.

**All-tools-failed guard** (R-013): if `execute_all` returns a list where all items are `None` (all tools failed or returned empty), the system MUST NOT silently proceed to the final LLM call with zero context — it will hallucinate. Instead:
```python
non_none_items = [i for i in tool_items if i is not None]
if not non_none_items:
    log.warning("all_tools_failed", tool_count=len(tool_calls), query=request.query[:100])
    # Fall through to classical path — do NOT call second LLM turn with empty context
    # The classical pipeline result (initial retrieval) becomes the final answer
    return  # let the caller stream the already-built classical context
```
This ensures the user always gets an answer grounded in at least the classical retrieval, even when all tool calls fail.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_orchestrator_no_tool_use_follows_existing_path` | LLM returns no tool_use → `execute_all` not called | unit (mock) |
| `test_orchestrator_tool_use_injects_results` | LLM emits tool_use → executor called → results in second LLM call | unit (mock) |
| `test_orchestrator_tool_loop_capped_at_2_turns` | second LLM response still has tool_use → treated as final | unit |
| `test_orchestrator_tool_none_results_filtered` | executor returns None items → not added to context | unit |
| `test_orchestrator_all_tools_failed_falls_back_to_classical` | all tool items None → second LLM turn NOT called, warning logged | unit |

Minimum: 5 unit tests.

**Acceptance criteria**:
- [x] `_tool_executor` is optional — `None` means feature is disabled without code change
- [x] Tool loop never exceeds 2 LLM turns
- [x] Existing tests pass with `tool_executor=None` (no behavior change for classical queries)
- [x] All-tools-failed logs `all_tools_failed` warning and falls back — never produces a hallucianted answer on zero context

---

##### T-W10-H-04: SSE streaming tool progress events
**Type**: impl
**depends_on**: T-W10-H-03
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` (modify — add SSE emissions)
- `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py` (modify — new event type) — NOTE: SSEEmitter lives in `application/pipeline/`, NOT `infrastructure/streaming/` (N-4)

**What to build**:

Before calling `execute_all`, emit one SSE event per tool call:
```python
for call in tool_calls:
    await sse_emitter.emit({
        "type": "tool_call",
        "tool": call.name,
        "input": call.input,
        "status": "running",
    })
```

After `execute_all` completes, emit a `tool_result` event for each tool:
```python
await sse_emitter.emit({
    "type": "tool_result",
    "tool": call.name,
    "status": "ok" if item is not None else "error",
})
```

The frontend UI (implemented in PLAN-0067 when tool use goes to all sources) uses `tool_call` events to show a spinner: `"Fetching AAPL price history..."`. For the PLAN-0066 MVP, the frontend does not yet consume these events — they are emitted and silently ignored by the current client.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_sse_tool_call_event_emitted_before_execute` | `tool_call` event emitted before `execute_all` call | unit (mock emitter) |
| `test_sse_tool_result_ok_emitted_on_success` | successful tool → `status: "ok"` emitted | unit |
| `test_sse_tool_result_error_emitted_on_none` | executor returns None → `status: "error"` emitted | unit |

Minimum: 3 unit tests.

**Acceptance criteria**:
- [x] `tool_call` event emitted before execution (enables streaming UI to show spinner immediately)
- [x] `tool_result` event always emitted (success or failure) — frontend can rely on it to close spinner

---

#### Validation Gate — Wave H
- [x] `ruff` + `mypy` pass on `libs/tools/` and `services/rag-chat/`
- [ ] 17 new tests pass (4+6+4+3)
- [ ] Existing 50-query golden set (PLAN-0063 Wave W5-1) passes — no regressions (tool loop is a no-op when LLM emits no tool_use blocks)
- [ ] Architecture test `test_manifest_yaml_has_entry_for_every_registered_tool` passes
- [ ] `pnpm vitest` — no frontend regressions

#### Break Impact — Wave H
| Broken file | Why | Fix |
|---|---|---|
| Any test mocking `S3Port` | new `get_ohlcv_range` + `get_fundamentals_history` methods required by Protocol (from Wave G T-W10-G-03) | add stub implementations |
| `services/rag-chat/tests/unit/use_cases/test_chat_orchestrator.py` | `ChatOrchestratorUseCase` constructor gains `tool_executor` arg | pass `tool_executor=None` in existing test fixtures |
| `services/rag-chat/src/rag_chat/api/dependencies.py` | `ToolExecutor` must be injected (N-5: no `infrastructure/wiring/` dir exists) | add `ToolExecutor` construction with `ToolRegistry` wired to S3Port |

#### Regression Guardrails — Wave H
- BP-025 (external I/O timeout): `ToolExecutor` handlers wrap S3 calls in `asyncio.wait_for(timeout=5.0)` — same pattern as all existing orchestrator fetch methods.
- Tool loop cap: the 2-turn max prevents infinite loops if the LLM keeps emitting tool_use blocks. Log a warning at turn 2 so the behavior is observable.
- R29: `capability_manifest.yaml` must be updated before merging any future tool additions — architecture test enforces this.

---

## 7. Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| PLAN-0062-W4 delayed — dependency not yet shipped | HIGH | All waves A–F depend on `BriefBullet`/`BriefCitation` being in prod. Do not merge PLAN-0066 branches until PLAN-0062-W4 is merged. |
| brief_archive persistence failure visible to user | MEDIUM | `asyncio.shield` in persistence hook — DB failure is logged, not propagated to HTTP response. |
| Implicit RAG seed inflates context window | MEDIUM | Cap: 8 seed items; each citation.snippet ≤400 chars = max 3,200 chars. Well within 8k context budget. |
| LLM calls tools on every query (unexpected tool_use blocks) | MEDIUM | Tool loop capped at 2 turns; tool descriptions scoped to temporal queries only. Monitor `tool_call` SSE events in staging to verify tool use rate is < 5% of queries on the 50-query golden set (none should trigger tools). |
| Tool executor returns `None` for all calls (silent degradation) | LOW | `tool_result` SSE event with `status: "error"` provides observability. LLM continues with classical context only — answer may be incomplete but system doesn't fail. |
| S3 OHLCV endpoint returns large datasets | LOW | `max_bars=252` cap + `S3_OHLCV_MAX_DAYS=365` env var. |
| Diff computation is slow on large section sets | LOW | Text comparison on ≤4×4 = ≤16 bullets per brief — O(N²) comparison is < 1ms. |
| Full NL→SQL (TTYD path) misses the thesis demo | LOW | Parameterised dispatch (Waves G+H) covers all demo scenarios. TTYD deferred as an ADR candidate. |

---

## 8. Open Questions

| OQ | Question | Decision Needed By |
|---|---|---|
| OQ-1 | Should `user_briefs` rows be deleted after 30 days (GDPR) or kept indefinitely? | Before Wave A |
| OQ-2 | Brief feedback: should we enforce one feedback entry per (user, brief, scope, bullet)? Currently allows multiple. | Before Wave C |
| OQ-3 | Full TTYD NL→SQL integration (ADR): should we scope a follow-on plan for NL→SQL over TimescaleDB? The tool-use loop in Wave H is the stepping stone — the same `ToolExecutor` can host a future `execute_sql` tool. | Post-thesis |
| OQ-5 | PLAN-0067 scope: should PLAN-0067 migrate ALL retrieval sources (chunks, relations, graph, claims, events) into the tool catalog and retire the intent classifier, or add sources incrementally? | Before PLAN-0067 kick-off |
| OQ-4 | Should the "Discuss in Chat" button create a brand-new thread every click, or reuse an existing seeded thread for the same brief? | Before Wave D — recommendation: always create new (user intention is explicit) |

---

## 9. Dependency Graph

```
PLAN-0062-W4 Waves A–E (must ship first)
      │
      ├── Wave A (DB schema) ──────────────────────────────────────────────────────────┐
      │         │                                                                       │
      │    Wave B (brief archive) ──────┬─────────────────────────────────────────────┐│
      │         │                       │                                             ││
      │    Wave C (diff + feedback) ──┐  Wave D (chat seeding) ──────────────────────┐││
      │                               │                │                             │││
      │                               └──── Wave E (S9 proxies) ────────────────────┘││
      │                                          │                                    ││
      │                                     Wave F (frontend)  ←──────────────────────┘│
      │                                                                                 │
      └── Wave G (S3 temporal endpoints) ─→ Wave H (ToolRegistry + ToolExecutor + tool loop) │
                                                                                        │
      All: PLAN-0062-W4 is a hard prerequisite for Waves A–F ──────────────────────────┘
      Waves G–H are parallel-safe with Waves A–F (different services)
```

**Critical path**: PLAN-0062-W4 → Wave A → Wave B → Wave D → Wave E → Wave F

**Parallel tracks**:
- G + H (S3 temporal) can run concurrently with A–F in a separate worktree
- Wave C (diff + feedback) parallel with Wave D (chat seeding) after Wave B

---

## 10. Compounding Check

Before closing this plan session, the following documents should be updated:

| Document | Update |
|---|---|
| `docs/services/rag-chat.md` | New endpoints: `/v1/briefings/morning/history`, `/v1/briefings/morning/diff`, `/v1/briefings/feedback/bullet`, `/v1/briefings/feedback/brief`, `/v1/briefings/chat/discuss`; new DB tables `user_briefs` + `brief_feedback`; Wave H tool-use loop (ToolRegistry, ToolExecutor, capability manifest) |
| `docs/services/market-data.md` | New endpoints: `GET /api/v1/ohlcv/{instrument_id}/bars` (N-2/N-3 corrected from instruments URL) and `GET /api/v1/fundamentals/{id}/history` (N-10 — reads earnings_history table); new env var `S3_OHLCV_MAX_DAYS` |
| `docs/BUG_PATTERNS.md` | Add BP-NEW: "Brief RAG seed context overflow" — if brief citations are too many / snippets too long, they can crowd out other retrieval sources. Cap: 8 items × 400 chars max = mitigated |
| `RULES.md` | No new rules needed; existing R8/R24/R27 cover all patterns in this plan |
