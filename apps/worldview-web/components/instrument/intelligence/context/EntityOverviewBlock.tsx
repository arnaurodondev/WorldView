/**
 * context/EntityOverviewBlock.tsx — primary entity summary for Intelligence right rail (W7 T-09)
 *
 * WHY THIS EXISTS: PRD-0089 W7 — when no graph node is selected, the right rail
 * shows the primary entity's key characteristics so the analyst has context
 * while exploring the graph: who is this company, how healthy is its KG data,
 * and what are its key facts (employees, founding year, HQ country).
 *
 * WHO USES IT: ContextPanel (Intelligence tab right rail), entity-overview mode.
 * DATA SOURCE:
 *   GET /v1/entities/{id}              → EntityPublic (description, metadata)
 *   GET /v1/entities/{id}/intelligence → EntityIntelligencePublic (health score)
 *   POST /v1/entities/{id}/narratives/generate → refresh trigger (Δ10)
 * DESIGN REFERENCE: W7 design doc §5 (ContextPanel entity-overview mode).
 *
 * WHY TWO QUERIES (not a bundle):
 * EntityPublic (description, metadata) is stable for ~2 hours after 13J enrichment.
 * EntityIntelligencePublic (health, confidence) changes every ~1 min as the KG
 * pipeline runs. Separate queries with different staleTime values let TanStack
 * refetch the fast-changing health badge without re-fetching the stable description.
 *
 * WHY INLINE REFRESH BUTTON (Δ10):
 * Analysts trigger narrative re-generation manually after ingesting breaking news.
 * The cool-down guard (POST returns 429) prevents abuse — we show the remaining
 * seconds so the user understands why the button is disabled.
 */

"use client";
// WHY "use client": useQuery + useMutation + onClick all require browser context.

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useAccessToken } from "@/lib/api-client";
import { apiFetch, GatewayError } from "@/lib/api/_client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { EntityPublic } from "@/types/api";
import type { EntityIntelligencePublic } from "@/types/intelligence";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Format a large employee count to "161k" or "1.2M" style. */
function formatEmployees(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}

/** health_score [0,1] → semantic color token for the badge. */
function healthTone(score: number | null | undefined): string {
  if (score == null) return "text-muted-foreground bg-muted";
  if (score >= 0.75) return "text-positive bg-positive/15";
  if (score >= 0.5) return "text-warning bg-warning/15";
  return "text-negative bg-negative/15";
}

/** data_completeness [0,1] → percentage badge color. */
function completenessTone(pct: number): string {
  if (pct >= 0.8) return "text-positive bg-positive/10";
  if (pct >= 0.5) return "text-warning bg-warning/10";
  return "text-muted-foreground bg-muted";
}

// ── Component ─────────────────────────────────────────────────────────────────

export interface EntityOverviewBlockProps {
  readonly entityId: string;
}

