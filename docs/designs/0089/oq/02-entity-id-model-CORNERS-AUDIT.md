---
id: PRD-0089-F2-CORNERS
title: F2 (Entity ID Unification) — Corners & Edges Audit
status: pending-user-review
created: 2026-05-20
parent: docs/designs/0089/oq/02-entity-id-model.md
locked_by: _DECISIONS.md §A DISCUSS-2 + §C FU-2.4/2.5 + §I no_backfill
---

# F2 — corners & edges audit (what cluster 02 missed)

Cluster 02 covers the core architecture decision (one canonical UUID per
tradable security, name = `instrument_id`, URL keyed by ticker). The
locked DISCUSS-2 + no_backfill constraint simplified the migration to
"drop seed + recreate". This audit hunts every concrete edge case the
cluster doc did NOT enumerate.

Severity legend:
- **🔴 BLOCKING** — F2 cannot ship without addressing this
- **🟡 IMPORTANT** — Plan should call it out explicitly; not a blocker
- **🟢 NICE** — Worth noting; can be deferred to v1.1

---

## §A — Coverage map (what cluster 02 + DECISIONS already address)

| Concern | Covered by |
|---------|------------|
| Two UUIDs per security today | Cluster 02 §2.1 + seed evidence |
| ADR-F-12 vs M-017 contradiction | Cluster 02 §3 |
| 145 LOC translation cost in S9 | Cluster 02 §2.3 |
| Ticker URL form (`/instruments/AAPL`) | DISCUSS-2 + FU-2.1 |
| Multi-class share dot form (`BRK.B`) | DISCUSS-2 + FU-2.2 |
| Field name stays `instrument_id` | DISCUSS-2 + FU-2.3 |
| Single-exchange canonical listing | DISCUSS-2 |
| `ticker_aliases` table forever-retention | FU-2.4 |
| New-tenant cutover only | FU-2.5 (mooted by no_backfill) |
| No backfill required | §I directive |

---

## §B — Corners we missed (the actual audit)

### Schema & data-shape gaps

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-01 | **`canonical_entities.kind` discriminator** — does the column exist today? If yes, what's the value for tradable securities? If no, F2 must add it and enumerate values (`financial_instrument`, `person`, `event`, `sector`, `macro_indicator`, `place`, `product`, etc). The unification ONLY applies to `kind=financial_instrument`. | 🔴 | Grep `canonical_entities` schema; if `kind`/`entity_type` column absent, F2 Alembic migration adds it with check-constraint enum + populates seed data |
| C-02 | **18 Avro schemas reference one or both IDs.** Cluster 02 doesn't enumerate them. Each must be classified: (a) tradable-only → use unified UUID, (b) any-entity → keep `entity_id`, (c) carries both → drop the redundant one. Notable: `entity.canonical.created.v1`, `entity.dirtied.v1`, `nlp.article.enriched.v1`, `portfolio.events.v1`, `alert.*.v1`, `intelligence.temporal_event.v1`, `intelligence.contradiction.v1`, `watchlist.item_*.avsc`. | 🔴 | F2 plan §X: schema-by-schema audit table with the (a/b/c) classification + R5 forward-compat note |
| C-03 | **api.ts: 36 `entity_id` refs + 29 `instrument_id` refs**, 9 types carry both simultaneously. Post-F2 these are redundant for tradable contexts. Decision: keep both for type-stability v1 (set equal) or drop one and break consumers. | 🟡 | F2 plan picks v1 = keep both, equal values; v1.1 cleanup pass drops `entity_id` from tradable-context types |
| C-04 | **Cypher queries** — `generate_narrative.py:306,329` and `cypher_neighborhood.py`, `cypher_path.py` join on `canonical_entities.entity_id`. After unification the SQL is unchanged (column stays; values now equal `instrument_id`). Confirm no Cypher query JOINs entity_id ↔ instrument_id across services (impossible by R7 anyway) | 🟢 | Document the invariant in F2 plan; no code change |

