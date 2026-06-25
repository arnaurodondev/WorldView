/**
 * components/instrument/quote/strips/PriceLevelsPanel.tsx — key levels panel
 *
 * WHY THIS EXISTS (Wave-2, replaces the "PRICE LEVELS — Unavailable (B-Q-4)"
 * placeholder): the bottom-strip column answering "where is price relative to
 * the levels that matter?" — 52-week range position bar, MA50/MA200 trend
 * cells, and fractal swing-point support/resistance chips.
 *
 * DATA SOURCE: GET /v1/instruments/{id}/price-levels (Wave-1 backend,
 * live-verified 2026-06-10). `sr_method` describes the S/R algorithm and is
 * surfaced as a tooltip on the chips so the levels are auditable, not magic.
 *
 * WHO USES IT: QuoteTab bottom strip (centre column).
 * DESIGN: 20px header + dense mono rows; em-dash for nulls.
 */

"use client";
// WHY "use client": useQuery requires the browser runtime.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";

interface PriceLevelsPanelProps {
  readonly instrumentId: string;
}

// WHY 5 minutes: levels are computed from daily bars + the latest close —
// they move at most once per session; 5m covers the close-update window.
const LEVELS_STALE_MS = 5 * 60 * 1000;

const fmt = (v: number | null | undefined): string => (v == null ? "—" : v.toFixed(2));

export function PriceLevelsPanel({ instrumentId }: PriceLevelsPanelProps) {
  const token = useAccessToken();
  const { data } = useQuery({
    queryKey: qk.instruments.priceLevels(instrumentId),
    queryFn: () => createGateway(token).getPriceLevels(instrumentId),
    // Token-gated (sidebar-fix pattern): never fire a doomed 401 request.
    enabled: !!instrumentId && !!token,
    staleTime: LEVELS_STALE_MS,
  });

  // ── 52-week position (0 = at low, 1 = at high) ─────────────────────────────
  // WHY clamp: a post-close print can momentarily sit outside yesterday's
  // 52w band; the marker must stay inside the bar.
  const lo = data?.low_52w ?? null;
  const hi = data?.high_52w ?? null;
  const last = data?.last_close ?? null;
  const pos =
    lo != null && hi != null && last != null && hi > lo
      ? Math.min(1, Math.max(0, (last - lo) / (hi - lo)))
      : null;

  // MA trend colouring: price above MA = uptrend (green), below = red.
  const maClass = (ma: number | null | undefined): string =>
    ma == null || last == null
      ? "text-muted-foreground/50"
      : last >= ma
        ? "text-positive"
        : "text-negative";

  // S/R chips: nearest-first arrays from the backend; cap at 3 each to fit
  // the column. Tooltip carries the algorithm description (sr_method).
  const support = (data?.support ?? []).slice(0, 3);
  const resistance = (data?.resistance ?? []).slice(0, 3);
  const srTitle = data?.sr_method ?? "Support/resistance method unavailable";

  return (
    <div className="flex flex-col h-full overflow-hidden" data-testid="price-levels-panel">
      {/* Column header — matches the sibling bottom-strip column style. */}
      <div className="flex items-center h-[20px] px-2 border-b border-border/40 flex-shrink-0">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">
          Price Levels
        </span>
      </div>

      <div className="flex flex-col gap-1 px-2 py-1 overflow-hidden">
        {/* ── 52W range bar: low … ▲marker … high ─────────────────────────── */}
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] font-mono text-muted-foreground shrink-0">{fmt(lo)}</span>
          <div className="relative h-[4px] flex-1 rounded-full bg-muted/40" aria-label="52-week range position">
            {pos != null && (
              // The marker: a 2px primary tick at the price's position within
              // the 52w band. translateX(-50%) centres it on the percentage.
              <div
                data-testid="range-marker"
                className="absolute top-[-2px] h-[8px] w-[2px] bg-primary"
                style={{ left: `${pos * 100}%`, transform: "translateX(-50%)" }}
              />
            )}
          </div>
          <span className="text-[9px] font-mono text-muted-foreground shrink-0">{fmt(hi)}</span>
        </div>
        {/* Distance from the band edges — percent-form straight from the API. */}
        <div className="flex justify-between text-[9px] font-mono text-muted-foreground/70">
          <span>{data?.pct_from_52w_low != null ? `+${data.pct_from_52w_low.toFixed(1)}% off low` : "—"}</span>
          <span>{data?.pct_from_52w_high != null ? `${data.pct_from_52w_high.toFixed(1)}% off high` : "—"}</span>
        </div>

        {/* ── MA50 / MA200 vs price ───────────────────────────────────────── */}
        <div className="flex items-baseline gap-3">
          <span className="text-[9px] uppercase font-mono text-muted-foreground">MA50</span>
          <span className={`text-[10px] font-mono tabular-nums ${maClass(data?.ma_50)}`}>{fmt(data?.ma_50)}</span>
          <span className="text-[9px] uppercase font-mono text-muted-foreground">MA200</span>
          <span className={`text-[10px] font-mono tabular-nums ${maClass(data?.ma_200)}`}>{fmt(data?.ma_200)}</span>
        </div>

        {/* ── Support / resistance chips (tooltip = algorithm) ─────────────── */}
        <div className="flex items-center gap-1 overflow-hidden" title={srTitle}>
          <span className="text-[9px] uppercase font-mono text-muted-foreground shrink-0">S</span>
          {support.length > 0 ? support.map((s) => (
            <span key={`s-${s}`} className="rounded-[2px] bg-positive/10 px-1 text-[9px] font-mono tabular-nums text-positive">
              {s.toFixed(2)}
            </span>
          )) : <span className="text-[9px] font-mono text-muted-foreground/50">—</span>}
          <span className="ml-1 text-[9px] uppercase font-mono text-muted-foreground shrink-0">R</span>
          {resistance.length > 0 ? resistance.map((r) => (
            <span key={`r-${r}`} className="rounded-[2px] bg-negative/10 px-1 text-[9px] font-mono tabular-nums text-negative">
              {r.toFixed(2)}
            </span>
          )) : <span className="text-[9px] font-mono text-muted-foreground/50">—</span>}
        </div>
      </div>
    </div>
  );
}
