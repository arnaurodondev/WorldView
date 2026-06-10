/**
 * components/instrument/financials/PeerComparisonTable.tsx — Peer comparison grid (T-12)
 *
 * WHY THIS EXISTS: PLAN-0089 W3 §4.5 — the peer comparison block is the primary
 * relative-value analysis surface on the Financials tab. Analysts benchmark
 * the subject instrument's P/E, P/B, market cap, and 1Y return against 5 same-
 * industry peers in a single compact table. The Bloomberg "RV" (relative value)
 * equivalent for equity analysts who need to answer "cheap vs peers?" in < 5s.
 *
 * WHY self-row highlight (bg-muted/30): traders need to locate the subject
 * instrument instantly when scanning a 6-row table. The muted background
 * mirrors Finviz's "current ticker" row pattern.
 *
 * WHY peer row click → router.push (not <Link>): the row is a <tr> element,
 * not an <a> element. Next.js App Router's router.push navigates programmatically.
 * F2 TickerLink exists at components/portfolio/cells/TickerLink.tsx but is
 * portfolio-scoped; here we navigate directly with F2-style URLs.
 *
 * WHO USES IT: FinancialsTab.tsx — Block 4 of the left column (T-25).
 * DATA SOURCE: peersData from useFinancialsSidebarData → qk.instruments.peers(id)
 *   → S9 GET /v1/instruments/{id}/peers (T-S9-03, shipped in W5).
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.5
 */

"use client";
// WHY "use client": router.push (useRouter) is a browser API. Row click
// handlers use the Next.js App Router client-side navigation.