### Frontend ID handling

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-05 | **TanStack query key invalidation** — `qk.instruments.entityGraph(id, depth)` currently takes the *KG* `entity_id`. After F2 it takes the unified `instrument_id` (same value). Old caches don't survive because the underlying UUID changes during the seed-rebuild; with no_backfill, `docker compose down -v` clears everything. **But** if a dev runs F2 against an existing volume without `-v`, TanStack cache mismatch is silent. | 🟡 | F2 plan §X: explicit reset step `docker compose down -v` + frontend cache version bump (`qk.VERSION = "v2"` constant) so post-F2 keys never collide with pre-F2 |
| C-06 | **`bundle.overview.instrument.entity_id` field** — currently a different value from `.instrument_id`. After F2, identical. Frontend components that currently use `.entity_id` to call KG endpoints continue to work (same value). But code that compares both as a sanity check (`if entity_id !== instrument_id: warn`) becomes a no-op. | 🟢 | Grep frontend for `entity_id !==` and `entity_id ===`; flag any conditional logic |
| C-07 | **`useChartTechnicals` and any hook that takes `entityId` vs `instrumentId` as separate args** — collapse to a single `id` arg post-F2. | 🟡 | F2 plan: audit hooks/ for prop naming consistency; cleanup pass |

### URL routing edges

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-08 | **Reserved-word collision on `/instruments/{ticker}`** — current frontend has `/instruments/[entityId]` only (just the slug + error/loading/page). If we keep `[entityId]` as `[ticker]` slug, no collision today. But what if we ever want `/instruments/compare` (a feature page)? Next.js routes win over slugs only if defined statically. Future-proof: never name a feature page under `/instruments/X`. | 🟡 | F2 plan: name routes outside `/instruments/{ticker}`: e.g. `/compare`, `/screener`. Document a "no static children of `/instruments`" rule |
| C-09 | **Case sensitivity** — `/instruments/aapl` vs `/instruments/AAPL`. Industry standard: uppercase canonical, lowercase 301-redirects. Without this, two URLs reference one instrument. SEO impact (post-prod) + cache fragmentation. | 🟡 | F2: middleware in `apps/worldview-web/middleware.ts` that `next/server.NextResponse.redirect` lowercase tickers to uppercase. Or simpler: gateway lookup is case-insensitive (`upper(ticker)` index already exists per cluster 02 §3 D-2.6) + frontend always renders uppercase |
| C-10 | **Dot in URL path** — `/instruments/BRK.B`. Next.js dynamic routes accept dots; verify in practice. Tests must cover BRK.B, BF.B, RDS.A. | 🔴 | F2 plan: Playwright test `instrument-url-special-chars.spec.ts` covering BRK.B + BF.B; verify gateway lookup handles them |
| C-11 | **Special-character ticker normalization** — EODHD uses `BRK.B`; Yahoo uses `BRK-B`; Bloomberg uses `BRK/B`. Single canonical form: **dot** per DISCUSS-2/FU-2.2. Adapter layer normalizes on ingest. | 🟡 | F2 plan: data-ingestion normalization at S2 boundary; document canonical form |
| C-12 | **Index tickers (`^TNX`, `^GSPC`)** — these aren't `kind=financial_instrument`; they're `kind=index` or similar. Watchlist sidebar IndexStrip per cluster 04 references `^TNX`. Does the URL `/instruments/^TNX` work? Caret in URL is reserved per RFC 3986 → percent-encoded as `%5E`. UX risk. | 🟡 | F2 plan: indices either get their own `/indices/{ticker}` route OR we strip the caret for routing (`/instruments/TNX` with kind=index discriminator). Recommend: keep `^` in DB, strip for URL, normalize on gateway lookup |
| C-13 | **Numeric tickers (HKEX `0700` Tencent)** — out of v1 scope (single-exchange US). Confirm in F2 plan. | 🟢 | Confirm in F2 §out-of-scope |

