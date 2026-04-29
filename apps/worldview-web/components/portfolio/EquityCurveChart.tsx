/**
 * components/portfolio/EquityCurveChart.tsx — Portfolio equity curve (PLAN-0046 Wave 5 / T-46-5-04)
 *
 * WHY THIS EXISTS: A line chart of portfolio total_value over time is the
 * single most important "how am I doing?" surface for a portfolio manager.
 * Every finance terminal (Bloomberg PORT, Schwab, Fidelity) puts the equity
 * curve at the top of the portfolio view. Numbers tell you the present;
 * the curve tells you the trajectory.
 *
 * WHY RECHARTS (not lightweight-charts): lightweight-charts is purpose-built
 * for OHLCV candlesticks (huge datasets, crosshair tooling). Equity curves
 * are simple line series — Recharts gives us a sane Tooltip API,
 * ResponsiveContainer, and tab-friendly resizing without the OHLCV-specific
 * baggage. Recharts is already in this project's bundle (used by sparklines,
 * earnings chart) — no new dependency.
 *
 * WHY PERIOD TOGGLE 1M/3M/6M/1Y/All (not 1D): the equity curve is a cumulative
 * series. 1D would only show one or two snapshot points which is meaningless;
 * the shortest informative window is 1M (~22 trading days).
 *
 * WHY HOVER TOOLTIP shows date + value + cost basis + return %: cost basis
 * lets the user instantly see "is the curve above or below my breakeven?";
 * return % lets them compare against the period selector.
 *
 * DATA SOURCE: S9 GET /v1/portfolios/{id}/value-history → S1 daily snapshots.
 * The snapshot worker writes once per trading day at 21:30 UTC (after US close).
 * For a portfolio with no snapshots yet, the chart shows an empty state.
 *
 * DESIGN REFERENCE: PLAN-0046 Wave 5 spec, Midnight Pro palette.
 */

"use client";
// WHY "use client": Recharts is a client-side renderer; useState for the
// period selector; useQuery for fetching snapshots.

import { useMemo, useState } from "react";
// F-P-003 (PLAN-0051 W6): the period state is OPTIONALLY controlled by the
// parent page now so other panels (KPI strip, analytics) can react to the
// same period the user picks here. We keep the local useState as a fallback
// so existing call sites that don't lift state continue to work.
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  type TooltipProps,
} from "recharts";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice, formatPercent, cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";

// ── Formatting helpers ────────────────────────────────────────────────────────

/**
 * Format the next-snapshot ISO timestamp ("2026-04-29T21:30:00+00:00") as a
 * concise "YYYY-MM-DD HH:MM UTC" string for the empty-state hint (F-009).
 *
 * WHY a custom formatter (not toLocaleString): we want the displayed time to
 * be in UTC verbatim — telling the user "Next snapshot scheduled for 2026-04-29
 * 21:30 UTC" is more honest than rendering it in local time, where 21:30 UTC
 * could appear as 5:30 PM in New York or 7:30 AM in Sydney depending on
 * locale. UTC is the system's canonical scheduling timezone.
 */
