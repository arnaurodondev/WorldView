/**
 * components/instrument/intelligence/ArticleImpactDrawer.tsx — Per-article
 * price-impact popover for the Intelligence tab news rail.
 *
 * WHY THIS EXISTS (PLAN-0091 C-2): Analysts reading the news rail need to know
 * whether a given article moved the stock price. Without this drawer, the news
 * rail shows a single 0-100 "impact score" aggregate but hides the per-window
 * detail — a high score on day T0 means the market reacted same-day, while a
 * high score only on T5 is a lagged, possibly unrelated move. Exposing the four
 * windows (T0/T1/T2/T5) lets analysts distinguish "immediate reaction" from
 * "slow-burn narrative shift."
 *
 * WHY a Popover (not a drawer or modal):
 * The news rail shows 30+ rows. A full-screen drawer would interrupt the reading
 * flow for every row hover. A Popover dismisses itself when focus moves away and
 * never blocks adjacent rows, matching Bloomberg's inline tooltips for news items.
 *
 * WHY the trigger is a 4-segment mini bar (not a button):
 * The bar encodes the direction of each window at a glance — green/red segments
 * let analysts spot "all four windows positive" without opening the popover.
 * The bar IS the interaction affordance; click opens full detail.
 *
 * WHO USES IT: DenseArticleRow (via NewsColumn), called with the article_id from
 * each RankedArticle in the Intelligence tab news list.
 * DATA SOURCE: GET /v1/articles/{article_id}/impact-history via S9 (auth-scoped).
 * DESIGN REFERENCE: PLAN-0091 C-2 spec §Item 2.
 *
 * QUERY STRATEGY:
 * staleTime = 1 hour — PriceImpactLabellingWorker runs once per article after the
 * trading day closes. Windows don't change after computation. A 1-hour stale
 * window means the same article can be hovered 100 times during a session with
 * exactly one network request.
 */

"use client";
// WHY "use client": useQuery + Popover open/close state require browser-side hooks.

