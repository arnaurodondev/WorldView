---
title: PRD-0089 F2 — Deferred Follow-ups
parent_wave: F2 (Entity / Instrument ID Unification)
parent_adr: ADR-F-16
created: 2026-05-20
status: living document — items get crossed off as they ship
---

# F2 Deferred Follow-ups

This document tracks work items surfaced during PRD-0089 wave F2 execution
that were **intentionally deferred**, not forgotten. Each entry states what
the deferred work is, why it was deferred, what triggers picking it back up,
and the rough shape of the eventual fix.

The three items at the top of [the F2 final report's "Open follow-up tasks"
list](../../specs/0089-platform-page-redesign.md) marked as `Concrete
defects` have **already been fixed** (see commit log on `feat/plan-0089-f2`
and `docs/BUG_PATTERNS.md` BP-493 / BP-494 / BP-495). What remains below is
design-decision territory.

---

## D-1. Add `instruments.is_active` (or full lifecycle status) — restore partial unique index

**Source**: F2 Step 1 deviation #2 — ADR-F-16 §Deviations item 2.
**Severity**: MEDIUM — silent collision risk at insert time.
**Effort**: half day.

### Current state
The F2 schema migration (`services/market-data/alembic/versions/017_unique_ticker_exchange.py`)
intends a **partial** unique index `(upper(symbol), exchange) WHERE status = 'active'`
per F2 plan §2.3 — which allows historical/delisted rows to share a symbol with
a currently-active row. But `instruments` has no `status` column, so the index
shipped **unconditional** (strictly stronger). Today no delisted rows exist, so
there's no observable problem.

### Why deferred
- No `status`/`is_active`/`lifecycle_status` column exists anywhere on `instruments` or its parent `securities`.
- A lifecycle indicator does exist *one table over* on `company_profiles.is_delisted BOOLEAN NOT NULL DEFAULT false` — single boolean, per-profile, not per-instrument.
- F2's scope was ID unification, not lifecycle modelling. Punting was the right call.

### Trigger condition (when to pick this up)
When **any** of the following becomes true:
1. The platform ingests its first delisted-then-relisted ticker and the unique constraint blocks the insert.
2. A user-visible "delisted" badge is needed (UI design pulls this onto the screener).
3. The platform extends ingestion beyond single-exchange (the locked-single-exchange constraint per F2 §14 lifts).

### Proposed solution (3 stages)

| Stage | Change | Risk |
|---|---|---|
| 1 | Drop the redundant `uq_instruments_symbol_exchange (symbol, exchange)` UNIQUE constraint — F2's `idx_instruments_ticker_exchange_active (upper(symbol), exchange)` is strictly more constraining and supersedes it | Trivial — zero ambiguity |
| 2 | Add `instruments.is_active BOOLEAN NOT NULL DEFAULT true`; rewrite the index `WHERE is_active = true`; backfill: `UPDATE instruments SET is_active = NOT EXISTS (SELECT 1 FROM company_profiles cp WHERE cp.instrument_id = instruments.id AND cp.is_delisted)` | Low — boolean column, no schema-shape changes |
| 3 | Replace `is_active` boolean with `lifecycle_status` enum `('active','delisted','suspended','pending','test')`; richer states, supports historical-listing views | Separate PRD — design discussion needed |

### Best long-term solution
Stage 2 alone (boolean + partial index) closes the F2 gap. Stage 3 is a v2
or v3 feature when the platform grows multi-state lifecycle UX. **Do stages
1+2 as one migration.**

---

## D-2. Reclassify ~1,238 legacy foreign canonical entities (.KS / .SZ / .HK / .T / …) — narrow M-017 invariant

**Source**: F2 Step 1 deviation #9 — ADR-F-16 §Deviations item 9.
**Severity**: LOW (test-bypassed) but data-shape: HIGH (heavy downstream references).
**Effort**: half day (Option A) — separate PRD for richer options.

### Current state
Live `intelligence_db` contains **1,238 canonical_entities rows** with
`entity_type='financial_instrument'` but no matching `market_data.instruments`
row. They're a mix of:

- Foreign exchanges: `.F` (Frankfurt), `.L` (London), `.HK` (Hong Kong), `.MX`, `.T` (Tokyo), `.KS` (Korea), `.PA`, `.MU`, `.DU`, `.US`
- US-suffixed-but-not-ingested tickers
- ~1,200 tickers with no exchange suffix at all

Source: migration `0009_seed_canonicals_bootstrap.py` (PLAN-0057 Wave A-3,
originally 224 rows / 9 classes) plus runtime growth.

Downstream coupling is **heavy**:

| Table | Rows referencing these legacy entities |
|---|---|
| `entity_aliases` | 6,764 |
| `entity_embedding_state` | 3,373 |
| `relation_evidence_raw` (subject OR object) | 2,492 |

