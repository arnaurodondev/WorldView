/**
 * components/ui/data-table — Universal DataTable primitive surface.
 *
 * The TSV/CSV utility helpers have moved to lib/format/csv-tsv.ts (canonical
 * location for serialisation primitives) — this index keeps the legacy
 * re-export so existing imports `from "@/components/ui/data-table"` keep
 * working. New code should import the format helpers directly from
 * `@/lib/format/csv-tsv`.
 */

export {
  DataTable,
  type DataTableProps,
  type DataTableDensity,
  type DataTableBulkAction,
  type DataTableContextMenuItem,
} from "./data-table";

// Backwards-compat re-exports — prefer @/lib/format/csv-tsv for new imports.
export { rowsToTsv, rowsToCsv, downloadCsv } from "@/lib/format/csv-tsv";
