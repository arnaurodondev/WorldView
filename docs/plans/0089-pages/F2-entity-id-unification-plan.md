---
id: PRD-0089-F2
title: Entity / Instrument ID Unification
prd: PRD-0089
order: F2 (foundation — runs after F1, before any per-page wave)
status: ready-to-execute
created: 2026-05-20
platform_state: pre-production (no_backfill: true)
parent_design: docs/designs/0089/oq/02-entity-id-model.md
corners_audit: docs/designs/0089/oq/02-entity-id-model-CORNERS-AUDIT.md
supersedes: ADR-F-12 (PRD-0027 §1367) — write replacement ADR per §8.1
locked_by: _DECISIONS.md §A DISCUSS-2 + §C FU-2.1..2.5 + §I no_backfill
---

# F2 — Entity / Instrument ID Unification (PRD-0089)

> **One sentence.** Collapse the parallel `entity_id` / `instrument_id`
> UUID namespaces into a single canonical `instrument_id` per tradable
> security, flip URL routing from UUIDs to tickers, and delete the
> 145 LOC of cross-service id-translation logic that the dual model
> required — all while non-tradable KG entities (people, events,
> sectors) keep their own `entity_id` unchanged.

## 1. Bloomberg-grade URL ergonomics checklist (acceptance signals)

Every URL + lookup behaviour F2 ships must satisfy:

| Test | How to verify |
|------|---------------|
| **Ticker-first URLs** | Every navigation to an instrument resolves to `/instruments/{TICKER}` (uppercase canonical). No production UUID URL survives in any component, link, or test |
| **Case-canonical** | `/instruments/aapl` → 301 → `/instruments/AAPL` (Next.js middleware). Server lookups are case-insensitive (`upper(ticker)` index) |
| **Multi-class dot form** | `/instruments/BRK.B`, `/instruments/BF.B`, `/instruments/RDS.A` all resolve. Playwright spec proves it |
| **Alias 301 redirect** | `/instruments/FB` (legacy ticker) → 301 → `/instruments/META`. `ticker_aliases` table looked up by middleware |
| **Unknown-ticker UX** | `/instruments/ZZZZZZ` renders `InstrumentNotFound.tsx` with search suggestions — never a stack trace |
| **UUID fallback still works** | `/v1/instruments/{any-UUID}` endpoint still resolves (gateway shim) — internal callers don't break |
| **M-017 invariant enforced in CI** | Integration test asserts every `canonical_entities` row with `kind='financial_instrument'` has a matching `market_data.instruments` row with `id = canonical_entities.entity_id` |
| **Translation logic deleted** | `git diff` shows 145 LOC removed from `services/api-gateway/src/api_gateway/clients.py` |
| **No dual-id types on tradable contexts** | `api.ts` types for `Instrument` carry `instrument_id` only (or both equal — v1 keeps both for backwards-compat per FU-C-03; v1.1 cleanup drops `entity_id`) |
| **Frontend cache doesn't carry stale IDs** | `qk.VERSION` constant bumped to `"v2"`; old cached entries never collide |

## 2. Schema specification — per database

### 2.1 `canonical_entities.kind` discriminator (kg_db) — C-01

Verify whether the column exists today (grep the model file). If absent:

```sql
-- migration: kg_db / 00NN_add_canonical_entity_kind.py
ALTER TABLE canonical_entities
  ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'unknown';

ALTER TABLE canonical_entities
  ADD CONSTRAINT ck_canonical_entities_kind
  CHECK (kind IN (
    'financial_instrument',  -- tradable; entity_id = market_data.instruments.id
    'person',                -- e.g. executives
    'event',                 -- e.g. FOMC meetings, earnings calls
    'sector',                -- GICS sector
    'industry',              -- GICS sub-industry
    'macro_indicator',       -- CPI, GDP, unemployment
    'place',                 -- country / region
    'product',               -- e.g. iPhone
    'index',                 -- e.g. ^GSPC, ^TNX
    'currency',              -- USD, EUR
    'unknown'
  ));

CREATE INDEX idx_canonical_entities_kind ON canonical_entities (kind);
```

If the column exists today: F2 still validates the enum + adds any
missing values. Document the audited grep result in the wave commit.

### 2.2 `ticker_aliases` table (kg_db) — FU-2.4 + C-17

Location decision: **kg_db** (single source of truth for entity
identity; aliases are an entity concern, not market-data ingestion).

