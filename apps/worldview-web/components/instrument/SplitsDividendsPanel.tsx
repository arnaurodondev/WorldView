/**
 * components/instrument/SplitsDividendsPanel.tsx — compact splits + dividends panel
 *
 * WHY THIS EXISTS (PLAN-0088 Wave F-3): the Overview tab needed a Splits/
 * Dividends zone (zone 12 of the 12-zone wireframe) so analysts can see at a
 * glance the dividend yield, payout ratio, ex-date, and last split — the
 * "is this an income stock and when did its share count last change" read.
 * Finviz, Bloomberg Terminal, and Yahoo Finance all surface these numbers
 * front-and-centre on the company overview; previously this only existed
 * deep inside the Fundamentals tab.
 *
 * WHY 4 ROWS (not 8): the Overview is a scan surface. Yield, Payout Ratio,
 * Ex-Date, and Last Split are the four highest-signal datapoints. Anything
 * deeper (full split history, NumberDividendsByYear) lives in the
 * Fundamentals tab where the user explicitly asked for that depth.
 *
 * WHY DERIVED FROM /v1/fundamentals/{id}/splits-dividends: S3/EODHD returns
 * a SNAPSHOT record whose data field carries PayoutRatio, ExDividendDate,
 * DividendDate, LastSplitDate, LastSplitFactor. The dividend yield is on
 * the highlights snapshot already fetched by the parent (passed in via
 * `dividendYield` prop) so we avoid a duplicate fetch.
 *
 * WHO USES IT: OverviewLayout right rail (zone 12)
 * DATA SOURCE:
 *   - S9 GET /v1/fundamentals/{instrument_id}/splits-dividends → ex-date, payout, last split
 *   - parent's fundamentals.dividend_yield → annual yield (decimal)
 * DESIGN REFERENCE: Finviz "Dividends" mini-row, Yahoo Finance "Forward Dividend"
 */

"use client";
// WHY "use client": uses TanStack Query for the splits-dividends fetch.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import type { FundamentalsRecord } from "@/types/api";

interface Props {
  instrumentId: string;
  /** Annual dividend yield as a decimal (e.g. 0.015 = 1.5%). Pass null when unknown. */
  dividendYield: number | null | undefined;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatPercent — render a decimal as a 2-decimal percent string.
 *
 * WHY 2 decimals: dividend yields cluster around 0.5%–4% for liquid US
 * equities; one decimal hides meaningful spread (1.5% vs 1.6% matters for
 * income screens), three decimals add noise without value.
 */
function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

/**
 * formatPercentDirect — render a number that is ALREADY a percent (not decimal).
 *
 * EODHD's PayoutRatio is reported as a decimal (0.127 = 12.7%); this matches
 * formatPercent. ShortPercentFloat is also decimal. Use this only when the
 * upstream has multiplied by 100 already (rare in our pipeline).
 */
function formatPercentDirect(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)}%`;
}

/**
 * formatDate — render an ISO date as "MMM D, YYYY".
 *
 * WHY locale-en-US fixed format: the platform is a single-locale beta. A
 * fixed format avoids hydration-mismatch warnings (server vs client locale
 * differences in Next.js SSR) and gives consistent column widths in the
 * 4-row strip.
 */
function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return "—";
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SplitsDividendsPanel({ instrumentId, dividendYield }: Props) {
  const auth = useAuth();
  const accessToken = auth.accessToken ?? null;

  // WHY enabled-on-token: the parent OverviewLayout renders pre-auth during
  // hydration. Returning enabled:false until accessToken is present prevents
  // a 401-flash in the React Query devtools and keeps the panel quiet during
  // bootstrap.
  const query = useQuery({
    queryKey: ["splits-dividends", instrumentId],
    queryFn: () =>
      createGateway(accessToken).getSplitsDividends(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 5 * 60 * 1000, // splits/dividends snapshot updates ~daily
  });

  // WHY take the most recent SNAPSHOT record: S3 returns an array; in practice
  // only one row exists per instrument, but the API contract allows N. Picking
  // the latest (by ingested_at) future-proofs against history retention.
  const record: FundamentalsRecord | undefined = query.data?.records?.[0];
  const data = record?.data as
    | {
        PayoutRatio?: number | null;
        ExDividendDate?: string | null;
        DividendDate?: string | null;
        LastSplitDate?: string | null;
        LastSplitFactor?: string | null;
      }
    | undefined;

  // ── Render ──────────────────────────────────────────────────────────────────

  if (query.isLoading) {
    // WHY 5 skeleton rows (header + 4 data): matches the rendered shape so
    // the layout doesn't shift when data resolves (CLS prevention).
    return (
      <div className="border-t border-border px-3 py-2">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
          Splits & Dividends
        </div>
        <div className="space-y-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[14px] w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (query.isError || !record) {
    return (
      <div className="border-t border-border px-3 py-2">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
          Splits & Dividends
        </div>
        <InlineEmptyState message="No splits / dividends data" />
      </div>
    );
  }

  return (
    <div className="border-t border-border px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
        Splits & Dividends
      </div>

      {/* WHY 4 rows of label/value: matches the OverviewSidebarMetrics row
          density (h-[22px]). Each row is a single line so the panel takes
          ~110px total — fits beneath the second sparkline panel without
          causing the right rail to overflow on the typical 1080p screen. */}
      <div className="text-xs tabular-nums">
        <Row label="Yield" value={formatPercent(dividendYield)} />
        <Row label="Payout" value={formatPercentDirect((data?.PayoutRatio ?? 0) * 100)} />
        <Row label="Ex-Date" value={formatDate(data?.ExDividendDate)} />
        <Row
          label="Last Split"
          value={
            data?.LastSplitFactor && data?.LastSplitDate
              ? `${data.LastSplitFactor} · ${formatDate(data.LastSplitDate)}`
              : data?.LastSplitFactor || formatDate(data?.LastSplitDate)
          }
        />
      </div>
    </div>
  );
}

// ── Row sub-component ─────────────────────────────────────────────────────────

/**
 * Row — single label/value line at h-[22px].
 *
 * WHY local (not extracted): this row shape is bespoke to the splits panel.
 * Extracting it to a shared MetricRow helper would invite the next caller
 * to add layout-affecting variants (alignment, formatting); keeping it
 * inline preserves a clean composition boundary.
 */
function Row({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="flex items-center justify-between h-[22px]">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground">{value || "—"}</span>
    </div>
  );
}
