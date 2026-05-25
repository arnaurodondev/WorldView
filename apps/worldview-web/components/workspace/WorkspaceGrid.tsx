/**
 * components/workspace/WorkspaceGrid.tsx — Resizable panel grid for workspace
 *
 * WHY THIS EXISTS: Institutional traders need to customize how much screen space
 * each data panel occupies — a chart panel should be bigger during intraday trading
 * than a news feed. react-resizable-panels provides drag-to-resize handles that
 * persist sizes to WorkspaceContext (survives page refresh and workspace switching).
 *
 * LAYOUT MODEL: WorkspaceConfig stores rows, each row has panels side-by-side.
 * Row 1: [chart | watchlist] ← horizontal Group
 * ── Separator ──
 * Row 2: [screener | alerts] ← horizontal Group
 *
 * WHY ROW-BASED (not column-based): The WorkspaceConfig data model uses rows.
 * Row-based rendering matches the mental model of "2 rows of panels, each with
 * side-by-side columns" — which is how institutional traders think about layouts.
 *
 * WHY v4 MIGRATION NOTES (react-resizable-panels v4 breaking changes):
 * - PanelGroup renamed to Group
 * - PanelResizeHandle renamed to Separator
 * - `direction` prop renamed to `orientation` on Group
 * - `onLayout` renamed to `onLayoutChanged` (fires after pointer release)
 * - Callback shape changed: was `(sizes: number[])`, now `(layout: Layout)`
 * where Layout = { [panelId: string]: number } — keyed by Panel id prop
 * - Separator MUST be a direct sibling of Panel inside Group (not nested inside Panel)
 *
 * WAVE H-5 ADDITIONS:
 * - AddPanelTray: slide-in right-edge tray (HTML5 drag-and-drop, no @dnd-kit)
 * - Quad detection: when workspace has exactly 2 rows × 2 panels, defaultSize="50%"
 * on the vertical PanelGroup so both rows start at equal height.
 * - Drop zone overlay: when the tray is open and the user drags a panel type over
 * the grid, addPanelToWorkspace is called on drop.
 *
 * WHY HTML5 DRAG-AND-DROP (not @dnd-kit): @dnd-kit is NOT in package.json.
 * The native draggable / onDragStart / onDragOver / onDrop API achieves the same
 * UX (tray items draggable → grid is the drop target) without an extra dependency.
 *
 * WHO USES IT: app/(app)/workspace/page.tsx
 * DATA SOURCE: WorkspaceContext (reads panel config + sizes, writes size updates)
 * DESIGN REFERENCE: PRD-0031 §5.2 Workspace layout, Wave 2 Terminal Quality
 */

"use client";
// WHY "use client": uses react-resizable-panels (browser drag events) + WorkspaceContext hooks

// WHY renamed imports: react-resizable-panels v4 renamed exports.
// PanelGroup → Group, PanelResizeHandle → Separator. Panel stays Panel.
import { useState } from "react";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle, type Layout } from "react-resizable-panels";
import { Plus } from "lucide-react";
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

// ── Panel Catalogue ────────────────────────────────────────────────────────────

/**
 * PANEL_CATALOGUE — the 10 panel types available to add via the tray.
 * WHY include all 10: users should be able to add any panel type at any time.
 * WHY this constant is module-level: both AddPanelTray and the drop handler
 * reference it — keeping it here avoids duplicating the list.
 */
const PANEL_CATALOGUE: { type: PanelType; label: string; icon: LucideIcon }[] = [
 { type: "chart", label: "Chart", icon: TrendingUp },
 { type: "watchlist", label: "Watchlist", icon: List },
 { type: "screener", label: "Screener", icon: LayoutDashboard },
 { type: "alerts", label: "Alerts", icon: Bell },
 { type: "fundamentals", label: "Fundamentals", icon: BarChart3 },
 { type: "news", label: "News", icon: Newspaper },
 { type: "graph", label: "Graph", icon: Network },
 { type: "portfolio", label: "Portfolio", icon: Briefcase },
 { type: "brief", label: "Brief", icon: BookOpen },
 { type: "chat", label: "Chat", icon: MessageSquare },
];

