/**
 * components/workspace/WorkspacePanelContainer.tsx — Individual panel wrapper
 *
 * WHY THIS EXISTS: Every workspace panel needs the same chrome: a 24px terminal
 * header with the link-color dot, type icon, type label, optional symbol indicator,
 * maximise + close buttons. Centralising this chrome prevents each widget from
 * implementing its own header — which would produce visual inconsistency.
 *
 * WHY THE COLOR PICKER MOVED OUT (PLAN-0051 T-C-3-05): The earlier inline color
 * popover lived inside this file as ~50 lines of JSX. Now SymbolLinkColorPicker.tsx
 * owns the dot + popover; this container just renders it. That keeps the panel
 * header logic readable and lets us reuse the picker elsewhere.
 *
 * WHY useSymbolLink(panelId) (not local state): symbol linking is the source of
 * truth for which ticker a symbol-aware widget should display. Reading from the
 * context here lets the container pass the linked symbol down to PanelContent —
 * widgets that opt into useSymbolLink themselves can also fetch the same value
 * directly without prop-drilling.
 *
 * WHO USES IT: WorkspaceGrid renders one WorkspacePanelContainer per panel slot.
 * DATA SOURCE: SymbolLinkingContext (current symbol per panel id).
 * DESIGN REFERENCE: PRD-0031 §5.4 Panel chrome spec; DESIGN_SYSTEM.md §6.13.
 */

"use client";
// WHY "use client": references context hooks (useWorkspace, useSymbolLink) and
// renders a Popover (Radix portals require browser DOM).

import {
  TrendingUp,
  Newspaper,
  MessageSquare,
  Bell,
  BarChart3,
  Network,
  Briefcase,
  LayoutDashboard,
  BookOpen,
  List,
  Maximize2,
  X,
  type LucideIcon,
} from "lucide-react";
import { EntityGraphPanel } from "@/components/instrument/EntityGraphPanel";
import { AlertsList } from "@/components/alerts/AlertsList";
import { WorkspaceScreenerWidget } from "./WorkspaceScreenerWidget";
import { WorkspaceChatWidget } from "./WorkspaceChatWidget";
import { WorkspaceWatchlistWidget } from "./WorkspaceWatchlistWidget";
import { WorkspaceBriefWidget } from "./WorkspaceBriefWidget";
import { WorkspaceNewsPanel } from "./WorkspaceNewsPanel";
import { WorkspacePortfolioPanel } from "./WorkspacePortfolioPanel";
import { WorkspaceChartWidget } from "./WorkspaceChartWidget";
import { WorkspaceFundamentalsWidget } from "./WorkspaceFundamentalsWidget";
import { SymbolLinkColorPicker } from "./SymbolLinkColorPicker";
import { TickerPicker } from "./TickerPicker";
import { useWorkspace, type PanelType, type WorkspacePanel } from "@/contexts/WorkspaceContext";
import { useSymbolLink } from "@/contexts/SymbolLinkingContext";

// ── Panel type metadata ────────────────────────────────────────────────────────

/**
 * PANEL_META — display metadata for the supported panel types.
 *
 * WHY separate from the widget switch: keeps icon/label lookups O(1) by key,
 * independent from the render-time dispatch that picks a component.
 */
const PANEL_META: Record<PanelType, { label: string; icon: LucideIcon }> = {
  chart:        { label: "CHART",        icon: TrendingUp },
  watchlist:    { label: "WATCHLIST",    icon: List },
  screener:     { label: "SCREENER",     icon: LayoutDashboard },
  alerts:       { label: "ALERTS",       icon: Bell },
  fundamentals: { label: "FUNDAMENTALS", icon: BarChart3 },
  news:         { label: "NEWS",         icon: Newspaper },
  graph:        { label: "GRAPH",        icon: Network },
  portfolio:    { label: "PORTFOLIO",    icon: Briefcase },
  brief:        { label: "BRIEF",        icon: BookOpen },
  chat:         { label: "CHAT",         icon: MessageSquare },
};

