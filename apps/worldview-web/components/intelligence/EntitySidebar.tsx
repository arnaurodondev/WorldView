/**
 * components/intelligence/EntitySidebar.tsx — Column 3: Entity intelligence summary
 * (PLAN-0074 Wave H T-H-05)
 *
 * WHY THIS EXISTS:
 * The sidebar synthesises the most actionable intelligence about the current entity
 * into a single scannable column:
 *   - Health score ring + entity name/type
 *   - Current AI narrative with regenerate button
 *   - Confidence trend sparkline
 *   - Source distribution bars
 *   - Key metrics grid
 *
 * WHY SIDEBAR SYNC (selected vs anchor):
 * When the analyst clicks a node in the graph (e.g., Tim Cook in Apple's graph),
 * `selectedEntityId` changes to Tim Cook's ID. The sidebar should then show
 * Tim Cook's intelligence — not Apple's — so the analyst can compare.
 * A "Back to {anchor}" link restores the original view without page navigation.
 *
 * WHY TWO QUERY CALLS (not one):
 * The anchor entity's intelligence is always needed (fallback state).
 * The selected entity's intelligence is conditional on selection.
 * Splitting them into two hooks lets TanStack Query cache them independently —
 * switching back to the anchor is instant (data already cached).
 *
 * WCAG: All interactive elements have aria-labels. The health score ring
 * has role="img" with an accessible description. Timestamps use Intl.DateTimeFormat.
 *
 * WHO USES IT: IntelligenceLayout column 3 slot
 */

"use client";
// WHY "use client": reads context + uses query hooks.

import { useMemo } from "react";
import { useSelectedEntity } from "@/contexts/SelectedEntityContext";
import { useEntityIntelligence } from "@/lib/api/intelligence";
import { useApiClient } from "@/lib/api-client";
import { useQuery } from "@tanstack/react-query";
import { HealthScoreBadge } from "@/components/intelligence/HealthScoreBadge";
import { ConfidenceTrendSparkline } from "@/components/intelligence/ConfidenceTrendSparkline";
import { SourceDistributionList } from "@/components/intelligence/SourceDistributionList";
import { NarrativeCard } from "@/components/intelligence/NarrativeCard";
import { KeyMetricsGrid } from "@/components/intelligence/KeyMetricsGrid";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ArrowLeft, BarChart2 } from "lucide-react";
import type { EntityGraph } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface EntitySidebarProps {
  entityId: string; // anchor entity UUIDv7 from URL param
}

// ── Section divider helper ────────────────────────────────────────────────────

function SectionHeader({ title }: { title: string }) {
  return (
    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
      {title}
    </p>
  );
}

// ── Sidebar skeleton ──────────────────────────────────────────────────────────