```sql
-- migration: kg_db / 00NN_create_ticker_aliases.py
CREATE TABLE ticker_aliases (
    id          UUID PRIMARY KEY DEFAULT new_uuid7(),
    entity_id   UUID NOT NULL REFERENCES canonical_entities(entity_id),
    alias       VARCHAR(32) NOT NULL,                -- e.g. 'FB'
    is_current  BOOLEAN NOT NULL DEFAULT FALSE,      -- TRUE for the live ticker
    valid_from  TIMESTAMPTZ NOT NULL DEFAULT utc_now(),
    valid_to    TIMESTAMPTZ,                         -- NULL = still valid (current ticker)
    source      VARCHAR(64),                         -- 'eodhd' | 'manual' | 'sec_form_8k'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT utc_now()
);

CREATE UNIQUE INDEX idx_ticker_aliases_alias_current
  ON ticker_aliases (upper(alias))
  WHERE is_current = TRUE;

CREATE INDEX idx_ticker_aliases_entity ON ticker_aliases (entity_id);
```

Table starts EMPTY per no_backfill (FU-2.4: forever retention but no
historical aliases to seed). The gateway alias-lookup path is
implemented but returns 0 rows until a future ticker change is
recorded.

### 2.3 Partial UNIQUE index on (upper(ticker), exchange) — D-2.6

Add to `market_data_db.instruments` (and the matching column on
`canonical_entities` if not already there):

```sql
-- migration: market_data_db / 00NN_unique_ticker_exchange.py
CREATE UNIQUE INDEX idx_instruments_ticker_exchange_active
  ON instruments (upper(symbol), exchange)
  WHERE status = 'active';
```

Allows BRK.A and BRK.B to coexist (different rows, different symbols).
Allows historical/delisted rows to have the same symbol.

### 2.4 Per-DB Alembic migration count

| DB | Migrations added | Notes |
|----|-----------------:|-------|
| `kg_db` | 2 (canonical_entities.kind, ticker_aliases) | Schema only — no_backfill |
| `market_data_db` | 1 (unique ticker_exchange) | Schema only |
| `intelligence_db` | 0 | No schema change — entity_id semantics unchanged |
| `portfolio_db` | 0 | InstrumentRef.entity_id stays nullable bridge field |
| `content_db` | 0 | Article.entity_id unchanged |
| `alert_db` | 0 | Alert.entity_id unchanged |
| `nlp_db` | 0 | document_source_metadata.entity_id unchanged |

All migrations use `op.create_index(..., postgresql_concurrently=False)`
— `make seed` runs against an empty schema in dev; no concurrent index
needed.

## 3. Avro schema audit (18 schemas) — C-02

Each Kafka schema classified per the (a/b/c) taxonomy from the audit.
The `Avro fields` column shows the relevant id fields TODAY; the
`F2 action` column says what changes. Forward-compatible per R5 — no
field removed without server_default and a deprecation cycle.

| # | Schema file | Class | Avro fields today | F2 action |
|---|-------------|-------|-------------------|-----------|
| 1 | `market.instrument.created.avsc` | (a) tradable-only | `instrument_id` | none — already canonical |
| 2 | `market.instrument.discovered.v1.avsc` | (a) tradable-only | `instrument_id`, `entity_id` | confirm `entity_id == instrument_id` post-F2; add doc note. Field stays for v1 forward-compat; deprecate in v1.1 |
| 3 | `market.instrument.updated.avsc` | (a) tradable-only | `instrument_id` | none |
| 4 | `portfolio.events.v1.avsc` | (a) tradable-only | `instrument_id` | none — Holding refs instruments only |
| 5 | `portfolio.watchlist.updated.v1.avsc` | (a) tradable-only | `instrument_id` | none |
| 6 | `watchlist.item_added.avsc` | (a) tradable-only | `instrument_id` | none |
| 7 | `watchlist.item_deleted.avsc` | (a) tradable-only | `instrument_id` | none |
| 8 | `entity.canonical.created.v1.avsc` | (b) any-entity | `entity_id`, `kind` (verify) | if `kind` missing: add field with default `"unknown"` + populate from upstream worker |
| 9 | `entity.dirtied.v1.avsc` | (b) any-entity | `entity_id` | partition key stays `entity_id`; no change |
| 10 | `entity.narrative.generated.v1.avsc` | (b) any-entity | `entity_id` | none |
| 11 | `nlp.article.enriched.v1.avsc` | (b) any-entity | `entity_mentions[].entity_id` | none — mentions can be of any entity kind |
| 12 | `nlp.signal.detected.v1.avsc` | (b) any-entity | `entity_id`, `subject_entity_id` | none |
| 13 | `intelligence.temporal_event.v1.avsc` | (b) any-entity (events are non-tradable) | `entity_id`, `affected_entities[]` | none |
| 14 | `intelligence.contradiction.v1.avsc` | (b) any-entity | `entity_id_a`, `entity_id_b` | none |
| 15 | `relation.type.proposed.v1.avsc` | (b) any-entity | `subject_entity_id`, `object_entity_id` | none |
| 16 | `graph.state.changed.v1.avsc` | (b) any-entity | `entity_id` | none |
| 17 | `alert.created.v1.avsc` | (b) any-entity | `entity_id` | none — alerts can target persons, sectors, instruments |
| 18 | `alert.delivered.v1.avsc` | (b) any-entity | `entity_id` | none |

