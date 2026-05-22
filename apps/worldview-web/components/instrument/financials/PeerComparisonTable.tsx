/**
 * components/instrument/financials/PeerComparisonTable.tsx — Bloomberg-grade peer table
 *
 * WHY THIS EXISTS: Relative valuation is the backbone of fundamental analysis.
 * Seeing the subject company's P/E and 1Y return alongside 5 GICS peers at a
 * glance answers "is this cheap or expensive relative to the sector?" in seconds.
 * The self-row (bg-muted/30) anchors the comparison: analysts scan the peer
 * columns and immediately see whether the subject is in the top/bottom quartile.
 *
 * WHY return_1y from PeersResponse (not batch OHLCV): S9 pre-computes the 1Y
 * return from OHLCV bars in the peers endpoint itself (PeerInstrument.return_1y).
 * Using the pre-computed value eliminates the additional batch OHLCV round-trip
 * and avoids the 252-bar gate check — S9 already returns null when insufficient
 * bars exist.
 *
 * WHO USES IT: FinancialsTab.tsx — Block 4 of the left column.
 * DATA SOURCE: PeersResponse from qk.instruments.peers(id) via useFinancialsSidebarData.
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.4
 */

"use client";
// WHY "use client": useRouter requires the client runtime for navigation.

import { useRouter } from "next/navigation";
import { formatMarketCap, formatPercent, formatRatio } from "@/lib/utils";
import type { PeersResponse, Fundamentals } from "@/types/api";

// ── Types ──────────────────────────────────────────────────────────────────

interface PeerComparisonTableProps {
  /** Full peers response from S9 (includes industry and 5 nearest peers). */
  peersData: PeersResponse | undefined;
  /** Current instrument identifier (for self-row baseline). */
  instrumentId: string;
  /** Pre-fetched fundamentals for the self-row values. */
  fundamentals: Fundamentals | null;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function returnColor(v: number | null): string {
  if (v == null) return "text-muted-foreground/40";
  if (v > 0) return "text-positive";
  if (v < 0) return "text-negative";
  return "text-foreground";
}

function fmtPct(v: number | null | undefined): string {
  // WHY null guard before formatPercent: formatPercent throws on NaN.
  if (v == null) return "—";
  return formatPercent(v / 100);
}

// ── Component ──────────────────────────────────────────────────────────────

export function PeerComparisonTable({
  peersData,
  instrumentId,
  fundamentals,
}: PeerComparisonTableProps) {
  const router = useRouter();

  if (!peersData) {
    return (
      <div className="text-[11px] text-muted-foreground px-2 py-2 border-t border-border">
        Peer data loading…
      </div>
    );
  }

  const peers = peersData.peers.slice(0, 5);
  if (peers.length === 0) {
    return (
      <div className="text-[11px] text-muted-foreground px-2 py-2 border-t border-border">
        No peers available for this instrument.
      </div>
    );
  }

  return (
    // WHY data-table-grid: 20px rows with border-based cell separators from
    // F1 §16.3 CSS variables.
    <div data-table-grid className="border-t border-border">
      <div className="flex items-center h-[var(--row-h,20px)] px-2 border-b border-border bg-muted/20">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
          PEER COMPARISON{peersData.industry ? ` — ${peersData.industry}` : ""}
        </span>
      </div>
      <table className="w-full text-[11px] font-mono" role="table" aria-label="Peer comparison">
        <thead>
          <tr className="h-[var(--row-h,20px)]">
            <th scope="col" className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal w-[52px]">Ticker</th>
            <th scope="col" className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Name</th>
            <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">Mkt Cap</th>
            <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">P/E</th>
            <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">1Y Ret</th>
            <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">Day Δ</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/30">
          {/* Self row — highlighted with muted background per design spec. */}
          <tr
            className="h-[var(--row-h,20px)] bg-muted/30"
            data-peer-self="true"
          >
            <td className="px-2 text-[11px] font-semibold text-primary tabular-nums whitespace-nowrap">
              {fundamentals?.ticker ?? "—"}
            </td>
            <td className="px-2 text-[11px] text-foreground truncate max-w-[120px]">
              {fundamentals?.name ?? "—"}
            </td>
            <td className="px-2 text-right tabular-nums text-foreground whitespace-nowrap">
              {formatMarketCap(fundamentals?.market_cap ?? null)}
            </td>
            <td className="px-2 text-right tabular-nums text-foreground">
              {fundamentals?.pe_ratio != null ? formatRatio(fundamentals.pe_ratio) : "—"}
            </td>
            {/* WHY 1Y return null for self: self-row uses fundamentals which
                doesn't carry return_1y. Use change_pct (daily) instead. */}
            <td className={`px-2 text-right tabular-nums whitespace-nowrap text-muted-foreground/40`}>—</td>
            <td className={`px-2 text-right tabular-nums whitespace-nowrap ${returnColor(fundamentals?.daily_return ?? null)}`}>
              {fmtPct(fundamentals?.daily_return != null ? fundamentals.daily_return * 100 : null)}
            </td>
          </tr>

          {/* Peer rows — clickable for navigation. */}
          {peers.map((peer) => (
            <tr
              key={peer.instrument_id}
              className="h-[var(--row-h,20px)] cursor-pointer hover:bg-muted/20 transition-colors"
              onClick={() => {
                // WHY push (not Link): we want row-level click on the tr element.
                // Using Link would require nesting a tags which is invalid HTML
                // (block element inside table row). router.push is cleaner here.
                if (peer.ticker) router.push(`/instruments/${encodeURIComponent(peer.ticker)}`);
              }}
              title={peer.ticker ? `Go to ${peer.ticker}` : undefined}
            >
              <td className="px-2 text-[11px] font-semibold text-primary tabular-nums whitespace-nowrap">
                {peer.ticker ?? "—"}
              </td>
              <td className="px-2 text-[11px] text-foreground truncate max-w-[120px]">
                {peer.name ?? "—"}
              </td>
              <td className="px-2 text-right tabular-nums text-foreground whitespace-nowrap">
                {formatMarketCap(peer.market_cap)}
              </td>
              <td className="px-2 text-right tabular-nums text-foreground">
                {peer.pe_ratio != null ? formatRatio(peer.pe_ratio) : "—"}
              </td>
              <td className={`px-2 text-right tabular-nums whitespace-nowrap ${returnColor(peer.return_1y)}`}>
                {fmtPct(peer.return_1y)}
              </td>
              <td className={`px-2 text-right tabular-nums whitespace-nowrap ${returnColor(peer.change_pct)}`}>
                {fmtPct(peer.change_pct)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
