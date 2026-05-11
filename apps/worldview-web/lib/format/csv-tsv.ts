/**
 * lib/format/csv-tsv.ts — TSV/CSV serialisation for tabular exports
 *
 * WHY THIS EXISTS: Both DataTable's clipboard/CSV exports and stand-alone export
 * buttons (e.g. ScreenerExportMenu) need to serialise rows to spreadsheet
 * formats. Co-locating with parse-shorthand.ts keeps all serde primitives
 * under `lib/format/`. Components that import these no longer reach into
 * `components/ui/data-table/` for non-UI logic.
 *
 * SECURITY: Every cell is run through `sanitiseFormula` to neutralise CWE-1236
 * (CSV injection). Excel/Sheets/Numbers will EXECUTE a cell starting with
 * `=`, `+`, `-`, `@`, `\t`, or `\r`. Prefixing with a single quote defangs the
 * formula while preserving the displayed value.
 */

import type { ColumnDef } from "@tanstack/react-table";

/**
 * sanitiseFormula — CWE-1236 mitigation. Prefix dangerous leading chars with `'`.
 * The single-quote is interpreted by spreadsheets as "force this cell to be
 * a string"; the value still displays the same minus the prefix in some apps.
 */
export function sanitiseFormula(s: string): string {
  return /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
}

/**
 * resolveCellValue — handle BOTH `accessorKey` and `accessorFn` column shapes.
 *
 * TanStack columns: `{accessorKey: "ticker"}` OR `{accessorFn: (row) => row.foo.bar}`.
 * Earlier impl only handled accessorKey — accessorFn columns silently exported
 * empty strings. Now we look at both.
 */
export function resolveCellValue<TData>(col: ColumnDef<TData>, row: TData): unknown {
  const accessorKey = (col as { accessorKey?: keyof TData }).accessorKey;
  if (accessorKey != null) return (row as TData)[accessorKey];
  const accessorFn = (col as { accessorFn?: (row: TData) => unknown }).accessorFn;
  if (accessorFn) return accessorFn(row);
  return "";
}

function columnHeader<TData>(c: ColumnDef<TData>): string {
  return typeof c.header === "string" ? c.header : (c.id ?? "");
}

/**
 * Convert rows to a TSV string. Sanitises formula-injection on every cell
 * (including headers), strips embedded tabs/newlines.
 *
 * Internal `__select__` columns (DataTable selection checkbox) are excluded.
 */
export function rowsToTsv<TData>(rows: TData[], columns: ColumnDef<TData>[]): string {
  const cols = columns.filter((c) => c.id !== "__select__");
  const headers = cols.map(columnHeader).map(sanitiseFormula);
  const lines = [headers.join("\t")];

  for (const row of rows) {
    const cells = cols.map((c) => {
      const v = resolveCellValue(c, row);
      const s = v == null ? "" : String(v).replace(/\t/g, " ").replace(/\n/g, " ");
      return sanitiseFormula(s);
    });
    lines.push(cells.join("\t"));
  }

  return lines.join("\n");
}

/** Convert rows to a CSV string. RFC 4180 quoting + formula-injection guard. */
export function rowsToCsv<TData>(rows: TData[], columns: ColumnDef<TData>[]): string {
  const escape = (v: unknown) => {
    if (v == null) return "";
    const safe = sanitiseFormula(String(v));
    return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
  };
  const cols = columns.filter((c) => c.id !== "__select__");
  const headers = cols.map(columnHeader);
  const lines = [headers.map(escape).join(",")];
  for (const row of rows) {
    lines.push(cols.map((c) => escape(resolveCellValue(c, row))).join(","));
  }
  return lines.join("\n");
}

/**
 * downloadCsv — trigger a browser download for the given CSV string.
 *
 * WHY Blob + revokeObjectURL: avoids leaking the object URL across exports.
 */
export function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
