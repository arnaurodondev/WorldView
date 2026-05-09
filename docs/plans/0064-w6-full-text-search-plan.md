---
id: PLAN-0064
prd: docs/specs/0034-mvp-launch-readiness-program.md
prd_section: §3 FR-T1-3 + §6 Workstream W6 + §8 AD-1
title: "W6 — Full-Text Search with Entity Facets (Tier 1, FR-T1-3)"
status: draft
created: 2026-05-03
updated: 2026-05-09
plans: 1
waves: 5
tasks: 15
---

# PLAN-0064 — W6 Full-Text Search with Entity Facets

> **Scope**: PRD-0034 Workstream W6 only. The keystone L1 feature: a search route across articles + EDGAR filings (transcripts deferred — see §0 Known Limitations) with entity facets sourced from KG resolution.
>
> **Out of scope** (other plans): retrieval/RAG hybrid search inside the AI pipeline (W5 / PLAN-0063 — supersedes PLAN-0060 Sub-Plan B), structured AI brief (W4), WebSocket quote stream (W7), RLS + Stripe (W8), observability (W9). This plan deliberately reuses W5's `chunks.tsv_english` GIN index (`ix_chunks_tsv_english_gin`) rather than building a parallel one.

---

## 0. Cross-Plan Decisions (locked 2026-05-03 — do not re-litigate)

These decisions were taken at the inter-plan boundary review on 2026-05-03 and are **frozen** for PLAN-0064:

1. **`chunks.tsv_english` / `chunks.tsv_simple` ownership** — owned by **PLAN-0063 Wave W5-2** (alembic migration `0017_add_chunks_tsv_english_gin.py`). PLAN-0060 Sub-Plan B was superseded by PLAN-0063 on 2026-05-03 (TRACKING.md lines 32, 35). PLAN-0064 does not redefine the columns or the indexes — it **reuses** them. **SHIPPED**: migration 0017 is live (alembic head is now `0019_add_tenant_id_to_chunks_sections`; index `ix_chunks_tsv_english_gin` confirmed in prod as of 2026-05-06).
2. **FTS GIN index name** — `ix_chunks_tsv_english_gin` (SQLAlchemy `ix_` convention). All `EXPLAIN ANALYZE` assertions and Prometheus checks reference this exact name.
3. **FTS tsquery parser** — `websearch_to_tsquery` (handles user-facing query syntax including quoted phrases and OR / `-` operators). PLAN-0064 SQL **does NOT use** `plainto_tsquery`. `websearch_to_tsquery` does the same input-escaping job (no string concat, no injection vector) while supporting richer operator semantics suited to a public search box.
4. **`documents.tsv` is NOT added** — PLAN-0064 aggregates chunks → document at query time; this supersedes PLAN-0063 §0's earlier expectation that W6 would add `documents.tsv`. PLAN-0063 §0 should be amended to reflect this resolution (cross-plan note).

### Architecture Compliance Adjustments (vs initial draft)

| Claim | Adjusted state | Reason |
|-------|----------------|--------|
| R27 (read replica for read-only use case) | **NOT CLAIMED** for this plan. nlp-pipeline currently has a single pool — there is no `ReadOnlyUnitOfWork` / `ReadUoWDep` abstraction in S6. For MVP a single-pool read is acceptable. Tracked as a follow-up (§15). | `grep -rn "ReadOnlyUnitOfWork" services/nlp-pipeline/src/` returns zero hits. The repo abstraction does not exist; pretending it does would silently mis-route to the writer pool. |
| Per-day per-tenant rate limit on `/v1/search` | **NOT CLAIMED**. The existing `RateLimitMiddleware` is global per-user, per-minute (default 100/60s). PLAN-0064 relies on this existing global limit. A per-route, per-tenant, per-day limiter is deferred to the W8 RLS+Tier+Stripe plan (no plan ID yet — W8 plan not yet authored). **Note**: PLAN-0065 is W9 observability (complete 2026-05-04), NOT W8. | `services/api-gateway/src/api_gateway/middleware.py:298-410` has no per-route or per-bucket configuration; absorbing the refactor into W6 would balloon scope. |
| `canonical_entities` JOIN inside the search query | **REMOVED**. `canonical_entities` lives in `intelligence_db` (S6/S7 shared), not `nlp_db`. PLAN-0064 fetches entity names via S7 batch HTTP (`POST /api/v1/entities/batch`), symmetric to the existing S5 batch hop for document titles. | `services/nlp-pipeline/alembic/versions/*` does not create a `canonical_entities` table or view in nlp_db. No `entity_canonical_consumer.py` exists in S6. The view assumed by the initial draft is fictional. |

### Known Limitations (documented up front)

- **Transcripts not yet ingested.** `ContentSourceType` enum (`libs/contracts/src/contracts/enums.py`) currently has only `EODHD, SEC_EDGAR, FINNHUB, NEWSAPI, MANUAL, POLYMARKET`. There is no `transcript` value. The `source_type` filter on `/v1/search` therefore exposes only the values that actually map to ingested data: `news`, `sec_edgar`, `all`. `transcript` is **omitted from the enum** until ingestion ships (avoids the silent-zero-result trap noted in `feedback_prompt_input_mismatch.md`).
- **Anonymous search is rejected (401).** The route is authenticated via the existing OIDC middleware. Anonymous landing-page search is out of scope for MVP.
- **Per-chunk-max ranking, not BM25.** Documented in AD-W6-3.
- **Single-pool read.** No read replica for this plan — see Architecture Compliance Adjustments above.

---

## 1. Pre-Flight Gate

| Check | Result | Note |
|-------|--------|------|
| No unresolved BLOCKING OQs in §14 | **PASS** | OQ-1..OQ-4 are not blockers for this workstream. OQ-7 and OQ-11 **RESOLVED** — both resolved in §3 (AD-W6-5 + AD-W6-2). |
| External API field verification | **PASS** | W6 touches only internal data; no external API contract dependency. |
| Cross-plan conflict scan | **PASS** | PLAN-0063 Wave W5-2 **SHIPPED** (2026-05-06); alembic 0017 live; `ix_chunks_tsv_english_gin` + `ix_chunks_tsv_simple_gin` confirmed. Hard dependency for Wave 3 is **already met**. PLAN-0055 (universe expansion / W2) must ship before Wave 5 acceptance (≥1 entity-facet hit for any S&P 500 ticker). |
| PRD recency | **PASS** | PRD-0034 revised 2026-05-09 (revise-prd audit); plan revised 2026-05-09. |
| Architecture compliance | **PASS_WITH_NOTE** | Owner is S6 nlp-pipeline. R7 honoured (entity names via `POST /api/v1/entities/batch` to S7; document titles via `POST /api/v1/documents/batch` to S5; S9 proxies to S6 via HTTP). R24 honoured (GIN index in `nlp_db` owned by PLAN-0063 W5-2). R25 honoured (S6 API uses use cases). **R27 NOT claimed** — see §0 Architecture Compliance Adjustments. |

**Decision**: PASS. Plan is ready for `/implement`. Wave 3 dependency (PLAN-0063 W5-2) is already met. `/implement PLAN-0064 Wave 1` can start immediately.

---

## 2. Workstream Boundary Coordination

| Workstream | Plan | Touches | This plan's relationship |
|-----------|------|---------|--------------------------|
| W1 KG remediation | PLAN-0057 (complete) + PLAN-0060 Sub-Plan A | KG seeding, F-CRIT-07 fix, entity_mentions persistence | **Producer dependency**. We read entity_mentions; if it's empty, entity facets return zero. PLAN-0057 SHIP 2026-05-01 unblocks us. |
| W4 structured AI brief | PLAN-0062 (forthcoming) | rag-chat, S9 brief endpoint, frontend brief renderer | **No file overlap**. Both surface citations but to different endpoints. |
| W5 hybrid retrieval | **PLAN-0063** (supersedes PLAN-0060 Sub-Plan B) | adds `chunks.tsv_english` + `chunks.tsv_simple` + GINs (alembic 0017, indexes `ix_chunks_tsv_english_gin` + `ix_chunks_tsv_simple_gin`); adds `search_type=hybrid` to existing internal `/api/v1/search/chunks` (S6). **SHIPPED 2026-05-06** | **Dependency MET**. We reuse `ix_chunks_tsv_english_gin`. We add a *new* user-facing route `/api/v1/search/documents` which aggregates chunks → documents. We do not modify `/search/chunks`. |
| W8 RLS + tier + Stripe | **TBD** (plan not yet authored; note: PLAN-0065 is W9 observability — complete) | per-tier rate limits, Stripe webhooks, RLS hardening | **Soft dependency**. Per-tenant per-day rate limits for search live in W8, not here. PLAN-0064 relies on the existing global per-user-per-minute limit only. |
| W9 stability + observability | **PLAN-0065** (complete 2026-05-04) | Sentry, status page, BP-302 redeploy | **DONE**. We add `s6_search_*` Prometheus metrics in our own scope. |

**Hard ordering constraint**:
```
PLAN-0063 Wave W5-2 (tsv_english/tsv_simple GINs, alembic 0017)  ──►  PLAN-0064 Wave 3 (search query engine) [DEPENDENCY MET — 0017 shipped 2026-05-06]
PLAN-0055/0057 (universe + KG)                        ──►  PLAN-0064 Wave 5 (acceptance: ≥1 entity-facet hit per S&P 500 ticker)
```

If PLAN-0063 Wave W5-2 slips, we can land PLAN-0064 Waves 1, 2, 4, 5 (schema-only, repository, S9 proxy, frontend) and stub Wave 3's tsvector query against an empty index — but the acceptance gate fails until both ship.

---

## 3. Architecture Decisions (resolves OQ-7 and OQ-11)

### AD-W6-1: Owner is S6 nlp-pipeline (not S5 content-store, not a new search-service)

**Decision**: The search endpoint, query engine, and indexes live in **S6 nlp-pipeline** under `services/nlp-pipeline/src/nlp_pipeline/`.

