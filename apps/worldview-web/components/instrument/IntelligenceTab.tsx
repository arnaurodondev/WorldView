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
import { AlertTriangle, CheckCircle } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime } from "@/lib/utils";
import type { Contradiction } from "@/types/api";

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

function ContradictionCard({ item }: { item: Contradiction }) {
  const styles = SEVERITY_STYLES[item.severity];

  return (
    <div className="rounded-[2px] border border-border/40 bg-card/60 p-3">
      {/* Header: severity badge + detected time */}
      <div className="mb-2 flex items-center justify-between">
        <span className={`rounded-[2px] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${styles.badge}`}>
          {styles.text}
        </span>
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {formatRelativeTime(item.detected_at)}
        </span>
      </div>

      {/* Claim A vs Claim B */}
      <div className="space-y-2">
        {/* WHY VS layout: makes the contradiction visually obvious at a glance */}
        <div className="rounded-[2px] bg-positive/5 p-2">
          <p className="text-xs text-foreground/80 leading-relaxed">&ldquo;{item.claim_a}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_a}</p>
        </div>
        <div className="flex items-center justify-center">
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} />
          <span className={`mx-1 text-[9px] font-semibold uppercase ${styles.icon}`}>vs</span>
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} />
        </div>
        <div className="rounded-[2px] bg-negative/5 p-2">
          <p className="text-xs text-foreground/80 leading-relaxed">&ldquo;{item.claim_b}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_b}</p>
        </div>
      </div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IntelligenceTab({ entityId }: IntelligenceTabProps) {
  const { accessToken } = useAuth();

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

  return (
    <div className="flex flex-col divide-y divide-border/40">

      {/* ── Entity Knowledge Graph ─────────────────────────────────────────── */}
      <section className="p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold text-foreground">Entity Knowledge Graph</h3>
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

      {/* ── AI Intelligence Brief (placeholder) ───────────────────────────── */}
      {/* WHY placeholder: getInstrumentBrief S9 endpoint exists but the brief
          generation pipeline (S8 DeepSeek R1) is not yet integrated into the
          Intelligence tab. This section marks the intended location for the
          brief so the layout is established for the next implementation wave. */}
      <section className="p-4">
        <h3 className="mb-2 text-xs font-semibold text-foreground">AI Intelligence Brief</h3>
        <div className="rounded-[2px] border border-border/30 bg-card/30 p-4 text-xs text-muted-foreground">
          Brief generation coming soon — this section will show an AI-generated
          summary of recent developments, risk factors, and price-relevant signals.
        </div>
      </section>

      {/* ── Detected Contradictions ────────────────────────────────────────── */}
      <section className="p-4">

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

        {/* Empty state */}
        {!isLoading && !isError && contradictions.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <CheckCircle className="h-8 w-8 text-positive/60" />
            <p className="text-sm font-medium text-muted-foreground">No contradictions detected</p>
            <p className="text-xs text-muted-foreground/60">
              The NLP pipeline found no conflicting claims across recent articles.
            </p>
          </div>
        )}

        {/* Contradiction list */}
        {!isLoading && !isError && contradictions.length > 0 && (
          <div className="space-y-3">
            {/* Count badge at top */}
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-foreground">
                Detected Contradictions
              </h3>
              <span className="rounded-[2px] bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                {contradictions.length} found
              </span>
            </div>

            {/* Contradiction cards */}
            {sorted.map((item) => (
              <ContradictionCard key={item.contradiction_id} item={item} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
