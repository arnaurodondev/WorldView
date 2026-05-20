---
id: PRD-0089-OQ-02
title: Entity / Instrument ID Model & Standardisation
status: design — proposal awaiting user approval
owner: cluster-2 investigator
created: 2026-05-19
parent_index: docs/designs/0089/_INDEX.md
supersedes: ADR-F-12 (PRD-0027 §1367) — see §3 "History of the split"
related_oqs:
  - docs/designs/0089/oq/07-instrument-intelligence.md  (depth-3 timeout root cause = entity-id mismatch)
  - docs/designs/0089/00-backend-data-inventory.md      (every ID currently exposed)
  - docs/designs/0089/02-dashboard.md                   (locks /instruments/{instrument_id})
  - docs/designs/0089/03-portfolio-overview.md          (holdings emit both ids)
  - docs/designs/0089/08-screener.md                    (row shape has both ids)
---

# 02 — Entity / Instrument ID Model

> **The user's anchor**: "we should standardize entity and instrument id to reduce
> complexity and enable to query instruments by ticker". This document confirms the
> intent is *both* correct *and* achievable, proposes a better-than-anchor design
> (Option D — hybrid), and lays out a 4-wave migration with zero downstream-service
> rewrites in Phase 1.

---

## 1. Executive Summary

The platform carries two parallel UUID namespaces for the same real-world tradeable
security:

- **`instrument_id`** (UUID7) — market-data S3, S2 ingestion, S1 portfolio. Example for
  AAPL: `01900000-0000-7000-8000-000000001001`
  (`scripts/seed-dev-data.sql:46`).
- **`entity_id`** (UUID, non-v7) — knowledge-graph S7 `canonical_entities.entity_id`,
  S6 NLP, S10 alerts. Example for AAPL: `11111111-0001-7000-8000-000000000001`
  (`scripts/seed_demo_data.py:95`).

ADR-F-12 in PRD-0027 (`docs/specs/0027-frontend-mvp-ui-design.md:1367`) declared these
are *intentionally* distinct because S7 entities cover non-tradable things (people,
events, sectors) and one entity may map to N instruments (BRK.A vs BRK.B).
**However**: invariant **M-017** (`docs/audits/2026-03-27-deep-cross-service-qa-report.md:190`,
`infra/kafka/schemas/market.instrument.discovered.v1.avsc:11`) demands the *opposite*
— `instrument_id` = `canonical_entity.entity_id` for the financial_instrument subset.
These two invariants are silently in conflict, and the demo seed data violates M-017
on every single ticker. The result: the frontend route
`/instruments/01900000-...001001` issues every `/v1/entities/{id}/...` call against an
id the KG has never seen, producing 404s on briefings, graph, paths, contradictions,
and narratives — the user's reported bug.

**Recommended path (Option D, hybrid)** — single physical ID *and* ticker-keyed URLs:

1. Adopt `security_id` as the single canonical UUID for every tradable security.
   The KG canonical entity row IS the system-of-record (entity_type =
   `financial_instrument`). S3 stops minting its own UUID and instead reuses the KG
   `entity_id` as its primary key. Non-tradable entities (events, persons) keep
   `entity_id` unchanged.
2. URLs become `/instruments/{ticker}` (e.g. `/instruments/AAPL`). The gateway resolves
   ticker → `security_id` in one query (already-existing
   `idx_entities_ticker_exchange` in `intelligence-migrations/0001:134`).
3. Backwards-compat shim: every `/v1/instruments/{id}` route accepts ticker OR UUID;
   no caller breaks.

Phase 1 ships the ticker shim and frontend URL flip without touching DB FKs (5 days).
Phase 2-4 collapse the two UUIDs over six waves — backend-only, behind the gateway
shim, no frontend-visible change. Total estimated cost: **~6 waves over 2 sprints**;
zero Kafka topic re-keys (partition keys stay on the new unified `security_id`);
hot-path latency goes *down* (one less KG roundtrip in `get_company_overview`).

This **unblocks** PRD-0089 design docs 05 (Quote), 06 (Financials), 07
(Intelligence) by removing the entity-id resolution branch that currently bloats
every page-bundle endpoint by 80+ lines (`services/api-gateway/src/api_gateway/clients.py:223-465`).

---

## 2. Current state — diagram + evidence

### 2.1 Namespace map

```
                   ┌─ instrument_id (UUID7)  ──── primary key
  market-data (S3) │   01900000-0000-7000-8000-000000001001  (AAPL)
                   └─ symbol, exchange     stored as enrichment

                   ┌─ entity_id (UUID, non-v7) ─ primary key
  knowledge-graph  │   11111111-0001-7000-8000-000000000001  (AAPL canonical)
       (S7)        ├─ ticker, exchange         indexed but NON-UNIQUE
                   │   idx_entities_ticker_exchange  (partial, ticker IS NOT NULL)
                   └─ aliases (entity_aliases)  trigram-fuzzy

                   ┌─ InstrumentRef.id     local UUIDv4
  portfolio (S1)   │
                   ├─ InstrumentRef.entity_id  UUID | None     <— bridge field
                   │   (populated by M-017 outbox path,
                   │    nullable because the KG row may not exist yet)
                   ├─ symbol, exchange    denormalised
                   └─ Holding.instrument_id     <— FK target is S2's UUID space
                                                   (NOT a real FK — R7 no
                                                    cross-service DB access)
```

### 2.2 The bug the user observed

