/**
 * context/EntityOverviewBlock.tsx — Entity header for Intelligence right rail (PLAN-0099 W4)
 *
 * WHY THIS EXISTS: When no graph node is selected, the context panel's top section
 * shows the primary instrument entity's name, type badge, health score, and LLM
 * description. This replaces the sparse `<p>` + health badge that lived inline in
 * ContextPanel — extracting it to a block keeps ContextPanel thin (orchestration only)
 * and makes EntityOverviewBlock independently testable.
 *
 * DATA SOURCES:
 *   GET /v1/entities/{id}              → EntityPublic (name, type, description)
 *   GET /v1/entities/{id}/intelligence → EntityIntelligencePublic (health_score)
 *
 * The ContextPanel already fetches both of these via TanStack Query; we re-use the
 * SAME cache keys here so there is exactly ONE network request per entity per session.
 *
 * DESIGN: compact density — 12px name, 9px type badge, health badge, 11px description
 * with line-clamp-4 to keep the block bounded in the narrow 3/14-column rail.
 */

"use client";
// WHY "use client": useQuery hooks require browser React runtime.

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { useEntityIntelligence } from "@/lib/api/intelligence";


export interface EntityOverviewBlockProps {
  /** The primary KG entity_id for the instrument page (UUIDv7). */
  readonly entityId: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * healthBadgeClass — maps health_score [0, 1] → Tailwind bg + text class.
 *
 * WHY three buckets: same break points as the rest of the platform (alert severity,
 * confidence badges). Finance UX rewards fast scanning — a 3-level signal is
 * instantly readable; a gradient would require the eye to interpret.
 */
function healthBadgeClass(score: number | null | undefined): string {
  if (score == null) return "bg-muted text-muted-foreground";
  if (score >= 0.75) return "bg-positive/15 text-positive";
  if (score >= 0.5) return "bg-warning/15 text-warning";
  return "bg-negative/15 text-negative";
}

function formatHealth(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return `${Math.round(score * 100)}%`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function EntityOverviewBlock({ entityId }: EntityOverviewBlockProps) {
  const { accessToken } = useAuth();

  // WHY the same key as ContextPanel (`["entity-detail", entityId]`):
  // TanStack Query dedupes by key — both components share one cached response.
  // Switching to `qk.kg.entityDetail` here would create a SECOND cache slot
  // (different key tuple) doubling the network round-trips.
  const { data: entity, isLoading: detailLoading } = useQuery({
    queryKey: ["entity-detail", entityId],
    queryFn: () => createGateway(accessToken).getEntityDetail(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 2 * 60 * 60 * 1000, // 2h — descriptions are stable (Worker 13J overnight)
    retry: 1,
  });

  // WHY useEntityIntelligence (not direct useQuery): health_score changes ~every
  // minute as the KG pipeline runs. The hook centralises staleTime=60s + auth
  // plumbing so this block and the ContextPanel badge always show the same value.
  const { data: intelligence, isLoading: intelLoading } = useEntityIntelligence(entityId);

  // ── Loading state ────────────────────────────────────────────────────────
  // WHY a skeleton instead of null: the block has a predictable height (≈80px).
  // Showing a skeleton prevents layout shift when data loads in.
  if (detailLoading || intelLoading) {
    return (
      <div className="px-3 py-2 space-y-2 border-b border-border/40">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-14 rounded-[2px]" />
          <Skeleton className="h-4 w-10 ml-auto rounded-[2px]" />
        </div>
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    );
  }

  // WHY graceful null (not an error): entity can be null when the KG enrichment
  // pipeline hasn't processed the entity yet (new instruments take up to 1h
  // after first ingest). Returning null collapses the block rather than showing
  // an error card for a normal transient state.
  if (!entity) return null;

  const typeLabel = entity.entity_type.replace(/_/g, " ");
  const healthScore = intelligence?.health_score ?? null;

  return (
    <div className="px-3 py-2 border-b border-border/40 space-y-1.5">
      {/* ── Header row: name + type badge + health badge ─────────────────── */}
      <div className="flex items-center gap-1.5 min-w-0">
        <h3
          className="text-[12px] font-semibold text-foreground leading-tight truncate"
          title={entity.canonical_name}
        >
          {entity.canonical_name}
        </h3>

        {/* WHY bg-primary/10: the type badge uses the primary accent at 10%
            opacity — subtle enough to not compete with the name but distinct
            from the health badge. Matches the design system's "tag" convention. */}
        <span className="shrink-0 text-[9px] uppercase tracking-[0.07em] bg-primary/10 text-primary px-1.5 py-0.5 rounded-[2px]">
          {typeLabel}
        </span>

        {/* WHY ml-auto: push health to the row-end so it never fights the truncated
            name for space — consistent with ContextPanel's entity-overview header. */}
        <span
          className={cn(
            "ml-auto shrink-0 text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded-[2px] tabular-nums",
            healthBadgeClass(healthScore),
          )}
          title="Composite KG health: data freshness + completeness + confidence"
          aria-label={`Entity health ${formatHealth(healthScore)}`}
        >
          {formatHealth(healthScore)}
        </span>
      </div>

      {/* ── Description ───────────────────────────────────────────────────
          WHY line-clamp-4: the right rail is ≈210 px at grid-cols-14/col-span-3.
          line-clamp-4 keeps the block bounded so the blocks below (TopRelations,
          PathInsights) remain visible without excessive scroll. */}
      <p className="text-[11px] leading-[1.5] text-foreground/80 line-clamp-4">
        {entity.description ?? (
          <span className="italic text-muted-foreground">No description available.</span>
        )}
      </p>
    </div>
  );
}