### Why deferred
- The M-017 integration test (`services/knowledge-graph/tests/integration/test_m017_invariant.py`) already filters via `entity_id::text LIKE '0190%'` (UUIDv7-only) so it correctly excludes legacy v4-UUID rows. No CI false positives.
- Deleting these rows would cascade-delete ~12,629 evidence/embedding/alias rows. They're active KG citizens: news articles tag them, embeddings power semantic search, relations feed the graph view.
- `make seed-verify-m017` was likewise patched to filter `LIKE '0190%'` (see BP-491 fix in this commit set).
- Pre-F2 the dual-id model meant `entity_type='financial_instrument'` was overloaded as "any company we've seen in news" rather than "tradable in our market-data DB". The mismatch is conceptual, not corrupt.

### Trigger condition (when to pick this up)
When **any** of the following becomes true:
1. The platform supports multi-exchange ingestion (locked-single-exchange constraint per F2 §14 lifts) — at which point most legacy rows would *gain* matching `instruments` rows automatically, no cleanup needed.
2. A UI surface displays an `entity_type='financial_instrument'` entity that has no fundamentals/price (broken-link experience) — users see the gap.
3. A future migration's CHECK constraint enforces "financial_instrument ⇒ row in instruments" via foreign-key — would need cleanup first.

### Proposed solutions (3 options, increasing aggressiveness)

**(A) Tag-don't-delete (RECOMMENDED for v1)**
- Add `canonical_entities.primary_exchange VARCHAR(10) NULL` (or reuse the existing `exchange` column if always populated).
- Narrow the M-017 invariant to "for `financial_instrument` entities with `primary_exchange='US'`".
- Update the integration test to filter on exchange instead of UUID prefix.
- Effort: half day. Risk: low.
- Preserves all KG signal AND fixes M-017 conceptually.

**(B) Reclassify to `unknown`**
- Bulk `UPDATE canonical_entities SET entity_type='unknown' WHERE entity_type='financial_instrument' AND entity_id::text NOT LIKE '0190%'`.
- Effort: 1 hour. Risk: medium — downstream code that filters `WHERE entity_type='financial_instrument'` will stop seeing them. Audit needed: news entity tagging, screener results for foreign tickers, embedding search by kind.

**(C) Selective cleanup**
- Delete only entities with zero downstream references in `entity_aliases`, `entity_embedding_state`, `relation_evidence_raw`. Heuristic; likely 0–50 truly-unused rows. Skin off the fingernail; not worth the audit work for that few rows.

### Best long-term solution
**Option A** — narrows the invariant to match reality without losing data. Apply
when condition (1) or (2) above triggers. If multi-exchange ingestion ships
first, this issue resolves itself.

---

## D-3. Unauthenticated S9 alias-lookup endpoint — activate middleware 301 redirects

**Source**: F2 Step 9 deviation #8 — ADR-F-16 §Deviations item 8.
**Severity**: LOW — UX nicety, not correctness.
**Effort**: half day.

### Current state
The Next.js middleware (`apps/worldview-web/middleware.ts:160-166`) has a
**documented TODO** for legacy-ticker-alias 301 redirects (e.g. `/instruments/FB`
→ `/instruments/META`). The middleware currently does case-canonicalization
only (`aapl` → `AAPL`).

The backend `resolve_security_id` helper (`services/api-gateway/src/api_gateway/resolution.py`)
**already handles alias resolution** server-side, so the page-bundle endpoint
serves the canonical data regardless of which alias the user types. Only the
URL-bar rewrite is missing — UX nicety, not data correctness.

### Why deferred
Next.js middleware runs at the **edge runtime**, which executes *before*
session hydration. Calling an OIDC-protected endpoint from middleware would
either:
- Leak JWTs into edge logs (bad)
- Require a service-account JWT not available to the edge runtime (impractical)

So the alias lookup must be **unauthenticated**, but no such endpoint exists
on S9 today. Adding one needs minor security thought (rate limiting at the
edge to prevent ticker enumeration).

Additionally, the `ticker_aliases` table is **empty** in v1 per the no-backfill
policy. No alias rows exist yet → the middleware can't observably do anything
even if wired.

### Trigger condition (when to pick this up)
When **either** is true:
1. The first row gets recorded in `ticker_aliases` (a real corporate ticker change happens, e.g. an issuer renames or merges).
2. A user-research signal indicates they're typing legacy tickers (e.g. `FB`) into the URL bar enough to warrant the rewrite UX.

### Proposed solution
Add a small public endpoint:

```
GET /internal/v1/instruments/aliases/{ticker}

200 → {"canonical_ticker": "META", "redirected_from": "FB"}
404 → not an alias (or unknown ticker — same response shape)
```

- Lives under `/internal/*` so it's covered by the existing `_AUTH_SKIP_PATHS` bypass for unauthenticated reads.
- Read-only on a public-domain table — ticker history isn't sensitive.
- Rate-limit at the edge (10 requests/minute per IP) to prevent ticker enumeration.
- Update `middleware.ts` to call it, cache result in `Response.headers` so subsequent navigations skip the round-trip.

