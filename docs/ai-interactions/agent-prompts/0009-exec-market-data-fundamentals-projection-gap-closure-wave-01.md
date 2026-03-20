# Execution Prompt 0008 — market-data fundamentals projection gap-closure wave 01

## Context (read first)

- Planning context: gap analysis from prompt 0007 plus live DB verification of source JSON keys vs projected `fundamental_metrics` rows.
- Key finding: `fundamental_metrics.metric` stores canonical names (for example `pe_ratio`) while many source keys in section JSONB are not yet projected.
- Goal: close all currently discovered projection gaps and correctness issues while preserving source-of-truth fundamentals tables.

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`
- `.claude/agents/qa-test-engineer.md`

## Mandatory pre-read

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/MASTER_PLAN.md`
4. `docs/ai-interactions/BUG_PATTERNS.md` (scan relevant categories before editing)
5. `docs/services/market-data.md`
6. `docs/ai-interactions/agent-prompts/0007-exec-market-data-fundamentals-read-optimized-wave-01.md`
7. `services/market-data/src/market_data/infrastructure/db/metric_extractor.py`
8. `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`
9. `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_repo.py`
10. `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_query.py`
11. `services/market-data/src/market_data/api/routers/fundamental_metrics.py`

## Objective

Fix all existing and discovered fundamentals projection issues:

1. Project all currently discovered source keys that are suitable for metrics into `fundamental_metrics`.
2. Fix known alias mismatch causing dropped metrics (`operating_cash_flow`).
3. Add missing compatibility aliases so common EODHD key variants are inserted.
4. Add one-time backfill for already ingested fundamentals rows.
5. Add test coverage proving no currently known source key is silently skipped for selected sections.
6. Update docs so query semantics and canonical metric names are explicit.

## Deterministic behavior requirements (mandatory)

1. Projection `as_of_date` must be derived from `record.period_end.date()` only.
2. This rule applies to ANNUAL, QUARTERLY, and SNAPSHOT records equally.
3. Do not derive `as_of_date` from `ingested_at`; replay and backfill must produce the same `(instrument_id, as_of_date, metric)` key.

## Task scope for this wave

### Parallel group(s)

- **FMG-01 (Catalog expansion):** expand extractor catalog to include all discovered unmapped numeric metrics from valuation/highlights/analyst/income/balance/cash-flow sections.
- **FMG-02 (Alias correctness):** add/adjust aliases for existing mapped metrics to match live payload keys (especially cash-flow aliases).
- **FMG-03 (Observability):** add debug/warn instrumentation for unmapped keys encountered during extraction.

### Sequential group(s)

- **FMG-04 (Backfill):** add a deterministic backfill path that replays existing fundamentals section rows into `fundamental_metrics`.
- **FMG-05 (Tests):** add/extend unit + integration tests for extractor, consumer write path, and backfill behavior.
- **FMG-06 (API/documentation alignment):** ensure API/docs clearly state canonical metric names and (optional) add alias translation for common raw names.

## Why this chunk

This chunk is cohesive around a single subsystem (fundamentals projection). It removes correctness gaps first (catalog + aliases), then addresses existing data consistency via backfill, and finally locks behavior with tests and documentation.

## Implementation instructions

### FMG-01 — Expand metric catalog with all discovered insertable keys

In `metric_extractor.py`, expand `_METRIC_CATALOG` to map all currently discovered keys below to canonical metric names (snake_case).

#### Valuation ratios (`valuation_ratios`)

Currently missing keys to add:

- `ForwardPE`
- `EnterpriseValueEbitda`
- `EnterpriseValueRevenue`
- `PriceSalesTTM`

Recommended canonical names:

- `forward_pe`
- `enterprise_value_ebitda`
- `enterprise_value_revenue`
- `price_sales_ttm`

#### Highlights (`highlights`)

Currently missing keys to add:

- `BookValue`
- `DilutedEpsTTM`
- `DividendShare`
- `DividendYield`
- `EPSEstimateCurrentQuarter`
- `EPSEstimateCurrentYear`
- `EPSEstimateNextQuarter`
- `EPSEstimateNextYear`
- `GrossProfitTTM`
- `MarketCapitalization`
- `MarketCapitalizationMln`
- `OperatingMarginTTM`
- `PEGRatio`
- `PERatio`
- `ProfitMargin`
- `QuarterlyEarningsGrowthYOY`
- `QuarterlyRevenueGrowthYOY`
- `RevenuePerShareTTM`
- `WallStreetTargetPrice`

Notes:

- Exclude non-metric date-like descriptors such as `MostRecentQuarter` from numeric metric projection unless explicitly modeled as date/text metric.
- Keep canonical names stable and documented.

#### Analyst consensus (`analyst_consensus`)

Currently missing keys to add:

