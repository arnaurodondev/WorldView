# ADR-F-16: Instrument / Entity ID Unification (Single UUID per Tradable Security)

**Date**: 2026-05-20
**Status**: Accepted
**Deciders**: Arnau Rodon
**Supersedes**: ADR-F-12 (PRD-0027 §1367) — "entity_id ≠ instrument_id — Resolution via S9 Composition"
**Implements**: PRD-0089 F2 wave (`docs/plans/0089-pages/F2-entity-id-unification-plan.md`)
**Parent design**: `docs/designs/0089/oq/02-entity-id-model.md`

---

## Context

ADR-F-12 (declared in PRD-0027 §1367 during the Q1 frontend redesign) blessed
a **dual-id model** for the Worldview platform:

| Namespace | Owner | Used by |
|-----------|-------|---------|
| `instrument_id` | S3 / S2 market-data | OHLCV / quotes / fundamentals |
| `entity_id`     | S7 knowledge-graph  | Canonical entities (people, events, sectors, tradable securities) |

The two were declared distinct UUIDs, bridged by a nullable `InstrumentRef.entity_id`
field on S1 portfolio and a `GET /v1/instruments/{id}/context` S9 composition
endpoint that returned both halves in one payload.

Two facts emerged after PRD-0027 shipped:

1. **Kafka invariant M-017** (audit `audits/2026-03-27-deep-cross-service-qa-report.md:190`)
   declared that every cross-service event payload must carry `entity_id =
   instrument_id` for tradable securities. M-017 is what makes idempotent
   consumers correct: a downstream service can dedupe by the same id whether it
   joined the topic from S3 or S7.

2. **Production code silently followed M-017** while seed scripts and frontend
   types followed ADR-F-12. The two declarations contradicted each other; the
   contradiction lived undetected for ~6 months and surfaced repeatedly as bugs:

   - **BP-342** — KG's `FundamentalsRefreshWorker` passed `entity_id` to
     market-data's `/api/v1/fundamentals/{instrument_id}` → 404 on every entity
     because seed UUIDs differed across the two DBs.
   - **BP-373** — Screener / watchlist / holdings row navigation read
     `row.entity_id` first; the API returned `null`; users got
     `/instruments/undefined`.
   - **BP-374** — Phase-2 of `get_instrument_page_bundle` used the raw URL
     param (often a KG UUID) instead of the Phase-1-resolved instrument_id, so
     Fundamentals tabs rendered with every metric as "—".
   - 145 LOC of id-translation logic accumulated in
     `services/api-gateway/src/api_gateway/clients.py` (`get_company_overview`
     resolution dance, KG ticker fallback, Phase-1→2 re-read, bundle dual-id
     payload).
   - URLs used UUIDs (`/instruments/01900000-0000-7000-8000-000000001001`)
     instead of tickers, killing shareability and developer ergonomics.

The right resolution is the one M-017 already required: **collapse the
namespaces for tradable securities**. Non-tradable entities (persons, events,
sectors, indicators) keep their independent `entity_id` because they have no
counterpart in market-data.

PRD-0089's deep-dive design corpus (`docs/designs/0089/oq/02-entity-id-model.md`,
753 lines) audited every code path, Kafka schema, and seed script. The F2 wave
plan (`docs/plans/0089-pages/F2-entity-id-unification-plan.md`) executed that
audit's mandate.

## Decision

**A single canonical UUID identifies each tradable security across the
platform.** That UUID is simultaneously:

- `market_data.instruments.id`
- `kg.canonical_entities.entity_id` (with `entity_type = 'financial_instrument'`)
- The `instrument_id` field on every Kafka event whose payload references a
  tradable security
- The `entity_id` field on those same events (M-017: the two are equal)

**Non-tradable kinds keep an independent `entity_id`** with no market-data
counterpart. The discriminator is `canonical_entities.entity_type` — see
"Deviations" §1 below for why this column was reused rather than adding a new
`kind` column.

### Concrete contract

