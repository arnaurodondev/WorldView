/**
 * components/instrument/intelligence/IntelligenceSummarySection.tsx
 *
 * WHY THIS EXISTS:
 * Extracted from IntelligenceTab.tsx (was lines 287-574) so the tab orchestrator
 * stays under 400 lines while each concern lives in a focused file.
 *
 * This section renders the rich PLAN-0074 payload at the very top of the
 * Intelligence tab — health score badge, LLM narrative, evidence quality
 * breakdown, source distribution, key metrics, and the 90-day confidence
 * trend sparkline.
 *
 * WHY 2-COL SPLIT (left = cards, right = trend):
 * On the instrument page the Intelligence tab is already squeezed by the
 * (optional) AnalystRail on the right. A 2-col internal split (60/40) keeps the
 * narrative text wide enough to read while pinning the small sparkline + jump
 * links to the right where they don't compete for attention.
 *
 * WHY hide silently when API errors:
 * The graph + brief sections below still work without /intelligence. Showing a
 * loud error tile when only this top section fails would penalise users who still
 * have valid graph data. Silent hide keeps the tab usable.
 *
 * DATA SOURCE: useEntityIntelligence → GET /v1/entities/{id}/intelligence
 *
 * WHO USES IT: components/instrument/IntelligenceTab.tsx
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ExternalLink, ArrowUpRight } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { useEntityIntelligence } from "@/lib/api/intelligence";
import { HealthScoreBadge } from "@/components/intelligence/HealthScoreBadge";
import { NarrativeCard } from "@/components/intelligence/NarrativeCard";
import { ConfidenceTrendSparkline } from "@/components/intelligence/ConfidenceTrendSparkline";
import { SourceDistributionList } from "@/components/intelligence/SourceDistributionList";
import { KeyMetricsGrid } from "@/components/intelligence/KeyMetricsGrid";

// ── Props ─────────────────────────────────────────────────────────────────────

interface IntelligenceSummarySectionProps {
  entityId: string;
}

// ── IntelligenceSummarySection ────────────────────────────────────────────────

export function IntelligenceSummarySection({ entityId }: IntelligenceSummarySectionProps) {
  const router = useRouter();
  // useEntityIntelligence is the canonical Wave H hook for `/v1/entities/{id}/intelligence`.
  // It already handles auth (useAccessToken), caching (1-min staleTime aligned with KG
  // pipeline cycle), and the !!entityId/!!token enabled guard — same hook used by the
  // standalone /intelligence/[entity_id] page so any future bug fix lands in one place.
  const { data: intel, isLoading, isError } = useEntityIntelligence(entityId);

  // ── Loading skeleton ────────────────────────────────────────────────────────
  // WHY a skeleton (not a spinner): the section has multiple cards arriving
  // together; a skeleton communicates the eventual shape so analysts visually
  // anchor to the layout before content arrives — avoiding layout shift.
  if (isLoading) {
    return (
      <section className="p-3">
        <div className="flex items-center gap-3 mb-3">
          <Skeleton className="h-12 w-12 rounded-full shrink-0" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-3">
          <Skeleton className="h-[140px] w-full" />
          <Skeleton className="h-[140px] w-full" />
        </div>
      </section>
    );
  }

  // WHY hide on error or no data: see component header comment. Graph/brief
  // sections below still render and provide value; we keep the tab usable.
  if (isError || !intel) {
    return null;
  }

  const trend = intel.confidence_breakdown?.confidence_trend ?? [];
  const hasMetrics = intel.key_metrics && Object.keys(intel.key_metrics).length > 0;
  const hasSources = (intel.confidence_breakdown?.source_distribution?.length ?? 0) > 0;
  // WHY show evidence quality only when we have at least one signal:
  // template-v1 narratives often lack mean_corroboration / mean_contradiction,
  // and rendering "Support 80%" alone with everything else N/A reads as broken.
  const hasEvidenceSignals =
    intel.confidence_breakdown?.mean_support != null ||
    intel.confidence_breakdown?.mean_corroboration != null ||
    intel.confidence_breakdown?.mean_contradiction != null ||
    intel.confidence_breakdown?.relation_count > 0;

  return (
    <section className="p-3 space-y-3">
      {/* ── Header strip: health + entity name + deep-link to full page ──── */}
      {/* WHY a strip (not a full hero): the instrument page already has its own
          CompactInstrumentHeader at the top. We don't repeat the price; we add
          KG-specific signals (health score) and a path to the full intelligence page. */}
      <div className="flex items-center gap-3">
        {/* HealthScoreBadge is purely visual — no hooks. Reused from the
            EntitySidebar so the same color thresholds apply everywhere. */}
        <HealthScoreBadge
          score={intel.health_score ?? null}
          size={48}
          className="shrink-0"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <h2 className="text-[13px] font-semibold text-foreground truncate">
              {intel.canonical_name}
            </h2>
            <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
              {intel.entity_type?.replace(/_/g, " ")}
            </span>
            {intel.data_completeness != null && (
              <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
                · {Math.round(intel.data_completeness * 100)}% complete
              </span>
            )}
          </div>
          <p className="text-[10px] text-muted-foreground mt-0.5">
            Knowledge graph intelligence summary
          </p>
        </div>
        {/* Deep-link to /intelligence/[entity_id] — closes the discovery gap
            identified in audit 2026-05-09 G3 (orphan route had no entry point).
            WHY router.push (not Link href): the instrument page is a deep route
            with state we want to preserve via browser back; router.push handles
            the back-stack correctly without prefetching an entire 3-col page on
            hover. Link href would prefetch all four panel queries on tab load. */}
        <button
          type="button"
          onClick={() => router.push(`/intelligence/${encodeURIComponent(entityId)}`)}
          className="shrink-0 flex items-center gap-1 rounded-[2px] border border-border/60 bg-card/60 px-2 py-1 text-[10px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground hover:border-border transition-colors"
          aria-label="Open full intelligence page"
        >
          <ExternalLink className="h-3 w-3" strokeWidth={1.5} />
          Full page
        </button>
      </div>

      {/* ── 2-col grid: narrative+evidence on the left, trend on the right ── */}
      {/* WHY lg breakpoint (1024px) for the split: below 1024px the right column
          becomes too narrow for the sparkline. Stacking on small viewports keeps
          everything readable; the AnalystRail forces this on tablets too. */}
      <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-3">

        {/* ── LEFT: narrative + evidence breakdown + sources + key metrics ── */}
        <div className="space-y-3">
          {/* NarrativeCard handles its own truncate/expand + Regenerate mutation.
              We pass the entityId so the regenerate button knows which entity to
              target (uses useTriggerNarrativeGeneration internally). */}
          <div className="rounded-[2px] border border-border/40 bg-card/40 p-3">
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
              Current Narrative
            </p>
            <NarrativeCard
              entityId={entityId}
              narrative={intel.current_narrative}
            />
          </div>

          {/* Evidence Quality breakdown (mirrors EntitySidebar §"Evidence Quality").
              WHY render here: the support/corroboration/contradiction triple is
              the worldview differentiator from PRD-0074 §3 FR-6. Hiding it
              behind the "Full page" button defeats the purpose of the redesign. */}
          {hasEvidenceSignals && (
            <div className="rounded-[2px] border border-border/40 bg-card/40 p-3">
              <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
                Evidence Quality
              </p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] font-mono">
                {intel.confidence_breakdown.mean_support != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Support</span>
                    <span className="tabular-nums text-foreground/90">
                      {(intel.confidence_breakdown.mean_support * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
                {intel.confidence_breakdown.mean_corroboration != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Corroboration</span>
                    <span className="tabular-nums text-foreground/90">
                      {(intel.confidence_breakdown.mean_corroboration * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
                {intel.confidence_breakdown.mean_contradiction != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Contradiction</span>
                    <span className="tabular-nums text-negative">
                      {(intel.confidence_breakdown.mean_contradiction * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Relations</span>
                  <span className="tabular-nums text-foreground/90">
                    {intel.confidence_breakdown.relation_count}
                  </span>
                </div>
                {intel.confidence_breakdown.latest_evidence_at && (
                  <div className="flex justify-between col-span-2">
                    <span className="text-muted-foreground">Latest evidence</span>
                    <span className="tabular-nums text-foreground/90">
                      {/* WHY Intl.DateTimeFormat (not toISOString().slice):
                          mirrors EntitySidebar's locale formatting so the same
                          timestamp on /intelligence and the tab look identical. */}
                      {new Intl.DateTimeFormat("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      }).format(new Date(intel.confidence_breakdown.latest_evidence_at))}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Source Distribution (PRD-0074 FR-11). Hidden when empty so the
              section doesn't show a "no sources" placeholder. */}
          {hasSources && (
            <div className="rounded-[2px] border border-border/40 bg-card/40 p-3">
              <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
                Evidence Sources
              </p>
              <SourceDistributionList
                distribution={intel.confidence_breakdown.source_distribution}
              />
            </div>
          )}

          {/* Key Metrics (entity-type-specific JSONB fields from canonical_entities) */}
          {hasMetrics && (
            <div className="rounded-[2px] border border-border/40 bg-card/40 p-3">
              <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
                Key Metrics
              </p>
              <KeyMetricsGrid metrics={intel.key_metrics} />
            </div>
          )}
        </div>

        {/* ── RIGHT: confidence trend sparkline + jump links ──────────────── */}
        <div className="space-y-3">
          {/* Confidence Trend sparkline (PRD-0074 FR-12). Show a placeholder
              tile if trend data is empty so the right column isn't blank
              while data accumulates — better than collapsing the column. */}
          <div className="rounded-[2px] border border-border/40 bg-card/40 p-3">
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
              Confidence Trend (90d)
            </p>
            {trend.length > 0 ? (
              <>
                <ConfidenceTrendSparkline data={trend} height={48} />
                <div className="flex justify-between mt-1">
                  {trend.length >= 2 && (
                    <>
                      <span className="text-[9px] font-mono text-muted-foreground">
                        {trend[0].date.slice(0, 7)}
                      </span>
                      <span className="text-[9px] font-mono text-muted-foreground">
                        {trend[trend.length - 1].date.slice(0, 7)}
                      </span>
                    </>
                  )}
                </div>
              </>
            ) : (
              <p className="text-[11px] font-mono text-muted-foreground italic py-3">
                Not enough evidence history yet — trend builds as the KG pipeline
                processes more articles.
              </p>
            )}
          </div>

          {/* Jump links — encourage exploration of the deeper page without
              forcing it. Layout mirrors the dense Bloomberg "see also" pattern. */}
          <div className="rounded-[2px] border border-border/40 bg-card/40 p-3">
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
              Explore further
            </p>
            <div className="space-y-1.5">
              {/* Each link uses next/link for client-side navigation + prefetch */}
              <Link
                href={`/intelligence/${encodeURIComponent(entityId)}`}
                className="flex items-center justify-between gap-2 text-[11px] text-foreground hover:text-primary transition-colors"
              >
                <span>Multi-hop paths & narrative history</span>
                <ArrowUpRight className="h-3 w-3 shrink-0" strokeWidth={1.5} />
              </Link>
              <Link
                href={`/intelligence/${encodeURIComponent(entityId)}#chat`}
                className="flex items-center justify-between gap-2 text-[11px] text-foreground hover:text-primary transition-colors"
              >
                <span>Ask AI about this entity</span>
                <ArrowUpRight className="h-3 w-3 shrink-0" strokeWidth={1.5} />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
