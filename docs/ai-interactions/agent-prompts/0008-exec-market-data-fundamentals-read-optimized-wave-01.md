# Execution Prompt 0007 — market-data fundamentals read-optimized table wave 01

## Context (read first)

- **Source**: Investigation of all data queried and stored in the market-data service (2026-03-12), plus prior discussion on screening (Finviz-style), timeseries (target price graphs), and read efficiency. This prompt defines: (1) current storage and JSONB content per table, (2) design and schema for an optimized read-only table for fundamentals metrics, (3) all code and config changes required so that the write path updates both source-of-truth tables and the read-optimized table, and the read path can use the new table for timeseries and screening.
- **Source planning context links**: N/A — this wave is scoped from this prompt and the storage investigation.
- **Goal**: Introduce a single narrow “fundamentals metrics” table for efficient reads (timeseries and screening) without replacing the existing section tables. Source of truth remains the 18 fundamentals section tables; the new table is a derived, read-optimized projection populated on write.

---

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md` (or equivalent)
- Prefer same structure and validation discipline as `0006-exec-market-data-audit-and-decoupling-wave-01.md`.

---

## Mandatory pre-read

1. `AGENTS.md`, `CLAUDE.md`
2. `docs/services/market-data.md` — API, DB schema, consumers, UoW
3. `services/market-data/src/market_data/infrastructure/db/models/` — all fundamentals models and _base mixin
4. `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py` — section handling and payload shapes
5. `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` — `_map_fundamentals_sections` (EODHD → canonical section keys)
6. `docs/ai-interactions/agent-prompts/0006-exec-market-data-audit-and-decoupling-wave-01.md` — read/write session usage

---

## Part 1 — Current storage: what each table stores and what is in the JSONB

### 1.1 Core and market data tables (no JSONB)

| Table | PK | Stored data | Notes |
|-------|----|-------------|--------|
| `securities` | `id` | figi, isin, name, sector, industry, country, currency, created_at, updated_at | Typed columns only. |
| `instruments` | `id` | security_id, symbol, exchange, has_ohlcv, has_quotes, has_fundamentals, name, isin, sector, industry, country, currency_code, created_at, updated_at | Typed columns; metadata denormalized from company_profile. |
| `ohlcv_bars` | (instrument_id, timeframe, bar_date) | open, high, low, close, volume, adjusted_close, source, provider_priority, ingested_at | TimescaleDB hypertable on bar_date. All typed. |
| `quotes` | instrument_id | bid, ask, last, volume, timestamp, updated_at | One row per instrument; typed. |

### 1.2 Fundamentals tables — common structure (14 period-based + 3 snapshot mixin-based)

**Shared columns (FundamentalsModelMixin):**

- `id` (UUID, PK)
- `instrument_id` (UUID, FK → instruments.id)
- `period_type` (VARCHAR: ANNUAL | QUARTERLY | SNAPSHOT)
- `period_end_date` (TIMESTAMPTZ)
- `data` (JSONB) — section-specific key/value payload
- `ingested_at` (TIMESTAMPTZ)

**Unique constraint:** `(instrument_id, period_type, period_end_date)` on all 17 mixin-based tables.

**How rows are produced (fundamentals_consumer):**

- **Financial statements** (income_statement, balance_sheet, cash_flow): EODHD payload is `{"quarterly": {"YYYY-MM-DD": row}, "yearly": {"YYYY-MM-DD": row}}`. One row per (date_str, row); `row` is stored as `data`; period_type = QUARTERLY or ANNUAL; period_end_date = parsed date_str.
- **Earnings trend:** Payload is period-code-keyed dict; each entry has `"date"`; one row per entry; data = entry; period_type = QUARTERLY.
- **Date-keyed series** (earnings_history, earnings_annual_trend, outstanding_shares, dividend_history): Payload is flat `{date_str: row}`; one row per date; row stored as `data`; period_type = QUARTERLY (earnings_history) or ANNUAL (others).
- **Snapshot sections** (highlights, valuation_ratios, technicals_snapshot, share_statistics, splits_dividends, analyst_consensus, company_profile, institutional_holders, fund_holders, insider_transactions_snapshot): One row per section per instrument; `data` = whole section object; period_end = ingested_at; period_type = SNAPSHOT (except company_profile, see below).

### 1.3 JSONB content per section (EODHD-derived keys; stored as-is in `data`)

Keys below are those observed in EODHD responses and/or user samples. Casing and presence may vary by provider.

| Section (table) | Shape | Example / typical keys in `data` |
|-----------------|--------|----------------------------------|
| income_statements | One row per fiscal period | date, totalRevenue, grossProfit, operatingIncome, netIncome, eps, currency_symbol, filing_date; camelCase from EODHD. |
| balance_sheets | One row per fiscal period | date, cash, totalAssets, totalLiab, totalStockholderEquity, netReceivables, inventory, goodWill, longTermDebt, shortTermDebt, accountsPayable, retainedEarnings, commonStockSharesOutstanding, filing_date, currency_symbol; many nullable keys. |
| cash_flow_statements | One row per fiscal period | date, operatingCashFlow, capitalExpenditures, dividendsPaid, netBorrowings, currency_symbol, filing_date. |
| highlights | One row (SNAPSHOT) | TTM metrics: Revenue, EBITDA, EPS, ROE, ROA, etc. (EODHD Highlights). |
| valuation_ratios | One row (SNAPSHOT) | PE, PB, PS, EnterpriseValue, ForwardPE, PEG, etc. (EODHD Valuation). |
| technicals_snapshot | One row (SNAPSHOT) | RSI, moving averages, beta (EODHD Technicals). |
| share_statistics | One row (SNAPSHOT) | SharesStats keys. |
| splits_dividends | One row (SNAPSHOT) | SplitsDividends summary. |
| analyst_consensus | One row (SNAPSHOT) | **Buy, Hold, Sell, StrongBuy, StrongSell, Rating, TargetPrice** (EODHD AnalystRatings). |
| earnings_history | One row per date | date, epsActual, epsEstimate, etc. |
| earnings_trends | One row per period code | date, growth/estimates. |
| earnings_annual_trends | One row per date | Annual earnings trend. |
| dividend_history | One row per date | Year/count or per-payment fields (NumberDividendsByYear). |
| outstanding_shares | One row per date | Share count. |
| institutional_holders | One row (SNAPSHOT) | EODHD Holders.Institutions structure. |
| fund_holders | One row (SNAPSHOT) | EODHD Holders.Funds structure. |
| insider_transactions_snapshot | One row (SNAPSHOT) | EODHD InsiderTransactions. |

### 1.4 company_profiles (different schema)

- **Columns:** id, instrument_id (UNIQUE), description, full_time_employees, ipo_date, fiscal_year_end, cik, cusip, lei, open_figi, is_delisted, officers (JSONB), listings (JSONB), **data (JSONB)**, ingested_at.
- **Row count:** One per instrument.
- **data JSONB:** EODHD General section: **Name, ISIN, Sector, Industry, CountryISO, CurrencyCode**, and other General keys. Consumer also copies Name, ISIN, Sector, Industry, CountryISO, CurrencyCode into instruments and securities.

### 1.5 Infrastructure tables

- ingestion_events, failed_tasks, outbox_events — no fundamentals JSONB; structure as in docs.

---

## Part 2 — Read-optimized table: design, schema, implications

### 2.1 Purpose

- **Timeseries:** Efficient “one instrument, one metric, date range” (e.g. target price over time for a graph).
- **Screening:** Efficient “filter instruments by metric” (e.g. PE &lt; 20, ROE &gt; 15) without querying JSONB in 18 tables.
- **Single source of truth:** Remains the 18 section tables. The read-optimized table is a **derived projection** populated when we write to section tables.

### 2.2 Design: narrow table (one row per instrument + as_of_date + metric)

- **Not** one column per stock (does not scale). Use **narrow** layout: one row per (instrument_id, as_of_date, metric), with a **value** column.
- **metric** is a string that identifies the series (e.g. `target_price`, `pe_ratio`, `analyst_rating`, `revenue`, `total_assets`, `roe`). A fixed set of metrics is defined and populated from section `data` using known JSONB keys.
- **value** is numeric (NUMERIC or DOUBLE PRECISION) for screening and graphing; optional second column for text/categorical if needed later.
- **as_of_date** is the logical date of the value: for period-based sections it is `period_end_date::date`; for SNAPSHOT sections it is also **always** `period_end_date::date`.
- **Deterministic date rule (mandatory):** do not derive `as_of_date` from `ingested_at`; derive from `record.period_end` only. This avoids replay drift and keeps uniqueness deterministic across retries and backfills.

### 2.3 Proposed schema

```sql
CREATE TABLE fundamental_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id   UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    as_of_date      DATE NOT NULL,
    metric          VARCHAR(64) NOT NULL,
    value_numeric   NUMERIC(24, 6) NULL,
    period_type     VARCHAR(20) NULL,  -- ANNUAL | QUARTERLY | SNAPSHOT (for disambiguation)
    section         VARCHAR(64) NULL,   -- source section e.g. analyst_consensus, valuation_ratios
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_fundamental_metrics_instrument_date_metric
    ON fundamental_metrics (instrument_id, as_of_date, metric);

