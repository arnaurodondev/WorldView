/**
 * components/instrument/PerformanceBar.tsx — multi-timeframe % change strip
 *
 * WHY THIS EXISTS: TradingView and Finviz both display a horizontal strip of
 * timeframe-bucket % changes (1D / 5D / 1M / 3M / 6M / YTD / 1Y / 5Y) at the
 * top of every symbol page. Analysts use it to instantly answer "is this hot
 * short-term but cold long-term, or vice-versa?" without reading the chart.
 *
 * WHY DERIVED CLIENT-SIDE (no extra endpoint): the standalone /v1/ohlcv
 * endpoint already returns daily bars going back 30+ years for AAPL.
 * Computing % change between two bars is O(1). No new backend route needed —
 * we reuse the OHLCVChart's data fetch via TanStack Query cache.
 *
 * WHY 22px ROW HEIGHT: matches the §0.1 Terminal UI v3 data-row standard. The
 * chips inside are h-[18px] with 2px breathing room above/below, giving the
 * row a consistent rhythm with the SessionStatsStrip (also h-[22px]).
 *
 * WHY tabular-nums + font-mono on numeric values: required by the global
 * Terminal Dark numeric-display rule (BP / DESIGN_SYSTEM convention).
 * Prevents jitter when the auto-refresh updates the latest bar.
 *
 * WHO USES IT: OverviewLayout (top of Overview tab, between AISubheader and chart)
 * DATA SOURCE: TanStack Query cache key ["ohlcv", instrumentId, "1d"] —
 *              shares the same fetch as OHLCVChart for zero overhead.
 * DESIGN REFERENCE: TradingView "Performance" strip; Finviz "Performance" row.
 */

"use client";
// WHY "use client": uses useQuery (TanStack Query is a client hook).

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type { OHLCVBar } from "@/types/api";

// ── Window definitions ───────────────────────────────────────────────────────
// WHY trading-day counts (not calendar): financial industry standard. 1M = 21
// trading days (≈ 1 calendar month minus weekends), 1Y = 252 trading days.
// We compute against the most-recent N bars in the daily timeframe series.
// "YTD" is special — uses calendar year-start, not a trading-day count.
interface WindowDef {
  /** Display label shown in the chip (uppercase 10px). */
  readonly label: string;
  /**
   * Trading-day lookback. `null` means "year-start" (YTD logic).
   * 1D=1, 5D=5, 1M=21, 3M=63, 6M=126, 1Y=252, 5Y=1260.
   */
  readonly tradingDays: number | "ytd";
}

const WINDOWS: readonly WindowDef[] = [
  { label: "1D", tradingDays: 1 },
  { label: "5D", tradingDays: 5 },
  { label: "1M", tradingDays: 21 },
  { label: "3M", tradingDays: 63 },
  { label: "6M", tradingDays: 126 },
  { label: "YTD", tradingDays: "ytd" },
  { label: "1Y", tradingDays: 252 },
  { label: "5Y", tradingDays: 1260 },
];

// ── Props ─────────────────────────────────────────────────────────────────────

interface PerformanceBarProps {
  /** Instrument market_data_id — used to fetch /v1/ohlcv?timeframe=1d. */
  readonly instrumentId: string;
}