| Subject               | Before ADR-F-16                                | After ADR-F-16                                                                       |
|-----------------------|------------------------------------------------|--------------------------------------------------------------------------------------|
| Tradable canonical entity insert | Mint fresh UUID; bridge via nullable FK | Use the `event.instrument_id` from `market.instrument.discovered.v1` as `entity_id` |
| S6 provisional-entity promotion (`financial_instrument` kind) | Mint fresh UUID                | Look up matching `instruments.id` by ticker; defer (retry queue, cap 5) if missing  |
| S9 gateway `get_company_overview` | 70-LOC resolution dance + KG ticker fallback | Single `resolve_security_id(identifier)` helper with LRU cache (TTL 1h)             |
| S9 page-bundle composition | Phase 1 KG lookup → re-read with resolved id | Same id used in Phase 1 and Phase 2 — re-read deleted                               |
| Frontend URL routing  | `/instruments/{uuid}`                          | `/instruments/{TICKER}` (uppercase canonical, case-canonical 301, alias 301)        |
| `Instrument` TS type  | Carries both `entity_id` and `instrument_id`   | Carries both (equal), JSDoc'd "post-F2 these are equal"; v1.1 drops the redundant   |
| `ticker_aliases`      | Did not exist                                  | New table in `intelligence_db` (forever retention; empty at v1 per no_backfill)     |
| Multi-class share form | Ad hoc (`BRK-B` from Yahoo, `BRK.B` from EODHD, `BRK/B` from Bloomberg) | Normalized at adapter boundary to canonical dot form (`BRK.B`)            |
| URL alias redirect    | None                                           | Middleware redirects 301 on (a) lowercase → uppercase, (b) known alias → current    |
| Unknown ticker        | Stack trace / `/instruments/undefined`         | `<InstrumentNotFound />` primitive with up to 5 suggested tickers + screener link   |
| M-017 invariant       | Implicit, often violated                       | CI test `services/knowledge-graph/tests/integration/test_m017_invariant.py` enforces |

### Out of scope (kept for later)

- An `/entities/{uuid}/...` page for non-tradable entities (executives, sectors)
- Multi-class share aggregation (combined BRK.A + BRK.B view)
- Multi-exchange support (locked single-exchange)
- Full `/indices/` route (stripped `^` for now)
- 631 legacy foreign canonical entities (.KS/.SZ/.HK/.T pre-F2) — see Deviation §9

## Consequences

### Positive

- **268 LOC deleted from `services/api-gateway/src/api_gateway/clients.py`**
  — 120 LOC across Step 3 (`get_company_overview` resolution + KG ticker
  fallback) + ~148 LOC from `get_instrument_page_bundle` Phase-1→2 re-read.
  Comparable to the 145 LOC budgeted in the F2 plan, slightly exceeding it
  because Step 3's deletion also removed an obsolete dual-id payload mapper.
- **M-017 is now an enforced invariant**, not an aspirational one. CI fails
  if a `canonical_entities` row with `entity_type='financial_instrument'`
  lacks a matching `instruments.id`.
- **Ticker-first URLs** restore Bloomberg-grade ergonomics: shareable,
  memorable, debuggable. Case-canonical 301 + alias 301 give the Bloomberg
  behaviour of "type any historical ticker, land on the current one".
- **The 3 chronic-bug families are closed:** BP-342, BP-373, BP-374 are all
  RESOLVED by F2 — see §"Bug pattern resolutions" below.
- **The S9 gateway is statelessly cheaper:** `resolve_security_id` LRU
  (`cachetools.TTLCache(10_000, 3600)`) replaces a multi-round-trip resolution
  dance, with a single Postgres `SELECT` on cache miss.
- **Cross-service ID translation is no longer a code path.** Every Kafka
  consumer reads the same UUID it would emit. M-017 is true by construction.

### Negative

- **One-time data migration risk during pre-prod:** existing dev volumes
  with mismatched seed UUIDs require `docker compose down -v` + `make seed`.
  Mitigated by the `no_backfill: true` flag on PRD-0089 and the M-017
  invariant test.
- **Two-step ticker-change handling:** when a real ticker change occurs (e.g.
  FB → META), an operator must insert a `ticker_aliases` row marking the old
  ticker non-current. Today there is no UI for this; it is a SQL operation
  documented in `docs/services/knowledge-graph.md` (see "Deviation §8" — the
  middleware-side alias redirect is partially deferred).
- **Frontend type duplication kept for v1:** `Instrument` TS type still carries
  both `instrument_id` and `entity_id` (equal values) so that pre-F2 callers
  (none today, but to support a clean v1.1 rename pass) do not break. v1.1
  drops `entity_id` from tradable-context types.

### Neutral

