/**
 * components/instrument/IntelligenceTab.tsx — Intelligence tab: entity graph + AI brief + contradictions
 *
 * WHY THIS EXISTS: The Intelligence tab gives analysts a holistic view of an entity's
 * relationship network and conflicting signals in one place. Three sections:
 *
 * 1. Entity Knowledge Graph (sigma.js) — full depth=2 interactive WebGL graph showing
 *    how this entity connects to others: competitors, executives, suppliers, macro events.
 *    Replaces the compact Overview sidebar SVG for deeper exploration.
 *
 * 2. AI Intelligence Brief (placeholder) — will show an AI-generated summary of recent
 *    developments, risk factors, and price-relevant signals (uses getInstrumentBrief S9 endpoint).
 *
 * 3. Detected Contradictions — NLP-extracted conflicting claims across recent articles.
 *    These are HIGH-signal for risk-aware investors and the unique worldview differentiator.
 *
 * WHY CONTRADICTIONS LAST (not first as before): The graph now occupies the primary position
 * because it provides spatial context for understanding which entities are generating
 * the contradictions. A quant sees the graph → understands entity relationships →
 * reads contradictions with full relational context.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Intelligence tab)
 * DATA SOURCES:
 *   - S9 GET /v1/entities/{entityId}/graph?depth=2 (entity graph)
 *   - S9 GET /v1/entities/{entityId}/contradictions (NLP contradictions)
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail State C-4 Intelligence tab
 */

"use client";
// WHY "use client": uses useQuery for async data fetching and useState via dynamic import.

import dynamic from "next/dynamic";
import { EntityGraphErrorBoundary } from "@/components/instrument/EntityGraphErrorBoundary";
import { useQuery } from "@tanstack/react-query";
// WHY CheckCircle removed: empty contradictions state now uses inline text only
import { AlertTriangle, RefreshCw, ChevronRight, ChevronDown, Clock } from "lucide-react";
// WHY MarkdownContent (PLAN-0049 T-D-4-03): the brief block previously rendered
// markdown via an inline ReactMarkdown + remarkGfm config with a long set of
// custom Tailwind selectors. That config drifted from MorningBriefCard's and
// InstrumentAISubheader's — three surfaces, three slightly different stylesheets.
// The shared <MarkdownContent size="comfortable"> centralises typography so the
// dashboard / instrument-header / intelligence-tab brief surfaces are visually
// identical. "comfortable" uses 12px base + slightly looser spacing, suited to
// the full-width Intelligence tab (vs the dense 10px "compact" used elsewhere).
import { MarkdownContent } from "@/components/ui/markdown-content";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime, cn } from "@/lib/utils";
import type { BriefingResponse, Contradiction } from "@/types/api";
import { useState, useMemo } from "react";

// ── EntityGraph dynamic import (ssr:false) ────────────────────────────────────
// WHY next/dynamic with ssr:false: EntityGraph.tsx uses sigma.js which creates a
// WebGL context. SSR (server-side rendering) has no browser/WebGL environment.
// ssr:false tells Next.js to skip SSR for this component and hydrate it client-side.
// WHY loading spinner: gives the user visual feedback while the sigma.js bundle
// (~200KB) loads and the WebGL context initializes.
const EntityGraph = dynamic(
  () => import("@/components/instrument/EntityGraph").then((m) => ({ default: m.EntityGraph })),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[460px] items-center justify-center rounded-[2px] border border-border/40 bg-card/30">
        <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />
      </div>
    ),
  },
);

// ── Props ─────────────────────────────────────────────────────────────────────

interface IntelligenceTabProps {
  entityId: string;
}

// ── Severity helpers ──────────────────────────────────────────────────────────
// WHY hex/class map: Contradiction severity mirrors alert severity visually.
// HIGH = red (destructive), MEDIUM = amber (warning), LOW = muted.
const SEVERITY_STYLES: Record<
  Contradiction["severity"],
  { icon: string; badge: string; text: string }
> = {
  HIGH: {
    icon: "text-negative",
    badge: "bg-destructive/15 text-negative",
    text: "HIGH",
  },
  MEDIUM: {
    icon: "text-warning",
    badge: "bg-warning/15 text-warning",
    text: "MED",
  },
  LOW: {
    icon: "text-muted-foreground",
    badge: "bg-muted text-muted-foreground",
    text: "LOW",
  },
};

// ── ContradictionCard sub-component ───────────────────────────────────────────

/**
 * ContradictionCard — collapsible contradiction row
 *
 * WHY COLLAPSIBLE: Long contradiction lists with full VS layouts consume too much
 * vertical space. The collapsed 22px row lets analysts scan all contradictions
 * quickly; expanding reveals the full claim-A vs claim-B layout.
 *
 * WHY CONTROLLED (isExpanded + onToggle props): The parent IntelligenceTab manages
 * the expanded ID so only one card is expanded at a time (accordion behavior).
 * This prevents the page from growing unboundedly when multiple cards are open.
 */
