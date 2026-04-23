/**
 * components/shell/Sidebar.tsx — Left navigation rail
 *
 * WHY THIS EXISTS: Finance terminals have persistent navigation that lets users
 * switch between views without losing their current context. The sidebar shows
 * active state, watchlist prices, and recent alerts in a compact 56px-wide rail.
 *
 * WHY nav rail (not full sidebar with text labels):
 * Space is premium in a data-dense layout. Icons with tooltips (Bloomberg-style)
 * occupy less horizontal space, leaving more room for the main content area.
 * Users learn the icons quickly — they're standard finance app conventions.
 *
 * WHY watchlist sub-section: Traders check their watchlist constantly.
 * Putting it in the sidebar means it's always visible without a page visit.
 *
 * WHO USES IT: app/(app)/layout.tsx — rendered at the left of every protected page
 * DATA SOURCE: S9 GET /api/v1/watchlists → members with live batch quotes
 * DESIGN REFERENCE: PRD-0028 §6.5 Sidebar
 */

"use client";
// WHY "use client": Uses usePathname (routing), useQuery (data fetching),
// and hover state (Tooltip) — all require client rendering.

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  TrendingUp,
  Filter,
  Briefcase,
  LayoutGrid,
  Bell,
  MessageSquare,
  Settings,
  ChevronRight,
} from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPercentDirect, priceChangeClass } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { WatchlistMember } from "@/types/api";

// ── Navigation items ──────────────────────────────────────────────────────────