function formatNextSnapshotHint(iso: string): string {
  // Defensive: invalid ISO falls back to the raw string so the user still
  // sees something rather than "Invalid Date".
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  const yyyy = parsed.getUTCFullYear();
  const mm = String(parsed.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(parsed.getUTCDate()).padStart(2, "0");
  const hh = String(parsed.getUTCHours()).padStart(2, "0");
  const min = String(parsed.getUTCMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min} UTC`;
}

// ── Period configuration ──────────────────────────────────────────────────────

/**
 * Period toggle options. The numeric value is days-back from today —
 * passed verbatim as the ``from`` query param to /value-history.
 *
 * "All" maps to a sentinel (10 years) so the API still receives a real
 * ``from`` date but in practice picks up every snapshot. An undefined
 * ``from`` would let the server's 90-day default kick in, defeating
 * the purpose of "All".
 */
// F-022: "All" is now an open-ended sentinel. The server treats a missing
// ``from`` query param as "every snapshot since the earliest one", so a
// 10-year clamp is no longer required. ``days: null`` is the marker for
// the gateway call below.
// F-212 (QA iter-2): re-added "1W" — iter-1 silently dropped it when adding
// "All". 1W matches the rest of the dashboard's KPI lookback selector and
// is a common short-horizon trader view.
//
// F-P-006 (PLAN-0051 W6): WHY no "1D" button here:
// The equity curve plots cumulative portfolio value over time, sourced from
// daily snapshots written by the snapshot worker exactly once per trading
// day at 21:30 UTC (after US close). A "1D" view would show, at most, ONE
// data point — there's no intraday curve to draw because we don't take
// intraday snapshots. If/when we add an intraday snapshot stream (e.g. every
// 15 min via S3 quotes), restore "1D" to this array AND update the worker
// schedule. Until then the shortest informative window is 1W (~5 trading
// days).
//
// F-P-022 (PLAN-0051 W6): Canonical period set is the array below.
// DO NOT silently re-add removed periods (e.g. "1S" / "1M" subsets that
// were considered and dropped) — every period must justify its slot in
// the toggle row. Adding a period without removing one crowds the header.
const PERIODS = [
  { label: "1W", days: 7 },
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
  { label: "All", days: null },
] as const;

export type PeriodLabel = (typeof PERIODS)[number]["label"];

// ── Props ─────────────────────────────────────────────────────────────────────

export interface EquityCurveChartProps {
  /** Portfolio UUID (or ROOT id for the aggregate view). */
  portfolioId: string;
  /**
   * F-P-003 (PLAN-0051 W6): optional controlled period.
   * When provided, the chart treats this as the source of truth and
   * notifies the parent via ``onPeriodChange``. When omitted, the chart
   * falls back to local state (preserves backward-compat with existing
   * mount points that don't care about the period).
   *
   * WHY optional (not required): existing tests + non-portfolio callers
   * mount this component without a controller, and it should still work.
   * Lifting state is opt-in for the parent that wants cross-panel sync.
   */
  period?: PeriodLabel;
  onPeriodChange?: (p: PeriodLabel) => void;
}

// ── Tooltip ──────────────────────────────────────────────────────────────────

/**
 * Custom tooltip — Recharts default tooltip is too generic. We render
 * the date, total value, cost basis, and the cumulative return % so the
 * user gets all four numbers without leaving the chart.
 *
 * WHY tabular-nums + font-mono inline: the Tooltip is rendered inside
 * Recharts' SVG layer, OUTSIDE the main React tree the rest of the page
 * cascades from. Tailwind classes still apply (Recharts uses portals to
 * the document body), but inheriting font-mono from a parent is unreliable.
 * Setting it explicitly is the safe pattern.
 */
interface PointShape {
  date: string;
  value: number;
  cost_basis: number;
  cash: number;
  // F-501 (QA iter-5): per-point data-quality flag mirrored from S1.
  // Always present after the gateway normalises ``undefined`` → ``"ok"``,
  // but typed as optional so legacy data shapes (e.g. fixtures) still pass.
  data_quality?: string;
}

function ChartTooltip({ active, payload }: TooltipProps<number, string>) {
  // payload[0].payload is the original data row (our PointShape).
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload as PointShape;
  // WHY guard the cost basis: a brand-new portfolio with no transactions
  // would have cost_basis === 0 → division produces Infinity. Show "—".
  const returnPct =
    point.cost_basis > 0
      ? ((point.value - point.cost_basis) / point.cost_basis) * 100
      : null;

  // F-501: render a "Partial prices" caveat when the snapshot was patched
  // up via the F-401 fallback (stale close or cost-basis substitution).
  // WHY a yellow/warning caption (not red): "partial_prices" is an honest
  // estimate within the F-401 1% tolerance, not an error — yellow signals
  // "trust but verify" rather than "broken". Uses the design-system
  // `--warning` token (resolves via globals.css HSL triplet) for parity
  // with every other warning surface in the app.
  const isPartial = point.data_quality && point.data_quality !== "ok";

  return (
    <div
      // WHY raw bg-popover / border-border / text-foreground tokens: Midnight
      // Pro palette is wired into Tailwind config — these CSS vars resolve
      // to the correct colours in dark mode without us referencing hex.
      // F-P-021 (PLAN-0051 W6): switched bg-card → bg-popover.
      // ``bg-card`` is the panel-level token (#111113) which is the same
      // tone as the equity-curve panel BEHIND the tooltip — the tooltip
      // disappeared into the panel in dark mode (gray-on-gray). The
      // ``bg-popover`` token (#18181B) is one elevation step above
      // bg-card so the tooltip floats clearly above the panel. The
      // popover token is also what shadcn DropdownMenu / HoverCard use,
      // so this matches the system's elevation hierarchy.
      className="bg-popover border border-border rounded-[2px] px-2 py-1.5 shadow-md text-foreground"
    >
      <div className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground mb-1">
        {point.date}
      </div>
      {isPartial && (
        // F-501: tiny caption below the date so the badge sits in the
        // metadata zone of the tooltip (not in the numbers grid where it
        // would compete with Value/Cost/Return for visual weight).
        <div
          className="text-[10px] leading-tight mb-1"
          style={{ color: "hsl(var(--warning))" }}
          // WHY inline style for the colour: the `--warning` HSL triplet
          // is defined in globals.css but Tailwind's arbitrary value
          // resolver doesn't pick it up consistently inside Recharts'
          // portal-rendered Tooltip. An explicit `style` attribute is the
          // safe escape hatch — same pattern the chart line itself uses.
        >
          Partial prices
        </div>
      )}
      <div className="font-mono tabular-nums text-[11px] space-y-0.5">
        <div className="flex justify-between gap-3">
          <span className="text-muted-foreground">Value</span>
          <span className="text-foreground">{formatPrice(point.value)}</span>
        </div>
        <div className="flex justify-between gap-3">
          <span className="text-muted-foreground">Cost</span>
          <span className="text-foreground">{formatPrice(point.cost_basis)}</span>
        </div>
        <div className="flex justify-between gap-3">
          <span className="text-muted-foreground">Return</span>
          <span
            className={
              returnPct == null
                ? "text-muted-foreground"
                : returnPct >= 0
                ? "text-positive"
                : "text-negative"
            }
          >
            {returnPct == null
              ? "—"
              : `${returnPct >= 0 ? "+" : ""}${formatPercent(returnPct / 100)}`}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── EquityCurveChart ─────────────────────────────────────────────────────────

export function EquityCurveChart({
  portfolioId,
  period: controlledPeriod,
  onPeriodChange,
}: EquityCurveChartProps) {
  const { accessToken } = useAuth();

  // Default 3M — matches the Bloomberg PORT default. Long enough to show
  // a meaningful trend without compressing recent moves.
  // F-P-003: dual-mode period state.
  // - controlled: parent passes `period` + `onPeriodChange` → we never
  //   call the local setter and always read from props.
  // - uncontrolled: parent passes neither → we manage period locally.
  // WHY this pattern (and not just "always controlled"): keeps the
  // component a drop-in replacement for the old API. Tests like
  // equity-curve-empty-state.test.tsx mount it with only `portfolioId`
  // and never touch the period — they continue to work.
  const [localPeriod, setLocalPeriod] = useState<PeriodLabel>("3M");
  const period = controlledPeriod ?? localPeriod;
  // setPeriod fans out: notify the parent (when controlled) AND update
  // local state (so uncontrolled mounts keep working). When fully
  // controlled, the local state still tracks but is unused.
  const setPeriod = (p: PeriodLabel) => {
    if (onPeriodChange) onPeriodChange(p);
    if (controlledPeriod === undefined) setLocalPeriod(p);
  };

  // F-202 (QA iter-2): switch the period selector to send ``days=N`` rather
  // than computing ``from`` client-side. The backend now accepts both, but
  // ``days`` is cleaner — server is source-of-truth for "today" and avoids
  // the timezone drift that ``new Date()`` on the client risks. "All" still
  // omits the param so the server returns every snapshot.
  const periodDays: number | null = useMemo(() => {
    return PERIODS.find((p) => p.label === period)!.days;
  }, [period]);

  // Fetch via TanStack Query — keyed on (portfolioId, period) so
  // toggling the period triggers a fresh fetch but switching back
  // hits the cache.
  const { data, isLoading, isError } = useQuery({
    queryKey: ["value-history", portfolioId, period],
    queryFn: () =>
      createGateway(accessToken).getValueHistory(portfolioId, {
        // F-202: only include ``days`` for bounded windows. "All" omits
        // both params so the server returns the full series.
        ...(periodDays != null ? { days: periodDays } : {}),
        granularity: "1d",
      }),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000, // 1 min — daily snapshots don't change intra-day
  });

  // ── Render: loading skeleton ────────────────────────────────────────────
  // WHY two skeleton blocks: matches the visual layout (header + chart area)
  // so the layout doesn't jump when data arrives.
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2 h-full">
        <div className="flex items-center justify-between h-6">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-5 w-40" />
        </div>
        <Skeleton className="flex-1 min-h-[180px] w-full" />
      </div>
    );
  }

  // ── Render: error state ──────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="flex flex-col gap-2 h-full">
        <ChartHeader period={period} setPeriod={setPeriod} />
        <div className="flex-1 min-h-[180px] flex items-center justify-center">
          <InlineEmptyState message="Failed to load equity curve." />
        </div>
      </div>
    );
  }

  // ── Render: empty state ──────────────────────────────────────────────────
  // BP-265 awareness: data.points may legitimately be empty (no snapshots
  // for the period — e.g. brand-new portfolio). Don't silently render an
  // empty chart — show an honest empty state.
  // F-210 (QA iter-2): also treat a series of all-zero points as "empty".
  // Pre-fix the snapshot worker wrote a $0 row every trading day for empty
  // portfolios, producing a flat line at $0 that misled users. The worker
  // has been changed to skip those writes, but legacy data may still exist
  // — this guard ensures the chart renders correctly either way.
  const points = data?.points ?? [];
  const allZeroValues =
    points.length > 0 && points.every((p) => Number(p.value) === 0);
  if (points.length === 0 || allZeroValues) {
    // F-009 (QA iter-2): when the gateway returns metadata, render a
    // sub-line telling the user when the next snapshot will be written.
    // The metadata block is forward-compatible — older gateways omit it
    // and we fall back to the previous static message.
    const meta = data?.metadata;
    const nextRun = meta?.next_scheduled_run_utc ?? null;
    const subline = nextRun
      ? `Next snapshot scheduled for ${formatNextSnapshotHint(nextRun)}.`
      : null;
    const message = allZeroValues
      ? "Open a position to see your equity curve."
      : "No snapshots yet — the worker writes one per trading day.";
    return (
      <div className="flex flex-col gap-2 h-full">
        <ChartHeader period={period} setPeriod={setPeriod} />
        <div className="flex-1 min-h-[180px] flex flex-col items-center justify-center gap-1">
          <InlineEmptyState message={message} />
          {subline && (
            <div className="text-[10px] text-muted-foreground/80">
              {subline}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Render: chart ────────────────────────────────────────────────────────
  // WHY compute the colour from first→last value: rising = positive teal,
  // falling = negative red. This matches the colour convention the rest of
  // the app uses for P&L cells and gives the chart a glance-able verdict.
  const first = points[0]?.value ?? 0;
  const last = points[points.length - 1]?.value ?? 0;
  const isUp = last >= first;

  return (
    <div className="flex flex-col gap-2 h-full">
      <ChartHeader period={period} setPeriod={setPeriod} />
      <div className="flex-1 min-h-[180px]">
        {/* WHY ResponsiveContainer: the parent grid cell sizes dynamically;
            Recharts needs explicit numeric width/height OR a ResponsiveContainer
            to compute layout. */}
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={points}
            margin={{ top: 4, right: 8, left: 8, bottom: 4 }}
          >
            {/* Subtle grid — visible enough to read values, faint enough not
                to compete with the line. */}
            <CartesianGrid
              strokeDasharray="2 4"
              // WHY inline rgba: Recharts CartesianGrid does not respect Tailwind
              // CSS-var fills inside SVG; using a hard-coded but theme-appropriate
              // semi-transparent grey is the standard escape hatch.
              stroke="rgba(148, 163, 184, 0.15)"
              vertical={false}
            />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "rgba(148,163,184,0.7)" }}
              tickLine={false}
              axisLine={false}
              minTickGap={32}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "rgba(148,163,184,0.7)" }}
              tickLine={false}
              axisLine={false}
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v: number) => formatPrice(v)}
              width={64}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: "rgba(148,163,184,0.3)" }} />
            <Line
              type="monotone"
              dataKey="value"
              // F-008: use the canonical Midnight Pro design tokens
              // (`--positive` / `--negative`, raw HSL triplets in globals.css)
              // wrapped in `hsl(...)` — matches every other coloured cell in
              // the app and respects future theme switches. The previous
              // `--color-positive`/`--color-negative` names did not exist in
              // the stylesheet and silently fell through to the hex fallback.
              stroke={isUp ? "hsl(var(--positive))" : "hsl(var(--negative))"}
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── ChartHeader ──────────────────────────────────────────────────────────────

/**
 * Header above the chart: title on the left, period toggle on the right.
 * Extracted because the chart, error-state, and empty-state branches all
 * render the same header — DRY pays off the moment we add another state.
 */
function ChartHeader({
  period,
  setPeriod,
}: {
  period: PeriodLabel;
  setPeriod: (p: PeriodLabel) => void;
}) {
  return (
    <div className="flex items-center justify-between h-6 px-1">
      <h3 className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
        Equity Curve
      </h3>
      <div className="flex items-center gap-0.5">
        {PERIODS.map((p) => (
          <button
            key={p.label}
            onClick={() => setPeriod(p.label)}
            className={cn(
              "h-5 px-1.5 rounded-[2px] font-mono text-[10px] tabular-nums transition-colors",
              period === p.label
                ? "bg-primary/15 text-primary font-semibold"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
            )}
            aria-pressed={period === p.label}
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
