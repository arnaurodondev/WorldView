/**
 * components/workspace/WorkspacePanelContainer.tsx — Individual panel wrapper
 *
 * WHY THIS EXISTS: Every workspace panel needs the same chrome: a 24px terminal
 * header with the color chip, type label, optional symbol selector, and close button.
 * Centralizing this chrome prevents each widget from needing to implement its own
 * header — which would produce visual inconsistency across panel types.
 *
 * WHO USES IT: WorkspaceGrid renders one WorkspacePanelContainer per panel slot.
 * DATA SOURCE: Reads symbol from SymbolLinkingContext based on panel group color.
 * DESIGN REFERENCE: PRD-0031 §5.4 Panel chrome spec, Wave 2 Terminal Quality Additions
 */

"use client";
// WHY "use client": uses React state for color popover and references WorkspaceContext hooks

import { useState } from "react";
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
import { OHLCVChart } from "@/components/instrument/OHLCVChart";
import { FundamentalsTab } from "@/components/instrument/FundamentalsTab";
import { EntityGraphPanel } from "@/components/instrument/EntityGraphPanel";
import { AlertsList } from "@/components/alerts/AlertsList";
import { WorkspaceScreenerWidget } from "./WorkspaceScreenerWidget";
import { WorkspaceChatWidget } from "./WorkspaceChatWidget";
import { WorkspaceWatchlistWidget } from "./WorkspaceWatchlistWidget";
import { WorkspaceBriefWidget } from "./WorkspaceBriefWidget";
import { WorkspaceNewsPanel } from "./WorkspaceNewsPanel";
import { WorkspacePortfolioPanel } from "./WorkspacePortfolioPanel";
import { useWorkspace, type PanelType, type WorkspacePanel } from "@/contexts/WorkspaceContext";
import { useSymbolLinking, GROUP_COLOR_HEX, type GroupColor } from "@/contexts/SymbolLinkingContext";
import { cn } from "@/lib/utils";

// ── Panel type metadata ────────────────────────────────────────────────────────

/**
 * PANEL_META — display metadata for each of the 10 panel types.
 * WHY separate from widget map: keeps icon/label lookups O(1) by key,
 * independent from the switch statement that renders content.
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

/** Symbol-aware panel types — these use a linked symbol for data fetching */
const SYMBOL_AWARE_TYPES = new Set<PanelType>([
  "chart", "fundamentals", "graph",
]);

// ── Group color selector ───────────────────────────────────────────────────────

/**
 * GROUP_COLORS — ordered list of available link group colors.
 * WHY include null: "Unlink" removes the panel from any color group.
 */
const GROUP_COLORS: GroupColor[] = ["red", "green", "blue", "yellow", "purple", null];

// ── Panel content switch ───────────────────────────────────────────────────────

/**
 * PanelContent — renders the correct widget for a given panel type.
 * WHY separate function (not inline JSX): keeps WorkspacePanelContainer JSX
 * readable and makes the type→component mapping easy to audit.
 *
 * WHY demoEntityId / demoInstrumentId: workspace panels currently use a demo entity
 * when no symbol is linked. A future wave adds a per-panel symbol picker.
 * When a symbol IS linked via SymbolLinkingContext, this component should prefer it.
 */
function PanelContent({
  type,
  linkedSymbol,
}: {
  type: PanelType;
  linkedSymbol: string | undefined;
}) {
  // WHY these demo IDs: S9 has a demo AAPL entity seeded for development.
  // When symbol linking is active, the linked symbol overrides the demo.
  const entityId = linkedSymbol ? `entity-${linkedSymbol.toLowerCase()}` : "entity-aapl";
  const instrumentId = linkedSymbol ? `ins-${linkedSymbol.toLowerCase()}` : "ins-aapl";

  switch (type) {
    case "chart":
      return <OHLCVChart instrumentId={instrumentId} />;

    case "fundamentals":
      return <FundamentalsTab instrumentId={instrumentId} />;

    case "graph":
      return <EntityGraphPanel entityId={entityId} centerLabel={linkedSymbol ?? "AAPL"} />;

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
      // TypeScript exhaustiveness guard
      return null;
  }
}

// ── Main component ─────────────────────────────────────────────────────────────

interface WorkspacePanelContainerProps {
  panel: WorkspacePanel;
  /** The workspace this panel belongs to — needed for panel removal */
  workspaceId: string;
}

