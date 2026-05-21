/**
 * components/instrument/quote/bottom/PeersStrip.tsx
 * — Top-5 industry peers strip (W5-T-19)
 *
 * DATA SOURCE: `data: PeersResponse | null` from useQuoteSidebarData().peers.
 *   Columns: ticker (min-w-[60px] Δ33) | P/E | mkt cap | 1Y return.
 *
 * DESIGN:
 *   - 5 rows × 4 cols. No `rounded-*` (Δ3). text-[10px] labels (Δ2).
 *   - Click → `/instruments/{peer.ticker}` (Δ10 — F2 ticker URL).
 *   - Hover (200ms debounce) prefetches peer page-bundle (Δ39).
 *   - `data-table-grid` → 20px rows (Δ4).
 *   - ETF / no-industry empty state: "No peer data available."
 *
 * WHO USES IT: BottomTripleStrip.tsx (T-22).
 * LINE LIMIT: ≤ 150 LOC.
 */

"use client";
// WHY "use client": useRouter + useQueryClient for click + hover prefetch.

import { useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { formatMarketCap, formatRatio } from "@/lib/utils";
import type { PeersResponse } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Return percent string with sign (already ×100 from S9): "+3.4%" / "−5.1%". */
function fmtReturn(v: number | null): string | null {
  if (v == null) return null;
  return (v >= 0 ? "+" : "") + v.toFixed(1) + "%";
}

/** 1Y return color class. */
function returnColor(v: number | null): string {
  if (v == null) return "text-muted-foreground/50";
  return v >= 0 ? "text-positive" : "text-negative";
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface PeersStripProps {
  /** Peers data from useQuoteSidebarData().peers. */
  data: PeersResponse | null | undefined;
  /** True while the query is in-flight. */
  isLoading?: boolean;
  /** Whether the component is in a loading/error state. */
  isError?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PeersStrip({ data, isLoading = false, isError = false }: PeersStripProps) {
  const router = useRouter();
  const qc = useQueryClient();
  const token = useAccessToken();
  // WHY timerRef: stable ref for the 200ms hover debounce. A new ref per peer
  // row would clear the wrong timer — one global ref is sufficient since only
  // one peer can be hovered at a time.
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const peers = data?.peers.slice(0, 5) ?? [];
  const isEmpty = !isLoading && !isError && peers.length === 0;

  /** Hover start: schedule a prefetch after 200ms (Δ39). */
  function handlePointerEnter(ticker: string | null) {
    if (!ticker) return;
    hoverTimerRef.current = setTimeout(() => {
      // WHY prefetchQuery (not ensureQueryData): prefetchQuery is fire-and-forget;
      // the data will warm the cache without blocking the hover interaction.
      qc.prefetchQuery({
        queryKey: ["instruments", "page-bundle", ticker],
        queryFn: () => createGateway(token).getInstrumentPageBundle(ticker),
        staleTime: 5 * 60_000, // 5 min — page bundle is stable during a session
      });
    }, 200);
  }

  /** Hover end: cancel the pending prefetch if pointer left before 200ms. */
  function handlePointerLeave() {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
  }

  return (
    <div>
      {/* Column headers */}
      <div className="flex items-center h-[20px] px-2 border-b border-[hsl(var(--border-subtle))]">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60 min-w-[60px]">Peers</span>
        <span className="text-[9px] text-muted-foreground/50 ml-auto w-[30px] text-right">P/E</span>
        <span className="text-[9px] text-muted-foreground/50 w-[44px] text-right">Cap</span>
        <span className="text-[9px] text-muted-foreground/50 w-[40px] text-right">1Y</span>
      </div>

      {/* WHY data-table-grid: F1 §16.3 opt-in → 20px --row-h. */}
      <div data-table-grid>
        {isLoading && Array.from({ length: 5 }).map((_, i) => (
          <div key={i} role="row" className="flex items-center h-[var(--row-h,20px)] px-2">
            <span className="text-[10px] text-muted-foreground/30">—</span>
          </div>
        ))}

        {(isEmpty || isError) && (
          <div className="px-2 py-2 text-[10px] text-muted-foreground/60">
            {isError ? "Failed to load peers. " : "No peer data available."}
          </div>
        )}

        {!isLoading && !isEmpty && !isError && peers.map((peer) => (
          <div
            key={peer.instrument_id}
            role="row"
            className="flex items-center h-[var(--row-h,20px)] px-2 cursor-pointer hover:bg-muted/20"
            onClick={() => peer.ticker && router.push(`/instruments/${peer.ticker}`)}
            onPointerEnter={() => handlePointerEnter(peer.ticker)}
            onPointerLeave={handlePointerLeave}
            tabIndex={0}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && peer.ticker) {
                router.push(`/instruments/${peer.ticker}`);
              }
            }}
          >
            {/* Ticker: min-w-[60px] fits BRK.B / BF.B (Δ33). */}
            <span className="text-[10px] font-mono font-semibold text-foreground min-w-[60px]">
              {peer.ticker ?? "—"}
            </span>
            <span className="text-[10px] font-mono tabular-nums text-foreground ml-auto w-[30px] text-right">
              {formatRatio(peer.pe_ratio, "") ?? "—"}
            </span>
            <span className="text-[10px] font-mono tabular-nums text-muted-foreground w-[44px] text-right">
              {formatMarketCap(peer.market_cap)}
            </span>
            <span className={`text-[10px] font-mono tabular-nums w-[40px] text-right ${returnColor(peer.return_1y)}`}>
              {fmtReturn(peer.return_1y) ?? "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