- `Buy`
- `Hold`
- `Sell`
- `StrongBuy`
- `StrongSell`

Recommended canonical names:

- `analyst_buy`
- `analyst_hold`
- `analyst_sell`
- `analyst_strong_buy`
- `analyst_strong_sell`

#### Income statements (`income_statements`)

Add numeric financial metrics that are currently unmapped, excluding metadata keys (`date`, `filing_date`, `currency_symbol`).

Minimum expected additions include:

- `costOfRevenue`, `grossProfit`, `operatingIncome`, `incomeBeforeTax`, `incomeTaxExpense`
- `interestExpense`, `interestIncome`, `ebit`, `ebitda`
- `totalOperatingExpenses`, `totalOtherIncomeExpenseNet`, `researchDevelopment`
- `sellingGeneralAdministrative`, `sellingAndMarketingExpenses`
- `netIncomeApplicableToCommonShares`, `netIncomeFromContinuingOps`

#### Balance sheets (`balance_sheets`)

Add numeric balance sheet metrics currently unmapped, excluding metadata keys (`date`, `filing_date`, `currency_symbol`).

Minimum expected additions include:

- `cash`, `cashAndEquivalents`, `cashAndShortTermInvestments`
- `totalLiab`, `totalCurrentAssets`, `totalCurrentLiabilities`
- `shortTermDebt`, `shortLongTermDebt`, `shortLongTermDebtTotal`
- `accountsPayable`, `netReceivables`, `inventory`
- `retainedEarnings`, `propertyPlantAndEquipmentNet`
- `commonStockSharesOutstanding`, `netDebt`, `netWorkingCapital`

#### Cash flow (`cash_flow_statements`)

Add numeric cash-flow metrics currently unmapped, excluding metadata keys (`date`, `filing_date`, `currency_symbol`).

Minimum expected additions include:

- `totalCashFromOperatingActivities`
- `capitalExpenditures`
- `freeCashFlow`
- `totalCashFromFinancingActivities`
- `totalCashflowsFromInvestingActivities`
- `dividendsPaid`
- `netBorrowings`
- `depreciation`

### FMG-02 — Alias correctness and canonical mapping consistency

1. Ensure existing metrics include aliases matching live payload keys.
2. Explicitly fix `operating_cash_flow` so current cash-flow payload keys populate it (for example alias `totalCashFromOperatingActivities` in addition to existing aliases).
3. Keep one canonical metric name per concept; aliases only affect extraction, never stored metric naming.

### FMG-03 — Unmapped key observability

1. Add extractor-level instrumentation for section keys present in `data` but not matched by catalog aliases.
2. Log as structured debug/warn with fields: `section`, `instrument_id` (if available at callsite), `period_type`, `unmapped_keys_count`, `unmapped_keys_sample`.
3. Do not fail ingestion due to unmapped keys.

### FMG-04 — Backfill existing rows

1. Add a backfill mechanism (script or one-shot job entrypoint) under market-data service scope that:
   - Scans existing fundamentals section tables.
   - Reconstructs `FundamentalsRecord`-equivalent inputs.
   - Re-runs extraction and upsert into `fundamental_metrics`.
2. Backfill must be idempotent (safe to re-run).
3. Backfill must report processed rows and inserted/updated metrics.
4. Backfill operational contract (mandatory):
   - Deterministic section traversal order and deterministic row ordering.
   - Chunked reads/writes with configurable batch size.
   - Per-batch commit and continue-on-error mode with structured failure reporting.
   - Resumable execution via cursor/checkpoint (`--section`, `--start-id` or equivalent).
   - Final machine-readable summary (JSON or logfmt) including runtime and counters.

### FMG-05 — Tests and guards

1. Add/extend unit tests for extractor mappings and alias handling.
2. Add targeted tests for text vs numeric storage (`value_text` and `value_numeric`) where relevant.
3. Add integration test proving a fundamentals payload containing newly mapped keys creates expected `fundamental_metrics` rows.
4. Add regression test for `operating_cash_flow` population from current payload key variants.
5. Add edge-case tests for extractor coercion and key handling:
   - Numeric strings with commas/whitespace.
   - Negative numbers and scientific notation.
   - Nulls, empty strings, and non-numeric text.
   - Duplicate alias keys mapping to the same canonical metric.
6. Add idempotency tests:
   - Re-ingest identical payload: no duplicate rows.
   - Re-ingest with changed value for same unique key: value updated.
7. Add API-level integration tests:
   - Timeseries endpoint ordering and inclusive date boundaries.
   - Screen endpoint latest-per-metric semantics.
   - 4xx validation for invalid metric/date params.
   - Alias query translation behavior (if enabled).
8. Add read-path tests proving timeseries/screen endpoints use read session wiring.

### FMG-06 — API and docs alignment

