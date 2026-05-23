/**
 * EntitySimilarityPanel.tsx — ANN embedding similarity search results panel
 *
 * WHY THIS EXISTS:
 * Analysts need to quickly discover "similar companies" to the entity they are
 * reviewing — either to compare fundamentals or to surface competitive dynamics
 * that the KG might not yet have explicit COMPETES_WITH edges for.
 * This panel calls POST /v1/entities/similar (pgvector cosine ANN via S7) and
 * renders the top-5 nearest embedding neighbours ranked by final_score.
 *
 * WHO USES IT:
 * ContextPanel (Intelligence tab right rail), mounted inside the right column.
 * Receives the primary entity's UUIDv7 as the only prop.
 *
 * DATA SOURCE:
 * POST /v1/entities/similar → SimilarEntitiesResponse (types/api.ts)
 * via createGateway(token).getSimilarEntities(entityId, 5, 0.0)
 * The response embeds are from the narrative embedding stored in S7.
 *
 * DESIGN REFERENCE:
 * Finance terminal UX: Bloomberg-grade density. 22px rows, IBM Plex Mono on all
 * numbers, tabular-nums on scores, dark bg-[#131722] background.
 */

"use client";
// WHY "use client": useQuery + useAccessToken require the browser React context.
// Server Components cannot call hooks.

import { useQuery } from "@tanstack/react-query";
import { useAccessToken } from "@/lib/api-client";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import type { SimilarEntitiesResponse } from "@/types/api";

// ── Props ──────────────────────────────────────────────────────────────────────

export interface EntitySimilarityPanelProps {
  /** UUIDv7 of the entity being viewed on the instrument page. */
  readonly entityId: string;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function EntitySimilarityPanel({ entityId }: EntitySimilarityPanelProps) {
  const token = useAccessToken();

  // WHY useQuery with getSimilarEntities (not a dedicated hook like useEntityPaths):
  // POST /v1/entities/similar is a single-use endpoint called with fixed params
  // (topK=5, minScore=0.0). Wrapping it in a custom hook would add indirection
  // without benefit — the query key and queryFn are simple enough to inline here.
  //
  // WHY staleTime 3_600_000 (1 hour):
  // Embedding similarity scores are computed by the nightly KG pipeline run (~60 min
  // cycle). Scores don't change between pipeline runs — fetching more often wastes
  // S9/S7 capacity with zero benefit to the user. 1h matches one pipeline cycle.
  //
  // WHY getSimilarEntities returns null on 404/422:
  // 404 = entity not in KG yet; 422 = embedding not computed yet.
  // Both are expected for newly ingested instruments. The gateway returns null so
  // we show an empty state instead of throwing an error that breaks the panel.
  const { data, isLoading, isError } = useQuery<SimilarEntitiesResponse | null>({
    queryKey: qk.kg.similarEntities(entityId),
    queryFn: () =>
      createGateway(token).getSimilarEntities(entityId, 5, 0.0),
    staleTime: 3_600_000,
    // WHY enabled guard: prevents a GET /v1/entities/undefined/similar 422 on first render
    // before entityId resolves from the URL param.
    enabled: !!entityId && !!token,
    retry: 1,
  });

  // ── Loading state — 5 placeholder rows matching the data layout ────────────────
  if (isLoading) {
    return (
      <section aria-label="Similar entities" aria-busy="true" className="px-3 py-2">
        <p className="text-[10px] font-mono uppercase text-muted-foreground mb-1.5">
          SIMILAR ENTITIES
        </p>
        {/* WHY 5 rows: matches the topK=5 data request so the layout doesn't
            shift when real data arrives. animate-pulse signals async loading. */}
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton
            key={i}
            className="h-[22px] bg-muted/20 animate-pulse rounded mb-[2px]"
          />
        ))}
      </section>
    );
  }

  // ── Error state — brief inline message (not a thrown error) ───────────────────
  if (isError) {
    return (
      <section aria-label="Similar entities" className="px-3 py-2">
        <p className="text-[10px] font-mono uppercase text-muted-foreground mb-1.5">
          SIMILAR ENTITIES
        </p>
        {/* WHY not thrown: the panel is non-critical; a partial failure must not
            crash the Intelligence tab. We surface the message inline and let the
            analyst continue using the graph and context panels. */}
        <p className="text-[10px] text-muted-foreground">Similarity data unavailable</p>
      </section>
    );
  }

  // ── null = no embedding computed yet (404/422 from getSimilarEntities) ─────────
  if (data === null) {
    return (
      <section aria-label="Similar entities" className="px-3 py-2">
        <p className="text-[10px] font-mono uppercase text-muted-foreground mb-1.5">
          SIMILAR ENTITIES
        </p>
        <p className="text-[10px] text-muted-foreground">No embedding available</p>
      </section>
    );
  }

  // ── Empty results (embedding exists but ANN returned 0 results) ───────────────
  if (!data || data.results.length === 0) {
    return (
      <section aria-label="Similar entities" className="px-3 py-2">
        <p className="text-[10px] font-mono uppercase text-muted-foreground mb-1.5">
          SIMILAR ENTITIES
        </p>
        <p className="text-[10px] text-muted-foreground">No similar entities found</p>
      </section>
    );
  }

  // ── Data state — top-5 entity rows ────────────────────────────────────────────
  return (
    <section aria-label="Similar entities" className="px-3 py-2">
      <p className="text-[10px] font-mono uppercase text-muted-foreground mb-1.5">
        SIMILAR ENTITIES
      </p>
      {data.results.map((item) => {
        // WHY Math.round * 100: final_score is a 0–1 float from pgvector cosine distance.
        // Multiply by 100 and round to get a clean integer percentage (e.g. 0.874 → "87%").
        const pct = Math.round(item.final_score * 100);

        return (
          <div
            key={item.entity_id}
            className="h-[22px] flex items-center gap-1.5"
          >
            {/* ── Company name (primary label) ─────────────────────────────── */}
            <span className="text-[10px] font-mono text-foreground/90 truncate min-w-0 flex-1">
              {item.canonical_name}
            </span>

            {/* ── Ticker (if available — financial_instrument entities only) ── */}
            {item.ticker && (
              <span className="text-[9px] font-mono text-muted-foreground shrink-0">
                {item.ticker}
              </span>
            )}

            {/* ── COMP badge (existing KG COMPETES_WITH edge detected) ───────
                WHY show only when has_competes_with_relation: the badge signals
                that S7 already has a confirmed edge — gives the analyst confidence
                that the similarity signal is backed by explicit KG evidence, not
                just embedding proximity alone. */}
            {item.has_competes_with_relation && (
              <span className="text-[8px] font-mono uppercase bg-[#EF5350]/10 text-[#EF5350] px-1 rounded shrink-0">
                COMP
              </span>
            )}

            {/* ── Similarity percentage (right-aligned) ─────────────────────
                WHY tabular-nums: prevents horizontal jitter as the score digits
                change width when scrolling through entities with different scores
                (e.g. "87%" vs "100%"). font-mono aligns with all numeric values
                in the finance terminal design system. */}
            <span className="text-[9px] font-mono tabular-nums text-muted-foreground shrink-0">
              {pct}%
            </span>
          </div>
        );
      })}
    </section>
  );
}
