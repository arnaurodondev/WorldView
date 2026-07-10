/**
 * components/intelligence/EntityPredictionsSection.tsx — "Prediction markets
 * referencing this entity" (PLAN-0056 Wave E2, task 6).
 *
 * ── WHY AN ENTITY-PAGE SECTION (not per-market chips on the list) ──
 * The prediction-markets LIST payload does not carry the entities a market
 * references (S3's summary has no entity_ids on the wire). The RICH direction is
 * the reverse edge: S7 GET /v1/entities/{id}/predictions returns, for one
 * entity, every market that references it PLUS the LLM-classified `polarity`
 * (bullish/bearish/neutral) — the "is this market for or against the company?"
 * read that is the whole point of the KG entity-linking. Surfacing that on the
 * entity intelligence page is strictly higher-value than scattering unlabelled
 * chips on list rows, and it's honest to the data we actually hold. Documented
 * in docs/apps/worldview-web.md.
 *
 * Each row shows the market question, a polarity indicator (green bullish / red
 * bearish / muted neutral), the entity-link confidence, and an external link to
 * the market. Links use buildPolymarketUrl(null, question) — the entity endpoint
 * carries a condition_id (not a slug), so the title-search fallback is the
 * honest best link (same helper the list + widget use).
 */

"use client";
// WHY "use client": query hook + reads the auth token.

import { useEntityPredictions } from "@/lib/api/prediction-markets-hooks";
import { buildPolymarketUrl } from "@/lib/prediction-markets";
import { Skeleton } from "@/components/ui/skeleton";
import { ExternalLink, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EntityPrediction } from "@/types/api";

interface EntityPredictionsSectionProps {
  entityId: string;
}

/** Section header matching the EntitySidebar idiom (mono 10px uppercase). */
function SectionHeader() {
  return (
    <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
      Prediction Markets
    </p>
  );
}

// ── Polarity → colour + icon (bullish green / bearish red / neutral muted) ────
function polarityStyle(polarity: string | null): {
  cls: string;
  Icon: typeof TrendingUp;
  label: string;
} {
  const p = (polarity ?? "").toLowerCase();
  if (p === "bullish") return { cls: "text-positive", Icon: TrendingUp, label: "bullish" };
  if (p === "bearish") return { cls: "text-negative", Icon: TrendingDown, label: "bearish" };
  return { cls: "text-muted-foreground", Icon: Minus, label: "neutral" };
}

function PredictionRow({ item }: { item: EntityPrediction }) {
  const { cls, Icon, label } = polarityStyle(item.polarity);
  // condition_id is not a Polymarket slug → title-search fallback (honest link).
  const url = buildPolymarketUrl(null, item.question);
  const confPct = Math.round(item.confidence * 100);

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="entity-prediction-row"
      className="group flex items-start gap-2 rounded-[2px] border border-border/30 bg-muted/20 px-2 py-1.5 hover:bg-muted/40"
    >
      {/* Polarity indicator */}
      <span
        data-testid="polarity-indicator"
        data-polarity={label}
        className={cn("mt-0.5 shrink-0", cls)}
        title={`Directional read for this entity: ${label}`}
        aria-label={`Polarity: ${label}`}
      >
        <Icon className="h-3 w-3" strokeWidth={2} aria-hidden />
      </span>

      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-[10px] text-foreground/90 group-hover:text-primary">
          {item.question}
        </span>
        <span className="mt-0.5 flex items-center gap-2 font-mono text-[9px] text-muted-foreground">
          <span className={cn("uppercase tracking-wider", cls)}>{label}</span>
          <span className="tabular-nums">· {confPct}% link</span>
        </span>
      </span>

      <ExternalLink
        className="mt-0.5 h-2.5 w-2.5 shrink-0 text-muted-foreground group-hover:text-primary"
        strokeWidth={1.5}
        aria-hidden
      />
    </a>
  );
}

export function EntityPredictionsSection({ entityId }: EntityPredictionsSectionProps) {
  const { data, isLoading, isError } = useEntityPredictions(entityId, { limit: 10 });

  // Loading: a couple of skeleton rows so the sidebar doesn't jump.
  if (isLoading) {
    return (
      <div data-testid="entity-predictions-loading">
        <SectionHeader />
        <div className="space-y-1.5">
          <Skeleton className="h-8 w-full rounded-[2px]" />
          <Skeleton className="h-8 w-full rounded-[2px]" />
        </div>
      </div>
    );
  }

  // Error OR no linked markets → render nothing. Absence of prediction-market
  // links is the COMMON case for most entities, so an empty "no data" block
  // would be noise. The caller renders the section header only when this returns
  // content (see hasContent below), so we return null here.
  const items = data?.items ?? [];
  if (isError || items.length === 0) return null;

  return (
    <div data-testid="entity-predictions">
      <SectionHeader />
      <div className="space-y-1.5">
        {items.map((item) => (
          <PredictionRow key={item.condition_id || item.question} item={item} />
        ))}
      </div>
    </div>
  );
}