export function EntityOverviewBlock({ entityId }: EntityOverviewBlockProps) {
  const token = useAccessToken();
  const queryClient = useQueryClient();

  // WHY cooldownSec state: 429 responses carry a cooldown_remaining_sec hint.
  // We surface it as a countdown so the user understands why the button is disabled.
  const [cooldownSec, setCooldownSec] = useState<number | null>(null);

  // ── Entity detail (stable — 30 min staleTime) ────────────────────────────
  const { data: entity, isLoading: entityLoading } = useQuery<EntityPublic | null>({
    queryKey: qk.kg.entityDetail(entityId),
    queryFn: () =>
      apiFetch<EntityPublic>(
        `/v1/entities/${encodeURIComponent(entityId)}`,
        { token: token ?? undefined },
      ),
    staleTime: 30 * 60 * 1000,
    enabled: !!entityId && !!token,
  });

  // ── Entity intelligence (fast-changing — 60s staleTime) ─────────────────
  const { data: intelligence, isLoading: intelLoading } = useQuery<EntityIntelligencePublic | null>({
    queryKey: qk.kg.intelligence(entityId),
    queryFn: () =>
      apiFetch<EntityIntelligencePublic>(
        `/v1/entities/${encodeURIComponent(entityId)}/intelligence`,
        { token: token ?? undefined },
      ),
    staleTime: 60_000,
    enabled: !!entityId && !!token,
  });

  // ── Narrative refresh mutation (Δ10) ─────────────────────────────────────
  const refreshMutation = useMutation({
    mutationFn: async () => {
      await apiFetch<void>(
        `/v1/entities/${encodeURIComponent(entityId)}/narratives/generate`,
        { method: "POST", token: token ?? undefined },
      );
    },
    retry: 0, // WHY no retry: POST is user-initiated; 429 means genuinely cooling down
    onSuccess: () => {
      // WHY invalidate intelligence: the new narrative appears in intelligence summary ~30s later.
      void queryClient.invalidateQueries({ queryKey: qk.kg.intelligence(entityId) });
      setCooldownSec(null);
    },
    onError: (err: unknown) => {
      // WHY 429 special-case: the API enforces a per-entity cooldown to prevent
      // spamming the LLM. We parse the remaining seconds from the GatewayError
      // detail string ("Cooldown active, N seconds remaining" pattern).
      if (err instanceof GatewayError && err.status === 429) {
        const match = err.message.match(/(\d+)/);
        setCooldownSec(match ? parseInt(match[1]!, 10) : 60);
      }
    },
  });

  // ── Loading state ─────────────────────────────────────────────────────────
  if (entityLoading || intelLoading) {
    return (
      <div className="p-3 space-y-2">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-12 rounded-[2px]" />
        </div>
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-2/3" />
        <div className="flex gap-4 mt-2">
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-5 w-16" />
        </div>
      </div>
    );
  }

  if (!entity) {
    return (
      <div className="p-3">
        <p className="text-[11px] text-muted-foreground italic">No entity data available.</p>
      </div>
    );
  }

  const typeLabel = entity.entity_type.replace(/_/g, " ");
  const healthScore = intelligence?.health_score ?? null;
  const completeness = entity.data_completeness ?? intelligence?.data_completeness ?? null;
  const pct = completeness != null ? Math.round(completeness * 100) : null;

  // Metadata fields — all from entity.metadata (EntityMetadata shape)
  const employees = entity.metadata?.employee_count;
  const founded = entity.metadata?.founded_year;
  const hqCountry = entity.metadata?.headquarters_country ?? entity.metadata?.country;

  return (
    <div className="p-3 space-y-2">
      {/* ── Header: name + type + health + completeness ───────────────────── */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <h3
          className="text-[12px] font-semibold text-foreground leading-tight truncate max-w-[120px]"
          title={entity.canonical_name}
        >
          {entity.canonical_name}
        </h3>
        {/* WHY type badge: distinguishes financial_instrument from person/concept/event at a glance */}
        <span className="shrink-0 text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground px-1.5 py-0.5 rounded-[2px]">
          {typeLabel}
        </span>
        {/* WHY health badge: composite freshness+completeness+confidence signal in one number.
            title attribute (E-01 tooltip) exposes the sub-scores on hover for analysts. */}
        {healthScore != null && (
          <span
            className={cn(
              "shrink-0 text-[9px] font-mono tabular-nums px-1.5 py-0.5 rounded-[2px]",
              healthTone(healthScore),
            )}
            title={
              intelligence?.confidence_breakdown
                ? JSON.stringify(intelligence.confidence_breakdown)
                : "Health score"
            }
            aria-label={`Health ${Math.round(healthScore * 100)}%`}
          >
            {Math.round(healthScore * 100)}%
          </span>
        )}
        {/* WHY completeness badge: separate from health — data_completeness tells the analyst
            how many expected fields are populated (missing fields = gaps in analysis). */}
        {pct != null && (
          <span
            className={cn(
              "shrink-0 text-[9px] font-mono tabular-nums px-1.5 py-0.5 rounded-[2px]",
              completenessTone(completeness!),
            )}
            aria-label={`${pct}% data complete`}
          >
            {pct}% complete
          </span>
        )}
      </div>

      {/* ── Description (4-line clamp) ─────────────────────────────────────
          WHY line-clamp-4: keeps the panel at a fixed height so the rows below
          (metrics, relations) always start at the same vertical position. */}
      <p className="text-[11px] text-foreground/80 leading-relaxed line-clamp-4">
        {entity.description ?? "No description available."}
      </p>

      {/* ── Metrics row + refresh button ─────────────────────────────────── */}
      <div className="flex items-center justify-between pt-1">
        <div className="flex gap-3">
          {/* WHY show only non-null fields: empty metric cells confuse more than they help.
              If no data exists for this entity type (e.g., a concept), the row stays compact. */}
          {employees != null && (
            <div className="flex flex-col">
              <span className="text-[9px] text-muted-foreground uppercase tracking-wider">Employees</span>
              <span className="text-[11px] font-mono tabular-nums text-foreground">{formatEmployees(employees)}</span>
            </div>
          )}
          {founded != null && (
            <div className="flex flex-col">
              <span className="text-[9px] text-muted-foreground uppercase tracking-wider">Founded</span>
              <span className="text-[11px] font-mono tabular-nums text-foreground">{founded}</span>
            </div>
          )}
          {hqCountry && (
            <div className="flex flex-col">
              <span className="text-[9px] text-muted-foreground uppercase tracking-wider">HQ</span>
              <span className="text-[11px] font-mono text-foreground">{hqCountry}</span>
            </div>
          )}
        </div>

        {/* ↻ Refresh narrative button (Δ10) */}
        <button
          type="button"
          onClick={() => { setCooldownSec(null); refreshMutation.mutate(); }}
          disabled={refreshMutation.isPending || cooldownSec != null}
          title={
            cooldownSec != null
              ? `Cooling down — wait ${cooldownSec}s`
              : "Regenerate intelligence narrative"
          }
          aria-label="Refresh intelligence narrative"
          className={cn(
            "shrink-0 p-1 rounded-[2px] text-muted-foreground hover:text-foreground transition-color-only duration-100",
            (refreshMutation.isPending || cooldownSec != null) && "opacity-40 cursor-not-allowed",
          )}
        >
          <RefreshCw
            className={cn("h-[10px] w-[10px]", refreshMutation.isPending && "animate-spin")}
            strokeWidth={1.5}
          />
        </button>
      </div>

      {/* WHY cooldown note: the analyst needs to know when to try again.
          Shows remaining seconds from the 429 response body. */}
      {cooldownSec != null && (
        <p className="text-[9px] font-mono text-warning">
          Cooldown: {cooldownSec}s remaining
        </p>
      )}
    </div>
  );
}
