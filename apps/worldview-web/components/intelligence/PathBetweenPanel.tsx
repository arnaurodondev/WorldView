/**
 * components/intelligence/PathBetweenPanel.tsx — "How are these related?" pairwise UI
 * (PLAN-0112 T-5-03)
 *
 * WHY THIS EXISTS:
 * The global feed answers "what's weird in the graph?". This panel answers the
 * complementary, user-directed question: "is entity A connected to entity B, and
 * if so, how?". The analyst picks two entities; we call the pairwise pathfinder
 * and render the connectivity verdict + ranked paths, or a clean "no meaningful
 * connection" empty state.
 *
 * DATA SOURCE: GET /v1/paths/between via usePathBetween (enabled only when both
 * endpoints are chosen).
 *
 * ENTITY PICKER — DESIGN CHOICE (documented per the task brief):
 * The codebase has NO standalone entity autocomplete primitive. It DOES have
 * `searchInstruments` (S9 /v1/search/instruments) which returns candidates, but
 * that endpoint returns instrument ids and sets `entity_id = instrument_id`
 * (S3 has no real entity link). The reliable entity_id comes from `searchFundamentals`
 * (search → company-overview enrichment) which IS on the gateway. To keep this
 * panel self-contained and avoid `this`-binding issues, we use the gateway's
 * `searchFundamentals(q)` via the existing useApiClient() — it returns
 * SearchResult.entity_id (the real KG entity id) which is exactly what the
 * pairwise endpoint needs. A minimal debounced text input + results dropdown is
 * built here (no new shadcn dependency); if a shared EntityPicker primitive is
 * added later, this should be swapped to it.
 *
 * DESIGN: Midnight Pro dark palette, shadcn/ui (Input) only. Painting-safe tokens.
 */

"use client";
// WHY "use client": uses useState (picker state), the debounce hook, and the
// TanStack Query hooks — all browser-only.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { usePathBetween } from "@/lib/api/intelligence";
import { useDebounce } from "@/hooks/useDebounce";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PathChain } from "@/components/intelligence/PathChain";
import { WeirdnessBreakdown } from "@/components/intelligence/WeirdnessBreakdown";
import type { PathBetweenPublic } from "@/types/intelligence";
import type { SearchResult } from "@/types/api";

// ── Chosen-entity shape ───────────────────────────────────────────────────────
// We only need the id + a display name once an entity is selected.
interface ChosenEntity {
  entityId: string;
  name: string;
}

// ── EntityPicker ──────────────────────────────────────────────────────────────

/**
 * EntityPicker — minimal debounced search box → results dropdown → onSelect.
 *
 * WHY built inline (not a shared primitive): see the file header. It is intentionally
 * small and local; extracting it is a future refactor once a second caller exists.
 */