### Best long-term solution
The endpoint as described above. **Effort: half day** including rate-limit
test + the `middleware.ts` call. Defer until trigger condition (1) — there's
no point shipping an endpoint that has nothing to return.

### Alternative considered
Doing the alias resolution **server-side** in `[ticker]/page.tsx` server
component and calling `redirect()` from there avoids needing an unauthenticated
endpoint, but the redirect happens one hop later — visible as a flash in
the UI. The middleware approach is cleaner; defer.

---

## D-4. Refactor MarketDataClient sharing — eliminate per-worker httpx pool duplication

**Source**: Surfaced during the F2 step-5 wiring fix (commit set following ADR-F-16).
**Severity**: LOW — performance / resource overhead, not correctness.
**Effort**: 1-2 days.

### Current state
After the F2-step-5-wiring fix landed:
- `_add_structured_enrichment_worker` builds its own `MarketDataClient` (line 706 in `scheduler.py`)
- `build_workers` now builds a **second** `MarketDataClient` for `ProvisionalEnrichmentWorker` (added by F2-step-5-wiring fix at line 425)
- `provisional_queued_consumer_main.py` (standalone consumer) builds a **third**

Each client owns an httpx connection pool. They run in the same process for
the scheduler container, separate processes for the consumer container. The
scheduler runs two parallel pools to the same S2 backend.

### Why deferred
The F2-step-5-wiring fix prioritized minimum-risk: a second client at scope
duplicates ~5 LOC of construction, with cleanly-tracked `aclose` lifecycle in
`workers["_aux_aclose"]`. Sharing the client requires refactoring
`_add_structured_enrichment_worker` to either return its client (signature
change) or moving client construction to `build_workers` top-level (multi-step
refactor that touches the structured-enrichment wiring).

### Trigger condition
When **any** of the following:
1. Connection pool exhaustion appears in metrics (`httpx_pool_full_total` or similar) under load.
2. The next F-wave already needs to refactor `build_workers` for another reason — at which point folding this in is free.
3. A third worker needs `MarketDataClient` (would mean four pools — getting ridiculous).

### Proposed solution
1. Move `MarketDataClient` construction to the **top** of `build_workers` (before any worker is instantiated).
2. Pass it as a kwarg to `_add_structured_enrichment_worker` and use the existing instance for `ProvisionalEnrichmentWorker`.
3. Register a single `aclose` hook in `workers["_aux_aclose"]`.
4. For `provisional_queued_consumer_main.py`, this is a separate process so a separate client is fine; can stay as-is.

Net change: 1 connection pool in the scheduler container, 1 in the consumer container. Down from 2+1.

### Best long-term solution
Same as proposed — defer until trigger (1) or (2). Don't do this as a
standalone refactor; bundle with the next scheduler-touching wave.

---

## Cross-cutting prevention recommendations

These came out of the F2 wave's surface area. They compound across future work.

1. **Hardcoded version literals in tests** → see [BP-493](../../BUG_PATTERNS.md). Code review must reject any test asserting against a literal `version_num` — must derive from `ScriptDirectory`.

2. **Bash-isms in Makefile recipes** → see [BP-494](../../BUG_PATTERNS.md). Add a lint pass: `grep -E '<\(|>\(|\[\[|\$\{[^}]*\^\^|\$RANDOM' Makefile` should be empty (or every match wrapped under an explicit `bash -c`).

3. **Wired-but-disabled feature flags** → see [BP-495](../../BUG_PATTERNS.md). New optional constructor kwargs that default to `None` for safety should have a wiring follow-up tracked at the same commit, AND a startup-time log that announces the feature state (`"M-017 deferral active"` vs `"…disabled (no lookup port)"`).

4. **Plan-vs-reality column drift** → F2 caught two cases (`canonical_entities.kind` not existing; `instruments.status` not existing). Pattern: PRDs reference column names that don't exist. Before writing a migration that depends on a column from a plan, `psql \d <table>` against a live DB if available.

5. **M-017-style invariants gated on UUID prefix filters** → the `LIKE '0190%'` filter is brittle (UUIDv7 prefix increments every ~25 days). Better: use `created_at > '2026-05-20'`, or add an explicit `f2_canonical BOOLEAN` flag, or reclassify the data so no filter is needed. See D-2 above.

---

## Status table

| ID | Item | Status | Triggered? |
|---|---|---|---|
| D-1 | `instruments.is_active` lifecycle | Deferred | No |
| D-2 | Legacy foreign canonicals reclassification | Deferred | No |
| D-3 | S9 unauthenticated alias endpoint | Deferred | No (ticker_aliases empty) |
| D-4 | MarketDataClient sharing | Deferred | No |

When an item triggers, move it to `docs/plans/<NNNN>-…` as a proper sub-plan.
