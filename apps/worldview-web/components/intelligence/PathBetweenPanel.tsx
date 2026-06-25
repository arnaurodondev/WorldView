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
 * ENTITY PICKER (PLAN-0113 W4 T-4-02): the picker was extracted to the shared
 * `components/common/EntityPicker.tsx` so the alert condition editors can reuse
 * it. It still uses `searchFundamentals` to attach the REAL KG `entity_id` (the
 * pairwise endpoint needs that, not a raw instrument_id). This panel now imports
 * the shared component instead of defining its own.
 *
 * DESIGN: Midnight Pro dark palette, shadcn/ui (Input) only. Painting-safe tokens.
 */

"use client";
// WHY "use client": uses useState (picker state) and the TanStack Query hooks —
// all browser-only.

import { useState } from "react";
import { BellPlus } from "lucide-react";
import { usePathBetween } from "@/lib/api/intelligence";
import { Skeleton } from "@/components/ui/skeleton";
import { PathChain } from "@/components/intelligence/PathChain";
import { WeirdnessBreakdown } from "@/components/intelligence/WeirdnessBreakdown";
import { EntityPicker, type ChosenEntity } from "@/components/common/EntityPicker";
// PLAN-0113 Wave 5 (T-5-01): "＋ Alert" entry point for KG_CONNECTION rules.
import { AlertWizard } from "@/components/alerts/AlertWizard";
import type { PathBetweenPublic } from "@/types/intelligence";

// ── PathBetweenPanel ──────────────────────────────────────────────────────────

export function PathBetweenPanel() {
  const [source, setSource] = useState<ChosenEntity | null>(null);
  const [target, setTarget] = useState<ChosenEntity | null>(null);
  // PLAN-0113 Wave 5: KG_CONNECTION alert wizard open-state. The "＋ Alert" button
  // (shown once both endpoints are chosen) opens it pre-scoped to KG_CONNECTION
  // with BOTH entities seeded — Journey D ("alert me when A connects to B").
  const [alertOpen, setAlertOpen] = useState(false);

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
      <div className="border-b border-border/50 px-3 py-3">
        <div className="grid grid-cols-2 gap-3">
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

        {/* ＋ Alert — only meaningful once BOTH endpoints are chosen. Opens the
            wizard pre-scoped to KG_CONNECTION with both entities seeded so the
            user only picks max_hops (+ optional relation_type). */}
        {bothChosen && (
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              onClick={() => setAlertOpen(true)}
              data-testid="kg-connection-alert-button"
              aria-label="Alert me when these entities connect"
              className="flex items-center gap-1 rounded-[2px] border border-border/50 bg-muted/20 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:border-primary/50 hover:bg-muted/40 hover:text-foreground"
            >
              <BellPlus className="size-3" aria-hidden="true" />
              Alert on connection
            </button>
          </div>
        )}
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

      {/* KG_CONNECTION alert wizard — pre-scoped + both entities seeded. Mounted
          only while both endpoints exist so the prefill is always valid. The
          editor enforces the node_a≠node_b guard; the wizard's Save flows through
          the gateway hooks (R14). */}
      {source && target && (
        <AlertWizard
          open={alertOpen}
          onOpenChange={setAlertOpen}
          initialRuleType="KG_CONNECTION"
          prefillCondition={{
            source_entity_id: source.entityId,
            target_entity_id: target.entityId,
            max_hops: 3,
          }}
          prefillNames={{
            [source.entityId]: source.name,
            [target.entityId]: target.name,
          }}
        />
      )}
    </div>
  );
}