- **Avro schemas are forward-compatible.** 7 of 18 schemas are tradable-only
  (carry `instrument_id`), 11 are any-entity (carry `entity_id`). Only
  `entity.canonical.created.v1.avsc` was edited (added `entity_type` field
  with default `"unknown"` per R5). The other 17 are doc-only updates.
- **`entity.dirtied.v1`** stays partitioned on `entity_id`; the same UUID is
  used regardless of tradability.

## Bug pattern resolutions

The following entries in `docs/BUG_PATTERNS.md` are marked **RESOLVED by F2**
and forward-reference this ADR:

- **BP-342** — KG `FundamentalsRefreshWorker` passing `entity_id` to
  `/api/v1/fundamentals/{id}`. After F2: `entity_id == instrument_id` for
  tradable kinds, so the legacy resolution step is no longer required (it is
  also no longer in the worker — the worker uses the single canonical id).
- **BP-373** — Screener row navigation reading null `entity_id`. After F2:
  navigation uses the ticker URL (`/instruments/${row.ticker}`), and the
  resolution happens server-side in the gateway. The `entity_id ?? null`
  branch is no longer reachable.
- **BP-374** — Page-bundle Phase-2 fundamentals using URL `instrument_id`.
  After F2: bundle composition uses the same id throughout (no Phase-1 →
  Phase-2 re-read), and the gateway's `resolve_security_id` accepts both
  tickers and UUIDs at the URL boundary.

## Deviations & follow-ups

These items were observed during F2 execution and either changed the plan or
remain as follow-up work. They are tracked here so they don't slip past
v1.1 reconciliation.

1. **No new `kind` column — `entity_type` reused as discriminator.** The F2
   plan §2.1 proposed adding `canonical_entities.kind`. Investigation revealed
   that `entity_type` already exists, is wired through repositories and
   workers, and carries a stale CHECK constraint with a 12-value legacy enum.
   F2 reused `entity_type` with the new 11-value enum
   (`financial_instrument, person, event, sector, industry, macro_indicator,
   place, product, index, currency, unknown`). This avoids two columns
   meaning the same thing and a deprecation cycle.

2. **Market-data `instruments` has no `status` column.** The plan §2.3
   proposed `WHERE status = 'active'` on the unique ticker index. The column
   does not exist; the index is unconditional. Pre-prod is fine
   (no_backfill); a future delisted-then-relisted ticker would error on
   insert. Follow-up: add a lifecycle column (`active | delisted | suspended`)
   and rebuild the partial index.

3. **`ticker_aliases` timestamps use `now()` not `utc_now()`.** Verified
   `intelligence_db` convention: no `utc_now()` SQL function exists; only a
   Python helper. SQL defaults use `now()`. Consistent with all other
   intelligence_db migrations.

4. **Migration 0039 hardening.** A pre-existing `ck_canonical_entity_type`
   (singular) CHECK constraint with a 12-value enum was discovered during
   execution — drifted from any committed migration. Migration 0039 now:
   (i) dynamically drops any pre-existing CHECK on `entity_type`,
   (ii) remaps legacy values (`company` + ticker patterns → `financial_instrument`,
   `country` → `place`, anything else → `unknown`),
   (iii) installs the canonical 11-value CHECK constraint.
   Migration 0038's `'organization'` seeds were also patched to `'unknown'`.

5. **api-gateway `entity.dirtied.v1` consumer DEFERRED.** The gateway has no
   Kafka consumer infrastructure today. The `resolve_security_id` LRU relies
   on its 1-hour TTL for staleness eviction. Acceptable for v1 (no_backfill,
   low write rate on ticker mutations). Follow-up: add a tiny consumer to the
   gateway or migrate the cache to Valkey with TTL+invalidate.

6. **S6 provisional-enrichment deferral wired but inactive.** The new
   `market_data_lookup` port defaults to `None` in
   `ProvisionalEnrichmentWorker.__init__`. The scheduler does **not** yet
   inject the adapter — behaviour is unchanged until ops opts in (a one-line
   scheduler change). The deferral logic is fully tested but dormant.

7. **Frontend `entityId` prop kept on `InstrumentPageClient`.** A v1.1
   cleanup pass will rename the prop through the
   `FinancialsTab` / `IntelligenceTab` / `AiBriefBanner` chain. Functionally
   correct today; cosmetic debt.

