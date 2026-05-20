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
 * WHY a multi-select dropdown for entity types (not pills): the canonical
 * type list has 13+ values (company, person, currency, regulator, location,
 * sector, event, …).  Pills would wrap to two rows on narrow viewports and
 * eat vertical space the analyst needs for the graph itself.  The dropdown
 * keeps the toolbar to a single 28px row regardless of how many types exist.
 *
 * STATE OWNERSHIP: the parent component holds the canonical filter state
 * (depth: number, entityTypes: string[]).  This toolbar receives the state
 * + callbacks and is fully controlled — no internal useState.  That makes it
 * trivial to unit-test (render with props, click, assert callback fired).
 */

"use client";

import * as React from "react";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";

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

// ── Constants ────────────────────────────────────────────────────────────────
// WHY this list is hardcoded (not derived from props): "All types" is a UI
// sentinel — it must be present even when availableEntityTypes is empty so the
// dropdown always shows a meaningful default.
const ALL_TYPES_SENTINEL = "__all__";

export function GraphToolbar({
  depth,
  onDepthChange,
  selectedEntityTypes,
  onEntityTypesChange,
  availableEntityTypes,
}: GraphToolbarProps) {
  // WHY map sentinel ↔ array: the Select primitive is single-value; we encode
  // "all" as a sentinel and any other value as a single-type whitelist.  Multi-
  // select inside a Radix Select is non-trivial; a single-pick + "all" sentinel
  // covers >95% of analyst workflows (focus on one type at a time).
  const currentValue =
    selectedEntityTypes.length === 0 ? ALL_TYPES_SENTINEL : selectedEntityTypes[0];

  const handleTypeChange = (value: string) => {
    if (value === ALL_TYPES_SENTINEL) {
      onEntityTypesChange([]);
    } else {
      onEntityTypesChange([value]);
    }
  };

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

      {/* ── Entity-type filter dropdown ───────────────────────────────────── */}
      {/* WHY disabled when availableEntityTypes is empty: rendering an empty
          dropdown would let the analyst click into a popup with no items —
          confusing.  Disabled state communicates "waiting for data". */}
      <div className="flex items-center gap-2" data-testid="entity-type-container">
        <span className="whitespace-nowrap text-[10px] uppercase tracking-wide text-muted-foreground">
          Type
        </span>
        <Select
          value={currentValue}
          onValueChange={handleTypeChange}
          disabled={availableEntityTypes.length === 0}
        >
          <SelectTrigger
            data-testid="entity-type-select"
            className="h-7 w-[140px] rounded-[2px] border-border/40 bg-card text-[11px]"
          >
            <SelectValue placeholder="All types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TYPES_SENTINEL} className="text-[11px]">
              All types
            </SelectItem>
            {availableEntityTypes.map((type) => (
              // WHY capitalize via CSS (not toUpperCase): keeps the raw enum
              // value intact for the callback while presenting it nicely.
              <SelectItem key={type} value={type} className="capitalize text-[11px]">
                {type.replace(/_/g, " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