function ContradictionCard({
  item,
  isExpanded,
  onToggle,
}: {
  item: Contradiction;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const styles = SEVERITY_STYLES[item.severity];

  if (!isExpanded) {
    // ── Collapsed: 22px row with severity badge + truncated claim + time ──
    // WHY <div> wrapper with onClick + inner <button>:
    //   - instrument-detail.test.tsx uses closest("div") to find the row element
    //     (legacy test written when the card was a plain div — R19: do not delete).
    //     closest("div") from the claim text span must resolve to a clickable element.
    //   - instrument-wave-e-plan-0053.test.tsx uses closest("button") to find the
    //     row for a11y/keyboard interaction (T-E-5-04 contract).
    //   Both constraints are satisfied by having a clickable <div> wrapper that also
    //   contains a <button>. closest("div") finds the wrapper; closest("button") finds
    //   the button. onClick on the div covers the pointer click; the button handles
    //   keyboard Enter/Space and is the correct semantic element for a11y.
    return (
      <div
        onClick={onToggle}
        className="flex items-center h-[22px] border-b border-border/30 hover:bg-muted/40 cursor-pointer"
        role="presentation"
      >
        <button
          type="button"
          className="w-full flex items-center h-[22px] px-2 gap-1.5 text-left"
          onClick={(e) => {
            // WHY stopPropagation: the wrapper div also has onClick={onToggle}.
            // Without stopPropagation, clicking the button fires the button's
            // onClick then bubbles to the div and fires the div's onClick —
            // calling onToggle twice and immediately re-collapsing the card.
            // stopPropagation ensures only one onToggle call per click regardless
            // of which element the click originates on.
            e.stopPropagation();
            onToggle();
          }}
          aria-expanded={false}
          aria-label={`Expand contradiction: ${item.claim_a.slice(0, 40)}`}
        >
          {/* Severity badge — compact colored pill */}
          <span className={`rounded-[2px] px-1 py-0 text-[9px] font-semibold uppercase ${styles.badge}`}>
            {styles.text}
          </span>

          {/* First 60 chars of claim_a — enough context to identify the signal */}
          <span className="text-[11px] text-foreground flex-1 truncate">
            {item.claim_a.slice(0, 60)}{item.claim_a.length > 60 ? "…" : ""}
          </span>

          {/* Relative time */}
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
            {formatRelativeTime(item.detected_at)}
          </span>

          {/* Expand chevron */}
          <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" strokeWidth={1.5} />
        </button>
      </div>
    );
  }

  // ── Expanded: full VS layout ────────────────────────────────────────────
  return (
    <div className="rounded-[2px] border border-border/40 bg-card/60 p-3">
      {/* Header: severity badge + collapse button + detected time */}
      <div className="mb-2 flex items-center justify-between">
        <span className={`rounded-[2px] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${styles.badge}`}>
          {styles.text}
        </span>

        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {formatRelativeTime(item.detected_at)}
          </span>
          {/* Collapse button — ChevronDown indicates the card can be collapsed */}
          <button
            onClick={onToggle}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Collapse contradiction"
          >
            <ChevronDown className="h-3 w-3" strokeWidth={1.5} />
          </button>
        </div>
      </div>

      {/* Claim A vs Claim B — full VS layout */}
      {/* WHY "Claim A" / "Claim B" labels: T-E-5-04 test asserts both labels
          are present when the Sheet is open. The labels also improve accessibility
          by clearly identifying each side of the contradiction to screen readers. */}
      <div className="space-y-2">
        {/* WHY VS layout: makes the contradiction visually obvious at a glance */}
        <div className="rounded-[2px] bg-positive/5 p-2">
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Claim A</p>
          <p className="text-[11px] text-foreground/80 leading-relaxed">&ldquo;{item.claim_a}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_a}</p>
        </div>
        <div className="flex items-center justify-center">
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} strokeWidth={1.5} />
          <span className={`mx-1 text-[9px] font-semibold uppercase ${styles.icon}`}>vs</span>
          <AlertTriangle className={`h-3 w-3 ${styles.icon}`} strokeWidth={1.5} />
        </div>
        <div className="rounded-[2px] bg-negative/5 p-2">
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Claim B</p>
          <p className="text-[11px] text-foreground/80 leading-relaxed">&ldquo;{item.claim_b}&rdquo;</p>
          <p className="mt-1 text-[10px] text-muted-foreground">— {item.source_b}</p>
        </div>
      </div>
    </div>
  );
}

