# Investigation Report: PRD-0089 W3 QA — Three Deferred Issues

**Date**: 2026-05-22
**Investigator**: Claude (investigation skill)
**Scope**: F-009, F-010, F-011 deferred from QA W3 pass

---

## Issue F-009 — EMPLOYEES field absent from CompanySnapshotPanel

**Severity**: HIGH
**Status**: Root cause identified — 3-layer gap (S9 client, TypeScript type, React component)

### 1. Issue Summary

The design spec (docs/designs/0089/06-instrument-financials.md §5.2 line 252) explicitly requires the CompanySnapshotPanel to render 5 rows: SECTOR / INDUSTRY / **EMPLOYEES** / HQ / DESCRIPTION. The current component only renders 3 rows (SECTOR / INDUSTRY / COUNTRY). The `employees` field is missing at every layer from the database-to-component data path.

### 2. Evidence

| Evidence | Source | Relevance |
|----------|--------|-----------|
| §5.2 line 252: "SECTOR / INDUSTRY / EMPLOYEES / HQ / DESCRIPTION" | Design doc | Explicit requirement |
| §11 line 454: "renders sector + industry + employees + HQ + 4-line description" | Acceptance checklist | Gate criterion |
| `company_profiles.full_time_employees: Mapped[int | None]` | `market-data models/company_profiles.py:28` | DB column exists |
| `Instrument` interface has no `full_time_employees` field | `types/api.ts:130–159` | Type gap |
| S9 `get_company_overview()` does not extract `FullTimeEmployees` | `api-gateway/clients/instrument.py:171–187` | API gap |
| `General.FullTimeEmployees` is a confirmed EODHD field | `docs/designs/0089/06-instrument-financials.md §3.2:106` | Source field exists |

### 3. Execution Path Analysis

```
EODHD API → General.FullTimeEmployees (confirmed real field)
    ↓ stored as
market-data S3 → company_profiles.full_time_employees (column EXISTS ✓)
    ↓ S3 /api/v1/fundamentals/{id}/company-profile → profile_data dict
api-gateway S9 → clients/instrument.py get_company_overview()
    ↓ MISSING: profile_data.get("FullTimeEmployees") not extracted
    ↓ instrument dict does NOT include full_time_employees
Frontend types → types/api.ts Instrument interface
    ↓ MISSING: full_time_employees field not declared
CompanySnapshotPanel → renders SECTOR / INDUSTRY / COUNTRY
    ↓ MISSING: no EMPLOYEES SnapshotRow
User sees 3 rows; spec requires 5 rows
```

### 4. Root Cause

Three independent gaps, each of which alone prevents the field from showing:

| Layer | File | Gap |
|-------|------|-----|
| S9 API client | `services/api-gateway/src/api_gateway/clients/instrument.py:184` | `profile_data.get("FullTimeEmployees")` line missing |
| TypeScript type | `apps/worldview-web/types/api.ts:~145` | `full_time_employees: number \| null` field missing from `Instrument` |
| React component | `CompanySnapshotPanel.tsx:77–79` | No `<SnapshotRow label="EMPLOYEES" ...>` render |

### 5. Impact

- Component renders 3 rows instead of 5 (acceptance checklist fails)
- Analysts cannot see headcount to gauge company scale in the sidebar
- All tickers with employee data in EODHD show blank — ~100% of S&P500 instruments

### 6. Recommended Fix (~5 LOC across 3 files)

**Step 1** — S9 `services/api-gateway/src/api_gateway/clients/instrument.py` line 184 (after `founded`):
```python
"full_time_employees": profile_data.get("FullTimeEmployees") or None,
```

**Step 2** — `apps/worldview-web/types/api.ts` in the `Instrument` interface:
```typescript
full_time_employees: number | null;
```

**Step 3** — `apps/worldview-web/components/instrument/financials/sidebar/CompanySnapshotPanel.tsx` after the COUNTRY row:
```tsx
<SnapshotRow
  label="EMPLOYEES"
  value={instrument.full_time_employees ? instrument.full_time_employees.toLocaleString() : undefined}
/>
```

**Step 4** — Verify S3 market-data `/api/v1/fundamentals/{id}/company-profile` includes `FullTimeEmployees` in its response body. If the JSONB `data` field does not surface it top-level, the S9 `profile_data.get("FullTimeEmployees")` call will silently return None and no further stack change is needed.

### 7. Test Design

```python
# services/api-gateway/tests/test_instruments.py
async def test_company_overview_includes_employees():
    """GET /v1/companies/{id}/overview includes full_time_employees from EODHD General.FullTimeEmployees."""
    mock_profile = {"Name": "Apple Inc.", "FullTimeEmployees": "147000", ...}
    # Assert response body contains: full_time_employees == 147000
```

