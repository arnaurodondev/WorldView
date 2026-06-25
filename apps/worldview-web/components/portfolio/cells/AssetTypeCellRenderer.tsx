/**
 * AssetTypeCellRenderer — AG Grid cell renderer: compact coloured asset-type badge.
 *
 * WHY THIS EXISTS: The holdings table design spec (PRD-0089 §6.2) calls for a
 * single-letter (or 3-char) chip in the ASSET column that immediately tells a
 * trader whether a row is an equity, ETF, bond, or crypto position. The chip
 * reuses the same badge semantics as the Transactions tab CLASS column so the
 * colour mapping is consistent across the app.
 *
 * WHO USES IT: ag-holdings-columns.tsx ASSET column cellRenderer.
 * DATA SOURCE: asset_class from HoldingOverviewMap/EnrichedHoldingRow.assetClass,
 *   passed via AG Grid context (params.context.assetClasses) keyed by instrument_id.
 *   When no context or no value, renders "—" placeholder.
 * DESIGN REFERENCE: PRD-0089 §5 component breakdown, §6.3 colour usage.
 *
 * WHY "use client" is NOT required: this is a pure render function, not a
 * React component with hooks. AG Grid invokes it synchronously — no effects,
 * no state, no browser APIs.
 */

import type { ICellRendererParams } from "ag-grid-community";
import { cn } from "@/lib/utils";
import type { EnrichedHoldingRow } from "@/components/portfolio/holdings-columns";

// ── Context shape injected by SemanticHoldingsTable via AG Grid `context` prop
interface AssetTypeContext {
  /**
   * Map from instrument_id → asset_class string (e.g. "equity", "etf").
   * Populated by the parent from HoldingOverviewMap once overviews load.
   * WHY a separate map (not a field on EnrichedHoldingRow): EnrichedHoldingRow
   * is built before overviews arrive; we don't want to invalidate all row
   * enrichment just because the asset-class lookup changed.
   */
  assetClasses?: Record<string, string | null | undefined>;
}

// ── Badge colour map ───────────────────────────────────────────────────────────
// WHY Tailwind classes (not hex inline styles): the design system tokens live in
// the CSS variables; inline style would break in CSS-variable dark/light theming.
// WHY "fund" gets its own case (not merged with "etf"): the backend data model
// uses "fund" for mutual funds / ETFs in PRD-0108; "etf" is kept as an alias so
// existing rows built before the rename still render correctly.
function badgeClass(assetClass: string | null | undefined): string {
  switch ((assetClass ?? "").toLowerCase()) {
    case "equity":
      return "bg-positive/15 text-positive border border-positive/30";
    case "fund":
    case "etf":
      // WHY same colour as primary: funds/ETFs are the default "basket" type —
      // blue primary signals "diversified" to align with industry convention.
      return "bg-primary/15 text-primary border border-primary/30";
    case "option":
      return "bg-negative/15 text-negative border border-negative/30";
    case "future":
      return "bg-warning/15 text-warning border border-warning/30";
    case "bond":
      return "bg-muted-foreground/10 text-muted-foreground border border-muted-foreground/30";
    case "crypto":
      return "bg-primary/25 text-primary border border-primary/40";
    default:
      return "bg-muted/40 text-muted-foreground border border-border/40";
  }
}

// ── Label map ──────────────────────────────────────────────────────────────────
// WHY single-letter codes (E/F/B/C per PRD-0108 §T-4-03): the ASSET column is
// only 48px wide; single-letter chips are more scannable than 2-3 char codes.
// "FUND" and "FUTURE" both start with F — resolved by the fact that "future"
// is not a first-class type in PRD-0108 holdings (futures live in a separate
// instrument type enum); if futures are ever added they will need a separate
// column, not this renderer.
// WHY "etf" falls through to "fund": legacy rows from before the PRD-0108 rename
// still have assetClass="etf"; we map both to "F" so the UI is consistent.
function assetLabel(assetClass: string | null | undefined): string {
  switch ((assetClass ?? "").toLowerCase()) {
    case "equity":
      // E — the canonical single-letter code for equities (PRD-0108 §T-4-03)
      return "E";
    case "fund":
    case "etf":
      // F — funds and ETFs are both "basket" instruments; single label keeps
      // the column unambiguous at a glance.
      return "F";
    case "bond":
      // B — fixed-income instruments
      return "B";
    case "crypto":
      // C — digital assets
      return "C";
    case "option":
      return "OPT";
    case "future":
      return "FUT";
    default:
      // Render muted em-dash for unknown/null to signal "unclassified"
      // without implying anything. Same pattern as transaction table cells.
      return "—";
  }
}

export function AssetTypeCellRenderer(
  params: ICellRendererParams<EnrichedHoldingRow>,
) {
  // WHY pinned-row guard: the TOTAL footer row has no meaningful asset class —
  // it aggregates across multiple instruments. Render nothing so the cell stays
  // clean (the sector cell already renders "—" there; empty is fine here).
  if (params.node?.rowPinned === "bottom") {
    return <span className="font-mono text-[11px] text-muted-foreground">—</span>;
  }

  const instrumentId = params.data?.h.instrument_id;
  const context = params.context as AssetTypeContext | undefined;
  // Look up the asset class from the shared context map injected by the parent.
  const assetClass = instrumentId
    ? (context?.assetClasses?.[instrumentId] ?? null)
    : null;

  const label = assetLabel(assetClass);
  const cls = badgeClass(assetClass);

  if (label === "—") {
    // No badge chrome for unknowns — a bare dash is less noisy.
    return (
      <span className="font-mono text-[11px] text-muted-foreground">—</span>
    );
  }

  return (
    // WHY inline-flex + items-center: the badge must be vertically centred in
    // the 22px row. Without flex the absolute font baseline sits ~2px too low.
    // WHY px-1 py-0 (not py-0.5): at 8px font size, py-0.5 (2px) top+bottom
    // makes the chip 16px tall — taller than the 10px bar allowed per row.
    <div className="flex items-center justify-center h-full">
      <span
        className={cn(
          "inline-flex items-center px-1 rounded-[2px]",
          "font-mono text-[8px] uppercase tracking-[0.04em] leading-[14px]",
          cls,
        )}
      >
        {label}
      </span>
    </div>
  );
}
