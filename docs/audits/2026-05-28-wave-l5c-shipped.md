# Wave L-5c Shipped — Calendar Fields Backend

**Date**: 2026-05-28
**Branch**: `feat/plan-0089-wl-5c`
**Plan ref**: `docs/plans/0089-pages/I-screener-plan.md` §3.2 L-5 row

---

## §1. Scope (delivered)

L-5c is the smallest of the L-5 sub-tracks: backend persistence + screener
wiring for **two calendar (date) snapshot fields**:

| Field | Source |
|-------|--------|
| `next_earnings_date` | `earnings_calendar.report_date` (read-only lookup; table populated by deferred L-5b worker) |
| `next_dividend_date` | EODHD `SplitsDividends.DividendDate` → fallback `ExDividendDate` (extracted by snapshot writer on every fundamentals payload) |

Out of scope:
- **L-5a** — 4 upstream endpoints (parallel sibling agent).
- **L-5b** — S3 sync worker / EODHD `/calendar/earnings` consumer (deferred).
- Frontend — UI changes are part of T-IB-21 (downstream wave I-B).

---

## §2. Migrations & schema

**Migration `028_add_l5c_calendar_columns.py`** (revision="028",
down_revision="024"):

- `ALTER TABLE instrument_fundamentals_snapshot ADD COLUMN IF NOT EXISTS
  next_earnings_date DATE NULL`
- `ALTER TABLE instrument_fundamentals_snapshot ADD COLUMN IF NOT EXISTS
  next_dividend_date DATE NULL`
- Partial BTREE indexes (NULL-excluding) for range queries:
    - `ix_ifs_next_earnings_date` ON (next_earnings_date) WHERE NOT NULL
    - `ix_ifs_next_dividend_date` ON (next_dividend_date) WHERE NOT NULL
- Seeds 2 rows in `screen_field_metadata` (idempotent ON CONFLICT DO NOTHING).
- Clean downgrade — drops only this migration's artefacts.

**Migration number coordination**: sibling waves L-3 / L-4a / L-4b are
running concurrently on parallel branches and claim revisions 025 / 026 /
027. L-5c chains directly from 024 to 028 to avoid collisions; the
integrator re-linearises on merge (a no-op rebase because each sibling
ALTERs distinct columns).

**Up/down/up cycle verified** against a temporary `l5c_test_db` database
on the running postgres container: every step succeeded, columns and
indexes appeared / disappeared as expected, seeded rows roundtripped.

---

## §3. ORM

**New** `EarningsCalendarModel` in
`services/market-data/src/market_data/infrastructure/db/models/earnings_calendar.py`
— mirrors migration 001 schema for the existing (but historically un-mapped)
`earnings_calendar` table. Registered in `models/__init__.py` so
`Base.metadata` includes it.

**Extended** `InstrumentFundamentalsSnapshotModel` with two new mapped
DATE columns matching migration 028.

---

## §4. Snapshot writer (T-WL5C-03)

`fundamentals_snapshot_writer.py`:

1. New `_safe_date(val, label)` helper — coerces ISO-8601 strings
   (`"2026-02-12"` or `"2026-02-12T00:00:00"`), python `date`/`datetime`,
   and common sentinels (`""`, `"N/A"`, `"0000-00-00"`) to `date | None`
   with debug-log fallback on unparseable strings.
2. `derive_fundamentals_snapshot` gains a new `splits_dividends` kwarg
   (default None for backward compat). When present, extracts
   `DividendDate` (preferred = payment date) → `ExDividendDate` (fallback
   = ex-div date) → None.
3. New `fetch_next_earnings_date(session, instrument_id)` helper —
   `SELECT MIN(report_date) FROM earnings_calendar WHERE instrument_id =
   :id AND report_date >= CURRENT_DATE`. Returns NULL today (L-5b worker
   not yet shipped); will auto-populate when L-5b lands without any
   further code change.
4. `_UPSERT_SQL` extended with the two new columns. The UPSERT keeps the
   same COALESCE-based policy as every other field (partial payload
   never clobbers a previously-recorded value).

`fundamentals_consumer.py`:

- Passes `splits_dividends` section to `derive_fundamentals_snapshot`.
- Calls `fetch_next_earnings_date` best-effort after deriving the rest
  of the snap dict; any DB error is logged at debug and never fails the
  snapshot UPSERT.
- Trigger condition extended so a splits-dividends-only payload still
  triggers a snapshot UPSERT (matters for non-equity payloads that lack
  highlights / cash flow / etc.).