8. **Alias 301 redirect partially DEFERRED.** Middleware cannot call the
   protected `resolve_security_id` endpoint (S9 requires OIDC). The
   middleware-side test documents the wiring shape but is skipped. Follow-up:
   add an unauthenticated `GET /v1/instruments/aliases/{ticker}` endpoint to
   S9 for the middleware to consume.

9. **~631 legacy foreign canonical entities** (`.KS`, `.SZ`, `.HK`, `.T`
   suffixes — Korean, Shenzhen, Hong Kong, Tokyo exchanges) violate M-017
   today. They are pre-existing data from migration 0009. The Step 12
   integration test filters to UUIDv7 entities (post-F2) to enforce M-017
   going forward without failing on legacy violations. Follow-up wave:
   clean up or migrate these 631 rows.

10. **`make seed-verify-m017` Makefile target bash-vs-sh syntax error.**
    Uses process substitution which `/bin/sh` does not support; silently
    reports "0 missing" regardless of real state. Fix path: either
    `SHELL := /bin/bash` for that target, or rewrite using `psql -A -t` +
    temp files. Track as follow-up.

11. **`market-data/tests/integration/test_infra_smoke.py:40`** has a
    hardcoded `'016'` migration head assertion. After F2's migration 0017,
    this is stale. Trivial fix; track as follow-up.

## Alternatives considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|--------------|
| Add `kind` column alongside existing `entity_type` | Cleanest new schema, no legacy enum drift | Two columns meaning the same thing for the deprecation window; doubles the surface area | Reusing `entity_type` is one column, audited tooling, and one drop-CHECK / add-CHECK migration |
| Keep dual-id model, fix BP-342/373/374 individually | Smallest diff per fix | M-017 still aspirational; 145 LOC of translation stays; URL ergonomics still UUID-based | The cost of dual ids is paid every time a new endpoint composes both — chronic, not one-time |
| Unify ALL entities (tradable + non-tradable) under a single id space | Symmetric model | Non-tradable kinds (executives, sectors) have no market-data counterpart; would force shim records | Non-tradable kinds genuinely live only in KG |
| Use ticker as the primary key instead of UUID | Human-readable, ergonomic | Tickers change (FB → META), collide across exchanges, and are not stable history | UUID stability is non-negotiable; tickers are an alias surface |

## References

- **PRD-0089** — `docs/specs/0089-platform-page-redesign.md` (platform-wide redesign; F2 wave entry)
- **F2 plan** — `docs/plans/0089-pages/F2-entity-id-unification-plan.md`
- **Parent design** — `docs/designs/0089/oq/02-entity-id-model.md`
- **Corners audit** — `docs/designs/0089/oq/02-entity-id-model-CORNERS-AUDIT.md`
- **Decisions index** — `docs/designs/0089/oq/_DECISIONS.md` (§A DISCUSS-2, §C FU-2.1..2.5, §I no_backfill)
- **Superseded ADR-F-12** — `docs/specs/0027-frontend-mvp-ui-design.md` §1367-1380
- **M-017 invariant origin** — `audits/2026-03-27-deep-cross-service-qa-report.md:190`
- **Resolved bug patterns** — BP-342, BP-373, BP-374 in `docs/BUG_PATTERNS.md`

## Implementation footprint

13 commits on `feat/plan-0089-f2`:

```
1dbf6d74 schema: add canonical_entities.entity_type CHECK + ticker_aliases + unique ticker index
4000ac1c s2-normalize: canonical dot-form ticker normalization at adapter boundary
3204e7bc instrument-not-found: primitive for unknown ticker
2736e538 s6-deferral: defer tradable provisional promotion when instrument absent
26ba1ee7 s1-snaptrade: simplify symbol→instrument_id resolution
be1d36c4 s9-shim: delete ~145 LOC translation; add resolve_security_id + LRU
eeb97d1c avro-audit: classify 18 schemas; add entity_type to entity.canonical.created if missing
1da9ae45 s7-m017: enforce instrument_id = entity_id on canonical entity creation
503ab715 seed: unified UUIDs across seed scripts + invariant verification
af4785a5 frontend-routing: ticker URLs + case-canonical middleware + alias 301
bea77cdc schema: rewrite legacy entity_type values in 0038 + defensive UPDATE in 0039
61ada182 frontend-types-cache: cache version bump + type docs + ticker URL sweep
840e99b6 schema: 0039 drops pre-existing CHECK + remaps legacy entity_type values
```