### Migration semantics (with no_backfill simplification)

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-14 | **Drop order across services** — DBs depend on each other's IDs (S1 holdings.instrument_id refs S2 instruments.id; S10 alerts.entity_id refs S7 canonical_entities.entity_id). With no_backfill, `docker compose down -v && up` resets everything. But seed scripts run in sequence — order matters or referential checks fail. Today: `make seed` runs `seed-dev-data.sql` (S1+S2 combined) then `seed_demo_data.py` (S7+others). | 🔴 | F2 plan §X: explicit seed-script-rewrite order (1: KG canonical_entities → 2: market_data.instruments using SAME UUIDs → 3: portfolio.holdings → 4: nlp + alerts). Or unify all seeding into one script |
| C-15 | **`seed-dev-data.sql` line 46** currently has the embedded mismatch (`01900000-...001001` AAPL with `entity_id='11111111-0001-...'`). F2 must rewrite this line. Plus `seed_demo_data.py:95`. Plus `seed-eval-corpus.py` (has BRK.A/B references). | 🔴 | F2 plan §X: explicit list of seed files to rewrite, with grep verification post-change |
| C-16 | **Alembic migration semantics** — even with no_backfill, F2 needs migrations because the schema may change (e.g. adding `kind` column, partial unique index `(upper(ticker), exchange)`). Plan must enumerate: how many migrations across which DBs (market_data_db, kg_db, intelligence_db, portfolio_db, content_db, alert_db). | 🟡 | F2 plan §X: per-DB Alembic migration list; verify HEAD revisions |
| C-17 | **`ticker_aliases` table location** — cluster 02 says `intelligence-migrations/alembic/versions/...` but intelligence_db is for S7 fact tables. Aliases relate to canonical entities — kg_db is the right place. Or market_data_db (since the alias is an instrument concern). Pick one. | 🟡 | F2 plan: place in `kg_db` alongside `canonical_entities` (single source of truth for entity identity); document |

### Process & worker edges

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-18 | **Provisional → canonical entity promotion** — S6's `provisional_enrichment_worker` promotes provisional entities to canonical. For a `kind=financial_instrument` promotion, it MUST look up the existing `instrument_id` from market_data (or wait for the M-017 outbox-published event). Cannot mint a fresh UUID. | 🔴 | F2 plan §X: code change in `services/nlp-pipeline/.../provisional_enrichment_worker.py`: when promoting tradable, look up `instrument_id` by ticker; if not found, **defer** promotion until S2 ingests |
| C-19 | **`InstrumentDiscoveredEvent` → S7 consumer** — S2 emits new instruments; S7 must NOT mint a new entity UUID for the same security. M-017 declares the invariant but enforcement is in S7's `knowledge_graph_instrument_discovered_consumer`. Verify the consumer uses the event's `instrument_id` as the new `canonical_entities.entity_id`. | 🔴 | F2 plan §X: verify consumer logic; add unit test asserting `entity_id == event.instrument_id` |
| C-20 | **Race condition: article tagged by ticker before instrument ingested** — if S5 sees an article mentioning AAPL and AAPL has not yet been ingested by S2 (cold-start), the entity-resolution worker can't get an `instrument_id`. Options: (a) defer entity creation until S2 catches up, (b) mint a deterministic UUID from ticker (e.g. UUIDv5 in a namespace), reconciled when S2 catches up. | 🟡 | F2 plan §X: document the race; recommend (a) defer with backoff (since no_backfill, S2 should always ingest first in dev). Add v1.1 ticket for (b) deterministic UUID for safety |
| C-21 | **Brokerage sync (S1)** — SnapTrade returns "symbol" strings (e.g. `AAPL`). The mapping to `instrument_id` happens in `services/portfolio/.../snaptrade_adapter.py`. Today's mapping may use a `entity_id` lookup (cluster 02 §2.1 shows `InstrumentRef.entity_id` as a bridge field). After F2, the adapter just looks up by ticker. | 🟡 | F2 plan §X: audit and simplify `snaptrade_adapter.py` to use ticker→instrument_id direct |
| C-22 | **OutboxAdapter idempotency on instrument-discovery replay** — if `market.instrument.discovered.v1` is replayed (Kafka offset reset), S7 must not double-mint. Idempotency key should be the `instrument_id` itself; `UPSERT canonical_entities ON CONFLICT (entity_id) DO NOTHING`. | 🟡 | F2 plan §X: verify consumer SQL is UPSERT with entity_id PK |