// ── InstrumentBriefSection (AI brief sub-component) ──────────────────────────
// WHY separate component: isolates the useQuery hook and its loading/error/stale
// states from the parent IntelligenceTab. This means the graph and contradictions
// sections are not blocked by the brief data fetch — they render independently.

/** Brief older than 12h shows a stale indicator */
const BRIEF_STALE_MS = 12 * 60 * 60 * 1000;

function InstrumentBriefSection({ entityId }: { entityId: string }) {
  const { accessToken } = useAuth();

  // WHY useQuery with staleTime 30min: instrument briefs are generated on-demand
  // by S8 and cached in Valkey for 24h. No need to refetch aggressively.
  // WHY retry 2 + retryDelay 10s: S8 may be generating the brief (503); give it
  // time to complete before showing an error state.
  const {
    data: brief,
    isLoading,
    isError,
    error,
  } = useQuery<BriefingResponse>({
    queryKey: ["instrument-brief", entityId],
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 30 * 60 * 1000,
    retry: 2,
    retryDelay: 10_000,
  });

  // WHY p-3 (was p-4): terminal panel standard padding
  return (
    <section className="p-3">
      <h3 className="mb-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">AI Intelligence Brief</h3>

      {/* ── Loading state: 3-line skeleton ──────────────────────────────────── */}
      {/* WHY 3 lines: instrument briefs are shorter than morning briefs (2-3 paragraphs).
          3 skeleton lines match the expected visual height while loading. */}
      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}

      {/* ── Error / unavailable state ────────────────────────────────────────── */}
      {/* WHY 503 soft error: S8 may still be generating the brief. Showing a
          "generating" message is less alarming than a hard error block. */}
      {isError && !isLoading && (
        <div className="rounded-[2px] border border-border/30 bg-card/30 p-3 text-[11px] text-muted-foreground">
          {error instanceof Error &&
          (error.message.includes("503") || error.message.includes("unavailable"))
            ? "Brief generating... check back in a few minutes."
            : "Intelligence brief unavailable."}
        </div>
      )}

      {/* ── Brief content (rendered as markdown) ─────────────────────────────── */}
      {!isLoading && !isError && brief && (
        <div>
          {/* WHY stale indicator: if the brief is older than 12h, the data may
              no longer reflect current market conditions. Amber text signals
              this to the trader without blocking the view. */}
          {Date.now() - new Date(brief.generated_at).getTime() > BRIEF_STALE_MS && (
            <div className="mb-2 flex items-center gap-1">
              <RefreshCw className="h-3 w-3 text-warning" />
              <span className="text-[11px] text-warning">Brief may be outdated</span>
            </div>
          )}

          {/* WHY MarkdownContent (T-D-4-03): centralised renderer — see imports
              above for the full rationale. The "comfortable" variant gives the
              brief block 12px text and looser spacing appropriate for the
              full-width Intelligence tab. brief.narrative is the canonical
              field name from S8's PublicBriefingResponse schema. */}
          {/* PLAN-0053 T-E-5-04 / I-09: align with dashboard MorningBriefCard
              and InstrumentAISubheader by using ``size="compact"``. The other
              two surfaces are the canonical layout; "comfortable" here was
              the only outlier and produced a visual mismatch. */}
          <MarkdownContent size="compact">{brief.narrative}</MarkdownContent>

          {/* WHY generated_at timestamp: traders need to know how fresh the
              intelligence is — a brief from yesterday may be stale after
              overnight earnings or macro events. */}
          <p className="mt-2 font-mono text-[10px] tabular-nums text-muted-foreground">
            Generated {new Date(brief.generated_at).toISOString().slice(0, 16).replace("T", " ")} UTC
          </p>
        </div>
      )}

      {/* ── Empty state — no brief available yet ─────────────────────────────── */}
      {!isLoading && !isError && !brief && (
        <div className="rounded-[2px] border border-border/30 bg-card/30 p-3 text-[11px] text-muted-foreground">
          No intelligence brief available for this entity yet.
        </div>
      )}
    </section>
  );
}

// ── Intelligence filter types (PLAN-0050 Wave E T-E-5-05) ────────────────────
// WHY a dedicated section: filter state is hoisted in IntelligenceTab and passed
// to EntityGraph as props. Defining the types here makes the interface explicit.

/** Graph exploration depth — how many hops from the center entity to show. */
type DepthValue = 1 | 2 | 3;

/** Time-window filter for relation evidence (how far back to look). */
type TimeWindow = "7d" | "30d" | "90d" | "all";

/** Force-directed layout options. */
type LayoutMode = "force" | "circular" | "hierarchical";

/**
 * IntelligenceFilterState — all filter values for the graph toolbar.
 *
 * WHY all in one object (not 6 separate state calls): grouping allows a single
 * state update to reset all filters at once (Reset button), and makes it easy
 * to serialise/deserialise filter state to URL params in the future.
 */
