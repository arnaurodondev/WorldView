/**
 * app/(app)/workspace/page.tsx — Multi-panel Workspace page
 *
 * WHY THIS EXISTS: Institutional traders need simultaneous visibility into
 * multiple data streams — a chart, screener results, news feed, and alerts
 * all at once. Navigating to separate pages breaks flow and loses context.
 * The Workspace solves this: a configurable multi-panel layout that lets
 * traders assemble exactly the data surfaces they need for their workflow.
 *
 * DESIGN PHILOSOPHY: Bloomberg Terminal model — every panel shows live data,
 * no wasted space, panel selector is always accessible at the top.
 *
 * MVP SCOPE: Up to 4 panels in a 2×2 grid (desktop). Each panel is a Card
 * containing one of 8 panel types. Panels are added/removed via a selector
 * bar at the top. No drag-to-resize — that is deferred to a future wave.
 *
 * WHY CLIENT STATE ONLY: Panel configuration is per-session preference, not
 * persisted data. localStorage persistence is a future enhancement. Using
 * useState keeps the MVP simple and avoids server state complexity.
 *
 * WHO USES IT: Power users / institutional traders navigating via the sidebar.
 * DATA SOURCE: Each panel delegates to its own component which calls S9 via gateway.
 * DESIGN REFERENCE: PRD-0028 §6.5 Workspace, canvas State A (11 Workspace panels).
 */

"use client";
// WHY "use client": uses useState for active panel list (client-only interaction).
// Each embedded component manages its own TanStack Query data-fetching.

