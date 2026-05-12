/**
 * components/instrument/intelligence/IntelligenceFilters.tsx
 *
 * WHY THIS EXISTS:
 * Extracted from IntelligenceTab.tsx (was lines 871-1036) so the tab orchestrator
 * stays under 400 lines while each concern lives in a focused file.
 *
 * This component renders the filter toolbar that sits above the sigma.js entity
 * knowledge graph. It controls:
 *
 *   - Relations (depth): 1–3 hops from the center entity.
 *   - Layout: force / circular / hierarchical (forwarded to EntityGraph).
 *   - Time Window: 7d / 30d / 90d / all (appended to the /graph query).
 *   - Confidence threshold: slider 0–100% — edges below threshold are hidden.
 *   - Entity types: chips derived from nodes present in the live graph.
 *   - Relation types: chips for the 8 most common RELN_TYPE values.
 *
 * WHY ALL TYPES ARE CHIP FILTERS (not a multi-select dropdown): Bloomberg-style
 * terminal UIs keep filters as scannable inline chips so analysts can toggle
 * multiple filters without opening a menu. The 22px row height constraint
 * matches the rest of the tab's dense layout.
 *
 * WHO USES IT: components/instrument/IntelligenceTab.tsx
 */

"use client";

import { cn } from "@/lib/utils";

// ── Filter types (re-exported so IntelligenceTab can import from one place) ───

export type DepthValue = 1 | 2 | 3;
export type TimeWindow = "7d" | "30d" | "90d" | "all";
export type LayoutMode = "force" | "circular" | "hierarchical";

export interface IntelligenceFilterState {
  depth: DepthValue;
  relationTypes: string[];
  entityTypes: string[];
  timeWindow: TimeWindow;
  layout: LayoutMode;
  confidenceThreshold: number;
}

export const DEFAULT_FILTERS: IntelligenceFilterState = {
  depth: 2,
  relationTypes: [],
  entityTypes: [],
  timeWindow: "all",
  layout: "force",
  confidenceThreshold: 0.0,
};

// WHY const array (not enum): these are the 8 most frequent relation types in
// the knowledge graph. New types appear in the graph automatically; this list
// only surfaces the most actionable ones as shortcut chips.
export const ALL_RELATION_TYPES = [
  "CEO_OF", "COMPETES_WITH", "SUPPLIER_OF", "PARTNER_OF",
  "OWNS", "ACQUIRED_BY", "BOARD_MEMBER_OF", "REPORTED",
] as const;

// ── Props ─────────────────────────────────────────────────────────────────────

interface IntelligenceFiltersProps {
  filters: IntelligenceFilterState;
  onFiltersChange: (f: IntelligenceFilterState) => void;
  // WHY derived here (not hard-coded): entity types come from whatever nodes
  // the API returns for the current depth/window combination. Chips are
  // regenerated on each re-render so they always reflect live graph data.
  availableEntityTypes: string[];
}

// ── IntelligenceFilters ───────────────────────────────────────────────────────

export function IntelligenceFilters({ filters, onFiltersChange, availableEntityTypes }: IntelligenceFiltersProps) {
  function toggleArrayFilter(field: "relationTypes" | "entityTypes", value: string) {
    const current = filters[field];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onFiltersChange({ ...filters, [field]: next });
  }

  const isDirty =
    filters.depth !== DEFAULT_FILTERS.depth ||
    filters.relationTypes.length > 0 ||
    filters.entityTypes.length > 0 ||
    filters.timeWindow !== DEFAULT_FILTERS.timeWindow ||
    filters.layout !== DEFAULT_FILTERS.layout ||
    filters.confidenceThreshold !== DEFAULT_FILTERS.confidenceThreshold;

  return (
    <div className="border-b border-border/40 bg-card/30 px-3 py-2 space-y-2" aria-label="Graph filter controls">
      {/* Row 1: depth slider + layout + time window + reset */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5">
          <label htmlFor="graph-depth" className="text-[10px] text-muted-foreground uppercase tracking-[0.06em] shrink-0">
            Relations
          </label>
          <input
            id="graph-depth"
            type="range"
            min={1} max={3} step={1}
            value={filters.depth}
            onChange={(e) => onFiltersChange({ ...filters, depth: Number(e.target.value) as DepthValue })}
            className="h-1 w-16 accent-primary cursor-pointer"
            aria-label={`Graph depth: ${filters.depth}`}
          />
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground w-3">{filters.depth}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground uppercase tracking-[0.06em] shrink-0">Layout</span>
          {(["force", "circular", "hierarchical"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => onFiltersChange({ ...filters, layout: mode })}
              className={cn(
                "rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono capitalize transition-colors",
                filters.layout === mode ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
              aria-pressed={filters.layout === mode}
            >{mode}</button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground uppercase tracking-[0.06em] shrink-0">Window</span>
          {(["7d", "30d", "90d", "all"] as const).map((w) => (
            <button
              key={w}
              onClick={() => onFiltersChange({ ...filters, timeWindow: w })}
              className={cn(
                "rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono transition-colors",
                filters.timeWindow === w ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
              aria-pressed={filters.timeWindow === w}
            >{w}</button>
          ))}
        </div>
        {isDirty && (
          <button
            onClick={() => onFiltersChange(DEFAULT_FILTERS)}
            className="ml-auto text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Reset all graph filters"
          >Reset</button>
        )}
      </div>

      {/* Row 2: confidence threshold + entity type chips + relation type chips */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5 shrink-0">
          <label htmlFor="graph-confidence" className="text-[10px] text-muted-foreground uppercase tracking-[0.06em]">
            Confidence
          </label>
          <input
            id="graph-confidence"
            type="range"
            min={0} max={1} step={0.05}
            value={filters.confidenceThreshold}
            onChange={(e) => onFiltersChange({ ...filters, confidenceThreshold: parseFloat(e.target.value) })}
            className="h-1 w-20 accent-primary cursor-pointer"
            aria-label={`Confidence threshold: ${(filters.confidenceThreshold * 100).toFixed(0)}%`}
          />
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground w-6">
            {(filters.confidenceThreshold * 100).toFixed(0)}%
          </span>
        </div>
        <div className="flex items-center gap-1">
          {availableEntityTypes.length === 0 ? (
            <span className="text-[9px] text-muted-foreground/50 font-mono italic">loading types…</span>
          ) : (
            availableEntityTypes.map((type) => (
              <button
                key={type}
                onClick={() => toggleArrayFilter("entityTypes", type)}
                className={cn(
                  "rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono capitalize transition-colors",
                  filters.entityTypes.includes(type) ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground hover:bg-muted/70",
                )}
                aria-pressed={filters.entityTypes.includes(type)}
              >{type.replace(/_/g, " ")}</button>
            ))
          )}
        </div>
        <div className="flex items-center gap-1 overflow-x-auto max-w-[220px]">
          {(ALL_RELATION_TYPES as readonly string[]).map((rel) => (
            <button
              key={rel}
              onClick={() => toggleArrayFilter("relationTypes", rel)}
              className={cn(
                "shrink-0 rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono transition-colors",
                filters.relationTypes.includes(rel) ? "bg-positive/20 text-positive" : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
              aria-pressed={filters.relationTypes.includes(rel)}
              title={rel.replace(/_/g, " ")}
            >{rel.split("_").map((w) => w.slice(0, 3)).join("·")}</button>
          ))}
        </div>
      </div>
    </div>
  );
}
