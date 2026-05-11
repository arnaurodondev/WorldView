/**
 * components/instrument/OwnershipSnapshotPanel.tsx — Ownership structure panel
 *
 * WHY THIS EXISTS: Institutional ownership is a key signal for institutional traders.
 * Stocks with >60% institutional ownership are under constant analyst scrutiny;
 * those with high insider ownership have "skin in the game" — both signal commitment.
 * Bloomberg DES shows ownership breakdown prominently in the fundamentals view.
 *
 * WHY SHARE STATISTICS ENDPOINT: The S3 market-data service stores share-statistics
 * snapshots from EODHD's Statistics endpoint. This data includes institutional %,
 * insider %, shares outstanding, float, and short interest — all in one endpoint.
 *
 * WHY CAST TO SHARESTATISTICSDATA: The S3 fundamentals section API returns
 * `records[].data` as `Record<string, unknown>` (the database stores generic JSON).
 * We cast to `ShareStatisticsData` for typed access. All field accesses are
 * null-guarded because the cast is not validated at runtime.
 *
 * WHO USES IT: FundamentalsTab right sidebar (Wave D-2)
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrumentId}/share-statistics
 * DESIGN REFERENCE: PLAN-0041 §T-D-2-04
 */

"use client";
// WHY "use client": uses useQuery for share statistics fetch.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPercentDirect } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface OwnershipSnapshotPanelProps {
  instrumentId: string;
}

// ── Sub-component ─────────────────────────────────────────────────────────────

function MetricRow({ label, value, valueClass = "text-foreground" }: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center h-[22px] px-2 border-b border-border/30 last:border-0">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1 truncate">
        {label}
      </span>
      <span className={`font-mono text-[11px] tabular-nums text-right ${valueClass}`}>
        {value}
      </span>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatShares — convert raw share count to human-readable string
 *
 * WHY billions threshold: shares outstanding for large caps (AAPL: 15.4B) would
 * display as "15,400,000,000" without formatting — unreadable at 11px font.
 * "15.4B" matches Bloomberg's share count display convention.
 */
function formatShares(shares: number | null | undefined): string {
  if (shares == null) return "—";
  if (shares >= 1e12) return `${(shares / 1e12).toFixed(2)}T`;
  if (shares >= 1e9) return `${(shares / 1e9).toFixed(2)}B`;
  if (shares >= 1e6) return `${(shares / 1e6).toFixed(2)}M`;
  return shares.toLocaleString();
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OwnershipSnapshotPanel({ instrumentId }: OwnershipSnapshotPanelProps) {
  const { accessToken } = useAuth();

  // ── Fetch share statistics ─────────────────────────────────────────────────
  // WHY staleTime 600_000: ownership percentages change on a quarterly/annual
  // schedule (13-F filings). 10-minute stale window is well within the filing cycle.
  const { data, isLoading } = useQuery({
    queryKey: ["share-statistics", instrumentId],
    queryFn: () => createGateway(accessToken).getShareStatistics(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 600_000,
  });

  // ── Extract ownership data from first record ──────────────────────────────
  // WHY records[0]: share-statistics is a snapshot (single latest record), not
  // a time series. The endpoint always returns the most recent snapshot as records[0].
  //
  // WHY PascalCase interface: S3 stores share-statistics from EODHD as raw
  // PascalCase keys (EODHD API format). The canonical ShareStatisticsData type uses
  // snake_case for type clarity, but the wire format is PascalCase. We use a local
  // type for the raw cast — no runtime validation occurs either way.
  //
  // WHY percentages are direct (e.g., 65.325 = 65.325%): EODHD returns ownership
  // percentages as pre-multiplied values, not decimals. PercentInstitutions: 65.325
  // means 65.325%. Use formatPercentDirect (not formatPercent which multiplies by 100).
  interface S3ShareStatsRaw {
    SharesOutstanding?: number | null;
    SharesFloat?: number | null;
    PercentInsiders?: number | null;     // e.g. 1.64 = 1.64%
    PercentInstitutions?: number | null; // e.g. 65.325 = 65.325%
    ShortRatio?: number | null;
    ShortPercentFloat?: number | null;   // e.g. 0.0086 = 0.86% (decimal, not percent)
  }
  const stats =
    (data?.records?.[0]?.data as S3ShareStatsRaw | undefined) ?? null;

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div>
        <div className="flex items-center border-b border-border px-2 h-6">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            OWNERSHIP
          </span>
        </div>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center h-[22px] px-2 gap-2">
            <Skeleton className="h-3 w-20 flex-none" />
            <Skeleton className="h-3 flex-1" />
          </div>
        ))}
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  if (!stats) {
    return (
      <div>
        <div className="flex items-center border-b border-border px-2 h-6">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            OWNERSHIP
          </span>
        </div>
        <div className="px-2 py-1.5 text-[10px] font-mono text-muted-foreground">
          Ownership data pending
        </div>
      </div>
    );
  }

  // ── Institutional holding color ───────────────────────────────────────────
  // WHY >60 green: high institutional ownership signals analyst coverage and
  // market confidence. <30 signals potential governance risk (lack of oversight).
  // WHY threshold 60/30 (not 0.60/0.30): PercentInstitutions is a direct percentage
  // (65.325 = 65.325%), not a decimal (0.65325). Thresholds must match the scale.
  const instPct = stats.PercentInstitutions ?? 0;
  const instClass =
    instPct > 60
      ? "text-positive"
      : instPct < 30 && instPct > 0
        ? "text-warning"
        : "text-foreground";

  return (
    <div>
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          OWNERSHIP
        </span>
      </div>

      {/* ── Row 1: Institutional % ──────────────────────────────────────── */}
      {/* WHY show institutional first: it's the most institutionally relevant metric.
          High institutional % = analysts watching, forced selling on downgrades. */}
      <MetricRow
        label="INSTITUTIONAL"
        value={formatPercentDirect(stats.PercentInstitutions ?? null)}
        valueClass={instClass}
      />

      {/* ── Row 2: Insider % ────────────────────────────────────────────── */}
      {/* WHY green >5%: insider ownership above 5% is a governance positive —
          executives have meaningful "skin in the game" per Buffett framework.
          WHY threshold 5 (not 0.05): PercentInsiders is direct % (1.64 = 1.64%). */}
      <MetricRow
        label="INSIDER"
        value={formatPercentDirect(stats.PercentInsiders ?? null)}
        valueClass={(stats.PercentInsiders ?? 0) > 5 ? "text-positive" : "text-foreground"}
      />

      {/* ── Row 3: Shares Outstanding ─────────────────────────────────── */}
      <MetricRow
        label="SHARES OUT"
        value={formatShares(stats.SharesOutstanding)}
      />

      {/* ── Row 4: Float ────────────────────────────────────────────────── */}
      {/* WHY show float: float = actual tradeable shares; small float → high
          volatility on institutional order flow. Analysts screen for low float. */}
      <MetricRow
        label="FLOAT"
        value={formatShares(stats.SharesFloat)}
      />
    </div>
  );
}
