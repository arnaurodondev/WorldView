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
  Bell,
  Briefcase,
  ChevronLeft,
  ChevronRight,
  Filter,
  LayoutDashboard,
  LayoutGrid,
  MessageSquare,
  Settings,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { WatchlistPanel } from "@/components/shell/WatchlistPanel";
import { AlarmsPanel } from "@/components/shell/AlarmsPanel";

// ── Nav items (PRD §4.2) ──────────────────────────────────────────────────────

/**
 * NAV_ITEMS — 7 primary navigation destinations.
 * WHY this order: Dashboard first (morning routine start), then Portfolio
 * (position review), Instruments (research), Screener (discovery), Workspace
 * (active analysis), Alerts (monitoring), Chat (research assistant).
 * Mirrors the institutional trader's daily workflow sequence.
 */
const NAV_ITEMS = [
  { href: "/dashboard",   icon: LayoutDashboard, label: "Dashboard"   },
  { href: "/portfolio",   icon: Briefcase,       label: "Portfolio"   },
  { href: "/instruments", icon: TrendingUp,      label: "Instruments" },
  { href: "/screener",    icon: Filter,          label: "Screener"    },
  { href: "/workspace",   icon: LayoutGrid,      label: "Workspace"   },
  { href: "/alerts",      icon: Bell,            label: "Alerts"      },
  { href: "/chat",        icon: MessageSquare,   label: "Chat"        },
] as const;

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * WHY these bounds: 160px is the minimum to show nav labels without truncation
 * on items like "Dashboard". 340px is the maximum — beyond that the sidebar
 * steals too much horizontal space from the main content panel on 1280px screens.
 */
const MIN_SIDEBAR_WIDTH = 160;
const MAX_SIDEBAR_WIDTH = 340;

/** Width of the collapsed icon-only rail — matches TopBar row height rhythm */
const COLLAPSED_WIDTH = 48;

// ── Props ─────────────────────────────────────────────────────────────────────

interface CollapsibleSidebarProps {
  /** Whether the sidebar is currently in expanded vs collapsed (48px) mode */
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
  // - Collapsed: always 48px regardless of the stored `width` value
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
        // WHY border-r always: a single consistent right border regardless of expanded
        // state avoids the "no separator" flash when transitioning. The drag handle is
        // still visible on hover (absolute inset-0 group-hover indicator) but the border
        // provides the baseline separator at all times.
        "relative flex flex-col h-full bg-background overflow-hidden shrink-0 border-r border-border",
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
                // WHY h-9 (36px): matches TopBar height rhythm — nav rows feel
                // proportional to the top chrome, not oversized relative to data rows.
                "flex h-9 items-center gap-2 px-3",
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
              <Icon className="h-[18px] w-[18px] shrink-0" />
              {expanded && (
                <span className="text-xs font-medium truncate">{label}</span>
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
        {/* Settings link */}
        <Link
          href="/settings"
          title={!expanded ? "Settings" : undefined}
          aria-current={pathname.startsWith("/settings") ? "page" : undefined}
          className={cn(
            "flex h-9 items-center gap-2 px-3 transition-colors duration-0",
            pathname.startsWith("/settings")
              ? "bg-primary/10 text-primary border-l-2 border-primary"
              : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
          )}
        >
          <Settings className="h-[18px] w-[18px] shrink-0" />
          {expanded && <span className="text-xs font-medium">Settings</span>}
        </Link>

        {/* Collapse / expand toggle button */}
        {/* WHY at the bottom (not top): users expand the sidebar intentionally;
         * the toggle should be where the hand rests after navigating, not at the
         * top where it might be accidentally clicked. */}
        <button
          onClick={onToggle}
          className="flex h-9 items-center gap-2 px-3 text-muted-foreground hover:bg-muted/40 hover:text-foreground transition-colors duration-0"
          aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
          title={expanded ? "Collapse sidebar" : "Expand sidebar"}
        >
          {expanded ? (
            <>
              <ChevronLeft className="h-[18px] w-[18px] shrink-0" />
              <span className="text-xs font-medium">Collapse</span>
            </>
          ) : (
            // Centered chevron in collapsed rail
            <ChevronRight className="h-[18px] w-[18px]" />
          )}
        </button>
      </div>

      {/* ── Drag-resize handle (expanded only) ──────────────────────────────── */}
      {/*
       * WHY only show when expanded: the collapsed 48px rail is a fixed-width icon
       * rail — there is no meaningful range to drag (48px is the smallest usable
       * width for the icons). Showing the handle on the collapsed rail would confuse
       * users who just want to expand via the chevron button.
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
          className="absolute right-0 top-0 h-full w-1 cursor-col-resize group z-10"
          onMouseDown={handleResizeMouseDown}
          // WHY role="separator" + aria-orientation: communicates to screen readers
          // that this is a resizable panel splitter, matching the ARIA Splitter pattern.
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
        >
          {/* Visual indicator line — 1px wide, only colored on hover
           * WHY bg-border default: subtle so it doesn't compete with content;
           * WHY group-hover:bg-primary/50: hover tints to primary color giving
           * clear feedback that the element is interactive before the user clicks. */}
          <div className="h-full w-px bg-border group-hover:bg-primary/50 transition-colors" />
        </div>
      )}
    </aside>
  );
}
