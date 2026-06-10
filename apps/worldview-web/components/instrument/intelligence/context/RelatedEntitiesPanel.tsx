/**
 * components/instrument/intelligence/context/RelatedEntitiesPanel.tsx
 * Related entities chip panel (Round-2 Enhancement, item 3).
 *
 * WHY THIS EXISTS: the Intelligence tab's graph canvas shows connected
 * entities VISUALLY, but there was no clickable, scannable list of "who is
 * connected to this company" — analysts had to pan/zoom the WebGL canvas to
 * discover relations. This panel renders the graph's neighbour nodes as
 * grouped chips: companies first (the actionable group — they navigate to
 * their own instrument page), then people, then everything else.
 *
 * DATA SOURCE — ZERO new fetches: the depth=2 EntityGraph already lives in the
 * qk.instruments.entityGraph(entityId, 2) cache slot (fetched by GraphColumn /
 * pre-warmed by the intelligence bundle hydrator). ContextPanel passively
 * subscribes to that slot and passes `nodes` down as a prop — this component
 * is purely derived (same zero-network contract as TopRelationsBlock).
 *
 * NAVIGATION RULES:
 *   - company-ish node WITH a ticker → router.push(/instruments/{ticker}).
 *     The S9 graph proxy includes `ticker` on financial_instrument nodes
 *     precisely so the FE can bridge KG entity_id → instrument page without a
 *     second lookup (see GraphNode.ticker docstring in types/api.ts).
 *   - any node WITHOUT a ticker (people, sectors, topics, ticker-less
 *     companies) → onNodeSelect(node.id): the right rail flips to
 *     NodeDetailCard — the same affordance as clicking the node on the canvas.
 *     There is no standalone entity page in the app, so in-panel detail is the
 *     sensible fallback (never a dead link).
 *
 * CHIP CAP: 12 visible (ordered by node.size — S7's importance score — so the
 * strongest connections always make the cut), with a "+N more" expander.
 * 12 ≈ three chip rows in the 3/14-column rail; beyond that the panel would
 * push the contradictions block below the fold.
 *
 * WHO USES IT: ContextPanel (entity-overview mode, after the description).
 */

"use client";
// WHY "use client": router navigation + expand/collapse local state.

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Share2 } from "lucide-react";

import { EmptyState } from "@/components/instrument/shared/EmptyState";
import { entityTypeToken } from "@/lib/entity-types";
import type { GraphNode } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface RelatedEntitiesPanelProps {
  /** Root entity of the page — excluded from the chip list (it IS the page). */
  readonly entityId: string;
  /** Nodes from the depth=2 graph cache (undefined while the cache is cold). */
  readonly nodes: GraphNode[] | undefined;
  /** Select a node in the context rail (mirrors a graph-canvas node click). */
  readonly onNodeSelect: (nodeId: string) => void;
}

// ── Constants ────────────────────────────────────────────────────────────────

/** Visible chips before the "+N more" expander kicks in (see header WHY). */
const MAX_VISIBLE_CHIPS = 12;

/**
 * Entity types treated as "companies" for grouping + ticker navigation.
 * "company" is the legacy KG alias still present in older graph payloads;
 * financial_institution covers banks/asset managers which also carry tickers.
 */
const COMPANY_TYPES = new Set(["financial_instrument", "company", "financial_institution"]);

// ── Grouping helper ──────────────────────────────────────────────────────────

interface ChipGroups {
  companies: GraphNode[];
  people: GraphNode[];
  other: GraphNode[];
}

/**
 * groupNodes — split neighbour nodes into the 3 display groups, each sorted
 * by descending `size` (S7 importance) so truncation keeps the strongest
 * connections. Ties broken alphabetically for a stable render across
 * refetches (prevents chips reshuffling under the cursor).
 */
function groupNodes(nodes: GraphNode[], rootId: string): ChipGroups {
  const bySizeThenLabel = (a: GraphNode, b: GraphNode) => {
    const sizeDiff = (b.size ?? 0) - (a.size ?? 0);
    if (sizeDiff !== 0) return sizeDiff;
    return a.label.localeCompare(b.label);
  };
  const neighbours = nodes.filter((n) => n.id !== rootId);
  return {
    companies: neighbours.filter((n) => COMPANY_TYPES.has(n.type)).sort(bySizeThenLabel),
    people: neighbours.filter((n) => n.type === "person").sort(bySizeThenLabel),
    other: neighbours
      .filter((n) => !COMPANY_TYPES.has(n.type) && n.type !== "person")
      .sort(bySizeThenLabel),
  };
}

// ── Chip sub-component ───────────────────────────────────────────────────────

