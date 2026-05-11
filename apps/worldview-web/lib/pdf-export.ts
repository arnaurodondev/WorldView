/**
 * lib/pdf-export.ts — Client-side PDF export utility (jspdf + jspdf-autotable)
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-07): Some workflows still travel as PDF —
 * compliance archives, client one-pagers, board attachments. CSV / Excel are
 * editable formats; a PDF is a snapshot of "this is what the screen showed
 * at this moment", which is exactly what auditors want.
 *
 * WHY jspdf@4.2.1 + jspdf-autotable@5.0.7:
 *   - jspdf is the only mature client-side PDF library; everything else is
 *     either server-side (puppeteer) or unmaintained (pdfmake).
 *   - jspdf 4.x patched the FreeText color injection + HTML injection CVEs
 *     that jspdf 2.x and 3.x carry.
 *   - jspdf-autotable 5.0.7 is the canonical "draw a data table" plugin and
 *     declares peerDependency on jspdf ^2 || ^3 || ^4 — works clean with 4.2.1.
 *
 * WHY not just embed a screenshot via html2canvas:
 *   - Bitmap export is unsearchable, fails accessibility, and balloons the
 *     file size. Native PDF text (vector) is preferable for any tabular data.
 *
 * WHY portrait A4:
 *   - International default; US Letter would crop on European printers.
 *   - Portrait fits ~10-12 columns at small font; wider tables paginate
 *     gracefully via autotable's built-in column-overflow handling.
 *
 * WHY a monospace font on data cells:
 *   - Tabular alignment of numbers is the whole point of an export. Default
 *     PDF Helvetica is proportional → "9.43" doesn't line up with "12.70".
 *     jspdf ships Courier as a built-in monospace.
 *
 * SECURITY: jspdf-autotable accepts strings verbatim — no formula or HTML
 * injection vectors apply (PDFs aren't macroed). Output is a static document.
 *
 * WHO USES IT: components/screener/ExportMenu.tsx
 */

import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";

// ── Public types ─────────────────────────────────────────────────────────────

export interface PdfColumn<T> {
  header: string;
  accessor: (row: T) => string | number | null | undefined;
}

export interface ExportToPdfOptions<T> {
  rows: readonly T[];
  columns: ReadonlyArray<PdfColumn<T>>;
  /** Filename WITHOUT extension; helper appends `.pdf`. */
  filenameStem: string;
  /** Optional doc title rendered above the table. */
  title?: string;
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * exportToPdf — produces an A4 portrait PDF with an optional title and a
 * monospaced data table, then triggers download via jspdf's `save()`.
 *
 * WHY synchronous (no async):
 *   - jspdf 4.x is purely synchronous on the document construction path;
 *     `save()` is the only side-effect (anchor click). No need to expose
 *     a Promise that the caller would just `await` for nothing.
 *
 * WHY guard `typeof document`: same SSR-safety reason as csv-export.ts.
 */
export function exportToPdf<T>({
  rows,
  columns,
  filenameStem,
  title,
}: ExportToPdfOptions<T>): void {
  if (typeof document === "undefined") return;

  // WHY a4 + portrait: see file-level WHY notes.
  const doc = new jsPDF({ orientation: "portrait", unit: "pt", format: "a4" });

  // ── Title (optional) ─────────────────────────────────────────────────────
  // WHY optional + small font: the table is the protagonist; the title is
  // chrome. 12pt is enough to identify the document without dominating it.
  if (title) {
    doc.setFontSize(12);
    doc.setFont("helvetica", "bold");
    // WHY 40,40 origin: jspdf default margin convention. Matches the table's
    // start position below for visual alignment.
    doc.text(title, 40, 40);
    doc.setFont("helvetica", "normal");
  }

  // ── Build header + body rows ─────────────────────────────────────────────
  // WHY string-coerce values: jspdf-autotable expects string|number cells.
  // null/undefined would render the literal word; we want a blank cell.
  const head = [columns.map((c) => c.header)];
  const body = rows.map((row) =>
    columns.map((c) => {
      const v = c.accessor(row);
      if (v == null) return "";
      return typeof v === "number" ? v : String(v);
    }),
  );

  // ── Render the table ─────────────────────────────────────────────────────
  // WHY autotable (vs hand-drawn rects):
  //   - Pagination, alternating row tints, header repeat-on-new-page, and
  //     column-width auto-fit are all built in. Reimplementing those is days
  //     of dev work.
  autoTable(doc, {
    head,
    body,
    startY: title ? 56 : 40, // leave room for the title if present
    // WHY courier: monospace alignment for tabular numerics — see file-level WHY.
    styles: {
      font: "courier",
      fontSize: 8,
      cellPadding: 3,
      // WHY no row-fill on data: keep the document austere; institutional PDFs
      // avoid alternating colour bars (they read as informal).
      lineColor: [200, 200, 200],
      lineWidth: 0.5,
    },
    headStyles: {
      // Subtle dark header — readable when printed in B&W too.
      fillColor: [40, 40, 40],
      textColor: [255, 255, 255],
      fontStyle: "bold",
    },
    // WHY margin 40pt on every side: matches the title's 40,40 origin and
    // gives binders a comfortable hole-punch margin.
    margin: { top: 40, left: 40, right: 40, bottom: 40 },
  });

  // ── Save (triggers browser download) ─────────────────────────────────────
  doc.save(`${filenameStem}.pdf`);
}