// ── AddPanelTray ───────────────────────────────────────────────────────────────

interface AddPanelTrayProps {
 /** Whether the tray is visible (slides in from right when true) */
 isOpen: boolean;
 /** Called when the user clicks the × close button */
 onClose: () => void;
}

/**
 * AddPanelTray — a slide-in tray listing all 10 panel types as draggable items.
 *
 * WHY a tray (not a dialog): a dialog forces the user to dismiss it before
 * interacting with the workspace. A tray stays open alongside the grid, letting
 * the user drag multiple panel types in sequence without reopening a modal.
 * This is the Bloomberg-style "panel palette" pattern.
 *
 * WHY HTML5 drag-and-drop (not @dnd-kit or react-dnd):
 * @dnd-kit is not in package.json. The native draggable / dataTransfer API
 * achieves the same UX:
 * - Each tray item sets draggable and encodes the panel type in dataTransfer.
 * - The grid area is the drop target (onDragOver + onDrop).
 * - effectAllowed="copy" gives the correct cursor (+ icon) during drag.
 *
 * WHY z-50: the tray must float above the panel grid, the tab strip, and any
 * panel header tooltips (typically z-10..z-30). z-50 matches shadcn Dialog/Sheet.
 *
 * WHY fixed right-0 (not absolute): the workspace grid uses overflow:hidden which
 * would clip an absolutely-positioned tray. Fixed positioning escapes the stacking
 * context and anchors to the viewport edge.
 *
 * WHY h-full top-0: tray spans the full viewport height so the user can see all
 * 10 panel types without scrolling, even on 720p screens.
 */
function AddPanelTray({ isOpen, onClose }: AddPanelTrayProps) {
 return (
 /*
 * WHY translate-x-full when closed (not display:none): CSS transform-based
 * show/hide preserves the DOM node between open/close, so the tray animation
 * plays on both open and close. display:none would show the tray instantly
 * (no closing animation).
 *
 * WHY transition-[transform] duration-200: 200ms is the Bloomberg-standard
 * drawer animation speed — fast enough to feel instant but visible enough
 * to orient the user spatially (element slid in from the right).
 */
 <div
 data-testid="add-panel-tray"
 className={[
 "fixed right-0 top-0 z-50 h-full w-[200px]",
 "border-l border-border/50 bg-card ",
 "transition-[transform] duration-200",
 isOpen ? "translate-x-0" : "translate-x-full",
 ].join(" ")}
 // WHY aria-hidden when closed: screen readers should not navigate to a
 // visually hidden off-screen tray. aria-hidden="true" excludes it from
 // the accessibility tree when closed.
 aria-hidden={!isOpen}
 >
 {/* ── Tray header ────────────────────────────────────────────────── */}
 <div className="flex items-center justify-between border-b border-border/40 px-3 py-2">
 <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-foreground">
 Add Panel
 </span>
 {/*
 * WHY leading-none: provides a compact click target without adding height
 * to the header. The × glyph is ~18px in a 28px tap zone.
 * NOTE: text-[20px] removed — it violates the finance-grade terminal mandate
 * (no text-[20px] on UI chrome). The × character renders at the inherited
 * text-[11px] size which is sufficient as a close affordance.
 */}
 <button
 onClick={onClose}
 aria-label="Close add panel tray"
 className="leading-none text-muted-foreground hover:text-foreground"
 >
 ×
 </button>
 </div>

 {/* ── Panel type list (draggable items) ──────────────────────────── */}
 {/*
 * WHY gap-0.5 (not gap-1): the tray is 200px wide with 10 items.
 * Minimal gap keeps all items visible without scrolling on 720p.
 */}
 <div className="flex flex-col gap-0.5 p-2">
 {PANEL_CATALOGUE.map(({ type, label, icon: Icon }) => (
 <div
 key={type}
 // WHY draggable: HTML5 native drag-and-drop; no external library.
 draggable
 onDragStart={(e) => {
 // WHY setData("panelType", type): the drop handler on the grid reads
 // this value via e.dataTransfer.getData("panelType") and passes it
 // to addPanelToWorkspace. Encoding the type string is the lightest
 // possible payload — no JSON serialisation needed.
 e.dataTransfer.setData("panelType", type);
 // WHY effectAllowed="copy": tells the browser to show the + copy
 // cursor during drag. "move" would imply removing from the tray,
 // which is wrong — the tray is a palette, not a source to deplete.
 e.dataTransfer.effectAllowed = "copy";
 }}
 className="flex cursor-grab items-center gap-2 rounded-[2px] px-2 py-1.5 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground active:cursor-grabbing"
 >
 <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden strokeWidth={1.5} />
 <span>{label}</span>
 </div>
 ))}
 </div>

 {/* ── Usage hint ─────────────────────────────────────────────────── */}
 {/*
 * WHY a hint label: the drag-to-grid interaction is not obvious without
 * signposting. The small tip text is styled as muted/dimmed so it
 * doesn't compete with the panel type list.
 */}
 <p className="px-3 pb-2 pt-1 text-[10px] leading-snug text-muted-foreground/50">
 Drag a panel onto the workspace to add it.
 </p>
 </div>
 );
}

