# Execution Prompt 0005 — eodhd-pipeline-fixes-and-extensions wave 01

## Context (read first)

- **Research source**: Live codebase audit conducted on 2026-03-12 — full read of
  `services/market-ingestion/`, `services/market-data/`, `libs/contracts/`, and
  `eodhd-claude-skills/skills/eodhd-api/references/`.
- **EODHD reference docs**: `eodhd-claude-skills/skills/eodhd-api/references/endpoints/`
- **Subscription assumed**: All-In-One ($99.99/mo) — 100,000 API credits/day,
  1,000 req/min, WebSocket included.

---

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`
- `.claude/agents/architecture-decision-lead.md`

---

## Mandatory pre-read

Read **all** of these before writing a single line of code:

1. `AGENTS.md` — coding standards, naming conventions, architecture patterns
2. `CLAUDE.md` — Claude-specific workflow, diff discipline, logging rules
3. `docs/services/market-data.md` — service spec (consumers, DB schema, API)
4. `docs/services/market-ingestion.md` — service spec (pipeline, adapters, policies)
5. `docs/libs/contracts.md` — canonical model spec
6. `docs/libs/messaging.md` — Kafka consumer/producer, outbox, error hierarchy
7. `docs/libs/storage.md` — ObjectStorage interface
8. `docs/ai-interactions/BUG_PATTERNS.md` — scan all entries relevant to upsert semantics,
   async ORM, datetime/timezone, and Kafka consumer idempotency
9. `eodhd-claude-skills/skills/eodhd-api/references/endpoints/fundamentals-common-stock.md`
   — authoritative EODHD response structure for fundamentals
10. `eodhd-claude-skills/skills/eodhd-api/SKILL.md` — full endpoint catalogue with cost table

When handing off, explicitly list which `BP-xxx` entries were applied.

---

## Objective

This wave covers **two independent scopes** that must be executed in order:

**Part A — Pipeline Bug Fixes (FIX-F1 through FIX-F10, FIX-O1, FIX-O2, FIX-Q1)**
Fix all confirmed bugs in the fundamentals, OHLCV, and quotes ingestion pipelines.
These are correctness regressions — data already in the database from the broken pipeline
may be malformed and must be considered stale after these fixes are deployed.

**Part B — New EODHD Endpoint Coverage (EXT-01 through EXT-08)**
Add eight new data types that the All-In-One plan makes available but the service does
not yet ingest: intraday OHLCV, earnings calendar, economic events, macro indicators,
news sentiment, insider transactions, US Treasury yield curve, and historical market cap.

At the end of this wave:
- All 13 fundamentals tables have correct `UNIQUE (instrument_id, period_type, period_end_date)`
  constraints and the repo upsert fires correctly.
- Financial statement sections are stored as individual per-period rows, not a single blob.
- `period_type` reflects actual data granularity (`annual`, `quarterly`, `snapshot`).
- `General` section is extracted and populates the `instruments` table + new `company_profiles` table.
- `dividend_history` is populated with real data from `NumberDividendsByYear`.
- OHLCV intraday datetime parsing is Python 3.10 compatible.
- Eight new `DatasetType` enum values exist (or reuse where noted), with adapter methods,
  canonical models, DB tables, migrations, and polling policy seeds.

---

## Task scope — Part A (Bug Fixes)

**Total tasks: 13**

### Parallel group A1 — no cross-task dependencies (start simultaneously)

| Task ID | Severity | Short title | Primary touched paths |
|---------|----------|-------------|-----------------------|
| FIX-F1 | 🔴 Critical | Add UNIQUE constraints to all fundamentals tables + fix upsert conflict target | `services/market-data/alembic/versions/`, `infrastructure/db/repositories/fundamentals_repo.py` |
| FIX-F5 | 🟠 High | Fix `dividend_history` key in mapper | `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` |
| FIX-F4 | 🟠 High | Extract `General` section → instruments + new `company_profiles` table | `execute_task.py`, `fundamentals_consumer.py`, `alembic/`, `domain/enums.py` (market-data), `db/models/`, `db/repositories/` |
| FIX-O1 | 🟡 Minor | Python 3.10-compatible intraday datetime parsing | `libs/contracts/src/contracts/canonical/ohlcv.py` |
| FIX-Q1 | 🟡 Minor | Log warning on zero-price quote | `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` |

### Sequential group A2 — after FIX-F1 completes (constraint must exist before consumer fix deployed)

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| FIX-F2 | FIX-F1 done | Add `PeriodType.SNAPSHOT` enum; decompose financial statements into per-period rows |
| FIX-F3 | FIX-F2 done | `period_type` now reflects actual data granularity (quarterly / annual / snapshot) |

### Parallel group A3 — after A1 and A2 complete

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| FIX-F6  | FIX-F1 done | Extract `Holders` (institutional + fund) from fundamentals |
| FIX-F7  | FIX-F1 done | Extract embedded `InsiderTransactions` from fundamentals |
| FIX-F8  | FIX-F1 done | Resolve dead `dividend_summary` table (add writer or drop) |
| FIX-F9  | FIX-F2, FIX-F3 done | Validate per-period row granularity for financial statements |
| FIX-F10 | FIX-F4 done | Split `Highlights` + `Valuation` into separate sections |
| FIX-O2  | FIX-O1 done | Document `adjusted_close = None` for intraday bars (comment + docs) |

---

## Task scope — Part B (New Endpoints)

**Total tasks: 8**

### Parallel group B1 — independent, can start once Part A is done

| Task ID | Short title | API credits/call | New `DatasetType` |
|---------|-------------|------------------|-------------------|
| EXT-01 | Intraday OHLCV | 5 | reuse `OHLCV` |
| EXT-02 | Earnings Calendar | 1 (bulk) | `EARNINGS_CALENDAR` |
| EXT-03 | Economic Events | 1 (bulk) | `ECONOMIC_EVENTS` |
| EXT-04 | Macro Indicators | 1 per (country, indicator) | `MACRO_INDICATOR` |
| EXT-05 | News + Daily Sentiment aggregation | 5+5/ticker | `NEWS_SENTIMENT` |
| EXT-06 | Insider Transactions (standalone endpoint) | 1/ticker | `INSIDER_TRANSACTIONS` |
| EXT-07 | US Treasury Yield Curve | 1/series | `YIELD_CURVE` |
| EXT-08 | Historical Market Cap | 10/ticker | `MARKET_CAP` |

---

## Implementation instructions — Part A

---

### FIX-F1 🔴 — Add UNIQUE constraints to all fundamentals tables; fix upsert conflict target

**Root cause confirmed:**

In `services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_repo.py`,
`_upsert_section()` conflicts on `["id"]`. The `id` column is `gen_random_uuid()` server-generated
and is always a fresh UUID4 — the conflict can never fire. Every call is a plain `INSERT`,
producing unbounded duplicate rows on every poll cycle.

In `services/market-data/alembic/versions/001_initial_schema.py`, the `_create_fundamentals_table()`
helper adds only a `ix_{table}_instrument_id` lookup index — there is no
`UNIQUE (instrument_id, period_type, period_end_date)` natural-key constraint on any of the 14
fundamentals tables.

**Step 1 — New Alembic migration in market-data:**

Create `services/market-data/alembic/versions/003_fundamentals_unique_constraints.py`:

```python
"""Add UNIQUE (instrument_id, period_type, period_end_date) to all fundamentals tables.

Revision ID: 003
Revises: 002
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

_FUNDAMENTALS_TABLES = [
    "income_statements",
    "balance_sheets",
    "cash_flows",
    "valuation_ratios",
    "technicals_snapshots",
    "share_statistics",
    "splits_dividends",
    "analyst_consensus",
    "earnings_history",
    "earnings_trend",
    "earnings_annual_trend",
    "dividend_history",
    "outstanding_shares",
    # company_profiles is added by FIX-F4 with its own UNIQUE (instrument_id)
]


def upgrade() -> None:
    for table in _FUNDAMENTALS_TABLES:
        op.create_unique_constraint(
            f"uq_{table}_instrument_period",
            table,
            ["instrument_id", "period_type", "period_end_date"],
        )
        op.create_index(
            f"ix_{table}_instrument_period",
            table,
            ["instrument_id", "period_type", "period_end_date"],
        )


def downgrade() -> None:
    for table in _FUNDAMENTALS_TABLES:
        op.drop_index(f"ix_{table}_instrument_period", table_name=table)
        op.drop_constraint(f"uq_{table}_instrument_period", table, type_="unique")
```

**Step 2 — Fix `_upsert_section()` in `fundamentals_repo.py`:**

```python
# BEFORE (broken — conflicts on PK which is always a new UUID)
.on_conflict_do_update(
    index_elements=["id"],
    set_={...},
)

# AFTER (correct — conflicts on natural key)
.on_conflict_do_update(
    index_elements=["instrument_id", "period_type", "period_end_date"],
    set_={
        "data": insert_stmt.excluded.data,
        "ingested_at": insert_stmt.excluded.ingested_at,
    },
)
```

**Done criteria:**
- Migration runs: `alembic upgrade head` succeeds, `alembic downgrade 002` succeeds.
- `_upsert_section()` called twice with the same `(instrument_id, period_type, period_end_date)`
  produces exactly one DB row (verified by integration test).
- No existing `id`-based conflict path remains in fundamentals_repo.

---

### FIX-F2 + FIX-F3 🔴🟠 — `PeriodType.SNAPSHOT`; decompose financial statements into per-period rows

**Root cause confirmed:**

In `fundamentals_consumer.py`, lines 234–244, every section — regardless of type — is stored
with `period_end=ingested_at` and `period_type=PeriodType.ANNUAL`. This means:
- Quarterly financial data is mislabeled as `ANNUAL`.
- All 13 sections carry `period_end = now()` rather than the actual fiscal period end date.
- Financial time-series data (income statement, balance sheet, etc.) is stored as a single
  row containing the entire dict of all periods, rather than one row per fiscal period.

EODHD`Financials.Income_Statement` shape:
```json
{
  "currency_symbol": "USD",
  "quarterly": {
    "2024-09-30": {"date": "2024-09-30", "totalRevenue": "94930000000", ...},
    "2024-06-30": {"date": "2024-06-30", "totalRevenue": "85777000000", ...}
  },
  "yearly": {
    "2023-12-31": {"date": "2023-12-31", "totalRevenue": "383285000000", ...}
  }
}
```

**Step 1 — Add `PeriodType.SNAPSHOT` in `services/market-data/src/market_data/domain/enums.py`:**

```python
class PeriodType(str, Enum):
    ANNUAL    = "annual"
    QUARTERLY = "quarterly"
    SNAPSHOT  = "snapshot"   # point-in-time sections with no fiscal period (added FIX-F2)
```

**Step 2 — Replace the monolithic record-creation block in `fundamentals_consumer.py`:**

Add these module-level constants:

```python
# Sections whose EODHD payload is {"quarterly": {date: row}, "yearly": {date: row}}
_FINANCIAL_STATEMENT_SECTIONS: frozenset[str] = frozenset({
    "income_statement",
    "balance_sheet",
    "cash_flow",
})

# Sections whose payload is a dict-of-dicts keyed by period code (0q, +1q, 0y, +1y …)
# with an explicit "date" field inside each entry
_EARNINGS_TREND_SECTIONS: frozenset[str] = frozenset({
    "earnings_trend",
})

# Sections whose payload is a date-keyed flat dict → one row per date entry
_DATE_KEYED_SERIES_SECTIONS: frozenset[str] = frozenset({
    "earnings_history",
    "earnings_annual_trend",
    "outstanding_shares",
})
```

Replace the inner `for section_key, handler_name in _SECTION_HANDLERS.items()` block:

```python
for section_key, handler_name in _SECTION_HANDLERS.items():
    section_data = payload.get(section_key)
    if section_data is None:
        continue

    section_enum = _SECTION_ENUM_MAP[section_key]
    handler = getattr(uow.fundamentals, handler_name)

    # ── financial statement sections: one row per fiscal period ──────────────
    if section_key in _FINANCIAL_STATEMENT_SECTIONS and isinstance(section_data, dict):
        for period_label, period_type_enum in (
            ("quarterly", PeriodType.QUARTERLY),
            ("yearly",    PeriodType.ANNUAL),
        ):
            sub: dict = section_data.get(period_label) or {}
            for date_str, row_data in sub.items():
                try:
                    period_end = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    logger.warning(
                        "fundamentals_consumer.skip_bad_date",
                        section=section_key,
                        date_str=date_str,
                    )
                    continue
                record = FundamentalsRecord(
                    security_id=instrument_id,
                    section=section_enum,
                    period_end=period_end,
                    period_type=period_type_enum,
                    data=row_data if isinstance(row_data, dict) else {"value": row_data},
                    source=provider_str,
                    ingested_at=ingested_at,
                )
                await handler(record)

    # ── earnings trend: period-code-keyed dict with explicit "date" field ────
    elif section_key in _EARNINGS_TREND_SECTIONS and isinstance(section_data, dict):
        for _period_code, entry in section_data.items():
            if not isinstance(entry, dict):
                continue
            date_str = entry.get("date") or ""
            try:
                period_end = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
            except (ValueError, TypeError):
                period_end = ingested_at  # trend entries sometimes lack a date
            record = FundamentalsRecord(
                security_id=instrument_id,
                section=section_enum,
                period_end=period_end,
                period_type=PeriodType.QUARTERLY,
                data=entry,
                source=provider_str,
                ingested_at=ingested_at,
            )
            await handler(record)

    # ── date-keyed flat series: one row per date key ──────────────────────────
    elif section_key in _DATE_KEYED_SERIES_SECTIONS and isinstance(section_data, dict):
        for date_str, row_data in section_data.items():
            try:
                period_end = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue
            period_type_enum = (
                PeriodType.QUARTERLY
                if section_key == "earnings_history"
                else PeriodType.ANNUAL
            )
            record = FundamentalsRecord(
                security_id=instrument_id,
                section=section_enum,
                period_end=period_end,
                period_type=period_type_enum,
                data=row_data if isinstance(row_data, dict) else {"value": row_data},
                source=provider_str,
                ingested_at=ingested_at,
            )
            await handler(record)

    # ── snapshot sections: single row, period_end = ingested_at ──────────────
    else:
        record = FundamentalsRecord(
            security_id=instrument_id,
            section=section_enum,
            period_end=ingested_at,
            period_type=PeriodType.SNAPSHOT,
            data=section_data if isinstance(section_data, dict) else {"value": section_data},
            source=provider_str,
            ingested_at=ingested_at,
        )
        await handler(record)
```

**Done criteria:**
- `income_statements` table contains one row per fiscal quarter and one per fiscal year for
  each instrument, not one row for the entire dict.
- `period_type` is `"quarterly"` for `2024-09-30` income statement rows and `"annual"` for
  `"2023-12-31"` rows.
- `valuation_ratios`, `technicals_snapshots`, `splits_dividends`, `analyst_consensus`,
  `dividend_history` all have `period_type = "snapshot"`.
- No `PeriodType.ANNUAL` value appears in snapshot-section rows.
- Unit test: feed a fixture with a 3-entry `quarterly` and 2-entry `yearly` income statement
  payload → assert 5 `FundamentalsRecord` objects emitted.

---

### FIX-F4 🟠 — Extract `General` section → populate `instruments` + new `company_profiles` table

**Root cause confirmed:**

`_map_fundamentals_sections()` in `execute_task.py` never calls `raw.get("General")`.
As a result, `instruments.name`, `instruments.isin`, sector, industry, country, currency
fields are never populated, and rich company metadata (description, IPO date, officers,
CIK, CUSIP, LEI, is_delisted) has nowhere to go.

**Step 1 — Add `company_profile` to the mapper (`execute_task.py`):**

```python
def _map_fundamentals_sections(raw: dict, symbol: str, source: str) -> dict:
    ...
    _add("company_profile", raw.get("General"))   # ← add this line
    ...
    return sections
```

**Step 2 — Add `"company_profile"` to consumer dispatch tables
(`fundamentals_consumer.py`):**

```python
_SECTION_HANDLERS: dict[str, str] = {
    ...
    "company_profile": "upsert_company_profile",   # ← new
}

_SECTION_ENUM_MAP: dict[str, FundamentalsSection] = {
    ...
    "company_profile": FundamentalsSection.COMPANY_PROFILE,   # ← new
}
```

**Step 3 — After the section loop, extract structured fields into `instruments`:**

```python
# fundamentals_consumer.py — after the section dispatch loop
general = payload.get("company_profile") or {}
if general:
    await uow.instruments.update_metadata(
        instrument_id,
        {
            "isin":          general.get("ISIN"),
            "name":          general.get("Name"),
            "sector":        general.get("Sector"),
            "industry":      general.get("Industry"),
            "country":       general.get("CountryISO"),
            "currency_code": general.get("CurrencyCode"),
        },
    )
```

`InstrumentRepository.update_metadata()` must be added if absent — it performs an
`UPDATE instruments SET ... WHERE id = :id` ignoring `None`-valued keys.

**Step 4 — New `company_profiles` migration in market-data:**

```sql
-- Include in migration 004_company_profiles.py
CREATE TABLE company_profiles (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id           UUID        NOT NULL
                            REFERENCES instruments(id) ON DELETE CASCADE,
    description             TEXT,
    full_time_employees     INTEGER,
    ipo_date                DATE,
    fiscal_year_end         VARCHAR(20),
    -- Cross-reference IDs
    cik                     VARCHAR(30),
    cusip                   VARCHAR(20),
    lei                     VARCHAR(30),
    open_figi               VARCHAR(30),
    is_delisted             BOOLEAN     NOT NULL DEFAULT FALSE,
    -- Rich nested objects stored as JSONB
    officers                JSONB,    -- [{name, title, yearBorn}]
    listings                JSONB,    -- [{exchange, code, country}]
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_company_profiles_instrument UNIQUE (instrument_id)
);
CREATE INDEX ix_company_profiles_instrument ON company_profiles (instrument_id);
```

**Step 5 — Add `FundamentalsSection.COMPANY_PROFILE` to domain enum
(`services/market-data/src/market_data/domain/enums.py`).**

**Step 6 — Add ORM model `CompanyProfileModel` following the existing
`FundamentalsModelMixin` pattern, then wire a `upsert_company_profile()` repo method.**
Note: `company_profiles` uses a different conflict target (`instrument_id` alone, not the
triple natural key) because there is exactly one profile per instrument.

**Done criteria:**
- After ingesting AAPL fundamentals, `instruments.name = "Apple Inc"` and
  `instruments.sector = "Technology"`.
- `company_profiles` row exists for AAPL with `description`, `cik`, `ipo_date` populated.
- `company_profile` section stored in `company_profiles` table with `upsert` semantics
  (conflict on `instrument_id`).

---

### FIX-F5 🟠 — Fix `dividend_history` key in mapper

**Root cause confirmed:**

`_map_fundamentals_sections()` calls `splits_divs.get("Dividends")`. This key does **not**
exist in EODHD `SplitsDividends`. The correct key is `NumberDividendsByYear`.

```python
# execute_task.py  _map_fundamentals_sections()  — BEFORE (broken)
_add("dividend_history", splits_divs.get("Dividends"))

# AFTER (correct)
_add("dividend_history", splits_divs.get("NumberDividendsByYear"))
```

`NumberDividendsByYear` is a dict keyed by year string (`"2023"`, `"2024"`) with integer
values (count of dividends paid that year). This fits the `_DATE_KEYED_SERIES_SECTIONS`
dispatching added in FIX-F2 — each year key maps to one row. Because year strings
(`"2024"`) are not ISO-8601 date strings, add a fallback in the consumer:

```python
# In the _DATE_KEYED_SERIES_SECTIONS branch of process_message()
try:
    period_end = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
except (ValueError, TypeError):
    # Year-only strings like "2024" — treat as year-end
    try:
        period_end = datetime(int(date_str), 12, 31, tzinfo=UTC)
    except (ValueError, TypeError):
        continue
```

**Done criteria:**
- `dividend_history` table is populated with non-null rows after a fundamentals ingest.
- Year-only keys (`"2023"`) produce `period_end = 2023-12-31T00:00:00Z`.

---

### FIX-F6 🟡 — Extract `Holders` (institutional + fund) from fundamentals

**Step 1 — Add mapper entries (`execute_task.py`):**

```python
_add("institutional_holders", (raw.get("Holders") or {}).get("Institutions"))
_add("fund_holders",          (raw.get("Holders") or {}).get("Funds"))
```

**Step 2 — Add to consumer `_SECTION_HANDLERS` / `_SECTION_ENUM_MAP`:**

```python
"institutional_holders": "upsert_institutional_holders",
"fund_holders":          "upsert_fund_holders",
```

**Step 3 — New tables (add to migration `004`):**

```sql
CREATE TABLE institutional_holders (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id  UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    period_type    VARCHAR(20) NOT NULL,
    period_end_date TIMESTAMPTZ NOT NULL,
    data           JSONB NOT NULL,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_institutional_holders_natural
      UNIQUE (instrument_id, period_type, period_end_date)
);

CREATE TABLE fund_holders (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id  UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    period_type    VARCHAR(20) NOT NULL,
    period_end_date TIMESTAMPTZ NOT NULL,
    data           JSONB NOT NULL,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fund_holders_natural
      UNIQUE (instrument_id, period_type, period_end_date)
);
```

`Holders.Institutions` and `Holders.Funds` are flat arrays (not date-keyed dicts), so they
dispatch as **snapshot** sections — `period_end = ingested_at`, `period_type = SNAPSHOT`.

**Done criteria:**
- `institutional_holders` row exists for AAPL after fundamentals ingest.
- `FundamentalsSection.INSTITUTIONAL_HOLDERS` and `FundamentalsSection.FUND_HOLDERS` added.

---

### FIX-F7 🟡 — Extract embedded `InsiderTransactions` from fundamentals

The EODHD fundamentals response contains an `InsiderTransactions` top-level key (embedded
Form 4 data). This should be extracted as a snapshot section — the standalone
`/insider-transactions` endpoint (EXT-06) provides the complete historical set; the embedded
version is a recent snapshot.

```python
# execute_task.py
_add("insider_transactions_snapshot", raw.get("InsiderTransactions"))
```

Add corresponding entries to `_SECTION_HANDLERS` / `_SECTION_ENUM_MAP`.
Reuse the `insider_transactions` table added by EXT-06 if that task runs first;
otherwise create a `insider_transactions_snapshot` table following the standard mixin.

---

### FIX-F8 🟡 — Resolve dead `dividend_summary` table

The `dividend_summary` table was created in `001_initial_schema.py` but has no writer.
`FundamentalsSection` has no `DIVIDEND_SUMMARY` member. This is dead schema.

**Decision**: drop the table in migration `004`. The `dividend_history` table (fixed by
FIX-F5) and the `splits_dividends` JSONB section together cover all dividend data.

```python
# migration 004_company_profiles.py  — add to upgrade()
op.drop_table("dividend_summary")

# downgrade() — recreate it
op.create_table(
    "dividend_summary",
    sa.Column("id", postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("instrument_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False),
    sa.Column("period_type", sa.String(20), nullable=False),
    sa.Column("period_end_date", sa.DateTime(timezone=True), nullable=False),
    sa.Column("data", postgresql.JSONB, nullable=False),
    sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    sa.PrimaryKeyConstraint("id"),
)
```

---

### FIX-F9 🟡 — Validate per-period row granularity (integration test)

Write a unit test in `services/market-data/tests/unit/test_fundamentals_consumer.py`:

```python
async def test_financial_statement_decomposed_into_per_period_rows():
    """FIX-F9: income_statement payload with 3 quarterly + 2 yearly entries
    must produce 5 distinct FundamentalsRecord calls, not 1."""
    payload = {
        "income_statement": {
            "quarterly": {
                "2024-09-30": {"totalRevenue": "94930000000"},
                "2024-06-30": {"totalRevenue": "85777000000"},
                "2024-03-31": {"totalRevenue": "90753000000"},
            },
            "yearly": {
                "2023-12-31": {"totalRevenue": "383285000000"},
                "2022-12-31": {"totalRevenue": "394328000000"},
            },
        }
    }
    records = await collect_fundamentals_records(payload)
    assert len(records) == 5
    quarterly = [r for r in records if r.period_type == PeriodType.QUARTERLY]
    annual    = [r for r in records if r.period_type == PeriodType.ANNUAL]
    assert len(quarterly) == 3
    assert len(annual)    == 2
```

---

### FIX-F10 🟡 — Split `Highlights` + `Valuation` into separate sections

**Root cause:** `_map_fundamentals_sections()` merges `Highlights` (TTM operational
metrics: revenue, EBITDA, EPS, ROE, ROA) with `Valuation` (price multiples: P/E,
P/B, P/S, EV/EBITDA) into a single `valuation_ratios` section. These are semantically
different datasets.

```python
# execute_task.py  _map_fundamentals_sections()  — BEFORE
highlights = raw.get("Highlights") or {}
valuation  = raw.get("Valuation")  or {}
valuation_ratios = {**highlights, **valuation} or None
...
_add("valuation_ratios", valuation_ratios)

# AFTER
_add("highlights",       raw.get("Highlights"))
_add("valuation_ratios", raw.get("Valuation"))
```

Add `"highlights": "upsert_highlights"` to `_SECTION_HANDLERS` / `_SECTION_ENUM_MAP`.

New table in migration `004`:

```sql
CREATE TABLE highlights (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id   UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    period_type     VARCHAR(20) NOT NULL,
    period_end_date TIMESTAMPTZ NOT NULL,
    data            JSONB NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_highlights_natural
      UNIQUE (instrument_id, period_type, period_end_date)
);
```

`valuation_ratios` table continues to exist and now receives only the `Valuation`
sub-object (price multiples). Run a data migration to split any existing merged rows if
the service has already been deployed with the old mapper.

---

### FIX-O1 🟡 — Python 3.10-compatible datetime parsing for intraday OHLCV

**Root cause:** EODHD intraday endpoint returns `"datetime": "2021-08-02 13:30:00"` (space
separator). `datetime.fromisoformat()` accepts space-separated strings only in Python ≥3.11.
Python 3.10 raises `ValueError`.

**Fix in `libs/contracts/src/contracts/canonical/ohlcv.py`:**

```python
# CanonicalOHLCVBar.from_dict()  — BEFORE
bar_date = datetime.fromisoformat(d["date"])

# AFTER — normalise separator before parsing (compatible with 3.10 and 3.11+)
raw_date_str = str(d.get("date") or d.get("datetime", "")).replace(" ", "T")
bar_date = datetime.fromisoformat(raw_date_str)
```

Note: EODHD EOD uses key `"date"`, intraday uses key `"datetime"`. The `d.get("date") or
d.get("datetime", "")` fallback handles both.

---

### FIX-O2 🟡 — Document `adjusted_close = None` for intraday bars

In `ohlcv_consumer.py` and `canonical/ohlcv.py`, add a code comment:

```python
# adjusted_close: populated only for EOD bars from EODHD (/eod/ endpoint).
# Intraday bars (/intraday/ endpoint) return no adjusted price — stored as None.
# This is expected behaviour, not a data quality issue.
```

Update `docs/services/market-data.md` under the OHLCV consumer section.

---

### FIX-Q1 🟡 — Log warning on zero-price quote

**In `execute_task.py` → `_remap_quote()`:**

```python
last = raw.get("last") or raw.get("close", 0.0)

if not last:
    # Log — do not raise; data may be legitimately halted
    logger.warning(
        "quote_zero_or_missing_price",
        symbol=symbol,
        exchange=exchange,
        raw_keys=list(raw.keys()),
    )
    last = 0.0
```

---

## Implementation instructions — Part B

---

### EXT-01 — Intraday OHLCV

**Endpoint:**
```
GET /api/intraday/{TICKER}?interval=1m|5m|1h&from=UNIX_EPOCH&to=UNIX_EPOCH
    &api_token=...&fmt=json
```
- `interval`: `1m` (history limited to 2 years), `5m` and `1h` (unlimited)
- Cost: **5 API credits per call**
- Returns: JSON array of `{datetime, open, high, low, close, volume}` objects
  (key is `datetime`, not `date` — handled by FIX-O1)

**DatasetType:** Reuse `DatasetType.OHLCV`. Differentiate intraday from EOD purely
via `task.timeframe` (`"1m"`, `"5m"`, `"1h"` vs `"1d"`, `"1w"`, `"1mo"`).

**New adapter method in `eodhd.py`:**

```python
async def fetch_intraday(
    self,
    ticker: str,
    interval: str,
    from_ts: int | None = None,
    to_ts: int | None = None,
) -> ProviderFetchResult:
    """Fetch intraday OHLCV bars.  interval ∈ {"1m", "5m", "1h"}."""
    params: dict[str, Any] = {
        "interval": self._INTRADAY_INTERVAL_MAP.get(interval, interval),
        "fmt": "json",
        "api_token": self._token,
    }
    if from_ts is not None:
        params["from"] = from_ts
    if to_ts is not None:
        params["to"] = to_ts
    url = f"{self._base}/intraday/{ticker}"
    return await self._get(url, params)

_INTRADAY_INTERVAL_MAP = {"1m": "1m", "5m": "5m", "1h": "1h"}
```

**Changes to `_fetch()` in `execute_task.py`:**

```python
if task.dataset_type == DatasetType.OHLCV:
    if task.timeframe in {"1m", "5m", "1h"}:
        return await adapter.fetch_intraday(
            task.symbol,
            interval=task.timeframe,
        )
    return await adapter.fetch_ohlcv(
        task.symbol,
        period=self._TIMEFRAME_MAP.get(task.timeframe, "d"),
        ...
    )
```

**Canonical model:** `CanonicalOHLCVBar` — no change needed. FIX-O1 must be applied first.

**DB table:** `ohlcv_bars` already has the correct composite PK
`(instrument_id, timeframe, bar_date)` — no new migration required.

**New polling policy seed rows (in market-ingestion `0003_seed_intraday_policies.py`):**

```python
# 1-hour bars — 6 symbols, run every 3600s
for symbol, exchange in [("AAPL", "US"), ("TSLA", "US"), ("AMZN", "US"),
                          ("BTC-USD", "CC"), ("EURUSD", "FOREX")]:
    insert_policy(symbol=f"{symbol}.{exchange}", dataset_type="ohlcv",
                  timeframe="1h", base_interval_seconds=3600)

# 5-min bars — premium symbols only
for symbol in ["AAPL.US", "TSLA.US"]:
    insert_policy(symbol=symbol, dataset_type="ohlcv",
                  timeframe="5m", base_interval_seconds=300)
```

---

### EXT-02 — Earnings Calendar

**Endpoint:**
```
GET /api/calendar/earnings?from=YYYY-MM-DD&to=YYYY-MM-DD
    &symbols=AAPL.US,TSLA.US&api_token=...&fmt=json
```
- Returns upcoming **and** historical earnings report dates
- Response fields: `code`, `report_date`, `date` (fiscal quarter end), `before_after_market`,
  `currency`, `actual`, `estimate`, `difference`, `percent`
- Cost: **1 API credit per call** (bulk — not per-symbol)

**New `DatasetType`:**
```python
EARNINGS_CALENDAR = "earnings_calendar"
```

**New `fetch_earnings_calendar()` in `eodhd.py`:**

```python
async def fetch_earnings_calendar(
    self,
    from_date: str,
    to_date: str,
    symbols: list[str] | None = None,
) -> ProviderFetchResult:
    params = {"from": from_date, "to": to_date, "fmt": "json", "api_token": self._token}
    if symbols:
        params["symbols"] = ",".join(symbols)
    return await self._get(f"{self._base}/calendar/earnings", params)
```

**New canonical model `libs/contracts/src/contracts/canonical/earnings_calendar.py`:**

```python
@dataclass(frozen=True)
class CanonicalEarningsEvent:
    symbol:              str
    report_date:         str        # YYYY-MM-DD — the date the report is/was released
    fiscal_date_ending:  str        # YYYY-MM-DD — the quarter/year end date
    before_after_market: str        # "BeforeMarket" | "AfterMarket" | ""
    currency:            str
    eps_estimate:        float | None
    eps_actual:          float | None
    source:              str
    fetched_at:          str

    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalEarningsEvent":
        return cls(
            symbol=d["code"],
            report_date=d.get("report_date") or d.get("date", ""),
            fiscal_date_ending=d.get("date", ""),
            before_after_market=d.get("before_after_market") or "",
            currency=d.get("currency") or "",
            eps_estimate=_to_float(d.get("estimate")),
            eps_actual=_to_float(d.get("actual")),
            source=d.get("source", "eodhd"),
            fetched_at=d.get("fetched_at", ""),
        )
```

**New DB table (market-data migration `005_earnings_calendar.py`):**

```sql
CREATE TABLE earnings_calendar (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id   UUID        NOT NULL
                    REFERENCES instruments(id) ON DELETE CASCADE,
    report_date     DATE        NOT NULL,
    fiscal_date     DATE,
    eps_estimate    NUMERIC(18, 4),
    eps_actual      NUMERIC(18, 4),
    before_after    VARCHAR(20),
    currency        VARCHAR(10),
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_earnings_calendar UNIQUE (instrument_id, report_date)
);
CREATE INDEX ix_earnings_calendar_report_date ON earnings_calendar (report_date);
CREATE INDEX ix_earnings_calendar_instrument ON earnings_calendar (instrument_id);
```

**New polling policy seed:** One shared task (`symbol = "CALENDAR.EARNINGS"`) at 86400s
interval. `_fetch()` maps this synthetic symbol to `fetch_earnings_calendar()` with a
`+/−14d` window around today.

---

### EXT-03 — Economic Events

**Endpoint:**
```
GET /api/economic-events?from=YYYY-MM-DD&to=YYYY-MM-DD&country=USA
    &comparison=mom|yoy|q2q&api_token=...&fmt=json
```
- CPI, NFP, FOMC decisions, PMI, retail sales, GDP flash estimates, trade balance, etc.
- Cost: **1 API credit per call**

**New `DatasetType`:**
```python
ECONOMIC_EVENTS = "economic_events"
```

**New `fetch_economic_events()` in `eodhd.py`:**

```python
async def fetch_economic_events(
    self,
    from_date: str,
    to_date: str,
    country: str = "USA",
    comparison: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> ProviderFetchResult:
    params = {
        "from": from_date, "to": to_date, "country": country,
        "limit": limit, "offset": offset,
        "fmt": "json", "api_token": self._token,
    }
    if comparison:
        params["comparison"] = comparison
    return await self._get(f"{self._base}/economic-events", params)
```

**New DB table (migration `005`):**

```sql
CREATE TABLE economic_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      VARCHAR(200) NOT NULL,
    country         VARCHAR(10)  NOT NULL,
    event_date      DATE         NOT NULL,
    actual          NUMERIC(18, 6),
    estimate        NUMERIC(18, 6),
    previous        NUMERIC(18, 6),
    change_value    NUMERIC(18, 6),
    change_pct      NUMERIC(10, 6),
    impact          VARCHAR(20),           -- "High" | "Medium" | "Low"
    unit            VARCHAR(50),
    currency        VARCHAR(10),
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_economic_events UNIQUE (event_type, country, event_date)
);
CREATE INDEX ix_economic_events_date    ON economic_events (event_date);
CREATE INDEX ix_economic_events_country ON economic_events (country, event_date);
```

**Polling policy seed:** One task per tracked country (`"EVENTS.USA"`, `"EVENTS.EUR"`,
`"EVENTS.GBR"`) at 86400s interval.

---

### EXT-04 — Macro Indicators

**Endpoint:**
```
GET /api/macro-indicator/{COUNTRY_ISO3}?indicator=gdp_current_usd
    &fmt=json&api_token=...
```
- ~100+ indicators: `gdp_current_usd`, `inflation_consumer_prices_annual`,
  `unemployment_total_pct`, `current_account_balance_bop_usd`,
  `real_interest_rate`, `population_total`, etc.
- Response: JSON array of `{date, value}` objects (annual frequency typical)
- Cost: **1 API credit per (country, indicator) call**

**New `DatasetType`:**
```python
MACRO_INDICATOR = "macro_indicator"
```

**Symbol convention:** `task.symbol` encodes both dimensions as `"USA.inflation_consumer_prices_annual"`.
`fetch_macro_indicator()` splits on the first `.`:

```python
async def fetch_macro_indicator(self, symbol: str) -> ProviderFetchResult:
    country, indicator = symbol.split(".", 1)
    return await self._get(
        f"{self._base}/macro-indicator/{country}",
        {"indicator": indicator, "fmt": "json", "api_token": self._token},
    )
```

**New DB table (migration `005`):**

```sql
CREATE TABLE macro_indicators (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    country      VARCHAR(10)  NOT NULL,
    indicator    VARCHAR(100) NOT NULL,
    period_date  DATE         NOT NULL,
    value        NUMERIC(24, 8),
    ingested_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_macro_indicators UNIQUE (country, indicator, period_date)
);
CREATE INDEX ix_macro_indicators_country_indicator
    ON macro_indicators (country, indicator, period_date DESC);
```

**Polling policy seeds (one row per (country, indicator) combination):**
Start with a representative set: `USA.gdp_current_usd`, `USA.inflation_consumer_prices_annual`,
`USA.unemployment_total_pct`, `EUR.gdp_current_usd`, `EUR.inflation_consumer_prices_annual`
— all at 604800s (weekly) interval.

---

### EXT-05 — News + Daily Sentiment Aggregation

**Endpoint:**
```
GET /api/news?s=AAPL.US&from=YYYY-MM-DD&to=YYYY-MM-DD
    &limit=50&offset=0&api_token=...&fmt=json
```
- Returns article title, url, date, tickers array, and inline sentiment:
  `{polarity, neg, neu, pos}` (pre-computed by EODHD NLP)
- Cost: **5 credits base + 5 per ticker** per call

**New `DatasetType`:**
```python
NEWS_SENTIMENT = "news_sentiment"
```

**Architecture note:** Full article metadata (title, url, body snippet) belongs in the
`content-ingestion` service. The `market-data` service stores only the **aggregated daily
sentiment signal** — one row per (instrument, date). The `_canonicalize()` step must:
1. Group articles by date.
2. Compute mean `polarity`, `pos`, `neu`, `neg` across articles for that day.
3. Produce `CanonicalDailySentiment` objects (see below).
4. Emit a separate outbox event `market.news.fetched` for `content-ingestion` to consume.

**New canonical model `libs/contracts/src/contracts/canonical/sentiment.py`:**

```python
@dataclass(frozen=True)
class CanonicalDailySentiment:
    symbol:          str
    exchange:        str
    date:            str           # YYYY-MM-DD
    polarity_mean:   float         # mean across articles that day (-1..1)
    pos_mean:        float
    neu_mean:        float
    neg_mean:        float
    article_count:   int
    source:          str
    fetched_at:      str
```

**New DB table (market-data migration `005`):**

```sql
CREATE TABLE daily_sentiments (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id   UUID        NOT NULL
                    REFERENCES instruments(id) ON DELETE CASCADE,
    date            DATE        NOT NULL,
    polarity_mean   NUMERIC(6, 4),
    pos_mean        NUMERIC(6, 4),
    neu_mean        NUMERIC(6, 4),
    neg_mean        NUMERIC(6, 4),
    article_count   INTEGER     NOT NULL DEFAULT 0,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_daily_sentiments UNIQUE (instrument_id, date)
);
CREATE INDEX ix_daily_sentiments_instrument_date
    ON daily_sentiments (instrument_id, date DESC);
```

**Polling policy seed:** One task per tracked symbol at 21600s (6-hour) interval.

---

### EXT-06 — Insider Transactions (standalone endpoint)

**Endpoint:**
```
GET /api/insider-transactions?code=AAPL.US
    &from=YYYY-MM-DD&to=YYYY-MM-DD&limit=100&api_token=...&fmt=json
```
- Form 4 filings: owner name, title, transaction date, transaction code
  (`P`=Purchase, `S`=Sale, `A`=Award, `D`=Disposition), shares, price per share,
  acquired/disposed flag, total shares owned after transaction
- Cost: **1 API credit per ticker**

**New `DatasetType`:**
```python
INSIDER_TRANSACTIONS = "insider_transactions"
```

**New `fetch_insider_transactions()` in `eodhd.py`:**

```python
async def fetch_insider_transactions(
    self,
    ticker: str,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
) -> ProviderFetchResult:
    params = {"code": ticker, "limit": limit, "fmt": "json", "api_token": self._token}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return await self._get(f"{self._base}/insider-transactions", params)
```

**New canonical model `libs/contracts/src/contracts/canonical/insider_transactions.py`:**

```python
@dataclass(frozen=True)
class CanonicalInsiderTransaction:
    symbol:              str
    exchange:            str
    owner_name:          str
    owner_title:         str
    transaction_date:    str        # YYYY-MM-DD
    transaction_code:    str        # "P" | "S" | "A" | "D" | etc.
    shares:              float | None
    price_per_share:     float | None
    acquired_disposed:   str        # "A" | "D"
    total_shares_owned:  float | None
    source:              str
    fetched_at:          str
```

**New DB table (market-data migration `005`):**

```sql
CREATE TABLE insider_transactions (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id       UUID        NOT NULL
                        REFERENCES instruments(id) ON DELETE CASCADE,
    owner_name          VARCHAR(300) NOT NULL,
    owner_title         VARCHAR(300),
    transaction_date    DATE         NOT NULL,
    transaction_code    VARCHAR(5),
    shares              NUMERIC(18, 2),
    price_per_share     NUMERIC(18, 4),
    acquired_disposed   VARCHAR(1),
    total_shares_owned  NUMERIC(18, 2),
    ingested_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_insider_transactions
      UNIQUE (instrument_id, owner_name, transaction_date, transaction_code, shares)
);
CREATE INDEX ix_insider_tx_instrument_date
    ON insider_transactions (instrument_id, transaction_date DESC);
```

**Polling policy seed:** One task per tracked equity symbol at 86400s interval.

---

### EXT-07 — US Treasury Yield Curve

**Endpoints (three separate series):**

```
GET /api/ust/yield-rates?from=YYYY-MM-DD&to=YYYY-MM-DD&api_token=...    # 1M – 10Y
GET /api/ust/bill-rates?from=...&to=...&api_token=...                    # 4W 8W 13W 26W 52W
GET /api/ust/long-term-rates?from=...&to=...&api_token=...               # 20Y 30Y
```
- Cost: **1 API credit per call** (not per maturity)
- Response: JSON array of `{date, "1_month": val, "3_month": val, ...}` objects

**New `DatasetType`:**
```python
YIELD_CURVE = "yield_curve"
```

**Symbol convention:** `"UST.yield"`, `"UST.bill"`, `"UST.longterm"` — one task per series.

**New `fetch_yield_curve()` in `eodhd.py`:**

```python
_YIELD_SERIES_MAP = {
    "UST.yield":    "ust/yield-rates",
    "UST.bill":     "ust/bill-rates",
    "UST.longterm": "ust/long-term-rates",
}

async def fetch_yield_curve(
    self,
    series_symbol: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> ProviderFetchResult:
    path = self._YIELD_SERIES_MAP.get(series_symbol)
    if path is None:
        raise ProviderDataError(f"Unknown yield curve series: {series_symbol}")
    params = {"fmt": "json", "api_token": self._token}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return await self._get(f"{self._base}/{path}", params)
```

**`_canonicalize()` for yield curve:** Pivot each date row's maturity fields into one
`CanonicalYieldPoint` per maturity, emitting NDJSON:

```python
for row in raw_list:
    date_str = row["date"]
    for maturity_key, rate_val in row.items():
        if maturity_key == "date":
            continue
        yield CanonicalYieldPoint(
            series=series_label,
            date=date_str,
            maturity=maturity_key,   # "1_month", "10_year", etc.
            rate=float(rate_val) if rate_val is not None else None,
            source="eodhd",
            fetched_at=now_iso,
        )
```

**New DB table (market-data migration `005`):**

```sql
CREATE TABLE yield_curve (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    series      VARCHAR(20) NOT NULL,   -- "yield" | "bill" | "longterm"
    date        DATE        NOT NULL,
    maturity    VARCHAR(15) NOT NULL,   -- "1_month" | "3_month" | "10_year" | "30_year" etc.
    rate        NUMERIC(8, 4),          -- percent, e.g. 4.2350
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_yield_curve UNIQUE (series, date, maturity)
);
CREATE INDEX ix_yield_curve_date ON yield_curve (date DESC);
CREATE INDEX ix_yield_curve_series ON yield_curve (series, maturity, date DESC);
```

**Polling policy seed:** Three tasks (`UST.yield`, `UST.bill`, `UST.longterm`) at 86400s.

---

### EXT-08 — Historical Market Cap

**Endpoint:**
```
GET /api/historical-market-cap/{SYMBOL}?from=YYYY-MM-DD&to=YYYY-MM-DD
    &api_token=...&fmt=json
```
- US equities only; typically weekly granularity
- Response: JSON array of `{date, value}` — `value` is USD market cap
- Cost: **10 API credits per call** — most expensive per-symbol endpoint

**New `DatasetType`:**
```python
MARKET_CAP = "market_cap"
```

**New `fetch_historical_market_cap()` in `eodhd.py`:**

```python
async def fetch_historical_market_cap(
    self,
    ticker: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> ProviderFetchResult:
    params = {"fmt": "json", "api_token": self._token}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return await self._get(f"{self._base}/historical-market-cap/{ticker}", params)
```

**New canonical model** `CanonicalMarketCapPoint`:

```python
@dataclass(frozen=True)
class CanonicalMarketCapPoint:
    symbol:     str
    exchange:   str
    date:       str       # YYYY-MM-DD
    value_usd:  float
    source:     str
    fetched_at: str
```

**New DB table (market-data migration `005`):**

```sql
CREATE TABLE market_cap_history (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id  UUID        NOT NULL
                   REFERENCES instruments(id) ON DELETE CASCADE,
    date           DATE        NOT NULL,
    value_usd      NUMERIC(24, 2),
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_market_cap_history UNIQUE (instrument_id, date)
);
CREATE INDEX ix_market_cap_history_instrument_date
    ON market_cap_history (instrument_id, date DESC);
```

**Budget guardrail:** At 10 credits/call and 100,000 daily budget, limit to ≤50 symbols
polled per day. Polling policy base interval must be ≥604800s (weekly). Add a
`dataset_type = "market_cap"` filter in `ProviderBudget` enforcement so the scheduler
enforces the cap independently of other dataset types.

**Polling policy seed:** 6 equity symbols at 604800s (weekly) interval.

---

## Migration consolidation summary

All new tables belong in **two new Alembic migrations** in `services/market-data/`:

| Migration file | Revision | Contents |
|----------------|----------|----------|
| `003_fundamentals_unique_constraints.py` | `003` | UNIQUE constraints + indexes on all 13 existing fundamentals tables |
| `004_fundamentals_extensions.py` | `004` | `company_profiles`, `institutional_holders`, `fund_holders`, `highlights` tables; DROP `dividend_summary` |
| `005_new_dataset_tables.py` | `005` | `earnings_calendar`, `economic_events`, `macro_indicators`, `daily_sentiments`, `insider_transactions`, `yield_curve`, `market_cap_history` |

All three must chain correctly: `003 → 004 → 005`. Each must have a working `downgrade()`.

---

## `DatasetType` enum — complete final state

After all tasks, `services/market-ingestion/src/market_ingestion/domain/enums.py`:

```python
class DatasetType(str, Enum):
    OHLCV                = "ohlcv"              # EOD + intraday (differentiated by timeframe)
    QUOTES               = "quotes"             # 15-min delayed real-time quote
    FUNDAMENTALS         = "fundamentals"       # Full company fundamentals (all sections)
    EARNINGS_CALENDAR    = "earnings_calendar"  # EXT-02
    ECONOMIC_EVENTS      = "economic_events"    # EXT-03
    MACRO_INDICATOR      = "macro_indicator"    # EXT-04
    NEWS_SENTIMENT       = "news_sentiment"     # EXT-05
    INSIDER_TRANSACTIONS = "insider_transactions"  # EXT-06
    YIELD_CURVE          = "yield_curve"        # EXT-07
    MARKET_CAP           = "market_cap"         # EXT-08
```

---

## Polling policy seed additions (market-ingestion)

Create `services/market-ingestion/alembic/versions/0003_seed_extended_policies.py`:

| DatasetType | Symbol / Key | Base interval (s) | Notes |
|-------------|-------------|-------------------|-------|
| `ohlcv` (1h intraday) | `AAPL.US`, `TSLA.US`, `AMZN.US`, `BTC-USD.CC`, `EURUSD.FOREX` | 3600 | timeframe=`1h` |
| `ohlcv` (5m intraday) | `AAPL.US`, `TSLA.US` | 300 | timeframe=`5m` |
| `earnings_calendar` | `CALENDAR.EARNINGS` | 86400 | synthetic symbol |
| `economic_events` | `EVENTS.USA`, `EVENTS.EUR`, `EVENTS.GBR` | 86400 | per country |
| `macro_indicator` | `USA.gdp_current_usd`, `USA.inflation_consumer_prices_annual`, `USA.unemployment_total_pct`, `EUR.gdp_current_usd`, `EUR.inflation_consumer_prices_annual` | 604800 | weekly |
| `news_sentiment` | `AAPL.US`, `TSLA.US`, `AMZN.US`, `BTC-USD.CC` | 21600 | 6-hour window |
| `insider_transactions` | `AAPL.US`, `TSLA.US`, `AMZN.US` | 86400 | |
| `yield_curve` | `UST.yield`, `UST.bill`, `UST.longterm` | 86400 | |
| `market_cap` | `AAPL.US`, `TSLA.US`, `AMZN.US`, `VTI.US`, `BRK-B.US` | 604800 | weekly; 10 credits/call |

---

## `FundamentalsSection` enum — complete final state

After FIX-F4, FIX-F6, FIX-F7, FIX-F10,
`services/market-data/src/market_data/domain/enums.py`:

```python
class FundamentalsSection(str, Enum):
    INCOME_STATEMENT       = "income_statement"
    BALANCE_SHEET          = "balance_sheet"
    CASH_FLOW              = "cash_flow"
    HIGHLIGHTS             = "highlights"           # FIX-F10: split from valuation_ratios
    VALUATION_RATIOS       = "valuation_ratios"     # FIX-F10: Valuation only
    TECHNICALS_SNAPSHOT    = "technicals_snapshot"
    SHARE_STATISTICS       = "share_statistics"
    SPLITS_DIVIDENDS       = "splits_dividends"
    ANALYST_CONSENSUS      = "analyst_consensus"
    EARNINGS_HISTORY       = "earnings_history"
    EARNINGS_TREND         = "earnings_trend"
    EARNINGS_ANNUAL_TREND  = "earnings_annual_trend"
    DIVIDEND_HISTORY       = "dividend_history"
    OUTSTANDING_SHARES     = "outstanding_shares"
    COMPANY_PROFILE        = "company_profile"      # FIX-F4
    INSTITUTIONAL_HOLDERS  = "institutional_holders"  # FIX-F6
    FUND_HOLDERS           = "fund_holders"           # FIX-F6
    INSIDER_TRANSACTIONS_SNAPSHOT = "insider_transactions_snapshot"  # FIX-F7
    # DIVIDEND_SUMMARY removed (FIX-F8 — table dropped)
```

---

## Regression guardrails (compounding, mandatory)

Before marking any task done, verify **all** of the following for that task:

1. **No naive datetimes.** Every `datetime` constructed in this wave must carry `tzinfo=UTC`.
   Search the modified files for `datetime(` and `datetime.now(` without `tz=` and fix.

2. **Upsert conflict target matches UNIQUE constraint.** After FIX-F1, every
   `on_conflict_do_update()` call in `fundamentals_repo.py` must reference
   `["instrument_id", "period_type", "period_end_date"]` — not `["id"]`.

3. **No unbounded inserts.** For any new `INSERT ... ON CONFLICT DO UPDATE` added in Part B,
   verify the conflict target columns are declared `UNIQUE` in the migration before wiring
   the repo method.

4. **Migration chain.** Run `alembic upgrade head && alembic downgrade base` in CI against
   a fresh PostgreSQL container. The round-trip must be clean.

5. **No new hardcoded `PeriodType.ANNUAL` in consumer.** After FIX-F3, `grep` the
   consumer for `PeriodType.ANNUAL` — the only permitted occurrence is inside the
   `_FINANCIAL_STATEMENT_SECTIONS` decomposition loop where `period_label == "yearly"`.

6. **Python 3.10 compatibility for all date parsing.** After FIX-O1, any `fromisoformat()`
   call on a string that might contain a space separator must have `.replace(" ", "T")`
   applied first.

7. **API credit budget.** Verify the sum of polling policy base intervals implies ≤100,000
   credits/day across all seeds. Compute: `sum(86400 / interval * credits_per_call)` for each
   policy. EXT-08 (market cap, 10 credits/call) must not be seeded for more than 50 symbols
   at weekly cadence.

8. **No dead enum members.** After FIX-F8, confirm `FundamentalsSection.DIVIDEND_SUMMARY`
   is removed and no code references it.

---

## Documentation updates (mandatory)

| Document | Required changes |
|----------|-----------------|
| `docs/services/market-data.md` | Add all 7 new DB tables and their schemas; update fundamentals section-to-table mapping; add `PeriodType.SNAPSHOT`; document `company_profiles` table and `update_metadata()` repo method |
| `docs/services/market-ingestion.md` | Add all 8 new `DatasetType` values; document `fetch_intraday()`, `fetch_earnings_calendar()`, `fetch_economic_events()`, `fetch_macro_indicator()`, `fetch_yield_curve()`, `fetch_historical_market_cap()`, `fetch_insider_transactions()`, `fetch_news_sentiment()`; add rate cost table |
| `docs/libs/contracts.md` | Document `CanonicalEarningsEvent`, `CanonicalDailySentiment`, `CanonicalInsiderTransaction`, `CanonicalYieldPoint`, `CanonicalMarketCapPoint`; update `CanonicalOHLCVBar.from_dict()` note on datetime key fallback |
| `docs/services/market-data.md` (Common Pitfalls) | Add: "Financial statement sections are blobs not rows — run migration 003 before deploying consumer fix"; "Snapshot sections use `period_end = ingested_at` — do not round-trip through the DB to reconstruct fiscal date" |

---

## Done criteria (wave complete when all pass)

- [ ] `alembic upgrade head` in a fresh DB applies all three migrations cleanly.
- [ ] `alembic downgrade base` after the above is clean.
- [ ] Integration test: ingest a fundamentals fixture for AAPL → `income_statements` has
      ≥4 rows (quarterly) and ≥2 rows (yearly); no `period_end` value equals `ingested_at`
      on any financial statement row.
- [ ] Integration test: ingest the same fixture twice → row counts are identical (upsert
      idempotency, not double-insert).
- [ ] `dividend_history` table has ≥1 non-null row for AAPL after ingest.
- [ ] `company_profiles` row for AAPL has non-null `description` and `cik`.
- [ ] `instruments` row for AAPL has `name = "Apple Inc"` and `sector = "Technology"`.
- [ ] `_remap_quote()` emits a `quote_zero_or_missing_price` warning for an instrument
      with no price data (unit test).
- [ ] `CanonicalOHLCVBar.from_dict({"datetime": "2021-08-02 13:30:00", ...})` does not
      raise `ValueError` in Python 3.10.
- [ ] `earnings_calendar`, `economic_events`, `macro_indicators`, `daily_sentiments`,
      `insider_transactions`, `yield_curve`, `market_cap_history` tables all exist and
      accept upserts with correct conflict-resolution behaviour (integration test per table).
- [ ] `DatasetType` enum has exactly the 10 values listed in the final state table above.
- [ ] `FundamentalsSection` enum has exactly the 18 values listed (no `DIVIDEND_SUMMARY`).
- [ ] `dividend_summary` table does not exist in the post-migration schema.
- [ ] `make lint && make test` passes in `libs/contracts`, `services/market-ingestion`,
      `services/market-data`.
- [ ] All documentation files in the table above are updated.

---

## Handoff evidence required

1. List of `BP-xxx` bug pattern IDs applied per task.
2. Confirmation that `UNIQUE (instrument_id, period_type, period_end_date)` exists on
   all 13 active fundamentals tables (output of `\d+ income_statements` from psql).
3. Row count for `income_statements` after re-ingesting the AAPL fixture (must be > 1).
4. Output of `alembic upgrade head && alembic downgrade base` (exit codes only).
5. `DatasetType` enum listing (copy-paste from final code).
6. `FundamentalsSection` enum listing (copy-paste from final code).
7. List of all new DB tables created (names only).
8. **Documentation quality checklist:**

| Criterion | Status |
|-----------|--------|
| Accuracy — all documented fields/events/tables match implementation | ✓ / N/A |
| Diagrams — fundamentals section-to-table ER diagram updated | ✓ / N/A |
| Code examples — all new public classes have `from_dict()` example | ✓ / N/A |
| Common pitfalls — ≥2 new entries added to `docs/services/market-data.md` | ✓ / N/A |
| Lib docs — `docs/libs/contracts.md` updated for all 5 new canonical models | ✓ / N/A |
| No orphan docs — `dividend_summary` reference removed from all docs | ✓ / N/A |

---

## Proposed commit message

```
fix(market-data/market-ingestion): fundamentals pipeline correctness + EODHD coverage expansion

Part A: Fix critical upsert bug (conflict on UUID PK → conflict on natural key), decompose
financial statement blobs into per-period rows, add PeriodType.SNAPSHOT, fix dividend_history
key, extract General section into instruments + company_profiles, split Highlights/Valuation,
add Holders and InsiderTransactions extraction, drop dead dividend_summary table.

Part B: Add DatasetTypes EARNINGS_CALENDAR, ECONOMIC_EVENTS, MACRO_INDICATOR, NEWS_SENTIMENT,
INSIDER_TRANSACTIONS, YIELD_CURVE, MARKET_CAP; new adapter methods, canonical models, DB
tables (migrations 003-005), and polling policy seeds.

Validated: alembic upgrade/downgrade cycle clean; all upserts idempotent; per-period rows
confirmed for income_statement; fundamentals lint+unit test suite green.
```
