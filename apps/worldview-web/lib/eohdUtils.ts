/**
 * lib/eohdUtils.ts — shared helpers for EODHD wire-format detection
 *
 * WHY SHARED: Four components (InsiderTransactionsTable, FundHoldersTable,
 * InstitutionalHoldersTable, InsiderActivityList) each duplicated an
 * `isDictOfDicts` implementation that had an edge-case bug: it accepted
 * `{"0": {}}` (empty-object first value) as a valid dict-of-dicts.
 * `filter(Boolean)` does not catch empty objects (Boolean({}) === true), so
 * a single `{"0": {}}` record would produce an all-dash row instead of the
 * empty state. This shared implementation fixes all four sites at once.
 *
 * EODHD dict-of-dicts format: some EODHD sections (insider transactions,
 * institutional holders, fund holders) are stored as a single DB record
 * whose `data` field contains `{"0": {...}, "1": {...}, ...}` rather than
 * one record per row. The detector must reliably distinguish this from:
 *   - {} — empty dict (no filings available)
 *   - {"0": {}} — empty-object value (EODHD placeholder)
 *   - {"0": null} — null value (malformed EODHD response)
 *   - [...] — array format (future EODHD changes)
 *   - per-record format (legacy test fixtures)
 */

/**
 * isDictOfDicts — returns true iff `obj` is a non-empty plain object whose
 * first value is also a non-null, non-empty plain object.
 *
 * WHY non-generic: callers cast to their specific EODHD type after the check
 * (e.g. `Object.values(firstData as Record<string, EohdInsiderTx>)`). A generic
 * `T extends Record<string, unknown>` causes TypeScript to infer T as the base
 * bound, making field access typed as `unknown` without an explicit type arg —
 * which adds noise at every call site. The non-generic predicate is simpler.
 *
 * EXAMPLES that return true:  {"0": {name: "Vanguard", ...}}
 * EXAMPLES that return false: {}, {"0": {}}, {"0": null}, [], "string", null
 */
export function isDictOfDicts(
  obj: unknown,
): obj is Record<string, Record<string, unknown>> {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
  const values = Object.values(obj as Record<string, unknown>);
  // WHY length check: {} empty dict must not be treated as a valid dict-of-dicts.
  if (values.length === 0) return false;
  const first = values[0];
  // WHY null check before typeof: typeof null === "object" in JS — explicit guard.
  if (first === null || typeof first !== "object" || Array.isArray(first)) return false;
  // WHY Object.keys check: {"0": {}} has an empty object as first value.
  // filter(Boolean) would retain {} (truthy), producing an all-dash row.
  return Object.keys(first as object).length > 0;
}