// ── WorkspaceGrid ──────────────────────────────────────────────────────────────

interface WorkspaceGridProps {
 workspace: WorkspaceConfig;
}

export function WorkspaceGrid({ workspace }: WorkspaceGridProps) {
 const { updateWorkspaceLayout, addPanelToWorkspace } = useWorkspace();

 // WHY controlled tray state (not dialog): the slide-in tray must be toggled
 // by the "Add Panel" button at the bottom of the grid. The tray stays open
 // across multiple drags; the user explicitly closes it with the × button.
 const [trayOpen, setTrayOpen] = useState(false);

 // WHY isDragOver state: when the user drags a tray item over the grid area,
 // we show a subtle highlight so they know the grid is a valid drop target.
 // Without this feedback, the drag interaction feels broken.
 const [isDragOver, setIsDragOver] = useState(false);

 /**
 * isQuadLayout — detect the 2×2 quad layout for equal-height default sizing.
 *
 * WHY detect (not store a layout type): the WorkspaceConfig data model stores
 * rows/panels — it does not have a layout "type" field. Rather than extending
 * the data model (which would require migrations), we infer the quad shape from
 * the data: exactly 2 rows, each with exactly 2 panels.
 *
 * WHY defaultSize "50%" for quad rows: react-resizable-panels assigns the
 * vertical space based on defaultSize. "50%" starts both rows at equal height,
 * giving the 2×2 grid its balanced appearance. Users can still resize rows
 * after the initial render.
 */
 const isQuadLayout =
 workspace.rows.length === 2 &&
 workspace.rows.every((row) => row.panels.length === 2);

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
 // WHY updateWorkspaceLayout (not updatePanelSizes directly): PLAN-0051 T-C-3-01
 // funnels resize-driven persistence through the layout entry point so a future
 // drag-to-reorder change has a single hook to extend.
 if (nextSizes.length === workspace.rows.length) {
 updateWorkspaceLayout(workspace.id, nextSizes);
 }
 }

 /**
 * handleGridDrop — respond to a panel type being dropped onto the grid.
 *
 * WHY preventDefault on dragOver: without it, browsers show the "not allowed"
 * cursor and fire no drop event. preventDefault signals that the target accepts
 * the dragged item (required for HTML5 DnD spec compliance).
 */
 function handleGridDrop(e: React.DragEvent<HTMLDivElement>) {
 e.preventDefault();
 setIsDragOver(false);

 // WHY getData("panelType"): this is the value we set in AddPanelTray's onDragStart.
 // If the user drags something OTHER than a panel type (e.g., a URL from another
 // tab), getData returns "" — we guard against that with the includes check below.
 const type = e.dataTransfer.getData("panelType") as PanelType;
 const validTypes = PANEL_CATALOGUE.map((p) => p.type);
 if (!type || !validTypes.includes(type)) return;

 // WHY close the tray after drop: keeps the focus on the newly-added panel.
 // The user can reopen the tray if they want to add another panel.
 addPanelToWorkspace(workspace.id, type);
 setTrayOpen(false);
 }

 return (
 // WHY h-full: WorkspaceGrid must fill its parent flex container entirely.
 // The parent (workspace/page.tsx) is a flex-col with flex-1 on this container.
 <div className="flex flex-col h-full">
 {/* ── Main panel grid (drop zone when tray is open) ─────────────── */}
 {/*
 * WHY onDragOver + onDrop on the outer wrapper: the user can drop the
 * panel type anywhere over the workspace grid area. Attaching handlers to
 * the wrapper (not individual panels) simplifies the target surface — any
 * part of the grid accepts the drop.
 *
 * WHY ring-1 ring-primary/30 on dragOver: subtle visual signal that the
 * grid is ready to accept the drop. We avoid a heavy overlay that would
 * obscure the existing panels (trader needs to see where they're dropping).
 */}
 <div
 className={[
 "flex-1 min-h-0",
 isDragOver ? "ring-1 ring-inset ring-primary/30" : "",
 ].join(" ")}
 onDragOver={(e) => {
 // WHY only intercept when tray is open: prevents accidental drops from
 // other browser drag sources (e.g., dragged links from another tab).
 if (!trayOpen) return;
 e.preventDefault();
 e.dataTransfer.dropEffect = "copy";
 setIsDragOver(true);
 }}
 onDragLeave={() => setIsDragOver(false)}
 onDrop={trayOpen ? handleGridDrop : undefined}
 >
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
 <PanelGroup orientation="vertical" className="h-full">
 {workspace.rows.flatMap((row, rowIdx) => {
 const rowSizes = workspace.panelSizes?.[rowIdx];

 // WHY isQuadLayout defaultSize "50%": for the quad 2×2 layout,
 // both rows should start at equal height. Without an explicit
 // defaultSize, react-resizable-panels distributes height unevenly
 // when rows have different numbers of panels in other workspaces.
 // In quad mode, both rows have 2 panels so "50%" is semantically correct.
 const rowDefaultSize = isQuadLayout ? "50%" : `${100 / workspace.rows.length}%`;

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
 defaultSize={rowDefaultSize}
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
 </div>

 {/* ── Add Panel button ─────────────────────────────────────────────── */}
 {/*
 * WHY at bottom (not in panel header): adding a panel is a workspace-level
 * action, not a panel-level action. The button lives below the grid so it
 * doesn't compete visually with the panel chrome.
 *
 * WHY toggles the tray (not a dialog): the slide-in tray stays open while
 * the user drags multiple panel types. A dialog would require re-opening
 * after each add. The tray is the better affordance for the palette pattern.
 */}
 <div className="flex h-6 shrink-0 items-center border-t border-border px-2">
 <button
 onClick={() => setTrayOpen((prev) => !prev)}
 className="flex items-center gap-1 text-[10px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground"
 aria-label="Add panel"
 // WHY aria-expanded: communicates tray state to screen readers.
 // Paired with the tray's aria-hidden so the tree is consistent.
 aria-expanded={trayOpen}
 >
 <Plus className="h-3 w-3" aria-hidden strokeWidth={1.5} />
 Add Panel
 </button>
 </div>

 {/* ── Slide-in panel type tray ─────────────────────────────────────── */}
 {/*
 * WHY AddPanelTray is OUTSIDE the grid div (not inside it): the tray uses
 * fixed positioning to escape any overflow:hidden ancestor. Rendering it
 * inside the grid div would NOT cause overflow clipping (fixed escapes),
 * but sibling placement makes the component structure clearer — the tray
 * is a workspace-level overlay, not a grid-level overlay.
 */}
 <AddPanelTray isOpen={trayOpen} onClose={() => setTrayOpen(false)} />
 </div>
 );
}