Concrete walkthrough, file:line cited:

1. Frontend renders the Watchlist panel (`apps/worldview-web/components/shell/WatchlistPanel.tsx:215`):
   ```ts
   onClick={() => router.push(`/instruments/${member.entity_id}`)}
   ```
   `member.entity_id` for AAPL came from S1's `WatchlistMember.entity_id` which is set
   to the M-017 bridge value (the S3 instrument UUID when the entity-resolution worker
   has run; otherwise null). In the demo dataset, this is
   `01900000-0000-7000-8000-000000001001` — the **market-data** id, not the KG id.

2. The instrument page server component pulls the param
   (`apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx:17`) and the
   client calls `useInstrumentBundle` (`apps/worldview-web/components/instrument/hooks/useInstrumentBundle.ts:8`).

3. S9 receives `GET /v1/instruments/01900000-.../page-bundle`. The composer
   (`services/api-gateway/src/api_gateway/clients.py:470`) does Phase 1 = overview, and
   `get_company_overview` (`clients.py:171`) executes the **70-line resolution dance**
   (`clients.py:230-299`):

   - try `GET /api/v1/instruments/lookup?id=01900000-...` against S3 → 200 OK.
   - read the resolved symbol `AAPL`.
   - call `/api/v1/entities/lookup?ticker=AAPL` against S7
     (`services/knowledge-graph/src/knowledge_graph/api/routes.py:179`) → returns
     `entity_id=11111111-0001-7000-8000-000000000001`.
   - bundle Phase 1 finishes with both ids stuffed into the response
     (`clients.py:370-382`):
     ```python
     instrument = {
         "instrument_id": instrument_raw.get("id", company_id),  # 01900000-...
         "entity_id": kg_entity_id,                                # 11111111-...
         ...
     }
     ```

4. Phase 2 of the bundle composer reads `entity_id` back out of the overview to call
   `_safe_nlp(f"/api/v1/news/entity/{entity_id}", ...)` (`clients.py:577`) — **this is the
   only Phase-2 leg that uses the KG id**; the rest (fundamentals, technicals, insider)
   call market-data with `resolved_md_id`. So the news works.