import { useRouter } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPercent, formatMarketCap } from "@/lib/utils";
import type { PeersResponse, PeerInstrument } from "@/lib/api/instruments";
import type { Fundamentals } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface PeerComparisonTableProps {
  /** The instrument being viewed — rendered as the self-row. */
  fundamentals: Fundamentals | null | undefined;
  /** Peers data from useFinancialsSidebarData. */
  peersData: PeersResponse | undefined;
  /** True while useFinancialsSidebarData is still fetching peers. */
  isLoading?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** formatReturn — converts decimal return to a ±% string. */
function formatReturn(v: number | null): string {
  if (v == null) return "—";
  // WHY multiply by 100: the backend returns 0.18 for +18%. formatPercent
  // expects a decimal (0–1 range) for percentages, so 0.18 → "18.0%".
  return formatPercent(v);
}

// ── Column definitions ────────────────────────────────────────────────────────
// WHY co-located: column headers and alignment are tightly coupled with their
// cell rendering logic. A separate constants file would invite drift.

const COLS = [
  { key: "ticker",     label: "TICKER",    align: "left"  as const },
  { key: "name",       label: "NAME",      align: "left"  as const },
  { key: "market_cap", label: "MCAP",      align: "right" as const },
  { key: "pe_ratio",   label: "P/E",       align: "right" as const },
  { key: "return_1y",  label: "1Y RET",    align: "right" as const },
  { key: "sector",     label: "SECTOR",    align: "left"  as const },
];

// ── Self-row builder ──────────────────────────────────────────────────────────

function buildSelfRow(fundamentals: Fundamentals): PeerInstrument {
  return {
    instrument_id: fundamentals.instrument_id,
    ticker: fundamentals.ticker,
    name: fundamentals.name,
    pe_ratio: fundamentals.pe_ratio ?? null,
    market_cap: fundamentals.market_cap ?? null,
    // WHY null for self return_1y: the self-row return would require a separate
    // OHLCV fetch. The peers endpoint returns 1Y return for peers; the
    // instrument's own 1Y return is visible on the Quote tab.
    return_1y: null,
    gics_sector: null,
  };
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PeerComparisonTable({
  fundamentals,
  peersData,
  isLoading = false,
}: PeerComparisonTableProps) {
  const router = useRouter();

  if (isLoading) {
    return (
      // WHY fixed height on skeleton: matches the expected table height (6 rows ×
      // 20px + header) so the layout doesn't jump when data loads.
      <Skeleton className="h-[160px] w-full rounded-[2px]" />
    );
  }

  // Build combined rows: self first, then peers.
  const selfRow = fundamentals ? buildSelfRow(fundamentals) : null;
  const peerRows = peersData?.peers ?? [];
  const allRows: Array<PeerInstrument & { isSelf: boolean }> = [
    ...(selfRow ? [{ ...selfRow, isSelf: true }] : []),
    ...peerRows.map((p) => ({ ...p, isSelf: false })),
  ];

  if (allRows.length === 0) {
    return (
      <div
        className="flex items-center justify-center border border-border bg-background py-4"
        data-table-grid
      >
        <span className="text-[11px] text-muted-foreground font-mono">No peer data available</span>
      </div>
    );
  }

  return (
    // WHY data-table-grid (no "dense" variant): peer table rows need 20px
    // height (default variant) to accommodate multi-word company names. The
    // dense variant (18px) is reserved for the DenseMetricsGrid snapshot only.
    <div data-table-grid className="w-full">
      {/* Section header — matches the convention used across all table blocks */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          PEER COMPARISON
        </span>
        {peerRows.length > 0 && (
          <span className="ml-2 text-[9px] text-muted-foreground/60 font-mono">
            same GICS industry · by market cap
          </span>
        )}
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[80px_1fr_90px_60px_70px_120px] border-b border-border bg-background/60">
        {COLS.map((col) => (
          <div
            key={col.key}
            className={`flex items-center px-2 h-[var(--row-h)] text-[9px] uppercase tracking-[0.08em] text-muted-foreground/70 font-mono ${
              col.align === "right" ? "justify-end" : ""
            }`}
          >
            {col.label}
          </div>
        ))}
      </div>

      {/* Data rows */}
      {allRows.map((row) => (
        <div
          key={row.instrument_id}
          // WHY bg-muted/30 for self row: the self-row identifies the current
          // instrument so analysts can locate it at a glance in the 6-row table.
          className={`grid grid-cols-[80px_1fr_90px_60px_70px_120px] border-b border-border last:border-b-0 ${
            row.isSelf
              ? "bg-muted/30"
              : "cursor-pointer hover:bg-muted/10 transition-colors"
          }`}
          // WHY onClick only on peer rows (not self): clicking self would
          // navigate to the same page the user is already on.
          onClick={
            row.isSelf
              ? undefined
              : () => router.push(`/instruments/${encodeURIComponent(row.ticker)}`)
          }
          // WHY role="row": improves accessibility and aligns with the
          // data-table-grid semantic model used across the design system.
          role="row"
          aria-label={row.isSelf ? `${row.ticker} (current)` : `Navigate to ${row.ticker}`}
          data-testid={`peer-row-${row.ticker}`}
        >
          {/* TICKER column */}
          <div className="flex items-center px-2 h-[var(--row-h)]">
            <span
              className={`text-[11px] font-mono tabular-nums font-semibold ${
                row.isSelf ? "text-foreground" : "text-primary"
              }`}
            >
              {row.ticker}
            </span>
            {row.isSelf && (
              // Visual indicator that this is the subject instrument.
              <span className="ml-1 text-[8px] text-muted-foreground/60 font-mono">◆</span>
            )}
          </div>

          {/* NAME column — truncate to single line */}
          <div className="flex items-center px-2 h-[var(--row-h)] min-w-0">
            <span className="text-[10px] font-mono text-muted-foreground truncate">
              {row.name}
            </span>
          </div>

          {/* MCAP column */}
          <div className="flex items-center justify-end px-2 h-[var(--row-h)]">
            <span className="text-[11px] font-mono tabular-nums text-foreground">
              {formatMarketCap(row.market_cap)}
            </span>
          </div>

          {/* P/E column */}
          <div className="flex items-center justify-end px-2 h-[var(--row-h)]">
            <span className="text-[11px] font-mono tabular-nums text-foreground">
              {row.pe_ratio != null ? row.pe_ratio.toFixed(1) : "—"}
            </span>
          </div>

          {/* 1Y RETURN column */}
          <div className="flex items-center justify-end px-2 h-[var(--row-h)]">
            <span
              className={`text-[11px] font-mono tabular-nums ${
                row.return_1y == null
                  ? "text-muted-foreground"
                  : row.return_1y >= 0
                  ? // WHY text-positive/text-negative (Round-2 token fix, DS §15.11):
                    // the previous `text-[color:var(--color-positive)]` referenced a
                    // CSS variable that is NEVER DEFINED in globals.css (the silent
                    // no-paint bug class that bit the portfolio sparkline) — the text
                    // fell back to inherited color and gains/losses rendered
                    // indistinguishable. `text-positive`/`text-negative` are the
                    // canonical semantic utilities mapped in tailwind.config.ts to
                    // hsl(var(--positive))/hsl(var(--negative)).
                    "text-positive"
                  : "text-negative"
              }`}
            >
              {row.isSelf ? "—" : formatReturn(row.return_1y)}
            </span>
          </div>

          {/* SECTOR column */}
          <div className="flex items-center px-2 h-[var(--row-h)] min-w-0">
            <span className="text-[10px] font-mono text-muted-foreground truncate">
              {row.gics_sector ?? "—"}
            </span>
          </div>
        </div>
      ))}

      {/* Footer with row count */}
      <div className="flex items-center px-2 py-1 border-t border-border bg-background/40">
        <span className="text-[9px] font-mono text-muted-foreground/50">
          {peerRows.length} peer{peerRows.length !== 1 ? "s" : ""} · click row to navigate
        </span>
      </div>
    </div>
  );
}
