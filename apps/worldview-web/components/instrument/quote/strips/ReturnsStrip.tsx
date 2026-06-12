/**
 * components/instrument/quote/strips/ReturnsStrip.tsx — multi-period returns row
 *
 * WHY THIS EXISTS (Wave-2, replaces the "RETURNS · Backend endpoint pending
 * (B-Q-3)" placeholder): a single 22px row answering "how has this name done
 * over every horizon?" — 1D 1W 1M 3M 6M YTD 1Y 3Y 5Y, colour-coded by sign.
 * This is the Bloomberg GP-style returns ribbon.
 *
 * DATA SOURCE: GET /v1/instruments/{id}/returns (Wave-1 backend, live-verified
 * 2026-06-10). UNITS: percent-form numbers (-7.93 = -7.93%) → rendered with
 * formatPercentDirect. A null horizon (insufficient price history, e.g. 3Y/5Y
 * in dev data) renders an em-dash — never a fake 0.00%.
 *
 * WHO USES IT: QuoteTab (left column, under the intraday stats strip).
 * DESIGN: 22px strip, 10px mono uppercase labels + 11px mono values (ADR-F-15).
 */

"use client";
// WHY "use client": useQuery requires the browser runtime.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { formatPercentDirect } from "@/lib/utils";
import { RETURN_HORIZONS } from "@/lib/api/instruments";

interface ReturnsStripProps {
  readonly instrumentId: string;
}

// WHY 5 minutes: returns shift with each new bar; the strip is context, not a
// trading signal — sub-minute freshness buys nothing here.
const RETURNS_STALE_MS = 5 * 60 * 1000;

/** Sign → colour class. Null/undefined → muted (rendered as "—"). */
function returnClass(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground/50";
  return v >= 0 ? "text-positive" : "text-negative";
}

export function ReturnsStrip({ instrumentId }: ReturnsStripProps) {
  const token = useAccessToken();
  const { data } = useQuery({
    queryKey: qk.instruments.multiPeriodReturns(instrumentId),
    queryFn: () => createGateway(token).getMultiPeriodReturns(instrumentId),
    // WHY token in enabled (BP from the sidebar fix): firing before the token
    // hydrates 401s and the settled error never self-heals.
    enabled: !!instrumentId && !!token,
    staleTime: RETURNS_STALE_MS,
  });

  return (
    // h-[22px]: the Quote tab's standard strip rhythm. overflow-x-auto keeps
    // all 9 horizons reachable on tablet widths instead of clipping.
    <div
      className="flex h-[22px] min-w-0 items-center gap-3 overflow-x-auto border-t border-border/50 bg-background px-3"
      aria-label="Multi-period returns"
      data-testid="returns-strip"
    >
      <span className="shrink-0 text-[9px] uppercase tracking-widest text-muted-foreground/60 font-mono">
        Returns
      </span>
      {RETURN_HORIZONS.map((h) => {
        const v = data?.returns?.[h] ?? null;
        return (
          <span key={h} className="flex items-baseline gap-1 shrink-0">
            <span className="text-[10px] uppercase text-muted-foreground font-mono">{h}</span>
            {/* WHY formatPercentDirect: the API already speaks percent form
                (live-verified) — formatPercent would divide by 100 twice. */}
            <span className={`text-[11px] font-mono tabular-nums ${returnClass(v)}`}>
              {v != null ? formatPercentDirect(v) : "—"}
            </span>
          </span>
        );
      })}
    </div>
  );
}