5. The **frontend** components that need KG endpoints have an explicit branch
   (e.g. `apps/worldview-web/components/instrument/EntityGraphPanel.tsx`,
   intelligence/* hooks) that reads `bundle.overview.instrument.entity_id` from the
   bundle response. **If**:

   - The KG `entities/lookup?ticker=AAPL` succeeded → `entity_id = 11111111-...` → KG calls
     succeed.
   - The KG lookup failed (e.g. ticker not in KG) → `entity_id` defaults to the input
     `company_id` (`clients.py:320`: `kg_entity_id: str = company_id  # default: fall back`).
     → every subsequent `GET /v1/entities/{entity_id}/...` call from the frontend hits
     S7 with an id S7 doesn't have → **404 cascade** = the bug.

6. Confirmed in BP records:
   - BP-342 (`docs/bug-patterns/api-contracts.md:912`) — exactly this 404 cascade.
   - BP-373 (`docs/bug-patterns/frontend.md:1018`) — screener/watchlist/holdings
     navigation with raw `entity_id` (sometimes null) routes to `/instruments/undefined`.
   - BP-374 (`docs/bug-patterns/frontend.md:1034`) — Phase-2 fundamentals used raw URL
     `instrument_id` even after Phase 1 resolved the *real* one.

### 2.3 The structural cost today

Lines of "id translation" logic counted (`services/api-gateway/src/api_gateway/clients.py`):

| Location | Lines | What it does |
|---|---|---|
| `get_company_overview` resolution dance | 230-299 (70) | id-lookup → fallback ticker-lookup → re-resolve |
| `get_company_overview` KG ticker lookup | 314-342 (29) | resolve KG entity_id by ticker |
| `get_instrument_page_bundle` Phase 1 → 2 wiring | 548-580 (33) | re-read both ids from Phase 1 overview |
| `bundle.overview.instrument` shape | 370-382 (13) | emit both ids alongside |
| **Total in S9** | **145 lines** | translation logic on hot path |

Frontend cost (`apps/worldview-web/types/api.ts`):

- `instrument_id` appears on 17 generated types
- `entity_id` appears on 12 generated types
- 9 of those types carry **both** simultaneously
  (`api.ts:131-132`, `api.ts:432-434`, `api.ts:746-747`, `api.ts:802-803`, `api.ts:1082-1083`,
  `api.ts:1114-1116`)

Every component that owns one of those types currently has a fallback expression like
`instrument_id ?? entity_id` (e.g. `apps/worldview-web/components/screener/screener-columns.tsx`,
referenced by BP-330, BP-373).

---

## 3. Why-split historical analysis

I traced the rationale across PRDs, ADRs, and bug patterns. The split is the
*accidental* outcome of three independently-correct decisions made at different times:

| Date | Decision | Why it made sense in isolation | Why it created the conflict |
|---|---|---|---|
| 2025-Q4 | S2/S3 ship first; S3 mints `instrument_id` as UUID7 | S7 didn't exist yet; instruments need a stable PK | Set a UUID7 convention before KG had its own UUID format |
| 2026-Q1 | S7 introduces `canonical_entities.entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid()` (`intelligence-migrations/0001:122`) | KG entities are a superset of instruments; need their own PK so persons/events/macro have homes | New UUID space; UUIDv4 default `gen_random_uuid()`, not UUID7 |
| 2026-Q1 | ADR-F-12 (PRD-0027 §1367) blesses the split | "BRK.A and BRK.B share one entity" + "OpenAI has no instrument" are real cases | Lifted the split to a contract instead of fixing the seed mismatch |
| 2026-Q2 | M-017 invariant (`audits/2026-03-27-deep-cross-service-qa-report.md:190`) demands `entity_id = instrument_id` on Kafka outbox payloads | Idempotent consumers need a stable cross-service id; the natural choice was S3's `instrument_id` because it's emitted first | Silently contradicts ADR-F-12. M-017 only works if the KG canonical_entities row is INSERTED with `entity_id = $market_data_instrument_id` |
| 2026-Q1 onwards | Demo seeds hard-code `11111111-...` for KG, `01900000-...` for S3, with a third bridge UUID in `instrument_refs` | Each seed file authored independently for its own service's tests | The seeds themselves are the M-017 violation. Production never ran the M-017 path on these tickers because they're seeded directly |

In short: ADR-F-12 said "keep two namespaces"; M-017 said "they must be equal";
the demo seed authors picked clean visual UUIDs in two different ranges. The
production path that *does* call `event_to_outbox_payload` honours M-017, but the
demo dataset (which is what the user is using) does not.

### Real "one-to-many" cases the split was meant to handle

The split's defensible cases (BRK.A vs BRK.B, ADRs, multi-listing):

- **BRK.A / BRK.B** — share company Berkshire Hathaway but have distinct economics
  (voting, price, market cap). The right ontology is **one company entity** + **two
  financial_instrument entities** that point at the company via a relation. Not one
  entity with two instruments.
  → Doesn't actually require two namespaces; requires two canonical_entities rows
  joined by a relation. The KG schema already supports this.
- **AAPL on Nasdaq vs hypothetical AAPL.L on LSE** — different listings of the same
  underlying security. Today S3 already creates *separate* `instrument_id`s for each
  exchange (`Instrument(security_id, symbol, exchange, ...)`) and S2 has a `Security`
  master record (`services/market-data/src/market_data/domain/entities.py:38-56`). The
  parent-`Security` abstraction is the join, not the entity_id split.
  → Reinforces the same point: instrument-vs-company should be one-to-many *within
  the KG entity space*, not across two namespaces.
- **OpenAI has no ticker** — true, and OpenAI's `entity_id` is a perfectly fine
  KG row with `entity_type='organization'`, `ticker=NULL`. Nothing about Option D
  breaks this; it lives in the same UUID space alongside AAPL.

### The split is not load-bearing

Searching for any code that *requires* `entity_id ≠ instrument_id`:

- ✗ No DB FK constraint depends on the values being different.
- ✗ No Kafka schema requires distinct UUIDs (`market.instrument.discovered.v1.avsc:14`
  literally documents "Set by event_to_outbox_payload (M-017) — portfolio (S2) uses
  this as its InstrumentRef.id so replays produce the same row").
- ✗ No domain model encodes the two as different types
  (`portfolio/domain/entities/instrument.py:30` has `entity_id: UUID | None`, same
  Python type as `id: UUID`).
- ✗ No analytical query requires the distinction.
- ✓ Only the **resolution dance in S9** and the **frontend dual-id types** depend on
  them being potentially-different — i.e. complexity that the split itself introduced.

---

## 4. Four options A / B / C / D

### Option A — Unify into a single `security_id`

**Idea**: Collapse `instrument_id` and `entity_id` into one UUID for the
`financial_instrument` subset. Non-tradable entities (events, persons, sectors)
keep `entity_id` unchanged — they are simply not addressable from
`/v1/instruments/{...}`.

**Concretely**:

- `canonical_entities.entity_id` becomes the system-of-record. S3
  `instruments.id` is migrated to be equal to it for the rows where a KG canonical
  entity exists. New instrument discoveries INSERT both rows in the same outbox
  transaction with `instruments.id = canonical_entities.entity_id`.
- Drop the bridge field `InstrumentRef.entity_id` (S1 holding).
- Every Kafka envelope keeps `instrument_id` field name for backwards-compat but the
  value IS the unified id.
- URLs unchanged (`/instruments/{security_id}` where security_id is the UUID).

**Pros**:
- Single ID across the platform; no more dual-id types in `api.ts`.
- M-017 becomes structural rather than convention.
- Removes 145 lines of S9 resolution logic.

**Cons**:
- DB migration touches: S3 `instruments.id` FK chain (OHLCV bars,
  fundamentals_records, quotes, all by `instrument_id`), portfolio
  `instrument_refs.entity_id`, plus topic re-keying *if* topic partition keys
  are on `instrument_id` (they are — `MASTER_PLAN.md:212`).
- Migration must rewrite every existing OHLCV bar's `instrument_id` if the unified
  id is the KG one (the seed already shows the mismatch in production data).
- BRK.A/BRK.B still need two `financial_instrument` rows in canonical_entities;
  not a problem but worth noting.
- User-facing URLs remain UUIDs — doesn't satisfy "query by ticker".

**Verdict**: solves the deduplication half. Does **not** solve the ergonomics half.

### Option B — Keep both IDs but make S9 translate seamlessly

**Idea**: Accept the dual-namespace status quo as a *physical* reality; lift the
S9 gateway to expose a *logical* contract where every endpoint accepts either id
and returns both. Frontend continues to carry both fields; backend services
unchanged.

**Concretely**:

- `/v1/entities/{id}/...` routes accept `id` as either a KG `entity_id` OR an S3
  `instrument_id` and resolve internally via a Valkey-backed cache
  (`gw:v1:idmap:{id} → {entity_id, instrument_id}`, TTL ~1h, populated lazily).
- `/v1/instruments/{id}/...` does the same.
- ID-resolution becomes a single helper in S9 used by all routers.

**Pros**:
- Zero backend-service migration. Zero Kafka changes.
- Backwards-compat trivially preserved.
- Can ship in a single wave.

**Cons**:
- The complexity moves but doesn't disappear — the gateway now owns the same
  resolution logic *forever*.
- Two-hop latency on every endpoint (cache miss → KG lookup → market-data lookup).
- ID-leakage on error responses still requires the frontend to know about two
  ids. The dual `instrument_id, entity_id` fields stay in `api.ts`.
- Cache invalidation: when S6 entity-resolution links a new ticker, S9 cache must
  bust. Adds another inter-service dependency.
- Doesn't satisfy "query by ticker" without yet another layer.

**Verdict**: a band-aid. Treats the symptom (404 cascade), not the design split.
Worth shipping **only as Phase 1 of D** while the deeper migration runs.

### Option C — Ticker as public ID

**Idea**: URLs are `/instruments/{ticker}` (e.g. `/instruments/AAPL`). Frontend
never sees UUIDs. Backend keeps both internal UUIDs unchanged; gateway resolves
ticker → ids on each request.

**Concretely**:

- Frontend route `app/(app)/instruments/[entityId]/page.tsx` becomes
  `app/(app)/instruments/[ticker]/page.tsx`. Param renamed.
- Watchlist, holdings, screener, search, graph — every `router.push` swaps to
  `/instruments/${row.ticker}`.
- S9 adds `GET /v1/instruments/lookup?symbol={ticker}` resolution at the
  entrypoint of every endpoint that currently takes a UUID; underlying service
  calls continue to use their own UUIDs.
- `api.ts` ditches all `entity_id, instrument_id` fields from response types
  where possible — the ticker is the public identifier.

**Pros**:
- Best ergonomics: `/instruments/AAPL` is what every analyst expects. Matches
  Bloomberg / TradingView / Finviz URL conventions.
- Shareable URLs — `apple.worldview.com/instruments/AAPL` is human-readable.
- The user's stated requirement ("query instruments by ticker") satisfied
  literally.
- Frontend dramatically simpler — one id type (string ticker), no fallbacks.

**Cons**:
- Ticker is **not globally unique**. Even if today we're US-only, the design must
  not assume that forever:
  - **Multi-exchange listings**: same ticker on different venues (e.g. `BHP` on
    ASX vs NYSE; `BABA` ADR vs HK 9988).
  - **Ticker reassignment**: ticker recycling after delisting (FB → META kept FB
    free for ~24 months; Twitter / X).
  - **Class shares**: `BRK.A` vs `BRK.B`, `GOOG` vs `GOOGL` — the dot/letter
    conventions vary across exchanges.
- URL stability under corporate actions: `FB → META`. Old URLs (`/instruments/FB`)
  must redirect. Solvable with a `ticker_aliases` table + 301 redirect, but it's
  ongoing operational cost.
- Ticker lookup performance: `idx_entities_ticker_exchange` is **non-unique**
  (`intelligence-migrations/0001:134`); a bare `WHERE ticker = 'AAPL'` can return
  multiple rows (Apple Inc. + Apple Inc. preferred + any duplicates left by
  dedup bugs). Today the lookup hides this by `LIMIT 1`
  (`knowledge-graph/...repositories/canonical_entity.py:138`) — silent data
  bug waiting to happen.
- International symbology (ISIN, CUSIP, RIC): demo is US-only but the platform
  ingests EODHD which carries non-US (`country` field in seed:
  `seed-dev-data.sql:46`). LSE `AAPL.L`, Tokyo `7203.T` — Stockanalysis.com uses
  `/quote/lse/aapl.l/`, TradingView uses `/symbols/LSE-AAPL/`. The convention
  must encode the exchange.

**Verdict**: best ergonomics, but the bare-ticker URL is fragile in a global
context. Resolve by either (a) requiring `/instruments/{exchange}-{ticker}`
(matches TradingView; e.g. `/instruments/NASDAQ-AAPL`), or (b) keeping plain
`/instruments/AAPL` with implicit `US` exchange and disambiguating via a
canonical-listing-per-ticker constraint. We recommend (b) for now — it's what
Bloomberg's terminal does — and accept that future global expansion will add
a `?exchange=LSE` query param fallback.

### Option D — Hybrid (RECOMMENDED): ticker URLs + unified internal `security_id` + UUID compat

**Idea**: combine Option A's structural fix with Option C's URL ergonomics, gated
behind Option B's gateway shim so we can ship in phases without breaking any
existing client.

**Concretely** (final state):

1. **Single canonical UUID** for tradable securities. `canonical_entities.entity_id`
   is the system-of-record. S3 `instruments.id` = `canonical_entities.entity_id`
   for `entity_type='financial_instrument'` rows.
2. **URLs use ticker** for the primary identifier. Default
   `/instruments/{ticker}` for US-listed; future extension
   `/instruments/{exchange}/{ticker}` for non-US (additive; old URLs survive).
3. **Gateway accepts UUID or ticker** on every existing `/v1/{...}/{id}` route
   forever (compatibility shim). Resolution is a single helper:
   ```py
   async def resolve_security_id(s: str) -> UUID:
       if is_uuid(s): return UUID(s)
       row = await kg.lookup_by_ticker(s.upper())
       if row: return row.entity_id
       raise HTTPException(404, f"No security for '{s}'")
   ```
4. **Kafka envelope field** `instrument_id` (string) is preserved verbatim — value
   carries the unified UUID. M-017 becomes structural (the producer reads the
   security row, can't accidentally diverge).
5. **`canonical_entities.ticker`** gains a **partial UNIQUE index** on
   `(upper(ticker), exchange) WHERE entity_type='financial_instrument'` (today
   only a non-unique index exists at `intelligence-migrations/0001:134`). This
   makes ticker → security_id a true 1:1 lookup with a DB-level invariant.
6. **`ticker_aliases`** (new table) records historical ticker changes:
   `(old_ticker, new_security_id, effective_from, effective_until)` for FB → META
   redirects. Frontend never sees this; S9 emits 301 on
   `/instruments/{old_ticker}`.

**Pros**:
- Solves both halves of the user's anchor.
- Removes the 145-line S9 dance + the 12-times-duplicated `instrument_id,
  entity_id` fields in `api.ts`.
- Phased rollout: gateway shim in Phase 1 means **zero** backend change is required
  to fix the user's current 404 bug; Option A's structural unification is a
  separate workstream that can run on its own timeline.
- M-017 becomes a DB constraint, not a code convention.
- Ticker URL is the natural Bloomberg/TradingView shape, with UUID compat retained.

**Cons**:
- DB migration is real (Phase 2/3): rewriting `instruments.id` to equal
  `canonical_entities.entity_id` requires either (a) backfilling existing rows
  one-by-one with explicit conflict handling on referencing FK chains (OHLCV,
  fundamentals, quotes) or (b) introducing a `security_id` column alongside
  `id` and slowly migrating writers/readers. We recommend (b) — see Phase 3.
- Two valid id formats in the wild during migration; the gateway shim must stay
  forever (which is fine; it's a 1-call cache lookup).
- BRK.A/BRK.B disambiguation: each class is its own `financial_instrument` row
  with its own ticker — no special-case logic.

**Verdict**: ✅ recommended. Captures Option A's structural cleanup, Option C's
ergonomics, Option B's shim safety net.

---

## 5. Migration cost matrix

| Dimension | A (unify) | B (shim) | C (ticker URL) | **D (hybrid, recommended)** |
|---|---|---|---|---|
| **DB migrations** (intelligence_db) | 1 large (PK swap on canonical_entities references, but PK is unchanged actually); +1 to backfill ids in S3 | 0 | 0 | 2 (add UNIQUE on `(upper(ticker), exchange)` partial; add `ticker_aliases`) |
| **DB migrations** (market_data_db) | 1 large: rewrite `instruments.id` to match KG; cascade FK to OHLCV, quotes, fundamentals, holdings refs | 0 | 0 | 1 medium: add `security_id` column to instruments; backfill from KG via ticker; flip primary key in a later wave |
| **DB migrations** (portfolio_db) | 1: drop `instrument_refs.entity_id` (becomes redundant), or null-coalesce | 0 | 0 | 1 small: deprecate `instrument_refs.entity_id` (alias for `id`) |
| **Kafka topic re-keying** | 0 (key field name unchanged, value content changes by row but the *key string* doesn't change shape; consumers idempotent) | 0 | 0 | 0 |
| **Kafka schema changes** | 0 (Avro field stays `instrument_id: string`) | 0 | 0 | 0 |
| **API endpoints affected** | every `/v1/entities/{id}` and `/v1/instruments/{id}` — but only because *callers* may pass either id; with the gateway shim, this collapses to one helper | 8-10 routes get the shim applied via middleware | every `/v1/instruments/{id}/...` accepts ticker | every route on S9 gets a 1-line resolver call; ~20 routes |
| **Frontend impact** | URLs unchanged; dual-id types collapse to one | None | Every `router.push("/instruments/${id}")` swap → `${ticker}`; param rename in route; `api.ts` types lose `entity_id`/`instrument_id` from ~12 shapes | Same as C plus opt-in to use UUID where preferred |
| **Test suite blast radius** | Every fixture that hard-codes `01900000-...` UUIDs (test_routes.py:51, test_quotes_api.py:22, et al.) needs the matching KG UUID seeded, OR the unification has to happen first | Add 1 contract test per shimmed route | Every component test that uses `/instruments/UUID` mocks; ~30 test files | C+A combined; ~50 test files |
| **Backwards compat** | Hard: old UUID values in S3 are no longer valid PKs after the rewrite | Trivial | Hard: old UUID URLs 404 unless gateway shim is added | **Trivial in Phase 1** (shim only); compatibility kept throughout |
| **Brokerage sync impact** | SnapTrade `BrokerageTransactionSyncWorker` writes `holding.instrument_id` — must use the new unified id; existing cached symbols → instrument map (per memory entry 2026-04-28) re-keys | None | None | None in Phase 1; in Phase 3 the resolver does the work |
| **Cached briefings (Valkey)** | `gw:brief:{instrument_id}` keys live ~24h; stale keys expire naturally | None | Keys re-shape to `gw:brief:{ticker}` over time | Same as C |

**Total estimated effort**:
- A: ~3 sprints, high risk (DB rewrite of S3 PK).
- B: 1 sprint, low risk, doesn't fix root cause.
- C: 1 sprint frontend + half-sprint backend, low risk.
- **D: 2 sprints total, low risk per wave** (each wave behind the shim).

---

## 6. Ticker-as-key deep dive

### 6.1 Ticker collision

Empirically:

- **AAPL** is uniquely Apple Inc. on Nasdaq US. EODHD `country='US'` rows have
  `(ticker='AAPL', exchange='US')`. Today's KG has 1 row.
- **BHP**: trades on ASX (BHP Group) and NYSE (BHP Billiton ADR). Both real
  companies, both real tickers, but they're the *same* underlying entity in the
  KG sense.
- **A**: ticker for both Agilent (NYSE) and Avantor (NYSE) at different historical
  points — recycling after delisting.

Resolution under Option D:

- Partial UNIQUE index on `(upper(ticker), exchange) WHERE entity_type='financial_instrument'`
  guarantees no two financial instruments share `(ticker, exchange)`.
- Default `/instruments/{ticker}` resolves to the US listing if one exists;
  ambiguity returns a disambiguation response (rare; we ship US-only Phase 1).
- `/instruments/{exchange}/{ticker}` is the unambiguous form for Phase 4.

### 6.2 Ticker change events

Historical: FB → META, FCAU → STLA, GOOG/GOOGL coexist, X (Twitter) ≠ X (US Steel,
delisted). EODHD provides `Outstanding_Shares.{old_symbol}` change events.

Under Option D:

- `ticker_aliases(old_ticker, new_security_id, effective_from, effective_until)`.
- Gateway: on `/instruments/{ticker}` lookup miss, search `ticker_aliases` with
  `effective_until IS NULL OR effective_until > now()`. On hit, issue 301 to
  `/instruments/{new_ticker}`.
- Browser bookmarks survive; analyst muscle memory survives.

### 6.3 Performance — ticker vs UUID

UUID lookup: `SELECT * FROM canonical_entities WHERE entity_id = $1` — PK hit,
~0.1ms.

Ticker lookup: `SELECT * FROM canonical_entities WHERE upper(ticker) = upper($1)
AND (exchange = $2 OR $2 IS NULL)` — uses `idx_entities_ticker_exchange`. With
the partial-UNIQUE proposed in §4 Option D, also ~0.1ms.

Plus one Valkey cache tier in front (key `gw:v1:ticker:{ticker} → security_id`,
TTL 6h). Cache hit ratio expected >99% in steady state.

**Net change**: ticker lookup *replaces* the current dual-call resolution (S3
lookup + S7 ticker lookup) → **net latency goes down**.

### 6.4 Multi-class shares

- BRK.A and BRK.B are two distinct `financial_instrument` entities, each with
  its own ticker, each with its own row. No special-case logic.
- The KG can hold a `SHARE_CLASS_OF` relation between them (already supported by
  `relation_type_registry`).
- URL: `/instruments/BRK.A` and `/instruments/BRK.B`. Standard URL-encoding of
  the dot (or accept as-is — Next.js routing handles dots in dynamic segments).

### 6.5 International symbology (ISIN / CUSIP / RIC)

- ISIN is already stored on `canonical_entities.isin` and `instruments.isin`.
- Gateway can additionally accept `/v1/instruments/lookup?isin={isin}` (already
  exists per `clients.py:147` "Unified instrument lookup by symbol, ISIN, or
  UUID").
- For URL routing we stick with ticker; ISIN lookups remain a query-param API
  for institutional consumers.

---

## 7. Recommendation

### Pick: **Option D (Hybrid)**.

Justified by:

- ✅ Satisfies user anchor 1 ("standardize entity and instrument id"): single
  `security_id` for tradable securities after Phase 3.
- ✅ Satisfies user anchor 2 ("query instruments by ticker"):
  `/instruments/{ticker}` URLs from Phase 1.
- ✅ Lowest-risk migration of the four. Each wave is independently revertible
  behind the gateway shim.
- ✅ Removes 145 lines of S9 resolution logic and ~30 dual-id frontend type
  fields.
- ✅ Hot-path latency strictly improves (one fewer KG roundtrip in
  `get_company_overview`).
- ✅ M-017 invariant becomes a DB constraint, not a convention.
- ✅ Compatible with future global expansion via `/instruments/{exchange}/{ticker}`.
- ✅ Existing UUID URLs and existing Kafka payloads continue to work forever.

What we are explicitly NOT recommending:

- ✗ Option A alone — doesn't fix ergonomics.
- ✗ Option B alone — perpetuates the dual namespace, doesn't pay off the
  complexity debt.
- ✗ Option C alone — fragile in the global case, doesn't fix M-017.

---

## 8. Phased rollout plan

**Each wave is shippable and revertible independently.**

### Phase 1 — Gateway shim + ticker URLs (1 sprint, ~5 working days)

Unblocks PRD-0089 design refresh.

**W1-1 — `resolve_security_id` helper**
- Add `services/api-gateway/src/api_gateway/lib/id_resolver.py` with the
  ticker-or-UUID resolver.
- Apply at the entrypoint of every `/v1/instruments/{id}/...` and
  `/v1/entities/{id}/...` route in S9.
- Valkey cache `gw:v1:ticker:{ticker}` TTL 6h.
- Tests: contract tests covering (a) UUID passthrough, (b) ticker hit,
  (c) ticker miss → 404, (d) cache hit/miss paths.
- **Acceptance**: `curl /v1/instruments/AAPL/page-bundle` returns the same
  payload shape as `curl /v1/instruments/01900000-...001001/page-bundle`.

**W1-2 — Frontend route flip**
- Rename `app/(app)/instruments/[entityId]/page.tsx` → `[ticker]/page.tsx`.
- Update every `router.push("/instruments/...")` to use ticker
  (~10 components — see grep in §2.2).
- Keep ID-based deep-links working: middleware in `next.config.ts` issues 301
  on `/instruments/{UUID}` → `/instruments/{ticker}` after a KG lookup.
- Tests: update mocks (~30 test files).
- **Acceptance**: clicking AAPL from watchlist lands at `/instruments/AAPL`
  with all tabs populated (no 404s on briefing / graph / news).

**W1-3 — Frontend type cleanup**
- Drop dual `entity_id, instrument_id` fields from response types where the
  gateway now emits only one. Specifically: `Quote`, `OHLCVResponse`,
  `Holding`, `WatchlistMember`. Keep `security_id` (renamed unified field) +
  `ticker`.
- `api.ts` line delta ~ -60 lines.

**Deliverables of Phase 1**:
- 404 cascade fixed for current users.
- URL is `/instruments/AAPL` everywhere.
- Backend service code unchanged. Zero Kafka changes. Zero DB migrations.

### Phase 2 — Unify writes (1 sprint)

**W2-1 — `security_id` column on `instruments`**
- S2 market-ingestion: when ingesting a new instrument, FIRST upsert the
  `canonical_entities` row (entity_type='financial_instrument', ticker,
  exchange) via the existing outbox path; capture the returned `entity_id`;
  then INSERT `instruments(security_id = entity_id)`.
- New `instruments.security_id UUID NULL REFERENCES canonical_entities(entity_id)`
  column. Nullable in this wave; backfill in W2-3.
- Tests: integration test that a fresh ingestion yields
  `instruments.security_id = canonical_entities.entity_id`.

**W2-2 — Partial UNIQUE on `(upper(ticker), exchange)`**
- Migration in `intelligence-migrations`: add the partial UNIQUE index. Pre-step:
  dedup any duplicate ticker+exchange rows (memory entry 2026-05-05 says these
  exist; BP-384/385 cleanup ran but check again).
- Tests: dedup pre-step + UNIQUE creation idempotent.

**W2-3 — Backfill `instruments.security_id`**
- Background job (one-off): for every existing instrument, find
  `canonical_entities.entity_id` by `(upper(ticker), exchange)`. If found, set
  `security_id`. If not, INSERT the canonical row first then set.
- Tests: integration test against seed dataset.

### Phase 3 — Cut over reads (1 sprint)

**W3-1 — S3 `lookup_instrument` returns security_id**
- Add `security_id` to the response shape. `instrument_id` (legacy) field
  retained.

**W3-2 — S9 emits `security_id` everywhere**
- The bundle composer + every other use-case stop populating `entity_id` as
  a separate field; the unified value goes out as `security_id`. Legacy
  `instrument_id` and `entity_id` remain in the response with
  `security_id` value (compat).

**W3-3 — Frontend reads `security_id`**
- `api.ts` types add `security_id` and mark the other two as
  `@deprecated`. Components migrate.

### Phase 4 — Burn legacy (1 sprint, optional)

**W4-1 — Drop `instruments.id` in favour of `instruments.security_id`**
- Migration: `instruments.id` becomes a generated column equal to
  `security_id` (or a straight rename + FK chain rewrite). After this wave the
  table has one UUID column.

**W4-2 — Drop legacy `instrument_id` / `entity_id` from response shapes**
- `api.ts` cleanup; legacy fields removed.

**W4-3 — `ticker_aliases` table + 301 redirect on stale ticker**
- Operational baseline for FB → META style events. Populated by S2 when EODHD
  reports a symbol change.

---

## 9. Impact on PRD-0089 design docs

| Doc | Update needed | Why |
|---|---|---|
| `_INDEX.md` | Add a "Cluster 2 resolved → Option D" line; lock URL convention to `/instruments/{ticker}` | Anchor every per-page agent on the same convention |
| `00-backend-data-inventory.md` | Note that `instrument_id` and `entity_id` will collapse to `security_id`; mark the dual-id rows | Future-proof the inventory |
| `02-dashboard.md:349` | Currently locks `/instruments/{instrument_id}` URL — flip to `/instruments/{ticker}` | Top-mover and watchlist cards must use ticker URLs |
| `03-portfolio-overview.md` | Holdings table row shape: drop `entity_id`, keep `security_id` + `ticker` | One id field is sufficient |
| `04-portfolio-detail.md` | Same as 03 | Same |
| `05-instrument-quote.md` | Page-bundle response shape simplified to `{security_id, ticker, ...}` | Removes one of the dual fields from the canonical bundle response |
| `06-instrument-financials.md` | Same as 05 | Same |
| `07-instrument-intelligence.md` | Path-to-portfolio resolves on `security_id`; the depth-3 timeout root cause (entity-id mismatch) goes away | Big win |
| `08-screener.md:182` | Row carries `security_id`, `ticker`, `name`; remove `entity_id` and `instrument_id` columns | Simplifies row type and prevents BP-330 / BP-373 class bugs |
| `09-workspace-predictions-alerts.md` | Alert subscription keys move to `security_id` (today they use `entity_id`) | Stops "alert tagged with entity_id, watchlist tagged with instrument_id" silent mismatches |
| `10-chat-ai.md` | Chat entity-extraction tools resolve names → `security_id` directly, not via `entity_id`/`instrument_id` branching | Removes one layer of resolve-by-name |

**Does this cluster BLOCK the design refresh?** No — Phase 1 of Option D is
non-blocking. Per-page design docs can lock their layouts assuming `security_id`
+ `ticker` and the gateway shim runs in parallel. The 404-cascade bug stops as
soon as Phase 1 W1-1 ships.

---

## 10. Follow-up OQs for the user

These need user input before final lock-in:

1. **Exchange-prefixed URLs in Phase 4?**
   Recommend `/instruments/{exchange}/{ticker}` as the unambiguous form for
   non-US listings (e.g. `/instruments/LSE/BHP`). Default unprefixed routes
   resolve to US. Acceptable?

2. **Class-share URL convention?**
   BRK.A → `/instruments/BRK.A` (with the dot URL-encoded as `BRK.A` literally)
   or `/instruments/BRK-A`? Bloomberg uses `BRK/A`. Recommend the literal dot.

3. **Ticker case sensitivity?**
   Recommend treating all tickers as upper-case in URLs (`/instruments/AAPL`,
   not `/instruments/aapl`). 301 redirect lower-case → upper-case.

4. **Ticker reassignment policy (FB → META)?**
   Recommend `ticker_aliases` table + 301 redirect indefinitely. Alternative:
   permanent redirect for 24 months, then 404. Recommend indefinite.

5. **`security_id` naming?**
   Three contenders: `security_id` (this doc), `asset_id` (broader; covers
   crypto, FX), `instrument_id` (reuses existing name; risks confusion during
   migration). Recommend `security_id` for clarity vs. the current dual-name
   confusion.

6. **Phase 4 timing?**
   Phase 4 is optional cosmetic cleanup — drop legacy fields, drop legacy
   columns. Can ship anytime in Q3. Or skip indefinitely if compat-field
   bloat is tolerable.

7. **Brokerage-sync read paths?**
   SnapTrade and TastyTrade adapters write `holding.instrument_id`. Confirm we
   migrate these to write the unified `security_id` in Phase 2 W2-3 (rather
   than later)?

8. **Should `canonical_entities.entity_type` retain the `financial_instrument`
   value, or rename to `security`?** Cosmetic; recommend keep as-is to avoid
   touching every existing enum.

---

## Appendix A — File evidence index

Every file:line cited in this doc, gathered for easy verification:

- Domain models:
  - `services/market-data/src/market_data/domain/entities.py:38-56` (`Security`)
  - `services/market-data/src/market_data/domain/entities.py:59-80` (`Instrument`)
  - `services/portfolio/src/portfolio/domain/entities/instrument.py:14-33`
    (`InstrumentRef` with `entity_id: UUID | None`)
  - `services/knowledge-graph/src/knowledge_graph/domain/models.py:275-297`
    (`CanonicalEntity`)
- KG canonical_entities DDL: `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py:121-138`
- KG entity-by-ticker route: `services/knowledge-graph/src/knowledge_graph/api/routes.py:179-195`
- S9 resolution dance: `services/api-gateway/src/api_gateway/clients.py:171-465`
- S9 bundle composer: `services/api-gateway/src/api_gateway/clients.py:470-602`
- S9 InstrumentPageBundleUseCase wrapper: `services/api-gateway/src/api_gateway/application/use_cases/instrument_page_bundle.py:31-87`
- Frontend route: `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx:12-18`
- Frontend `api.ts` dual-id types: `apps/worldview-web/types/api.ts:131-132, 432-434, 746-747, 802-803, 1082-1083, 1114-1116`
- Frontend ticker-vs-id router.push call sites: `apps/worldview-web/components/shell/WatchlistPanel.tsx:215`,
  `components/workspace/WorkspacePortfolioPanel.tsx:118`, `components/workspace/WorkspaceScreenerWidget.tsx:122`,
  `components/instrument/EntityGraphPanel.tsx:421,495`, `components/shell/GlobalSearch.tsx:184`
- ADR-F-12 declaration: `docs/specs/0027-frontend-mvp-ui-design.md:1367-1380`
- M-017 invariant: `docs/audits/2026-03-27-deep-cross-service-qa-report.md:190`,
  `infra/kafka/schemas/market.instrument.discovered.v1.avsc:11-14`
- Demo UUID divergence: `scripts/seed-dev-data.sql:46`, `scripts/seed_demo_data.py:95`
- Bug patterns confirming the issue:
  - BP-330 `docs/BUG_PATTERNS.md:328` — screener entity_id slug never matched
  - BP-342 `docs/bug-patterns/api-contracts.md:912` — KG entity_id ≠ market-data instrument_id 404
  - BP-373 `docs/bug-patterns/frontend.md:1018` — navigation entity_id null
  - BP-374 `docs/bug-patterns/frontend.md:1034` — Phase-2 fundamentals 404
- Kafka topic partition key: `docs/MASTER_PLAN.md:212-222` (all keyed on
  `instrument_id` or `entity_id`; values become unified under Option D, names stay).
- Master plan describing canonical_entities ownership: `docs/MASTER_PLAN.md:281-294`