### Endpoint surface

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-23 | **`/v1/entities/{id}/...` for non-tradable entities** — these stay (events, executives, sectors). After F2, the route exists side-by-side with `/v1/instruments/{ticker}`. Routing logic: tradable → `/instruments/{ticker}`, non-tradable → `/entities/{uuid}`. No frontend `/entities/{uuid}/...` page exists yet (only API). Implication for v1.1: do we want a page like `/entities/{uuid}` for executives? | 🟢 | F2 plan: out-of-scope for v1; flagged for v1.1 PRD |
| C-24 | **Bundle endpoint 145-LOC translation logic** — cluster 02 §2.3. F2 wave must explicitly delete `services/api-gateway/src/api_gateway/clients.py:230-299`, `:314-342`, `:548-580`, `:370-382`. Without explicit deletion, F2 ships with dead code. | 🔴 | F2 plan §X: explicit "delete these line ranges" task with test coverage gate (clients_test.py should still pass) |
| C-25 | **`/v1/instruments/lookup`** — must accept ticker as primary key. Verify the current implementation accepts both `?id=UUID` and `?ticker=AAPL`. If only one path: add the other. | 🟡 | F2 plan §X: verify lookup endpoint surface area; ensure both query forms supported |

### Performance edges

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-26 | **Ticker→UUID lookup cache** — every `/instruments/AAPL` URL hit requires the resolution. The `idx_entities_ticker_exchange` partial unique index gives sub-ms lookup. But in-process LRU in S9 (e.g. `cachetools.TTLCache(maxsize=10000, ttl=3600)`) saves the round-trip. | 🟢 | F2 plan §X: ship in-process LRU in gateway; invalidate on `entity.dirtied.v1` for the affected entity_id |
| C-27 | **Ticker rename event invalidation** — when META←FB renames, S2 emits an event; the LRU + `ticker_aliases` table both update. Order: alias write → LRU invalidate → emit event. | 🟢 | F2 plan §X: document order; add unit test |

### Test coverage

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-28 | **Test fixtures with hardcoded UUIDs** — many tests use `entity_id="11111111-..."` and `instrument_id="01900000-..."` as different values. Some tests may assert "they are different". F2 must audit + update. | 🔴 | F2 plan §X: grep `11111111` and `01900000` across `services/**/tests/` and `apps/worldview-web/__tests__/`; rewrite to use unified UUIDs |
| C-29 | **Playwright E2E navigates by UUID** — current E2E specs visit `/instruments/{uuid}`. All E2E specs need updating to `/instruments/{TICKER}`. | 🔴 | F2 plan §X: update Playwright specs |
| C-30 | **Architecture test for invariant** — add a test that asserts: for every row in `canonical_entities` where `kind='financial_instrument'`, there exists a row in `market_data.instruments` with `id = canonical_entities.entity_id`. Enforces M-017 in CI. | 🟡 | F2 plan §X: add a postgres-backed integration test (run inside docker-compose test) that asserts the invariant on dev seed data |

### Documentation

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-31 | **ADR-F-12 supersession** — user explicitly flagged ADR-F-12 as wrong. F2 must write ADR-F-XX superseding it. | 🔴 | F2 plan §X: new ADR file `docs/architecture/decisions/F-XX-instrument-entity-id-unification.md` |
| C-32 | **`docs/services/*.md` and `services/*/.claude-context.md`** — many docs mention dual IDs. Audit + update. | 🟡 | F2 plan §X: grep `entity_id` + `instrument_id` in `docs/` and `.claude-context.md` files; update sections that describe the dual model |
| C-33 | **BP-342 / BP-373 / BP-374** — bug patterns describing the dual-ID bug. After F2, mark as RESOLVED with F2 wave reference. | 🟢 | F2 plan §X: amend BUG_PATTERNS.md entries |
| C-34 | **MASTER_PLAN.md + RULES.md** — any mention of `entity_id` distinction; reconcile. | 🟢 | F2 plan §X: grep + amend |

