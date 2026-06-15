/**
 * components/instrument/graph/GraphToolbar.tsx — Compact toolbar for EntityGraph
 *
 * WHY THIS EXISTS (T-D-01 / PLAN-0090): The Intelligence tab needs a small,
 * dedicated toolbar that drives the two highest-signal graph filters: traversal
 * depth (1–3) and an entity-type whitelist.  Previously the depth slider was
 * embedded in the IntelligenceTab filter rail alongside time-window and other
 * controls, which made it hard to scan and hard to test in isolation.  This
 * toolbar is a pure presentational component — the parent owns state and the
 * callbacks; the toolbar never mutates the graph directly.
 *
 * WHY depth 1–3 (not 1–5): PRD-0088 §6.10 caps the interactive sigma graph at
 * depth 3 because the AGE Cypher traversal cost is O(n³) and depth=3 already
 * yields ~80 edges at the AAPL scale — depth=4/5 routinely time out and the
 * graph is unreadable.  The slider step is 1 so each tick is a discrete depth.
 *
 * ENTITY-TYPE FILTER — MULTISELECT (2026-06-15 enhancement):
 * Previously this was a single-value Radix <Select> with an "All types"
 * sentinel: the analyst could focus exactly ONE type or see everything, but
 * NOT, say, "people AND organizations" together. A graph investigation often
 * needs a SUBSET of types at once (e.g. hide instruments to study the
 * people/org/event subgraph). We replaced the single-select with a Popover
 * containing a checkbox per available type, so the whitelist is a true
 * multiselect (`string[]`). The empty array still means "show all" — exactly
 * the contract GraphColumn's filter already expects (it returns the unfiltered
 * graph when `typeFilters.length === 0`), so NO change was needed downstream.
 *
 * WHY a Popover+checkbox list (not a row of pills): the canonical type list
 * has 8+ values at the NVDA scale (financial_instrument, person, organization,
 * place, index, product, exchange, unknown, …). Inline pills would wrap to two
 * rows on the narrow centre column and steal vertical space from the graph.
 * The Popover keeps the toolbar to a single ~28px row; a count badge on the
 * trigger ("3 types") tells the analyst the filter is active without opening it.
 *
 * STATE OWNERSHIP: the parent component holds the canonical filter state
 * (depth: number, entityTypes: string[]).  This toolbar receives the state
 * + callbacks and is fully controlled — no internal filter useState (the
 * Popover open/closed flag is purely local UI chrome).  That makes it
 * trivial to unit-test (render with props, click, assert callback fired).
 */

"use client";

import * as React from "react";
import { Check, ChevronDown } from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────
// WHY availableEntityTypes is required (not optional): the toolbar can't invent
// types out of thin air — it shows the types that exist in the current graph
// response.  Passing [] means "no types known yet" (loading state) and the
// dropdown is rendered disabled.

export interface GraphToolbarProps {
  /** Current traversal depth (1, 2, or 3). */
  depth: number;
  /** Called when the depth slider changes. */
  onDepthChange: (depth: number) => void;
  /** Entity types currently selected as a whitelist; [] means "show all". */
  selectedEntityTypes: string[];
  /** Called with the new whitelist when the user picks a type. */
  onEntityTypesChange: (types: string[]) => void;
  /** Entity types that exist in the current graph (sorted asc).  Empty = loading. */
  availableEntityTypes: string[];
}

/** Present a raw enum value ("financial_instrument") as a human label
 *  ("Financial instrument") without mutating the value used in the callback. */
function prettyType(type: string): string {
  return type.replace(/_/g, " ");
}