**Result**: 7 schemas are (a), 11 are (b), 0 are (c) "drops both
needed". The only physical schema change is potentially adding `kind`
to `entity.canonical.created.v1.avsc` (schema 8) — verify whether it
already has it. Everything else is no-op at the wire format level
because `entity_id` and `instrument_id` are still both UUIDs that
HAPPEN to equal the same value for tradable-classified entities.

**Verification step**: F2 plan §9.5 includes a contract test that
spins up Kafka, publishes one of each schema with sample data, and
asserts the consumer accepts the message.

## 4. Service-by-service code changes

### 4.1 S9 (api-gateway) — delete translation logic + add ticker shim

File: `services/api-gateway/src/api_gateway/clients.py`

**Delete** (per C-24, exact line ranges per cluster 02 §2.3):
- Lines `230-299` — `get_company_overview` 70-LOC resolution dance
- Lines `314-342` — KG ticker lookup fallback
- Lines `548-580` — `get_instrument_page_bundle` Phase 1 → 2 re-read
- Lines `370-382` — `bundle.overview.instrument` dual-id payload (now uses single canonical)

**Add**:
- New helper `resolve_security_id(identifier: str) -> UUID`:
  - If `identifier` matches UUIDv7 regex → return as-is
  - Else: treat as ticker → look up `(upper(ticker), 'US') → UUID` from `instruments` table
  - Fallback: look up `ticker_aliases` → 301-redirect signal to caller
  - In-process LRU: `cachetools.TTLCache(maxsize=10000, ttl=3600)` — C-26
- `entity.dirtied.v1` consumer in gateway invalidates the relevant LRU entry — C-27
- Every endpoint with path `/v1/instruments/{instrument_id}` accepts BOTH a UUID and a ticker

**Test coverage**: existing `services/api-gateway/tests/test_clients.py` must
remain green; add new unit tests for `resolve_security_id` (uuid, ticker,
alias, unknown).

### 4.2 S7 (knowledge-graph) — enforce M-017 on instrument-discovered — C-19

File: `services/knowledge-graph/src/knowledge_graph/consumers/instrument_discovered_consumer.py`

Current behaviour: receives `market.instrument.discovered.v1` event, creates
a `canonical_entities` row with a freshly-minted UUID.

**Change**: use `event.instrument_id` AS the new `canonical_entities.entity_id`.
SQL becomes:

```sql
INSERT INTO canonical_entities (entity_id, kind, ticker, exchange, name, created_at)
VALUES ($1, 'financial_instrument', $2, $3, $4, utc_now())
ON CONFLICT (entity_id) DO UPDATE SET
  ticker = EXCLUDED.ticker,
  exchange = EXCLUDED.exchange,
  name = EXCLUDED.name,
  updated_at = utc_now();
```

ON CONFLICT clause handles replay (C-22 idempotency).

**Test**: new unit test asserts `entity_id == event.instrument_id` after
the consumer processes a message.

### 4.3 S6 (nlp-pipeline) — defer tradable promotion when instrument absent — C-18, C-20

File: `services/nlp-pipeline/src/nlp_pipeline/workers/provisional_enrichment_worker.py`

Current behaviour: promotes a provisional entity (e.g. mention of "AAPL"
detected by NER) to canonical, minting a fresh UUID.

