/**
 * components/screener/FilterChipStrip.tsx — Active filter chips (PLAN-0092 Wave D)
 *
 * WHY THIS EXISTS: After applying filters the user needs to see at a glance
 * what's active AND be able to dismiss individual filters without opening the
 * full filter panel. The chip strip fills this role — a 22px horizontal bar
 * below the header that renders one chip per active (non-default) filter.
 *
 * WHY DISMISSABLE (not read-only): If the chip were read-only it would be
 * purely decorative — the user still has to open the full panel to clear it.
 * Clicking the ✕ on a chip clears just that filter and re-applies (i.e. sends
 * a new screener request with the cleared value). Same UX as Finviz pill chips.
 *
 * WHY render null (not an empty strip): an empty strip adds 22px of vertical
 * chrome for zero information. Null-render keeps the layout compact when no
 * filters are set (the default state after Reset or on first load).
 *
 * CHIP LOGIC: Each FilterState key that differs from DEFAULT_FILTERS produces
 * a chip. Range filters produce one chip covering both min+max (e.g. "P/E ≤ 15"
 * or "P/E 10–50"). This mirrors the Finviz convention of one chip per metric.
 *
 * WHO USES IT: app/(app)/screener/page.tsx (rendered below ScreenerHeader)
 * DESIGN REF: docs/designs/0089/08-screener.md §3.3
 */

"use client";

import { X } from "lucide-react";
import { DEFAULT_FILTERS, type FilterState } from "@/features/screener/lib/filter-state";

// ── Types ─────────────────────────────────────────────────────────────────────

interface FilterChip {
  /** Stable key for React reconciliation. */
  key: string;
  /** Human-readable chip label (e.g. "P/E ≤ 15", "Sector: Technology"). */
  label: string;
  /** Called when the user clicks ✕. Patch is applied to current FilterState. */
  clear: (current: FilterState) => FilterState;
}

// ── Chip building ─────────────────────────────────────────────────────────────

/** Format a decimal value as a percentage string for display.
 *  Values < 2 assumed to be decimals (0.15 → 15%); larger assumed already pct. */
function fmtPct(v: number): string {
  const pct = Math.abs(v) < 2 ? v * 100 : v;
  return `${pct.toFixed(1)}%`;
}

function fmtNum(v: number): string {
  return v % 1 === 0 ? String(v) : v.toFixed(1);
}

/** Build a min/max chip string ("≥ X", "≤ Y", or "X–Y"). */
function rangeLabel(prefix: string, min?: number, max?: number, fmt = fmtNum): string {
  if (min != null && max != null) return `${prefix} ${fmt(min)}–${fmt(max)}`;
  if (min != null) return `${prefix} ≥ ${fmt(min)}`;
  if (max != null) return `${prefix} ≤ ${fmt(max)}`;
  return prefix;
}