import { useAuthedQuery } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { ArticleImpactHistoryResponse } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ArticleImpactDrawerProps {
  /** The article UUID from RankedArticle.article_id. */
  articleId: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

/** Labels for the four price-impact windows, displayed in the popover rows. */
const WINDOW_LABELS = [
  { key: "day_t0" as const, label: "SAME DAY" },
  { key: "day_t1" as const, label: "+1 DAY" },
  { key: "day_t2" as const, label: "+2 DAYS" },
  { key: "day_t5" as const, label: "+5 DAYS" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * segmentClass — maps a single window value to the bar segment's bg class.
 *
 * WHY null → bg-muted/30 (not hidden):
 * A missing segment would collapse the bar width and misalign subsequent segments.
 * A muted fill preserves the 4-segment shape while communicating "not computed."
 */
function segmentClass(value: number | null | undefined): string {
  if (value == null) return "bg-muted/30";
  return value >= 0 ? "bg-[#26A69A]" : "bg-[#EF5350]";
}

/**
 * formatImpact — formats a 0-1 impact value as a signed percentage string.
 * Returns "—" for null/undefined (not yet computed by the labelling worker).
 */
function formatImpact(value: number | null | undefined): string {
  if (value == null) return "—";
  const pct = (value * 100).toFixed(2);
  // WHY explicit "+" prefix: analysts expect "+1.23%" not "1.23%" for gains;
  // the sign is the primary signal at a glance.
  return value >= 0 ? `+${pct}%` : `${pct}%`;
}

/**
 * impactColorClass — maps an impact value to a text color class.
 * null → muted (not computed); 0 → muted (flat); positive → teal; negative → red.
 */
function impactColorClass(value: number | null | undefined): string {
  if (value == null) return "text-muted-foreground";
  if (value > 0) return "text-[#26A69A]";
  if (value < 0) return "text-[#EF5350]";
  return "text-muted-foreground";
}

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * ImpactBar — the 40×4px 4-segment trigger bar rendered inline in the news row.
 *
 * WHY 40px wide (not flex-fill): a fixed width keeps the impact bar column
 * aligned across all 30+ rows regardless of headline length. The remaining space
 * is absorbed by the flex-1 headline.
 *
 * WHY 4px tall: thin enough to fit inside the 18px row without competing with the
 * headline text, thick enough to be clickable and visually distinct from a border.
 */
function ImpactBar({
  data,
}: {
  data: ArticleImpactHistoryResponse | null | undefined;
}) {
  const windows = data?.impact_windows;

  return (
    // WHY w-[40px]: fixed column width keeps all rows aligned regardless of flex parent.
    // WHY gap-px: 1px gap between segments creates a subtle grid effect that helps
    // the eye read each segment as a distinct window rather than a continuous bar.
    <div
      className="flex w-[40px] h-[4px] gap-px rounded-[1px] overflow-hidden"
      aria-label="price impact bar"
    >
      {WINDOW_LABELS.map(({ key }) => (
        <div
          key={key}
          // WHY flex-1: each of the 4 segments takes equal width within the 40px bar.
          className={cn("flex-1", segmentClass(windows?.[key]))}
        />
      ))}
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * ArticleImpactDrawer — self-contained popover showing per-window price impact.
 *
 * The component manages its own open/close state via the shadcn Popover.
 * The 4-segment bar is both the visual summary AND the click trigger.
 */
export function ArticleImpactDrawer({ articleId }: ArticleImpactDrawerProps) {
  // WHY useAuthedQuery (not raw useQuery):
  // useAuthedQuery auto-disables while the user is signed out (prevents spurious
  // 401s during logout) AND provides the memoised gateway via the ApiClientProvider
  // so we don't create a new gateway object on every render.
  const { data, isLoading, isError } = useAuthedQuery<ArticleImpactHistoryResponse | null>({
    queryKey: qk.news.articleImpactHistory(articleId),
    queryFn: (gw) => gw.getArticleImpactHistory(articleId),
    // WHY 1 hour staleTime: PriceImpactLabellingWorker computes windows once per
    // article after the trading day. Refetching more often is wasted bandwidth.
    staleTime: 3_600_000,
  });

  return (
    <Popover>
      {/*
       * WHY asChild on PopoverTrigger: we want the ImpactBar div to BE the
       * trigger — no extra wrapper button that would affect row height or
       * add an unwanted focus ring.
       */}
      <PopoverTrigger asChild>
        <button
          type="button"
          // WHY shrink-0: prevents the bar from being squeezed by the headline flex-1.
          // WHY p-0 / bg-transparent: we want the ImpactBar visuals, not a button look.
          className="shrink-0 p-0 bg-transparent border-none cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[1px]"
          aria-label={`View price impact windows for article`}
        >
          <ImpactBar data={data} />
        </button>
      </PopoverTrigger>

      <PopoverContent
        // WHY max-w-[180px]: the four window rows are short — label + pct fits in
        // 180px. Wider would push the popover off-screen on narrow displays.
        className="max-w-[180px] p-2 bg-[#131722] border border-border"
        // WHY side="top": the news rail is scrollable vertically; opening above the
        // row means the popover never gets clipped by the bottom of the viewport.
        side="top"
        align="end"
      >
        {/* Header */}
        <p className="text-[9px] font-mono uppercase text-muted-foreground mb-1 tracking-wide">
          PRICE IMPACT
        </p>

        {isLoading ? (
          // Loading state: 4 skeleton rows — one per window.
          // WHY animate-pulse (not a spinner): skeletons communicate "content
          // is coming" without suggesting network latency; the rows will fill
          // in place, reducing layout shift.
          <div className="flex flex-col gap-[2px]" aria-live="polite" aria-busy="true">
            {WINDOW_LABELS.map(({ key }) => (
              <div
                key={key}
                className="h-[18px] bg-muted/20 animate-pulse rounded-[2px]"
              />
            ))}
          </div>
        ) : isError ? (
          // Error state: inline message, NOT thrown to the error boundary.
          // WHY: the impact popover is an enhancement, not a critical path.
          // A boundary throw would unmount the entire news row.
          <p className="text-[9px] text-muted-foreground">
            Impact data unavailable
          </p>
        ) : (
          // Data state: 4 rows with label + formatted impact value.
          <div className="flex flex-col gap-[2px]" aria-live="polite">
            {WINDOW_LABELS.map(({ key, label }) => {
              const value = data?.impact_windows?.[key] ?? null;
              return (
                <div
                  key={key}
                  // WHY h-[22px]: standard finance data row height from DESIGN_SYSTEM.
                  className="h-[22px] flex items-center justify-between gap-2"
                >
                  <span className="text-[9px] font-mono text-muted-foreground">
                    {label}
                  </span>
                  <span
                    className={cn(
                      "text-[10px] font-mono tabular-nums",
                      impactColorClass(value),
                    )}
                  >
                    {formatImpact(value)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
