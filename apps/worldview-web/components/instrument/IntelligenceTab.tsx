/**
 * components/instrument/IntelligenceTab.tsx — Contradictions + intelligence feed
 *
 * WHY THIS EXISTS: NLP-extracted knowledge contradictions are high-signal
 * for risk-aware investors. If one article says "Apple's supply chain is robust"
 * and another says "Apple faces severe supply constraints", analysts need to see
 * that conflict surfaced — not buried in 100 articles.
 *
 * WHY CONTRADICTIONS FIRST: Contradictions are the unique worldview differentiator
 * vs Bloomberg. A quant analyst scanning before a position entry wants to see
 * conflicting signals immediately — not after scrolling past generic news.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Intelligence tab)
 * DATA SOURCE: S9 GET /v1/entities/{entityId}/contradictions
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail State C-4 Intelligence tab
 */

"use client";
// WHY "use client": uses useQuery for async data fetching.

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime } from "@/lib/utils";
import type { Contradiction } from "@/types/api";

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
    <div className="rounded border border-border/40 bg-card/60 p-3">
      {/* Header: severity badge + detected time */}
      <div className="mb-2 flex items-center justify-between">
        <span className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${styles.badge}`}>
          {styles.text}
        </span>
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {formatRelativeTime(item.detected_at)}
        </span>
      </div>

      {/* Claim A vs Claim B */}
      <div className="space-y-2">
        {/* WHY VS layout: makes the contradiction visually obvious at a glance */}
        <div className="rounded bg-positive/5 p-2">
          <p className="text-xs text-foreground/80 leading-relaxed">&ldquo;{item.claim_a}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_a}</p>
        </div>
        <div className="flex items-center justify-center">
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} />
          <span className={`mx-1 text-[9px] font-semibold uppercase ${styles.icon}`}>vs</span>
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} />
        </div>
        <div className="rounded bg-negative/5 p-2">
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

  const { data: resp, isLoading, isError } = useQuery({
    queryKey: ["contradictions", entityId],
    queryFn: () => createGateway(accessToken).getContradictions(entityId),
    enabled: !!accessToken && !!entityId,
    // WHY 10min: contradiction detection runs hourly on the backend
    staleTime: 10 * 60_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="space-y-3 p-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-2 rounded border border-border/40 p-3">
            <div className="flex justify-between">
              <Skeleton className="h-4 w-12" />
              <Skeleton className="h-4 w-16" />
            </div>
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        Could not load intelligence data. Try again shortly.
      </div>
    );
  }

  const contradictions = resp?.contradictions ?? [];

  // ── Empty state ────────────────────────────────────────────────────────────
  if (contradictions.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-8 text-center">
        <CheckCircle className="h-8 w-8 text-positive/60" />
        <p className="text-sm font-medium text-muted-foreground">No contradictions detected</p>
        <p className="text-xs text-muted-foreground/60">
          The NLP pipeline found no conflicting claims across recent articles.
        </p>
      </div>
    );
  }

  // ── Sort: HIGH first, then MEDIUM, then LOW ────────────────────────────────
  const SEVERITY_ORDER: Record<Contradiction["severity"], number> = {
    HIGH: 0, MEDIUM: 1, LOW: 2,
  };

  const sorted = [...contradictions].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );

  return (
    <div className="space-y-3 p-4">
      {/* Count badge at top */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-foreground">
          Detected Contradictions
        </h3>
        <span className="rounded bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
          {contradictions.length} found
        </span>
      </div>

      {/* Contradiction cards */}
      {sorted.map((item) => (
        <ContradictionCard key={item.contradiction_id} item={item} />
      ))}
    </div>
  );
}
