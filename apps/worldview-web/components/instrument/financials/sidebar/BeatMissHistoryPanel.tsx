/**
 * sidebar/BeatMissHistoryPanel.tsx — Historical EPS beat/miss sparkline
 *
 * WHY THIS EXISTS (T-21): The beat/miss history is a trailing indicator of
 * management's ability to guide and deliver. 4+ consecutive beats suggests
 * conservative guidance practice (premium-multiple signal); a pattern of misses
 * warns of operational volatility. The sparkline encodes the trajectory —
 * analysts see trend without reading individual numbers.
 *
 * WHY REUSE ["earnings-history"] KEY: EarningsBarChart fires this query in the
 * same render cycle. TanStack Query deduplicates on the shared key → zero
 * extra network round-trips. staleTime=24h matches EarningsBarChart.
 *
 * DATA: surprisePercent from EODHD earnings_annual_trend section. Each record's
 *   data = {date, epsActual, epsEstimate, surprisePercent}. Beats ≥ 0, misses < 0.
 *   Null surprise (estimate absent) excluded from beat/miss count.
 *
 * WHO USES IT: AnalystSidebar.tsx (T-24).
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §5.5
 */

"use client";
// WHY "use client": useQuery requires the React QueryClient context.

import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { Sparkline } from "@/components/primitives/Sparkline";

interface BeatMissHistoryPanelProps {
  instrumentId: string;
}

interface EarningsAnnualRecord {
  date?: string | null;
  epsActual?: number | null;
  epsEstimate?: number | null;
  surprisePercent?: number | null;
}

export function BeatMissHistoryPanel({ instrumentId }: BeatMissHistoryPanelProps) {
  const gateway = useApiClient();

  // WHY ["earnings-history"] key (not a sidebar-specific key): EarningsBarChart
  // on the same page fires this exact query. Sharing the key gives zero-cost
  // deduplication — the panel reads from cache, not from a second HTTP call.
  const { data, isLoading } = useQuery({
    queryKey: ["earnings-history", instrumentId],
    queryFn: () => gateway.getEarningsHistory(instrumentId),
    enabled: !!instrumentId,
    staleTime: 24 * 60 * 60 * 1000,
  });

  const records = (data?.records ?? [])
    .map((r) => {
      const d = r.data as EarningsAnnualRecord | undefined;
      return {
        date: d?.date ?? "",
        actual: d?.epsActual ?? null,
        estimate: d?.epsEstimate ?? null,
        surprise: d?.surprisePercent ?? null,
      };
    })
    .filter((r) => !!r.date)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-8); // last 8 fiscal years

  // Separate beats and misses for the caption — only count where both values exist.
  const withSurprise = records.filter((r) => r.surprise != null);
  const beats = withSurprise.filter((r) => (r.surprise ?? 0) >= 0).length;
  const misses = withSurprise.filter((r) => (r.surprise ?? 0) < 0).length;

  // Sparkline data: surprise% values (positive=beat, negative=miss) for color coding.
  // Fall back to actual EPS values when surprise is missing (shows growth trajectory).
  const sparkData = records.map((r) =>
    r.surprise != null ? r.surprise : r.actual ?? 0,
  );

  return (
    <div className="flex flex-col gap-1 px-2 py-2 border-b border-border">
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
        EPS BEAT / MISS
      </span>

      {isLoading && (
        <div className="h-[20px] flex items-center">
          <span className="text-[10px] text-muted-foreground/30">—</span>
        </div>
      )}

      {!isLoading && sparkData.length >= 2 && (
        <div className="flex flex-col gap-0.5">
          <Sparkline
            data={sparkData}
            width={120}
            height={20}
            trend="auto"
            label="EPS beat/miss history"
          />
          {withSurprise.length > 0 && (
            <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
              <span className="text-positive">{beats}B</span>
              {" / "}
              <span className="text-negative">{misses}M</span>
              {" last "}
              {withSurprise.length}Y
            </span>
          )}
        </div>
      )}

      {!isLoading && sparkData.length < 2 && (
        <span className="text-[10px] text-muted-foreground/40">No data</span>
      )}
    </div>
  );
}
