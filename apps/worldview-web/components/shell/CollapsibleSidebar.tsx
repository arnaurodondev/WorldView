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
 * WHO USES IT: app/(app)/layout.tsx — replaces the old fixed-width <Sidebar />
 * DATA SOURCE: WatchlistPanel + AlarmsPanel (their own useQuery calls)
 * DESIGN REFERENCE: PRD-0031 §4.2–§4.3 Sidebar spec
 */

"use client";
// WHY "use client": uses usePathname (routing), React props with callbacks,
// and renders WatchlistPanel + AlarmsPanel (both are client components).

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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { WatchlistPanel } from "@/components/shell/WatchlistPanel";
import { AlarmsPanel } from "@/components/shell/AlarmsPanel";

// ── Nav items (PRD §4.2) ──────────────────────────────────────────────────────

/**
 * NAV_ITEMS — 6 primary navigation destinations.
 * WHY this order: Workspace first (primary use case), then discovery tools
 * (Dashboard → Screener), then personal tools (Portfolio → Alerts → Chat).
 * Matches the order a first-time Bloomberg user would naturally reach for.
 */
const NAV_ITEMS = [
  { href: "/workspace",  icon: LayoutGrid,     label: "Workspace"  },
  { href: "/dashboard",  icon: LayoutDashboard, label: "Dashboard"  },
  { href: "/screener",   icon: Filter,          label: "Screener"   },
  { href: "/portfolio",  icon: Briefcase,       label: "Portfolio"  },
  { href: "/alerts",     icon: Bell,            label: "Alerts"     },
  { href: "/chat",       icon: MessageSquare,   label: "Chat"       },
] as const;

// ── Props ─────────────────────────────────────────────────────────────────────

interface CollapsibleSidebarProps {
  /** Whether the sidebar is currently in expanded (220px) vs collapsed (48px) mode */
  expanded: boolean;
  /** Callback — parent (layout.tsx) flips the expanded boolean and persists it */
  onToggle: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CollapsibleSidebar({ expanded, onToggle }: CollapsibleSidebarProps) {
  const pathname = usePathname();

  return (
    <aside
      aria-label="Application navigation"
      className={cn(
        // WHY flex-col: vertical stack — logo → nav → watchlist → alarms → bottom
        // WHY h-full: fills the vertical space between TopBar and viewport bottom
        // WHY bg-card (not bg-background): sidebar is a raised surface per elevation rules
        // WHY overflow-hidden: prevents labels from bleeding out during width animation
        "flex flex-col h-full bg-card border-r border-border overflow-hidden shrink-0",
        // WHY transition-[width]: only the width animates — color/padding changes remain instant
        // WHY ease-out: snappy opening (fast start, smooth finish) not linear
        "transition-[width] duration-200 ease-out",
        expanded ? "w-[220px]" : "w-[48px]",
      )}
    >
      {/* ── Logo / brand row ────────────────────────────────────────────────── */}
      {/* WHY h-9 (36px): matches the new TopBar height — creates a horizontal
       * chrome line across the full viewport width at the same elevation. */}
      <div className="flex h-9 shrink-0 items-center border-b border-border px-3">
        {/* WHY text-primary: brand glyph uses primary color (sky blue) to anchor
         * the "W" as a visual landmark — consistent with Bloomberg's amber logo. */}
        <span className="text-[13px] font-semibold text-primary font-mono shrink-0">W</span>
        {/* WHY conditional render (not opacity-0): avoids reserving horizontal space
         * for the label when collapsed — the "W" glyph should be centered in 48px. */}
        {expanded && (
          <span className="ml-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground whitespace-nowrap overflow-hidden">
            WORLDVIEW
          </span>
        )}
      </div>

      {/* ── Navigation items ──────────────────────────────────────────────── */}
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

      {/* ── Alarms section ────────────────────────────────────────────────── */}
      {/* WHY shown in both states: ALARMS is critical — must be visible even
       * when collapsed. Collapsed: just the Bell icon (via the bottom settings row).
       * The AlarmsPanel itself renders a compact 22px-row list when expanded. */}
      {expanded ? (
        // WHY max-h-[160px]: cap the alarms panel height so WatchlistPanel above
        // gets the majority of the sidebar flex space. 160px ≈ 7 alarm rows.
        <div className="overflow-hidden flex-none max-h-[160px]">
          <AlarmsPanel />
        </div>
      ) : (
        // Collapsed state: single Bell icon button that navigates to /alerts
        // WHY justify-center: center the icon in the 48px collapsed rail
        <Link
          href="/alerts"
          className="flex h-9 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors duration-0"
          aria-label="Alerts"
          title="Alerts"
        >
          <Bell className="h-[18px] w-[18px]" />
        </Link>
      )}

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
    </aside>
  );
}