**Change**: when the provisional entity has `kind = 'financial_instrument'` AND
a known ticker:
1. Look up `market_data.instruments` (via S2 internal API, NOT direct DB
   per R7) for an instrument with that ticker.
2. If found: use its `id` as the new `entity_id`. Insert canonical row.
3. If NOT found: defer promotion (push back to provisional queue with
   `retry_after = now + 60s`). Add a retry-count cap (5 attempts → DLQ).

**Test**: new tests for both branches (instrument exists / instrument missing).

### 4.4 S1 (portfolio) — simplify brokerage adapter — C-21

File: `services/portfolio/src/portfolio/infrastructure/snaptrade_adapter.py`

Today the adapter resolves SnapTrade symbol → `entity_id` via a bridge
field. After F2, the resolution is simpler:

```python
async def resolve_symbol_to_instrument_id(symbol: str) -> UUID:
    """SnapTrade returns symbol; we look up instrument_id by ticker."""
    instrument = await self._s2_client.lookup_instrument(ticker=symbol)
    if not instrument:
        raise BrokerageSyncSymbolNotFoundError(symbol=symbol)
    return instrument.instrument_id
```

Remove the `InstrumentRef.entity_id` bridge-field branch logic.

### 4.5 S2 (market-data) — ticker normalization at adapter boundary — C-11

File: `services/market-data/src/market_data/adapters/eodhd.py` (and similar
for any other source)

Current EODHD returns symbols like `BRK.B`. Yahoo returns `BRK-B`. Bloomberg
returns `BRK/B`. F2 normalizes ALL incoming symbols to the dot form on
ingest:

```python
def _normalize_ticker(raw: str) -> str:
    """Canonical ticker form: uppercase, multi-class via dot.
    Examples: 'brk.b' -> 'BRK.B'; 'BRK-B' -> 'BRK.B'; 'BRK/B' -> 'BRK.B'.
    """
    return raw.strip().upper().replace("-", ".").replace("/", ".")
```

Applied at adapter ingest before any DB write.

## 5. Seed-data rewrite — C-14, C-15

Three files to rewrite (verify exhaustive via `grep -rln "01900000-0000-7000" scripts/`):

| File | Lines to change | Action |
|------|----------------:|--------|
| `scripts/seed-dev-data.sql` | ~46-50 (the AAPL/MSFT/GOOGL/TSLA/AMZN block) | Set `instruments.id` = the same UUID as `canonical_entities.entity_id` (drop the `11111111-...` UUIDs; use `01900000-...` for both) |
| `scripts/seed_demo_data.py` | ~95 (the KG entity insertion) | Use `01900000-...` UUIDs for tradable canonical entities |
| `scripts/seed-eval-corpus.py` | BRK references | Ensure BRK.A and BRK.B each get their own canonical entity with matching instrument |

**Seed order** (C-14):
1. `kg_db.canonical_entities` for tradable kinds — must be inserted first (or concurrently); they ARE the system-of-record per M-017
2. `market_data_db.instruments` — uses same UUIDs
3. `portfolio_db.holdings` — refs `instruments.id`
4. `nlp_db.document_source_metadata` — refs entity_id
5. `alert_db.alerts` — refs entity_id

Easiest: unify all SQL into a single `scripts/seed-all.sql` ordered as
above, OR keep separate files but document the order in `make seed` target.

**Verification step** added to `make seed`:
```bash
psql -d kg_db -c "
  SELECT count(*) FROM canonical_entities ce
  WHERE ce.kind = 'financial_instrument'
  AND NOT EXISTS (
    SELECT 1 FROM dblink('host=market_data_db dbname=market_data_db',
                          'SELECT id FROM instruments') AS t(id UUID)
    WHERE t.id = ce.entity_id
  );
"
# Expected: 0 (every tradable canonical entity has a matching instrument)
```

