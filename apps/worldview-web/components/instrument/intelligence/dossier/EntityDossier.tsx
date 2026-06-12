/**
 * dossier/EntityDossier.tsx — left rail of the Intelligence investigation grid
 * (PLAN-0099 Wave 2, Bloomberg-investigation-page rework).
 *
 * WHY THIS EXISTS:
 * The reworked Intelligence tab is a three-zone investigation page:
 *   LEFT  — this dossier: WHO the entity is (identity, description, aliases,
 *           AI brief, strongest relations) — the analyst's anchor context.
 *   CENTRE — the graph canvas + selection inspector (HOW it connects).
 *   RIGHT — news / events / contradictions / narrative (WHAT is happening).
 *
 * The dossier replaces two previous surfaces: the entity-overview mode of the
 * retired right-rail ContextPanel (name/type/health/description/enriched_at)
 * and the AI-brief block that used to sit on top of GraphColumn. Both moved
 * here so the centre column is pure graph + inspector.
 *
 * DATA SOURCES (all cache-shared — ZERO new fetch types):
 *   - ["entity-detail", entityId]      → EntityDetailEnriched (PLAN-0099 Wave 1:
 *     now includes health_score, aliases, top_relations, relation_count).
 *     Pre-warmed by the intelligence-bundle hydrator under this EXACT key.
 *   - qk.instruments.brief(entityId)   → BriefingResponse (same slot the Quote
 *     tab + bundle hydrator fill — the brief renders instantly when cached).
 *   - useEntityIntelligence(entityId)  → health_score fallback (60s cadence)
 *     for pre-Wave-1 cached detail payloads that lack health_score.
 *
 * INTERACTIONS:
 *   - Top-relation rows fire onSelectRelation(relation_id) → the centre
 *     inspector opens the edge dossier (same flow as clicking the edge on the
 *     canvas). This is the keyboard/list-first path to edge detail.
 *   - "Discuss" fires onDiscuss() → IntelligenceTab opens the entity chat strip.
 *
 * WHO USES IT: IntelligenceTab (left column, col-span-3).
 */

"use client";
// WHY "use client": TanStack Query hooks + expand/collapse state need browser React.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileQuestion, MessageSquare } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { useEntityIntelligence } from "@/lib/api/intelligence";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import { StructuredBrief } from "@/components/brief/StructuredBrief";
import { RelatedEntitiesPanel } from "../context/RelatedEntitiesPanel";
import { cn, formatDate } from "@/lib/utils";
import type { EntityDetailEnriched } from "@/lib/api/knowledge-graph";
import type { BriefingResponse, EntityGraph } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface EntityDossierProps {
  /** Primary KG entity_id for the instrument page. */
  readonly entityId: string;
  /** Opens the edge inspector for a top-relation row (== edge click). */
  readonly onSelectRelation: (relationId: string) => void;
  /** Selects a related-entity chip in the inspector (== node click). */
  readonly onSelectNode: (nodeId: string) => void;
  /** Opens the entity chat strip at the bottom of the tab. */
  readonly onDiscuss: () => void;
}

// ── Shared chrome: accent-bar section header ─────────────────────────────────

/**
 * SectionHeader — the house accent-bar header (DenseMetricsGrid Round-1
 * pattern): 2px trading-yellow left bar + 9px uppercase tracking label.
 * WHY local (not imported from financials/): the financials surface is owned
 * by a sibling agent this sprint — duplicating 10 lines beats a cross-surface
 * import that couples two concurrently-edited trees.
 */
