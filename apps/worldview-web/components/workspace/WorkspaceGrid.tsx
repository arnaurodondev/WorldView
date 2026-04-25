/**
 * components/workspace/WorkspaceGrid.tsx — Resizable panel grid for workspace
 *
 * WHY THIS EXISTS: Institutional traders need to customize how much screen space
 * each data panel occupies — a chart panel should be bigger during intraday trading
 * than a news feed. react-resizable-panels provides drag-to-resize handles that
 * persist sizes to WorkspaceContext (survives page refresh and workspace switching).
 *
 * LAYOUT MODEL: WorkspaceConfig stores rows, each row has panels side-by-side.
 *   Row 1: [chart | watchlist]  ← horizontal Group
 *   ── Separator ──
 *   Row 2: [screener | alerts]  ← horizontal Group
 *
 * WHY ROW-BASED (not column-based): The WorkspaceConfig data model uses rows.
 * Row-based rendering matches the mental model of "2 rows of panels, each with
 * side-by-side columns" — which is how institutional traders think about layouts.
 *
 * WHY v4 MIGRATION NOTES (react-resizable-panels v4 breaking changes):
 *   - PanelGroup renamed to Group
 *   - PanelResizeHandle renamed to Separator
 *   - `direction` prop renamed to `orientation` on Group
 *   - `onLayout` renamed to `onLayoutChanged` (fires after pointer release)
 *   - Callback shape changed: was `(sizes: number[])`, now `(layout: Layout)`
 *     where Layout = { [panelId: string]: number } — keyed by Panel id prop
 *   - Separator MUST be a direct sibling of Panel inside Group (not nested inside Panel)
 *
 * WHO USES IT: app/(app)/workspace/page.tsx
 * DATA SOURCE: WorkspaceContext (reads panel config + sizes, writes size updates)
 * DESIGN REFERENCE: PRD-0031 §5.2 Workspace layout, Wave 2 Terminal Quality
 */

"use client";
// WHY "use client": uses react-resizable-panels (browser drag events) + WorkspaceContext hooks

// WHY renamed imports: react-resizable-panels v4 renamed exports.
// PanelGroup → Group, PanelResizeHandle → Separator. Panel stays Panel.
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle, type Layout } from "react-resizable-panels";
import { Plus } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
  type LucideIcon,
} from "lucide-react";
import { useWorkspace, type WorkspaceConfig, type PanelType } from "@/contexts/WorkspaceContext";
import { WorkspacePanelContainer } from "./WorkspacePanelContainer";

// ── Add Panel Modal ────────────────────────────────────────────────────────────

/**
 * PANEL_CATALOGUE — the 10 panel types available to add via the Add Panel dialog.
 * WHY include all 10: users should be able to add any panel type at any time.
 */
const PANEL_CATALOGUE: { type: PanelType; label: string; icon: LucideIcon }[] = [
  { type: "chart",        label: "Chart",        icon: TrendingUp },
  { type: "watchlist",    label: "Watchlist",    icon: List },
  { type: "screener",     label: "Screener",     icon: LayoutDashboard },
  { type: "alerts",       label: "Alerts",       icon: Bell },
  { type: "fundamentals", label: "Fundamentals", icon: BarChart3 },
  { type: "news",         label: "News",         icon: Newspaper },
  { type: "graph",        label: "Graph",        icon: Network },
  { type: "portfolio",    label: "Portfolio",    icon: Briefcase },
  { type: "brief",        label: "Brief",        icon: BookOpen },
  { type: "chat",         label: "Chat",         icon: MessageSquare },
];

/**
 * AddPanelModalContent — inner content of the Add Panel dialog.
 * WHY separate component: keeps dialog content decoupled from the outer Dialog
 * wrapper so the catalogue grid renders cleanly inside DialogContent.
 */