/**
 * Symbol-aware panel types — these render symbol-locked content (chart/fundamentals/
 * graph). When a symbol is broadcast through their link group, they re-render with it.
 *
 * WHY a Set: cheaper membership checks than Array.includes for repeated lookups in
 * the render loop, and the intent ("is this panel symbol-aware?") reads cleanly.
 */
const SYMBOL_AWARE_TYPES = new Set<PanelType>(["chart", "fundamentals", "graph"]);

// ── Panel content switch ───────────────────────────────────────────────────────

/**
 * PanelContent — renders the correct widget for a given panel type.
 *
 * WHY separate function (not inline JSX): keeps WorkspacePanelContainer JSX
 * readable and makes the type→component mapping easy to audit.
 *
 * WHY linkedSymbol vs linkedInstrumentId: instrument-fetching widgets need an
 * instrument_id (API contract); chart and entity-graph want the human ticker for
 * display. Passing both lets each widget pick the value that matches its data path.
 */
function PanelContent({
  type,
  linkedSymbol,
  linkedInstrumentId,
}: {
  type: PanelType;
  linkedSymbol: string | null;
  linkedInstrumentId: string | null;
}) {
  // WHY graph keeps a demo AAPL fallback: the entity-graph component requires an
  // entityId to render anything. Without the demo seed it would show a permanently
  // empty SVG canvas. Until graph gets its own dedicated empty state, we keep the
  // demo entity so the graph panel always has SOMETHING to display.
  const entityId = linkedSymbol
    ? `entity-${linkedSymbol.toLowerCase()}`
    : "entity-aapl";
  const centerLabel = linkedSymbol ?? "AAPL";

  // WHY undefined when not linked: the panel-sized widgets (WorkspaceChartWidget,
  // WorkspaceFundamentalsWidget) render their own "no symbol linked" empty state
  // when ticker is undefined, prompting the user to pick a color via the
  // SymbolLinkColorPicker. Falling back to demo AAPL would mask the un-linked state.
  // (graph keeps the demo fallback below — its empty SVG canvas is a worse UX.)
  const tickerOrUndefined = linkedSymbol ?? undefined;
  // WHY void linkedInstrumentId: reserved for future widgets that need a precise
  // instrument_id (currently chart + fundamentals derive ins-<ticker> internally).
  // The void expression silences the unused-arg lint without removing the prop.
  void linkedInstrumentId;

  switch (type) {
    case "chart":
      return <WorkspaceChartWidget ticker={tickerOrUndefined} />;

    case "fundamentals":
      return <WorkspaceFundamentalsWidget ticker={tickerOrUndefined} />;

    case "graph":
      return <EntityGraphPanel entityId={entityId} centerLabel={centerLabel} />;

    case "alerts":
      return <AlertsList />;

    case "news":
      return <WorkspaceNewsPanel />;

    case "screener":
      return <WorkspaceScreenerWidget />;

    case "chat":
      return <WorkspaceChatWidget />;

    case "portfolio":
      return <WorkspacePortfolioPanel />;

    case "watchlist":
      return <WorkspaceWatchlistWidget />;

    case "brief":
      return <WorkspaceBriefWidget />;

    default:
      // TypeScript exhaustiveness guard — every PanelType must have a case above.
      return null;
  }
}

// ── Main component ─────────────────────────────────────────────────────────────

interface WorkspacePanelContainerProps {
  panel: WorkspacePanel;
  /** The workspace this panel belongs to — needed for the close button */
  workspaceId: string;
}

