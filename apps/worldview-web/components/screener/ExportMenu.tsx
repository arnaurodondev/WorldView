/**
 * components/screener/ExportMenu.tsx — CSV / Excel / PDF export dropdown
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-07): users want to take their filtered
 * screener result set into another tool — Excel for analysis, CSV for
 * scripting, PDF for archive/sharing. A single export button is too narrow;
 * three separate buttons clutter the header. A small dropdown keeps the
 * surface compact and lets users pick the format they need.
 *
 * WHY shadcn/ui DropdownMenu (not custom):
 *   - Already in the dep set; consistent with TopBar and other dropdowns.
 *   - Radix handles keyboard nav (Enter/Space activate, Esc dismiss) — needed
 *     for accessibility certification.
 *
 * WHY the menu only shows currently-VISIBLE columns:
 *   - Hidden columns are hidden because the user said so. Exporting them
 *     would surprise — the rule is "what you see is what you export".
 *   - This keeps the export menu coupled to the column popover state without
 *     needing extra UI ("which columns to include?" dialog would be friction).
 *
 * WHY YYYYMMDD-HHmm filename pattern:
 *   - Sortable in any file manager (lex order = chronological).
 *   - No timezone in name (avoids locale ambiguity); users get LOCAL-time
 *     stamps so the file matches their session clock.
 *   - Compact format — the user re-saves these often and a long ISO timestamp
 *     just adds noise.
 *
 * WHO USES IT: app/(app)/screener/page.tsx (results header)
 */

"use client";
// WHY "use client": uses dropdown menu with Radix state, calls helpers that
// touch document/Blob.

import { Download, FileText, FileSpreadsheet, FileImage } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { exportToCsv, type CsvColumn } from "@/lib/csv-export";
import { exportToXlsx, type XlsxColumn } from "@/lib/xlsx-export";
import { exportToPdf, type PdfColumn } from "@/lib/pdf-export";

// ── Public types ─────────────────────────────────────────────────────────────

/**
 * ExportColumn — the unified column descriptor that ExportMenu accepts.
 *
 * WHY one shared type (instead of three): all three exporters take the same
 * (header, accessor) pair. Forcing callers to construct three separate column
 * arrays would be pure busywork.
 */
export interface ExportColumn<T> {
  header: string;
  accessor: (row: T) => string | number | null | undefined;
}

export interface ExportMenuProps<T> {
  /** Already-filtered, already-sorted rows. We export verbatim. */
  rows: readonly T[];
  /** Visible columns only — see file-level WHY. */
  columns: ReadonlyArray<ExportColumn<T>>;
  /** Filename stem WITHOUT extension or timestamp. We append both. */
  filenameBase: string;
  /** Optional title for the PDF export (CSV/XLSX ignore it). */
  pdfTitle?: string;
  /** Optional disabled flag — e.g. when results are still loading. */
  disabled?: boolean;
}

// ── Internal helpers ─────────────────────────────────────────────────────────

/**
 * timestampStem — local-time YYYYMMDD-HHmm. See file-level "WHY YYYYMMDD-HHmm".
 *
 * WHY local components (not toISOString().slice): the user thinks "today" in
 * their local clock. Saving a file at 23:55 PST should be tagged with that
 * day, not the next day's UTC.
 */
function timestampStem(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  return `${y}${m}${d}-${hh}${mm}`;
}

// ── Component ────────────────────────────────────────────────────────────────

export function ExportMenu<T>({
  rows,
  columns,
  filenameBase,
  pdfTitle,
  disabled = false,
}: ExportMenuProps<T>) {
  // WHY one filename for all three: makes the three exports of the same data
  // recognisable as siblings on disk (".csv", ".xlsx", ".pdf" of "screener-...").
  const stem = `${filenameBase}-${timestampStem()}`;

  function handleCsv() {
    const csvColumns: CsvColumn<T>[] = columns.map((c) => ({
      header: c.header,
      accessor: c.accessor,
    }));
    exportToCsv({ rows, columns: csvColumns, filenameStem: stem });
  }

  async function handleXlsx() {
    const xlsxColumns: XlsxColumn<T>[] = columns.map((c) => ({
      header: c.header,
      accessor: c.accessor,
    }));
    await exportToXlsx({ rows, columns: xlsxColumns, filenameStem: stem });
  }

  function handlePdf() {
    const pdfColumns: PdfColumn<T>[] = columns.map((c) => ({
      header: c.header,
      accessor: c.accessor,
    }));
    exportToPdf({ rows, columns: pdfColumns, filenameStem: stem, title: pdfTitle });
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label="Export results"
          className="flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground hover:text-foreground hover:border-border/80 rounded-[2px] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Download className="h-3 w-3" aria-hidden />
          Export
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        {/* WHY explicit aria-label per item: lucide icons are aria-hidden, so
            each menuitem needs its own label for screen readers. */}
        <DropdownMenuItem onSelect={handleCsv} aria-label="Export as CSV" className="text-[11px] gap-2">
          <FileText className="h-3 w-3" aria-hidden />
          CSV
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleXlsx} aria-label="Export as Excel" className="text-[11px] gap-2">
          <FileSpreadsheet className="h-3 w-3" aria-hidden />
          Excel (.xlsx)
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handlePdf} aria-label="Export as PDF" className="text-[11px] gap-2">
          <FileImage className="h-3 w-3" aria-hidden />
          PDF
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