function SidebarSkeleton() {
  return (
    <div className="p-3 space-y-4">
      <div className="flex items-center gap-3">
        <Skeleton className="h-12 w-12 rounded-full shrink-0" />
        <div className="space-y-1.5 flex-1">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
      <Skeleton className="h-[80px] w-full" />
      <Skeleton className="h-[40px] w-full" />
      <Skeleton className="h-[60px] w-full" />
      <Skeleton className="h-[48px] w-full" />
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function EntitySidebar({ entityId }: EntitySidebarProps) {
  const { selectedEntityId, setSelectedEntityId, anchorEntityId } = useSelectedEntity();
  const isShowingSelected = selectedEntityId !== anchorEntityId;
  const gw = useApiClient();

  // Always fetch the anchor entity's intelligence (for fallback + quick "back")
  const { data: anchorIntel, isLoading: anchorLoading } = useEntityIntelligence(entityId);

  // Only fetch selected entity when it differs from anchor
  // WHY enabled guard: avoids a duplicate fetch when selected === anchor.
  const { data: selectedIntel, isLoading: selectedLoading } = useEntityIntelligence(
    selectedEntityId,
  );

  // Determine which intelligence data to display
  // WHY selectedIntel takes priority: the analyst chose to explore a neighbour.
  const displayIntel = isShowingSelected ? selectedIntel : anchorIntel;
  const isLoading = isShowingSelected ? selectedLoading : anchorLoading;
  const displayEntityId = isShowingSelected ? selectedEntityId : entityId;

  // ── Entity detail (description from Worker 13J) ────────────────────────────
  //
  // WHY separate getEntityDetail call: useEntityIntelligence() returns
  // intelligence aggregates (confidence, narrative, relations).
  // getEntityDetail() returns the entity's own enrichment fields
  // (description from Worker 13J, metadata like sector/industry/founded_year).
  // These two endpoints have different stale times — descriptions are
  // stable for hours; intelligence metrics refresh every few minutes.
  const { data: entityDetail } = useQuery({
    queryKey: ["entity-detail", displayEntityId],
    queryFn: () => gw.getEntityDetail(displayEntityId),
    staleTime: 300_000, // WHY 5min: entity descriptions rarely change
    enabled: !!displayEntityId,
  });

  // ── Top-3 relations with summaries ─────────────────────────────────────────
  // Read from the graph query cache — GraphPanel already fetched this data.
  // WHY depth=2 in queryKey: matches GraphPanel's default, so the cache hit is
  // guaranteed when GraphPanel is mounted (which it always is on the intelligence page).
  const { data: graphData } = useQuery<EntityGraph>({
    queryKey: ["intelligence-graph", displayEntityId, 2, false],
    queryFn: () => gw.getEntityGraph(displayEntityId, 2, "all"),
    // WHY staleTime 60_000: matches GraphPanel's staleTime so both components
    // share the same cache entry without any re-fetch.
    staleTime: 60_000,
    enabled: !!displayEntityId,
  });

  // Top-3 relations sorted by confidence (weight), filtered to edges that include
  // the display entity, with summaries if available.
  const topRelations = useMemo(() => {
    if (!graphData?.edges) return [];
    return [...graphData.edges]
      .filter((e) => e.source === displayEntityId || e.target === displayEntityId)
      .sort((a, b) => b.weight - a.weight)
      .slice(0, 3);
  }, [graphData, displayEntityId]);

  if (isLoading) {
    return (
      <div className="h-full overflow-y-auto">
        <SidebarSkeleton />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-background" aria-label="Entity intelligence summary">
      {/* ── "Viewing selected entity" banner ──────────────────────────────── */}
      {/* WHY show banner + back button:
          Without a clear indicator, analysts might not realize the sidebar is
          now showing a different entity's data. The amber banner + "Back" link
          give an unmissable visual cue and an instant escape route. */}
      {isShowingSelected && (
        <div className="px-3 py-2 bg-primary/10 border-b border-primary/20 flex items-center justify-between gap-2">
          <p className="text-[10px] font-mono text-primary truncate">
            Now showing: {displayIntel?.canonical_name ?? selectedEntityId}
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedEntityId(anchorEntityId)}
            className="h-6 px-2 text-[10px] font-mono shrink-0"
            aria-label={`Back to ${anchorIntel?.canonical_name ?? anchorEntityId}`}
          >
            <ArrowLeft className="h-3 w-3 mr-1" strokeWidth={1.5} />
            Back
          </Button>
        </div>
      )}

      {/* ── Header: health ring + entity name ─────────────────────────────── */}
      <div className="px-3 py-3 border-b border-border/50">
        <div className="flex items-start gap-3">
          <HealthScoreBadge
            score={displayIntel?.health_score ?? null}
            size={48}
            className="shrink-0 mt-0.5"
          />
          <div className="flex-1 min-w-0">
            <h2 className="text-[13px] font-semibold text-foreground truncate">
              {displayIntel?.canonical_name ?? "—"}
            </h2>
            <p className="text-[11px] font-mono text-muted-foreground uppercase tracking-wide">
              {displayIntel?.entity_type ?? "—"}
            </p>
            {displayIntel?.data_completeness != null && (
              <p className="text-[10px] font-mono text-muted-foreground mt-0.5 tabular-nums">
                {Math.round(displayIntel.data_completeness * 100)}% complete
              </p>
            )}
            {/* Entity description from Worker 13J (StructuredEnrichmentWorker).
                WHY show here (not a separate section): the description is a one-line
                or two-line human-readable label that gives context before the analyst
                reads the intelligence narrative. Placing it in the header makes it
                scannable at a glance. */}
            {entityDetail?.description && (
              <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
                {entityDetail.description}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* ── No data state ─────────────────────────────────────────────────── */}
      {!displayIntel && (
        <div className="p-3 text-center">
          <BarChart2 className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" strokeWidth={1} />
          <p className="text-[11px] text-muted-foreground font-mono">
            No intelligence data
          </p>
        </div>
      )}

      {displayIntel && (
        <div className="p-3 space-y-4">
          {/* ── Current narrative ───────────────────────────────────────────── */}
          <div>
            <SectionHeader title="Current Narrative" />
            <NarrativeCard
              entityId={displayEntityId}
              narrative={displayIntel.current_narrative}
            />
          </div>

          {/* ── Confidence trend sparkline ────────────────────────────────── */}
          {displayIntel.confidence_breakdown.confidence_trend.length > 0 && (
            <div>
              <SectionHeader title="Confidence Trend" />
              <ConfidenceTrendSparkline
                data={displayIntel.confidence_breakdown.confidence_trend}
                height={40}
              />
              <div className="flex justify-between mt-1">
                {/* First and last date as x-axis labels */}
                {displayIntel.confidence_breakdown.confidence_trend.length >= 2 && (
                  <>
                    <span className="text-[9px] font-mono text-muted-foreground">
                      {displayIntel.confidence_breakdown.confidence_trend[0].date.slice(0, 7)}
                    </span>
                    <span className="text-[9px] font-mono text-muted-foreground">
                      {displayIntel.confidence_breakdown.confidence_trend[
                        displayIntel.confidence_breakdown.confidence_trend.length - 1
                      ].date.slice(0, 7)}
                    </span>
                  </>
                )}
              </div>
            </div>
          )}

          {/* ── Confidence breakdown numbers ──────────────────────────────── */}
          {(displayIntel.confidence_breakdown.mean_support != null ||
            displayIntel.confidence_breakdown.relation_count > 0) && (
            <div>
              <SectionHeader title="Evidence Quality" />
              <div className="space-y-1 text-[11px] font-mono">
                {displayIntel.confidence_breakdown.mean_support != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Support</span>
                    <span className="tabular-nums text-foreground/90">
                      {(displayIntel.confidence_breakdown.mean_support * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
                {displayIntel.confidence_breakdown.mean_corroboration != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Corroboration</span>
                    <span className="tabular-nums text-foreground/90">
                      {(displayIntel.confidence_breakdown.mean_corroboration * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
                {displayIntel.confidence_breakdown.mean_contradiction != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Contradiction</span>
                    <span className="tabular-nums text-negative">
                      {(displayIntel.confidence_breakdown.mean_contradiction * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Relations</span>
                  <span className="tabular-nums text-foreground/90">
                    {displayIntel.confidence_breakdown.relation_count}
                  </span>
                </div>
                {displayIntel.confidence_breakdown.latest_evidence_at && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Latest evidence</span>
                    <span className="tabular-nums text-foreground/90">
                      {new Intl.DateTimeFormat("en-US", {
                        month: "short",
                        day: "numeric",
                      }).format(
                        new Date(displayIntel.confidence_breakdown.latest_evidence_at),
                      )}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Source distribution bars ──────────────────────────────────── */}
          {displayIntel.confidence_breakdown.source_distribution.length > 0 && (
            <div>
              <SectionHeader title="Evidence Sources" />
              <SourceDistributionList
                distribution={displayIntel.confidence_breakdown.source_distribution}
              />
            </div>
          )}

          {/* ── Top-3 relations with summaries ───────────────────────────── */}
          {/* WHY top-3 (not all): the sidebar column is narrow (~200px). Showing
              only the 3 highest-confidence relations keeps the section scannable.
              The full relations list is in the IntelligencePanel Relations tab.
              WHY show when empty: once SummaryWorker runs, summaries will appear.
              Until then, we still show the relation type + confidence to surface
              "what does the KG know about this entity" without needing summaries. */}
          {topRelations.length > 0 && (
            <div>
              <SectionHeader title="Top Relations" />
              <div className="space-y-1.5">
                {topRelations.map((edge) => {
                  // Determine the "other" entity in the relation
                  const otherEntityId = edge.source === displayEntityId ? edge.target : edge.source;
                  // Find the neighbor label from the graph nodes
                  const neighborNode = graphData?.nodes.find((n) => n.id === otherEntityId);
                  const neighborLabel = neighborNode?.label ?? otherEntityId.slice(0, 8) + "…";
                  // Pretty-print the relation label (CEO_OF → ceo of)
                  const relLabel = edge.label.replace(/_/g, " ").toLowerCase();
                  const confidencePct = Math.round(edge.weight * 100);

                  return (
                    <div
                      key={edge.id}
                      className="rounded-[2px] border border-border/30 bg-muted/20 px-2 py-1.5"
                    >
                      {/* Relation header: type + confidence badge */}
                      <div className="flex items-center justify-between gap-1 mb-0.5">
                        <span className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground truncate">
                          {relLabel}
                        </span>
                        <span
                          className={[
                            "shrink-0 font-mono text-[9px] tabular-nums rounded-[2px] px-1 py-0.5",
                            edge.weight >= 0.7
                              ? "bg-positive/15 text-positive"
                              : edge.weight >= 0.4
                                ? "bg-warning/15 text-warning"
                                : "bg-muted text-muted-foreground",
                          ].join(" ")}
                        >
                          {confidencePct}%
                        </span>
                      </div>
                      {/* Neighbor entity name */}
                      <p className="text-[10px] text-foreground/90 truncate">{neighborLabel}</p>
                      {/* LLM summary when available */}
                      {edge.relation_summary && (
                        <p className="mt-0.5 text-[9px] leading-relaxed text-muted-foreground line-clamp-2">
                          {edge.relation_summary}
                        </p>
                      )}
                      {/* Evidence snippets — direct quotes from articles that
                          established this relation (forwarded from S9 once the
                          S9 transform fix is deployed). WHY limit to 2: the
                          sidebar column is narrow — two snippets give enough
                          primary-source context without overwhelming the view. */}
                      {edge.evidence_snippets && edge.evidence_snippets.length > 0 && (
                        <div className="mt-1 space-y-0.5">
                          {edge.evidence_snippets.slice(0, 2).map((snippet, i) => (
                            <p
                              key={i}
                              className="text-[9px] leading-relaxed text-muted-foreground/70 italic line-clamp-2"
                            >
                              &ldquo;{snippet}&rdquo;
                            </p>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Key metrics grid ──────────────────────────────────────────── */}
          {Object.keys(displayIntel.key_metrics).length > 0 && (
            <div>
              <SectionHeader title="Key Metrics" />
              <KeyMetricsGrid metrics={displayIntel.key_metrics} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