**Rationale**:
- Entity facets require joining text matches to `entity_mentions` and `chunk_entity_mentions`, both of which live in `nlp_db` (S6's database). Putting search in S5 forces a cross-service join (R9 violation).
- `chunks.tsv_english` GIN index (PLAN-0063 Wave W5-2, alembic 0017, index `ix_chunks_tsv_english_gin`) already lives in `nlp_db.chunks`. Reusing it from S5 is impossible without breaking R9.
- A separate `search-service` is premature — it doubles operational surface for one query route.
- S6 already exposes `/api/v1/search/chunks` (internal, used by S8). Adding `/api/v1/search/documents` (public-via-S9, used by frontend) is a natural sibling.

**Reversibility**: Reversible. If load profile demands a dedicated search service later, the use case + repository in S6 can be lifted into a new pod with minimal refactor (the API contract stays stable).

### AD-W6-2: Postgres `tsvector` + GIN, not Algolia / Typesense

**Decision** (resolves OQ-11): Use Postgres `tsvector` with GIN index, reusing the `chunks.tsv_english` column added by PLAN-0063 Wave W5-2 (index name `ix_chunks_tsv_english_gin`). **SHIPPED** — index is live.

**Rationale**:
- Cost: Algolia $1/1000 records-month; ~50K documents = ~$50/month for one feature. Postgres is $0 incremental.
- Latency: with GIN + ≤100K documents (MVP scale), p95 ≤500ms is achievable. Re-evaluate at v1.1 if measurements show miss.
- Operational simplicity: no second data plane to seed, fail over, or back up.
- The platform already runs Postgres at every layer; adding a managed search service requires new auth/security review.

**Trade-off**: typo tolerance / fuzzy matching is weaker than Algolia. Acceptable for MVP — research analysts type tickers and proper nouns, not fuzzy queries.

### AD-W6-3: Aggregate chunks → document, do not index documents independently

**Decision**: Search results are **documents**, but the underlying tsvector lookup happens on `chunks.tsv_english` and is grouped/aggregated up to the document level. We do **not** add a `documents.tsv` column on the S5 `documents` table.

**Rationale**:
- Document body text only lives in MinIO silver, not in any Postgres column. Adding a `documents.tsv` would require extracting text into Postgres — a net-new sync pipeline.
- Chunks already contain the full text (segmented). Aggregating `MAX(ts_rank_cd(...))` per `doc_id` gives a defensible per-document score.
- Reuses the PLAN-0063 W5-2 GIN index `ix_chunks_tsv_english_gin` (live since 2026-05-06) — zero new index maintenance.

**Cross-DB strategy** (resolves the `canonical_entities` location question):
- **Document titles**: fetched from S5 via `POST /api/v1/documents/batch` (existing endpoint — `services/content-store/src/content_store/api/documents.py:18`).
- **Entity names**: fetched from S7 via `POST /api/v1/entities/batch` (entity-canonical service — `canonical_entities` lives in `intelligence_db`, not `nlp_db`). This is symmetric to the S5 hop.
- The search SQL (Wave 2) does **not** join `canonical_entities`. It returns `(doc_id, score, snippet)` and `(entity_id, count)` only; the use case enriches both via the two batch HTTP calls in parallel (`asyncio.gather`).
- Both calls honour R7 (no cross-service DB) and R9 (no cross-DB joins).

**Snippet contract** (resolves the Wave-1-vs-Wave-4 internal contradiction):
- Server returns `snippet: str | None` as **plain text** (no HTML tags) plus `match_offsets: list[tuple[int, int]]` — a list of (start, end) character offsets where matches occur within the snippet.
- Frontend renders `<mark>` tags from these offsets using React's automatic escaping. **No `dangerouslySetInnerHTML` is used.** This eliminates the HTML-injection risk surface entirely; DOMPurify is therefore not required for the snippet render path.
- Postgres still uses `ts_headline(...)` to choose the best fragment, but the route handler strips the wrapper tags and converts them into offset pairs before returning. (`ts_headline` defaults to `<b>` wrappers; we configure `StartSel`/`StopSel` to a sentinel like `\x02`/`\x03` for unambiguous post-processing.)

**Trade-off**: ranking is per-chunk-max not per-whole-document-BM25. For MVP this is acceptable; documented for future work.

### AD-W6-4: Authenticated route, S9 proxied, existing global rate limit

**Decision**: The new endpoint is **authenticated** (logged-in users only — anonymous returns 401), proxied by S9. Rate limiting uses the **existing** global per-user-per-minute `RateLimitMiddleware` (default 100/60s); no per-route or per-day limiter is added in this plan.

**Rationale**:
- The PRD §4 NFR table mentions "100 search/day"; verifying against the actual middleware shows it is per-user-per-minute, global, with no per-route or per-tenant or custom-window hooks (`services/api-gateway/src/api_gateway/middleware.py:298-410`). Building per-route + per-tenant + per-day support is a 0.5-1 dev-day refactor that belongs alongside W8's tier/quota work, not here.
- Anonymous landing-page search is out of scope for MVP; everyone reaching `/search` is authenticated already (the homepage gates behind login).

**Tenancy**: All searched content is global (not tenant-scoped). The route does not require RLS. W8 RLS work does not affect this route.

**Per-tenant per-day quota deferred**: Tracked as a follow-up in §15 to land in the W8 RLS+Stripe plan (TBD — no plan ID yet; PLAN-0065 is W9 observability, already complete) where it joins tier and Stripe quota work. The PRD §4 NFR "100 search/day" target is therefore aspirational for this plan; the immediate, enforced limit is the existing global 100/min/user.

### AD-W6-5: Query parameter design (resolves OQ-7) — revised 2026-05-03 per Sam-alignment audit

```
GET /v1/search?q=<query>
              &entity_id=<uuid>
              &scope=<watchlist|portfolio|all>
              &source_type=<news|sec_edgar|all>
              &date_from=<iso>&date_to=<iso>
              &date_preset=<since_last_visit|7d|30d|90d>
              &page=<int>&page_size=<int=25>
```

- `q` (required, ≤500 chars, parsed via `websearch_to_tsquery` — auto-escapes operators and supports user-facing quoted phrases / `OR` / `-`; no injection vector since asyncpg parameterises the value)
- `entity_id` (optional, UUID, repeatable — multiple values = AND)
- **`scope`** (optional, enum: `watchlist` | `portfolio` | `all`, default `watchlist` when the authenticated user has a non-empty watchlist; default `all` otherwise — added 2026-05-03). PRD-0034 §2 persona Sam researches ≤20 active tickers. The default scope MUST reflect that: a fresh `/search` query is overwhelmingly likely about a ticker he already watches. Resolution: `scope=watchlist` AND-joins the watchlist entity_ids into the entity filter; `scope=portfolio` does the same for current holdings; `scope=all` keeps the existing global behaviour. The Frontend EntityFacetSidebar pins watchlist entities to the top with a "Only my universe" toggle bound to `?scope=`.
- `source_type` (optional, enum: `news` | `sec_edgar` | `all`, default `all`. **`transcript` deliberately omitted** until ingestion ships — see §0 Known Limitations)
- `date_from`, `date_to` (optional, ISO 8601 dates)
- **`date_preset`** (optional, enum: `since_last_visit` | `7d` | `30d` | `90d` — added 2026-05-03). When supplied, server resolves the value into `date_from` (and ignores any caller-supplied `date_from`). `since_last_visit` reads `users.last_seen_at` from the api-gateway DB — Sam's "what's new" pattern. Mutually exclusive with `date_from`/`date_to`; if both are supplied the explicit ISO range wins and a warning is logged. Frontend renders preset chips above the results list.
- `page` (optional, 1-based, default 1, max 40 → 1000 results cap)
- `page_size` (optional, default 25, max 100 — bumped from 50 per Sam-alignment audit; surface 25/50/100 chips). Internal soft cap stays at 1000 total results so cursor-based infinite scroll (T-W6-4-02 revised) is preferred over deep pagination for >100 page_size.

Response shape defined in Wave 1 task T-W6-1-02.

---

## 4. Codebase State Verification

| PRD Reference | Type | Service | Actual Current State (read from code) | PRD Expected State | Delta |
|--------------|------|---------|---------------------------------------|--------------------|-------|
| `chunks.tsv_english` + `chunks.tsv_simple` | DB column / GIN | S6 `nlp_db.chunks` | **SHIPPED** — alembic 0017 live (current head: `0019_add_tenant_id_to_chunks_sections`); GIN indexes `ix_chunks_tsv_english_gin` + `ix_chunks_tsv_simple_gin` confirmed in prod 2026-05-06 | exists with GIN index `ix_chunks_tsv_english_gin`; **PLAN-0063 Wave W5-2 owns this** (alembic 0017) | none in this plan — hard dependency is MET |
| `entity_mentions(doc_id, resolved_entity_id)` | DB column + index | S6 `nlp_db` | exists; index `idx_entity_mentions_resolved` exists (alembic 0001) | unchanged | none |
| `documents` (S5) | DB table | S5 `content_store_db` | exists with `doc_id, source_type, source_url, title, published_at, ingested_at, content_hash, normalized_hash, status, dedup_result, minio_silver_key, word_count, language, corroborates_doc_id, is_backfill` | unchanged | none |
| `POST /api/v1/documents/batch` | endpoint | S5 | exists, returns `title, url, source_type, published_at, source_name, word_count` | unchanged — we'll consume this | none |
| `GET /api/v1/search/documents` | endpoint | S6 | does not exist | **NEW** — created by this plan | new file `services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py` extension OR new `search_documents.py` route file |
| `SearchDocumentsUseCase` | use case | S6 | does not exist | **NEW** | new file under `application/use_cases/` |
| `DocumentSearchRepository` | repo + port | S6 | does not exist | **NEW** | new port + asyncpg adapter |
| `GET /v1/search` | endpoint | S9 api-gateway | does not exist (only `/v1/search/instruments` for top-bar) | **NEW** S9 proxy route | new addition to `routes/proxy.py` |
| `apps/worldview-web/app/(app)/search/` | route | worldview-web | does not exist | **NEW** Next.js page | new directory |
| `lib/api/search.ts` | gateway client | worldview-web | exists per PLAN-0059 E-1 (split from monolith); has `search_instruments` only | extend with `searchDocuments(...)` | extend |
| `s6_search_documents_*` | Prometheus metrics | S6 `infrastructure/metrics/prometheus.py` | does not exist | counter + histogram | new |
| `tests/architecture/test_layer_invariants.py` | arch test | repo root | exists | will assert that new search route uses use case (R25) | none — existing test catches this |
| `chunks` table — `doc_id` foreign key | column | S6 | exists | unchanged | none |
| `transcripts` ingestion path | code | S4/S5 | EDGAR ingested as articles (`source_type='sec_edgar'`); transcripts not currently ingested; `transcript` is **not** a value of `ContentSourceType` enum (`libs/contracts/src/contracts/enums.py`) | PRD says "when available" | **scope note**: search supports `news` + `sec_edgar` only. `transcript` is **omitted from the source_type enum** (see §0 Known Limitations) until ingestion ships. Acceptance criterion adjusted accordingly. |
| `isomorphic-dompurify` (or `dompurify`) | npm dep | `apps/worldview-web/package.json` | **not installed** (verified 2026-05-03) | required IF snippet HTML rendering had been chosen | **not needed** — AD-W6-3 chose plain-text + offsets, so DOMPurify is unnecessary. Removed from cross-cutting concerns. |
| `RateLimitMiddleware` per-route per-tenant per-day | api-gateway middleware | S9 | **does not exist** — middleware is global per-user-per-minute (`max_requests=100, window_seconds=60`); no per-route or per-bucket hooks | required IF per-day per-tenant limit had been added in this plan | **not needed** — AD-W6-4 defers this work to the W8 RLS+Stripe plan (TBD — no plan ID yet; PLAN-0065 is W9 observability, already complete). |
| `ReadOnlyUnitOfWork` / `ReadUoWDep` in nlp-pipeline | infra | S6 | **does not exist** (`grep -rn "ReadOnlyUnitOfWork" services/nlp-pipeline/src/` returns 0 hits) | required IF R27 had been claimed | **not needed** — §0 Architecture Compliance Adjustments dropped the R27 claim for MVP. |
| `canonical_entities` in `nlp_db` | DB table/view | S6 | **does not exist** in nlp_db; lives in `intelligence_db` (S6/S7 shared); accessed by S6 via separate pool at `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/canonical_entity.py` | (initial draft assumed a view in nlp_db — incorrect) | use S7 batch HTTP `POST /api/v1/entities/batch` instead — see AD-W6-3 |
| S7 batch entities endpoint | endpoint | S7 entity-canonical-service | `POST /api/v1/entities/batch` exists per existing contracts | needed for entity-name lookup | new client wrapper added in Wave 2 |

**Critical baseline note**: `chunks.tsv_english` is **live** in `nlp_db` (alembic head `0019`; PLAN-0063 W5-2 shipped 2026-05-06). This plan must not duplicate the migration. Wave 1 Task T-W6-1-01 can skip the alembic-head gate check — the dependency is met. Implementers should still verify `ix_chunks_tsv_english_gin` exists before starting Wave 3 (`\d chunks` in psql).

---

## 5. Wave Decomposition

```
Wave 1: Schema + Contracts (parallelisable with Wave 4 frontend skeleton)
  └─► Wave 2: S6 Repository + Use Case
        └─► Wave 3: S6 API Route + Metrics + Unit Tests          (HARD DEP: PLAN-0063 Wave W5-2)
              └─► Wave 4: S9 Proxy + Rate Limiting + Frontend Page
                    └─► Wave 5: Integration / Acceptance / Docs
```

Estimated total effort: **3.5 dev-days** (PRD says 4 — minor compression because `chunks.tsv_english` GIN is already live, not built here).

Critical path: Wave 1 → Wave 2 → Wave 3 → Wave 4 → Wave 5.
Parallelism opportunity: Wave 1 task T-W6-1-04 (frontend types) can start in parallel with T-W6-1-01..03 (backend schemas).

---

## 6. Wave 1 — Schema, Contracts, and Type Stubs

**Goal**: Land the public contract (request/response Pydantic + TS types + OpenAPI schema) and the Prometheus metric definitions so Waves 2–4 can be implemented against a frozen interface.
**Depends on**: none (T-W6-1-04 can run in parallel with T-W6-1-01..03)
**Estimated effort**: 45–60 min
**Architecture layer**: API contracts + observability

### Tasks

#### T-W6-1-01: Define `SearchDocumentsRequest` / `SearchDocumentsResponse` Pydantic schemas in S6

**Type**: schema
**depends_on**: none
**blocks**: T-W6-1-02, T-W6-2-01, T-W6-3-01
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` (extend)
**PRD reference**: §3 FR-T1-3, §6 Workstream W6, this plan §3 AD-W6-5

**What to build**: Two Pydantic v2 models that fully describe the public search request/response. These freeze the contract so T-W6-1-04 (TS types) and T-W6-2-01 (use case) can be authored in parallel.

**Entities / Components**:
- **`SearchDocumentsRequest(BaseModel)`** — request DTO for the use case (note: the *HTTP* layer uses query params, not a JSON body; this model is what the route handler builds and hands to the use case).
  - `q: str` — `Field(..., min_length=1, max_length=500)`. Passed to `websearch_to_tsquery` (auto-escapes operators; supports user-facing quoted phrases / `OR` / `-` syntax). asyncpg parameterises the value — no string concat, no injection vector.
  - `entity_ids: list[UUID] = Field(default_factory=list)` — empty = no facet filter.
  - `source_type: Literal["news", "sec_edgar", "all"] = "all"` — `transcript` deliberately omitted until ingestion ships (see §0).
  - `date_from: datetime | None = None` — interpreted as UTC; if naive, raise `ValueError`.
  - `date_to: datetime | None = None`
  - `page: int = Field(default=1, ge=1, le=40)`
  - `page_size: int = Field(default=25, ge=1, le=100)` — **max bumped from 50 → 100 per Sam-alignment audit (§3 AD-W6-5); surface 25/50/100 chips in frontend**
  - **Invariants**: `date_from <= date_to` if both set (validator); use case raises `DomainError` otherwise.
- **`SearchDocumentResult(BaseModel)`** — single hit.
  - `doc_id: UUID`
  - `title: str | None`
  - `source_type: str`
  - `source_url: str | None`
  - `published_at: datetime | None`
  - `snippet: str | None` — top-ranked chunk fragment as **plain text** (no HTML), ≤300 chars. Null when `ts_headline` generation fails.
  - `match_offsets: list[tuple[int, int]]` — list of `(start, end)` character offsets within `snippet` marking matches. Frontend renders `<mark>` from these via React-safe rendering (no `dangerouslySetInnerHTML`). Empty list when snippet is null.
  - `score: float` — `MAX(ts_rank_cd(tsv_english, websearch_to_tsquery('english', :q)))` aggregated per doc.
  - `entity_hits: list[UUID]` — resolved entity IDs that matched the entity facet (for highlight UI).
- **`SearchDocumentsFacet(BaseModel)`** — entity facet sidebar item.
  - `entity_id: UUID`
  - `name: str`
  - `entity_type: str` — GLiNER class.
  - `count: int` — distinct doc_ids in current result set that mention this entity.
- **`SearchDocumentsResponse(BaseModel)`**.
  - `query: str` — echo back the q (after escape).
  - `total: int` — total matching documents (before pagination).
  - `page: int`, `page_size: int`, `has_more: bool`.
  - `results: list[SearchDocumentResult]` — exactly `page_size` or fewer.
  - `facets: list[SearchDocumentsFacet]` — top 25 entities by count in the current result set.
  - `latency_ms: int` — server-measured for observability.

**Tests to write** (unit, in `services/nlp-pipeline/tests/unit/api/test_schemas_search.py`):

| Test | What It Verifies |
|------|------------------|
| `test_request_q_required_min_length_1` | q="" raises `ValidationError` |
| `test_request_q_max_length_500` | q with 501 chars raises |
| `test_request_page_size_clamped_to_100` | page_size=101 raises (max is 100 per Sam-alignment audit) |
| `test_request_page_max_40` | page=41 raises |
| `test_request_date_range_inverted_rejected` | date_from > date_to raises |
| `test_request_naive_datetime_rejected` | tz-naive datetime raises |
| `test_response_has_more_true_when_total_exceeds_page` | total=100, page=1, page_size=25 → has_more=True |
| `test_response_facets_max_25` | facets list capped at 25 |
| `test_request_source_type_transcript_rejected` | `source_type="transcript"` raises ValidationError (enum drops it) |
| `test_result_snippet_is_plain_text_no_html` | snippet field rejects strings containing `<` or `>` (validator) |
| `test_result_match_offsets_within_snippet_bounds` | invalid offsets (start≥end, end>len(snippet)) raises |

Minimum 11 tests. Edge cases: empty q, max-length q, single-char q, `all` source_type, single entity_id, multi entity_id, snippet plain-text contract, offset validation.

**Downstream test impact**: none yet (no caller exists).

**Acceptance criteria**:
- [ ] All 4 models import cleanly with `mypy --strict`.
- [ ] 8 unit tests pass.
- [ ] `ruff check` clean.

#### T-W6-1-02: OpenAPI route stub + 422 contract test

**Type**: schema
**depends_on**: T-W6-1-01
**blocks**: T-W6-3-01
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/search_documents.py` (new — placeholder route returning `501`)
- `services/nlp-pipeline/tests/unit/api/test_search_documents_contract.py` (new)
**PRD reference**: §3 FR-T1-3, this plan §3 AD-W6-5

**What to build**: A `GET /api/v1/search/documents` route that validates query params via the request model and returns `501 Not Implemented` for now. Establishes the URL surface and locks the contract before the real implementation lands.

**Logic & Behavior**:
- Parse query params, build `SearchDocumentsRequest`.
- Catch `ValidationError` → return 422 with structured detail.
- Otherwise return `JSONResponse(status_code=501, content={"detail":"not yet implemented"})`.
- Use case dependency intentionally not wired yet (Wave 3 wires it).

**Tests to write** (in `test_search_documents_contract.py`):
- `test_missing_q_returns_422`
- `test_invalid_uuid_entity_id_returns_422`
- `test_page_zero_returns_422`
- `test_valid_request_returns_501_for_now`
- `test_q_over_500_chars_returns_422`

**Downstream test impact**: none.

**Acceptance criteria**:
- [ ] Route registered in `app.py` router list.
- [ ] OpenAPI spec at `/openapi.json` shows the new route with all query params.
- [ ] 5 contract tests pass.

#### T-W6-1-03: Prometheus metric definitions (no instrumentation yet)

**Type**: config
**depends_on**: none
**blocks**: T-W6-3-02
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/metrics/prometheus.py` (extend)
- `services/nlp-pipeline/tests/unit/infrastructure/test_metrics_search.py` (extend or new)
**PRD reference**: §11 cross-workstream observability

**What to build**: Three Prometheus metrics scoped to the search route:
- `s6_search_documents_total{source_type, status}` Counter — `status ∈ {ok, error, empty}`.
- `s6_search_documents_duration_seconds{source_type}` Histogram — buckets `0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0`.
- `s6_search_documents_results_count{source_type}` Histogram — buckets `0, 1, 5, 10, 25, 50, 100, 500, 1000` for result-count distribution.

**Tests to write**: assert metrics exist on the Prometheus registry with correct label sets. Minimum 3 tests.

**Acceptance criteria**:
- [ ] `curl /metrics` shows all three new series with zero samples.
- [ ] `ruff check` and `mypy` clean.

#### T-W6-1-04: TypeScript types + frontend gateway stub

**Type**: schema
**depends_on**: T-W6-1-01 (read the spec; can run in parallel with T-W6-1-02/03)
**blocks**: T-W6-4-03
**Target files**:
- `apps/worldview-web/lib/api/search.ts` (extend)
- `apps/worldview-web/types/api.ts` (extend — add the 4 search types)
- `apps/worldview-web/lib/api/__tests__/search.test.ts` (extend)
**PRD reference**: §3 FR-T1-3, this plan §3 AD-W6-5

**What to build**: TypeScript mirrors of the four Pydantic models, plus a `searchDocuments(params)` method on the gateway client that returns `Promise<SearchDocumentsResponse>` and throws `GatewayError` on non-2xx.

The function only assembles the URL and parses JSON — it does not implement any logic. Heavy comments per `feedback_frontend_comments.md` (user is new to Next.js): explain *why* `entity_ids` is sent as repeated `entity_id=` query params (matches FastAPI list semantics), *why* dates are serialised as ISO strings, *why* we URL-encode `q`.

**Tests** (vitest, mocked fetch):
- `test_buildsCorrectUrlWithSingleEntityFilter`
- `test_buildsCorrectUrlWithMultipleEntityFilters`
- `test_throwsOnNon2xx`
- `test_serialisesDatesAsIso8601`
- `test_urlEncodesQ`

Minimum 5 tests.

**Downstream test impact**: none — function is new.

**Acceptance criteria**:
- [ ] `pnpm typecheck` clean.
- [ ] `pnpm test lib/api/__tests__/search.test.ts` passes.
- [ ] No call site uses the function yet (linker only).

### Wave 1 Pre-read

- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` — existing Pydantic patterns
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py` — existing internal search route style
- `apps/worldview-web/lib/api/news.ts` — existing query-param-style gateway method (closest analogue)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/metrics/prometheus.py` — existing metric patterns

### Wave 1 Validation Gate
- [ ] ruff check passes on changed files
- [ ] mypy passes on `services/nlp-pipeline/`
- [ ] `pnpm typecheck` and `pnpm lint` pass
- [ ] All Wave 1 unit tests pass (≥21 new tests across 4 tasks)
- [ ] OpenAPI spec change visible at `/openapi.json`
- [ ] No domain-layer infra imports (R12 / IG-LAYER-001)

### Wave 1 Break Impact
| Broken File | Why It Breaks | Fix Required |
|------------|---------------|--------------|
| `services/nlp-pipeline/src/nlp_pipeline/app.py` | New router not yet registered | Wave 1 task T-W6-1-02 registers it; if missed, the contract test will fail to find the route |
| `tests/architecture/test_layer_invariants.py` | Asserts every API route imports only from `application.use_cases` | T-W6-1-02 placeholder route uses no use case yet; the architecture test must still pass — keep the placeholder route free of any `infrastructure.` import (return 501 directly) |
| `apps/worldview-web/lib/gateway.ts` (shim) | If we accidentally re-export from the wrong place after PLAN-0059 E-1 split | Add export only via `lib/api/search.ts`, never directly in `gateway.ts` |

### Wave 1 Regression Guardrails
- **BP-019** (DDL must match ORM): N/A — no DDL in this wave (`chunks.tsv_english` and `ix_chunks_tsv_english_gin` come from PLAN-0063 W5-2, already shipped).
- **BP-064** (FastAPI 204 status): use 501 + dict, never 501 + None.
- **BP-127** (pre-commit ruff drift): run `uvx ruff format --check` *file-mode* on staged Python files before commit.
- **BP-205-equivalent** (untyped frontend): every new TS field has an explicit type — no `any`.
- **BP-044** (R25 layer violation): the placeholder route must not import from `infrastructure.*`. Architecture test (95-test suite) catches this.

---

## 7. Wave 2 — Repository + Search Use Case

**Goal**: Implement the asyncpg query that performs the tsvector match, the entity-mention join, the per-doc aggregation, and the facet rollup. Wrap it in a use case that the route handler will call in Wave 3.
**Depends on**: Wave 1
**Estimated effort**: 90–120 min
**Architecture layer**: application + infrastructure

### Tasks

#### T-W6-2-01: Define `DocumentSearchRepository` port

**Type**: impl
**depends_on**: T-W6-1-01
**blocks**: T-W6-2-02, T-W6-2-03
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/document_search.py` (new)
**PRD reference**: §3 FR-T1-3

**What to build**: Abstract `DocumentSearchRepository` (ABC) with two methods:
- `async def search(self, request: SearchDocumentsRequest) -> tuple[list[SearchDocumentResult], int]` — returns hits + total count.
- `async def facets(self, request: SearchDocumentsRequest, hit_doc_ids: list[UUID]) -> list[SearchDocumentsFacet]` — entity rollup over the hit set.

**Invariants**: port has no SQL, no asyncpg, no SQLAlchemy imports. Pure interface.

**Tests**: none directly (port is interface only); compliance verified by adapter tests in T-W6-2-02.

**Acceptance criteria**:
- [ ] mypy clean.
- [ ] No infra imports in this file.

#### T-W6-2-02: Implement `AsyncpgDocumentSearchRepository` adapter

**Type**: impl
**depends_on**: T-W6-2-01
**blocks**: T-W6-2-03, T-W6-3-01
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/repositories/document_search.py` (new)
- `services/nlp-pipeline/tests/unit/infrastructure/db/test_document_search_repository.py` (new)
- `services/nlp-pipeline/tests/integration/test_document_search_real_db.py` (new)
**PRD reference**: §3 FR-T1-3, §9 (escape user input)

**What to build**: The asyncpg implementation. Three SQL queries — all confined to `nlp_db` (no cross-DB joins; `canonical_entities` is **not** referenced — entity names come from S7 batch HTTP in the use case layer).

`StartSel`/`StopSel` for `ts_headline` use sentinel bytes `\x02` / `\x03` so the route handler can deterministically convert them into `match_offsets` and strip the markers, returning the snippet as plain text.

**Query 1 — search**:
```sql
WITH ranked_chunks AS (
    SELECT
        c.doc_id,
        c.chunk_id,
        ts_rank_cd(c.tsv_english, websearch_to_tsquery('english', $1)) AS rank,
        ts_headline('english', c.chunk_text,
                    websearch_to_tsquery('english', $1),
                    'MaxFragments=1, MaxWords=40, MinWords=15, ShortWord=3, StartSel=E''\x02'', StopSel=E''\x03''') AS snippet_marked
    FROM chunks c
    WHERE c.tsv_english @@ websearch_to_tsquery('english', $1)
),
top_chunk_per_doc AS (
    SELECT DISTINCT ON (rc.doc_id)
        rc.doc_id, rc.rank, rc.snippet_marked
    FROM ranked_chunks rc
    ORDER BY rc.doc_id, rc.rank DESC
),
filtered AS (
    SELECT t.doc_id, t.rank, t.snippet_marked
    FROM top_chunk_per_doc t
    -- source_type / date filters folded into a single hash join on document_source_metadata
    LEFT JOIN document_source_metadata dsm ON dsm.doc_id = t.doc_id
    WHERE
        (CAST($2 AS uuid[]) IS NULL OR t.doc_id IN (
            SELECT DISTINCT em.doc_id
            FROM entity_mentions em
            WHERE em.resolved_entity_id = ANY($2::uuid[])
        ))
        AND (CAST($3 AS text) IS NULL OR dsm.source_type = $3)
        AND (CAST($4 AS timestamptz) IS NULL OR dsm.published_at >= $4)
        AND (CAST($5 AS timestamptz) IS NULL OR dsm.published_at <= $5)
)
SELECT doc_id,
       rank,
       snippet_marked,
       -- Blended final_score (revised 2026-05-03 per Sam-alignment audit).
       -- Pure ts_rank_cd routinely surfaces a 1-day-old newsapi blurb above a
       -- 30-day-old EDGAR 10-Q for the same lexical match — the OPPOSITE of
       -- what Sam (research analyst) wants. Blend lifts authoritative sources
       -- and recent items without burying tied-relevance primary disclosures.
       --
       -- Weights (tuneable via Settings; see F-W6-NEW for telemetry follow-up):
       --   source_weight: sec_edgar=1.5, news=1.0 (matches PLAN-0063
       --                  _SOURCE_QUALITY_FLOOR direction; values intentionally
       --                  smaller because W6 has no separate recency multiplier)
       --   recency_decay: exp(-age_days / 90)  (90-day half-life; lifts last
       --                  quarter's filings vs ancient news, doesn't crush
       --                  multi-year filings the way W5's per-source rates do)
       (rank
        * CASE dsm.source_type
            WHEN 'sec_edgar' THEN 1.5
            WHEN 'news'      THEN 1.0
            ELSE                  1.0
          END
        * exp(- (extract(epoch from (now() - dsm.published_at)) / 86400.0) / 90.0)
       ) AS final_score
FROM filtered
ORDER BY final_score DESC
LIMIT $6 OFFSET $7;
```

Notes:
- The JOIN on `document_source_metadata` (added by PLAN-0033 migration 0002 in `nlp_db` with columns `doc_id, source_type, published_at, ingested_at` — confirmed in pre-read) is a single hash join, not three correlated EXISTS — addresses I-6 (NFR feasibility) and the integration test asserts the EXPLAIN plan shape.
- `CAST($N AS …) IS NULL OR …` pattern (BP-180) for nullable parameters under asyncpg.
- No reference to `canonical_entities` — entity names are batch-fetched from S7 in the use case layer.
- **Ranking blend (added 2026-05-03)**: SQL above sets `ORDER BY final_score DESC` where `final_score = ts_rank_cd × source_weight × recency_decay`. Add a unit test in T-W6-3-02 asserting an EDGAR 10-Q with `ts_rank_cd=0.10` outranks a same-day newsapi blurb with `ts_rank_cd=0.10` (same lexical, EDGAR wins via source_weight). Add a second test asserting a 1-day-old newsapi blurb still outranks a 365-day-old EDGAR filing with the same lexical score (recency dominates at extreme age gap). Both tests guard the chosen weights against drift.

**Query 2 — total count**: same CTE structure but `SELECT count(*) FROM filtered`.

**Query 3 — facets** (called only when results non-empty):
```sql
SELECT em.resolved_entity_id, em.mention_class AS entity_type, COUNT(DISTINCT em.doc_id) AS cnt
FROM entity_mentions em
WHERE em.doc_id = ANY($1::uuid[])
  AND em.resolved_entity_id IS NOT NULL
GROUP BY em.resolved_entity_id, em.mention_class
ORDER BY cnt DESC
LIMIT 25;
```

The use case then calls `S7Client.batch_get_entities([row.resolved_entity_id for row in result])` to attach `name` to each facet (single HTTP roundtrip, parallelised with the S5 title hop via `asyncio.gather`).

**Snippet post-processing in the route handler**:
- For each row, scan `snippet_marked` for `\x02 ... \x03` pairs.
- Build `match_offsets: list[tuple[int, int]]` from the positions *after* the markers are stripped (i.e. positions in the final plain-text snippet).
- Return `snippet = stripped_text`, `match_offsets = offsets`.
- This conversion is unit-tested separately (8+ tests against canned inputs) and lives in a pure helper `nlp_pipeline/application/use_cases/_snippet.py` so the use case stays thin.

**Title field source**: `documents` table is in `content_store_db`. To return titles without a cross-DB query, the use case calls `S5.POST /api/v1/documents/batch` (R7-compliant HTTP) with the hit doc_ids and merges in the metadata. Repository returns IDs + score + raw `snippet_marked` only; the use case does the S5 batch call AND the S7 batch call AND the snippet post-processing.

**Logic & Behavior**:
- Build params list defensively; use `None` for unfiltered params (Postgres CAST per BP-180 pattern).
- Empty `entity_ids` → pass `NULL::uuid[]` (the SQL `IS NULL OR ... IN (...)` short-circuits).
- Wrap each query in a single asyncpg `connection.fetch` per call.
- Pool: use the existing nlp-pipeline writer pool (no `ReadOnlyUnitOfWork` exists in S6 — see §0). Single-pool read for MVP; tracked as a follow-up in §15.

**Idempotency / safety**:
- All inputs go through `websearch_to_tsquery` which auto-escapes — no string concat.
- Add `LIMIT 1000` total cap (page=40, page_size=25) enforced in the request validator already (T-W6-1-01).

**Error classification**:
- asyncpg `QueryCanceledError` (timeout) → `RetryableSearchError` → 503.
- asyncpg `PostgresError` other → `FatalSearchError` → 500 + log + Sentry.
- Empty result is not an error.

**Tests** (unit, against mocked asyncpg connection):
| Test | What |
|------|------|
| `test_search_no_filters_returns_results` | basic happy path |
| `test_search_with_entity_filter_applies_join` | param[1] non-null path |
| `test_search_with_source_type_filter` | param[2] applied |
| `test_search_with_date_range` | param[3]/param[4] |
| `test_search_paginates_offset_limit` | page=2 → OFFSET=25 |
| `test_search_empty_results` | returns ([], 0) |
| `test_search_handles_query_with_special_chars` | `q=":;|!&"` does not crash (`websearch_to_tsquery` escapes) |
| `test_search_handles_websearch_quoted_phrase` | `q="\"federal reserve\""` parsed as phrase |
| `test_search_handles_websearch_or_operator` | `q="apple OR microsoft"` matches either |
| `test_facets_returns_top_25_no_canonical_join` | 30 entities → 25 returned, sorted by count desc; SQL contains no `canonical_entities` reference |
| `test_facets_skips_unresolved_entities` | resolved_entity_id IS NULL filtered out |
| `test_snippet_marker_to_offsets_helper` | `\x02foo\x03 bar` → snippet="foo bar", offsets=[(0,3)] |
| `test_snippet_helper_multiple_matches` | two markers → two offsets, ordered |
| `test_snippet_helper_no_markers_returns_empty_offsets` | plain text → offsets=[] |

Minimum 13 unit tests + 3 integration tests (real Postgres testcontainer).

**Downstream test impact**:
- `tests/architecture/test_kafka_avro_enforcement.py` — N/A (no Kafka in this task).
- `services/nlp-pipeline/tests/unit/test_app.py` — if it counts router routes, will need increment.

**Acceptance criteria**:
- [ ] All 16 tests pass.
- [ ] `EXPLAIN ANALYZE` of search query against seeded test DB shows `Bitmap Index Scan on ix_chunks_tsv_english_gin` AND a `Hash Join` on `document_source_metadata` (never `Nested Loop`) — asserted in integration test.
- [ ] mypy + ruff clean.
- [ ] Source SQL contains no `canonical_entities` reference (grep assertion in test).

#### T-W6-2-03: `SearchDocumentsUseCase` orchestrator

**Type**: impl
**depends_on**: T-W6-2-02
**blocks**: T-W6-3-01
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/search_documents.py` (new)
- `services/nlp-pipeline/tests/unit/application/use_cases/test_search_documents.py` (new)
**PRD reference**: §3 FR-T1-3

**What to build**: Use case that:
1. Validates request (already validated by Pydantic; re-checks invariants like `entity_ids ⊆ known canonicals` softly — silently drops unknowns, does not fail).
2. Calls `repository.search(request)` → `(hits_with_marked_snippets, total)`.
3. For each hit, runs the snippet marker→offsets helper to produce `(snippet_plain_text, match_offsets)`.
4. Calls `repository.facets(request, [h.doc_id for h in hits])` → raw facet rows `(entity_id, entity_type, count)`.
5. **In parallel via `asyncio.gather`**:
   - `s5_client.batch_documents([h.doc_id for h in hits])` → titles + URLs + published_at.
   - `s7_client.batch_get_entities([f.entity_id for f in facets])` → entity names.
6. Merges S5 metadata into hits and S7 names into facets.
7. Builds `SearchDocumentsResponse` with computed `latency_ms` and `has_more`.
8. Increments `s6_search_documents_total` and observes histogram (Wave 3 metric wiring uses this — keep metric calls inside the use case so the route stays thin).

**Entities / Components**:
- Constructor takes: `repo: DocumentSearchRepository`, `s5_client: S5BatchDocumentsClient`, `s7_client: S7BatchEntitiesClient`, `clock: Callable[[], datetime] = utc_now`.
- Single public method: `async def execute(self, request: SearchDocumentsRequest) -> SearchDocumentsResponse`.

**Logic & Behavior**:
- Time the operation with `time.perf_counter`.
- If S5 batch returns fewer docs than requested (some doc_id not in S5), the result is still emitted with title/url=None — the doc still exists in `nlp_db.chunks` but the canonical document was deleted. Log WARN.
- If S7 batch returns fewer entities than requested, facets without a name fall back to `name=str(entity_id)` and log WARN.
- Empty result short-circuits: skip facets call AND both batch calls (saves three roundtrips).
- Both `s5_client` and `s7_client` use `httpx.AsyncClient(timeout=httpx.Timeout(2.0))` per BP-235.

**Tests** (unit, with mocked repo + mocked S5 client + mocked S7 client):
| Test | What |
|------|------|
| `test_execute_happy_path_calls_repo_then_facets_then_gather_s5_s7` | call order: repo.search → repo.facets → gather(s5, s7) |
| `test_execute_empty_results_skips_facets_and_batch_calls` | optimisation — three roundtrips skipped |
| `test_execute_merges_s5_metadata_into_hits` | title/url propagation |
| `test_execute_merges_s7_names_into_facets` | entity-name propagation |
| `test_execute_handles_s5_partial_response` | S5 returns subset → snippet still present, title=None |
| `test_execute_handles_s7_partial_response` | S7 returns subset → facet name=str(entity_id) fallback, WARN logged |
| `test_execute_runs_s5_and_s7_in_parallel` | asyncio.gather observed (both awaited) |
| `test_execute_increments_metrics` | counter+histogram observed |
| `test_execute_propagates_repo_errors` | RetryableSearchError surfaces |
| `test_execute_computes_has_more_correctly` | total > page*page_size → True |
| `test_execute_records_latency_ms` | latency_ms is int and ≥ 0 |
| `test_execute_post_processes_snippet_markers` | marker bytes converted to offsets, plain text returned |

Minimum 12 tests.

**Downstream test impact**: none.

**Acceptance criteria**:
- [ ] All 12 tests pass.
- [ ] No infra imports in use case file.

### Wave 2 Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/enhanced_chunk_search.py` — closest analogue, mirror its structure
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/repositories/` — existing repository patterns
- `services/nlp-pipeline/alembic/versions/0001_create_nlp_schema.py` — confirm `entity_mentions(doc_id, resolved_entity_id, mention_class)` shape (canonical_entities is NOT in nlp_db; do not search for it)
- `services/nlp-pipeline/alembic/versions/0002_add_document_source_metadata.py` — confirm `document_source_metadata(doc_id, source_type, published_at, ingested_at)` shape
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/canonical_entity.py` — existing intelligence_db pool pattern (do NOT use this — listed for context only; we use S7 HTTP instead)
- `services/content-store/src/content_store/api/documents.py` — S5 batch endpoint contract
- S7 entity-canonical batch endpoint contract — read existing API spec for `POST /api/v1/entities/batch`
- `services/nlp-pipeline/src/nlp_pipeline/clients/` (if exists) — existing S5/S7 client patterns; otherwise add minimal clients in this task
- `services/api-gateway/src/api_gateway/routes/proxy.py:74` (`_system_headers` precedent) — used by S6 clients to mint a system JWT for internal calls
- `docs/audits/2026-04-23-local-bring-up-remediation-report.md` — BP-180 (CAST asyncpg pattern)

### Wave 2 Validation Gate
- [ ] ruff + mypy clean
- [ ] ≥28 new unit tests + ≥3 integration tests pass
- [ ] Integration test asserts GIN index used (`EXPLAIN ANALYZE` contains `Bitmap Index Scan on ix_chunks_tsv_english_gin`) AND `Hash Join` on `document_source_metadata` (never `Nested Loop` per filter)
- [ ] grep assertion: source SQL contains zero `canonical_entities` references
- [ ] Architecture test (R25 use-case-only) passes
- [ ] No `print` / stdlib logging — structlog only

### Wave 2 Break Impact
| Broken File | Why It Breaks | Fix Required |
|------------|---------------|--------------|
| `services/nlp-pipeline/src/nlp_pipeline/app.py` startup | New repository + S5 + S7 clients need wiring | Add `app.state.document_search_repo`, `app.state.s5_batch_client`, `app.state.s7_batch_client` to lifespan; add to readiness probe |
| `services/nlp-pipeline/tests/conftest.py` | New test fixtures needed for repo + 2 clients | Add `document_search_repo` fixture wrapping a pg testcontainer + httpx mock fixtures for S5/S7 |
| `services/nlp-pipeline/src/nlp_pipeline/clients/s5_client.py` (may not exist) | Use case depends on it | If not present, create a thin httpx async client in this wave |
| `services/nlp-pipeline/src/nlp_pipeline/clients/s7_client.py` (likely not present) | Use case depends on it | Create a thin httpx async client; mints internal JWT via existing `_system_headers` pattern; targets `POST /api/v1/entities/batch` |

### Wave 2 Regression Guardrails
- **BP-180** (asyncpg AmbiguousParameterError on nullable params): every nullable filter must use `CAST($N AS uuid[]) IS NULL OR ...` style.
- **BP-179** (pydantic SecretStr empty-string trap): N/A here — q is plain str.
- **BP-235** (httpx asyncio timeout shadowing): both S5 and S7 client calls wrap `httpx.AsyncClient(timeout=httpx.Timeout(2.0))` — never default.
- **BP-007** (UoW commit ordering): N/A — read-only.
- **BP-301-equivalent** (silent zero-output): if the use case returns 0 hits AND `chunks` table is non-empty, log INFO with `q`, `entity_ids`, `source_type` so we can debug a too-strict tsquery escape.
- **BP-044 / R25**: route never imports repo directly; only via use case.
- **`feedback_prompt_input_mismatch`** (silent drop): the `source_type` enum at the API layer EXACTLY matches the values the SQL filter accepts (`news`, `sec_edgar`, `all`). If a future ingestion adds a new source_type, both the enum and the docs must be updated atomically.
- **`feedback_audit_returned_value_persistence`** (audit values must be persisted, not just observed): `latency_ms` is BOTH observed via Prometheus histogram AND included in the response body so the caller can audit; structlog also logs it.

---

## 8. Wave 3 — API Route, Metrics Wiring, S6 End-to-End

**Goal**: Replace the 501 placeholder with the real handler, instrument metrics, and ship the search endpoint inside S6 with full integration tests.
**Depends on**: Wave 1, Wave 2. **PLAN-0063 Wave W5-2 dependency MET** — `chunks.tsv_english` GIN index `ix_chunks_tsv_english_gin` is live (alembic 0017 shipped 2026-05-06; current head is 0019).
**Estimated effort**: 60–90 min
**Architecture layer**: API + integration

### Tasks

#### T-W6-3-01: Wire route to use case + metrics

**Type**: impl
**depends_on**: T-W6-1-02, T-W6-2-03
**blocks**: T-W6-3-02
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/search_documents.py` (replace placeholder)
- `services/nlp-pipeline/src/nlp_pipeline/api/dependencies.py` (add `SearchDocumentsUseCaseDep`)
- `services/nlp-pipeline/tests/unit/api/test_search_documents_route.py` (new)

**What to build**:
- Replace the 501 handler with one that:
  1. Builds `SearchDocumentsRequest` from query params (handles `entity_id` repeating params via `Query(None)` + `list[UUID]`).
  2. Awaits `use_case.execute(request)`.
  3. Maps `RetryableSearchError` → 503; `FatalSearchError` → 500; other unexpected → 500 + log.
  4. Returns `SearchDocumentsResponse`.
- Increment `s6_search_documents_total{source_type, status}` in finally block.
- Observe `s6_search_documents_duration_seconds{source_type}`.
- Observe `s6_search_documents_results_count{source_type}` with the response total.

**Tests**:
| Test | What |
|------|------|
| `test_get_search_documents_200_with_results` | with mocked use case |
| `test_get_search_documents_503_on_retryable` | RetryableSearchError → 503 |
| `test_get_search_documents_500_on_fatal` | FatalSearchError → 500 |
| `test_get_search_documents_metrics_incremented_on_ok` | counter inspect |
| `test_get_search_documents_metrics_incremented_on_error` | counter inspect with status=error |
| `test_get_search_documents_repeating_entity_id_params` | `?entity_id=A&entity_id=B` parses to list of 2 |
| `test_get_search_documents_returns_facets` | facet list in response |

Minimum 7 tests.

**Downstream test impact**:
- The contract tests from T-W6-1-02 (which expected 501) — update assertion to 200/422.
- `services/nlp-pipeline/tests/integration/test_full_app.py` (if it counts routes) — increment expected route count.

**Acceptance criteria**:
- [ ] All Wave 1 contract tests still pass with updated 200 assertion.
- [ ] 7 new route tests pass.
- [ ] Manual `curl 'http://localhost:8006/api/v1/search/documents?q=apple'` returns 200 with valid JSON.

#### T-W6-3-02: Integration tests against real seeded data

**Type**: test
**depends_on**: T-W6-3-01. **PLAN-0063 W5-2 dependency MET** — GIN `ix_chunks_tsv_english_gin` live since 2026-05-06.
**blocks**: T-W6-5-01
**Target files**:
- `services/nlp-pipeline/tests/integration/test_search_documents_e2e.py` (new)

**What to build**: End-to-end tests against a Postgres testcontainer with seeded chunks + entity_mentions. Tests include:

| Test | What |
|------|------|
| `test_search_finds_seeded_apple_article` | seed 1 chunk containing "Apple announced...", search "apple" → 1 hit |
| `test_search_filters_by_entity_id` | seed 2 chunks, only one has resolved_entity_id=APPLE_UUID; query with `entity_ids=[APPLE_UUID]` returns only that one |
| `test_search_filters_by_source_type` | seed 1 news + 1 sec_edgar; source_type=sec_edgar returns 1 |
| `test_search_filters_by_date_range` | seed 3 chunks with 3 dates; date range returns expected subset |
| `test_search_pagination_consistent` | 30 hits, page=1+page=2 → 25+5, no overlap |
| `test_search_facets_top_25_capped` | seed 30 distinct entities, response.facets.length == 25 |
| `test_search_p95_latency_under_500ms_end_to_end` | seed 1k chunks, run search 50× including S5+S7 batch hops (mocked at 100ms each) → p95 < 500ms (PRD §4 NFR). Latency budget breakdown: tsvector + facets SQL ≤ 250ms; S5 batch hop ≤ 100ms (parallel with S7); S7 batch hop ≤ 100ms (parallel with S5); snippet post-processing + serialisation ≤ 50ms. |
| `test_search_explain_uses_gin_and_hash_join` | `EXPLAIN ANALYZE` plan contains `Bitmap Index Scan on ix_chunks_tsv_english_gin` AND `Hash Join` on `document_source_metadata`; never `Nested Loop` per filter |
| `test_search_special_chars_in_query_no_500` | `q="C:\\windows&|!"` → 200 |

Minimum 9 integration tests.

**Latency budget table** (p95 target ≤ 500ms):

| Hop | Budget | Notes |
|-----|--------|-------|
| `tsvector` search SQL (Query 1 + Query 2) | ≤ 200 ms | bitmap-index scan via `ix_chunks_tsv_english_gin` + hash join on `document_source_metadata` |
| Facets SQL (Query 3) | ≤ 50 ms | only runs when result set is non-empty |
| S5 `POST /api/v1/documents/batch` | ≤ 100 ms | parallel with S7 via `asyncio.gather` |
| S7 `POST /api/v1/entities/batch` | ≤ 100 ms | parallel with S5 |
| Snippet post-processing + serialisation | ≤ 50 ms | pure Python, in-memory |
| **Total p95 target** | **≤ 500 ms** | (S5/S7 are parallel, so contribute max not sum: 100 ms not 200 ms) |

If the integration test misses the target, the fallback options are: (a) reduce default page_size to 10; (b) tighten `LIMIT` early-cut in CTE; (c) escalate to `/investigate`.

**Acceptance criteria**:
- [ ] All 9 integration tests pass against real Postgres + GIN.
- [ ] Latency test asserts measured p95 ≤ 500ms with mocked S5/S7 at 100ms each.
- [ ] EXPLAIN ANALYZE plan-shape assertion green.
- [ ] No fixture leaks between tests.

### Wave 3 Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py` — existing route style for reference
- PLAN-0063 Wave W5-2 **SHIPPED** (alembic 0017 live). Verify `ix_chunks_tsv_english_gin` exists (`\d chunks` in psql) before starting Wave 3 as a sanity check.

### Wave 3 Validation Gate
- [ ] ruff + mypy clean
- [ ] All Wave 3 tests pass (≥15)
- [ ] All Wave 1 contract tests still green (501→200 assertion update)
- [x] PLAN-0063 Wave W5-2 confirmed shipped (alembic head `0019` ≥ `0017`; index `ix_chunks_tsv_english_gin` live since 2026-05-06)
- [ ] Manual smoke: `curl` against running S6 returns valid JSON

### Wave 3 Break Impact
| Broken File | Why | Fix |
|------------|-----|-----|
| `services/nlp-pipeline/tests/unit/api/test_search_documents_contract.py` | Was asserting 501 | Update T-W6-1-02 contract tests to assert real 200/422 — done as part of T-W6-3-01 |
| `services/nlp-pipeline/src/nlp_pipeline/app.py` lifespan | Needs to instantiate the new use case + repo + S5 client | Wire in lifespan; add startup probe |
| `apps/worldview-web/lib/gateway.ts` (no break, but) | Was returning stub | Becomes real once Wave 4 lands |

### Wave 3 Regression Guardrails
- **BP-302** (article-consumer hang): N/A — this is read-only.
- **BP-127** (ruff drift): use file-mode check before commit.
- **BP-064** (FastAPI 204): we never return 204; 200/422/500/503.
- **BP-235** (httpx timeout shadowing): S5 client uses `httpx.Timeout(2.0)` not default.
- **BP-180** (asyncpg CAST): all repo queries use CAST.
- **R25 violation**: route imports only from `application.use_cases` and `api.schemas` and `api.dependencies` — `mypy` plus the architecture test (95-test suite) will catch breaches.
- **BP-301-equivalent** (silent empty result): when 0 hits, log INFO with the query — already noted Wave 2.

---

## 9. Wave 4 — S9 Proxy, Rate Limiting, Frontend Page

**Goal**: Expose the S6 endpoint publicly via S9 with rate limiting; ship the Next.js search page with results list, facet sidebar, and pagination.
**Depends on**: Wave 3
**Estimated effort**: 90–120 min
**Architecture layer**: API gateway + frontend

### Tasks

#### T-W6-4-01: S9 proxy route + rate limiting

**Type**: impl
**depends_on**: T-W6-3-01
**blocks**: T-W6-4-03
**Target files**:
- `services/api-gateway/src/api_gateway/routes/proxy.py` (extend)
- `services/api-gateway/src/api_gateway/clients.py` (extend — add `search_documents` helper)
- `services/api-gateway/tests/test_search_proxy.py` (new)
**PRD reference**: §3 FR-T1-3, §9 (auth + injection)

**What to build**:
- `GET /v1/search` on S9 forwarding to S6 `/api/v1/search/documents`.
- Authenticated via existing OIDC middleware (logged-in users only). For unauthenticated callers, return 401 (anonymous searching is out of scope; landing page may stub it later).
- The S9 → S6 hop **must mint a system JWT** via `_system_headers(request)` (precedent: `services/api-gateway/src/api_gateway/routes/proxy.py:74` — already used by `/v1/news/relevant` and `/v1/search/instruments`). S6 routes are protected by `InternalJWTMiddleware`; without `X-Internal-JWT` the call returns 401.
- Rate limiting: relies on the **existing global** `RateLimitMiddleware` (per-user, per-minute, default 100/60s). No per-route, per-tenant, or per-day bucket is added in this plan — that work is deferred to the W8 RLS+Stripe plan (TBD — no plan ID yet; PLAN-0065 is W9 observability, already complete) where it joins tier and Stripe quota machinery (see §0 Architecture Compliance Adjustments and §15 Follow-ups).
- Forward all query params verbatim; do not modify q.
- Response: stream the JSON body straight through (no transformation).
- Errors: 502 on downstream timeout, 503 if S6 returns 503, otherwise propagate status.

**Tests**:
| Test | What |
|------|------|
| `test_search_proxy_401_without_jwt` | unauthenticated rejected |
| `test_search_proxy_200_with_jwt_forwards_response` | authed happy path |
| `test_search_proxy_forwards_all_query_params` | all params pass through verbatim |
| `test_search_proxy_includes_internal_jwt_header_to_s6` | outbound request to S6 contains `X-Internal-JWT` header (asserted via httpx mock recorder) |
| `test_search_proxy_502_on_downstream_timeout` | httpx timeout |
| `test_search_proxy_propagates_503` | downstream 503 → client 503 |
| `test_search_proxy_global_rate_limit_still_active` | 101st call within 60s → 429 (existing global limit; documents the actual enforced limit) |

Minimum 7 tests.

**Acceptance criteria**:
- [ ] All 7 tests pass.
- [ ] Manual: `curl` against `localhost:8000/v1/search?q=apple` with valid JWT returns S6 response.
- [ ] Integration smoke against real S6 verifies the `X-Internal-JWT` header is present on the inbound side.

#### T-W6-4-02: Frontend search page

**Type**: impl
**depends_on**: T-W6-4-01, T-W6-1-04
**blocks**: T-W6-4-03
**Target files**:
- `apps/worldview-web/app/(app)/search/page.tsx` (new)
- `apps/worldview-web/app/(app)/search/SearchResultsList.tsx` (new)
- `apps/worldview-web/app/(app)/search/EntityFacetSidebar.tsx` (new)
- `apps/worldview-web/app/(app)/search/__tests__/SearchPage.test.tsx` (new)
- `apps/worldview-web/lib/query/keys.ts` (extend — add `qk.search.documents(...)`)
**PRD reference**: §3 FR-T1-3

**What to build** (revised 2026-05-03 per Sam-alignment audit). Heavy-comments UI per `feedback_frontend_comments.md`. Three components, all using **"result card"** terminology consistently (was mixed "rows"/"list" — unified per audit):

1. **`/search` page** (server component shell + client island for results):
   - Reads `?q=`, `?entity_id=`, `?scope=`, `?source_type=`, `?date_from=`, `?date_to=`, `?date_preset=`, `?page=` from URL via `nuqs` (per PLAN-0059 C-6 pattern — already shipped).
   - Renders search input bound to `?q=`.
   - **Date preset chips** above the results list: `[ Since last visit ] [ 7 days ] [ 30 days ] [ 90 days ] [ Custom… ]` — clicking a chip sets `?date_preset=`; "Custom" reveals the date_from/date_to range pickers. Default for an authenticated user with `last_seen_at` set is `since_last_visit`; otherwise no preset (all dates).
   - **Scope toggle** in the sidebar: "Only my universe" checkbox bound to `?scope=watchlist` (default ON when watchlist non-empty).
   - Renders the results list and facet sidebar.
   - Empty state when q is empty: "Type a query to search articles and filings." (Transcripts will be added once ingestion ships — see §0 Known Limitations.)
   - **0-results state — replaced (audit HIGH)**: instead of a dead-end "No matches" message, render a helpful panel:
     - Try entity-resolution on `q` via the existing instrument resolver (`/v1/instruments/resolve?q=`); if a ticker is recognised, fetch and surface "Recent activity on TICKER" (top 5 hits dropping the lexical filter, keeping the entity filter).
     - "Broaden to all sources" CTA that drops `source_type` and `date_from`/`date_to` filters and re-runs the query.
     - "Did you mean" entity suggestions (top 3 entities by string-distance to `q`).
     - This is added as a sub-task **T-W6-4-02b** below for review tracking, but lives in the same component file.
   - Loading: skeleton result cards (8 placeholder cards — terminology unified).

2. **`SearchResultsList`** (client component):
   - Uses **`useInfiniteQuery`** with cursor-based pagination (revised 2026-05-03): `useInfiniteQuery({ queryKey: qk.search.documents(params), queryFn: ({ pageParam }) => gateway.searchDocuments({ ...params, page: pageParam ?? 1 }) })`. The `?page=` URL param remains for deep-linking but the visible UI is infinite scroll with a "Load more" sentinel. Numbered pagination is a Bloomberg/SEC pattern, not a research-tool pattern — Sam scans many results.
   - Renders each hit as a **result card**: title, snippet (with `<mark>` highlights generated **from `match_offsets`** in React-safe rendering — no `dangerouslySetInnerHTML`, no DOMPurify, no HTML on the wire), source badge, published date, "Open source ↗" link.
   - **Snippet popover (added 2026-05-03 — Sam-alignment audit)**: clicking the result card title (NOT the "Open source" link) opens an inline shadcn `<Sheet>` drawer with the full snippet, all matched chunks for that doc, source metadata, and an "Open source ↗" button as the escape hatch. This is the AlphaSense/Sentieo "verify-without-leaving" pattern. Implemented in new component `SearchResultCardSheet.tsx` per **T-W6-4-05** below.
   - Snippet renderer is a small helper `renderSnippetWithMarks(snippet, offsets)` that splits the plain text on the offsets and emits alternating `<span>{text}</span>` and `<mark>{text}</mark>` JSX children. React's automatic escaping handles all character escaping. Heavy comments explain why this is safer than `dangerouslySetInnerHTML` + sanitiser.
   - **Page-size selector**: 25 / 50 / 100 chips (was 25 only). Bound to `?page_size=` in URL.
   - Comment block at the top explains query-key invariants and `staleTime: 30_000` choice.

3. **`EntityFacetSidebar`** (client component):
   - **"My universe" section pinned at top** (revised 2026-05-03): when authenticated, renders a header "My universe" followed by watchlist entities first, then portfolio holdings, before the facet frequency list. The "Only my universe" toggle binds to `?scope=`.
   - Lists top facets with checkboxes.
   - Clicking a facet toggles the entity_id in the URL (additive — multiple facets ANDed).
   - "Clear filters" button when any filter is active.
   - Comment block explains why we drive state through URL not local state (shareable, refresh-safe, plays with nuqs).

**Tests** (vitest + RTL with nuqs adapter):
| Test | What |
|------|------|
| `test_renders_input_bound_to_url_q` | `?q=apple` → input value == "apple" |
| `test_typing_in_input_updates_url` | typing → URL ?q updates after debounce |
| `test_facet_click_adds_entity_id_to_url` | click facet → ?entity_id=... appended |
| `test_displays_empty_state_when_q_blank` | empty state copy visible |
| `test_displays_zero_results_state` | mocked 0 hits → explicit copy |
| `test_pagination_changes_page_param` | next button → ?page=2 |
| `test_renders_snippet_with_marks_from_offsets` | given `snippet="apple pie"` + `match_offsets=[(0,5)]` → DOM contains `<mark>apple</mark> pie`; assert NO `dangerouslySetInnerHTML` is used (grep the rendered React tree) |
| `test_renders_snippet_escapes_special_chars_safely` | `snippet="<script>x</script>"` rendered as literal text, never executed (React auto-escape) |
| `test_renders_snippet_no_offsets_renders_plain_text` | empty `match_offsets` → plain text only |
| `test_clear_filters_resets_url_params` | clear → all query params dropped except q |

Minimum 10 tests.

**Acceptance criteria**:
- [ ] `pnpm typecheck` clean.
- [ ] `pnpm test app/(app)/search/__tests__/` passes (≥10 tests).
- [ ] `pnpm build` succeeds.
- [ ] No new npm dependency added (DOMPurify is **not** needed — see AD-W6-3 snippet contract).
- [ ] Manual: visit `/search?q=apple` against running stack → page renders with results.

#### T-W6-4-03: Top-bar search command-palette wiring

**Type**: impl
**depends_on**: T-W6-4-02
**blocks**: T-W6-5-01
**Target files**:
- `apps/worldview-web/components/shell/TopBar.tsx` (extend — find existing search input)
- `apps/worldview-web/components/shell/CommandPalette.tsx` (extend if exists)
- `apps/worldview-web/components/shell/__tests__/TopBar.test.tsx` (extend)

**What to build**: When the user submits the existing top-bar search (currently calls `/v1/search/instruments` per PLAN-0050), if no instrument matches OR the user presses `⏎ Enter` after `?` modifier, navigate to `/search?q=<text>` instead.

Heavy comments explain the routing precedence (instrument hit → direct nav to instrument; no instrument hit → fallback to full-text search page).

**Tests** (vitest):
| Test | What |
|------|------|
| `test_topbar_redirects_to_instrument_when_match` | existing behaviour preserved |
| `test_topbar_redirects_to_search_when_no_match` | new fallback |
| `test_topbar_q_param_url_encoded` | special chars escaped |
| `test_topbar_no_instrument_match_shows_inline_hint` | (Sam-fit) brief "no instrument matched — searching all content" hint visible before navigation, so Sam isn't silently redirected |

Minimum 4 new tests (was 3; +1 for inline hint per audit LOW finding).

**Acceptance criteria**:

---

#### T-W6-4-04: Saved search + "what's new since" unread badge

**Type**: impl
**depends_on**: T-W6-4-02
**blocks**: T-W6-5-01
**Target files**:
- `services/api-gateway/alembic/versions/00XX_add_saved_searches.py` (new — small migration on api-gateway DB)
- `services/api-gateway/src/api_gateway/routes/saved_searches.py` (new)
- `services/api-gateway/src/api_gateway/api/schemas.py` (extend — add `SavedSearch` Pydantic)
- `apps/worldview-web/app/(app)/search/SavedSearchesSidebar.tsx` (new)
- `apps/worldview-web/app/(app)/search/__tests__/SavedSearches.test.tsx` (new)
- `services/api-gateway/tests/unit/api/test_saved_searches.py` (new)

**PRD reference**: PRD-0034 §2 persona Sam ("researches ≤20 tickers actively, watches ≤100") — Sam re-runs the same queries on familiar names; saved-search retention is the highest-leverage post-MVP retention feature for the persona.

**What to build** (added 2026-05-03 per Sam-alignment audit, audit's NEW T-W6-4-04 — promoted into the plan):

1. **Schema**: `saved_searches(id UUID PK, user_id UUID NOT NULL, q TEXT NOT NULL, filters_json JSONB NOT NULL, last_viewed_at TIMESTAMPTZ NOT NULL DEFAULT now(), created_at TIMESTAMPTZ NOT NULL DEFAULT now())` with index on `(user_id, last_viewed_at DESC)`. Lives in api-gateway DB (cross-service search history doesn't belong in nlp_db).
2. **API**:
   - `POST /v1/search/saved` body `{q, filters}` → `{saved_search_id}`.
   - `GET /v1/search/saved` → list of `SavedSearch` with `unread_count` field (computed by re-running the search with `published_at > last_viewed_at`, counting hits, capped at 99). Cached 60s per user to avoid re-running every poll.
   - `DELETE /v1/search/saved/{id}`.
   - `POST /v1/search/saved/{id}/mark_viewed` → updates `last_viewed_at = now()`.
3. **Frontend `SavedSearchesSidebar`** (above EntityFacetSidebar):
   - Lists saved searches as chips with `q` + `[unread_count]` badge.
   - Clicking a chip restores the URL params and calls `mark_viewed`.
   - "Save current query" button at the top of the page when `?q` is non-empty and not already saved.
4. R23 / R27 compliance: read endpoint uses ReadOnlyUoW; write endpoints use full UoW. Per-user, no cross-tenant aggregation.
5. Free-tier cap: 5 saved searches; Pro tier: 50. Enforced at `POST` time.

**Tests** (≥6):
| Test | What |
|------|------|
| `test_post_saved_search_creates_row` | row exists in DB with correct user_id |
| `test_get_saved_searches_returns_user_only` | RLS-equivalent check — user A doesn't see user B's saves |
| `test_unread_count_decrements_after_mark_viewed` | post-view, unread=0 |
| `test_unread_count_capped_at_99` | doc count = 250 → unread shown as 99 |
| `test_free_tier_capped_at_5_saved` | 6th POST → 403 |
| `test_delete_saved_search_removes_row` | DELETE → 404 on subsequent GET |

**Acceptance criteria**:
- [ ] Migration applied to api-gateway DB.
- [ ] Endpoints behind existing auth middleware (no anonymous saves).
- [ ] Frontend sidebar visible on `/search`.
- [ ] All 6+ tests pass.

---

#### T-W6-4-05: Snippet popover (verify-without-leaving)

**Type**: impl
**depends_on**: T-W6-4-02
**blocks**: T-W6-5-01
**Target files**:
- `apps/worldview-web/app/(app)/search/SearchResultCardSheet.tsx` (new — shadcn `<Sheet>` wrapper)
- `apps/worldview-web/app/(app)/search/SearchResultsList.tsx` (extend — open Sheet on card-title click)
- `apps/worldview-web/app/(app)/search/__tests__/SearchResultCardSheet.test.tsx` (new)

**PRD reference**: PRD-0034 §2 persona Sam — "pain is finding the relevant claim across sources"; the AlphaSense/Sentieo verification pattern.

**What to build** (added 2026-05-03 per Sam-alignment audit, audit's NEW T-W6-4-05 — promoted into the plan):

A right-side `<Sheet>` drawer (shadcn) that opens when the user clicks a result-card title (NOT the "Open source ↗" link, which keeps the new-tab escape hatch). The Sheet content:
- Result title + source badge + published date in the header.
- The full snippet from the search result (already truncated to ~280 chars on the API side; the Sheet shows it without further truncation).
- All other matched chunks for the same doc (fetched lazily on Sheet open via a new `GET /v1/search/document/{doc_id}/chunks?q=` endpoint OR via a top-up call to `/v1/search` with `entity_id=` derived from the doc — implementation detail decided in the use-case layer; the simpler path is a per-doc top-up call so no new endpoint is needed).
- Entity mentions for that doc as chips (linkable to the instrument page).
- A primary "Open source ↗" button that navigates to the source URL in a new tab.

**Why a Sheet not a modal**: the Sheet keeps the result list visible and scrollable behind a translucent overlay; Sam can keep scanning while a verification panel is open. Modal would force commit/close cycles.

**Note about reuse**: PLAN-0062 W4-D-02 added an `onCitationOpen` hook on `<StructuredBrief>` — both the brief citation chips AND search result cards SHOULD eventually share a single `<SnippetSheet>` component (codified in F-W6-NEW-1 follow-up). For W6 v1 we keep the search Sheet local; deduplication is a later refactor.

**Tests** (≥4):
| Test | What |
|------|------|
| `test_card_title_click_opens_sheet` | click → Sheet visible with snippet |
| `test_open_source_link_does_not_open_sheet` | click "Open source ↗" → no Sheet, anchor navigates |
| `test_sheet_open_source_button_links_to_url` | Sheet's CTA href matches result url |
| `test_sheet_close_restores_focus` | a11y — closing Sheet returns focus to result card title |

**Acceptance criteria**:
- [ ] Sheet renders on title click and not on link click.
- [ ] All 4+ tests pass.
- [ ] No new npm dep (shadcn Sheet already in the app).

---

**Acceptance criteria**:
- [ ] Existing TopBar tests still pass.
- [ ] 3 new tests pass.
- [ ] No new typecheck/lint errors.

### Wave 4 Pre-read
- `services/api-gateway/src/api_gateway/routes/proxy.py` lines 142-160 (existing news/relevant proxy as template)
- `services/api-gateway/src/api_gateway/middleware.py` (RateLimitMiddleware patterns)
- `apps/worldview-web/app/(app)/news/page.tsx` (similar list+facet UI pattern)
- `apps/worldview-web/lib/api/news.ts` (gateway method style)
- `apps/worldview-web/components/shell/TopBar.tsx` (existing search input)
- `docs/ui/URL_STATE.md` (PLAN-0059 C-6 nuqs guidance)

### Wave 4 Validation Gate
- [ ] Backend ruff + mypy clean
- [ ] Frontend `pnpm lint` + `pnpm typecheck` clean
- [ ] All Wave 4 tests pass (≥17 across S9 + frontend)
- [ ] `pnpm build` succeeds
- [ ] Architecture test green (S9 proxy doesn't import S6 directly — uses httpx)

### Wave 4 Break Impact
| Broken File | Why | Fix |
|------------|-----|-----|
| `apps/worldview-web/components/shell/TopBar.tsx` | Routing precedence change | T-W6-4-03 updates and adds tests |
| `apps/worldview-web/lib/query/keys.ts` | Need `qk.search.documents(...)` factory | Add per PLAN-0059 C-2 pattern |
| `services/api-gateway/tests/test_routes_smoke.py` (if exists) | Asserts route count | Bump expected count |
| `apps/worldview-web/middleware.ts` | If route protection list is hard-coded | Add `/search` to authenticated routes |

### Wave 4 Regression Guardrails
- **SEC-003** (callback sanitization analogue): never echo back q via redirect; always render through React's automatic escaping. **No `dangerouslySetInnerHTML` is used anywhere in the search UI** — snippets render via `match_offsets` (see T-W6-4-02 helper). DOMPurify is therefore not required.
- **SEC-008 / CSP**: snippets are plain text on the wire; no `<mark>` / `<b>` / `<script>` / any HTML traverses the API boundary. Frontend wraps matched ranges in JSX `<mark>` elements; React auto-escapes all character content.
- **BP-127** (ruff drift) + **BP-205** (frontend pnpm exact versions): no `^` versions if we add deps. (No deps added in this wave.)
- **BP-145** (OIDC issuer= check): N/A — using existing middleware.
- **BP-146** (PKCE atomicity): N/A — no PKCE here.
- **BP-148** (Avro default mismatch): N/A — no Avro.
- **R14** (frontend → S9 only): the new gateway client only calls `/v1/search`, never S6 directly.
- **R27** (read replica): **NOT claimed** — see §0 Architecture Compliance Adjustments. Tracked as a follow-up in §15.
- **System-JWT propagation**: S9 → S6 hop must include `X-Internal-JWT` per `_system_headers` precedent — asserted by `test_search_proxy_includes_internal_jwt_header_to_s6`.
- **Rate-limit bypass**: existing global per-user-per-minute limit is enforced; per-tenant per-day deferred to PLAN-0065.

---

## 10. Wave 5 — Acceptance, Docs, Compounding

**Goal**: Run the PRD acceptance criteria end-to-end, write user-facing + service docs, and update compounding artefacts.
**Depends on**: Wave 4, **PLAN-0055 (universe expansion / W2)**
**Estimated effort**: 45–60 min
**Architecture layer**: validation + documentation

### Tasks

#### T-W6-5-01: Acceptance test against running stack

**Type**: test
**depends_on**: T-W6-4-02, T-W6-3-02, **PLAN-0055**
**blocks**: T-W6-5-02
**Target files**:
- `tests/e2e/test_search_w6_acceptance.py` (new)

**What to verify** (PRD §3 FR-T1-3 acceptance):

| Acceptance | Test |
|-----------|------|
| Search latency p95 ≤ 500ms | seed ≥10K chunks across S&P 500 instruments; run 100 mixed queries; assert p95 < 500ms (must run against the populated dev stack, not a unit fixture) |
| Entity facet returns ≥1 hit for any S&P 500 ticker | iterate all S&P 500 canonical entities; for each, assert search with `entity_id=<that>&q=*` returns ≥1 hit OR explicitly tag the ticker as having no ingested coverage yet |
| Results paginated 25/page | response.page_size == 25 default; response.results.length ≤ 25 |
| Citation accuracy (cross-FR check) | every result has non-null `source_url` OR explicit `source_url=null` is logged; 0% of returned URLs return 404 (sample 10 random hits) |

Minimum 4 acceptance tests, run as part of `tests/e2e/`.

**Acceptance criteria**:
- [ ] All acceptance tests pass against the dev stack.
- [ ] Latency test results recorded in audit log.
- [ ] If S&P 500 coverage gap exists, document it (don't fail — PLAN-0055 is a separate workstream).

#### T-W6-5-02: Documentation + service-context updates

**Type**: docs
**depends_on**: T-W6-5-01
**blocks**: none
**Target files**:
- `docs/services/nlp-pipeline.md` (extend — add `/api/v1/search/documents` endpoint section)
- `docs/services/api-gateway.md` (extend — add `/v1/search` route)
- `services/nlp-pipeline/.claude-context.md` (extend — add new endpoint to API Endpoints list)
- `services/api-gateway/.claude-context.md` (extend if applicable)
- `apps/worldview-web/.claude-context.md` (extend — add `/search` page)
- `docs/MASTER_PLAN.md` (one-liner under S6 features list)
- `docs/plans/TRACKING.md` (mark waves complete)

**What to write**:
- Endpoint contract (request, response, errors, rate limit).
- Architecture decisions copied/summarised from §3 of this plan.
- Known limitations: no fuzzy matching; no transcripts ingested yet; aggregation per-chunk-max not BM25.
- Frontend route screenshots (if /design-ui assets are available, otherwise placeholder).

**Acceptance criteria**:
- [ ] All listed docs updated.
- [ ] `grep -r "/v1/search" docs/` finds at least the api-gateway entry.
- [ ] No stale references to "TODO" or "coming soon" for this feature in MASTER_PLAN.

#### T-W6-5-03: Compounding artefact updates

**Type**: docs
**depends_on**: T-W6-5-02
**blocks**: none
**Target files**:
- `docs/BUG_PATTERNS.md` (potential new patterns — see below)
- `RULES.md` (no expected change)
- `.claude/skills/plan/SKILL.md` (no expected change)

**What to write — only if observed during waves 1-4**:

- Candidate pattern: "Postgres `tsvector` full-text search must use a parameterised parser (`websearch_to_tsquery` or `plainto_tsquery`), not `to_tsquery`-with-string-concat, to avoid injection." (Likely BP-NEW-1.)
- Candidate pattern: "Reuse existing GIN indexes across feature waves; do not add a parallel index on the same column." (Likely BP-NEW-2.)
- Candidate pattern: "Cross-DB joins (nlp_db ↔ content_store_db) must be replaced by a use-case-level HTTP batch call to honour R9." (May reinforce existing R9 guidance.)

If none of these patterns have already fired during implementation, an explicit **"Compounding check: no updates needed"** note in the commit message is sufficient.

**Acceptance criteria**:
- [ ] BUG_PATTERNS.md updated OR explicit no-update note in commit.
- [ ] All other compounding documents reviewed.

### Wave 5 Validation Gate
- [ ] All e2e acceptance tests pass
- [ ] Docs updated and grep-verifiable
- [ ] TRACKING.md row updated to `completed`
- [ ] No reverted/orphan files

### Wave 5 Break Impact
| Broken File | Why | Fix |
|------------|-----|-----|
| `docs/services/nlp-pipeline.md` | Endpoint table out of date | T-W6-5-02 |
| `services/nlp-pipeline/.claude-context.md` | Endpoint count mismatch with `/api/v1/search/chunks` | T-W6-5-02 |

### Wave 5 Regression Guardrails
- **R15** (docs update mandatory on API change): T-W6-5-02 covers it.
- **Audit return-value persistence** (memory feedback `feedback_audit_returned_value_persistence.md`): the metrics + latency_ms in the response are persisted by Prometheus *and* logged via structlog `chunk_search_request`-style log line — confirm in T-W6-3-01.
- **Prompt input vs lookup mismatch** (memory feedback `feedback_prompt_input_mismatch.md`): not directly applicable, but parallel: ensure `entity_id` filter values are the *same UUIDs* the facet sidebar reports — mismatched entity_id schemes (canonical vs tenant) would silently drop everything. Asserted by T-W6-3-02 facet-roundtrip test.

---

## 11. Cross-Cutting Concerns Summary

| Concern | Status |
|---------|--------|
| Avro schema changes | None |
| Kafka topic changes | None |
| DB migrations | None in this plan (`chunks.tsv_english` + GIN `ix_chunks_tsv_english_gin` come from PLAN-0063 W5-2, shipped 2026-05-06) |
| Outbox pattern | N/A — read-only feature |
| Idempotency | N/A — read-only |
| Auth | Existing OIDC middleware on S9 + InternalJWTMiddleware on S6; S9 → S6 uses `_system_headers` precedent to mint `X-Internal-JWT` |
| Rate limiting | **No new bucket added.** Relies on existing global `RateLimitMiddleware` (per-user, per-minute). Per-tenant per-day deferred to the W8 RLS+Stripe plan (TBD — no plan ID yet; PLAN-0065 is W9 observability, already complete). |
| Documentation | T-W6-5-02 covers nlp-pipeline + api-gateway + worldview-web docs + MASTER_PLAN |
| Frontend security | Snippet rendered as React JSX `<mark>` from `match_offsets` (no HTML on the wire, no `dangerouslySetInnerHTML`, no DOMPurify needed); nuqs for URL state |
| Observability | 3 new Prometheus series; existing structlog patterns |
| Migration ordering | Depends on PLAN-0063 Wave W5-2 (alembic 0017); no migration owned by this plan |
| Cross-DB calls | S5 batch HTTP for titles + S7 batch HTTP for entity names (parallel via `asyncio.gather`); no JOINs across databases |

---

## 12. Risk Assessment

### Critical path
Wave 1 → Wave 2 → Wave 3 → Wave 4 → Wave 5 (linear).

Highest-leverage parallelism: T-W6-1-04 (frontend types) can start as soon as T-W6-1-01 lands the Pydantic spec.

### Highest risk
**Wave 3** was the riskiest. Its PLAN-0063 W5-2 dependency is now **MET** (`chunks.tsv_english` GIN `ix_chunks_tsv_english_gin` live since 2026-05-06). Residual risk: latency NFR at MVP scale (see secondary risks below).

### Secondary risks
- **Latency NFR (≤500ms p95)**: untested at MVP scale, and the budget now includes two parallel batch HTTP hops (S5 + S7). Mitigation: T-W6-3-02 includes a synthetic 1k-chunk latency assertion with mocked S5/S7 at 100ms each; the latency budget table in Wave 3 makes per-hop allotments explicit. T-W6-5-01 retests against ≥10K chunks. If p95 misses, options: (a) reduce default page_size to 10; (b) tighten LIMIT in CTE; (c) split facets into a separate `/v1/search/facets` endpoint with a higher latency budget; (d) escalate to /investigate.
- **Empty entity facets**: if W1 has not seeded enough canonicals (PLAN-0057 SHIP closed but ongoing seeding), facets may be sparse. Mitigation: T-W6-5-01 documents coverage gap rather than failing.
- **S7 batch endpoint absence or instability**: the use case depends on `POST /api/v1/entities/batch` being available and within latency budget. Mitigation: pre-read in Wave 2 confirms endpoint presence; client wraps `httpx.Timeout(2.0)` so a slow S7 cannot stall the request; if S7 returns partial data, facets fall back to `name=str(entity_id)` and log WARN.
- **Per-day rate limit gap**: PRD §4 NFR table mentions "100 search/day"; the existing middleware enforces only per-minute limits. Mitigation: documented as deferred work (PLAN-0065 / W8); for MVP the 100/min/user limit is sufficient.

### Rollback strategy
Plan is fully revertable via `git revert` of each wave commit. No destructive migrations. If Wave 3 ships and Wave 4 must roll back, the S6 endpoint stays live but has no caller — safe.

### Testing gaps
- No load test at production-scale concurrency (≥100 RPS). Acceptable for MVP launch; add to v1.1 backlog.
- No fuzzy / typo tolerance tests — by design (AD-W6-2 trade-off).

---

## 13. Open Questions / Risks

| ID | Question | Severity | Resolution |
|----|---------|----------|-----------------|
| OQ-W6-A | Where does `canonical_entities` live for the facet query? | **RESOLVED** | `intelligence_db`, accessed via S7 batch HTTP (`POST /api/v1/entities/batch`). No JOIN inside `nlp_db`. See AD-W6-3 + Wave 2 T-W6-2-03. |
| OQ-W6-B | Is anonymous (no-JWT) search desired for the public landing page? | LOW | Currently rejected as 401 in T-W6-4-01. Easy to flip to system JWT later if product wants it. |
| OQ-W6-C | Per-tenant per-day search rate limit | **DEFERRED** | Not added in this plan; existing global per-user-per-minute is enforced. Tracked in §15 follow-ups for the W8 RLS+Stripe plan (TBD — no plan ID yet; PLAN-0065 is W9 observability, already complete). |
| OQ-W6-D | Are transcripts ever ingested in MVP scope? | **RESOLVED** | No. `transcript` is removed from the `source_type` enum until ingestion ships. See §0 Known Limitations. |
| OQ-W6-E | Should highlighted snippet be HTML (`<mark>`) or plain text? | **RESOLVED** | Plain text + `match_offsets`. Frontend renders `<mark>` via React JSX (no `dangerouslySetInnerHTML`, no DOMPurify). See AD-W6-3 snippet contract. |
| OQ-W6-F | Should the S5 hop fields move into `document_source_metadata` to avoid a roundtrip? | LOW | Considered; rejected for MVP. Adding `title` / `source_url` to nlp_db would require a sync pipeline. The S5 batch hop is cheap (parallel with S7) and keeps the source-of-truth in S5. |

None of these are BLOCKING for /implement to start Wave 1.

---

## 14. Estimation Summary

| Wave | Tasks | Effort | Critical-path? |
|------|-------|--------|----------------|
| Wave 1 | 4 | 45-60 min | yes |
| Wave 2 | 3 | 120-150 min (added S7 client + snippet helper vs initial draft) | yes |
| Wave 3 | 2 | 60-90 min | yes (gated on PLAN-0063 W5-2) |
| Wave 4 | 3 | 90-120 min | yes |
| Wave 5 | 3 | 45-60 min | yes |
| **Total** | **15 task IDs across 5 waves (≈19 sub-deliverables incl. multi-file tasks)** | **~6-8 hours of agent time ≈ 3.5–4 dev-days** | |

PRD's 4 dev-day estimate is honoured. ~0.5 day saved by reusing PLAN-0063's GIN index instead of building a parallel one; ~0.5 day spent on the S7 batch client + snippet helper that the initial draft elided. Net: aligned with the PRD estimate.

---

## 15. Recommended Execution Order

1. ~~Verify PLAN-0063 Wave W5-2 status~~ **DONE** — alembic 0017 shipped 2026-05-06; `ix_chunks_tsv_english_gin` live. Sanity-check: `\d chunks` in psql confirms index.
2. `/implement PLAN-0064 Wave 1` — schema/contracts/types (parallel-safe). Can start immediately.
3. `/implement PLAN-0064 Wave 2` — repo + use case + S5 + S7 clients + snippet helper.
4. ~~**Gate**: confirm PLAN-0063 Wave W5-2 alembic shipped~~ — **already met**.
5. `/implement PLAN-0064 Wave 3` — route + integration.
6. `/implement PLAN-0064 Wave 4` — S9 + frontend.
7. **Gate**: confirm PLAN-0055 has populated S&P 500 universe.
8. `/implement PLAN-0064 Wave 5` — acceptance + docs.
9. `/qa PLAN-0064` — full QA pass before merge.

---

## 16. Follow-ups (Deferred — not in PLAN-0064 scope)

These items were considered during the 2026-05-03 audit and intentionally pushed out:

| Item | Why deferred | Owner / next plan |
|------|--------------|-------------------|
| Per-route, per-tenant, per-day rate limit on `/v1/search` (`100 search/day` from PRD §4 NFR) | Requires extending `RateLimitMiddleware` with rule-table, tenant key, and 24h window — 0.5–1 dev-day cross-cutting work. Belongs alongside W8 tier/quota machinery. | the W8 RLS+Stripe plan (TBD — no plan ID yet; PLAN-0065 is W9 observability, already complete) |
| `ReadOnlyUnitOfWork` / read-replica abstraction in nlp-pipeline | nlp-pipeline currently has a single pool. Building a read-replica abstraction is its own architectural change. Acceptable for MVP. | TBD — dedicated R27 retrofit plan (note: PLAN-0066 is W10 Brief Intelligence, already complete) |
| `transcript` source_type | Awaiting ingestion. When transcripts ship, add the enum value and update T-W6-1-01 / T-W6-3-02. | Future content-ingestion work |
| Move `title` + `source_url` into `document_source_metadata` to remove the S5 batch hop | Would require a sync pipeline; latency budget already accommodates the hop; not worth the complexity for MVP. | Re-evaluate at v1.1 if latency missed |
| Fuzzy / typo-tolerant matching | Trade-off accepted in AD-W6-2. | v1.1 |
| Load test at ≥100 RPS | Out of scope for MVP launch. | v1.1 |
| Amend PLAN-0063 §0 to drop the "W6 will add `documents.tsv`" expectation | One-line cross-plan note (N-1 in audit). | Open a small PR against PLAN-0063 docs. |
