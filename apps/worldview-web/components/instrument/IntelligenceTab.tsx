/**
 * components/instrument/IntelligenceTab.tsx — Intelligence tab: entity graph + AI brief + contradictions
 *
 * WHY THIS EXISTS: The Intelligence tab gives analysts a holistic view of an entity's
 * relationship network and conflicting signals in one place. Three sections:
 *
 * 1. Entity Knowledge Graph (sigma.js) — full depth=2 interactive WebGL graph showing
 *    how this entity connects to others: competitors, executives, suppliers, macro events.
 *    Replaces the compact Overview sidebar SVG for deeper exploration.
 *
 * 2. AI Intelligence Brief (placeholder) — will show an AI-generated summary of recent
 *    developments, risk factors, and price-relevant signals (uses getInstrumentBrief S9 endpoint).
 *
 * 3. Detected Contradictions — NLP-extracted conflicting claims across recent articles.
 *    These are HIGH-signal for risk-aware investors and the unique worldview differentiator.
 *
 * WHY CONTRADICTIONS LAST (not first as before): The graph now occupies the primary position
 * because it provides spatial context for understanding which entities are generating
 * the contradictions. A quant sees the graph → understands entity relationships →
 * reads contradictions with full relational context.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Intelligence tab)
 * DATA SOURCES:
 *   - S9 GET /v1/entities/{entityId}/graph?depth=2 (entity graph)
 *   - S9 GET /v1/entities/{entityId}/contradictions (NLP contradictions)
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail State C-4 Intelligence tab
 */

"use client";
// WHY "use client": uses useQuery for async data fetching and useState via dynamic import.

import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
// WHY CheckCircle removed: empty contradictions state now uses inline text only
import { AlertTriangle, RefreshCw, ChevronRight, ChevronDown } from "lucide-react";
// WHY ReactMarkdown: S8 returns instrument briefs as markdown (headers, bold, lists).
// ReactMarkdown renders these as proper HTML elements with semantic structure.
import ReactMarkdown from "react-markdown";
// WHY remarkGfm: enables GFM extensions (tables, task lists, strikethrough)
import remarkGfm from "remark-gfm";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime, cn } from "@/lib/utils";
import type { BriefingResponse, Contradiction } from "@/types/api";
import { useState } from "react";

// ── EntityGraph dynamic import (ssr:false) ────────────────────────────────────
// WHY next/dynamic with ssr:false: EntityGraph.tsx uses sigma.js which creates a
// WebGL context. SSR (server-side rendering) has no browser/WebGL environment.
// ssr:false tells Next.js to skip SSR for this component and hydrate it client-side.
// WHY loading spinner: gives the user visual feedback while the sigma.js bundle
// (~200KB) loads and the WebGL context initializes.
const EntityGraph = dynamic(
  () => import("@/components/instrument/EntityGraph").then((m) => ({ default: m.EntityGraph })),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[460px] items-center justify-center rounded-[2px] border border-border/40 bg-card/30">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-primary" />
      </div>
    ),
  },
);

// ── Props ─────────────────────────────────────────────────────────────────────

interface IntelligenceTabProps {
  entityId: string;
}

// ── Severity helpers ──────────────────────────────────────────────────────────
// WHY hex/class map: Contradiction severity mirrors alert severity visually.
// HIGH = red (destructive), MEDIUM = amber (warning), LOW = muted.
const SEVERITY_STYLES: Record<
  Contradiction["severity"],
  { icon: string; badge: string; text: string }
> = {
  HIGH: {
    icon: "text-negative",
    badge: "bg-destructive/15 text-negative",
    text: "HIGH",
  },
  MEDIUM: {
    icon: "text-warning",
    badge: "bg-warning/15 text-warning",
    text: "MED",
  },
  LOW: {
    icon: "text-muted-foreground",
    badge: "bg-muted text-muted-foreground",
    text: "LOW",
  },
};

// ── ContradictionCard sub-component ───────────────────────────────────────────

/**
 * ContradictionCard — collapsible contradiction row
 *
 * WHY COLLAPSIBLE: Long contradiction lists with full VS layouts consume too much
 * vertical space. The collapsed 22px row lets analysts scan all contradictions
 * quickly; expanding reveals the full claim-A vs claim-B layout.
 *
 * WHY CONTROLLED (isExpanded + onToggle props): The parent IntelligenceTab manages
 * the expanded ID so only one card is expanded at a time (accordion behavior).
 * This prevents the page from growing unboundedly when multiple cards are open.
 */
