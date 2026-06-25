/**
 * components/instrument/financials/useSortableRows.ts — tiny client-side
 * column-sort primitive shared by the Financials-tab tables (Wave-4 enhancement).
 *
 * WHY THIS EXISTS: the holder tables (Institutional / Fund) and the peer
 * relative-value board were STATIC — they rendered a fixed order ("top 10 by
 * shares" / "by market cap") with no way for the analyst to re-rank. On a
 * Bloomberg/Finviz-grade surface the FIRST thing a user does with a dense
 * ranked table is click a column header to ask a different question:
 * "who's BUYING the most?" (sort Change desc), "who holds the biggest %?"
 * (sort % Held desc), "which peer is cheapest?" (sort P/E asc). Hard-coding
 * one order forces the user to scan all 10 rows by eye — exactly the kind of
 * friction that reads as "static / unfinished".
 *
 * WHY A HOOK (not a full <SortableTable> component): the three tables already
 * have bespoke, finance-grade markup (mono fonts, 22px rows, colour-coded
 * deltas, dict-of-dicts extraction). Replacing them with a generic table
 * component would be a large risky rewrite and would FLATTEN the per-table
 * formatting that makes each one readable. A hook + a header-cell helper lets
 * each table keep its exact JSX and gain sorting with ~3 lines of wiring.
 *
 * WHY CLIENT-SIDE SORT (not a new API param): every one of these tables is
 * already fully materialised in the browser (≤10 rows from a single S9
 * record). Sorting 10 rows in JS is free and instant — round-tripping to S9
 * for a re-sort would add latency for zero benefit and is not even supported
 * by the endpoints.
 *
 * NULL HANDLING: nulls always sort to the BOTTOM regardless of direction.
 * A missing value ("—") is not "smaller than everything" — it's "unknown",
 * and unknowns belong at the end of a ranked list in both asc and desc so the
 * populated rows the analyst cares about stay at the top.
 *
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §6 (dense tables), Finviz column
 * headers (click to sort, arrow indicates active column + direction).
 */

"use client";
// WHY "use client": useState + useMemo run in the browser; the consuming
// tables are client components anyway.

import { useMemo, useState } from "react";

/** Sort direction. "asc" = smallest/A-first, "desc" = largest/Z-first. */
export type SortDirection = "asc" | "desc";

/**
 * The sort state a table tracks: which column key is active and which way.
 * `key` is null when the table is in its natural/default order (no header
 * clicked yet) — we keep the caller's incoming order untouched in that case.
 */
export interface SortState<K extends string> {
  readonly key: K | null;
  readonly direction: SortDirection;
}

/**
 * A column's value extractor. Returns the comparable primitive for a row, or
 * null when the row has no value for this column (sorts to the bottom).
 *
 * WHY string OR number: holder names sort alphabetically (locale compare),
 * while shares / % / value / price sort numerically. Returning the raw
 * primitive lets the comparator pick the right comparison automatically.
 */
export type SortAccessor<T> = (row: T) => string | number | null | undefined;

export interface UseSortableRowsResult<T, K extends string> {
  /** The rows in the current sort order (or the input order when key is null). */
  readonly sortedRows: readonly T[];
  /** Current sort state — drives the header arrow indicators. */
  readonly sort: SortState<K>;
  /**
   * Click handler for a header cell. Clicking the ACTIVE column flips the
   * direction; clicking a NEW column activates it with the supplied default
   * direction (numeric columns default to "desc" — biggest-first is what an
   * analyst means by "sort by shares"; text columns default to "asc").
   */
  readonly toggleSort: (key: K) => void;
}

export interface UseSortableRowsOptions<T, K extends string> {
  /** The rows to sort (already extracted/normalised by the caller). */
  readonly rows: readonly T[];
  /** Per-column value extractors, keyed by the same K the headers use. */
  readonly accessors: Record<K, SortAccessor<T>>;
  /**
   * Default direction per column when it first becomes active. Numeric
   * "ranked" columns want "desc" (biggest first); a NAME column wants "asc".
   * Omitted keys default to "desc".
   */
  readonly defaultDirections?: Partial<Record<K, SortDirection>>;
  /**
   * Optional initial active column. When provided, the table renders sorted
   * from first paint (e.g. peers default-sorted by market cap desc). When
   * omitted the table keeps the caller's incoming order until a header click.
   */
  readonly initialSort?: SortState<K>;
}

/**
 * Compare two extracted values. Strings use locale compare (case-insensitive
 * via the `sensitivity` option so "Apple" and "apple" rank together);
 * numbers subtract. Nulls/undefined are handled by the caller (pushed to the
 * bottom) BEFORE this runs, so here we only see real primitives.
 */
function compareValues(a: string | number, b: string | number): number {
  if (typeof a === "number" && typeof b === "number") {
    return a - b;
  }
  // Coerce to string for the mixed/text case (defensive — accessors should be
  // consistent per column, but this keeps the comparator total).
  return String(a).localeCompare(String(b), undefined, { sensitivity: "base" });
}

export function useSortableRows<T, K extends string>({
  rows,
  accessors,
  defaultDirections,
  initialSort,
}: UseSortableRowsOptions<T, K>): UseSortableRowsResult<T, K> {
  // Sort state lives here so each table instance tracks its own column/dir.
  const [sort, setSort] = useState<SortState<K>>(
    initialSort ?? { key: null, direction: "desc" },
  );

  const toggleSort = (key: K) => {
    setSort((prev) => {
      // Same column clicked again → flip direction (asc ⇄ desc). This is the
      // universal spreadsheet/Finviz affordance users already expect.
      if (prev.key === key) {
        return { key, direction: prev.direction === "asc" ? "desc" : "asc" };
      }
      // New column → activate with its configured default direction.
      const dir = defaultDirections?.[key] ?? "desc";
      return { key, direction: dir };
    });
  };

  const sortedRows = useMemo(() => {
    // No active column → preserve the caller's incoming order verbatim. This
    // is important: callers pass a meaningful default (self-row-first for
    // peers, top-10-by-shares for holders) that we must not disturb until the
    // user explicitly asks for a different ranking.
    if (sort.key === null) return rows;

    const accessor = accessors[sort.key];
    const dirFactor = sort.direction === "asc" ? 1 : -1;

    // Copy before sort — never mutate the input array (it's TanStack-cached
    // data; mutating it in place would corrupt the shared query cache).
    return [...rows].sort((rowA, rowB) => {
      const va = accessor(rowA);
      const vb = accessor(rowB);

      // Null handling: unknowns always sink to the bottom in BOTH directions.
      const aNull = va == null;
      const bNull = vb == null;
      if (aNull && bNull) return 0;
      if (aNull) return 1; // a after b
      if (bNull) return -1; // a before b

      return compareValues(va, vb) * dirFactor;
    });
  }, [rows, accessors, sort]);

  return { sortedRows, sort, toggleSort };
}
