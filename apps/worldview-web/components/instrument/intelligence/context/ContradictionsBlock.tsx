/**
 * context/ContradictionsBlock.tsx — KG-detected contradictions for the Intelligence
 * right rail (W7 Block I, T-12).
 *
 * WHY THIS EXISTS: The knowledge-graph pipeline runs a contradiction-detection job
 * that flags pairs of conflicting claims about an entity (e.g. two sources saying
 * opposite things about whether a merger is complete). Surfacing these in the
 * Intelligence tab lets analysts immediately see data-quality signals that would
 * otherwise be buried in raw article text.
 *
 * DESIGN REFERENCE: W7 §1 checks 12/30 (Δ8 + Δ16).
 * DATA SOURCE: GET /v1/entities/{id}/contradictions → ContradictionsResponse
 *              via createKnowledgeGraphApi(token).getContradictions(entityId)
 *
 * WHO USES IT: ContextPanel (entity-overview mode, 4th block in the 5-block stack).
 */

"use client";
// WHY "use client": useQuery + useAuth require browser runtime.

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { createKnowledgeGraphApi } from "@/lib/api/knowledge-graph";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Contradiction } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * normalizeSeverity — ensures the severity badge is always uppercase and falls
 * back to "LOW" for unexpected values (Δ8 from W7 design audit).
 *
 * WHY normalize here (not at the API layer): the ContradictionsResponse comes
 * directly from the S7 proxy without transformation. Normalising at the
 * rendering layer keeps the type contract permissive while the UI is strict.
 */
function normalizeSeverity(s: string | undefined | null): "HIGH" | "MEDIUM" | "LOW" {
  const upper = (s ?? "").toUpperCase();
  if (upper === "HIGH" || upper === "MEDIUM" || upper === "LOW") return upper;
  return "LOW";
}

/**
 * severityClass — maps severity → color token class.
 *
 * WHY semantic tokens: no-off-palette-colors rule bans raw Tailwind palette
 * colors (text-red-*, text-amber-*). text-negative / text-warning / text-muted-foreground
 * resolve through globals.css and stay in sync when the design system is retuned.
 */
function severityClass(s: "HIGH" | "MEDIUM" | "LOW"): string {
  if (s === "HIGH") return "text-negative bg-negative/15";
  if (s === "MEDIUM") return "text-warning bg-warning/15";
  return "text-muted-foreground bg-muted";
}

// ── Sub-component: individual contradiction card ──────────────────────────────

interface ContradictionCardProps {
  contradiction: Contradiction;
}

function ContradictionCard({ contradiction }: ContradictionCardProps) {
  const severity = normalizeSeverity(contradiction.severity);
  // Δ16: claim_type pill. The Contradiction type currently has severity but not
  // claim_type — we derive a display label from the available severity field
  // until S9 exposes claim_type in a follow-up (backend additive change, zero risk).
  const claimTypeLabel = (contradiction as { claim_type?: string }).claim_type
    ? ((contradiction as { claim_type?: string }).claim_type ?? "CLAIM").toUpperCase()
    : "CLAIM";

  return (
    // WHY border-border/40: consistent with other right-rail cards (RelationsList rows).
    <div className="border border-border/40 p-2 space-y-1">
      {/* ── Header: claim_type pill + severity badge ────────────────────────── */}
      <div className="flex items-center gap-1.5">
        {/* claim_type pill — uppercase, 9px mono (Δ16) */}
        <span className="text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground px-1.5 py-0.5 rounded-[2px]">
          {claimTypeLabel}
        </span>
        {/* severity badge (Δ8: always uppercase, fallback LOW) */}
        <span
          className={cn(
            "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded-[2px]",
            severityClass(severity),
          )}
        >
          {severity}
        </span>
      </div>

      {/* ── Claims: claim_a vs claim_b ───────────────────────────────────────── */}
      <p className="text-[10px] text-foreground/90 leading-snug">{contradiction.claim_a}</p>
      <p className="text-[9px] text-muted-foreground font-mono uppercase">vs</p>
      <p className="text-[10px] text-foreground/90 leading-snug">{contradiction.claim_b}</p>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export interface ContradictionsBlockProps {
  readonly entityId: string;
  /** Maximum number of contradiction cards to show. Default: 5. */
  readonly limit?: number;
}

export function ContradictionsBlock({ entityId, limit = 5 }: ContradictionsBlockProps) {
  const { accessToken } = useAuth();

  // WHY useQuery (not useEntityContradictions hook): the hook pattern is only
  // warranted when multiple components share the same query. ContradictionsBlock
  // is the sole consumer — inline query keeps the data-fetching visible here.
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.kg.contradictions(entityId),
    queryFn: () => createKnowledgeGraphApi(accessToken ?? undefined).getContradictions(entityId),
    staleTime: 2 * 60 * 1000, // 2 min — contradictions update after each KG pipeline run
    enabled: !!accessToken && !!entityId,
    retry: 1,
  });

  // ── Loading skeleton (single card) ──────────────────────────────────────────
  if (isLoading) {
    return (
      <section className="space-y-1.5" aria-label="Contradictions loading">
        <Skeleton className="h-14 w-full" />
      </section>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────────
  if (isError) {
    return (
      <p className="text-[10px] text-muted-foreground italic">
        Contradictions unavailable.
      </p>
    );
  }

  const items = (data?.contradictions ?? []).slice(0, limit);

  // ── Empty state ──────────────────────────────────────────────────────────────
  if (items.length === 0) {
    return (
      <p className="text-[10px] text-muted-foreground italic">
        No contradictions detected.
      </p>
    );
  }

  // ── Populated state ──────────────────────────────────────────────────────────
  return (
    <section className="space-y-1.5" aria-label="Contradictions">
      {items.map((c) => (
        <ContradictionCard key={c.contradiction_id} contradiction={c} />
      ))}
    </section>
  );
}