```typescript
// CompanySnapshotPanel.test.tsx — add to MOCK_OVERVIEW.instrument
full_time_employees: 147000,
// Add assertion:
expect(await findByText("147,000")).toBeInTheDocument();
expect(await findByText("EMPLOYEES")).toBeInTheDocument();
```

---

## Issue F-010 — api-gateway instrument_id UUID format not validated

**Severity**: HIGH
**Status**: Root cause identified — 24 affected routes, FastAPI type annotation fix

### 1. Issue Summary

24 route handlers in the api-gateway use `instrument_id: str` (bare string) for path parameters. FastAPI accepts any string, including `javascript:` payloads, path-traversal strings, and SQL injection attempts. When these propagate to S3 (market-data), they either cause 500 errors (asyncpg DataError on invalid UUID cast) or silently drop in signal resolution pipelines.

### 2. Evidence

| Evidence | Source | Relevance |
|----------|--------|-----------|
| `instrument_id: str` in 21 routes | `routes/market.py:620-788` | No validation |
| `instrument_id: str` in 3 routes | `routes/instruments.py:88,200,241` | No validation |
| Portfolio route validates manually: `UUID(instrument_id)` | `routes/portfolio.py:729` | Inconsistency — 1 route validates, 24 don't |
| S3 `quotes.py` validates with regex | `market-data/api/routers/quotes.py:88-91` | Downstream catch only |
| S3 `fundamental_metrics.py` does NOT validate | `market-data/api/routers/fundamental_metrics.py:47` | Risk: asyncpg DataError → 500 |
| FastAPI `UUID` path param auto-validates and returns 422 | FastAPI docs | Drop-in fix |

### 3. Divergence Points

| # | Route | Risk | Likelihood |
|---|-------|------|------------|
| 1 | `GET /fundamentals/{id}/snapshot` | asyncpg DataError → 500 | HIGH |
| 2 | `GET /ohlcv/{instrument_id}` | asyncpg DataError → 500 | HIGH |
| 3 | `GET /fundamentals/timeseries` | S3 fundamental_metrics no UUID guard | HIGH |
| 4 | `GET /instruments/{id}/page-bundle` | S3 instrument not found → 404 | MED |
| 5 | All 24 routes | Path traversal via `../` in URL | LOW (httpx normalizes) |

### 4. Root Cause

All fundamentals, ohlcv, quotes, and instruments routes use bare `str` type annotations. FastAPI's automatic path parameter coercion **only validates the type, not the format** for `str`. The `UUID` type annotation is the correct FastAPI mechanism — it delegates validation to Python's `uuid.UUID` constructor and returns a 422 with a descriptive error for invalid inputs.

The one route that does validate (`portfolio.py:729`) uses manual `try: UUID(x) except ValueError: raise HTTPException(422)` — this pattern should be replaced by the type annotation approach.

### 5. Recommended Fix

In **`services/api-gateway/src/api_gateway/routes/market.py`** and **`services/api-gateway/src/api_gateway/routes/instruments.py`**:

```python
# Before (all 24 routes):
from uuid import UUID
# route handlers:
async def get_fundamentals_snapshot(instrument_id: str, ...):

# After:
async def get_fundamentals_snapshot(instrument_id: UUID, ...):
    # FastAPI auto-validates; instrument_id is now a UUID object
    # String interpolation in URLs still works: f".../{instrument_id}/..."
```

Add to top of both files: `from uuid import UUID` (if not already imported).

This is a 1-token change per route signature (24 occurrences). No logic changes needed.

### 6. Test Design

```python
# services/api-gateway/tests/test_uuid_validation.py
@pytest.mark.parametrize("bad_id", [
    "not-a-uuid",
    "AAPL",
    "screen",  # real case: path-segment collision (PLAN-0059 F-010)
    "'; DROP TABLE instruments; --",
    "12345678-1234-1234-1234",  # truncated UUID
])
async def test_fundamentals_routes_reject_non_uuid(authed_app, bad_id):
    for path in ["/v1/fundamentals/{id}/snapshot", "/v1/fundamentals/{id}", "/v1/ohlcv/{id}"]:
        resp = await client.get(path.replace("{id}", bad_id), headers=auth_headers)
        assert resp.status_code == 422
        # Verify S3 was never called (validation at S9 boundary)
        mock_clients.market_data.get.assert_not_called()

async def test_fundamentals_routes_accept_valid_uuid(authed_app):
    valid_uuid = "11111111-1111-1111-1111-111111111111"
    mock_clients.market_data.get = AsyncMock(return_value=_200_response(b"{}"))
    resp = await client.get(f"/v1/fundamentals/{valid_uuid}/snapshot", headers=auth_headers)
    assert resp.status_code == 200
```