export function GraphToolbar({
  depth,
  onDepthChange,
  selectedEntityTypes,
  onEntityTypesChange,
  availableEntityTypes,
}: GraphToolbarProps) {
  // WHY a Set for membership tests: the checkbox list calls includes() once per
  // available type on every render; a Set makes each check O(1) and reads
  // clearly as "is this type in the active whitelist?".
  const selected = React.useMemo(
    () => new Set(selectedEntityTypes),
    [selectedEntityTypes],
  );

  // Toggle one type in/out of the whitelist. We rebuild a fresh array (never
  // mutate the prop) so React/TanStack see a new reference and the parent's
  // useMemo'd filteredGraph recomputes.
  const toggleType = (type: string) => {
    const next = new Set(selected);
    if (next.has(type)) next.delete(type);
    else next.add(type);
    onEntityTypesChange(Array.from(next));
  };

  // "Clear" resets to the show-all state (empty whitelist) in one click.
  const clearTypes = () => onEntityTypesChange([]);

  // Trigger label: "All types" when nothing is whitelisted, otherwise the
  // single type's name (so the common focus-one case reads naturally) or an
  // "N types" count when several are active.
  const activeCount = selectedEntityTypes.length;
  const triggerLabel =
    activeCount === 0
      ? "All types"
      : activeCount === 1
        ? prettyType(selectedEntityTypes[0])
        : `${activeCount} types`;

  return (
    <div
      data-testid="graph-toolbar"
      className="flex flex-wrap items-center gap-3 rounded-[2px] border border-border/40 bg-card/40 px-2 py-1.5"
    >
      {/* ── Depth slider ──────────────────────────────────────────────────── */}
      {/* WHY label + value badge: the slider thumb does not display the current
          value, so a static "Depth: N" label keeps the analyst informed without
          forcing them to read the thumb position. */}
      <div className="flex items-center gap-2" data-testid="depth-slider-container">
        <span className="whitespace-nowrap text-[10px] uppercase tracking-wide text-muted-foreground">
          Depth
        </span>
        <Slider
          data-testid="depth-slider"
          value={[depth]}
          onValueChange={([v]) => onDepthChange(v ?? 1)}
          min={1}
          max={3}
          step={1}
          // WHY w-24: matches the strength slider in EntityGraph for visual
          // consistency.  Two integer steps (1→2→3) don't need more travel.
          className="w-24"
        />
        <span
          data-testid="depth-value"
          className="font-mono text-[10px] tabular-nums text-foreground"
        >
          {depth}
        </span>
      </div>

      {/* ── Entity-type filter — MULTISELECT popover ──────────────────────── */}
      {/* WHY disabled when availableEntityTypes is empty: an empty popover lets
          the analyst open a panel with no checkboxes — confusing. Disabled
          communicates "waiting for graph data". */}
      <div className="flex items-center gap-2" data-testid="entity-type-container">
        <span className="whitespace-nowrap text-[10px] uppercase tracking-wide text-muted-foreground">
          Type
        </span>
        <Popover>
          {/* The trigger doubles as the active-filter readout: "All types",
              one type name, or an "N types" count. A count badge keeps the
              active-filter signal visible without opening the panel. */}
          <PopoverTrigger
            data-testid="entity-type-select"
            disabled={availableEntityTypes.length === 0}
            className={cn(
              "flex h-7 w-[150px] items-center justify-between rounded-[2px] border border-border/40 bg-card px-2 text-[11px]",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
            aria-label="Filter graph by entity type"
          >
            <span className="truncate capitalize">{triggerLabel}</span>
            <div className="flex items-center gap-1">
              {/* Count pill only when MORE than one type is active — a single
                  type already shows its name, and 0 shows "All types". */}
              {activeCount > 1 && (
                <span className="rounded-[2px] bg-primary/20 px-1 font-mono text-[9px] tabular-nums text-primary">
                  {activeCount}
                </span>
              )}
              <ChevronDown className="h-3 w-3 shrink-0 opacity-60" strokeWidth={1.5} aria-hidden />
            </div>
          </PopoverTrigger>
          <PopoverContent
            align="start"
            className="w-[200px] p-1"
            data-testid="entity-type-popover"
          >
            {/* "Show all types" reset row — checked (and disabled) when the
                whitelist is empty, since that IS the show-all state. */}
            <button
              type="button"
              onClick={clearTypes}
              disabled={activeCount === 0}
              className={cn(
                "flex w-full items-center gap-2 rounded-[2px] px-2 py-1.5 text-left text-[11px]",
                "hover:bg-muted/60 focus-visible:outline-none focus-visible:bg-muted/60",
                "disabled:cursor-default disabled:opacity-60",
              )}
            >
              {/* The check mark only shows in the "all" state so the row reads
                  as the current selection when no per-type filter is active. */}
              <Check
                className={cn("h-3.5 w-3.5", activeCount === 0 ? "opacity-100 text-primary" : "opacity-0")}
                strokeWidth={2}
                aria-hidden
              />
              <span className="text-muted-foreground">Show all types</span>
            </button>
            <div className="my-1 h-px bg-border/40" />
            {/* One checkbox row per type that EXISTS in the current graph
                response (sorted asc upstream). Toggling adds/removes the type
                from the whitelist; multiple may be active at once. */}
            <div role="group" aria-label="Entity types" className="max-h-[240px] overflow-y-auto">
              {availableEntityTypes.map((type) => {
                const checked = selected.has(type);
                return (
                  <label
                    key={type}
                    className="flex cursor-pointer items-center gap-2 rounded-[2px] px-2 py-1.5 text-[11px] hover:bg-muted/60"
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggleType(type)}
                      // data-testid keyed by raw type so tests can target a
                      // specific checkbox deterministically.
                      data-testid={`entity-type-checkbox-${type}`}
                      aria-label={prettyType(type)}
                    />
                    {/* capitalize via CSS keeps the raw enum value intact for
                        the callback while presenting it nicely. */}
                    <span className="capitalize">{prettyType(type)}</span>
                  </label>
                );
              })}
            </div>
          </PopoverContent>
        </Popover>
      </div>
    </div>
  );
}