function EntityPicker({
  label,
  value,
  onSelect,
  onClear,
}: {
  label: string;
  value: ChosenEntity | null;
  onSelect: (e: ChosenEntity) => void;
  onClear: () => void;
}) {
  const gw = useApiClient();
  const [query, setQuery] = useState("");
  // Debounce so we only hit S9 when the user pauses typing (same 300ms as
  // GlobalSearch). Empty / very short queries never fire.
  const debounced = useDebounce(query, 300);

  // WHY enabled gate on length>=2 AND no current selection: don't search while a
  // value is already chosen (the input is hidden then), and skip 1-char noise.
  const { data, isFetching } = useQuery({
    queryKey: ["pathbetween-entity-search", debounced],
    // searchFundamentals enriches each candidate with the REAL KG entity_id
    // (see lib/api/search.ts) — exactly what the pairwise endpoint needs.
    queryFn: () => gw.searchFundamentals(debounced, 8),
    enabled: debounced.trim().length >= 2 && value === null,
    staleTime: 60_000,
  });

  // Selected state: show the chosen entity as a chip with a clear (×) button.
  if (value) {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <div className="flex items-center gap-2 rounded-[2px] border border-primary/40 bg-primary/10 px-2 py-1">
          <span className="flex-1 truncate text-[11px] font-mono text-primary">
            {value.name}
          </span>
          <button
            type="button"
            onClick={() => {
              onClear();
              setQuery("");
            }}
            className="text-[12px] leading-none text-muted-foreground hover:text-foreground"
            aria-label={`Clear ${label}`}
          >
            ×
          </button>
        </div>
      </div>
    );
  }

  // Unselected state: search input + results dropdown.
  return (
    <div className="relative flex flex-col gap-1">
      <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <Input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search entity…"
        className="h-7 text-[11px]"
        aria-label={`${label} entity search`}
      />

      {/* Results dropdown — only when the user has typed enough to search. */}
      {debounced.trim().length >= 2 && (
        <div className="absolute top-full z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-[2px] border border-border/60 bg-popover shadow-lg">
          {isFetching && (
            <div className="space-y-1 p-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-full" />
            </div>
          )}
          {!isFetching && (data?.results.length ?? 0) === 0 && (
            <p className="p-2 font-mono text-[10px] text-muted-foreground">
              No matching entities
            </p>
          )}
          {!isFetching &&
            (data?.results ?? []).map((r: SearchResult) => (
              <button
                key={r.entity_id}
                type="button"
                onClick={() => onSelect({ entityId: r.entity_id, name: r.name })}
                className="block w-full px-2 py-1 text-left text-[11px] font-mono text-foreground/90 hover:bg-muted/60"
              >
                <span className="text-primary">{r.ticker}</span>
                {"  "}
                <span className="text-foreground/70">{r.name}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

// ── PathBetweenPanel ──────────────────────────────────────────────────────────

export function PathBetweenPanel() {
  const [source, setSource] = useState<ChosenEntity | null>(null);
  const [target, setTarget] = useState<ChosenEntity | null>(null);

  // The hook is mounted unconditionally (hooks rule) but its `enabled` gate keeps
  // it idle until BOTH endpoints are chosen — passing "" until then.
  const { data, isFetching, isError } = usePathBetween(
    source?.entityId ?? "",
    target?.entityId ?? "",
    { maxHops: 3, limit: 10, meaningfulOnly: true },
  );

  const bothChosen = source !== null && target !== null;

  return (
    <div className="flex h-full flex-col">
      {/* ── Picker row ───────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 border-b border-border/50 px-3 py-3">
        <EntityPicker
          label="Source"
          value={source}
          onSelect={setSource}
          onClear={() => setSource(null)}
        />
        <EntityPicker
          label="Target"
          value={target}
          onSelect={setTarget}
          onClear={() => setTarget(null)}
        />
      </div>

      {/* ── Result body ──────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto py-2">
        {/* Prompt before both endpoints are chosen. */}
        {!bothChosen && (
          <p className="p-3 text-center font-mono text-[11px] text-muted-foreground">
            Pick two entities to see how they are connected
          </p>
        )}

        {bothChosen && isFetching && (
          <div className="space-y-3 p-3">
            <Skeleton className="h-6 w-1/2" />
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-[84px] w-full" />
            ))}
          </div>
        )}

        {bothChosen && isError && (
          <p className="p-3 text-center font-mono text-[11px] text-muted-foreground">
            Failed to compute connection
          </p>
        )}

        {bothChosen && !isFetching && !isError && data && (
          <>
            {/* Connectivity verdict headline. */}
            {data.connected ? (
              <p className="px-3 pb-2 font-mono text-[11px] text-positive">
                Connected
                {data.shortest_hops != null && (
                  <> · shortest path {data.shortest_hops} hop
                    {data.shortest_hops !== 1 ? "s" : ""}</>
                )}
                {" · "}
                {data.paths.length} path{data.paths.length !== 1 ? "s" : ""} found
              </p>
            ) : (
              // Clean empty state when there is no meaningful connection.
              <div className="p-3 text-center">
                <p className="font-mono text-[12px] text-foreground/80">
                  No meaningful connection found
                </p>
                <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                  {source?.name} and {target?.name} are not linked within{" "}
                  {/* maxHops we passed above */}3 hops in the knowledge graph.
                </p>
              </div>
            )}

            {/* Ranked path cards (only when connected with paths). */}
            {data.connected &&
              data.paths.map((path: PathBetweenPublic, i: number) => {
                const pct = Math.round(
                  Math.min(1, Math.max(0, path.weirdness)) * 100,
                );
                return (
                  <div
                    key={i}
                    className="mx-3 mb-2 rounded-[2px] border border-border/50 bg-card/40 p-3"
                    role="article"
                    aria-label={`${path.hop_count}-hop path, weirdness ${pct}%`}
                  >
                    <div className="mb-2 flex items-center justify-between">
                      <span className="inline-block rounded-[2px] bg-muted px-1.5 py-0.5 text-[10px] font-mono font-medium uppercase text-muted-foreground">
                        {path.hop_count}hop
                      </span>
                      <div className="flex items-center gap-1.5">
                        <div
                          className="h-1.5 w-[48px] overflow-hidden rounded-full bg-muted"
                          role="progressbar"
                          aria-valuenow={pct}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-label={`Weirdness: ${pct}%`}
                        >
                          <div
                            className="h-full rounded-full bg-primary"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-[10px] font-mono tabular-nums text-foreground/80">
                          {pct}%
                        </span>
                      </div>
                    </div>

                    <PathChain
                      nodes={path.path_nodes}
                      edges={path.path_edges}
                      highlightEntityId={source?.entityId}
                      className="my-2"
                    />

                    <WeirdnessBreakdown
                      reliability={path.reliability}
                      unexpectedness={path.unexpectedness}
                      semantic_distance={path.semantic_distance}
                      novelty={path.novelty}
                      className="mt-2 border-t border-border/30 pt-2"
                    />
                  </div>
                );
              })}
          </>
        )}
      </div>
    </div>
  );
}