function AddPanelModalContent({ workspaceId }: { workspaceId: string }) {
  const { addPanelToWorkspace } = useWorkspace();

  return (
    // WHY gap-px grid: each panel type card is visually separated by 1px seams
    // (background showing through), consistent with the workspace panel seam style.
    <div className="grid grid-cols-2 gap-px bg-border">
      {PANEL_CATALOGUE.map(({ type, label, icon: Icon }) => (
        <button
          key={type}
          className="flex items-center gap-2 bg-card px-3 h-9 text-left hover:bg-muted/40"
          // WHY no explicit close: shadcn Dialog wraps content in a context that
          // closes when the button interaction triggers the parent DialogClose.
          // For now, add and rely on user closing the dialog manually.
          onClick={() => addPanelToWorkspace(workspaceId, type)}
        >
          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <span className="text-[11px] text-foreground">{label}</span>
        </button>
      ))}
    </div>
  );
}

// ── WorkspaceGrid ──────────────────────────────────────────────────────────────

interface WorkspaceGridProps {
  workspace: WorkspaceConfig;
}

export function WorkspaceGrid({ workspace }: WorkspaceGridProps) {
  const { updatePanelSizes } = useWorkspace();

  /**
   * handleRowLayout — converts v4 Layout object to ordered size array and persists.
   *
   * WHY this conversion exists: react-resizable-panels v4 changed the onLayoutChanged
   * callback from `(sizes: number[])` to `(layout: Layout)` where Layout is a map
   * of { panelId → percentage }. WorkspaceContext stores sizes as number[][] (ordered
   * arrays), so we must convert by reading each panel's ID in order.
   *
   * WHY onLayoutChanged (not onLayoutChange): v4 has both callbacks.
   * onLayoutChange fires on every pointer move (too frequent for localStorage writes).
   * onLayoutChanged fires only after the pointer is released — correct for persistence.
   *
   * @param rowIdx — which row fired the event
   * @param layout — v4 Layout object: { [panelId]: percentage (0-100) }
   * @param panels — the panels in this row, in render order (used to sort sizes)
   */
  function handleRowLayout(
    rowIdx: number,
    layout: Layout,
    panels: WorkspaceConfig["rows"][number]["panels"]
  ) {
    // WHY map by panel.id: v4 Layout keys are the Panel id props we pass below.
    // Fallback to equal distribution if a panel's id isn't in the layout yet.
    const sizes = panels.map((p) => layout[p.id] ?? 100 / panels.length);

    // WHY full rebuild: we persist ALL rows' sizes each time any row changes.
    // We need the previous rows' data to avoid wiping sizes for unchanged rows.
    const currentSizes: (number[] | undefined)[] = workspace.panelSizes
      ? [...workspace.panelSizes]
      : workspace.rows.map(() => undefined);
    currentSizes[rowIdx] = sizes;
    const nextSizes = currentSizes.filter((s): s is number[] => s !== undefined);

    // WHY length check: only persist when all rows have been touched at least once.
    // Partial writes (some rows undefined) would corrupt the saved layout.
    if (nextSizes.length === workspace.rows.length) {
      updatePanelSizes(workspace.id, nextSizes);
    }
  }

  return (
    // WHY h-full: WorkspaceGrid must fill its parent flex container entirely.
    // The parent (workspace/page.tsx) is a flex-col with flex-1 on this container.
    <div className="flex flex-col h-full">
      {/* ── Main panel grid ─────────────────────────────────────────────── */}
      {/*
       * WHY PanelGroup orientation="vertical": rows are stacked vertically.
       * Each row is a Panel that itself contains a horizontal PanelGroup
       * for the side-by-side columns within that row.
       *
       * WHY flatMap (not map): Separator must be a DIRECT sibling of Panel inside
       * Group — it cannot be nested inside Panel. flatMap lets us interleave
       * [Separator, Panel] alternately in a single flat children array.
       *
       * WHY gap-px on Separator: the 1px seam IS the border between panels.
       * Background color (#09090B) shows through gap-px = hairline border.
       */}
      <PanelGroup orientation="vertical" className="flex-1 min-h-0">
        {workspace.rows.flatMap((row, rowIdx) => {
          const rowSizes = workspace.panelSizes?.[rowIdx];

          // WHY array spread pattern: flatMap requires returning an array per element.
          // We conditionally prepend a Separator before each non-first row Panel.
          return [
            // Vertical separator between rows (not before the first row)
            ...(rowIdx > 0
              ? [
                  <PanelResizeHandle
                    key={`row-sep-${rowIdx}`}
                    // WHY h-px: the resize handle is 1px — same as the border seam.
                    // data-separator attribute is used for custom hover/active styles.
                    className="h-px bg-border hover:bg-primary/60 data-[separator]:bg-border transition-colors duration-0 cursor-row-resize"
                  />,
                ]
              : []),

            // Row panel — contains horizontal group for this row's panels
            <Panel
              key={`row-${rowIdx}`}
              // WHY minSize="10%": prevents rows from becoming completely invisible.
              // 10% of the viewport height is the minimum a row can be dragged to.
              minSize="10%"
              defaultSize={`${100 / workspace.rows.length}%`}
            >
              {/* Horizontal PanelGroup for panels within this row */}
              {/*
               * WHY onLayoutChanged (not onLayoutChange): onLayoutChange fires on
               * every pointer move during resize — too frequent for localStorage.
               * onLayoutChanged fires once when the user releases the handle.
               */}
              <PanelGroup
                orientation="horizontal"
                onLayoutChanged={(layout) => handleRowLayout(rowIdx, layout, row.panels)}
                className="h-full"
              >
                {row.panels.flatMap((panel, panelIdx) => {
                  const defaultPanelSize = rowSizes?.[panelIdx] ?? 100 / row.panels.length;

                  return [
                    // Horizontal separator between columns (not before first column)
                    ...(panelIdx > 0
                      ? [
                          <PanelResizeHandle
                            key={`sep-${panel.id}`}
                            // WHY w-px: 1px visual handle. The Separator renders its
                            // own hit-target expansion — no pseudo-element needed.
                            className="w-px bg-border hover:bg-primary/60 data-[separator]:bg-border transition-colors duration-0 cursor-col-resize"
                          />,
                        ]
                      : []),

                    // Panel for this workspace panel config
                    <Panel
                      key={panel.id}
                      // WHY id={panel.id}: v4 Layout callback uses Panel id as key.
                      // We must pass the workspace panel's ID so handleRowLayout
                      // can map layout[panel.id] → sizes in order.
                      id={panel.id}
                      minSize="15%"
                      defaultSize={`${defaultPanelSize}%`}
                    >
                      <WorkspacePanelContainer
                        panel={panel}
                        workspaceId={workspace.id}
                      />
                    </Panel>,
                  ];
                })}
              </PanelGroup>
            </Panel>,
          ];
        })}
      </PanelGroup>

      {/* ── Add Panel button ─────────────────────────────────────────────── */}
      {/*
       * WHY at bottom (not in panel header): adding a panel is a workspace-level
       * action, not a panel-level action. The button lives below the grid so it
       * doesn't compete visually with the panel chrome.
       */}
      <div className="flex h-6 shrink-0 items-center border-t border-border px-2">
        <Dialog>
          <DialogTrigger asChild>
            <button
              className="flex items-center gap-1 text-[10px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground"
              aria-label="Add panel"
            >
              <Plus className="h-3 w-3" aria-hidden />
              Add Panel
            </button>
          </DialogTrigger>
          <DialogContent
            // WHY max-w-sm: the panel type grid is 2 columns × 10 items.
            // A narrow dialog keeps the layout compact and focused.
            className="max-w-sm p-0 bg-card border border-border rounded-[2px] shadow-none"
          >
            <DialogHeader className="px-3 py-2 border-b border-border">
              <DialogTitle className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-sans font-normal">
                Add Panel
              </DialogTitle>
            </DialogHeader>
            <AddPanelModalContent workspaceId={workspace.id} />
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}
