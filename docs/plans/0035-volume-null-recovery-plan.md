# Volume Null Recovery Plan

**Status**: Proposed
**Date**: 2026-04-24
**Related**: F-002 (BP-189), `CanonicalOHLCVBar.volume: int | None`

---

## Problem

Before the F-002 fix (2026-04-24), `CanonicalOHLCVBar.from_dict()` coerced `volume: null` to `volume: 0`. Historical `ohlcv_bars.volume = 0` rows in the database are permanently ambiguous: they could mean actual zero trades OR null provider data silently coerced to 0.

After the fix, new data correctly preserves `None` through the canonical layer (coerced to `0` only at the storage boundary for the NOT NULL DB column).

---

## Recovery Options

### Option A: Re-ingest from bronze bucket
- The bronze S3 bucket (`market-bronze`) contains original EODHD JSON responses with raw `volume` values
- A backfill script reads bronze objects, extracts the original volume, and identifies null-volume bars
- Comparison with DB rows: where DB has `volume=0` and bronze has `volume=null` → mark as recovered
- **Requires**: Either ALTER COLUMN to NULLABLE (high-risk for TimescaleDB hypertable) or a companion boolean column
- **Effort**: Medium (script + migration + validation)
- **Risk**: Medium (hypertable ALTER, data volume)

### Option B: Mark-and-ignore with boolean flag
- Add `volume_null_estimated: bool DEFAULT FALSE` column to `ohlcv_bars`
- Backfill: `SET volume_null_estimated = TRUE WHERE volume = 0 AND bar_date < '2026-04-24'`
- Downstream consumers filter: skip `volume_null_estimated` rows for volume analytics
- **Effort**: Low (migration + simple UPDATE)
- **Risk**: Low (additive column, no schema break)

### Option C: Accept data loss (recommended for thesis)
- Document the ambiguity in `docs/BUG_PATTERNS.md` (BP-189) — already done
- New data going forward preserves null → correctly serialized in S3 JSONL
- Historical data ambiguity is acceptable for thesis scope
- Full recovery only needed if deploying to production with paying customers
- **Effort**: None
- **Risk**: None (thesis-scoped acceptance)

---

## Recommendation

**Option C** for thesis scope. The volume ambiguity affects a small subset of historical bars (off-hours, settlement, closed-market days). Price impact scoring (PRD-0020) uses recent data where the fix is active. The fix prevents new data corruption going forward.

If the platform progresses beyond thesis to production deployment, implement **Option B** as a low-risk first step, then **Option A** if analytics precision requires it.

---

## Acceptance Criteria

- [x] BP-189 documents the historical ambiguity clearly
- [x] New data after 2026-04-24 correctly preserves null volume through the pipeline
- [x] `CanonicalOHLCVBar.volume` is `int | None` with tests
- [x] Storage boundary coerces `None → 0` at DB layer only
- [ ] (Future) Option B migration if production deployment proceeds
