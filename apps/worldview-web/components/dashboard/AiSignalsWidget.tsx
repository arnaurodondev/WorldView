/**
 * components/dashboard/AiSignalsWidget.tsx — Top AI price-impact signals
 *
 * WHY THIS EXISTS: S6 produces article-level price-impact signals (label + confidence
 * score) every time a new article is processed. Surfacing the top 6 on the dashboard
 * gives traders a real-time feed of ML-detected market-moving signals without
 * navigating away from the dashboard morning routine.
 *
 * WHY col-span-2 (Row 3): signals are compact by design — ticker, a 4px bar, and
 * a score percentage. A narrow 2-column cell (~15% of viewport width) is sufficient
 * and leaves room for the other Row 3 widgets at 4+4+2+2.
 *
 * WHY score bar (not just text): the bar encodes magnitude visually so traders can
 * rank signals at a glance without reading numbers — Bloomberg-style compact encoding.
 *
 * WHY 2-minute refetch: signals are generated as articles arrive (continuous). A
 * 2-minute window catches new signals promptly without hammering S9/S6. This is
 * faster than fundamentals (5min) but slower than quotes (1min) — appropriate for
 * a near-real-time signal feed.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 3, col-span-2)
 * DATA SOURCE: S9 GET /v1/signals/ai via createGateway().getAiSignals(limit)
 * DESIGN REFERENCE: PLAN-0043 Wave A-5, PRD-0020 Signal Scoring
 */

"use client";
// WHY "use client": uses useQuery (TanStack), useAuth (React context), and useRouter
// for row-click navigation. None of these work in Next.js server components.

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";
import type { AiSignal } from "@/types/api";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * AiSignalsWidget — compact list of top AI price-impact signals.
 *
 * Renders up to 6 rows, each showing:
 *  - ticker (or entity_id prefix if no ticker resolved)
 *  - proportional fill bar (colored by label)
 *  - score percentage (right-aligned, colored by label)
 *
 * Rows are clickable and navigate to /instruments/{entity_id}.
 */
export function AiSignalsWidget() {
  const { accessToken } = useAuth();
  const router = useRouter();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-ai-signals"],
    queryFn: () => createGateway(accessToken).getAiSignals(6),
    enabled: !!accessToken,
    // WHY 120_000 (2 min): signals arrive continuously as articles are processed.
    // 2 min is fast enough to feel live without generating excessive S9 → S6 traffic.
    staleTime: 120_000,
    refetchInterval: 120_000,
  });

  // ── Loading state ───────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex h-full flex-col bg-background">
        <div className="flex h-5 shrink-0 items-center border-b border-border px-2">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            AI SIGNALS
          </span>
        </div>
        {/* WHY 6 skeleton rows: matches the max signal count so the layout
            doesn't reflow when data arrives — no "skeleton collapse" jump. */}
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center gap-1.5 px-2">
              <Skeleton className="h-3 w-[36px]" style={{ animationDelay: `${i * 40}ms` }} />
              <Skeleton className="h-[4px] flex-1" style={{ animationDelay: `${i * 40 + 20}ms` }} />
              <Skeleton className="h-3 w-[28px]" style={{ animationDelay: `${i * 40 + 40}ms` }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Error state ─────────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="flex h-full flex-col bg-background">
        <WidgetHeader />
        <div className="flex-1 px-2">
          <InlineEmptyState message="Signals failed to load — check connection" />
        </div>
      </div>
    );
  }

  const signals = data?.signals ?? [];

  // ── Empty state ─────────────────────────────────────────────────────────────
  if (signals.length === 0) {
    return (
      <div className="flex h-full flex-col bg-background">
        <WidgetHeader />
        <div className="flex-1 px-2">
          <InlineEmptyState message="No signals yet — processing articles…" />
        </div>
      </div>
    );
  }

  // ── Data state ──────────────────────────────────────────────────────────────
  return (
    // WHY bg-background (not bg-card): consistent with all other dashboard widgets.
    // All cells sit on the same surface level; bg-card creates an unwanted "raised"
    // appearance against the gap-px grid background.
    <div className="flex h-full flex-col bg-background">
      <WidgetHeader signalCount={signals.length} />

      {/* Signal rows — one row per signal, each 22px tall (§0 terminal rule) */}
      <div className="flex-1 divide-y divide-border/30 overflow-auto">
        {signals.map((signal) => (
          <SignalRow
            key={signal.signal_id}
            signal={signal}
            onClick={() => router.push(`/instruments/${signal.entity_id}`)}
          />
        ))}
      </div>
    </div>
  );
}