const NAV_ITEMS = [
  { href: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/instruments", icon: TrendingUp, label: "Instruments" },
  { href: "/screener", icon: Filter, label: "Screener" },
  { href: "/portfolio", icon: Briefcase, label: "Portfolio" },
  { href: "/workspace", icon: LayoutGrid, label: "Workspace" },
  { href: "/alerts", icon: Bell, label: "Alerts & News" },
  { href: "/chat", icon: MessageSquare, label: "Intelligence / Chat" },
] as const;

// BT-002 FIX: Removed /help link — no help page exists. Settings is the only
// bottom nav item. A help page can be added in a future wave if needed.
const BOTTOM_ITEMS = [
  { href: "/settings", icon: Settings, label: "Settings" },
] as const;

// ── Component ─────────────────────────────────────────────────────────────────

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { accessToken } = useAuth();

  // Fetch the first active watchlist for the sidebar price display
  // WHY staleTime 30s: watchlist changes infrequently; 30s freshness is fine
  const { data: watchlistsData } = useQuery({
    queryKey: ["watchlists-sidebar"],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    staleTime: 30_000,
  });

  // Get the first watchlist's members to display
  // WHY ?.[0]: getWatchlists returns Watchlist[] (array), not {watchlists: Watchlist[]}
  const firstWatchlist = watchlistsData?.[0];
  const memberIds = firstWatchlist?.members?.map((m: WatchlistMember) => m.entity_id) ?? [];

  // Fetch live quotes for watchlist members (batch for efficiency)
  const { data: quotesData } = useQuery({
    queryKey: ["watchlist-sidebar-quotes", memberIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(memberIds),
    enabled: memberIds.length > 0 && !!accessToken,
    refetchInterval: 30_000, // WHY 30s: sidebar prices are reference, not trading inputs
    staleTime: 0,
  });

  const quotes = quotesData?.quotes ?? {};

  return (
    // WHY w-14: 56px is the minimum width for icon-only nav that's still tap-friendly.
    // A wider sidebar would eat into the chart/data view area.
    <aside className="flex h-full w-14 flex-col border-r border-border bg-background" aria-label="Application navigation">
      {/* ── Primary nav ──────────────────────────────────────── */}
      <nav className="flex flex-1 flex-col gap-1 px-2 py-3" aria-label="Main navigation">
        {NAV_ITEMS.map(({ href, icon: Icon, label }) => {
          // WHY startsWith: /instruments/AAPL should also highlight the Instruments nav item
          const isActive = pathname === href || pathname.startsWith(href + "/");

          return (
            <Link
              key={href}
              href={href}
              title={label} // WHY title: serves as tooltip for icon-only nav
              className={cn(
                // WHY focus-visible:ring-*: keyboard users (Tab/Shift-Tab) must see
                // a clear focus indicator. ring-ring maps to #FFD60A (trading yellow) —
                // consistent with all other interactive elements. ring-offset-background
                // creates a 2px gap against #09090B so the yellow ring is clearly visible.
                // WHY rounded-[2px] not rounded-md: matches the new 2px radius system.
                // Active state treatment:
                // WHY bg-primary/10 not bg-primary/15: trading yellow (#FFD60A) is
                // higher-chroma than old amber; at /15 the tint was visually heavy/loud.
                // /10 gives a clear but restrained active background — the text-primary
                // yellow icon color carries the "active" signal, not the background fill.
                "group flex h-9 w-9 items-center justify-center rounded-[2px] transition-colors",
                "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
              aria-current={isActive ? "page" : undefined}
            >
              <Icon className="h-4 w-4" />
            </Link>
          );
        })}
      </nav>

      {/* ── Watchlist mini-section ────────────────────────────── */}
      {firstWatchlist && memberIds.length > 0 && (
        <div className="border-t border-border px-2 py-2">
          {/* Watchlist header — clicking opens full watchlist */}
          <button
            onClick={() => router.push("/portfolio?tab=watchlist")}
            className="flex w-full items-center justify-between px-1 py-0.5 text-muted-foreground hover:text-foreground"
            title="Open watchlist"
          >
            <span className="text-[10px] font-medium uppercase tracking-wider">WL</span>
            <ChevronRight className="h-3 w-3" />
          </button>

          {/* Watchlist members — show up to 5 in sidebar */}
          <div className="mt-1 space-y-1">
            {memberIds.slice(0, 5).map((entityId) => {
              const quote = quotes[entityId];
              const member = firstWatchlist.members?.find((m: WatchlistMember) => m.entity_id === entityId);

              return (
                <button
                  key={entityId}
                  onClick={() => router.push(`/instruments/${entityId}`)}
                  // WHY rounded-[2px]: consistent with 2px radius system; avoids
                  // Tailwind's `rounded` shorthand (4px default) which looks too soft
                  className="w-full rounded-[2px] px-1 py-0.5 text-left hover:bg-muted"
                  title={member?.name ?? entityId}
                >
                  {/* Symbol — truncated for sidebar width */}
                  <div className="truncate font-mono text-[10px] font-medium tabular-nums text-foreground">
                    {member?.ticker ?? entityId.slice(0, 6)}
                  </div>
                  {/* Price and change */}
                  {quote && (
                    <div
                      className={`font-mono text-[10px] tabular-nums ${priceChangeClass(quote.change_pct ?? null)}`}
                    >
                      {formatPercentDirect(quote.change_pct ?? null)}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Keyboard shortcut hint strip ─────────────────────── */}
      {/*
       * WHY THIS EXISTS: Bloomberg and tastytrade users expect keyboard-first
       * navigation. Making shortcuts discoverable directly in the sidebar
       * communicates "professional tool" and reduces the learning cliff for
       * new users. The strip is deliberately subtle (muted/50, text-[9px]) —
       * it is a hint, not a feature advertisement.
       *
       * WHY a 2×2 grid (not a single column): the sidebar is only 56px wide.
       * Stacking all 4 shortcuts vertically would require excessive height.
       * A 2×2 grid fits 4 shortcuts in ~2.5 lines of height while keeping
       * each badge legible at text-[9px] font-mono.
       *
       * WHY title attr (not visible labels): there is no horizontal room for
       * full labels like "Dashboard". The title attr surfaces as a native
       * browser tooltip on hover, providing the full action description
       * without occupying permanent space.
       *
       * WHY rounded-[2px]: consistent with 2px radius system; these key
       * badges are structural affordances, not decorative pills.
       */}
      <div
        className="border-t border-border px-1.5 py-2"
        aria-label="Keyboard shortcuts"
      >
        <div className="grid grid-cols-2 gap-0.5">
          {/* g+d — navigate to Dashboard */}
          <span
            title="g then d — Go to Dashboard"
            className="inline-flex items-center justify-center rounded-[2px] bg-muted/50 px-0.5 py-0.5 font-mono text-[9px] leading-none text-muted-foreground/50 select-none"
          >
            g+d
          </span>
          {/* g+w — navigate to Workspace */}
          <span
            title="g then w — Go to Workspace"
            className="inline-flex items-center justify-center rounded-[2px] bg-muted/50 px-0.5 py-0.5 font-mono text-[9px] leading-none text-muted-foreground/50 select-none"
          >
            g+w
          </span>
          {/* g+c — navigate to Companies (instruments list) */}
          <span
            title="g then c — Go to Companies"
            className="inline-flex items-center justify-center rounded-[2px] bg-muted/50 px-0.5 py-0.5 font-mono text-[9px] leading-none text-muted-foreground/50 select-none"
          >
            g+c
          </span>
          {/* ⌘K — open GlobalSearch command palette */}
          <span
            title="⌘K — Open search / command palette"
            className="inline-flex items-center justify-center rounded-[2px] bg-muted/50 px-0.5 py-0.5 font-mono text-[9px] leading-none text-muted-foreground/50 select-none"
          >
            ⌘K
          </span>
        </div>
      </div>

      {/* ── Bottom nav (Settings, Help) ───────────────────────── */}
      <nav className="flex flex-col gap-1 border-t border-border px-2 py-3" aria-label="Settings">
        {BOTTOM_ITEMS.map(({ href, icon: Icon, label }) => {
          const isActive = pathname === href || pathname.startsWith(href + "/");

          return (
            <Link
              key={href}
              href={href}
              title={label}
              className={cn(
                // WHY focus-visible:ring-*: same keyboard accessibility requirement as NAV_ITEMS.
                // All focusable elements in the sidebar must show the trading-yellow ring on focus.
                // WHY rounded-[2px]: consistent with NAV_ITEMS and the new 2px radius system.
                "flex h-9 w-9 items-center justify-center rounded-[2px] transition-colors",
                "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
