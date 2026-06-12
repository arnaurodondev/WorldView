/**
 * components/instrument/quote/strips/IntradayStatsStrip.tsx — session stats row
 *
 * WHY THIS EXISTS (Wave-2, replaces BOTH the OHLCV-bar-derived
 * SessionStatsStrip and the "INTRADAY STATS · pending (B-Q-2)" placeholder):
 * the dedicated intraday-stats endpoint is strictly richer than the last
 * chart bar — it adds PREV CLOSE, a real VWAP (tagged with the bar resolution
 * it was computed from) and the session-volume-vs-30-day-average ratio that
 * makes unusual activity scannable in one glance.
 *
 * DATA SOURCE: GET /v1/instruments/{id}/intraday-stats (Wave-1 backend,
 * live-verified 2026-06-10). All fields nullable → "—".
 *
 * WHO USES IT: QuoteTab (left column, directly under the KeyStatsBar).
 * DESIGN: 22px strip, Bloomberg O/H/L row conventions — session high in
 * positive green, session low in negative red.
 */

"use client";
// WHY "use client": useQuery requires the browser runtime.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { formatVolume } from "@/lib/utils";

interface IntradayStatsStripProps {
  readonly instrumentId: string;
}

// WHY 60s: this strip is the page's most session-live surface (it tracks the
// forming session), but it is still summary data — a minute keeps it honest
// without per-tick polling.
const INTRADAY_STALE_MS = 60 * 1000;

/** 2-dp price or em-dash. Local (not formatPrice) — the strip is $-implied. */
const fmt = (v: number | null | undefined): string => (v == null ? "—" : v.toFixed(2));

/** One LABEL value cell — identical typography to KeyStatsBar's StatCell. */
function Stat({ label, value, valueClass = "text-foreground", title }: {
  label: string; value: string; valueClass?: string; title?: string;
}) {
  return (
    <span className="flex items-baseline gap-1 shrink-0" title={title}>
      <span className="text-[10px] uppercase text-muted-foreground font-mono">{label}</span>
      <span className={`text-[11px] font-mono tabular-nums ${valueClass}`}>{value}</span>
    </span>
  );
}

/** Thin vertical rule between cells — house separator glyph. */
function Rule() {
  return <span className="text-[10px] text-border" aria-hidden="true">│</span>;
}

export function IntradayStatsStrip({ instrumentId }: IntradayStatsStripProps) {
  const token = useAccessToken();
  const { data } = useQuery({
    queryKey: qk.instruments.intradayStats(instrumentId),
    queryFn: () => createGateway(token).getIntradayStats(instrumentId),
    // Token-gated (sidebar-fix pattern): never fire a doomed 401 request.
    enabled: !!instrumentId && !!token,
    staleTime: INTRADAY_STALE_MS,
  });

  // Volume vs 30-day average: ratio ≥1.5 (unusually heavy) renders amber so
  // the analyst's eye snags on it; otherwise neutral. Null → hidden cell.
  const ratio = data?.volume_vs_30d_ratio ?? null;
  const ratioText = ratio != null ? `${(ratio * 100).toFixed(0)}%` : "—";
  const ratioClass = ratio != null && ratio >= 1.5 ? "text-warning" : "text-foreground";

  return (
    <div
      className="flex h-[22px] min-w-0 items-center gap-4 overflow-x-auto border-t border-border/50 bg-background px-3"
      aria-label="Intraday session statistics"
      data-testid="intraday-stats-strip"
    >
      <span className="shrink-0 text-[9px] uppercase tracking-widest text-muted-foreground/60 font-mono">
        Session
      </span>
      <Stat label="O" value={fmt(data?.open)} />
      <Rule />
      {/* Session high green / low red — Bloomberg O/H/L row convention. */}
      <Stat label="H" value={fmt(data?.day_high)} valueClass="text-positive" />
      <Rule />
      <Stat label="L" value={fmt(data?.day_low)} valueClass="text-negative" />
      <Rule />
      <Stat label="PREV CL" value={fmt(data?.prev_close)} />
      <Rule />
      {/* VWAP source ("1m"/"5m"/"1h") in the tooltip — the precision of the
          number depends on the bar resolution it was computed from. */}
      <Stat
        label="VWAP"
        value={fmt(data?.vwap)}
        title={data?.vwap_source ? `VWAP computed from ${data.vwap_source} bars` : undefined}
      />
      <Rule />
      <Stat label="VOL" value={data?.volume != null ? formatVolume(data.volume) : "—"} />
      <Rule />
      {/* vs 30D: session volume as % of the 30-day average — the "is today
          unusual?" cell. ≥150% renders amber. */}
      <Stat
        label="VS 30D"
        value={ratioText}
        valueClass={ratioClass}
        title="Session volume as a percentage of the 30-day average"
      />
    </div>
  );
}
