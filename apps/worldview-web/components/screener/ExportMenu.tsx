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
// QA-iter1 MIN-3: only CSV is statically imported — it has zero deps that
// blow up bundle size. PDF (~600KB jspdf + autotable) and Excel (~120KB
// write-excel-file) are dynamic-imported per click so screener users who
// only export CSV never pay for the other formats.
import { exportToCsv, type CsvColumn } from "@/lib/csv-export";
import type { XlsxColumn } from "@/lib/xlsx-export";
import type { PdfColumn } from "@/lib/pdf-export";

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
  /**
   * Round 2 — sort-aware export: when provided, called AT CLICK TIME to fetch
   * the rows, taking precedence over `rows`.
   *
   * WHY a function (not just better `rows`): AG Grid owns its sort state
   * internally — the parent's `rows` prop is the PRE-sort base array and goes
   * stale the moment the user clicks a header. A getter lets the parent pull
   * the grid's post-filter-post-sort row order (via
   * api.forEachNodeAfterFilterAndSort) at the moment of export, so the file
   * matches exactly what the user sees on screen. `rows` remains as the
   * fallback (and powers the disabled state, which needs a render-time count).
   */
  getRows?: () => readonly T[];
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
  getRows,
  columns,
  filenameBase,
  pdfTitle,
  disabled = false,
}: ExportMenuProps<T>) {
  // WHY one filename for all three: makes the three exports of the same data
  // recognisable as siblings on disk (".csv", ".xlsx", ".pdf" of "screener-...").
  const stem = `${filenameBase}-${timestampStem()}`;

  /**
   * resolveRows — pick the export row source AT CLICK TIME.
   * getRows (grid-sorted snapshot) wins over the render-time rows prop —
   * see the getRows prop doc for why. Falls back to `rows` if the getter
   * returns an empty array (e.g. grid not mounted yet) so an export click
   * never silently produces an empty file when data is visibly on screen.
   */
  function resolveRows(): readonly T[] {
    if (getRows) {
      const fresh = getRows();
      if (fresh.length > 0) return fresh;
    }
    return rows;
  }

  function handleCsv() {
    const csvColumns: CsvColumn<T>[] = columns.map((c) => ({
      header: c.header,
      accessor: c.accessor,
    }));
    exportToCsv({ rows: resolveRows(), columns: csvColumns, filenameStem: stem });
  }

  async function handleXlsx() {
    // QA-iter1 MIN-3: dynamic-import write-excel-file only when the user
    // actually clicks Excel — keeps the eager bundle CSV-only.
    const { exportToXlsx } = await import("@/lib/xlsx-export");
    const xlsxColumns: XlsxColumn<T>[] = columns.map((c) => ({
      header: c.header,
      accessor: c.accessor,
    }));
    await exportToXlsx({ rows: resolveRows(), columns: xlsxColumns, filenameStem: stem });
  }

  async function handlePdf() {
    // QA-iter1 MIN-3: jspdf + autotable is the largest export dep (~600KB).
    // Dynamic-import on click means CSV-only users never download it.
    const { exportToPdf } = await import("@/lib/pdf-export");
    const pdfColumns: PdfColumn<T>[] = columns.map((c) => ({
      header: c.header,
      accessor: c.accessor,
    }));
    // WHY await: exportToPdf is now async (it dynamic-imports jspdf + autotable
    // inside the function body so those heavy deps form a separate chunk).
    await exportToPdf({ rows: resolveRows(), columns: pdfColumns, filenameStem: stem, title: pdfTitle });
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label="Export results"
          className="flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground hover:text-foreground hover:border-border/80 rounded-[2px] transition-colors disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))] disabled:cursor-not-allowed"
        >
          <Download className="h-3 w-3" aria-hidden strokeWidth={1.5} />
          Export
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        {/* WHY explicit aria-label per item: lucide icons are aria-hidden, so
            each menuitem needs its own label for screen readers. */}
        <DropdownMenuItem onSelect={handleCsv} aria-label="Export as CSV" className="text-[11px] gap-2">
          <FileText className="h-3 w-3" aria-hidden strokeWidth={1.5} />
          CSV
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleXlsx} aria-label="Export as Excel" className="text-[11px] gap-2">
          <FileSpreadsheet className="h-3 w-3" aria-hidden strokeWidth={1.5} />
          Excel (.xlsx)
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handlePdf} aria-label="Export as PDF" className="text-[11px] gap-2">
          <FileImage className="h-3 w-3" aria-hidden strokeWidth={1.5} />
          PDF
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
