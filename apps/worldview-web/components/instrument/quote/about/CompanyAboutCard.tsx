/**
 * components/instrument/quote/about/CompanyAboutCard.tsx
 * — Company profile card (PLAN-0099 W4)
 *
 * WHY THIS EXISTS: The Quote tab layout Wave D adds a 110px company profile
 * strip below the SessionStatsStrip. Showing sector/industry/HQ/employees and a
 * 3-line description gives traders immediate context without switching to the
 * Financials tab or opening a browser search.
 *
 * DATA SOURCE: `instrument` prop — from bundle.overview.instrument (already on
 * the page bundle, zero extra fetch). The `Instrument` type carries gics_sector,
 * gics_industry, country, and description directly.
 *
 * DESIGN:
 *   - Fixed h-[110px], px-3 py-1, border-t border-border
 *   - First line: SECTOR + INDUSTRY in 10px uppercase tracking-wide muted
 *   - Second line: HQ + employees in same style
 *   - Third-fifth lines: description, text-[11px], line-clamp-3, "more" toggle
 *   - Null fields → "—"; all null → italic "Company profile not available."
 *   - Loading state: 5 × skeleton bars
 *
 * WHO USES IT: QuoteTab.tsx (Wave D layout).
 * LINE LIMIT: ≤ 120 LOC.
 */

// WHY no "use client" at module level: we use useState for the expand toggle,
// so this IS a client component. "use client" is required.
"use client";

import { useState } from "react";
import type { Instrument } from "@/types/api";

// ── Props ──────────────────────────────────────────────────────────────────────

interface CompanyAboutCardProps {
  /** Instrument from page bundle (null → skeleton or unavailable state). */
  instrument: Instrument | null;
  /** True while the bundle is in-flight — shows animated skeleton. */
  isLoading?: boolean;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function CompanyAboutCard({ instrument, isLoading = false }: CompanyAboutCardProps) {
  // WHY useState: the description is clamped to 3 lines by default; clicking
  // "more" removes the clamp so the analyst can read the full text inline.
  const [expanded, setExpanded] = useState(false);

  // ── Loading skeleton ─────────────────────────────────────────────────────
  // WHY 5 skeleton bars: mirrors the real content height (2 metadata rows + 3
  // description lines = ~5 text lines of equal height).
  if (isLoading) {
    return (
      <div className="h-[110px] px-3 py-1 border-t border-border overflow-hidden">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-[18px] w-full mb-[1px] animate-pulse bg-muted rounded-[2px]"
          />
        ))}
      </div>
    );
  }

  // ── No data state ────────────────────────────────────────────────────────
  // WHY all-null check (not just instrument null): an instrument object may
  // arrive with every profile field set to null (e.g. freshly-seeded ETF with
  // no EODHD company profile yet). Guard the render in that case too.
  const hasNoData =
    !instrument ||
    (!instrument.gics_sector && !instrument.gics_industry &&
      !instrument.country && !instrument.description);

  if (hasNoData) {
    return (
      <div className="h-[110px] px-3 py-2 border-t border-border flex items-start overflow-hidden">
        <span className="text-[11px] text-muted-foreground italic">
          Company profile not available.
        </span>
      </div>
    );
  }

  // ── Normal render ────────────────────────────────────────────────────────
  return (
    <div className="h-[110px] px-3 py-1 border-t border-border overflow-hidden">
      {/* Line 1: Sector + Industry */}
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground leading-[1.6] truncate">
        {/* WHY truncate: long sector/industry names would overflow the 380px right rail. */}
        <span className="text-muted-foreground/60">SECTOR:</span>{" "}
        {instrument.gics_sector ?? "—"}
        {" · "}
        <span className="text-muted-foreground/60">INDUSTRY:</span>{" "}
        {instrument.gics_industry ?? "—"}
      </p>

      {/* Line 2: HQ country */}
      {/* WHY no employee count: the Instrument type from S9/page-bundle does
          not include employee_count — that field lives on EntityMetadata (KG).
          A future Wave E can add it once a dedicated endpoint exposes it. */}
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground leading-[1.6] truncate">
        <span className="text-muted-foreground/60">HQ:</span>{" "}
        {instrument.country ?? "—"}
        {" · "}
        <span className="text-muted-foreground/60">EXCHANGE:</span>{" "}
        {instrument.exchange ?? "—"}
      </p>

      {/* Lines 3–5: Company description with expand toggle */}
      {instrument.description && (
        <div className="mt-[2px]">
          <p
            className={`text-[11px] leading-[1.5] text-foreground/80 ${expanded ? "" : "line-clamp-3"}`}
          >
            {instrument.description}
          </p>
          {/* WHY "more"/"less" toggle: the card is fixed 110px — expanding shows
              the full description which overflows the card but is still readable
              because the parent column has `overflow-hidden` at the tab level,
              not at the card level. Future wave: consider an expandable drawer. */}
          <button
            className="text-[10px] text-primary cursor-pointer mt-[1px] hover:underline"
            onClick={() => setExpanded((v) => !v)}
            type="button"
          >
            {expanded ? "less" : "more"}
          </button>
        </div>
      )}
    </div>
  );
}
