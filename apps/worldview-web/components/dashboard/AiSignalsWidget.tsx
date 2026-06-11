/**
 * components/dashboard/AiSignalsWidget.tsx — AI news-event signal feed
 *
 * WHY THIS EXISTS: S6 extracts financial events (earnings, M&A, guidance cuts,
 * product launches, …) from every ingested article. This widget surfaces the
 * latest of those signals so a trader scanning the dashboard sees WHICH
 * entities have news-flow, WHAT kind of event fired, in WHICH direction, and
 * WHEN — without leaving the morning-routine screen.
 *
 * 2026-06-10 OVERHAUL — the previous version showed "9ECB ——— 95%" rows:
 *  - UUID prefixes leaked when ticker resolution failed (fixed server-side:
 *    S9 routes/signals.py now resolves entity NAME too and drops entities the
 *    KG doesn't know);
 *  - duplicate tickers repeated 3x with no differentiation (fixed: S9 dedups
 *    per article, and this widget groups remaining signals per ENTITY with an
 *    expandable "×N" cluster toggle);
 *  - the bare % and the 4px bar implied a price-move prediction. The number
 *    is the LLM's EXTRACTION CONFIDENCE — and since live values are pinned at
 *    0.90–0.95 the bar was visually constant decoration. It is replaced by a
 *    direction glyph + signal-type chip, with a tooltip that defines the %.
 *
 * WHY 2-minute refetch: signals are generated as articles arrive (continuous).
 * A 2-minute window catches new signals promptly without hammering S9/S6 —
 * faster than fundamentals (5min), slower than quotes (1min).
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 2, col-span-3)
 * DATA SOURCE: S9 GET /v1/signals/ai via createGateway().getAiSignals(limit)
 *   (services/api-gateway routes/signals.py — enriched + deduplicated feed)
 * DESIGN REFERENCE: PLAN-0043 Wave A-5, PRD-0020 Signal Scoring,
 *   components/dashboard/ai-signals/* (group row, types, grouping logic)
 */

"use client";
// WHY "use client": uses useQuery (TanStack), useAuth (React context), and useRouter
// for row-click navigation. None of these work in Next.js server components.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
// Round 3 (item 4): panel-level empty/error states migrate to the shared
// EmptyState primitive (DESIGN_SYSTEM §15.12) with named dashboard.* copy
// keys; InlineEmptyState remains the tool for in-list messages only.
import { EmptyState } from "@/components/primitives/EmptyState";
// Round 4 (item 1): error state gains a Retry action wired to refetch() —
// Round 3 named the state but offered no recovery path.
import { WidgetErrorState } from "@/components/dashboard/WidgetErrorState";
import { Radar } from "lucide-react";
// Grouping + row rendering live in the ai-signals/ subdir so each piece is
// independently testable (pure grouping fn, router-free row component).
import { groupSignalsByEntity } from "@/components/dashboard/ai-signals/group-signals";
import { SignalGroupRow } from "@/components/dashboard/ai-signals/SignalGroupRow";
import type { EnrichedAiSignal } from "@/components/dashboard/ai-signals/types";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * AiSignalsWidget — grouped feed of AI-extracted news-event signals.
 *
 * Renders one 22px row per ENTITY (newest first), each showing:
 *  - direction glyph + color (▲ bullish / ▼ bearish / ▪ neutral)
 *  - ticker in mono — falls back to the entity NAME, never a UUID prefix
 *  - signal-type chip ("Earnings", "M&A", "Product launch", …)
 *  - "×N" toggle when several signals cluster on one entity (expands to the
 *    per-signal evidence rows with the triggering headline)
 *  - extraction-confidence % with a tooltip defining the metric
 *  - relative time of the latest signal
 *
 * Rows navigate to /instruments/{ticker} (entity_id fallback when unlisted).
 */