### State machine corners

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-35 | **Unknown-ticker URL** — `/instruments/UNKNOWNXYZ` → gateway lookup returns nothing → frontend shows "Instrument not found" + search suggestions. Need an explicit empty state, not the existing `entityId === "undefined"` redirect (which targets a different bug). | 🟡 | F2 plan §X: new component `InstrumentNotFound.tsx` (lives in `components/primitives/` per F1); route in InstrumentPageClient |
| C-36 | **Delisted instruments** — `instruments.status='delisted'` rows still resolve via ticker, but page renders "delisted" banner. No code change needed today (delisted column exists); UX may want a banner. | 🟢 | F2 plan §X: optional banner component; deferrable |
| C-37 | **Ticker-alias 301 redirect** — `/instruments/FB` → gateway resolves alias → return 301 to `/instruments/META`. Who issues: Next.js middleware (good for SEO) or page-level `redirect()`? Next.js middleware preferred. | 🟡 | F2 plan §X: middleware logic |

### Concurrency / topic compatibility

| # | Corner | Severity | Action for F2 plan |
|---|--------|---------:|--------------------|
| C-38 | **Kafka topic partition keys** — many topics partition by `instrument_id` (or `entity_id`). After unification, partitioning is unchanged for tradables. For non-tradable events (FOMC, sector), partition key stays `entity_id`. Validate no topic uses BOTH as partition keys for the same event class. | 🟡 | F2 plan §X: audit 18 Avro schemas; partition-key column per schema |
| C-39 | **`canonical_entities.entity_id` UUID format** — currently NON-v7 per cluster 02 §2.1. After F2, all tradable entities should use UUIDv7 (matching `instruments.id` format which IS v7). Non-tradable entities keep current format. | 🟡 | F2 plan §X: confirm new tradable inserts use `new_uuid7()`; non-tradable can keep `uuid4()` (cluster 02 doesn't break this) |

---

## §C — Cross-cluster implications discovered by this audit

These corners affect OTHER PRD-0089 design docs:

1. **Cluster 04 (Watchlist sidebar)** — C-12 (`^TNX` index ticker URL) affects how the IndexStrip clicks navigate. Currently each index ticker would land on `/instruments/^TNX` which is broken. **Action**: amend cluster 04 to clarify "IndexStrip cells do not navigate" OR introduce `/indices/{ticker}` route in v1.
2. **Cluster 06 (Graph)** — C-04 confirms Cypher queries are unchanged; cluster 06 is unaffected.
3. **Cluster 07 (Quote)** — C-24 (delete 145 LOC) means the Page Bundle endpoint becomes simpler; should reduce the cluster 07 spec's "Phase 1 + Phase 2" complexity.
4. **Cluster 08 (News)** — C-02 (`nlp.article.enriched.v1` schema audit) may surface that article tagging carries both ids redundantly.
5. **Cluster 09 (Workspace)** — C-15 affects the `?config=` URL share format if it embeds instrument IDs.
6. **F1 (Design system)** — C-35 needs a new primitive `InstrumentNotFound.tsx`; add to F1 primitive catalogue.

---

## §D — Recommended F2 plan structure (drawing from F1 template + this audit)

Sections:
1. Mission (one paragraph)
2. Bloomberg-grade resemblance checklist (URL ergonomics: ticker-first, case-canonical, dot-multi-class)
3. Schema specification — full delta per DB
   - 3.1 `canonical_entities.kind` discriminator column (C-01)
   - 3.2 `ticker_aliases` table (C-17 — placement in kg_db)
   - 3.3 Partial UNIQUE index on `(upper(ticker), exchange)` per FU-2.6
4. Avro schema audit — 18 schemas classified (a/b/c) per C-02 with R5 forward-compat plan
5. Service-by-service code changes
   - 5.1 S9 gateway: delete 145 LOC translation (C-24); add ticker→UUID resolution shim + in-process LRU (C-26)
   - 5.2 S7 KG: instrument-discovered consumer enforces M-017 (C-19); narrative/path Cypher unchanged (C-04)
   - 5.3 S6 NLP: provisional-enrichment worker defers tradable promotion when ticker has no instrument yet (C-18, C-20)
   - 5.4 S1 portfolio: brokerage adapter simplified (C-21)
   - 5.5 S2 market-data: ticker normalization at adapter boundary (C-11)
6. Seed-data rewrite
   - 6.1 Order across services (C-14)
   - 6.2 Specific files (`seed-dev-data.sql`, `seed_demo_data.py`, `seed-eval-corpus.py`) — C-15
   - 6.3 Verification: post-seed grep that asserts every `instruments.id` has a matching `canonical_entities.entity_id`
7. Frontend changes
   - 7.1 URL routing: rename slug `[entityId]` → `[ticker]`; middleware for case-canonicalization (C-09); 301 redirect for aliases (C-37); special-char handling (C-10, C-11, C-12)
   - 7.2 New primitive: `InstrumentNotFound.tsx` (C-35)
   - 7.3 TanStack cache version bump (C-05)
   - 7.4 api.ts type cleanup (C-03 — keep both fields v1, drop in v1.1)
   - 7.5 Hook prop naming consistency (C-07)
   - 7.6 Search-result URL construction (search returns tickers)
8. ADR + docs
   - 8.1 Write ADR-F-XX (C-31)
   - 8.2 Update docs/services/*.md + .claude-context.md (C-32)
   - 8.3 Resolve BP-342/373/374 (C-33)
   - 8.4 Reconcile MASTER_PLAN.md + RULES.md (C-34)
9. Tests
   - 9.1 Architecture invariant test for M-017 (C-30)
   - 9.2 Playwright special-character ticker tests (C-10)
   - 9.3 E2E update from UUID URLs to ticker URLs (C-29)
   - 9.4 Test fixture grep + rewrite (C-28)
10. Acceptance criteria + rollback
11. Estimation revised

Revised estimate post-audit:
- Original cluster 02 estimate: 3-5d (with no_backfill simplification)
- Post-audit added scope: +18 corner-items × ~0.3d avg = +5d
- **F2 total: 8-10 engineer-days** (vs 3-5d in the §D wave plan)

The plan-level wave est in `_DECISIONS.md §D` listed F2 = "2-3d backend
shim + URL routing"; this audit shows that was naively scoped. Most of
the extra time is in seed-data rewrite + Avro audit + test fixture
sweep — not new feature work.

---

## §E — Recommended next step

You have three options:

**Option A — Write the full F2 plan now** (similar 500-line depth to F1)
incorporating every corner above. I draft, you review, we dispatch a
single agent to execute.

**Option B — Patch cluster 02 in-place** with the corners + scope
adjustment, then write a leaner F2 plan that just executes against the
amended cluster 02. Less duplication.

**Option C — Defer F2 entirely until F1 lands** so the primitive
`InstrumentNotFound.tsx` exists when F2 needs it. Sequence becomes:
F1 → Page 1 (Global Shell, which uncovers more ticker-URL edges) → F2.
Counter-argument: Page 1 depends on F2 (watchlist navigation, ticker
URLs in TopBar). They are coupled.

Recommendation: **Option A**. F1 doesn't block F2 conceptually (different
files), and F2's ticker-URL changes have to land before Page 1 wires
the watchlist navigation. Run F1 and F2 in parallel branches if the
single-agent-per-page rule allows, OR run them sequentially F1 → F2 →
Page 1 in the same agent session pipeline.

Reply with `option A`, `option B`, or `option C` and I'll proceed. If
A: I'll write the F2 plan + draft the executor prompt the same way I did
for F1.