**Did `next_earnings_date` already ingest?** No. The `earnings_calendar`
table has existed since migration 001 but no consumer wrote to it. The
read-side lookup (`fetch_next_earnings_date`) is wired now, so the
column will auto-populate as soon as the deferred L-5b worker starts
writing rows. Until then, the column stays NULL — which is correct.

---

## §5. Screener wiring (T-WL5C-04)

| Layer | Change |
|-------|--------|
| `ScreenFilterRequest` (Pydantic) | + `next_earnings_within_days: int \| None` and `next_dividend_within_days: int \| None`, both validated `ge=0, le=365`. |
| `ScreenFilter` (port dataclass) | + matching frozen-dataclass kwargs (defaults to None). |
| Router | passes the new fields through; adds them to the `snap_sort_fields` SQL-injection allowlist for `sort_by`. |
| `_SNAP_FIELDS` (repo) | + `next_earnings_date`, `next_dividend_date` so they project into every screen result. |
| `query_screen` WHERE | calendar-window predicate: `WHERE col BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL ':n_days days'`. NULL snapshots are excluded by `NULL BETWEEN ...` → UNKNOWN. |
| `query_screen` ORDER BY | new branch handles the two date columns (ASC = soonest first). |
| Router response | `date` values serialize to ISO-8601 strings before fitting the existing `dict[str, float \| str \| None]` shape. |

---

## §6. screen_field_metadata seed + LOCK-STEP

Migration 028 seeds two rows. `_get_static_screen_fields()` in
`market-data/src/market_data/app.py` is updated in lock-step (docstring
"23 static" → "25 static"; two new `ScreenFieldMetadata` entries with
exactly matching `field_name` / `label` / `field_type` / `unit` /
`description` values). Divergence would let the 6-hour refresh loop
overwrite the migration's seed on the next tick.

`field_type='numeric'` because the CHECK constraint
`ck_screen_field_metadata_field_type` admits only `('numeric', 'text')`
— the UI filter is a number-of-days input so numeric semantics are
correct.

---

## §7. Tests

`tests/unit/test_screener_l5c.py` (**new, 17 tests, all PASS**):

WHERE-clause assertions:
- `next_earnings_within_days=30` → SQL contains `next_earnings_date`,
  `CURRENT_DATE`, `INTERVAL`, `30`.
- `next_earnings_within_days=0` → still adds the BETWEEN predicate
  (no short-circuit bug).
- `next_dividend_within_days=14` → symmetric to earnings.
- No calendar filter → no `CURRENT_DATE` WHERE clause.

ORDER BY assertions:
- `sort_by='next_earnings_date'` ASC → SQL contains the column in the
  ORDER BY clause.
- Same for `next_dividend_date`.

Result projection:
- Populated calendar columns appear in `metrics` dict as python `date`
  objects.
- NULL calendar columns are absent from the dict (no `None` strings).

Snapshot writer:
- `derive_fundamentals_snapshot` extracts `DividendDate` from EODHD JSONB.
- Falls back to `ExDividendDate` when `DividendDate` is missing.
- Returns `None` for missing/sentinel/empty values.

`_safe_date` helper:
- ISO date string, ISO datetime string, python `date`, empty / sentinel
  variants, unparseable strings.

Two existing tests updated (R19-compliant — no deletion):
- `test_get_screen_fields_route_returns_12_fields` count assertion
  23 → 25, plus assert new L-5c field names appear.
- `test_upsert_snapshot_ohlcv_fallback_skipped_when_eodhd_provides_volume`
  no longer asserts `execute.assert_not_called()` (the consumer now
  always calls `fetch_next_earnings_date`); instead scans the captured
  SQL strings for the OHLCV-specific `ohlcv_bars` table reference and
  asserts no such call was made.

**Full market-data unit suite: 774 pass, 27 warnings, 0 failures.**

---

## §8. Validation gates (per task spec)

| Gate | Result |
|------|--------|
| `ruff check --fix src/` | Clean |
| `ruff format src/` | Clean |
| `mypy src/` | Success — no issues in 141 source files |
| Migration cycle up → down → up | Clean on `l5c_test_db` |
| `pytest tests/unit/ -k "calendar or l5c or screener"` | All pass |
| `pytest tests/unit/` | 774 pass, 0 failures |

---

## §9. Open items / follow-ups

- **L-5b worker** — when it lands, no code change needed in market-data:
  the `fetch_next_earnings_date` lookup auto-populates from `earnings_calendar`.
- **L-5a endpoints** — parallel sibling agent; tracking under a separate
  branch.
- **Migration re-linearisation on merge** — integrator must rebase 028
  onto whatever the post-merge head is (likely 027 after L-3/L-4a/L-4b
  land). The DDL is independent of the sibling waves' ALTERs so no
  semantic conflict is expected.
