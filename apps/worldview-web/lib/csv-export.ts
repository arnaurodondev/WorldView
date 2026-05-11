/**
 * lib/csv-export.ts — Client-side CSV download utility for tabular data
 *
 * WHY THIS EXISTS: Several screens in the app (Transactions, Screener,
 * Holdings) need to export their currently-visible rows so the user can
 * paste into a spreadsheet, mail it to an accountant, or import into a
 * tax-prep tool. Until now each screen would have to re-implement the
 * "stringify rows → trigger download" pipeline; centralising it here
 * means there is exactly one place that worries about CSV escaping
 * (commas, quotes, newlines, dates) and one place to add features
 * (BOM for Excel, semicolon delimiters for European locales) later.
 *
 * WHY papaparse (instead of a hand-rolled `rows.map(r => r.join(','))`):
 * the naive join breaks the moment a value contains a comma, quote, or
 * embedded newline. Papaparse's `unparse()` is the de facto standard for
 * RFC 4180 quoting and is tiny (~40 KB minified). Using it here avoids
 * the long tail of CSV-corruption bugs that plague hand-rolled escapers.
 *
 * WHY the function is provider-agnostic (rows + columns shape): the same
 * helper will be reused by the screener export (T-B-2-07). Pinning the
 * input shape to {columns, rows} keeps the call site self-documenting and
 * makes per-feature wrappers (e.g. `exportTransactionsCSV`) trivial to
 * write — they just shape their domain rows once and call this helper.
 *
 * WHY a Blob + temporary <a> link (not `window.open(dataURI)`):
 * data: URIs are blocked by Chrome's downloads when they exceed ~2MB and
 * by Safari unconditionally for non-image MIME types. Blob URLs route
 * through the browser's normal download UI and trigger Save-As. Anchor
 * `download` attribute gives us an exact filename without server help.
 *
 * SECURITY NOTE: We do NOT inject the filename into the DOM as text — it
 * is only set as the `download` attribute on a synthetic anchor that is
 * never inserted, so XSS via filename is not a concern. URL.revokeObjectURL
 * is called after the click event so the Blob is reclaimed.
 *
 * WHO USES IT:
 *   - components/portfolio/TransactionsTable.tsx  (PLAN-0051 T-A-1-02)
 *   - components/screener/ScreenerExportMenu.tsx  (PLAN-0051 T-B-2-07, planned)
 */

import Papa from "papaparse";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * Column descriptor.
 *
 * WHY a header/key pair (not just `keyof T`): the on-screen column label
 * ("Total $") is rarely a valid JS identifier, and we sometimes want to
 * derive a column from the row (e.g. computed `total = qty × price`) that
 * doesn't exist as a property at all. The `accessor` callback covers both
 * cases without forcing callers to pre-shape rows into "CSV view models".
 */
export interface CsvColumn<T> {
  /** Header shown as the first row in the CSV (e.g. "Total $"). */
  header: string;
  /** Pulls the cell value for this column from a single row. */
  accessor: (row: T) => string | number | null | undefined;
}

export interface ExportToCsvOptions<T> {
  /** Row data — already filtered/sorted exactly how the user is seeing it. */
  rows: readonly T[];
  /** Column definitions — order is preserved in the CSV. */
  columns: ReadonlyArray<CsvColumn<T>>;
  /**
   * Filename WITHOUT extension. The function appends `.csv` itself so
   * downstream callers can't accidentally save a `.txt`.
   * Recommended pattern: `transactions-${YYYY-MM-DD}`.
   */
  filenameStem: string;
}

// ── Internal helpers ─────────────────────────────────────────────────────────

/**
 * Given a Date, returns "YYYY-MM-DD" suitable for an export filename.
 *
 * WHY local-date components (not toISOString().slice(0,10)): the user
 * thinks of "today" in their LOCAL timezone — exporting at 23:30 PST should
 * produce the local calendar date, not the UTC one for tomorrow.
 */
export function todayDateStamp(now: Date = new Date()): string {
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * exportToCsv — turns rows + column definitions into a CSV blob and
 * triggers a browser download. Safe to call only in the browser; calling
 * during server rendering throws because `document` is undefined.
 *
 * WHY guard with `typeof document`: a stray import in a server component
 * would otherwise crash the build with a confusing "document is not
 * defined" error at render time. The guard returns a no-op so Next.js
 * doesn't treeshake the call and tests can still import this module
 * inside jsdom (where `document` is defined).
 */
export function exportToCsv<T>({
  rows,
  columns,
  filenameStem,
}: ExportToCsvOptions<T>): void {
  // SSR / build-time safety — see WHY note above.
  if (typeof document === "undefined") {
    return;
  }

  // Build the matrix Papa.unparse expects: header row + one row per data row.
  // WHY pre-flatten with accessor: papaparse can also stringify object arrays
  // by reading `Object.keys`, but that path doesn't preserve column order
  // across browsers (Object.keys is not guaranteed for non-integer keys
  // in older engines). The matrix path keeps the order explicit.
  const header = columns.map((c) => c.header);
  const data = rows.map((row) =>
    columns.map((c) => {
      const value = c.accessor(row);
      // Coerce undefined/null to empty string. Papaparse leaves them as
      // literal "null"/"undefined" otherwise, which is jarring in Excel.
      if (value == null) return "";
      return value;
    }),
  );

  const csv = Papa.unparse({ fields: header, data }, {
    // Newlines as CRLF — Excel-on-Windows and modern Numbers/LibreOffice
    // all accept it; Unix-only \n broke the import-into-Excel flow when
    // we last shipped a CSV exporter.
    newline: "\r\n",
    // Quote every field — eliminates an entire class of edge cases where
    // a stray comma, quote, or newline in user data corrupts the file.
    quotes: true,
  });

  // Prepend a UTF-8 BOM. WHY: Excel still opens un-BOMed CSVs in CP1252
  // by default on Windows, mangling any non-ASCII ticker / company name
  // (e.g. "Société Générale" → "SociÃ©tÃ© GÃ©nÃ©rale"). The 3-byte
  // BOM tells Excel to interpret the file as UTF-8 — invisible in every
  // other tool.
  const blob = new Blob(["\uFEFF" + csv], {
    type: "text/csv;charset=utf-8;",
  });

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${filenameStem}.csv`;
  // WHY append + click + remove (no .style.display="none"): if we don't
  // attach the anchor to the DOM, Firefox refuses to honour the click. We
  // remove it synchronously after the click event has fired.
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  // Free the blob URL on the next tick — clicking it is synchronous, but
  // some browsers continue to read from the URL during the download
  // negotiation. setTimeout(0) is the canonical cure.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
