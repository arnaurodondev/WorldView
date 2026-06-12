/**
 * components/dashboard/AiSignalsWidget.tsx — NEWS MOMENTUM feed
 *
 * WHY THIS EXISTS: this dashboard widget answers "what's moving in the news
 * right now?" — the most relevant RECENT stories across everything the platform
 * ingests, so a user scanning the morning-routine screen sees the live news
 * flow without leaving the dashboard.
 *
 * 2026-06-12 WAVE-4 PIVOT — the previous version showed extraction-confidence
 * "AI signals" (e.g. "NA · NEWS EVENT · 95% · 11m"):
 *  - the 95% was the LLM's EXTRACTION CONFIDENCE (pinned at 0.90/0.95) — a
 *    constant decoration that READ like a price prediction;
 *  - the "NEWS EVENT / CORP ACTION / EARNINGS" labels were opaque pipeline
 *    enums, not user-relevant;
 *  - the feed surfaced internal pipeline state, not information a user acts on.
 *  The user's verdict: pivot to "occurrences in news over the last X time, or
 *  something more relevant". This rewrite does exactly that — each row is a real
 *  recent article with an HONEST relevance score, a sentiment direction, a
 *  source, and a click-through to read it. A window selector (24h / 3D / 1W)
 *  lets the user widen or tighten "right now".
 *
 * WHY 2-minute refetch: news arrives continuously as articles are processed.
 * 2 min is fast enough to feel live without hammering S9/S6.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 2, col-span-3) — no props.
 * DATA SOURCE: S9 GET /v1/signals/ai?limit&hours via createGateway().getAiSignals
 *   (services/api-gateway routes/signals.py — proxies S6 /api/v1/news/top)
 * DESIGN REFERENCE: components/dashboard/ai-signals/* (row, meta, types)
 */

"use client";
// WHY "use client": uses useQuery (TanStack), useAuth (React context) and
// useState for the window selector — none work in Next.js server components.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import { WidgetErrorState } from "@/components/dashboard/WidgetErrorState";
import { cn } from "@/lib/utils";
import { Radar } from "lucide-react";
import { NewsMomentumRow } from "@/components/dashboard/ai-signals/NewsMomentumRow";
import type { NewsMomentumItem } from "@/components/dashboard/ai-signals/types";

// ── Window selector ───────────────────────────────────────────────────────────
// The three windows the feed supports (matches the S9 _ALLOWED_WINDOWS set).
// 3D (72h) is the default: 24h is frequently too sparse to fill the widget,
// a full week dilutes "right now". Each option carries the API hours value and
// the compact label shown in the header toggle.
const WINDOWS = [
  { hours: 24, label: "24H" },
  { hours: 72, label: "3D" },
  { hours: 168, label: "1W" },
] as const;
const DEFAULT_WINDOW_HOURS = 72;

// How many rows to request — generous so the scroll area is full; the row
// height (22px) keeps even 20 rows cheap to render.
const ROW_LIMIT = 20;

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * AiSignalsWidget — NEWS MOMENTUM feed (kept name for the dashboard slot).
 *
 * Renders one 22px row per recent news story (most relevant first), each with a
 * sentiment dot, headline (links to the article), source, honest relevance %,
 * and relative time. A header toggle switches the look-back window.
 */
