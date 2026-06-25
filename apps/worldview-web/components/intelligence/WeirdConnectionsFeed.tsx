/**
 * components/intelligence/WeirdConnectionsFeed.tsx — global "weird connections" feed
 * (PLAN-0112 T-5-03)
 *
 * WHY THIS EXISTS:
 * This is the headline discovery surface of PLAN-0112. It shows a graph-WIDE ranked
 * list of the most surprising multi-hop connections in the knowledge graph — e.g.
 * "Apple →…→ a Norwegian sovereign fund →…→ a defence contractor" — ranked by the
 * precomputed "weirdness" score. Unlike the per-entity PathsTab, it is not scoped
 * to one entity; it answers "what's the weirdest thing in the whole graph?".
 *
 * DATA SOURCE: GET /v1/connections/weird via useWeirdConnections (5-min staleTime).
 *
 * WHY CARDS (not a dense table):
 * Each connection is a rich object — a multi-node path PLUS four sub-scores. A
 * table row can't hold the path visualisation legibly. Cards give each connection
 * its own container with the path chain as the focal element and the score
 * breakdown beneath, matching the existing PathsTab card idiom.
 *
 * FILTER CONTROLS (top bar):
 *   - min-weirdness slider (0–100%) → only show connections above the floor.
 *   - limit buttons (10 / 25 / 50) → page size.
 * Both feed back into the hook's filters, which are part of the query key, so each
 * filter combination is cached independently (instant when revisited).
 *
 * DESIGN: Midnight Pro dark palette, shadcn/ui only (Slider, Skeleton). All colour
 * via guaranteed-painting token classes (bg-primary/bg-muted/text-*-foreground) to
 * dodge the known hsl(var()) no-paint bug class — verified the bars/pills paint.
 */

"use client";
// WHY "use client": uses the TanStack Query hook + local filter state (useState).

import { useState } from "react";
import Link from "next/link";
import { useWeirdConnections } from "@/lib/api/intelligence";
import { Slider } from "@/components/ui/slider";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { PathChain } from "@/components/intelligence/PathChain";
import { WeirdnessBreakdown } from "@/components/intelligence/WeirdnessBreakdown";
import type { WeirdConnectionPublic } from "@/types/intelligence";

// ── Page-size options ─────────────────────────────────────────────────────────
// WHY a fixed set (not a free input): a feed is browsed in chunks; three presets
// cover "quick look / standard / deep" without an unbounded number that could time
// out the precomputed query. 25 is the default (matches the §6.2 backend default).
const LIMIT_OPTIONS = [10, 25, 50] as const;

// ── WeirdConnectionCard ───────────────────────────────────────────────────────

/**
 * One ranked connection. WHY a separate sub-component: keeps the feed's map() body
 * small and makes the card independently testable.
 */
