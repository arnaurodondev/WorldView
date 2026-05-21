/**
 * components/instrument/quote/about/CompanyAboutCard.tsx
 * — Bloomberg DES-style company about card (W5-T-12)
 *
 * DATA SOURCE: `instrument: Instrument | null` from the page-bundle.
 *   All fields (sector, industry, country, founded, description) are
 *   already hydrated in the overview — no extra fetch needed.
 *
 * DESIGN:
 *   - `data-table-grid` on the 4-row stat block → 20px rows (Δ4, F1 §16.3).
 *   - `text-[10px]` labels (F1 floor, Δ2). No `rounded-*` (Δ3).
 *   - Description: 3-line clamp + "more" toggle (Δ — §7.4).
 *   - ETF empty state (Δ35): name + exchange + "Description not available".
 *   - `country` = HQ; city-level deferred to v1.1 (not yet in S9 bundle).
 *
 * WHO USES IT: QuoteTab.tsx (T-25 wiring pass).
 */

"use client";
// WHY "use client": useState for description toggle requires browser runtime.

import { useState } from "react";
import type { Instrument } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Return ISO-3166-1 country code as HQ label. City-level deferred to v1.1. */
function fmtHQ(country: string | null): string | null {
  if (!country) return null;
  return country.toUpperCase(); // EODHD stores 2-letter code (e.g. "US")
}

/** Extract 4-digit year from EODHD Founded (may be "1976" or "1976-01-01"). */
function fmtFounded(founded: string | null): string | null {
  if (!founded) return null;
  const year = founded.slice(0, 4);
  return /^\d{4}$/.test(year) ? year : null;
}

// ── Sub-components ────────────────────────────────────────────────────────────

/** One stat row inside the data-table-grid block (20px via --row-h). */
function StatRow({ label, value }: { readonly label: string; readonly value: string | null }) {
  return (
    <div role="row" className="flex items-center h-[var(--row-h,20px)] px-3 gap-2">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground shrink-0 w-[72px]">
        {label}
      </span>
      <span className="text-[11px] font-mono tabular-nums text-foreground truncate">
        {value ?? "—"}
      </span>
    </div>
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface CompanyAboutCardProps {
  /** Page-bundle Instrument (null while loading). */
  instrument: Instrument | null;
  /** True while the page-bundle query is still in-flight. */
  isLoading?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CompanyAboutCard({ instrument, isLoading = false }: CompanyAboutCardProps) {
  const [descExpanded, setDescExpanded] = useState(false);

  // ── Derived values ───────────────────────────────────────────────────────
  const sector = instrument?.gics_sector ?? null;
  const industry = instrument?.gics_industry ?? null;
  const hq = fmtHQ(instrument?.country ?? null);
  const founded = fmtFounded(instrument?.founded ?? null);
  const description = instrument?.description ?? null;

  // ETFs have no description and no GICS sector. Show name+exchange instead.
  const isEtfEmpty = !isLoading && instrument != null && !description && !sector;

  return (
    // WHY no rounded-* (Δ3). WHY border-t (Δ6 hairline between right-rail cards).
    <div className="border-t border-[hsl(var(--border-subtle))]">

      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex items-center h-[20px] px-3 border-b border-[hsl(var(--border-subtle))]">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">
          About
        </span>
      </div>

      {/* ── ETF empty state (Δ35) ───────────────────────────────────────── */}
      {isEtfEmpty && (
        <div className="px-3 py-2 flex flex-col gap-0.5">
          <span className="text-[11px] font-semibold text-foreground truncate">
            {instrument?.name ?? "—"}
          </span>
          {instrument?.exchange && (
            <span className="text-[10px] text-muted-foreground">
              {instrument.exchange}
            </span>
          )}
          <span className="text-[10px] text-muted-foreground/60 mt-1">
            Description not available
          </span>
        </div>
      )}

      {/* ── Normal (company) state ──────────────────────────────────────── */}
      {!isEtfEmpty && (
        <>
          {/* data-table-grid: F1 §16.3 opt-in → --row-h=20px for [role="row"] children. */}
          <div data-table-grid>
            <StatRow label="Sector"  value={isLoading ? null : sector} />
            <StatRow label="Industry" value={isLoading ? null : industry} />
            <StatRow label="HQ"       value={isLoading ? null : hq} />
            <StatRow label="Founded"  value={isLoading ? null : founded} />
          </div>

          {/* ── Description with 3-line clamp + toggle ──────────────────── */}
          {(description || isLoading) && (
            <div className="px-3 pt-1.5 pb-2">
              <p
                className={`text-[11px] text-foreground leading-relaxed ${
                  // line-clamp-3 preserves word boundaries; removed when expanded.
                  descExpanded ? "" : "line-clamp-3"
                }`}
              >
                {isLoading
                  ? "Loading…"
                  : description}
              </p>
              {/* WHY only render toggle when description exists and has content
                  longer than 3 lines: the toggle is useless for short descriptions.
                  We can't measure line count in SSR, so we always render it for
                  non-null descriptions — the browser hides the clamped portion
                  naturally if description fits in 3 lines. */}
              {description && (
                <button
                  type="button"
                  aria-label={descExpanded ? "Collapse description" : "Expand description"}
                  onClick={() => setDescExpanded((v) => !v)}
                  className="mt-0.5 text-[10px] text-muted-foreground hover:text-foreground"
                >
                  {descExpanded ? "less" : "more"}
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
