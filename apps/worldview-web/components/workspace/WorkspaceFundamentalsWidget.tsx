/**
 * components/workspace/WorkspaceFundamentalsWidget.tsx — Compact fundamentals table
 *
 * WHY THIS EXISTS: When a workspace panel is set to type "fundamentals", the
 * existing WorkspacePanelContainer falls back to the heavyweight `FundamentalsTab`
 * component built for the Instrument Detail page. That component is densely
 * paginated with multiple sections (valuation, profitability, growth, dividends,
 * balance sheet) and assumes the parent page is at least 1200px wide.
 *
 * In a workspace panel — typically 300-500px wide and 200-400px tall — that
 * full tab is unreadable. This widget shows the SIX most important metrics in
 * a compact 22px-row vertical table — enough information for a glance without
 * sacrificing legibility.
 *
 * METRICS SHOWN (in display order, justification per row):
 *   1. Market Cap     — size of company; first thing every analyst checks
 *   2. P/E (TTM)      — most-cited valuation multiple
 *   3. P/B            — alternate valuation lens (esp. financials/REITs)
 *   4. Div Yield      — income perspective for non-growth stocks
 *   5. ROE            — capital-efficiency proxy (key profitability metric)
 *   6. Beta           — risk/correlation with S&P 500
 *
 * Beta + EPS_TTM live in `FundamentalsSnapshot` (S3 derived metrics endpoint),
 * the rest live in the regular `Fundamentals` payload. We fetch the snapshot
 * only when a ticker is linked — empty panels make zero S9 calls.
 *
 * WHO USES IT: WorkspacePanelContainer when panel.type === "fundamentals"
 * DATA SOURCE: GET /v1/fundamentals/{instrumentId} and /v1/fundamentals/{id}/snapshot
 * DESIGN REFERENCE: PRD-0031 §5.4 Panel widgets, §0.2 22px row height
 */

"use client";
// WHY "use client": uses TanStack Query (browser data fetching/caching)

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { DashboardEmptyState } from "@/components/ui/dashboard-empty-state";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatMarketCap } from "@/lib/utils";

// ── Format helpers (local — these mirror the formatting rules used elsewhere) ──

/** Format a P/E or P/B multiple — 2 decimals, em-dash for null. */
function formatRatio(v: number | null | undefined): string {
  // WHY em-dash on null: design system §0 mandates em-dash for missing data
  // (NEVER 0, NEVER "N/A", NEVER blank). Distinguishes "no data" from "zero".
  if (v == null) return "—";
  return v.toFixed(2);
}