function WeirdConnectionCard({ conn }: { conn: WeirdConnectionPublic }) {
  // Headline weirdness as a 0–100 %.
  const pct = Math.round(Math.min(1, Math.max(0, conn.weirdness)) * 100);

  // Endpoint names for the deep-link labels (first + last node of the path).
  const srcName = conn.path_nodes[0]?.name ?? "source";
  const dstName = conn.path_nodes[conn.path_nodes.length - 1]?.name ?? "target";

  return (
    <div
      className="mx-3 mb-2 rounded-[2px] border border-border/50 bg-card/40 p-3"
      role="article"
      aria-label={`${conn.hop_count}-hop weird connection, weirdness ${pct}%`}
    >
      {/* ── Header: hop badge + endpoint deep-links + weirdness headline ──── */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="inline-block rounded-[2px] bg-muted px-1.5 py-0.5 text-[10px] font-mono font-medium uppercase text-muted-foreground">
            {conn.hop_count}hop
          </span>
          {/* WHY deep-links to the intelligence page: clicking an endpoint takes
              the analyst from "this is weird" to "investigate this entity". */}
          <Link
            href={`/intelligence/${encodeURIComponent(conn.src_entity_id)}`}
            className="text-[10px] font-mono text-primary hover:underline"
          >
            {srcName}
          </Link>
          <span className="text-[10px] text-muted-foreground">↔</span>
          <Link
            href={`/intelligence/${encodeURIComponent(conn.dst_entity_id)}`}
            className="text-[10px] font-mono text-primary hover:underline"
          >
            {dstName}
          </Link>
        </div>

        {/* Weirdness headline bar */}
        <div className="flex items-center gap-1.5">
          <div
            className="h-1.5 w-[48px] overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Weirdness: ${pct}%`}
          >
            <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-[10px] font-mono tabular-nums text-foreground/80">
            {pct}%
          </span>
        </div>
      </div>

      {/* ── Path chain ───────────────────────────────────────────────────── */}
      <PathChain nodes={conn.path_nodes} edges={conn.path_edges} className="my-2" />

      {/* ── Sub-score breakdown ──────────────────────────────────────────── */}
      <WeirdnessBreakdown
        reliability={conn.reliability}
        unexpectedness={conn.unexpectedness}
        semantic_distance={conn.semantic_distance}
        novelty={conn.novelty}
        className="mt-2 border-t border-border/30 pt-2"
      />
    </div>
  );
}

// ── WeirdConnectionsFeed ──────────────────────────────────────────────────────

export function WeirdConnectionsFeed() {
  // Local filter state. WHY local (not URL): this is an exploratory panel; the
  // filters are ephemeral session preferences, not deep-linkable views.
  const [minWeirdnessPct, setMinWeirdnessPct] = useState(0); // 0–100 (UI units)
  const [limit, setLimit] = useState<number>(25);

  // Convert the slider's 0–100 UI value to the 0–1 the API expects. We only pass
  // min_weirdness when the user has moved the slider off zero (keep URLs minimal).
  const { data, isLoading, isError } = useWeirdConnections({
    limit,
    minWeirdness: minWeirdnessPct > 0 ? minWeirdnessPct / 100 : undefined,
  });

  return (
    <div className="flex h-full flex-col">
      {/* ── Filter bar ───────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-4 border-b border-border/50 px-3 py-2">
        {/* Min-weirdness slider */}
        <div className="flex min-w-[180px] items-center gap-2">
          <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            Min weirdness
          </span>
          <Slider
            // WHY value (controlled): the displayed % readout must stay in sync
            // with the slider; a controlled value guarantees a single source.
            value={[minWeirdnessPct]}
            min={0}
            max={100}
            step={5}
            onValueChange={(v) => setMinWeirdnessPct(v[0] ?? 0)}
            className="w-24"
            aria-label="Minimum weirdness filter"
          />
          <span className="w-8 text-right text-[10px] font-mono tabular-nums text-foreground/80">
            {minWeirdnessPct}%
          </span>
        </div>

        {/* Limit (page size) buttons */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            Show
          </span>
          {LIMIT_OPTIONS.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => setLimit(opt)}
              aria-pressed={limit === opt}
              className={cn(
                "rounded-[2px] border px-1.5 py-0.5 text-[10px] font-mono transition-colors",
                limit === opt
                  ? "border-primary/40 bg-primary/20 text-primary"
                  : "border-border/60 bg-muted/40 text-muted-foreground hover:bg-muted/70",
              )}
            >
              {opt}
            </button>
          ))}
        </div>
      </div>

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto py-2">
        {isLoading && (
          <div className="space-y-3 p-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[96px] w-full" />
            ))}
          </div>
        )}

        {isError && (
          <p className="p-3 text-center font-mono text-[11px] text-muted-foreground">
            Failed to load weird connections
          </p>
        )}

        {!isLoading && !isError && (!data || data.connections.length === 0) && (
          <p className="p-3 text-center font-mono text-[11px] text-muted-foreground">
            No weird connections match the current filters
          </p>
        )}

        {!isLoading && !isError && data && data.connections.length > 0 && (
          <>
            {/* Freshness + total summary line. */}
            <p className="px-3 pb-2 font-mono text-[10px] text-muted-foreground">
              {data.total} ranked connections
              {data.freshness_ts && (
                <>
                  {" · computed "}
                  {new Intl.DateTimeFormat("en-US", {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(data.freshness_ts))}
                </>
              )}
            </p>

            {data.connections.map((conn, i) => (
              // WHY composite key: a connection has no own id; src+dst+index is
              // stable within a single response render.
              <WeirdConnectionCard
                key={`${conn.src_entity_id}-${conn.dst_entity_id}-${i}`}
                conn={conn}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
