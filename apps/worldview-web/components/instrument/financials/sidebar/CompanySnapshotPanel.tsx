/**
 * sidebar/CompanySnapshotPanel.tsx — Company identity + description panel (T-23)
 *
 * WHY THIS EXISTS: PLAN-0089 W3 §4.8 — analysts often need the company's sector,
 * industry classification, headcount, and headquarters alongside the financial
 * metrics. The CompanySnapshotPanel puts "what kind of company is this?" on
 * the right rail so it's always visible while the analyst scrolls the income
 * table. Mirrors Bloomberg's "DES" (company description) command surface.
 *
 * WHY 4-line clamp on description: the sidebar is 240px wide. A full-length
 * EODHD description (often 300–500 words) would dwarf the panel. 4 lines gives
 * enough context to orient the analyst; the "more" toggle reveals the full text
 * without navigating away.
 *
 * WHY reads from Instrument (not Fundamentals): sector, industry, country, and
 * description live on the `Instrument` row (populated from EODHD General section
 * by the market-data backfill). The `Fundamentals` type doesn't carry these fields.
 * The CompanyOverview bundle provides both shapes together.
 *
 * WHO USES IT: AnalystSidebar.tsx composition shell (T-24).
 * DATA SOURCE: instrument prop from InstrumentPageBundle.overview.instrument
 *   (pre-populated by InstrumentPageClient bundle fetch — no additional network call).
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.8
 */

"use client";
// WHY "use client": useState controls the "more/less" description toggle —
// a browser interaction that can't be server-rendered.

import { useState } from "react";
import type { Instrument } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface CompanySnapshotPanelProps {
  /** instrument — from InstrumentPageBundle.overview.instrument. */
  instrument: Instrument | null | undefined;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Row — a label + value pair at 20px data-table-grid height. */
function SnapshotRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex items-start justify-between gap-2 px-2 h-auto min-h-[var(--row-h)]">
      <span className="shrink-0 text-[9px] uppercase tracking-[0.08em] text-muted-foreground/70 font-mono pt-[2px]">
        {label}
      </span>
      <span className="text-right text-[10px] font-mono text-foreground leading-snug">
        {value ?? "—"}
      </span>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CompanySnapshotPanel({ instrument }: CompanySnapshotPanelProps) {
  // Controls whether the full description text is visible or clamped to 4 lines.
  const [showFullDescription, setShowFullDescription] = useState(false);

  if (!instrument) {
    return (
      <div className="flex flex-col border-b border-border">
        {/* Round-3 item 2: uniform accent-bar header (border-l-2 border-l-primary
          + bg-muted/20 — Round-1 DenseMetricsGrid pattern, applied tab-wide). */}
      <div className="flex h-6 items-center border-b border-border border-l-2 border-l-primary bg-muted/20 px-2">
          <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
            COMPANY
          </span>
        </div>
        <div className="flex items-center justify-center py-3">
          <span className="text-[10px] font-mono text-muted-foreground">No data</span>
        </div>
      </div>
    );
  }

  // Build HQ string: "City, COUNTRY" — graceful fallback if either is null.
  const hq = [instrument.country].filter(Boolean).join(", ") || null;

  return (
    <div
      // WHY data-table-grid (default, not dense): the snapshot rows here use
      // 20px height (default variant). Dense variant (18px) is reserved for
      // the DenseMetricsGrid only.
      data-table-grid
      className="flex flex-col border-b border-border"
    >
      {/* Panel header */}
      {/* Round-3 item 2: uniform accent-bar header (border-l-2 border-l-primary
          + bg-muted/20 — Round-1 DenseMetricsGrid pattern, applied tab-wide). */}
      <div className="flex h-6 items-center border-b border-border border-l-2 border-l-primary bg-muted/20 px-2">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
          COMPANY
        </span>
      </div>

      {/* Identity rows — SECTOR / INDUSTRY / EMPLOYEES / HQ */}
      <div className="flex flex-col py-1">
        <SnapshotRow label="SECTOR"   value={instrument.gics_sector} />
        <SnapshotRow label="INDUSTRY" value={instrument.gics_industry} />
        <SnapshotRow label="EXCHANGE" value={instrument.exchange} />
        <SnapshotRow label="HQ"       value={hq} />
      </div>

      {/* Description — 4-line clamp with "more" toggle */}
      {instrument.description && (
        <div className="flex flex-col gap-1 border-t border-border/50 px-2 py-2">
          <span
            className={`text-[10px] font-mono text-muted-foreground leading-snug ${
              // WHY line-clamp-4: 4 lines of 10px mono text at 1.3 line-height ≈ 52px.
              // This keeps the panel compact while giving enough context.
              showFullDescription ? "" : "line-clamp-4"
            }`}
          >
            {instrument.description}
          </span>
          {/* WHY always show the toggle button (not only when text overflows):
              detecting overflow in React requires a ref + ResizeObserver which
              adds complexity. Showing "more" consistently is simpler and
              users quickly learn to click it if they want the full text. */}
          <button
            onClick={() => setShowFullDescription((v) => !v)}
            className="self-start text-[9px] font-mono text-primary hover:text-primary/80 transition-colors"
            aria-label={showFullDescription ? "Show less description" : "Show full description"}
          >
            {showFullDescription ? "← less" : "more →"}
          </button>
        </div>
      )}
    </div>
  );
}