interface IntelligenceFilterState {
  depth: DepthValue;
  relationTypes: string[];    // empty = show all relation types
  entityTypes: string[];      // empty = show all entity types
  timeWindow: TimeWindow;
  layout: LayoutMode;
  confidenceThreshold: number; // 0.0–1.0; edges below this are hidden
}

const DEFAULT_FILTERS: IntelligenceFilterState = {
  depth: 2,
  relationTypes: [],
  entityTypes: [],
  timeWindow: "all",
  layout: "force",
  confidenceThreshold: 0.0,
};

/** All relation types understood by the knowledge graph. */
const ALL_RELATION_TYPES = [
  "CEO_OF", "COMPETES_WITH", "SUPPLIER_OF", "PARTNER_OF",
  "OWNS", "ACQUIRED_BY", "BOARD_MEMBER_OF", "REPORTED",
] as const;

// WHY no ALL_ENTITY_TYPES constant: entity types are not a fixed enum in the KG.
// Real KG nodes may have types like "organization", "financial_instrument", "macro_event",
// etc. — types that a hardcoded list would miss. Dynamic types are derived from the
// live graph data in IntelligenceTab via useMemo and passed as a prop.

/** Stale threshold: graph data older than 24h shows a warning banner (F-I-030). */
const GRAPH_STALE_MS = 24 * 60 * 60 * 1000;

// ── IntelligenceFilters toolbar ───────────────────────────────────────────────

/**
 * IntelligenceFilters — filter toolbar above the entity graph.
 *
 * PLAN-0050 Wave E T-E-5-05:
 *   - Depth slider 1-3: controls how many hops from center to show
 *   - Relation-type multi-select chips: filter by relationship category
 *   - Entity-type filter chips: filter by node type
 *   - Time-window filter: 7d / 30d / 90d / all
 *   - Layout selector: force / circular / hierarchical
 *   - Confidence threshold slider: hide low-confidence edges
 *
 * WHY COMPACT CHIP STYLE (not full-width dropdown): The filter bar sits above a
 * 460px graph. A full-width dropdown row would consume too much vertical space.
 * Chips are scannable and can be toggled without opening a menu.
 *
 * WHY all controls collapse below a single scrollable row: the Intelligence tab
 * is typically opened by power users who want to explore the full graph. The
 * filter bar should be immediately usable without scrolling.
 */