export function AiSignalsWidget() {
  const { accessToken } = useAuth();

  // Selected look-back window. Local state (not URL) — it's throwaway view
  // state scoped to this widget, lost on reload, which is fine.
  const [windowHours, setWindowHours] = useState<number>(DEFAULT_WINDOW_HOURS);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    // Window is part of the key so switching windows refetches (and caches each
    // window independently — flipping back is instant).
    queryKey: ["dashboard-ai-signals", windowHours],
    queryFn: () => createGateway(accessToken).getAiSignals(ROW_LIMIT, windowHours),
    enabled: !!accessToken,
    // WHY 120_000 (2 min): news arrives continuously; 2 min feels live without
    // excessive S9 → S6 traffic.
    staleTime: 120_000,
    refetchInterval: 120_000,
  });

  // Cast via unknown is safe: the shared AiSignalsResponse type in types/api.ts
  // still describes the LEGACY signal shape (a different shared workstream owns
  // it), but the wire payload is now NewsMomentumItem[]. NewsMomentumItem reads
  // every field defensively, so a legacy payload also degrades gracefully
  // (forward-compat, same principle as Avro schema evolution).
  const items: NewsMomentumItem[] = useMemo(
    () => (data?.signals as unknown as NewsMomentumItem[] | undefined) ?? [],
    [data],
  );

  // Shared header — the window selector must be present in EVERY state (loading,
  // error, empty, data) so the user can switch windows even when one is empty.
  const header = (
    <WidgetHeader
      windowHours={windowHours}
      onWindowChange={setWindowHours}
      count={items.length}
      // Don't let the user spam window switches mid-fetch.
      disabled={isFetching}
    />
  );

  // ── Loading state ───────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex h-full flex-col bg-background" role="region" aria-label="News momentum">
        {header}
        {/* WHY 6 skeleton rows: roughly fills the panel so the layout doesn't
            reflow when data arrives — no "skeleton collapse" jump. */}
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center gap-1.5 px-2">
              <Skeleton className="h-2 w-2 rounded-full" style={{ animationDelay: `${i * 40}ms` }} />
              <Skeleton className="h-3 flex-1" style={{ animationDelay: `${i * 40 + 20}ms` }} />
              <Skeleton className="h-3 w-[26px]" style={{ animationDelay: `${i * 40 + 40}ms` }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Error state ─────────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="flex h-full flex-col bg-background" role="region" aria-label="News momentum">
        {header}
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
  // The window selector stays visible so the user can widen the window — the
  // copy ("Try a wider window") points them at the fix.
  if (items.length === 0) {
    return (
      <div className="flex h-full flex-col bg-background" role="region" aria-label="News momentum">
        {header}
        <div className="flex flex-1 items-center justify-center">
          <EmptyState condition="empty-no-data" copyKey="dashboard.no-signals" icon={Radar} />
        </div>
      </div>
    );
  }

  // ── Data state ──────────────────────────────────────────────────────────────
  return (
    // WHY bg-background (not bg-card): consistent with all other dashboard
    // widgets — every cell sits on the same surface level.
    <div className="flex h-full flex-col bg-background" role="region" aria-label="News momentum">
      {header}
      <div className="flex-1 divide-y divide-border/30 overflow-auto">
        {items.map((item, i) => (
          // article_id is the stable key; index fallback for the rare null id.
          <NewsMomentumRow key={item.article_id ?? `row-${i}`} item={item} />
        ))}
      </div>
    </div>
  );
}

// ── WidgetHeader ─────────────────────────────────────────────────────────────

/**
 * WidgetHeader — the fixed 20px header: title + window selector + count.
 * WHY h-5: Row 2 headers use h-5 to fit within the 130px cap; Row 3 headers
 * also use h-5 for visual consistency across all dashboard cells.
 */
function WidgetHeader({
  windowHours,
  onWindowChange,
  count,
  disabled,
}: {
  windowHours: number;
  onWindowChange: (hours: number) => void;
  count: number;
  disabled: boolean;
}) {
  return (
    <div className="flex h-5 shrink-0 items-center justify-between border-b border-border px-2">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">NEWS MOMENTUM</span>

      <div className="flex items-center gap-1.5">
        {/* Window selector — three tiny toggle buttons (24H / 3D / 1W).
            role=group + aria-label gives SR users the control's purpose; each
            button reports aria-pressed so the active window is announced. */}
        <div className="flex items-center gap-0.5" role="group" aria-label="News look-back window">
          {WINDOWS.map((w) => {
            const active = w.hours === windowHours;
            return (
              <button
                key={w.hours}
                type="button"
                disabled={disabled}
                onClick={() => onWindowChange(w.hours)}
                aria-pressed={active}
                className={cn(
                  "rounded-[2px] px-1 font-mono text-[9px] tabular-nums transition-colors disabled:text-[hsl(var(--disabled-foreground))]",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  active
                    ? "bg-muted/60 text-foreground"
                    : "text-muted-foreground/60 hover:bg-muted/30 hover:text-foreground",
                )}
              >
                {w.label}
              </button>
            );
          })}
        </div>

        {/* Row count — only when present, avoids a "0" flash during load. */}
        {count > 0 && <span className="font-mono text-[10px] text-muted-foreground/60">{count}</span>}
      </div>
    </div>
  );
}