(Note: `dblink` is fine in seed scripts; per R7 it's banned at runtime.)

## 6. Frontend changes

### 6.1 URL routing flip — slug rename + middleware

| Change | Where | Notes |
|--------|-------|-------|
| Rename slug `[entityId]` → `[ticker]` | `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` → `[ticker]/page.tsx` | Cascade rename across `InstrumentPageClient.tsx` props + every callsite |
| Add Next.js middleware | `apps/worldview-web/middleware.ts` | (a) Lowercase ticker → 301 redirect to uppercase. (b) Resolve ticker → check `ticker_aliases` → 301 to canonical ticker on alias match |
| Special-character routing test | `apps/worldview-web/tests/e2e/instrument-url-special-chars.spec.ts` | Navigates to `/instruments/BRK.B`, `/instruments/BF.B`, `/instruments/RDS.A` and asserts page renders |
| Index ticker URL handling | `apps/worldview-web/middleware.ts` | Strip `^` for routing — `^TNX` → `/instruments/TNX` with kind=index. Or: route indices to `/indices/{ticker}` (recommended; cleaner separation) |

### 6.2 New primitive — `InstrumentNotFound.tsx` — C-35

Location: `apps/worldview-web/components/primitives/InstrumentNotFound.tsx`
(matches F1 primitive structure).

Props:
- `attemptedTicker: string`
- `suggestedTickers?: string[]` (from S9 fuzzy-match lookup)

Renders: terminal-style "INSTRUMENT NOT FOUND" header + the attempted
ticker + a list of up to 5 suggested tickers + link to `/screener`.

InstrumentPageClient.tsx: if `useInstrumentBundle` returns 404, render
`<InstrumentNotFound attemptedTicker={ticker} />` instead of throwing.

### 6.3 TanStack cache version bump — C-05

File: `apps/worldview-web/lib/query/keys.ts`

Add a `VERSION` constant prepended to every cache key:

```ts
export const QK_VERSION = "v2";  // post-F2 — UUID semantics changed

export const qk = {
  instruments: {
    detail: (id: string) => [QK_VERSION, "instruments", "detail", id] as const,
    ...
  },
};
```

Bumping `VERSION` invalidates the entire post-F2 cache namespace from
pre-F2 entries. With no_backfill, the dev environment uses
`docker compose down -v` so this is belt-and-suspenders, but the
constant makes future bumps trivial.

### 6.4 api.ts type cleanup — C-03

| Type | Today | F2 (v1) | v1.1 cleanup |
|------|-------|---------|---------------|
| `Instrument` | both `instrument_id` + `entity_id` | both, equal values | drop `entity_id` |
| `RankedArticle.entity_mentions[].entity_id` | unchanged | unchanged | unchanged (mentions can be non-tradable) |
| `Holding.instrument_id` | unchanged | unchanged | unchanged |
| `WatchlistMember.entity_id` | bridge field, often null | always = instrument_id | rename to `instrument_id` |
| `GraphNode.entity_id` | unchanged | unchanged | unchanged (graph contains any kind) |
| `GraphEdge.{source,target}_entity_id` | unchanged | unchanged | unchanged |

v1: keep both fields on tradable-context types, document "post-F2 these
are equal" in JSDoc. v1.1: drop the redundant ones.

### 6.5 Hook prop naming consistency — C-07

`grep -rn "entityId\b" apps/worldview-web/components/instrument/hooks/`
— audit every hook prop. After F2, props on tradable contexts should be
named `instrumentId`, on cross-kind contexts named `entityId`.

Examples post-F2:
- `useInstrumentBundle(instrumentId)` ✓ already
- `useMetricsTableData(instrumentId)` ✓
- `useChartTechnicals(instrumentId)` ✓
- `useFinancialsTabData(instrumentId)` ✓
- `useEntityNewsInfinite(instrumentId)` ← rename from `entityId`
- `useEntityIntelligence(entityId)` — STAYS (intelligence covers persons/events too)

### 6.6 Search-result URL construction

Every search-result component must construct ticker URLs:

```tsx
// Before (post-F2 banned):
<Link href={`/instruments/${result.entity_id}`}>...</Link>
// After:
<Link href={`/instruments/${result.ticker}`}>...</Link>
```

Affects: `apps/worldview-web/components/search/*`, screener row links,
watchlist member links, holdings row links, news article entity-tag
links. Grep+sed sweep.

## 7. ADR + documentation updates

### 7.1 New ADR superseding ADR-F-12 — C-31

New file: `docs/architecture/decisions/F-XX-instrument-entity-id-unification.md`

(Number assigned at write time — current highest is F-15 per
`grep -E "^F-[0-9]+" docs/architecture/decisions/*.md`.)

Body sections:
1. Context — why ADR-F-12 was wrong
2. Decision — single `instrument_id` per tradable security; non-tradable entities keep `entity_id`
3. Consequences — 145 LOC deleted, M-017 finally true, ticker URLs enabled
4. Reference: PRD-0089, F2 wave, this plan

### 7.2 Reconcile service docs — C-32

Grep `docs/services/*.md` and `services/*/.claude-context.md` for:
- "entity_id and instrument_id are distinct"
- "M-017"
- "ADR-F-12"
- "dual id" / "two namespaces"

Update each occurrence to reflect the unified model.

### 7.3 Resolve bug patterns — C-33

Amend `docs/BUG_PATTERNS.md`:
- **BP-342** (KG 404 cascade) — mark RESOLVED by F2; reference this plan
- **BP-373** (navigation with null entity_id) — RESOLVED
- **BP-374** (Phase-2 fundamentals UUID mismatch) — RESOLVED

### 7.4 MASTER_PLAN.md + RULES.md — C-34

- MASTER_PLAN.md: update "Architecture Conventions" section that mentions the dual-id model
- RULES.md: if any rule references entity_id semantics, reconcile

## 8. Tests

### 8.1 Architecture invariant test — C-30

New file: `services/knowledge-graph/tests/integration/test_m017_invariant.py`

```python
import pytest

@pytest.mark.integration
async def test_every_tradable_canonical_entity_has_matching_instrument(
    kg_db_session, market_data_db_session
):
    """M-017 invariant: ce.entity_id == instrument.id for tradable kinds."""
    tradable_entities = await kg_db_session.execute(
        "SELECT entity_id FROM canonical_entities WHERE kind = 'financial_instrument'"
    )
    instrument_ids = await market_data_db_session.execute(
        "SELECT id FROM instruments"
    )
    tradable_ids = {r.entity_id for r in tradable_entities}
    instrument_ids_set = {r.id for r in instrument_ids}
    missing = tradable_ids - instrument_ids_set
    assert not missing, f"M-017 violated: {len(missing)} tradable entities have no instrument"
```

Runs in CI against the seeded dev DB.

### 8.2 Playwright special-character URL tests — C-10

`apps/worldview-web/tests/e2e/instrument-url-special-chars.spec.ts`:

```ts
test.describe("special-character tickers", () => {
  for (const ticker of ["BRK.A", "BRK.B", "BF.B", "RDS.A"]) {
    test(`/instruments/${ticker} renders`, async ({ page }) => {
      await page.goto(`/instruments/${ticker}`);
      await expect(page.locator('[data-testid="instrument-header"]')).toContainText(ticker);
    });
  }
});
```

### 8.3 E2E migration from UUID URLs to ticker URLs — C-29

Grep all `apps/worldview-web/tests/e2e/*.spec.ts` for
`/instruments/01900000` and `/instruments/11111111` — replace with the
canonical ticker. Most likely `/instruments/AAPL`.

### 8.4 Test fixture rewrite — C-28

Grep `services/**/tests/` and `apps/worldview-web/__tests__/` for the
two seed-data UUIDs (`01900000-0000-7000-8000-000000001001` AAPL and
`11111111-0001-7000-8000-000000000001` AAPL). Replace every occurrence
of the `11111111-...` with the corresponding `01900000-...` (the
unified value). Add a test that asserts they are EQUAL (catches future
regression).

### 8.5 Kafka contract tests — C-02 §4 above

`services/knowledge-graph/tests/contract/test_kafka_schemas_f2.py` —
spins up the test Kafka, publishes one of each of the 18 schemas with
sample data, asserts every consumer accepts. Catches any schema-shape
regression introduced by F2.

### 8.6 Unit tests for new code

- `services/api-gateway/tests/test_resolve_security_id.py` — uuid / ticker / alias / unknown
- `services/knowledge-graph/tests/test_instrument_discovered_consumer_m017.py`
- `services/nlp-pipeline/tests/test_provisional_enrichment_deferral.py`
- `apps/worldview-web/tests/unit/middleware.test.ts` — case-canonicalization + alias redirect
- `apps/worldview-web/tests/unit/InstrumentNotFound.test.tsx`

## 9. Acceptance criteria

| # | Gate | Verification |
|---|------|--------------|
| 1 | `pnpm --filter worldview-web typecheck` | 0 errors |
| 2 | `pnpm --filter worldview-web test --run` | All tests green |
| 3 | All service pytests | All green (`make test` or equivalent) |
| 4 | New integration test for M-017 invariant | PASSES |
| 5 | Playwright special-character URL spec | PASSES |
| 6 | `grep -E "/instruments/[0-9a-f]{8}-" apps/worldview-web/` | 0 results (no UUID URLs) |
| 7 | `grep -E "01900000\|11111111" services/**/tests/` | All occurrences are the same value (unified) |
| 8 | `git diff services/api-gateway/src/api_gateway/clients.py` | Shows ≥145 LOC removed |
| 9 | `make seed && (M-017 invariant query)` | Returns 0 violations |
| 10 | New ADR-F-XX file exists | `ls docs/architecture/decisions/F-*instrument-entity-id*` |
| 11 | BUG_PATTERNS.md BP-342/373/374 amended | grep for "RESOLVED by F2" |
| 12 | `apps/worldview-web/middleware.ts` exists | Both case-canonicalization and alias redirect are unit-tested |
| 13 | TanStack cache `QK_VERSION = "v2"` | grep `apps/worldview-web/lib/query/keys.ts` |
| 14 | Visual smoke | `/instruments/AAPL`, `/instruments/aapl` (→301), `/instruments/BRK.B`, `/instruments/UNKNOWN` (→ NotFound) all render correctly |

## 10. Risk register

| Risk | Mitigation |
|------|------------|
| Existing dev volumes have stale data after migration → mismatched IDs | F2 plan documents `docker compose down -v` as the prerequisite for `make seed`; CI test asserts the invariant |
| `canonical_entities.kind` column already exists with different values → enum constraint fails | Step 1 of F2: grep the column; if exists, audit values before adding CHECK constraint |
| Ticker normalization regex breaks a legit ticker (e.g. `T.A` is a valid ticker with hyphen treated correctly) | Add specific positive-case tests in `_normalize_ticker` unit test for every known multi-class share form |
| Provisional-enrichment deferral creates infinite-retry loop | Retry-count cap of 5 + DLQ on `provisional_entity_dlq` topic |
| Middleware 301 redirect for case → infinite loop if middleware also lowercases | Middleware ONLY redirects when input is lowercase; uppercase URLs render directly. Unit test covers both branches |
| 18 Avro schema audit misses a (c) "carries both" — wire format breakage | Mitigation: §8.5 contract tests publish one of each schema with sample data; any consumer reject fails CI |
| Frontend `entityId` prop rename breaks 3rd-party components (none today) | None — Worldview frontend has no external consumers |
| Removing 145 LOC from S9 breaks an undocumented caller | All gateway tests must still pass; existing E2E specs must still pass |

## 11. Files touched (consolidated)

```
EDIT:
  services/api-gateway/src/api_gateway/clients.py             (-145 LOC)
  services/api-gateway/src/api_gateway/dependencies.py         (resolve_security_id wire-up)
  services/knowledge-graph/src/knowledge_graph/consumers/instrument_discovered_consumer.py
  services/nlp-pipeline/src/nlp_pipeline/workers/provisional_enrichment_worker.py
  services/portfolio/src/portfolio/infrastructure/snaptrade_adapter.py
  services/market-data/src/market_data/adapters/eodhd.py       (+_normalize_ticker)
  services/market-data/src/market_data/adapters/yahoo.py        (if exists)
  apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx → renamed to [ticker]/page.tsx
  apps/worldview-web/components/instrument/InstrumentPageClient.tsx  (ticker prop)
  apps/worldview-web/lib/query/keys.ts                          (QK_VERSION constant)
  apps/worldview-web/types/api.ts                               (JSDoc on dual-id fields)
  apps/worldview-web/hooks/useEntityNewsInfinite.ts             (rename prop)
  scripts/seed-dev-data.sql                                     (unified UUIDs)
  scripts/seed_demo_data.py
  scripts/seed-eval-corpus.py
  Makefile                                                       (`make seed` ordering)
  docs/BUG_PATTERNS.md                                          (BP-342/373/374 amended)
  docs/MASTER_PLAN.md                                            (dual-id section reconciled)
  18 × infra/kafka/schemas/*.avsc                               (per §3 audit; mostly doc-only)
  many × docs/services/*.md, services/*/.claude-context.md

CREATE:
  intelligence-migrations/alembic/versions/00NN_add_canonical_entity_kind.py  (kg_db)
  intelligence-migrations/alembic/versions/00NN_create_ticker_aliases.py       (kg_db)
  services/market-data/alembic/versions/00NN_unique_ticker_exchange.py
  apps/worldview-web/middleware.ts                              (case + alias redirect)
  apps/worldview-web/components/primitives/InstrumentNotFound.tsx
  apps/worldview-web/tests/e2e/instrument-url-special-chars.spec.ts
  apps/worldview-web/tests/unit/middleware.test.ts
  apps/worldview-web/tests/unit/InstrumentNotFound.test.tsx
  services/api-gateway/tests/test_resolve_security_id.py
  services/knowledge-graph/tests/test_instrument_discovered_consumer_m017.py
  services/knowledge-graph/tests/integration/test_m017_invariant.py
  services/knowledge-graph/tests/contract/test_kafka_schemas_f2.py
  services/nlp-pipeline/tests/test_provisional_enrichment_deferral.py
  docs/architecture/decisions/F-XX-instrument-entity-id-unification.md
  docs/plans/0089-pages/F2-entity-id-unification-plan.md       (this file)

MOVE / RENAME:
  apps/worldview-web/app/(app)/instruments/[entityId]/        → apps/worldview-web/app/(app)/instruments/[ticker]/

GREP+SED SWEEPS:
  All `<Link href="/instruments/${...entity_id}">` → ticker form (~30 sites)
  All Playwright `/instruments/{uuid}` → `/instruments/AAPL` (~12 specs)
  All test fixtures with hardcoded `11111111-...` UUIDs (~80 sites) → matching `01900000-...`
```

## 12. Estimation

| Phase | Effort |
|-------|-------:|
| Schema migrations (3 Alembic) + canonical_entities.kind audit | 0.5d |
| 18 Avro schema audit + contract test | 1d |
| S9 gateway delete-145-LOC + resolve_security_id + LRU + middleware-side cache | 1d |
| S7 instrument-discovered consumer M-017 enforcement | 0.5d |
| S6 provisional-enrichment deferral logic | 0.5d |
| S1 snaptrade_adapter simplification | 0.5d |
| S2 ticker normalization adapter | 0.5d |
| Seed-data rewrite + ordering + verification query | 0.5d |
| Frontend slug rename + middleware + InstrumentNotFound | 1d |
| Frontend types + hook prop sweep | 0.5d |
| Frontend URL construction grep-sweep | 0.5d |
| Tests (architecture, Playwright, fixtures, units) | 1.5d |
| ADR + docs + bug patterns | 0.5d |
| **Single agent serial** | **~8-10 days** |

## 13. Rollback plan

F2 is large but every sub-change has a discrete commit. Rollback paths:

- **Schema migrations**: each Alembic version has `downgrade()`. Reverse-apply.
- **Code changes**: `git revert` per commit.
- **Seed data**: `make seed-reset` (drops and re-seeds) — with no_backfill,
  this is the canonical reset.
- **Frontend URL routing**: revert the slug rename + middleware.
- **Avro schema audits**: doc-only changes; no rollback needed.

Worst case: revert all of F2 via reset to the parent commit on
`feat/plan-0089-f2`. Per no_backfill, no production data at risk.

## 14. Out of scope for F2

F2 standardizes the ID model. It does NOT:
- Add `/entities/{uuid}/...` page for non-tradable entities (executives, sectors) — that's a v1.1 PRD
- Implement v1.1 force-regenerate brief endpoint, FU-3.2 deferred
- Touch any per-page layout (F1 + per-page waves do that)
- Add multi-exchange support (locked single-exchange)
- Add multi-class share aggregation (BRK.A + BRK.B combined view) — v2
- Touch the index ticker routing beyond stripping `^` for URL — full `/indices/` route is v1.1
- Implement drag-to-add-ticker-to-watchlist (FU-4.6 v1.1)
- Add per-ticker historical-name resolver beyond the `ticker_aliases` table

## 15. Definition of done

- All 14 acceptance criteria in §9 pass
- F2 wave commit lands on `feat/plan-0089-f2` branch (or merged into `feat/plan-0089`)
- ADR-F-XX written and merged
- `docs/plans/TRACKING.md` shows PRD-0089 wave count incremented (F1 done + F2 done)
- BP-342, BP-373, BP-374 marked RESOLVED
- Page 1 (Global Shell) is unblocked — its watchlist navigation now uses ticker URLs