/** Convert active FilterState to a list of dismissable chips. */
function buildChips(filters: FilterState): FilterChip[] {
  const chips: FilterChip[] = [];

  // ── Text search ─────────────────────────────────────────────────────────
  if (filters.search) {
    chips.push({
      key: "search",
      label: `"${filters.search}"`,
      clear: (f) => ({ ...f, search: "" }),
    });
  }

  // ── Sector ──────────────────────────────────────────────────────────────
  if (filters.sector) {
    chips.push({
      key: "sector",
      label: `Sector: ${filters.sector}`,
      clear: (f) => ({ ...f, sector: "" }),
    });
  }

  // ── Cap tier ────────────────────────────────────────────────────────────
  if (filters.capTier !== DEFAULT_FILTERS.capTier) {
    const label = filters.capTier === "LARGE" ? "Large Cap" : filters.capTier === "MID" ? "Mid Cap" : "Small Cap";
    chips.push({
      key: "capTier",
      label,
      clear: (f) => ({ ...f, capTier: "ALL" }),
    });
  }

  // ── Valuation ───────────────────────────────────────────────────────────
  if (filters.peMin != null || filters.peMax != null) {
    chips.push({
      key: "pe",
      label: rangeLabel("P/E", filters.peMin, filters.peMax),
      clear: (f) => ({ ...f, peMin: undefined, peMax: undefined }),
    });
  }
  if (filters.pbMin != null || filters.pbMax != null) {
    chips.push({
      key: "pb",
      label: rangeLabel("P/B", filters.pbMin, filters.pbMax),
      clear: (f) => ({ ...f, pbMin: undefined, pbMax: undefined }),
    });
  }
  if (filters.psMin != null || filters.psMax != null) {
    chips.push({
      key: "ps",
      label: rangeLabel("P/S", filters.psMin, filters.psMax),
      clear: (f) => ({ ...f, psMin: undefined, psMax: undefined }),
    });
  }
  if (filters.divYieldMin != null || filters.divYieldMax != null) {
    chips.push({
      key: "divYield",
      label: rangeLabel("Div Yield", filters.divYieldMin, filters.divYieldMax, fmtPct),
      clear: (f) => ({ ...f, divYieldMin: undefined, divYieldMax: undefined }),
    });
  }

  // ── Profitability ────────────────────────────────────────────────────────
  if (filters.roeMin != null || filters.roeMax != null) {
    chips.push({
      key: "roe",
      label: rangeLabel("ROE", filters.roeMin, filters.roeMax, fmtPct),
      clear: (f) => ({ ...f, roeMin: undefined, roeMax: undefined }),
    });
  }
  if (filters.netMarginMin != null || filters.netMarginMax != null) {
    chips.push({
      key: "netMargin",
      label: rangeLabel("Net Margin", filters.netMarginMin, filters.netMarginMax, fmtPct),
      clear: (f) => ({ ...f, netMarginMin: undefined, netMarginMax: undefined }),
    });
  }
  if (filters.opMarginMin != null || filters.opMarginMax != null) {
    chips.push({
      key: "opMargin",
      label: rangeLabel("Op Margin", filters.opMarginMin, filters.opMarginMax, fmtPct),
      clear: (f) => ({ ...f, opMarginMin: undefined, opMarginMax: undefined }),
    });
  }

  // ── Growth ──────────────────────────────────────────────────────────────
  if (filters.revGrowthMin != null || filters.revGrowthMax != null) {
    chips.push({
      key: "revGrowth",
      label: rangeLabel("Rev Growth", filters.revGrowthMin, filters.revGrowthMax, fmtPct),
      clear: (f) => ({ ...f, revGrowthMin: undefined, revGrowthMax: undefined }),
    });
  }
  if (filters.earningsGrowthMin != null || filters.earningsGrowthMax != null) {
    chips.push({
      key: "earningsGrowth",
      label: rangeLabel("EPS Growth", filters.earningsGrowthMin, filters.earningsGrowthMax, fmtPct),
      clear: (f) => ({ ...f, earningsGrowthMin: undefined, earningsGrowthMax: undefined }),
    });
  }

  // ── Technical ───────────────────────────────────────────────────────────
  if (filters.above50dMa) {
    chips.push({
      key: "above50dMa",
      label: "Above 50d MA",
      clear: (f) => ({ ...f, above50dMa: undefined }),
    });
  }
  if (filters.rsiMin != null || filters.rsiMax != null) {
    chips.push({
      key: "rsi",
      label: rangeLabel("RSI", filters.rsiMin, filters.rsiMax),
      clear: (f) => ({ ...f, rsiMin: undefined, rsiMax: undefined }),
    });
  }

  return chips;
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface FilterChipStripProps {
  /** Current applied filters (from page state). */
  filters: FilterState;
  /** Called when the user dismisses a chip. Passes the updated FilterState. */
  onApply: (filters: FilterState) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FilterChipStrip({ filters, onApply }: FilterChipStripProps) {
  const chips = buildChips(filters);

  // WHY null (not empty strip): no active filters = no chrome needed.
  if (chips.length === 0) return null;

  return (
    <div
      role="list"
      aria-label="Active screener filters"
      className="flex items-center gap-1 border-b border-border px-3 py-1 overflow-x-auto shrink-0"
    >
      {chips.map((chip) => (
        <span
          key={chip.key}
          role="listitem"
          className="inline-flex items-center gap-1 rounded-[2px] border border-border/60 bg-muted/40 px-1.5 py-0.5 text-[10px] font-mono text-foreground whitespace-nowrap shrink-0"
        >
          {chip.label}
          <button
            type="button"
            aria-label={`Remove filter: ${chip.label}`}
            onClick={() => onApply(chip.clear(filters))}
            className="ml-0.5 text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="h-2.5 w-2.5" aria-hidden strokeWidth={2} />
          </button>
        </span>
      ))}
    </div>
  );
}