import { useState } from "react";
import {
  LayoutDashboard,
  TrendingUp,
  Newspaper,
  MessageSquare,
  Bell,
  BarChart3,
  Network,
  Briefcase,
  X,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { OHLCVChart } from "@/components/instrument/OHLCVChart";
import { FundamentalsTab } from "@/components/instrument/FundamentalsTab";
import { EntityGraphPanel } from "@/components/instrument/EntityGraphPanel";
import { AlertsList } from "@/components/alerts/AlertsList";

// ── Panel type catalogue ───────────────────────────────────────────────────────

/**
 * PanelType — the 8 supported workspace panel types.
 *
 * WHY enum-style literal union (not enum): TypeScript string literal unions
 * are narrowable, serialisable, and don't require a runtime import. The 8
 * types map to the panel definitions in PRD-0028 §6.5.
 */
type PanelType =
  | "chart"
  | "screener"
  | "news"
  | "chat"
  | "alerts"
  | "fundamentals"
  | "graph"
  | "portfolio";

/**
 * PanelDef — metadata for a panel type used in the selector bar.
 *
 * WHY separate from PanelType: The selector bar needs a human-readable label
 * and icon for each type. This struct pairs those with the type key so the
 * selector can be rendered from data (no if/else chains).
 */
interface PanelDef {
  type: PanelType;
  label: string;
  /** Lucide icon component (h-4 w-4 size) */
  icon: React.ElementType;
  description: string;
}

/**
 * PANEL_CATALOGUE — all 8 panel types with their display metadata.
 *
 * WHY const array: React.ElementType references are resolved at module load time,
 * and the catalogue is immutable. Array preserves render order in selector bar.
 */
const PANEL_CATALOGUE: PanelDef[] = [
  {
    type: "chart",
    label: "Chart",
    icon: TrendingUp,
    description: "OHLCV candlestick chart",
  },
  {
    type: "screener",
    label: "Screener",
    icon: LayoutDashboard,
    description: "Instrument filter panel",
  },
  {
    type: "news",
    label: "News",
    icon: Newspaper,
    description: "Top news feed",
  },
  {
    type: "chat",
    label: "Chat",
    icon: MessageSquare,
    description: "AI chat assistant",
  },
  {
    type: "alerts",
    label: "Alerts",
    icon: Bell,
    description: "Recent alerts feed",
  },
  {
    type: "fundamentals",
    label: "Fundamentals",
    icon: BarChart3,
    description: "Fundamental metrics",
  },
  {
    type: "graph",
    label: "Graph",
    icon: Network,
    description: "Entity relationship graph",
  },
  {
    type: "portfolio",
    label: "Portfolio",
    icon: Briefcase,
    description: "Holdings summary",
  },
];

/**
 * MAX_PANELS — cap visible panels at 4 for the 2×2 MVP grid.
 *
 * WHY 4: A 2×2 grid is the densest layout that remains readable on a 1440px
 * wide desktop monitor without horizontal scrolling. More panels would require
 * drag-to-resize (future wave) to be usable.
 */
const MAX_PANELS = 4;

/**
 * DEFAULT_PANELS — initial set of panels shown on first load.
 *
 * WHY chart + news + alerts: These three are the most universally useful
 * panels for any trader's workflow. Chart for price context, news for
 * catalysts, alerts for real-time signals. A 4th slot is left empty to
 * communicate that the user can add more.
 */
const DEFAULT_PANELS: PanelType[] = ["chart", "news", "alerts"];

// ── Panel content component ────────────────────────────────────────────────────

/**
 * PanelContent — renders the content area for a given panel type.
 *
 * WHY separate component: Keeps the main workspace JSX clean. Each case
 * delegates to the correct existing component (OHLCVChart, AlertsList, etc.)
 * or renders a lightweight inline placeholder for panels without a dedicated
 * component yet (screener, chat, portfolio, fundamentals in workspace context).
 *
 * WHY placeholder for some panels: The instrument-detail components (OHLCVChart,
 * FundamentalsTab, EntityGraphPanel) require an instrumentId / entityId.
 * In the workspace MVP, we show a demo entity ("entity-aapl") so the component
 * renders meaningfully. A future wave will add an entity picker per panel.
 */
function PanelContent({ type }: { type: PanelType }) {
  // WHY demo entity ID: workspace MVP doesn't have per-panel entity selection.
  // "entity-aapl" is used as a placeholder that produces real-looking data
  // from S9 in development. Future wave adds a per-panel entity picker.
  const demoEntityId = "entity-aapl";
  const demoInstrumentId = "ins-aapl";

  switch (type) {
    case "chart":
      // OHLCVChart handles its own loading/error states with Skeleton + error text
      return (
        <OHLCVChart
          instrumentId={demoInstrumentId}
          // WHY no initialBars: workspace panels load independently without a
          // CompanyOverview prefetch, so there are no pre-fetched bars available.
        />
      );

    case "fundamentals":
      // FundamentalsTab handles its own loading/error states
      return (
        <FundamentalsTab
          instrumentId={demoInstrumentId}
          // WHY no initialData: same reason as chart — no CompanyOverview prefetch
        />
      );

    case "graph":
      // EntityGraphPanel handles its own loading/error states
      return (
        <EntityGraphPanel
          entityId={demoEntityId}
          centerLabel="AAPL"
        />
      );

    case "alerts":
      // AlertsList handles its own loading/error/empty states
      return <AlertsList />;

    case "news":
      // WHY inline placeholder (not importing NewsPage): The news feed is a
      // standalone page. Embedding the full page in a workspace panel would
      // duplicate the header/toolbar. A future wave creates a NewsPanel
      // component specifically for workspace embedding.
      return <WorkspacePlaceholder type="news" />;

    case "screener":
      // WHY inline placeholder: ScreenerPage has a complex filter form that
      // needs full-page width to be usable. A future wave creates a compact
      // ScreenerPanel with pre-set filters for workspace use.
      return <WorkspacePlaceholder type="screener" />;

    case "chat":
      // WHY inline placeholder: Chat requires a streaming SSE connection and
      // input form that needs at minimum 300px height. The ChatPage is built
      // for full-page use. A future wave adds a compact ChatPanel.
      return <WorkspacePlaceholder type="chat" />;

    case "portfolio":
      // WHY inline placeholder: The PortfolioSummary dashboard widget could
      // be reused here. Wiring it in is a 2-line change — deferred to keep
      // this wave focused on the workspace scaffold.
      return <WorkspacePlaceholder type="portfolio" />;

    default:
      // TypeScript exhaustiveness guard — should never reach here
      return null;
  }
}

// ── Placeholder sub-component ──────────────────────────────────────────────────

/**
 * WorkspacePlaceholder — renders an informative "coming to workspace" message
 * for panel types not yet adapted for workspace embedding.
 *
 * WHY show a message (not just a Skeleton): The user added this panel; they
 * deserve an explanation of why it's not fully interactive yet, not a
 * misleading loading state that never resolves.
 */
function WorkspacePlaceholder({ type }: { type: PanelType }) {
  const def = PANEL_CATALOGUE.find((p) => p.type === type);
  const Icon = def?.icon ?? LayoutDashboard;

  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      {/* Panel type icon for visual context */}
      <Icon className="h-8 w-8 text-muted-foreground/30" aria-hidden="true" />
      <p className="text-sm font-medium text-muted-foreground">
        {def?.label ?? type} panel
      </p>
      <p className="max-w-[200px] text-xs text-muted-foreground/60">
        {/* WHY this message: users need to know this is a planned feature, not a bug */}
        Compact workspace layout coming in a future wave. Navigate to the full{" "}
        {def?.label ?? type} page for the complete experience.
      </p>
    </div>
  );
}

// ── Panel selector bar ─────────────────────────────────────────────────────────