function SectionHeader({ label, badge }: { label: string; badge?: string | null }) {
  return (
    <div className="flex items-center justify-between border-y border-border border-l-2 border-l-primary bg-muted/20 h-[18px] px-2">
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70 font-medium">
        {label}
      </span>
      {badge != null && (
        <span className="font-mono text-[9px] tabular-nums text-muted-foreground">{badge}</span>
      )}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** 3-bucket health → semantic token classes (same break points platform-wide). */
function healthClass(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "text-muted-foreground bg-muted";
  if (score >= 0.75) return "text-positive bg-positive/15";
  if (score >= 0.5) return "text-warning bg-warning/15";
  return "text-negative bg-negative/15";
}

function formatHealth(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return `${Math.round(score * 100)}%`;
}

// ── Component ────────────────────────────────────────────────────────────────

export function EntityDossier({
  entityId,
  onSelectRelation,
  onSelectNode,
  onDiscuss,
}: EntityDossierProps) {
  const { accessToken } = useAuth();
  // WHY expand state for the description: enriched descriptions run 3-8
  // sentences; clamping to 5 lines keeps the brief + relations above the fold.
  const [descExpanded, setDescExpanded] = useState(false);

  // ── Entity detail (enriched: health, aliases, top_relations) ──────────────
  // WHY ["entity-detail", entityId] (not qk.kg.entityDetail): the intelligence
  // bundle hydrator seeds THIS exact key — using any other tuple would fork the
  // cache and re-fire the fetch the bundle already paid for.
  const detailQuery = useQuery<EntityDetailEnriched | null>({
    queryKey: ["entity-detail", entityId],
    queryFn: () => createGateway(accessToken).getEntityDetail(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 2 * 60 * 60 * 1000, // descriptions are stable (Worker 13J overnight)
    retry: 1,
  });

  // ── AI brief — SAME cache slot as the Quote tab / bundle hydrator ─────────
  const briefQuery = useQuery<BriefingResponse>({
    queryKey: qk.instruments.brief(entityId),
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 10 * 60 * 1000,
    retry: false, // brief 404s for cold instruments; retry just hammers the LLM
  });

  // ── Health fallback for pre-Wave-1 cached payloads ────────────────────────
  const intelligenceQuery = useEntityIntelligence(entityId);

  // ── Graph cache subscription for the related-entities chips ──────────────
  // Passive read of the depth=2 slot GraphColumn/bundle fill — queryFn () =>
  // null mirrors the retired ContextPanel's zero-network subscription contract.
  const graphQuery = useQuery<EntityGraph | null>({
    queryKey: qk.instruments.entityGraph(entityId, 2),
    queryFn: () => null,
    enabled: !!accessToken && !!entityId,
    staleTime: 5 * 60 * 1000,
    retry: 0,
  });

  // ── Loading skeleton (shape-matched: header row + text lines) ─────────────
  if (detailQuery.isLoading) {
    return (
      <section className="p-0 space-y-2" aria-label="Entity dossier loading">
        <SectionHeader label="Dossier" />
        <div className="px-2 space-y-2">
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-4 w-14 rounded-[2px]" />
          </div>
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      </section>
    );
  }

  // ── Per-section error: named + retry (errors ≠ emptiness) ────────────────
  if (detailQuery.isError) {
    return (
      <section className="p-0" aria-label="Entity dossier">
        <SectionHeader label="Dossier" />
        <div
          data-testid="dossier-fetch-error"
          className="flex flex-col items-center gap-1 px-3 py-6 text-center"
        >
          <p className="text-[12px] text-foreground">Couldn&apos;t load the entity dossier</p>
          <p className="text-[11px] text-muted-foreground">
            The graph and news columns are unaffected.
          </p>
          <button
            type="button"
            onClick={() => void detailQuery.refetch()}
            className="mt-1 font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  const entity = detailQuery.data;

  // ── Named no-entity state (404 → null: enrichment hasn't run yet) ─────────
  if (!entity) {
    return (
      <section className="p-0" aria-label="Entity dossier">
        <SectionHeader label="Dossier" />
        <EmptyState
          condition="empty-no-data"
          copyKey="instrument.no-entity-context"
          icon={FileQuestion}
        />
      </section>
    );
  }

  const typeLabel = entity.entity_type.replace(/_/g, " ");
  // Prefer the Wave-1 enriched health on the detail payload; fall back to the
  // intelligence aggregate for cached pre-Wave-1 responses.
  const health = entity.health_score ?? intelligenceQuery.data?.health_score ?? null;
  const aliases = entity.aliases ?? [];
  const topRelations = entity.top_relations ?? [];
  const brief = briefQuery.data ?? null;

  return (
    <section className="flex flex-col" aria-label="Entity dossier">
      {/* ════ IDENTITY ════════════════════════════════════════════════════ */}
      <SectionHeader label="Dossier" />
      <div className="px-2 py-2 space-y-1.5">
        {/* Name + type chip + health badge — the 3 highest-value identity
            signals on one 22px-rhythm row (truncate keeps long names sane). */}
        <div className="flex items-center gap-1.5 min-w-0">
          <h3
            className="text-[12px] font-semibold text-foreground leading-tight truncate"
            title={entity.canonical_name}
          >
            {entity.canonical_name}
          </h3>
          <span className="shrink-0 text-[9px] uppercase tracking-[0.07em] bg-primary/10 text-primary px-1.5 py-0.5 rounded-[2px]">
            {typeLabel}
          </span>
          <span
            className={cn(
              "ml-auto shrink-0 text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded-[2px] tabular-nums",
              healthClass(health),
            )}
            title="Composite KG health: freshness + completeness + confidence"
            aria-label={`Entity health ${formatHealth(health)}`}
          >
            {formatHealth(health)}
          </span>
        </div>

        {/* Ticker / exchange line — mono numerics register, hidden when absent
            (no-noise policy: "Ticker —" rows add nothing). */}
        {entity.ticker && (
          <p className="font-mono text-[10px] text-muted-foreground">
            {entity.ticker}
            {entity.exchange ? ` · ${entity.exchange}` : ""}
          </p>
        )}

        {/* Aliases — dense chips. WHY cap at 6: alias tables can hold dozens
            of fuzzy variants; the first 6 (gateway orders EXACT/TICKER first)
            cover the recognisable ones without flooding the rail. */}
        {aliases.length > 0 && (
          <div className="flex flex-wrap gap-1" data-testid="dossier-aliases">
            {aliases.slice(0, 6).map((a) => (
              <span
                key={`${a.alias_text}-${a.alias_type}`}
                className="text-[9px] font-mono bg-muted text-muted-foreground px-1 py-0.5 rounded-[2px]"
                title={a.alias_type ?? undefined}
              >
                {a.alias_text}
              </span>
            ))}
          </div>
        )}

        {/* Description with expand — line-clamp keeps the fold honest. The
            toggle only renders when there is a real description to expand. */}
        <p
          className={cn(
            "text-[11px] leading-[1.5] text-foreground/80",
            !descExpanded && "line-clamp-5",
          )}
        >
          {entity.description ?? (
            <span className="italic text-muted-foreground">No description available.</span>
          )}
        </p>
        {entity.description && entity.description.length > 280 && (
          <button
            type="button"
            onClick={() => setDescExpanded((v) => !v)}
            aria-expanded={descExpanded}
            className="font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
          >
            {descExpanded ? "Show less" : "Show more"}
          </button>
        )}

        {/* Freshness anchor — ported verbatim from the retired ContextPanel
            overview (Round-1 requirement 4): a missing timestamp IS
            information ("never enriched"), so the row always renders. */}
        <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/70">
          Updated{" "}
          <span className="tabular-nums text-muted-foreground">
            {entity.enriched_at ? formatDate(entity.enriched_at) : "—"}
          </span>
        </p>

        {/* Discuss — opens the entity-scoped chat strip (platform chat reuse). */}
        <button
          type="button"
          onClick={onDiscuss}
          data-testid="dossier-discuss"
          className="flex items-center gap-1.5 mt-1 border border-border/60 rounded-[2px] px-2 py-1 text-[10px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground hover:border-border focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <MessageSquare className="h-3 w-3" strokeWidth={1.5} aria-hidden />
          Discuss
        </button>
      </div>

      {/* ════ AI BRIEF ═══════════════════════════════════════════════════ */}
      <SectionHeader label="AI Brief" />
      <div className="px-2 py-2">
        {briefQuery.isLoading ? (
          // Shape-matched static skeleton (DS §6.2: skeletons never animate).
          <div className="space-y-1.5" data-testid="dossier-brief-skeleton" aria-hidden>
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-3/4" />
          </div>
        ) : brief?.narrative || brief?.lead || (brief?.sections?.length ?? 0) > 0 ? (
          // WHY StructuredBrief (not raw markdown text): renders the lead +
          // sections with proper hierarchy — the spec's "styled, not raw".
          <StructuredBrief
            sections={brief?.sections ?? []}
            lead={brief?.lead}
            confidence={brief?.confidence}
            variant="compact"
          />
        ) : (
          // Named empty — brief generation is async; absence is a state.
          <p className="text-[10px] text-muted-foreground italic" data-testid="dossier-brief-empty">
            No AI brief generated yet.
          </p>
        )}
      </div>

      {/* ════ TOP RELATIONS (authority-ranked, Wave-1 enrichment) ════════ */}
      <SectionHeader
        label="Top Relations"
        badge={entity.relation_count != null ? String(entity.relation_count) : null}
      />
      <div className="py-1">
        {topRelations.length === 0 ? (
          <p className="px-2 py-1 text-[10px] text-muted-foreground italic">
            No ranked relations yet.
          </p>
        ) : (
          <ul role="list">
            {topRelations.slice(0, 8).map((r) => (
              <li key={r.relation_id}>
                {/* WHY a button row (not a static row): clicking opens the
                    edge inspector — the same investigation flow as clicking
                    the edge on the canvas, but scannable + keyboard-reachable.
                    h-[22px] honours the house dense-row rhythm. */}
                <button
                  type="button"
                  onClick={() => onSelectRelation(r.relation_id)}
                  data-testid={`dossier-relation-${r.relation_id}`}
                  title={r.relation_summary ?? undefined}
                  className="w-full flex items-center gap-1.5 h-[22px] px-2 text-left hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  {/* direction glyph: ← inbound / → outbound relative to root */}
                  <span aria-hidden className="shrink-0 text-[9px] text-muted-foreground/60 font-mono">
                    {r.direction === "inbound" ? "←" : "→"}
                  </span>
                  <span className="shrink-0 text-[9px] font-mono uppercase tracking-wider text-muted-foreground">
                    {r.canonical_type.replace(/_/g, " ")}
                  </span>
                  <span className="flex-1 truncate text-[11px] text-foreground/80" title={r.other_entity_name}>
                    {r.other_entity_name}
                  </span>
                  {typeof r.confidence === "number" && (
                    <span className="shrink-0 font-mono text-[9px] tabular-nums text-muted-foreground">
                      {r.confidence.toFixed(2)}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ════ RELATED ENTITIES (graph-derived chips — component reuse) ═══
          NO SectionHeader here: RelatedEntitiesPanel renders its OWN
          accent-bar "Related Entities · (N)" label — a second header would
          double-announce the section. */}
      <div className="px-2 py-1 border-t border-border/40">
        <RelatedEntitiesPanel
          entityId={entityId}
          nodes={graphQuery.data?.nodes}
          onNodeSelect={onSelectNode}
        />
      </div>
    </section>
  );
}