// ── Helper: compute % change between two bars ────────────────────────────────
// WHY null-safe: bars[i].close is decimal-as-string in some adapters, number
// in others. We coerce via Number() and bail to null if non-finite.
function pctChange(latest: OHLCVBar | undefined, prior: OHLCVBar | undefined): number | null {
  if (!latest || !prior) return null;
  const a = Number(latest.close);
  const b = Number(prior.close);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b === 0) return null;
  return ((a - b) / b) * 100;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PerformanceBar({ instrumentId }: PerformanceBarProps) {
  const { accessToken } = useAuth();

  // WHY same query key as OHLCVChart: TanStack Query dedupes — both components
  // share one network fetch when the user opens the Overview tab. Memory/CPU win.
  // staleTime 5min: daily bars don't change within 5 minutes during market hours.
  const { data } = useQuery({
    queryKey: ["ohlcv", instrumentId, "1d"],
    queryFn: () => createGateway(accessToken).getOHLCV(instrumentId, { timeframe: "1d" }),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 5 * 60_000,
  });

  // WHY useMemo: re-computing 8 % changes only when bars change. Without memo
  // the values would recompute on every parent re-render (e.g., when the user
  // hovers any control on the page).
  const perf = useMemo(() => {
    const bars = data?.bars ?? [];
    if (bars.length === 0) return null;

    // Latest bar = most recent close. Bars are oldest-first.
    const latest = bars[bars.length - 1];

    // WHY date parse: we need this for the YTD index search.
    const latestYear = new Date(latest.timestamp).getUTCFullYear();

    // For each window, compute % change vs the bar `tradingDays` ago.
    return WINDOWS.map((w) => {
      let prior: OHLCVBar | undefined;
      if (w.tradingDays === "ytd") {
        // WHY scan backwards: find the LAST bar from the previous year (year-end
        // close). Standard YTD reference point used by Yahoo / Finviz / TradingView.
        for (let i = bars.length - 2; i >= 0; i--) {
          const y = new Date(bars[i].timestamp).getUTCFullYear();
          if (y < latestYear) {
            prior = bars[i];
            break;
          }
        }
      } else {
        // WHY -1 (not full lookback): bars[length-1] is "today" so the comparison
        // bar is `tradingDays` indices back. We clamp so requesting more days than
        // we have falls back to the OLDEST available bar (5Y on a stock with 3y
        // history shows the 3y % change instead of nothing).
        const idx = Math.max(0, bars.length - 1 - w.tradingDays);
        prior = bars[idx];
      }
      return { label: w.label, pct: pctChange(latest, prior) };
    });
  }, [data?.bars]);

  // ── Empty state ──────────────────────────────────────────────────────────────
  // WHY render the chip skeleton (not a full skeleton block): keeps the row
  // height stable so the chart below doesn't jump on first paint.
  if (!perf) {
    return (
      <div className="flex items-center h-[22px] px-2 gap-1 border-b border-border/40 overflow-x-auto">
        {WINDOWS.map((w) => (
          <span
            key={w.label}
            className="rounded-[2px] border border-border/30 bg-card/50 px-1.5 py-0 font-mono text-[10px] tabular-nums text-muted-foreground/40"
          >
            {w.label} —
          </span>
        ))}
      </div>
    );
  }

  return (
    // WHY border-b: visual separator between this strip and the chart below.
    // WHY overflow-x-auto: on narrow viewports (phones) the chips can scroll
    //   horizontally instead of wrapping (preserves single-line analyst reflex).
    <div
      className="flex items-center h-[22px] px-2 gap-1 border-b border-border/40 overflow-x-auto"
      role="group"
      aria-label="Performance across timeframes"
    >
      {perf.map(({ label, pct }) => {
        // WHY null-check separately: when a window has no data (e.g. 5Y on a
        // newly-listed stock), show an em-dash so the user sees "no data" not
        // "0%".
        if (pct == null) {
          return (
            <span
              key={label}
              className="shrink-0 rounded-[2px] border border-border/30 bg-card/50 px-1.5 font-mono text-[10px] tabular-nums text-muted-foreground/40"
              title={`${label} — no data`}
            >
              <span className="opacity-60">{label}</span> <span>—</span>
            </span>
          );
        }
        // WHY color-coded: positive / negative is the primary scan target.
        // The label itself stays muted — eye should land on the number first.
        const isUp = pct >= 0;
        const colorClass = isUp ? "text-positive" : "text-negative";
        const sign = isUp ? "+" : "";
        return (
          <span
            key={label}
            className="shrink-0 rounded-[2px] border border-border/30 bg-card/50 px-1.5 font-mono text-[10px] tabular-nums"
            title={`${label} change`}
          >
            <span className="text-muted-foreground">{label}</span>{" "}
            <span className={colorClass}>
              {sign}
              {pct.toFixed(2)}%
            </span>
          </span>
        );
      })}
    </div>
  );
}