CREATE INDEX ix_fundamental_metrics_metric_date
    ON fundamental_metrics (metric, as_of_date);

CREATE INDEX ix_fundamental_metrics_instrument_metric
    ON fundamental_metrics (instrument_id, metric, as_of_date);
```

- **Unique constraint:** One value per `(instrument_id, as_of_date, metric)`. For both period-based and SNAPSHOT sections, `as_of_date` is `period_end_date::date`.
- **Indexes:** Support (1) “one instrument, one metric, date range” and (2) “one metric, date range” (screening by metric then filter by date).

### 2.4 Metric catalog (initial set to extract from JSONB)

Map from (section, JSONB key) → metric name. Populate `fundamental_metrics` when writing section rows.

| Section | JSONB key(s) (EODHD / observed) | metric name | Notes |
|---------|----------------------------------|------------|-------|
| analyst_consensus | TargetPrice | target_price | |
| analyst_consensus | Rating | analyst_rating | |
| valuation_ratios | PE, pe_ratio | pe_ratio | Normalize key name from provider. |
| valuation_ratios | PB, price_to_book | pb_ratio | |
| valuation_ratios | EnterpriseValue | enterprise_value | |
| highlights | Revenue | revenue_ttm | |
| highlights | EBITDA | ebitda_ttm | |
| highlights | EPS | eps_ttm | |
| highlights | ROE | roe_ttm | |
| highlights | ROA | roa_ttm | |
| income_statements | totalRevenue, total_revenue | revenue | Use period_end_date as as_of_date. |
| income_statements | netIncome, net_income | net_income | |
| income_statements | eps | eps | |
| balance_sheets | totalAssets, total_assets | total_assets | |
| balance_sheets | totalStockholderEquity, total_equity | total_equity | |
| balance_sheets | longTermDebt | long_term_debt | |
| cash_flow_statements | operatingCashFlow | operating_cash_flow | |

All values stored in `value_numeric`; string metrics (e.g. sector) are not in this table — screening by sector uses `instruments` / `securities`. The prompt implementer must define one canonical metric name per logical series and map each provider’s JSONB keys to that name (and coerce to numeric).

### 2.5 Implications

- **Consistency:** Read-optimized table is eventually consistent with section tables: it is updated in the same write path (consumer or post-write job) that writes section tables.
- **Idempotency:** Upsert on (instrument_id, as_of_date, metric) so re-ingestion overwrites the same row.
- **Backfill:** After creating the table, backfill from existing section tables: for each section and each row, extract the catalogued keys from `data` and insert into `fundamental_metrics`. One-time migration or script.
- **Backfill operation (mandatory):** backfill must be chunked, idempotent, resumable, and observable. At minimum include batch-size control, deterministic section order, per-batch commit, and summary counters for scanned rows, extracted metrics, inserted rows, updated rows, skipped rows, and failures.
- **New metrics:** Adding a new metric = add mapping in the extractor and (optional) migration to backfill.

---

## Part 3 — Modifications required

### 3.1 Write path (put) — update source of truth and read-optimized table

- **Ownership:** Fundamentals data is written only by the **FundamentalsConsumer** (no REST “put” for fundamentals; ingestion is event-driven). So the “put” that must update both places is the consumer’s write.
- **Current behavior:** Consumer writes only to the 18 section tables via `FundamentalsRepository` upsert methods.
- **Required change:** After each successful section upsert (or after processing all sections for an event), **also** upsert into `fundamental_metrics`:
  - For each section and each record written, run an **extractor** that:
    - Reads `record.section`, `record.period_end`, `record.period_type`, `record.data`.
    - For each (section, json_key) in the metric catalog, if `record.data.get(json_key)` is present and numeric (or coercible), insert/upsert one row into `fundamental_metrics`: instrument_id = record.security_id (instrument_id), as_of_date = record.period_end.date(), metric = catalog_metric_name, value_numeric = coerced value, period_type = record.period_type, section = record.section.value.
  - Use the same transaction as the section upsert so that section table and fundamental_metrics stay in sync (or document that a separate job runs if you choose async projection).
- **Implementation options:**
  - **Option A (in-consumer):** In `fundamentals_consumer.py`, after each `await handler(record)`, call a new function `upsert_fundamental_metrics_from_record(session, record)` that performs the extraction and upsert. Session is the same UoW write session.
  - **Option B (repository layer):** Extend `FundamentalsRepository` (or add a `FundamentalMetricsRepository`) with `upsert_metrics_from_record(record)`, and call it from the consumer after each section upsert. Repository uses the same session.
- **Idempotency:** Upsert into `fundamental_metrics` with ON CONFLICT (instrument_id, as_of_date, metric) DO UPDATE SET value_numeric = EXCLUDED.value_numeric, period_type = EXCLUDED.period_type, section = EXCLUDED.section, ingested_at = EXCLUDED.ingested_at.

### 3.2 Read path — when to read from section tables vs read-optimized table

- **Keep reading from section tables for:**
  - “Full section” or “all sections for instrument” (existing endpoints): `GET /api/v1/fundamentals/{instrument_id}`, `GET /api/v1/fundamentals/{instrument_id}/income-statement`, etc. These return full `data` JSONB and must stay on section tables.
- **Use read-optimized table for:**
  - **Timeseries:** New endpoint or existing extended: e.g. `GET /api/v1/fundamentals/timeseries?instrument_id=&metric=target_price&start_date=&end_date=` returning `[{ "as_of_date": "…", "value": … }, …]`. Query: `SELECT as_of_date, value_numeric FROM fundamental_metrics WHERE instrument_id = :id AND metric = :metric AND as_of_date BETWEEN :start AND :end ORDER BY as_of_date`.
  - **Screening:** New endpoint: e.g. `GET /api/v1/fundamentals/screen?pe_ratio_max=20&roe_min=15&sector=Technology&limit=100` returning instrument IDs or summary rows. Query: join `fundamental_metrics` (filter by metric = 'pe_ratio', value_numeric &lt; 20), (metric = 'roe_ttm', value_numeric &gt; 15) and `instruments`/`securities` for sector. Implementation may use subqueries or a single query with conditional aggregation; prefer “latest as_of_date per instrument” for each metric (e.g. MAX(as_of_date)) when multiple dates exist.
- **Required code changes:**
  - New repository or query module: `FundamentalMetricsRepository` or `query_fundamental_metrics(session, instrument_id, metric, start_date, end_date)` and `query_screen(session, filters: ScreenFilters)`.
  - New API routes: timeseries and screen (path and query params as above or as agreed in API design).
  - Wire these routes to the **read** session (UoW read session or read replica) so screening/timeseries do not add load to the write DB.

### 3.3 Other modifications

- **Migrations:** New Alembic migration that creates `fundamental_metrics` and the indexes/unique constraint. No change to existing section tables.
- **Config:** No new env vars required for the new table (same DB).
- **Backfill:** Implement a one-time backfill script that reads from all section tables and inserts into `fundamental_metrics` for the metric catalog. Script requirements: deterministic ordering, chunked reads, idempotent upsert, resumability via cursor/checkpoint option, and final machine-readable summary.
- **Documentation:** Update `docs/services/market-data.md` with: new table schema, metric catalog, new endpoints (timeseries, screen), and a short “Data flow” diagram: Kafka → Consumer → Section tables + Fundamental_metrics; API “full section” → Section tables; API “timeseries” / “screen” → Fundamental_metrics.

### 3.4 Mandatory test matrix (wave 01)

The implementation is incomplete unless the following tests are added and passing:

1. **Extractor unit tests**
  - Key alias normalization (for example `PE` and `pe_ratio` → `pe_ratio`).
  - Numeric coercion (`"123"`, `"123.45"`, negative values, scientific notation).
  - Null/empty/unparseable values are skipped without raising.
  - Duplicate aliases for the same canonical metric in one payload resolve deterministically.
2. **Consumer integration tests**
  - Section upsert and metric upsert occur in the same transaction.
  - Idempotent re-ingest does not create duplicate `(instrument_id, as_of_date, metric)` rows.
  - Retry/replay overwrites existing value via ON CONFLICT.
3. **Read query integration tests**
  - Timeseries query returns sorted points and respects `start_date`/`end_date` boundaries.
  - Screening query uses latest date per metric per instrument.
  - Screening with two metrics (AND semantics) returns only instruments satisfying both.
4. **API integration tests**
  - Existing full fundamentals endpoints remain shape-compatible.
  - New timeseries/screen endpoints read from read-session path (not write-session path).
  - Invalid metric/date parameters return explicit 4xx validation errors.
5. **Backfill integration tests**
  - One run populates expected metrics from existing section rows.
  - Re-running backfill is idempotent (row counts stable, values updated when changed).
  - Progress/result summary includes scanned/extracted/inserted/updated/skipped counts.

---

## Task scope (summary)

| Task ID | Short title |
|---------|-------------|
| ROPT-1 | Add Alembic migration: create `fundamental_metrics` table and indexes. |
| ROPT-2 | Implement metric extractor: map section + JSONB keys → (metric, value_numeric); handle type coercion and missing keys. |
| ROPT-3 | Implement upsert into `fundamental_metrics` from a FundamentalsRecord (same transaction as section upsert). |
| ROPT-4 | Wire consumer to call the upsert after each section write (or after all sections for the event, same transaction). |
| ROPT-5 | Add read-side repository/query for fundamental_metrics (timeseries by instrument+metric+date range; screen by filters). |
| ROPT-6 | Add GET timeseries endpoint (e.g. /api/v1/fundamentals/timeseries) and GET screen endpoint (e.g. /api/v1/fundamentals/screen). |
| ROPT-7 | Use read session for new endpoints; document in service doc. |
| ROPT-8 | (Optional) Backfill script from section tables → fundamental_metrics. |
| ROPT-9 | Update docs/services/market-data.md: table schema, metric list, new routes, data flow diagram. |
| ROPT-10 | Add mandatory edge-case unit/integration tests for extractor, consumer, queries, API, and backfill. |

---

## Implementation order

1. ROPT-1 (migration) first.
2. ROPT-2, ROPT-3 (extractor + upsert) then ROPT-4 (wire in consumer); validate with integration test (ingest fixture, assert rows in fundamental_metrics).
3. ROPT-5, ROPT-6, ROPT-7 (read layer and endpoints).
4. ROPT-8 (backfill) and ROPT-10 (edge-case tests).
5. ROPT-9 (docs) after all behavior and tests are final.

---

## Regression and quality gates

- Existing fundamentals API (all section endpoints and full fundamentals) must still read from section tables and return unchanged response shape.
- No change to section table schemas or to the consumer’s idempotency (ingestion_events) or outbox behavior.
- New endpoints must use the read session (read replica when configured).
- After ingest of a fundamentals payload that contains analyst_consensus (TargetPrice, Rating) and valuation_ratios (PE), assert that `fundamental_metrics` contains rows for that instrument_id with metric in (target_price, analyst_rating, pe_ratio).
- Re-ingesting the same event payload must keep row cardinality stable while allowing value overwrite through upsert.
- Backfill run 1 and run 2 over identical source rows must produce identical final table state.

---

## Handoff evidence

1. List of changed/added files per task.
2. Output of migration upgrade (and downgrade) for the new table.
3. Example rows from `fundamental_metrics` after ingesting a known fixture (e.g. AAPL or test fixture).
4. Documentation quality checklist (accuracy, diagrams, pitfalls, service doc updated).
5. Exact documentation files and sections updated.

---

## Documentation quality standard

Updates to `docs/services/market-data.md` must satisfy the 8 criteria from `0000-exec-wave-generation-template.md`. Include: (1) new table `fundamental_metrics` and its columns/indexes, (2) list of promoted metrics and their source section/key, (3) new API routes and query parameters, (4) a Mermaid diagram for data flow: ingestion → section tables + fundamental_metrics; read paths (section APIs vs timeseries/screen).