1. Ensure read APIs are explicit about canonical metric names.
2. If implementing metric alias query translation (recommended), document alias map and precedence.
3. Update market-data docs with:
   - Expanded promoted metric catalog.
   - Raw key aliases and canonical names.
   - Backfill command and expected output.
   - Deterministic `as_of_date` derivation rule.
   - Screening semantics: latest metric row per instrument at query time.

## Constraints

1. Do not change source-of-truth fundamentals section table semantics.
2. Do not remove existing canonical metric names.
3. Do not introduce breaking API contract changes without versioning.
4. Do not modify unrelated services.

## Scope & token budget

- **write_paths:**
  - `services/market-data/src/market_data/infrastructure/db/metric_extractor.py`
  - `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`
  - `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_repo.py`
  - `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_query.py`
  - `services/market-data/src/market_data/api/routers/fundamental_metrics.py`
  - `services/market-data/src/market_data/**/backfill*.py` (new)
  - `services/market-data/tests/**`
  - `docs/services/market-data.md`
  - `docs/ai-interactions/agent-prompts/0007-exec-market-data-fundamentals-read-optimized-wave-01.md` (only if metric catalog section needs synchronization)
- **exploration bound:** max 10 files before first edit unless blocker discovered.
- **stop condition:** if canonical naming conflicts with existing public consumers, stop and propose compatibility plan before continuing.

## Required tests

Run in task-scoped fail-fast order after each logical task:

1. `cd services/market-data && .venv/bin/pytest tests -k "fundamental_metrics or metric_extractor or fundamentals_consumer or backfill or fundamental_metrics_router"`
2. `cd services/market-data && .venv/bin/ruff check src/market_data/infrastructure/db/metric_extractor.py src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py src/market_data/infrastructure/db/repositories tests`
3. `cd services/market-data && .venv/bin/mypy src`

Pass criteria:

- All three commands exit 0.
- New tests prove newly mapped keys are inserted.
- New tests prove deterministic idempotency and edge-case coercion behavior.

## Minimum edge-case test matrix

All rows below are mandatory unless explicitly waived with rationale in handoff evidence.

| Area | Case | Expected result |
|------|------|-----------------|
| Extractor | `PE`, `pe_ratio`, `PERatio` aliases present across payload variants | One canonical metric `pe_ratio` stored |
| Extractor | `totalCashFromOperatingActivities` only | `operating_cash_flow` populated |
| Extractor | `" 1,234.56 "` numeric string | Coerced to numeric value |
| Extractor | `"N/A"` or empty string | No numeric value inserted; ingestion continues |
| Extractor | same canonical metric appears under two alias keys in same row | deterministic precedence, one upsert row |
| Consumer/UoW | section upsert succeeds, metric upsert fails | transaction rollback (no partial write) |
| Consumer/UoW | replay same record | no duplicate rows, upsert overwrite semantics preserved |
| API timeseries | `start_date > end_date` | explicit 4xx validation error |
| API screen | two metric filters + sector filter | AND semantics + sector filter enforced |
| Backfill | run twice with same data | identical final state and counters reflect updates/not duplicates |
| Backfill | resume from checkpoint after failure | completion without duplicating prior rows |

## Incremental quality gates (mandatory)

For each FMG task:

1. Implement minimal change for that task.
2. Run targeted pytest.
3. Run changed-path ruff.
4. Run changed-package mypy.
5. Fix failures immediately before next task.

No deferred fixes allowed.

## Documentation requirements

Update docs in the same wave for any behavior/contract/config/schema/test-surface changes.

Mandatory updates:

1. `docs/services/market-data.md`
2. If canonical metric list changed materially, update `docs/ai-interactions/agent-prompts/0007-exec-market-data-fundamentals-read-optimized-wave-01.md` metric catalog section for consistency.

Documentation must satisfy the Documentation quality standard from `0000-exec-wave-generation-template.md`.

## Required handoff evidence

1. Changed files grouped by FMG task ID.
2. List of all newly added canonical metric names by section.
3. Before/after sample query output proving previously missing keys now appear in `fundamental_metrics`.
4. Backfill run summary (rows scanned, metric rows upserted, runtime).
5. Validation ledger: command, scope, exit code, result.
6. Documentation quality checklist table.
7. Commit message proposal:
   - Title (imperative)
   - 1-2 sentence body with implemented scope + validation.
8. Edge-case matrix status table: each case mapped to test name and pass/fail.

## Definition of done

1. All discovered insertable keys listed in this prompt are either:
   - mapped and tested, or
   - explicitly rejected with documented technical reason.
2. `operating_cash_flow` alias mismatch is fixed and covered by tests.
3. Backfill exists and is idempotent.
4. Task-scoped pytest + ruff + mypy pass.
5. Required docs are updated and quality checklist is complete.
6. Minimum edge-case test matrix is fully green, or waivers are documented with explicit technical reason.