function ContradictionCard({
  item,
  isExpanded,
  onToggle,
}: {
  item: Contradiction;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const styles = SEVERITY_STYLES[item.severity];

  if (!isExpanded) {
    // ── Collapsed: 22px row with severity badge + truncated claim + time ──
    return (
      <div
        className="flex items-center h-[22px] px-2 gap-1.5 hover:bg-muted/40 cursor-pointer border-b border-border/30"
        onClick={onToggle}
      >
        {/* Severity badge — compact colored pill */}
        <span className={`rounded-[2px] px-1 py-0 text-[9px] font-semibold uppercase ${styles.badge}`}>
          {styles.text}
        </span>

        {/* First 60 chars of claim_a — enough context to identify the signal */}
        <span className="text-[11px] text-foreground flex-1 truncate">
          {item.claim_a.slice(0, 60)}{item.claim_a.length > 60 ? "…" : ""}
        </span>

        {/* Relative time */}
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
          {formatRelativeTime(item.detected_at)}
        </span>

        {/* Expand chevron */}
        <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />
      </div>
    );
  }

  // ── Expanded: full VS layout ────────────────────────────────────────────
  return (
    <div className="rounded-[2px] border border-border/40 bg-card/60 p-3">
      {/* Header: severity badge + collapse button + detected time */}
      <div className="mb-2 flex items-center justify-between">
        <span className={`rounded-[2px] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${styles.badge}`}>
          {styles.text}
        </span>

        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {formatRelativeTime(item.detected_at)}
          </span>
          {/* Collapse button — ChevronDown indicates the card can be collapsed */}
          <button
            onClick={onToggle}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Collapse contradiction"
          >
            <ChevronDown className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Claim A vs Claim B — full VS layout */}
      <div className="space-y-2">
        {/* WHY VS layout: makes the contradiction visually obvious at a glance */}
        <div className="rounded-[2px] bg-positive/5 p-2">
          <p className="text-[11px] text-foreground/80 leading-relaxed">&ldquo;{item.claim_a}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_a}</p>
        </div>
        <div className="flex items-center justify-center">
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} />
          <span className={`mx-1 text-[9px] font-semibold uppercase ${styles.icon}`}>vs</span>
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} />
        </div>
        <div className="rounded-[2px] bg-negative/5 p-2">
          <p className="text-[11px] text-foreground/80 leading-relaxed">&ldquo;{item.claim_b}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_b}</p>
        </div>
      </div>
    </div>
  );
}

// ── InstrumentBriefSection (AI brief sub-component) ──────────────────────────
// WHY separate component: isolates the useQuery hook and its loading/error/stale
// states from the parent IntelligenceTab. This means the graph and contradictions
// sections are not blocked by the brief data fetch — they render independently.

/** Brief older than 12h shows a stale indicator */
const BRIEF_STALE_MS = 12 * 60 * 60 * 1000;