/** Format a percentage (input is fraction: 0.085 → "8.50%"). */
function formatPercent(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

/** Format beta — 2 decimals, em-dash for null. */
function formatBeta(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(2);
}

// ── Component props ────────────────────────────────────────────────────────────

interface WorkspaceFundamentalsWidgetProps {
  /**
   * Optional ticker symbol. When omitted, the widget shows an empty state.
   * The instrument ID is derived using the demo-seed convention `ins-<ticker>`
   * (matches WorkspacePanelContainer's mapping).
   */
  ticker?: string;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function WorkspaceFundamentalsWidget({ ticker }: WorkspaceFundamentalsWidgetProps) {
  const { accessToken } = useAuth();

  // WHY derive here (not as a prop): keeps the widget's API simple — the
  // parent only knows about the linked ticker, not S9 instrument identifiers.
  const instrumentId = ticker ? `ins-${ticker.toLowerCase()}` : undefined;

  // ── Fundamentals + snapshot fetches ──────────────────────────────────────
  // WHY two queries (not one): /v1/fundamentals/{id} returns the bulk metrics
  // (market cap, P/E, ROE, dividend yield, etc). /v1/fundamentals/{id}/snapshot
  // returns derived metrics (beta, eps_ttm, fcf). They're separate S3 endpoints
  // and we don't want one failing to take down the other — independent useQueries
  // give us per-metric resilience.
  const { data: fundamentals, isLoading: fundLoading, isError: fundError } = useQuery({
    queryKey: ["workspace-fundamentals", instrumentId],
    queryFn: () => createGateway(accessToken).getFundamentals(instrumentId!),
    enabled: !!accessToken && !!instrumentId,
    // WHY 5min: fundamentals update on quarterly cadence — refreshing every
    // 5min is generous. Even daily would be sufficient for accuracy.
    staleTime: 5 * 60_000,
  });

  const { data: snapshot } = useQuery({
    queryKey: ["workspace-fundamentals-snapshot", instrumentId],
    queryFn: () => createGateway(accessToken).getFundamentalsSnapshot(instrumentId!),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 5 * 60_000,
  });

  // ── Empty state: no symbol linked ────────────────────────────────────────
  if (!ticker) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <DashboardEmptyState
          title="No symbol linked"
          message="Pick a symbol via the color picker to see fundamentals."
        />
      </div>
    );
  }

  // ── Loading skeleton ─────────────────────────────────────────────────────
  if (fundLoading && !fundamentals) {
    return (
      // WHY space-y-px: 1px gap between rows for visual separation.
      // WHY 7 rows (header + 6 metrics): matches the final layout density.
      <div className="space-y-px">
        <div className="flex h-6 items-center border-b border-border px-2">
          <Skeleton className="h-2.5 w-16" />
        </div>
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="flex items-center justify-between gap-2 px-2 h-[22px]"
          >
            <Skeleton className="h-2.5 w-14" style={{ animationDelay: `${i * 30}ms` }} />
            <Skeleton className="h-2.5 w-12" style={{ animationDelay: `${i * 30 + 15}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────
  if (fundError || !fundamentals) {
    return (
      <p className="px-2 py-1 text-[11px] text-muted-foreground">
        Fundamentals unavailable for {ticker}.
      </p>
    );
  }

  // ── Build the metric rows ────────────────────────────────────────────────
  // WHY array-driven (not 6 inline rows): keeps the JSX compact and lets us
  // map with consistent spacing/coloring. Each row has a label + value + units.
  const rows = [
    { label: "Market Cap", value: formatMarketCap(fundamentals.market_cap) },
    { label: "P/E (TTM)", value: formatRatio(fundamentals.pe_ratio) },
    { label: "P/B", value: formatRatio(fundamentals.price_to_book) },
    { label: "Div Yield", value: formatPercent(fundamentals.dividend_yield) },
    { label: "ROE", value: formatPercent(fundamentals.roe) },
    // WHY snapshot.beta (not fundamentals.beta): beta lives only in the
    // FundamentalsSnapshot endpoint per types/api.ts. If snapshot hasn't loaded
    // yet, show em-dash (loading state shouldn't block the rest of the table).
    { label: "Beta", value: formatBeta(snapshot?.beta) },
  ];

  return (
    <div className="divide-y divide-border/30">
      {/* Section header — ticker label */}
      {/*
       * WHY h-6 + uppercase tracked: matches the established panel section
       * header pattern (§0.9). Ticker shown in font-mono primary color so it
       * matches the widget's chart sibling visually.
       */}
      <div className="flex h-6 items-center gap-1.5 border-b border-border px-2">
        {/* WHY font-mono: ADR-F-15 — section labels use IBM Plex Mono */}
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          Fundamentals
        </span>
        <span className="font-mono text-[11px] uppercase tabular-nums text-primary">
          {ticker}
        </span>
      </div>

      {/* Metric rows — 22px each per §0.2 */}
      {rows.map((row) => (
        <div
          key={row.label}
          // WHY h-[22px]: §0.2 row height mandate. flex justify-between so the
          // label sits on the left and the value tab-aligns on the right.
          className="flex items-center justify-between gap-2 px-2 h-[22px] hover:bg-muted/40"
        >
          {/* Label — left, muted, sentence case (not uppercase — uppercase is
              reserved for SECTION headers per §0.9). */}
          <span className="text-[11px] text-muted-foreground">{row.label}</span>
          {/* Value — right-aligned, monospace, tabular-nums for column alignment */}
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}
