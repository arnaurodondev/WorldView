/**
 * lib/xlsx-export.ts — Client-side Excel (.xlsx) export utility
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-07): Excel is the lingua franca of finance.
 * CSV works for technical users, but a portfolio manager opening the file on
 * a managed Windows laptop expects to see formatted columns, frozen header,
 * and proper number columns — not "97,365.21" rendered as a date.
 * write-excel-file produces a real .xlsx with type-aware cells.
 *
 * WHY write-excel-file (NOT xlsx aka SheetJS):
 *   - SheetJS / `xlsx` 0.18.5 has unpatched Prototype Pollution + ReDoS CVEs
 *     (GHSA-4r6h-8v6p-xvw6 + GHSA-5pgg-2g8v-p4x9). The mandate is "0 CVEs"
 *     so SheetJS is off the table.
 *   - exceljs has transitive `uuid` CVEs.
 *   - write-excel-file is small, modern (browser-first ESM), and audits clean.
 *
 * WHY a small wrapper (instead of letting callers import write-excel-file):
 *   - The wrapper enforces consistent behaviour across all Excel exports
 *     (column types, header formatting, filename pattern).
 *   - Single seam to mock in tests — the screener test suite mocks this
 *     module, not the third-party library directly.
 *
 * WHY the input shape mirrors lib/csv-export.ts:
 *   - The screener export menu fans the same row+column data out to CSV/Excel/PDF.
 *   - A shared shape ({ rows, columns: {key,label}[], filename }) keeps the
 *     ExportMenu component's call sites symmetric and easy to read.
 *
 * SECURITY: Excel formulas starting with =/+/-/@ can trigger formula injection
 * when the file is opened in Excel. We defensively prefix any string cell that
 * begins with one of those characters with a single quote ('), the canonical
 * "force literal" escape. See OWASP "CSV Injection" (applies to xlsx too).
 *
 * WHO USES IT: components/screener/ExportMenu.tsx
 */

// WHY the /browser subpath: write-excel-file 4.x is split into /browser, /node,
// and /universal entry points; only the subpaths ship type declarations. The
// browser bundle is what the Next.js client uses (no Node-only fs usage).
import writeXlsxFile from "write-excel-file/browser";

// ── Public types ─────────────────────────────────────────────────────────────

/**
 * XlsxColumn — column descriptor shared with the ExportMenu.
 *
 * WHY accessor returns string | number | null | undefined: covers every value
 * type the screener emits (tickers, prices, ratios, "—" placeholders). null
 * and undefined are normalised to empty cells inside the helper, so callers
 * never need to filter them out manually.
 */
export interface XlsxColumn<T> {
  /** Header text shown in the first row. */
  header: string;
  /** Pulls the cell value out of one row. */
  accessor: (row: T) => string | number | null | undefined;
}

export interface ExportToXlsxOptions<T> {
  rows: readonly T[];
  columns: ReadonlyArray<XlsxColumn<T>>;
  /** Filename WITHOUT extension. The helper appends `.xlsx`. */
  filenameStem: string;
}

// ── Internal helpers ─────────────────────────────────────────────────────────

/**
 * sanitizeFormula — see SECURITY note above. Defends against Excel formula
 * injection by prefixing any cell that starts with =, +, -, @ (the four
 * characters Excel treats as formula starters) with a single quote.
 */
function sanitizeFormula(value: string): string {
  if (!value) return value;
  const first = value.charAt(0);
  if (first === "=" || first === "+" || first === "-" || first === "@") {
    return "'" + value;
  }
  return value;
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * exportToXlsx — render rows + columns into an .xlsx and trigger download.
 *
 * WHY async: write-excel-file is async (it streams ZIP entries internally).
 * Callers should `await` so any error surfaces to a try/catch instead of
 * disappearing into an unhandled promise rejection.
 *
 * WHY guard `typeof document`: same reason as csv-export — prevents SSR import
 * crashes during Next.js build/server-render passes.
 */
export async function exportToXlsx<T>({
  rows,
  columns,
  filenameStem,
}: ExportToXlsxOptions<T>): Promise<void> {
  if (typeof document === "undefined") return;

  // Build SheetData (the matrix overload) — a 2D array of Cell objects.
  //
  // WHY the matrix form (not the objects+schema form):
  //   - The objects+schema overload of write-excel-file 4.x has very strict
  //     typing that doesn't let us narrow type per-cell (Number vs String).
  //   - The SheetData matrix accepts a heterogeneous {value, type} per cell
  //     with no schema generic, which is exactly what we need.
  //
  // Cell objects: `{ value, type, fontWeight? }`.
  //   - type: String (text) or Number (numeric). Numbers sort/aggregate in Excel.
  //   - fontWeight: "bold" only on the header row.

  // Header row — bold so it visually separates from data.
  const headerRow = columns.map((c) => ({
    value: c.header,
    fontWeight: "bold" as const,
    type: String,
  }));

  // Data rows.
  const dataRows = rows.map((row) =>
    columns.map((c) => {
      const v = c.accessor(row);
      if (v == null || v === "") {
        return { value: null, type: String };
      }
      if (typeof v === "number") {
        return { value: v, type: Number };
      }
      // String path: defend against formula injection (see SECURITY note above).
      return { value: sanitizeFormula(String(v)), type: String };
    }),
  );

  const data = [headerRow, ...dataRows];

  // WHY columns option: hint Excel to give every column ~16 chars of width.
  // Long names will wrap; numbers will display fully.
  const sheetColumns = columns.map(() => ({ width: 16 }));

  // WHY any-cast on data: the SheetData type is a deeply-nested union that TS
  // struggles to infer through the .map() above. The runtime contract is
  // satisfied — each cell is a {value, type, ...} object.
  //
  // WHY the .toFile() chain: write-excel-file 4.x splits creation from output.
  // The function returns an object with toBlob() and toFile() methods. toFile()
  // triggers the browser download via a synthetic anchor under the hood — exactly
  // what we want.
  await writeXlsxFile(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    data as any,
    {
      columns: sheetColumns,
      // Freeze the header row so users can scroll through long result sets
      // without losing column context — institutional table convention.
      stickyRowsCount: 1,
    },
  ).toFile(`${filenameStem}.xlsx`);
}