function InstrumentBriefSection({ entityId }: { entityId: string }) {
  const { accessToken } = useAuth();

  // WHY useQuery with staleTime 30min: instrument briefs are generated on-demand
  // by S8 and cached in Valkey for 24h. No need to refetch aggressively.
  // WHY retry 2 + retryDelay 10s: S8 may be generating the brief (503); give it
  // time to complete before showing an error state.
  const {
    data: brief,
    isLoading,
    isError,
    error,
  } = useQuery<BriefingResponse>({
    queryKey: ["instrument-brief", entityId],
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 30 * 60 * 1000,
    retry: 2,
    retryDelay: 10_000,
  });

  // WHY p-3 (was p-4): terminal panel standard padding
  return (
    <section className="p-3">
      <h3 className="mb-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">AI Intelligence Brief</h3>

      {/* ── Loading state: 3-line skeleton ──────────────────────────────────── */}
      {/* WHY 3 lines: instrument briefs are shorter than morning briefs (2-3 paragraphs).
          3 skeleton lines match the expected visual height while loading. */}
      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}

      {/* ── Error / unavailable state ────────────────────────────────────────── */}
      {/* WHY 503 soft error: S8 may still be generating the brief. Showing a
          "generating" message is less alarming than a hard error block. */}
      {isError && !isLoading && (
        <div className="rounded-[2px] border border-border/30 bg-card/30 p-3 text-[11px] text-muted-foreground">
          {error instanceof Error &&
          (error.message.includes("503") || error.message.includes("unavailable"))
            ? "Brief generating... check back in a few minutes."
            : "Intelligence brief unavailable."}
        </div>
      )}

      {/* ── Brief content (rendered as markdown) ─────────────────────────────── */}
      {!isLoading && !isError && brief && (
        <div>
          {/* WHY stale indicator: if the brief is older than 12h, the data may
              no longer reflect current market conditions. Amber text signals
              this to the trader without blocking the view. */}
          {Date.now() - new Date(brief.generated_at).getTime() > BRIEF_STALE_MS && (
            <div className="mb-2 flex items-center gap-1">
              <RefreshCw className="h-3 w-3 text-warning" />
              <span className="text-[11px] text-warning">Brief may be outdated</span>
            </div>
          )}

          {/* WHY custom selectors (was prose prose-sm prose-invert):
              The @tailwindcss/typography prose plugin adds opinionated margins and
              font sizes that clash with our terminal dense layout. Custom selectors
              on the wrapper div give the same rendered structure (headers, bold,
              lists) without the forced whitespace. Pattern mirrors MorningBriefCard. */}
          <div className="text-[13px] leading-relaxed text-foreground [&_h2]:mb-1 [&_h2]:mt-3 [&_h2]:text-xs [&_h2]:font-semibold [&_h2]:text-foreground [&_h3]:mb-1 [&_h3]:text-xs [&_h3]:font-semibold [&_li]:ml-3 [&_p]:mb-1.5 [&_strong]:font-semibold [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-3">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {brief.content}
            </ReactMarkdown>
          </div>

          {/* WHY generated_at timestamp: traders need to know how fresh the
              intelligence is — a brief from yesterday may be stale after
              overnight earnings or macro events. */}
          <p className="mt-2 font-mono text-[10px] tabular-nums text-muted-foreground">
            Generated {new Date(brief.generated_at).toISOString().slice(0, 16).replace("T", " ")} UTC
          </p>
        </div>
      )}

      {/* ── Empty state — no brief available yet ─────────────────────────────── */}
      {!isLoading && !isError && !brief && (
        <div className="rounded-[2px] border border-border/30 bg-card/30 p-3 text-[11px] text-muted-foreground">
          No intelligence brief available for this entity yet.
        </div>
      )}
    </section>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IntelligenceTab({ entityId }: IntelligenceTabProps) {
  const { accessToken } = useAuth();

  // ── Severity filter state ────────────────────────────────────────────────────
  // WHY null default: no filter = show all severities. Clicking a severity button
  // filters to only that severity; clicking again clears the filter.
  const [severityFilter, setSeverityFilter] = useState<"HIGH" | "MEDIUM" | "LOW" | null>(null);

  // ── Expanded contradiction row state ─────────────────────────────────────────
  // WHY string|null (not boolean): each contradiction has a unique ID; only one
  // can be expanded at a time (accordion). null = all collapsed.
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // ── Entity graph query ──────────────────────────────────────────────────────
  // WHY separate query (not shared with EntityGraphPanel): the Intelligence tab uses
  // depth=2 (full graph) while the Overview sidebar uses depth=1. Different query
  // keys ensure they are cached separately by TanStack Query.
  const { data: graphData } = useQuery({
    queryKey: ["entity-graph", entityId, 2],
    queryFn: () => createGateway(accessToken).getEntityGraph(entityId, 2),
    enabled: !!accessToken && !!entityId,
    // WHY 10min: knowledge graph edges don't change frequently
    staleTime: 10 * 60_000,
  });

  // ── Contradictions query ────────────────────────────────────────────────────
  const { data: resp, isLoading, isError } = useQuery({
    queryKey: ["contradictions", entityId],
    queryFn: () => createGateway(accessToken).getContradictions(entityId),
    enabled: !!accessToken && !!entityId,
    // WHY 10min: contradiction detection runs hourly on the backend
    staleTime: 10 * 60_000,
  });

  // ── Contradictions data ─────────────────────────────────────────────────────
  const contradictions = resp?.contradictions ?? [];

  // ── Sort contradictions: HIGH first, then MEDIUM, then LOW ─────────────────
  const SEVERITY_ORDER: Record<Contradiction["severity"], number> = {
    HIGH: 0, MEDIUM: 1, LOW: 2,
  };

  const sorted = [...contradictions].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );

  // ── Apply severity filter ───────────────────────────────────────────────────
  // WHY filter on sorted (not raw): maintains the HIGH→MEDIUM→LOW order even after filtering
  const filtered = sorted.filter((c) => !severityFilter || c.severity === severityFilter);

  return (
    <div className="flex flex-col divide-y divide-border/40">

      {/* ── Entity Knowledge Graph ─────────────────────────────────────────── */}
      {/* WHY p-3 (was p-4): terminal panel standard padding */}
      <section className="p-3">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Entity Knowledge Graph</h3>
          <span className="text-[10px] text-muted-foreground">
            depth 2 · {graphData?.nodes.length ?? 0} entities
          </span>
        </div>

        {/* WHY conditional render: show spinner while graphData is loading,
            then render the sigma.js graph once data arrives.
            The EntityGraph component itself also handles the empty state. */}
        {graphData ? (
          <EntityGraph data={graphData} centerEntityId={entityId} />
        ) : (
          <div className="flex h-[460px] items-center justify-center rounded-[2px] border border-border/40 bg-card/30">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-primary" />
          </div>
        )}
      </section>

      {/* ── AI Intelligence Brief (live) ─────────────────────────────────── */}
      {/* WHY live: PLAN-0034 integrated the S8 briefing pipeline. This section
          now fetches a real AI-generated brief from S8 via the S9 gateway.
          It shows loading skeletons, 503 soft errors, and stale indicators. */}
      <InstrumentBriefSection entityId={entityId} />

      {/* ── Detected Contradictions ────────────────────────────────────────── */}
      {/* WHY p-3 (was p-4): terminal panel standard padding */}
      <section className="p-3">

        {/* Loading state */}
        {isLoading && (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="space-y-2 rounded-[2px] border border-border/40 p-3">
                <div className="flex justify-between">
                  <Skeleton className="h-4 w-12" />
                  <Skeleton className="h-4 w-16" />
                </div>
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ))}
          </div>
        )}

        {/* Error state */}
        {isError && !isLoading && (
          <p className="text-sm text-muted-foreground">
            Could not load intelligence data. Try again shortly.
          </p>
        )}

        {/* Empty state — no contradictions found */}
        {/* WHY inline (was flex-col items-center py-8): terminal empty states are
            compact inline text. A full-height centered panel with a large icon is
            consumer SaaS style; a single compact line is terminal style. */}
        {!isLoading && !isError && contradictions.length === 0 && (
          <p className="py-2 text-[11px] text-positive">
            No contradictions detected — signals are consistent.
          </p>
        )}

        {/* Contradiction list */}
        {!isLoading && !isError && contradictions.length > 0 && (
          <div className="space-y-3">
            {/* Count badge at top */}
            <div className="flex items-center justify-between">
              <h3 className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                Detected Contradictions
              </h3>
              <span className="rounded-[2px] bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                {contradictions.length} found
              </span>
            </div>

            {/* ── Temporal histogram — weekly buckets from detected_at ─────
                WHY 8 weeks: contradiction signals build over time. Showing 8 weeks
                gives enough history to spot "signal spikes" before earnings or events.
                WHY 30px height: tall enough to show bar height differences without
                consuming significant vertical space. */}
            {(() => {
              const now = Date.now();
              const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
              const buckets = Array.from({ length: 8 }, (_, i) => ({
                weekAgo: i,
                count: contradictions.filter((c) => {
                  const age = now - new Date(c.detected_at).getTime();
                  return age >= i * WEEK_MS && age < (i + 1) * WEEK_MS;
                }).length,
              })).reverse();
              const maxCount = Math.max(1, ...buckets.map((b) => b.count));
              return (
                <div className="flex items-end gap-px h-[30px] mb-2">
                  {buckets.map((b, i) => (
                    <div
                      key={i}
                      className="flex-1 flex items-end justify-center"
                      title={`${b.count} signals ${b.weekAgo === 0 ? "this week" : `${b.weekAgo}w ago`}`}
                    >
                      <div
                        className="w-full bg-primary/30 hover:bg-primary/60 cursor-pointer transition-colors"
                        style={{ height: `${Math.max(2, (b.count / maxCount) * 28)}px` }}
                      />
                    </div>
                  ))}
                </div>
              );
            })()}

            {/* ── Severity count strip — filter buttons ────────────────────
                WHY always visible: lets analysts quickly assess the severity
                distribution before reading individual contradictions. */}
            <div className="flex items-center gap-4 h-[22px] px-0 mb-1">
              {(["HIGH", "MEDIUM", "LOW"] as const).map((sev) => {
                const count = contradictions.filter((c) => c.severity === sev).length;
                return (
                  <button
                    key={sev}
                    onClick={() => setSeverityFilter((f) => (f === sev ? null : sev))}
                    className={cn(
                      "font-mono text-[10px] tabular-nums",
                      sev === "HIGH"
                        ? severityFilter === "HIGH"
                          ? "text-negative font-medium"
                          : "text-negative/60"
                        : sev === "MEDIUM"
                        ? severityFilter === "MEDIUM"
                          ? "text-warning font-medium"
                          : "text-warning/60"
                        : severityFilter === "LOW"
                        ? "text-muted-foreground font-medium"
                        : "text-muted-foreground/60",
                    )}
                  >
                    {sev} {count}
                  </button>
                );
              })}
              {/* Clear filter button — only visible when a filter is active */}
              {severityFilter && (
                <button
                  onClick={() => setSeverityFilter(null)}
                  className="text-[10px] text-muted-foreground hover:text-foreground ml-auto"
                >
                  Clear filter
                </button>
              )}
            </div>

            {/* Contradiction rows (collapsible accordion) */}
            {filtered.map((item) => (
              <ContradictionCard
                key={item.contradiction_id}
                item={item}
                isExpanded={expandedId === item.contradiction_id}
                onToggle={() =>
                  setExpandedId((id) =>
                    id === item.contradiction_id ? null : item.contradiction_id,
                  )
                }
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