/**
 * PanelSelectorBar — horizontal scrollable button bar to add/remove panels.
 *
 * WHY overflow-x-auto: On narrow screens (< 768px) all 8 panel buttons don't
 * fit in a single row. Horizontal scroll preserves all options without wrapping
 * the layout. The user can swipe to see all options.
 *
 * WHY outline (active) vs ghost (inactive): The outline variant with a
 * primary-coloured border clearly marks which panels are currently active
 * while ghost buttons fade visually for inactive ones. This follows the
 * existing timeframe button pattern in OHLCVChart.
 */
function PanelSelectorBar({
  activePanels,
  onAdd,
  onRemove,
}: {
  activePanels: PanelType[];
  onAdd: (type: PanelType) => void;
  onRemove: (type: PanelType) => void;
}) {
  const isAtMax = activePanels.length >= MAX_PANELS;

  return (
    // WHY border-b: separates the selector bar from the panel grid below,
    // consistent with the tab navigation style in InstrumentDetailPage.
    <div className="border-b border-border/40 bg-background px-4 py-3">
      {/* Row 1: Page title + panel count */}
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-sm font-semibold tracking-tight text-foreground">Workspace</h1>
        {/* WHY show panel count: gives instant feedback on how many more panels
            the user can add before hitting the 4-panel limit. */}
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {activePanels.length}/{MAX_PANELS} panels
        </span>
      </div>

      {/* Row 2: Panel type buttons — horizontally scrollable */}
      <div
        className="flex gap-2 overflow-x-auto pb-1"
        // WHY pb-1: prevents the scrollbar from clipping the button bottom edge
        role="toolbar"
        aria-label="Panel selector"
      >
        {PANEL_CATALOGUE.map((def) => {
          const isActive = activePanels.includes(def.type);
          const Icon = def.icon;

          return (
            <Button
              key={def.type}
              // WHY outline for active: matches the design token for "selected" state;
              // ghost for inactive preserves visual hierarchy (active panels stand out).
              variant={isActive ? "outline" : "ghost"}
              size="sm"
              // WHY aria-label: the button performs two different actions (add vs remove)
              // depending on state. aria-label makes this explicit for screen readers.
              aria-label={
                isActive
                  ? `Remove ${def.label} panel`
                  : `Add ${def.label} panel`
              }
              aria-pressed={isActive}
              // WHY disabled when at max AND not active: prevents adding a 5th panel
              // while still allowing removal of active panels.
              disabled={isAtMax && !isActive}
              onClick={() => {
                if (isActive) {
                  onRemove(def.type);
                } else {
                  onAdd(def.type);
                }
              }}
              className={`shrink-0 gap-1.5 text-xs ${
                isActive ? "border-primary/40 text-primary" : ""
              }`}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              {def.label}
              {/* WHY Plus/X icon suffix: makes add/remove intent immediately scannable;
                  users don't need to read the aria-label to understand the action. */}
              {isActive ? (
                <X className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
              ) : (
                <Plus className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
              )}
            </Button>
          );
        })}
      </div>

      {/* Row 3: Hint when at max capacity */}
      {isAtMax && (
        <p className="mt-2 text-[10px] text-muted-foreground/60">
          {/* WHY show hint: prevents confusion when the user tries to add a 5th panel
              and the button is disabled — without this hint they wouldn't know why. */}
          Maximum {MAX_PANELS} panels reached. Remove a panel to add another.
        </p>
      )}
    </div>
  );
}

// ── WorkspacePanel — single panel card ────────────────────────────────────────

/**
 * WorkspacePanel — a Card wrapping one panel type with a title header and close button.
 *
 * WHY close button in header (not in selector bar only): Power users expect to
 * dismiss panels quickly without hunting for the panel button in the toolbar.
 * Both mechanisms work — toolbar toggles provide discoverability, card header
 * X provides speed.
 */
function WorkspacePanel({
  type,
  onClose,
}: {
  type: PanelType;
  onClose: () => void;
}) {
  const def = PANEL_CATALOGUE.find((p) => p.type === type);
  const Icon = def?.icon ?? LayoutDashboard;

  return (
    // WHY min-h-0: in a flex/grid container, children default to auto height.
    // min-h-0 allows the panel to shrink below its content height when needed.
    <Card className="flex min-h-0 flex-col overflow-hidden">
      <CardHeader className="shrink-0 border-b border-border/40 p-3">
        <div className="flex items-center justify-between">
          {/* Panel icon + title row */}
          <div className="flex items-center gap-2">
            <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <CardTitle className="text-xs text-foreground">
              {def?.label ?? type}
            </CardTitle>
          </div>

          {/* Close button — removes this panel from the workspace */}
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0 text-muted-foreground hover:text-foreground"
            aria-label={`Close ${def?.label ?? type} panel`}
            onClick={onClose}
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </Button>
        </div>
      </CardHeader>

      {/* WHY overflow-auto: panel content may overflow (chart, long news list).
          overflow-auto adds a scrollbar instead of clipping content. */}
      <CardContent className="min-h-0 flex-1 overflow-auto p-3">
        <PanelContent type={type} />
      </CardContent>
    </Card>
  );
}