function IntelligenceFilters({
  filters,
  onFiltersChange,
  // WHY availableEntityTypes prop (not constant): entity types are derived from
  // live graph data (see useMemo in IntelligenceTab). The filter chips only show
  // types that actually exist in the current graph — no phantom chips for types
  // with zero matching nodes. Passed from parent after graphData resolves.
  availableEntityTypes,
}: {
  filters: IntelligenceFilterState;
  onFiltersChange: (f: IntelligenceFilterState) => void;
  availableEntityTypes: string[];
}) {
  /** Helper: toggle a value in a string array filter field. */
  function toggleArrayFilter(
    field: "relationTypes" | "entityTypes",
    value: string,
  ) {
    const current = filters[field];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onFiltersChange({ ...filters, [field]: next });
  }

  return (
    <div
      className="border-b border-border/40 bg-card/30 px-3 py-2 space-y-2"
      aria-label="Graph filter controls"
    >
      {/* ── Row 1: depth slider + layout + time window ─────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">

        {/* Depth slider 1–3 */}
        {/* WHY range input (not Select): a slider makes the 1-2-3 relationship
            intuitive — dragging from 1 to 3 feels like "expanding" the graph.
            A dropdown for 3 options is heavier UX than a simple slider. */}
        <div className="flex items-center gap-1.5">
          <label
            htmlFor="graph-depth"
            className="text-[10px] text-muted-foreground uppercase tracking-[0.06em] shrink-0"
          >
            Depth
          </label>
          <input
            id="graph-depth"
            type="range"
            min={1}
            max={3}
            step={1}
            value={filters.depth}
            onChange={(e) =>
              onFiltersChange({ ...filters, depth: Number(e.target.value) as DepthValue })
            }
            className="h-1 w-16 accent-primary cursor-pointer"
            aria-label={`Graph depth: ${filters.depth}`}
          />
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground w-3">
            {filters.depth}
          </span>
        </div>

        {/* Layout selector — force / circular / hierarchical */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground uppercase tracking-[0.06em] shrink-0">
            Layout
          </span>
          {(["force", "circular", "hierarchical"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => onFiltersChange({ ...filters, layout: mode })}
              className={cn(
                "rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono capitalize transition-colors",
                filters.layout === mode
                  ? "bg-primary/20 text-primary"
                  : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
              aria-pressed={filters.layout === mode}
            >
              {mode}
            </button>
          ))}
        </div>

        {/* Time-window filter */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground uppercase tracking-[0.06em] shrink-0">
            Window
          </span>
          {(["7d", "30d", "90d", "all"] as const).map((w) => (
            <button
              key={w}
              onClick={() => onFiltersChange({ ...filters, timeWindow: w })}
              className={cn(
                "rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono transition-colors",
                filters.timeWindow === w
                  ? "bg-primary/20 text-primary"
                  : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
              aria-pressed={filters.timeWindow === w}
            >
              {w}
            </button>
          ))}
        </div>

        {/* Reset button — appears only when filters differ from defaults */}
        {(filters.depth !== DEFAULT_FILTERS.depth ||
          filters.relationTypes.length > 0 ||
          filters.entityTypes.length > 0 ||
          filters.timeWindow !== DEFAULT_FILTERS.timeWindow ||
          filters.layout !== DEFAULT_FILTERS.layout ||
          filters.confidenceThreshold !== DEFAULT_FILTERS.confidenceThreshold) && (
          <button
            onClick={() => onFiltersChange(DEFAULT_FILTERS)}
            className="ml-auto text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Reset all graph filters"
          >
            Reset
          </button>
        )}
      </div>

      {/* ── Row 2: confidence threshold + relation-type chips ─────────────── */}
      <div className="flex flex-wrap items-center gap-2">

        {/* Confidence threshold slider */}
        <div className="flex items-center gap-1.5 shrink-0">
          <label
            htmlFor="graph-confidence"
            className="text-[10px] text-muted-foreground uppercase tracking-[0.06em]"
          >
            Confidence
          </label>
          <input
            id="graph-confidence"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={filters.confidenceThreshold}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                confidenceThreshold: parseFloat(e.target.value),
              })
            }
            className="h-1 w-20 accent-primary cursor-pointer"
            aria-label={`Confidence threshold: ${(filters.confidenceThreshold * 100).toFixed(0)}%`}
          />
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground w-6">
            {/* WHY integer percentage: 0.50 → "50" is more readable than "0.5" in a compact chip */}
            {(filters.confidenceThreshold * 100).toFixed(0)}%
          </span>
        </div>

        {/* Entity-type filter chips — rendered from live graph data (see availableEntityTypes prop).
            WHY loading placeholder: while graphData is fetching, availableEntityTypes is [].
            Showing a subtle "loading types…" span prevents layout shift when chips appear. */}
        <div className="flex items-center gap-1">
          {availableEntityTypes.length === 0 ? (
            <span className="text-[9px] text-muted-foreground/50 font-mono italic">
              loading types…
            </span>
          ) : (
            availableEntityTypes.map((type) => (
              <button
                key={type}
                onClick={() => toggleArrayFilter("entityTypes", type)}
                className={cn(
                  "rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono capitalize transition-colors",
                  filters.entityTypes.includes(type)
                    ? "bg-primary/20 text-primary"
                    : "bg-muted text-muted-foreground hover:bg-muted/70",
                )}
                aria-pressed={filters.entityTypes.includes(type)}
              >
                {/* WHY replace /_/g: KG node types like "financial_instrument" render
                    better as "financial instrument" — underscores are internal conventions. */}
                {type.replace(/_/g, " ")}
              </button>
            ))
          )}
        </div>

        {/* Relation-type multi-select chips — collapsed to avoid overwhelming the toolbar */}
        {/* WHY scrollable wrapper: ALL_RELATION_TYPES has 8 items; wrapping into 2 rows
            would push the graph down. Horizontal scroll keeps the row height fixed. */}
        <div className="flex items-center gap-1 overflow-x-auto max-w-[220px]">
          {(ALL_RELATION_TYPES as readonly string[]).map((rel) => (
            <button
              key={rel}
              onClick={() => toggleArrayFilter("relationTypes", rel)}
              className={cn(
                "shrink-0 rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono transition-colors",
                filters.relationTypes.includes(rel)
                  ? "bg-positive/20 text-positive"
                  : "bg-muted text-muted-foreground hover:bg-muted/70",
              )}
              aria-pressed={filters.relationTypes.includes(rel)}
              title={rel.replace(/_/g, " ")} // WHY title: full label on hover for abbreviated chips
            >
              {/* Show first 3 letters of each relation type token for compact display */}
              {rel.split("_").map((w) => w.slice(0, 3)).join("·")}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IntelligenceTab({ entityId }: IntelligenceTabProps) {
  const { accessToken } = useAuth();

  // ── Severity filter state ────────────────────────────────────────────────────
  // WHY null default: no filter = show all severities. Clicking a severity button
  // filters to only that severity; clicking again clears the filter.
  const [severityFilter, setSeverityFilter] = useState<"HIGH" | "MEDIUM" | "LOW" | null>(null);

  // ── Intelligence graph filter state (PLAN-0050 Wave E T-E-5-05) ─────────────
  // WHY hoisted here (not inside IntelligenceFilters): EntityGraph needs to know
  // the active filters to apply them to the graph data. The toolbar and graph are
  // siblings so state must live in the common parent — this component.
  const [graphFilters, setGraphFilters] = useState<IntelligenceFilterState>(DEFAULT_FILTERS);

  // ── Expanded contradiction row state ─────────────────────────────────────────
  // WHY string|null (not boolean): each contradiction has a unique ID; only one
  // can be expanded at a time (accordion). null = all collapsed.
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // ── Entity graph query ──────────────────────────────────────────────────────
  // WHY separate query (not shared with EntityGraphPanel): the Intelligence tab uses
  // configurable depth (1-3 via filter slider) while the Overview sidebar always uses
  // depth=1. Different query keys ensure they are cached separately by TanStack Query.
  // WHY graphFilters.depth in query key: changing depth = new S9 request (different data).
  // WHY graphFilters.timeWindow in query key: changing the time window sends a different
  // ?time_window= param to S9 — the response graph is different, so it must be cached
  // separately. Without this, switching from "7d" to "all" would return cached 7d data.
  const {
    data: graphData,
    dataUpdatedAt: graphUpdatedAt,
  } = useQuery({
    queryKey: ["entity-graph", entityId, graphFilters.depth, graphFilters.timeWindow],
    queryFn: () => createGateway(accessToken).getEntityGraph(entityId, graphFilters.depth, graphFilters.timeWindow),
    enabled: !!accessToken && !!entityId,
    // WHY 10min: knowledge graph edges don't change frequently
    staleTime: 10 * 60_000,
  });

  // ── Dynamic entity types (derived from graph data) ─────────────────────────
  // WHY useMemo: the set of entity types present in the graph is derived from the
  // graph nodes. We compute it once when graphData changes and pass it to
  // IntelligenceFilters as a prop. This avoids repeating the derivation in the
  // filter component and avoids re-renders when graphFilters changes (different memo).
  // WHY sort(): stable alphabetical order prevents chip order flickering across fetches.
  const availableEntityTypes = useMemo<string[]>(() => {
    if (!graphData?.nodes?.length) return [];
    const typeSet = new Set<string>();
    for (const node of graphData.nodes) {
      if (node.type) typeSet.add(node.type);
    }
    return Array.from(typeSet).sort();
  }, [graphData]);

  // ── Contradictions query ────────────────────────────────────────────────────
  const { data: resp, isLoading, isError } = useQuery({
    queryKey: ["contradictions", entityId],
    queryFn: () => createGateway(accessToken).getContradictions(entityId),
    enabled: !!accessToken && !!entityId,
    // WHY 10min: contradiction detection runs hourly on the backend
    staleTime: 10 * 60_000,
  });

  // ── Client-side graph data filtering (T-E-5-05) ────────────────────────────
  // WHY client-side filter (not new S9 param): the graph is fetched by depth;
  // filtering by relation_type / entity_type / confidence is presentation-only.
  // Sending them as API params would require S9 changes; client filtering is
  // simpler and adequate for ≤100 nodes.
  //
  // WHY timeWindow is NOT applied client-side here: filtering edges by time window
  // requires each GraphEdge to carry a `last_seen` or `created_at` timestamp. The
  // current GraphEdge type (types/api.ts) only has `source`, `target`, `label`,
  // and `weight` fields — no temporal field. Until S9/S7 exposes last_seen on edges,
  // time-window filtering is handled server-side via the ?time_window= query param
  // (which is part of the queryKey and triggers a fresh fetch on change).
  const filteredGraphData = useMemo(() => {
    if (!graphData) return graphData;
    const { relationTypes, entityTypes, confidenceThreshold } = graphFilters;

    // Filter edges by confidence threshold and active relation-type chips
    const filteredEdges = graphData.edges.filter((edge) => {
      if (edge.weight < confidenceThreshold) return false;
      if (relationTypes.length > 0 && !relationTypes.includes(edge.label)) return false;
      return true;
    });

    // Collect node IDs still reachable after edge filtering
    const reachableIds = new Set<string>([graphData.entity_id]);
    for (const e of filteredEdges) {
      reachableIds.add(e.source);
      reachableIds.add(e.target);
    }

    // Filter nodes by entity type and reachability
    const filteredNodes = graphData.nodes.filter(
      (node) =>
        reachableIds.has(node.id) &&
        (entityTypes.length === 0 || entityTypes.includes(node.type)),
    );

    return { ...graphData, nodes: filteredNodes, edges: filteredEdges };
  }, [graphData, graphFilters]);

  // ── Stale-graph indicator (T-E-5-06, F-I-030) ──────────────────────────────
  // WHY graphUpdatedAt (TanStack internal timestamp): dataUpdatedAt is the JS
  // Date.now() value at which the last successful fetch resolved. We compare it
  // to GRAPH_STALE_MS (24h) to decide whether to show the staleness banner.
  // WHY NOT graphData.fetched_at (server-side): S9 doesn't include a fetch_timestamp
  // on entity graph responses. The client's fetch time is a good proxy — if the user
  // has had the page open for 24h without reloading, the graph is effectively stale.
  const isGraphStale = graphUpdatedAt > 0 && Date.now() - graphUpdatedAt > GRAPH_STALE_MS;
  const graphAgeHours = graphUpdatedAt > 0
    ? Math.floor((Date.now() - graphUpdatedAt) / (60 * 60 * 1000))
    : 0;

  // ── Contradictions data ─────────────────────────────────────────────────────
  const contradictions = resp?.contradictions ?? [];

  // ── Sort contradictions: HIGH first, then MEDIUM, then LOW ─────────────────
  const SEVERITY_ORDER: Record<Contradiction["severity"], number> = {
    HIGH: 0, MEDIUM: 1, LOW: 2,
  };

  const sorted = [...contradictions].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );

  // ── Apply severity filter ───────────────────────────────────────────────────
  // WHY filter on sorted (not raw): maintains the HIGH→MEDIUM→LOW order even after filtering
  const filtered = sorted.filter((c) => !severityFilter || c.severity === severityFilter);

  return (
    <div className="flex flex-col divide-y divide-border/40">

      {/* ── Entity Knowledge Graph ─────────────────────────────────────────── */}
      {/* WHY p-3 (was p-4): terminal panel standard padding */}
      <section className="p-3">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Entity Knowledge Graph</h3>
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            depth {graphFilters.depth} · {filteredGraphData?.nodes?.length ?? 0} entities
          </span>
        </div>

        {/* ── Intelligence filter toolbar (T-E-5-05) ──────────────────────── */}
        {/* WHY above the graph (not below): filters change what the graph shows;
            placing them above follows the standard UI pattern of "controls → output". */}
        <div className="mb-2">
          <IntelligenceFilters
            filters={graphFilters}
            onFiltersChange={setGraphFilters}
            availableEntityTypes={availableEntityTypes}
          />
        </div>

        {/* ── Stale-graph indicator (T-E-5-06, F-I-030) ─────────────────── */}
        {/* WHY only when isGraphStale: a banner on every page load would be noisy.
            24h is the threshold because knowledge-graph edges are typically updated
            daily by the S7 extraction pipeline. */}
        {isGraphStale && (
          <div className="mb-2 flex items-center gap-2 rounded-[2px] border border-warning/30 bg-warning/5 px-3 py-1.5">
            <Clock className="h-3 w-3 shrink-0 text-warning" aria-hidden="true" strokeWidth={1.5} />
            <span className="text-[11px] text-warning">
              Graph last updated {graphAgeHours}h ago — newer relations may not be reflected.
            </span>
          </div>
        )}

        {/* WHY conditional render: show spinner while graphData is loading,
            then render the sigma.js graph once data arrives.
            The EntityGraph component itself also handles the empty state.
            PLAN-0050 T-F-6-19: wrap the WebGL-rendering EntityGraph in an
            error boundary so a sigma.js crash (e.g. headless browser with
            no WebGL, or graphology rejecting malformed data) does not tear
            down the whole Intelligence tab. */}
        {filteredGraphData ? (
          <>
            {/* WHY empty-state check (not relying on EntityGraph to show it):
                filteredGraphData may have 0 nodes after the user applies aggressive filters
                (e.g., entity-type = "person" but the graph has no person nodes). EntityGraph
                with 0 nodes renders a blank WebGL canvas with no visual feedback. We
                intercept here and show an actionable message instead. */}
            {filteredGraphData.nodes.length === 0 ? (
              <div className="flex h-[460px] items-center justify-center rounded-[2px] border border-border/40 bg-card/30">
                <p className="text-[11px] text-muted-foreground">
                  No nodes match the current filters.{" "}
                  <button
                    onClick={() => setGraphFilters(DEFAULT_FILTERS)}
                    className="text-primary underline underline-offset-2 hover:no-underline"
                  >
                    Reset filters
                  </button>
                </p>
              </div>
            ) : (
              <EntityGraphErrorBoundary>
                <EntityGraph data={filteredGraphData} centerEntityId={entityId} />
              </EntityGraphErrorBoundary>
            )}
          </>
        ) : (
          <div className="flex h-[460px] items-center justify-center rounded-[2px] border border-border/40 bg-card/30">
            <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />
          </div>
        )}
      </section>

      {/* ── AI Intelligence Brief (live) ─────────────────────────────────── */}
      {/* WHY live: PLAN-0034 integrated the S8 briefing pipeline. This section
          now fetches a real AI-generated brief from S8 via the S9 gateway.
          It shows loading skeletons, 503 soft errors, and stale indicators. */}
      <InstrumentBriefSection entityId={entityId} />

      {/* ── Detected Contradictions ────────────────────────────────────────── */}
      {/* WHY p-3 (was p-4): terminal panel standard padding */}
      <section className="p-3">

        {/* Loading state */}
        {isLoading && (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="space-y-2 rounded-[2px] border border-border/40 p-3">
                <div className="flex justify-between">
                  <Skeleton className="h-4 w-12" />
                  <Skeleton className="h-4 w-16" />
                </div>
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ))}
          </div>
        )}

        {/* Error state */}
        {isError && !isLoading && (
          <p className="text-[11px] text-muted-foreground">
            Could not load intelligence data. Try again shortly.
          </p>
        )}

        {/* Empty state — no contradictions found */}
        {/* WHY inline (was flex-col items-center py-8): terminal empty states are
            compact inline text. A full-height centered panel with a large icon is
            consumer SaaS style; a single compact line is terminal style. */}
        {!isLoading && !isError && contradictions.length === 0 && (
          <p className="py-2 text-[11px] text-positive">
            No contradictions detected — signals are consistent.
          </p>
        )}

        {/* Contradiction list */}
        {!isLoading && !isError && contradictions.length > 0 && (
          <div className="space-y-3">
            {/* Count badge at top */}
            <div className="flex items-center justify-between">
              <h3 className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                Detected Contradictions
              </h3>
              <span className="rounded-[2px] bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                {contradictions.length} found
              </span>
            </div>

            {/* ── Temporal histogram — weekly buckets from detected_at ─────
                WHY 8 weeks: contradiction signals build over time. Showing 8 weeks
                gives enough history to spot "signal spikes" before earnings or events.
                WHY 30px height: tall enough to show bar height differences without
                consuming significant vertical space. */}
            {(() => {
              const now = Date.now();
              const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
              const buckets = Array.from({ length: 8 }, (_, i) => ({
                weekAgo: i,
                count: contradictions.filter((c) => {
                  const age = now - new Date(c.detected_at).getTime();
                  return age >= i * WEEK_MS && age < (i + 1) * WEEK_MS;
                }).length,
              })).reverse();
              const maxCount = Math.max(1, ...buckets.map((b) => b.count));
              return (
                <div className="flex items-end gap-px h-[30px] mb-2">
                  {buckets.map((b, i) => (
                    <div
                      key={i}
                      className="flex-1 flex items-end justify-center"
                      title={`${b.count} signals ${b.weekAgo === 0 ? "this week" : `${b.weekAgo}w ago`}`}
                    >
                      <div
                        className="w-full bg-primary/30 hover:bg-primary/60 cursor-pointer transition-colors"
                        style={{ height: `${Math.max(2, (b.count / maxCount) * 28)}px` }}
                      />
                    </div>
                  ))}
                </div>
              );
            })()}

            {/* ── Severity count strip — filter buttons ────────────────────
                WHY always visible: lets analysts quickly assess the severity
                distribution before reading individual contradictions. */}
            <div className="flex items-center gap-4 h-[22px] px-0 mb-1">
              {(["HIGH", "MEDIUM", "LOW"] as const).map((sev) => {
                const count = contradictions.filter((c) => c.severity === sev).length;
                return (
                  <button
                    key={sev}
                    onClick={() => setSeverityFilter((f) => (f === sev ? null : sev))}
                    className={cn(
                      "font-mono text-[10px] tabular-nums",
                      sev === "HIGH"
                        ? severityFilter === "HIGH"
                          ? "text-negative font-medium"
                          : "text-negative/60"
                        : sev === "MEDIUM"
                        ? severityFilter === "MEDIUM"
                          ? "text-warning font-medium"
                          : "text-warning/60"
                        : severityFilter === "LOW"
                        ? "text-muted-foreground font-medium"
                        : "text-muted-foreground/60",
                    )}
                  >
                    {sev} {count}
                  </button>
                );
              })}
              {/* Clear filter button — only visible when a filter is active */}
              {severityFilter && (
                <button
                  onClick={() => setSeverityFilter(null)}
                  className="text-[10px] text-muted-foreground hover:text-foreground ml-auto"
                >
                  Clear filter
                </button>
              )}
            </div>

            {/* Contradiction rows (collapsible accordion) */}
            {filtered.map((item) => (
              <ContradictionCard
                key={item.contradiction_id}
                item={item}
                isExpanded={expandedId === item.contradiction_id}
                onToggle={() =>
                  setExpandedId((id) =>
                    id === item.contradiction_id ? null : item.contradiction_id,
                  )
                }
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
