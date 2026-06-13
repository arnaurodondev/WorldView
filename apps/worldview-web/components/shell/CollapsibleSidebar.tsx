/**
 * components/shell/CollapsibleSidebar.tsx — Collapsible navigation rail
 *
 * WHY THIS EXISTS: PRD-0031 §4.2 — the v3 redesign replaces the fixed icon-only
 * sidebar with a collapsible rail that reveals labels, watchlist, and alarms in
 * expanded state. This follows Bloomberg's model: icon rail for power users who
 * know the layout, expanded labels + data panels for newer users or analysts
 * exploring the platform.
 *
 * WHY expanded state is owned by the parent (layout.tsx) not local state:
 * The shell layout needs to respond to the expanded width to re-calculate the
 * main content area. Lifting the state avoids prop-drilling the width value
 * across unrelated components.
 *
 * WHY transition-[width] not transition-all: animating only `width` prevents
 * Tailwind from transitioning every property that changes (e.g. text-color on
 * hover). Per §0.6 Anti-Patterns, transitions must only target intended properties.
 *
 * WHY the sidebar is drag-resizable (width + onResize props):
 * Power users (Bloomberg PMs, quant analysts) arrange their workspace to their
 * screen size. A fixed 220px sidebar wastes space on 1440px+ monitors; 220px
 * is too narrow on ultra-wide setups where long watchlist names truncate.
 * The resizable handle follows the VSCode / Bloomberg Terminal convention:
 * drag the panel edge to set a custom width, clamped to 160–340px.
 *
 * WHO USES IT: app/(app)/layout.tsx — replaces the old fixed-width <Sidebar />
 * DATA SOURCE: WatchlistPanel + AlarmsPanel (their own useQuery calls)
 * DESIGN REFERENCE: PRD-0031 §4.2–§4.3 Sidebar spec
 */

"use client";
// WHY "use client": uses usePathname (routing), React props with callbacks,
// useRef for drag-resize geometry, and renders WatchlistPanel + AlarmsPanel
// (both are client components).

import { useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart2,
  Bell,
  Briefcase,
  ChevronLeft,
  ChevronRight,
  Filter,
  LayoutDashboard,
  LayoutGrid,
  MessageSquare,
  Settings,
  Spline,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { WatchlistPanel } from "@/components/shell/WatchlistPanel";
import { AlarmsPanel } from "@/components/shell/AlarmsPanel";

// ── Nav items (PRD §4.2) ──────────────────────────────────────────────────────

/**
 * NAV_ITEMS — 8 primary navigation destinations.
 * WHY this order: Dashboard first (morning routine start), then Portfolio
 * (position review), Instruments (research), Screener (discovery), Workspace
 * (active analysis), Predictions (market sentiment), Alerts (monitoring),
 * Chat (research assistant). Mirrors the institutional trader's daily workflow.
 */
const NAV_ITEMS = [
  { href: "/dashboard",          icon: LayoutDashboard, label: "Dashboard"   },
  { href: "/portfolio",          icon: Briefcase,       label: "Portfolio"   },
  { href: "/instruments",        icon: TrendingUp,      label: "Instruments" },
  { href: "/screener",           icon: Filter,          label: "Screener"    },
  // PLAN-0112 T-5-03: graph-wide "weird connections" feed + pairwise pathfinder.
  // WHY after Screener: it is a discovery surface (like the screener), placed in
  // the "research/discovery" cluster of the daily workflow.
  { href: "/connections",        icon: Spline,          label: "Connections" },
  { href: "/workspace",          icon: LayoutGrid,      label: "Workspace"   },
  { href: "/prediction-markets", icon: BarChart2,       label: "Predictions" },
  { href: "/alerts",             icon: Bell,            label: "Alerts"      },
  { href: "/chat",               icon: MessageSquare,   label: "Chat"        },
] as const;

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * WHY these bounds: 160px is the minimum to show nav labels without truncation
 * on items like "Dashboard". 340px is the maximum — beyond that the sidebar
 * steals too much horizontal space from the main content panel on 1280px screens.
 */
const MIN_SIDEBAR_WIDTH = 160;
const MAX_SIDEBAR_WIDTH = 340;

/**
 * Width of the collapsed icon-only rail.
 *
 * WHY 40px (was 48px): PLAN-0071 Phase 6.5 terminal density sprint.
 * h-7 (28px) rows + 14px icons match the bloomberg-terminal reference density
 * (feremabraz/bloomberg-terminal). The collapsed 40px rail gives 14px icon +
 * 2×13px padding = minimum usable width. 48px was proportioned for 18px icons
 * at h-9 (36px) rows; 40px is the correct tight-rail for the new 14px icon size.
 */
const COLLAPSED_WIDTH = 40;

// ── Props ─────────────────────────────────────────────────────────────────────

interface CollapsibleSidebarProps {
  /** Whether the sidebar is currently in expanded vs collapsed (40px) mode */
  expanded: boolean;
  /** Callback — parent (layout.tsx) flips the expanded boolean and persists it */
  onToggle: () => void;
  /**
   * Current expanded width in px (default 220).
   * WHY optional: callers that haven't migrated yet don't need to pass it — the
   * sidebar falls back to 220px so no behaviour breaks.
   */
  width?: number;
  /**
   * Called with the new width (px) whenever the user drags the resize handle.
   * WHY optional: resize is a progressive enhancement; works without this prop.
   */
  onResize?: (w: number) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CollapsibleSidebar({
  expanded,
  onToggle,
  width = 220,
  onResize,
}: CollapsibleSidebarProps) {
  const pathname = usePathname();

  // WHY useRef for currentWidth: the drag handler is attached to document-level
  // mousemove/mouseup events which close over the values at the time of mousedown.
  // If we used the state value directly in the closure the drag would use a stale
  // snapshot (the width at the moment the user started dragging, which is correct
  // for the delta calculation — but we store it in a ref to be explicit).
  const widthAtDragStart = useRef<number>(width);

  /**
   * handleResizeMouseDown — attaches document-level move + up listeners to track
   * the drag, then removes them on mouseup (one-shot cleanup).
   *
   * WHY document-level listeners (not onMouseMove on the handle element):
   * If the user moves the mouse faster than the browser fires events, the cursor
   * can leave the 4px handle element. Document-level capture keeps tracking even
   * when the cursor is over the main content area during a fast drag.
   *
   * WHY e.preventDefault(): prevents text-selection in adjacent elements (nav
   * labels, watchlist item names) during the drag gesture.
   */
  function handleResizeMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    e.preventDefault();
    const startX = e.clientX;
    widthAtDragStart.current = width;

    function onMove(moveEvent: MouseEvent) {
      const delta = moveEvent.clientX - startX;
      const newWidth = Math.max(
        MIN_SIDEBAR_WIDTH,
        Math.min(MAX_SIDEBAR_WIDTH, widthAtDragStart.current + delta),
      );
      onResize?.(newWidth);
    }

    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    }

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  // Compute the actual CSS width:
  // - Collapsed: always 40px regardless of the stored `width` value
  // - Expanded: use the caller-supplied `width` (which comes from localStorage)
  const currentCssWidth = expanded ? width : COLLAPSED_WIDTH;

  return (
    <aside
      aria-label="Application navigation"
      // WHY relative: the drag handle uses `absolute right-0` positioning which
      // requires a positioned ancestor to anchor to. Without relative the handle
      // would escape to the nearest positioned parent (which could be the body).
      style={{ width: currentCssWidth }}
      className={cn(
        // WHY flex-col: vertical stack — nav → watchlist → alarms → bottom
        // WHY h-full: fills the vertical space between TopBar and viewport bottom
        // WHY bg-background (not bg-card): using bg-card (#18181b) while main area uses
        // bg-background (#09090b) creates TWO visible lines — the CSS border-r AND the
        // color-change boundary. Matching backgrounds means only the single explicit
        // CSS border (or drag handle line) is visible. This matches Bloomberg Terminal
        // convention: one hairline separator, not two.
        // WHY overflow-hidden: prevents labels from bleeding out during width animation
        // WHY border-r always for collapsed, NOT for expanded: in collapsed (48px) state
        // there is no drag handle so we need the CSS border-r as the separator.
        // In expanded state the drag handle provides its own w-px visual line at the
        // exact right edge — keeping border-r PLUS the drag handle line creates a
        // double-border artefact (the CSS border is inside the element's bounding box
        // while the drag handle's w-px line is inside the 4px hit zone, making them
        // appear as two adjacent 1px lines ~3px apart). Solution: use border-r only
        // when collapsed; let the drag handle supply the single border when expanded.
        expanded ? "relative flex flex-col h-full bg-background overflow-hidden shrink-0" : "relative flex flex-col h-full bg-background overflow-hidden shrink-0 border-r border-border",
        // WHY transition-[width]: only the width animates — color/padding changes remain instant
        // WHY ease-out: snappy opening (fast start, smooth finish) not linear
        // WHY only animate on toggle (not drag): we skip the transition during mouse-drag
        // because a 200ms lag behind the cursor would make dragging feel broken.
        // The transition is intentionally applied via CSS class (not inline style) so we
        // can remove it during drag by conditionally omitting the class — but since the
        // style prop drives the width during drag the transition class doesn't interfere
        // (the style change bypasses Tailwind's transition for inline-style updates in
        // browsers that apply transitions to style-prop changes; this is a known browser
        // behaviour difference from class-driven transitions, so the drag stays smooth).
        "transition-[width] duration-200 ease-out",
      )}
    >
      {/* ── Navigation items ──────────────────────────────────────────────── */}
      {/* WHY no logo row: "Worldview" already appears in the TopBar. Repeating a
       * brand glyph in the sidebar creates visual clutter. The TopBar is the
       * canonical brand location — Bloomberg Terminal convention. */}
      <nav className="flex flex-col shrink-0" aria-label="Main navigation">
        {NAV_ITEMS.map(({ href, icon: Icon, label }) => {
          // WHY startsWith: sub-routes (e.g. /alerts/event-123) also highlight
          // the parent Alerts nav item — user's conceptual location is still "Alerts"
          const isActive = pathname === href || pathname.startsWith(href + "/");

          return (
            <Link
              key={href}
              href={href}
              // WHY title only when collapsed: tooltip is redundant when the label
              // is visible. Collapsed state uses title as the only label affordance.
              title={!expanded ? label : undefined}
              aria-current={isActive ? "page" : undefined}
              aria-label={label}
              className={cn(
                // WHY h-7 (28px, was h-9 36px): PLAN-0071 Phase 6.5 terminal density
                // sprint. bloomberg-terminal reference uses h-6/h-7 nav rows; h-9 was
                // proportioned for desktop apps with large click targets. 28px is the
                // minimum for comfortable nav in a terminal context.
                // WHY px-2.5 gap-1.5 (was px-3 gap-2): tighter padding/gap matches
                // the reduced icon size (14px vs 18px) for proportional visual rhythm.
                "flex h-7 items-center gap-1.5 px-2.5",
                // WHY duration-0: INSTANT color change — Bloomberg convention.
                // Nav hover states must not lerp/animate — they must be instant.
                // Even 50ms transition on a nav link feels laggy in a trading terminal.
                "transition-colors duration-0",
                isActive
                  // WHY border-l-2 border-primary: left accent line is the Bloomberg
                  // active indicator pattern — more compact than a full background fill.
                  // WHY bg-primary/10: faint tint confirms the active state without
                  // competing with data content that follows the nav item.
                  ? "bg-primary/10 text-primary border-l-2 border-primary"
                  : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
              )}
            >
              {/* WHY h-[14px] w-[14px] (was h-[18px] w-[18px]): 14px icons in a 28px
                * row give proportional padding. 18px icons were right for 36px rows;
                * at 28px they consumed too much of the row height. */}
              <Icon className="h-[14px] w-[14px] shrink-0" />
              {expanded && (
                // WHY text-[10px] (was text-xs 12px): at 28px row height, 12px text
                // is too prominent relative to the compact icon. 10px keeps the label
                // readable while matching the terminal's data-text density standard.
                <span className="text-[10px] font-medium truncate">{label}</span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* ── Watchlist section (expanded only) ─────────────────────────────── */}
      {/* WHY conditional render (not CSS hide): WatchlistPanel fires two useQuery
       * calls. Conditionally rendering it prevents fetching data for a hidden panel
       * and conserves rate limit budget when the sidebar is collapsed. */}
      {expanded && (
        <div className="min-h-0 flex-1 overflow-hidden flex flex-col">
          <WatchlistPanel />
        </div>
      )}

      {/* ── Alarms section (expanded only) ────────────────────────────────── */}
      {/* WHY only in expanded state: in collapsed state, the "Alerts" nav item
       * above already provides a Bell icon linking to /alerts. Showing a second
       * Bell icon (the collapsed AlarmsPanel replacement) created a duplicate.
       * The AlarmsPanel itself renders a compact 22px-row list of recent alarms. */}
      {expanded && (
        // WHY max-h-[160px]: cap the alarms panel height so WatchlistPanel above
        // gets the majority of the sidebar flex space. 160px ≈ 7 alarm rows.
        <div className="overflow-hidden flex-none max-h-[160px]">
          <AlarmsPanel />
        </div>
      )}

      {/* ── Spacer (collapsed only) ───────────────────────────────────────── */}
      {/* WHY: in expanded state, WatchlistPanel has flex-1 which pushes the bottom
       * chrome (Settings + Collapse) to the viewport bottom.
       * In collapsed state there is no flex-1 element, so without this spacer the
       * bottom chrome sits immediately below the last nav item instead of at the
       * actual bottom of the sidebar. flex-1 here fills the remaining vertical space. */}
      {!expanded && <div className="flex-1" />}

      {/* ── Bottom chrome: Settings + collapse toggle ──────────────────────── */}
      <div className="flex shrink-0 flex-col border-t border-border">
        {/* Settings link — same h-7/px-2.5/gap-1.5/text-[10px] density as nav items above */}
        <Link
          href="/settings"
          title={!expanded ? "Settings" : undefined}
          aria-current={pathname.startsWith("/settings") ? "page" : undefined}
          className={cn(
            "flex h-7 items-center gap-1.5 px-2.5 transition-colors duration-0",
            pathname.startsWith("/settings")
              ? "bg-primary/10 text-primary border-l-2 border-primary"
              : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
          )}
        >
          {/* WHY h-[14px] w-[14px]: matches nav item icons — bottom chrome must
              align visually with the nav rail above it. */}
          <Settings className="h-[14px] w-[14px] shrink-0" />
          {expanded && <span className="text-[10px] font-medium">Settings</span>}
        </Link>

        {/* Collapse / expand toggle button */}
        {/* WHY at the bottom (not top): users expand the sidebar intentionally;
         * the toggle should be where the hand rests after navigating, not at the
         * top where it might be accidentally clicked. */}
        <button
          onClick={onToggle}
          className="flex h-7 items-center gap-1.5 px-2.5 text-muted-foreground hover:bg-muted/40 hover:text-foreground transition-colors duration-0"
          aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
          title={expanded ? "Collapse sidebar" : "Expand sidebar"}
        >
          {expanded ? (
            <>
              {/* WHY h-[14px] w-[14px]: matches nav item icons in the same bottom chrome. */}
              <ChevronLeft className="h-[14px] w-[14px] shrink-0" />
              <span className="text-[10px] font-medium">Collapse</span>
            </>
          ) : (
            // Centered chevron in collapsed rail
            <ChevronRight className="h-[14px] w-[14px]" />
          )}
        </button>
      </div>

      {/* ── Drag-resize handle (expanded only) ──────────────────────────────── */}
      {/*
       * WHY only show when expanded: the collapsed 40px rail is a fixed-width icon
       * rail — there is no meaningful range to drag (40px is the smallest usable
       * width for the 14px icons). Showing the handle on the collapsed rail would
       * confuse users who just want to expand via the chevron button.
       *
       * WHY absolute right-0: the handle sits on the very right edge of the sidebar
       * so it visually "touches" the border between sidebar and main content.
       * The aside has `relative` to anchor this.
       *
       * WHY w-1 (4px): narrow hit-target avoids stealing click events from nav labels
       * near the right edge. 4px is wide enough to grab reliably without a hover
       * state tooltip. The group-hover indicator line grows to w-px (1px) visual width
       * inside the 4px hit area.
       *
       * WHY cursor-col-resize: matches OS convention for column resize handles
       * (used by every major IDE and terminal app — VSCode, IntelliJ, BBG Terminal).
       */}
      {expanded && (
        <div
          className="absolute right-0 top-0 h-full w-1 cursor-col-resize group z-10 flex justify-end"
          onMouseDown={handleResizeMouseDown}
          // WHY role="separator" + aria-orientation: communicates to screen readers
          // that this is a resizable panel splitter, matching the ARIA Splitter pattern.
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
        >
          {/* Visual indicator line — always visible 1px separator, tints on hover.
           * WHY bg-border always (not transparent): this line IS the panel separator
           * when expanded — border-r was removed from the aside to avoid a double
           * border artefact. The line must be visible by default, not just on hover.
           * WHY group-hover:bg-primary/50: hover tints to primary color giving
           * clear feedback that the element is drag-resizable before the user clicks. */}
          <div className="h-full w-px bg-border group-hover:bg-primary/50 transition-colors" />
        </div>
      )}
    </aside>
  );
}