// ── Empty workspace state ──────────────────────────────────────────────────────

/**
 * EmptyWorkspace — shown when the user has closed all panels.
 *
 * WHY: An empty grid with no panels would be confusing. This component guides
 * the user back to the selector bar with a clear call-to-action.
 */
function EmptyWorkspace() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <LayoutDashboard className="h-12 w-12 text-muted-foreground/20" aria-hidden="true" />
      <div>
        <p className="text-sm font-medium text-muted-foreground">
          No panels open
        </p>
        <p className="mt-1 text-xs text-muted-foreground/60">
          Use the panel selector above to add up to {MAX_PANELS} panels.
        </p>
      </div>
    </div>
  );
}

// ── Page component ─────────────────────────────────────────────────────────────

/**
 * WorkspacePage — the main Workspace page component.
 *
 * STATE:
 * - activePanels: ordered list of currently open panel types (max 4)
 *
 * WHY no URL sync for panel state: Session-local preference, not shareable
 * state. URL sync adds complexity (serialisation, hydration mismatch) without
 * user benefit for an MVP. Future wave: add ?panels= query param for link sharing.
 */
export default function WorkspacePage() {
  // ── Active panel state ───────────────────────────────────────────────────────
  // WHY DEFAULT_PANELS as initial value: gives the user a useful starting layout
  // (chart + news + alerts) on first visit instead of an empty workspace.
  const [activePanels, setActivePanels] = useState<PanelType[]>(DEFAULT_PANELS);

  // ── Panel management callbacks ────────────────────────────────────────────────

  /**
   * handleAdd — add a panel type to the workspace.
   *
   * WHY guard against duplicates: the selector bar disables already-active
   * buttons, but the callback defensively checks anyway to prevent double-adds
   * (e.g., rapid clicks before the disabled state propagates).
   *
   * WHY guard against MAX_PANELS: belt-and-suspenders — the button is also
   * disabled in the UI, but this prevents state corruption if called directly.
   */
  function handleAdd(type: PanelType) {
    setActivePanels((prev) => {
      if (prev.includes(type) || prev.length >= MAX_PANELS) return prev;
      return [...prev, type];
    });
  }

  /**
   * handleRemove — remove a panel type from the workspace.
   *
   * WHY filter (not splice): filter is a pure function that returns a new
   * array without mutating the original — consistent with React state update rules.
   */
  function handleRemove(type: PanelType) {
    setActivePanels((prev) => prev.filter((p) => p !== type));
  }

  return (
    // WHY flex-col min-h-0: the workspace sits inside the app shell's content
    // area which is a flex container. min-h-0 allows the workspace to fill
    // the available height without overflowing the shell.
    <div className="flex min-h-0 flex-col">
      {/* ── Panel selector bar ─────────────────────────────────────────────── */}
      <PanelSelectorBar
        activePanels={activePanels}
        onAdd={handleAdd}
        onRemove={handleRemove}
      />

      {/* ── Panel grid ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto p-4">
        {activePanels.length === 0 ? (
          // Empty state when the user has closed all panels
          <EmptyWorkspace />
        ) : (
          /*
           * WHY grid-cols-1 sm:grid-cols-2: mobile-first responsive grid.
           * On mobile (< 640px) panels stack vertically — touch scrolling through
           * a 2-column grid on 375px is unusable. On tablet+ (≥ 640px) we use
           * 2 columns, giving each panel ~50% width for readable content density.
           *
           * WHY not 3 or 4 columns: at 3+ columns each panel is ~300px wide.
           * Charts need ≥ 400px to show candlestick detail; fundamentals tables
           * need ≥ 300px. 2-column is the practical maximum for this content type.
           *
           * WHY auto-rows-[minmax(320px,_auto)]: panels need a minimum height of
           * 320px to show meaningful content (chart: 280px + 40px header).
           * auto allows panels with more content (news, fundamentals) to grow.
           */
          <div
            className="grid grid-cols-1 gap-3 sm:grid-cols-2"
            style={{ gridAutoRows: "minmax(320px, auto)" }}
            // WHY role="region" + aria-label: makes the panel grid a named ARIA landmark
            // region. Tests and screen readers can then locate it by role + name without
            // relying on implementation-specific CSS class selectors.
            role="region"
            aria-label="Workspace panels"
          >
            {activePanels.map((type) => (
              <WorkspacePanel
                key={type}
                type={type}
                onClose={() => handleRemove(type)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