---

## Issue F-011 — isDictOfDicts() type guard too lenient

**Severity**: MEDIUM
**Status**: Root cause identified and fixed in this session

### 1. Issue Summary

Four components share an `isDictOfDicts()` helper (4 duplicated copies) that incorrectly returns `true` for `{"0": {}}` — a dict whose first value is an empty object. This causes a holder/transaction row with all-dash values to render instead of the empty state. `filter(Boolean)` does not catch empty objects because `Boolean({}) === true`.

### 2. Evidence

| Input | `isDictOfDicts()` before fix | Rendered output | Correct output |
|-------|---------------------------|-----------------|----------------|
| `{}` | `false` | Empty state | ✓ Correct |
| `{"0": {}}` | **`true`** | All-dash row | ✗ Should be empty state |
| `{"0": null}` | `false` (null guard) | Legacy path: all-dash | ✗ Should be empty state |
| `{"0": {...}}` | `true` | Data rows | ✓ Correct |

The QA pass added an empty-dict guard (`Object.keys(firstData).length === 0`) for FundHolders and InstitutionalHolders, but:
- It checks the outer dict's key count, not the first value's key count — misses `{"0": {}}`
- InsiderTransactionsTable and InsiderActivityList have no guard at all

### 3. Duplication

The function is duplicated across 4 files:
- `InsiderTransactionsTable.tsx:71`
- `FundHoldersTable.tsx:45`
- `InstitutionalHoldersTable.tsx:49`
- `InsiderActivityList.tsx:92` (Quote tab)

### 4. Root Cause

The function checks `first !== null && typeof first === "object"` but does not verify `Object.keys(first).length > 0`. An empty object `{}` passes these checks. Additionally, each component's `filter(Boolean)` call in the extraction path retains empty objects because they are truthy values.

### 5. Fix Applied

Created shared utility `apps/worldview-web/lib/eohdUtils.ts`:
```typescript
export function isDictOfDicts<T extends Record<string, unknown>>(
  obj: unknown
): obj is Record<string, T> {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  const values = Object.values(obj as Record<string, unknown>);
  if (values.length === 0) return false;  // {} empty dict
  const first = values[0];
  if (first === null || typeof first !== "object" || Array.isArray(first)) return false;
  return Object.keys(first as object).length > 0;  // {"0": {}} empty-value dict
}
```

All 4 components updated to import from shared location. Local copies removed. Legacy extraction paths updated to filter out records missing a primary field (name / ownerName).

### 6. Test Design

```typescript
// apps/worldview-web/__tests__/lib/eohdUtils.test.ts
import { isDictOfDicts } from "@/lib/eohdUtils";

test.each([
  [null, false],
  [undefined, false],
  [[], false],
  [{}, false],                     // empty dict
  [{"0": null}, false],            // null first value
  [{"0": {}}, false],              // empty object first value  ← KEY FIX
  [{"0": "string"}, false],        // scalar first value
  [{"0": {name: "X"}}, true],      // valid dict-of-dicts
  [{"0": {name: "X"}, "1": {name: "Y"}}, true],
])("isDictOfDicts(%s) === %s", (input, expected) => {
  expect(isDictOfDicts(input)).toBe(expected);
});
```

---

## Summary

| Issue | Root Cause | Fix Complexity | Layers Affected | Status |
|-------|-----------|----------------|-----------------|--------|
| F-009 EMPLOYEES | S9 doesn't extract `FullTimeEmployees` from EODHD profile_data | ~5 LOC | S9 + TS type + UI | Needs `/implement` |
| F-010 UUID validation | 24 routes use `str` not `UUID` type annotation | 24 × 1-token change | api-gateway only | Needs `/implement` |
| F-011 isDictOfDicts | `first !== null && typeof === "object"` doesn't require non-empty | ~40 LOC refactor | Frontend only | **FIXED in this session** |

### Recommended Next Steps

- **F-011**: Already fixed — see commit in this session.
- **F-009**: Run `/implement` with scope "add full_time_employees field to S9 instrument builder + TypeScript type + CompanySnapshotPanel render". Requires verifying S3 response includes the field before the S9 extraction.
- **F-010**: Run `/implement` with scope "change `instrument_id: str` → `instrument_id: UUID` in all 24 routes in `routes/market.py` and `routes/instruments.py`, add parametrized 422-rejection test". Low risk, high value.
