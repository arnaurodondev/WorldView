/**
 * components/ui/data-table — Universal DataTable primitive surface.
 *
 * Re-exports the DataTable component plus its TSV/CSV utility helpers
 * so consumers can import everything from a single path.
 */

export {
  DataTable,
  rowsToTsv,
  rowsToCsv,
  downloadCsv,
  type DataTableProps,
  type DataTableDensity,
  type DataTableBulkAction,
  type DataTableContextMenuItem,
} from "./data-table";