export function WorkspacePanelContainer({ panel, workspaceId }: WorkspacePanelContainerProps) {
  const { removePanelFromWorkspace } = useWorkspace();
  const { getSymbol, setSymbol } = useSymbolLinking();

  // WHY local state for groupColor: the user picks a color via the chip popover.
  // This is UI-only state — it doesn't need to be in WorkspaceContext because
  // the color only matters while the panel is mounted.
  const [groupColor, setGroupColor] = useState<GroupColor>(null);
  const [showColorPicker, setShowColorPicker] = useState(false);

  const meta = PANEL_META[panel.type];
  const Icon = meta.icon;
  const linkedSymbol = SYMBOL_AWARE_TYPES.has(panel.type)
    ? getSymbol(groupColor)
    : undefined;

  function handleColorSelect(color: GroupColor) {
    setGroupColor(color);
    setShowColorPicker(false);
    // WHY propagate existing symbol to new color group: if the panel already
    // has a symbol context, link it to the new color so other panels in the
    // same color group immediately show the same symbol.
    if (color && linkedSymbol) {
      setSymbol(color, linkedSymbol);
    }
  }

  return (
    // WHY flex flex-col min-h-0: panel must fill the full PanelGroup slot height.
    // min-h-0 prevents overflow from the child's auto height expanding past the slot.
    // bg-card: terminal panel background (#111113), distinct from page bg (#09090B).
    <div className="flex flex-col min-h-0 h-full bg-card">

      {/* ── Panel header — 24px terminal chrome ──────────────────────────── */}
      {/*
       * WHY h-6 (24px): §0 spec mandates ≤24px panel chrome overhead.
       * The header is the ONLY chrome — no title bar, no card padding.
       * border-b border-border: the structural divider between header and content.
       * shrink-0: prevents the header from shrinking when content is tall.
       */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2 gap-1.5">

        {/* Color group chip — 6px dot, click to open color picker */}
        {/*
         * WHY inline style for color: Tailwind purges dynamic `bg-[#hex]` classes
         * unless explicitly listed. GROUP_COLOR_HEX provides stable hex values.
         * WHY border on null: unlinked panels show a subtle border-only dot.
         */}
        <div className="relative">
          <button
            className={cn(
              "h-1.5 w-1.5 rounded-full shrink-0 cursor-pointer",
              "ring-offset-background focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
              !groupColor && "border border-border/60",
            )}
            style={groupColor ? { backgroundColor: GROUP_COLOR_HEX[groupColor] } : {}}
            aria-label="Set symbol group color"
            onClick={() => setShowColorPicker((v) => !v)}
          />

          {/* Color picker dropdown */}
          {showColorPicker && (
            <div
              className="absolute left-0 top-full z-50 mt-1 flex flex-col gap-0.5 rounded-[2px] border border-border bg-card p-1.5 shadow-none"
              // WHY onMouseLeave: close picker when user moves away — no explicit close button
              // needed since the picker is tiny and closing by leave is the most ergonomic UX.
              onMouseLeave={() => setShowColorPicker(false)}
            >
              {GROUP_COLORS.map((color) => (
                <button
                  key={color ?? "none"}
                  className={cn(
                    "flex items-center gap-1.5 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground rounded-[2px]",
                    groupColor === color && "text-foreground",
                  )}
                  onClick={() => handleColorSelect(color)}
                >
                  <span
                    className={cn(
                      "h-2 w-2 rounded-full shrink-0",
                      !color && "border border-border",
                    )}
                    style={color ? { backgroundColor: GROUP_COLOR_HEX[color] } : {}}
                  />
                  {color ? color.charAt(0).toUpperCase() + color.slice(1) : "Unlink"}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Panel type icon — 14px, muted foreground */}
        {/*
         * WHY h-3.5 w-3.5 (14px): smaller than nav icons (20px) — panel headers are
         * dense chrome; the icon communicates type at a glance without dominating.
         */}
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />

        {/* Panel type label — 10px ALL CAPS, terminal section header pattern (§0.1) */}
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          {meta.label}
        </span>

        {/* Symbol indicator (symbol-aware panels only) */}
        {/*
         * WHY show symbol inline (not a full input): the panel header is only 24px.
         * A [AAPL ▾] bracketed label is the Bloomberg pattern — click to change symbol.
         * Future wave: add click handler to open a symbol picker.
         */}
        {SYMBOL_AWARE_TYPES.has(panel.type) && linkedSymbol && (
          <span className="font-mono text-[11px] text-foreground ml-1 cursor-default">
            [{linkedSymbol}]
          </span>
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
            <Maximize2 className="h-3 w-3" aria-hidden />
          </button>

          {/* Close button — removes THIS panel instance from the workspace */}
          <button
            className="flex h-5 w-5 items-center justify-center text-muted-foreground hover:text-foreground"
            aria-label={`Close ${meta.label} panel`}
            onClick={() => removePanelFromWorkspace(workspaceId, panel.id)}
          >
            <X className="h-3 w-3" aria-hidden />
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
        <PanelContent type={panel.type} linkedSymbol={linkedSymbol} />
      </div>
    </div>
  );
}