// ── WidgetHeader ─────────────────────────────────────────────────────────────

/**
 * WidgetHeader — the fixed 20px header bar for the AI Signals widget.
 * WHY h-5 (not h-6): Row 2 headers use h-5 to fit within the 130px cap (A-2).
 * Row 3 headers also use h-5 for visual consistency across all dashboard cells.
 */
function WidgetHeader({ signalCount }: { signalCount?: number }) {
  return (
    <div className="flex h-5 shrink-0 items-center justify-between border-b border-border px-2">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        AI SIGNALS
      </span>
      {/* WHY show count only when data is present: avoids "0 signals" flash during load */}
      {signalCount != null && signalCount > 0 && (
        <span className="font-mono text-[10px] text-muted-foreground/60">
          {signalCount}
        </span>
      )}
    </div>
  );
}

// ── SignalRow ─────────────────────────────────────────────────────────────────

interface SignalRowProps {
  signal: AiSignal;
  onClick: () => void;
}

/**
 * SignalRow — single signal row: ticker label, fill bar, score percentage.
 *
 * WHY separate sub-component: keeps the list map clean and the bar-width
 * calculation logic independently readable.
 */
function SignalRow({ signal, onClick }: SignalRowProps) {
  // ── Derived display values ─────────────────────────────────────────────────

  // WHY ticker ?? entity_id.slice(0,4): some signals are for entities that have
  // no ticker yet (e.g., private companies, ETFs under ingestion). Showing the
  // first 4 chars of entity_id is a readable fallback that signals "data exists".
  const label = signal.ticker ?? signal.entity_id.slice(0, 4).toUpperCase();

  // WHY Math.round(score * 100): score is 0.0–1.0 float; display as integer % for
  // compact monospace rendering. "87%" is cleaner than "86.7%" at text-[9px].
  const scorePct = Math.round(signal.score * 100);

  // WHY these specific color classes for each label:
  //  POSITIVE → text-positive / bg-positive: teal-green (--positive = #26A69A)
  //  NEGATIVE → text-negative / bg-negative: muted red (--negative = #EF5350)
  //  NEUTRAL  → text-muted-foreground / bg-muted-foreground/50: grey, secondary
  // These match TradingView's up/down color convention used throughout the app.
  const colorText =
    signal.label === "POSITIVE"
      ? "text-[hsl(var(--positive))]"
      : signal.label === "NEGATIVE"
        ? "text-[hsl(var(--negative))]"
        : "text-muted-foreground";

  const colorBar =
    signal.label === "POSITIVE"
      ? "bg-[hsl(var(--positive))]"
      : signal.label === "NEGATIVE"
        ? "bg-[hsl(var(--negative))]"
        : "bg-muted-foreground/50";

  return (
    <div
      className="flex h-[22px] cursor-pointer items-center gap-1.5 px-2 transition-colors hover:bg-muted/30"
      onClick={onClick}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      role="button"
      tabIndex={0}
      // WHY title shows article_title: the compact row can't show the full article
      // title inline. The tooltip gives a preview without requiring a click.
      title={signal.article_title ?? undefined}
      aria-label={`${label} — ${signal.label} signal, ${scorePct}% confidence`}
    >
      {/* Ticker label — fixed 36px width so all bars start at the same x position */}
      <span className="w-[36px] shrink-0 truncate font-mono text-[10px] font-medium tabular-nums text-foreground">
        {label}
      </span>

      {/* Score bar track — fills available horizontal space */}
      {/* WHY h-[4px] (not h-1 = 4px): same visual result; explicit px value for
          clarity since the bar is the primary visual encoding of signal strength. */}
      <div className="relative h-[4px] flex-1 rounded-none bg-muted/30">
        {/* Bar fill — proportional to score, colored by label direction */}
        <div
          className={cn("absolute inset-y-0 left-0", colorBar)}
          style={{ width: `${scorePct}%` }}
        />
      </div>

      {/* Score percentage — right-aligned, monospace, colored by label */}
      {/* WHY w-[28px]: "100%" is the longest value (4 chars at ~7px each = 28px).
          Fixed width ensures the bar flex container always has the same right boundary. */}
      <span
        className={cn(
          "w-[28px] shrink-0 text-right font-mono text-[9px] tabular-nums",
          colorText,
        )}
      >
        {scorePct}%
      </span>
    </div>
  );
}