export function WorkspacePanelContainer({
  panel,
  workspaceId,
}: WorkspacePanelContainerProps) {
  const { removePanelFromWorkspace } = useWorkspace();
  // WHY useSymbolLink (not useSymbolLinking): we only need this panel's view of the
  // linked symbol — the convenience hook is narrower and prevents accidentally
  // reading sibling-panel state we shouldn't react to.
  const { symbol, instrumentId, isLinked } = useSymbolLink(panel.id);

  const meta = PANEL_META[panel.type];
  const Icon = meta.icon;

  return (
    // WHY flex flex-col min-h-0: panel must fill the full PanelGroup slot height.
    // min-h-0 prevents overflow from the child's auto height expanding past the slot.
    // bg-card: terminal panel background (#111113), distinct from page bg (#09090B).
    <div className="flex flex-col min-h-0 h-full bg-card">

      {/* ── Panel header — 24px terminal chrome ──────────────────────────── */}
      {/*
       * WHY h-6 (24px): §0 spec mandates ≤24px panel chrome overhead.
       * The header is the ONLY chrome — no title bar, no card padding.
       * border-b border-border: structural divider between header and content.
       * shrink-0: prevents the header from shrinking when content is tall.
       */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2 gap-1.5">

        {/* Color group dot — opens a popover for color selection */}
        <SymbolLinkColorPicker panelId={panel.id} />

        {/* Panel type icon — 14px, muted foreground */}
        {/*
         * WHY h-3.5 w-3.5 (14px): smaller than nav icons (20px) — panel headers are
         * dense chrome; the icon communicates type at a glance without dominating.
         * WHY strokeWidth={1.5}: Bloomberg terminal chrome uses hairline strokes —
         * the default 2px stroke weight is too heavy for 14px panel-chrome icons.
         */}
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.5} aria-hidden />

        {/* Panel type label — 10px ALL CAPS, terminal section header pattern (§0.1) */}
        {/*
         * WHY text-[10px] uppercase: Bloomberg panel chrome labels are compact 10px
         * uppercase identifiers — this distinguishes chrome from data content (which
         * uses 11px). font-medium reinforces the structural hierarchy over body text.
         */}
        <span className="text-[10px] uppercase tracking-[0.08em] font-medium text-muted-foreground">
          {meta.label}
        </span>

        {/* Symbol picker — only on symbol-aware panels (chart/fundamentals/graph) */}
        {/*
         * WHY show on ALL symbol-aware panels (not just when linked): even an unlinked
         * panel needs the picker so the user can set an initial symbol. The TickerPicker
         * renders "[—]" when symbol is null — a visible invite to pick a ticker.
         *
         * WHY TickerPicker (not a static label): the static "[AAPL]" was read-only.
         * TickerPicker broadcasts the new symbol to all panels in the same color group
         * via setActiveSymbol — essential for the multi-panel symbol-linking UX.
         */}
        {SYMBOL_AWARE_TYPES.has(panel.type) && (
          <TickerPicker panelId={panel.id} symbol={symbol} />
        )}

        {/* Spacer — pushes right controls to the edge */}
        <div className="ml-auto flex items-center gap-0.5">
          {/* Fullscreen button — future wave: expands panel to full viewport */}
          <button
            className="flex h-5 w-5 items-center justify-center text-muted-foreground hover:text-foreground"
            aria-label={`Maximize ${meta.label} panel`}
            // WHY no-op for now: fullscreen is deferred to a future wave.
            // The button exists for UX consistency (Bloomberg has this affordance).
            onClick={() => {}}
          >
            {/* WHY strokeWidth={1.5}: toolbar icons at 12px must use hairline strokes —
                default 2px weight overpowers the tiny icon at this size. */}
            <Maximize2 className="h-3 w-3" strokeWidth={1.5} aria-hidden />
          </button>

          {/* Close button — removes THIS panel instance from the workspace */}
          <button
            className="flex h-5 w-5 items-center justify-center text-muted-foreground hover:text-foreground"
            aria-label={`Close ${meta.label} panel`}
            onClick={() => removePanelFromWorkspace(workspaceId, panel.id)}
          >
            {/* WHY strokeWidth={1.5}: same hairline rule as Maximize2 above. */}
            <X className="h-3 w-3" strokeWidth={1.5} aria-hidden />
          </button>
        </div>
      </div>

      {/* ── Panel content — fills remaining height ────────────────────────── */}
      {/*
       * WHY flex-1 min-h-0 overflow-auto: the content area must fill the space
       * left by the 24px header. min-h-0 allows shrinking below content height
       * (required for overflow-auto to kick in). overflow-auto adds a scrollbar
       * when content exceeds the panel height.
       */}
      <div className="flex-1 min-h-0 overflow-auto">
        <PanelContent
          type={panel.type}
          linkedSymbol={isLinked ? symbol : null}
          linkedInstrumentId={isLinked ? instrumentId : null}
        />
      </div>
    </div>
  );
}