export function AiSignalsWidget() {
  const { accessToken } = useAuth();
  const router = useRouter();

  // Round 4 (item 1): refetch + isFetching destructured for the Retry action.
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["dashboard-ai-signals"],
    queryFn: () => createGateway(accessToken).getAiSignals(20),
    enabled: !!accessToken,
    // WHY 120_000 (2 min): signals arrive continuously as articles are processed.
    // 2 min is fast enough to feel live without generating excessive S9 → S6 traffic.
    staleTime: 120_000,
    refetchInterval: 120_000,
  });

  // Cast is safe: EnrichedAiSignal only ADDS optional fields to AiSignal, so
  // both the new enriched payload and a legacy payload satisfy it. See
  // ai-signals/types.ts for why the extension lives there, not types/api.ts.
  const signals: EnrichedAiSignal[] = useMemo(() => data?.signals ?? [], [data]);

  // Group per entity — MUST be called before any early return (Rules of
  // Hooks: every render must call the same hooks in the same order, so no
  // hook may sit below a conditional `return`). useMemo keeps the grouping
  // from re-running on unrelated re-renders (e.g. parent state changes).
  const groups = useMemo(() => groupSignalsByEntity(signals), [signals]);

  // ── Loading state ───────────────────────────────────────────────────────────
  // Round 4 (item 2): every return branch carries the same role="region" +
  // aria-label so the landmark exists from first paint (SR users can target
  // the panel even while it loads).
  if (isLoading) {
    return (
      <div className="flex h-full flex-col bg-background" role="region" aria-label="AI signals">
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
              {/* w-[30px] mirrors the loaded score column (Round 3: 10px floor). */}
              <Skeleton className="h-3 w-[30px]" style={{ animationDelay: `${i * 40 + 40}ms` }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Error state ─────────────────────────────────────────────────────────────
  // Round 3 (item 4): shared EmptyState primitive replaces InlineEmptyState —
  // a failed feed is a PANEL-level condition (the whole widget has no data),
  // not an in-list message. Copy lives in lib/copy/empty-states.ts.
  if (isError) {
    return (
      <div className="flex h-full flex-col bg-background" role="region" aria-label="AI signals">
        <WidgetHeader />
        {/* Round 4 (item 1): WidgetErrorState = same named copy key + icon as
            the Round-3 EmptyState, plus the Retry → refetch() recovery path. */}
        <WidgetErrorState
          copyKey="dashboard.signals-error"
          icon={Radar}
          onRetry={() => void refetch()}
          retrying={isFetching}
        />
      </div>
    );
  }

  // ── Empty state ─────────────────────────────────────────────────────────────
  // Named empty state (Round 3 item 4) — Radar icon gives the "scanning for
  // signals" category cue; copy key dashboard.no-signals.
  if (signals.length === 0) {
    return (
      <div className="flex h-full flex-col bg-background" role="region" aria-label="AI signals">
        <WidgetHeader />
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            condition="empty-no-data"
            copyKey="dashboard.no-signals"
            icon={Radar}
          />
        </div>
      </div>
    );
  }

  // ── Data state ──────────────────────────────────────────────────────────────
  return (
    // WHY bg-background (not bg-card): consistent with all other dashboard widgets.
    // All cells sit on the same surface level; bg-card creates an unwanted "raised"
    // appearance against the gap-px grid background.
    <div className="flex h-full flex-col bg-background" role="region" aria-label="AI signals">
      <WidgetHeader signalCount={signals.length} />

      {/* Entity rows — one 22px row per ENTITY (§0 terminal rule). Grouping
          turned the old "BAC, BAC, BAC" repetition into a single "BAC ×3"
          row that expands into its per-signal evidence lines. */}
      <div className="flex-1 divide-y divide-border/30 overflow-auto">
        {groups.map((group) => (
          <SignalGroupRow
            key={group.key}
            group={group}
            // PRD-0089 F2 step 11 (§6.6): ticker-first URL — falls back to
            // the KG entity_id when the entity is not a listed instrument.
            onNavigate={() =>
              router.push(`/instruments/${group.ticker || group.entityId}`)
            }
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