function EntityChip({
  node,
  onActivate,
  navigable,
}: {
  node: GraphNode;
  onActivate: () => void;
  navigable: boolean;
}) {
  const token = entityTypeToken(node.type);
  return (
    <button
      type="button"
      onClick={onActivate}
      // WHY title attr: chips truncate at 120px; the tooltip restores the full
      // label + tells the user what the click does (nav vs in-panel detail).
      title={navigable ? `Open ${node.label} (${node.ticker})` : `${node.label} — show details`}
      aria-label={navigable ? `Open instrument page for ${node.label}` : `Show details for ${node.label}`}
      className="flex h-[18px] max-w-[140px] items-center gap-1 rounded-[2px] border border-border/60 bg-muted/20 px-1.5 hover:bg-muted/50 transition-colors"
    >
      {/* Type dot — raw hex from the shared entity-type token map (the same
          palette sigma.js paints the canvas nodes with), so chip ↔ canvas
          colour identity is exact. Inline style is mandatory: tokens are hex
          values for the WebGL renderer, not Tailwind classes. */}
      <span
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: token.color }}
        aria-hidden="true"
      />
      <span className="truncate text-[10px] font-mono text-foreground/90">
        {node.label}
      </span>
      {/* Ticker suffix — only for navigable company chips; signals "this chip
          is a link to an instrument page" without an icon. */}
      {navigable && (
        <span className="shrink-0 text-[9px] font-mono text-muted-foreground tabular-nums">
          {node.ticker}
        </span>
      )}
    </button>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export function RelatedEntitiesPanel({
  entityId,
  nodes,
  onNodeSelect,
}: RelatedEntitiesPanelProps) {
  const router = useRouter();
  // Expanded = show ALL chips. Collapses back via "Show less" so a 60-node
  // graph can't permanently take over the rail after one curious click.
  const [expanded, setExpanded] = useState(false);

  const groups = useMemo<ChipGroups>(
    () => groupNodes(nodes ?? [], entityId),
    [nodes, entityId],
  );

  const total = groups.companies.length + groups.people.length + groups.other.length;

  // ── Truncation: a single budget consumed group-by-group (companies first)
  // so the cap is GLOBAL (≤12 chips on screen) while preserving the
  // companies → people → other priority order. ─────────────────────────────
  const visible = useMemo<ChipGroups>(() => {
    if (expanded) return groups;
    let budget = MAX_VISIBLE_CHIPS;
    const take = (arr: GraphNode[]): GraphNode[] => {
      const slice = arr.slice(0, Math.max(0, budget));
      budget -= slice.length;
      return slice;
    };
    return {
      companies: take(groups.companies),
      people: take(groups.people),
      other: take(groups.other),
    };
  }, [groups, expanded]);

  const hiddenCount = total - (visible.companies.length + visible.people.length + visible.other.length);

  // Section caption — same 9px mono uppercase convention as TopRelationsBlock.
  const sectionLabel = (
    <div className="flex h-[20px] items-center">
      <span className="text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground">
        Related Entities{total > 0 ? ` · (${total})` : ""}
      </span>
    </div>
  );

  // ── Named empty state (Round-1 rule: every section is data OR a named
  // state). Covers both "graph cache cold" and "entity genuinely isolated";
  // the hint explains what fills the section. ───────────────────────────────
  if (total === 0) {
    return (
      <div>
        {sectionLabel}
        <EmptyState
          icon={Share2}
          headline="No related entities"
          hint="Connections appear once the knowledge graph links this entity to companies, people or topics from ingested news."
          variant="inline"
        />
      </div>
    );
  }

  /** Activate a chip per the navigation rules in the file header. */
  const activate = (node: GraphNode) => {
    const ticker = node.ticker?.trim();
    if (COMPANY_TYPES.has(node.type) && ticker) {
      // WHY encodeURIComponent: tickers like "BRK.B" are path-safe but
      // defensive encoding matches PeerComparisonTable's navigation.
      router.push(`/instruments/${encodeURIComponent(ticker)}`);
      return;
    }
    // Ticker-less node (person, sector, topic, unlisted company): flip the
    // context rail to NodeDetailCard — same affordance as a canvas click.
    onNodeSelect(node.id);
  };

  /** Render one labelled chip group; renders nothing when the group is empty. */
  const renderGroup = (caption: string, groupNodesList: GraphNode[]) => {
    if (groupNodesList.length === 0) return null;
    return (
      <div className="space-y-1">
        <span className="block text-[8px] font-mono uppercase tracking-[0.12em] text-muted-foreground/70">
          {caption}
        </span>
        <div className="flex flex-wrap gap-1">
          {groupNodesList.map((n) => (
            <EntityChip
              key={n.id}
              node={n}
              navigable={COMPANY_TYPES.has(n.type) && !!n.ticker?.trim()}
              onActivate={() => activate(n)}
            />
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-1.5">
      {sectionLabel}
      {renderGroup("Companies", visible.companies)}
      {renderGroup("People", visible.people)}
      {renderGroup("Topics & Other", visible.other)}

      {/* Expander — only rendered when chips are actually hidden (or when
          expanded, to collapse back). A bare count keeps it one tap high. */}
      {(hiddenCount > 0 || expanded) && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="text-[9px] font-mono uppercase tracking-wider text-primary hover:text-primary/80 transition-colors"
          aria-expanded={expanded}
        >
          {expanded ? "Show less" : `+${hiddenCount} more`}
        </button>
      )}
    </div>
  );
}
