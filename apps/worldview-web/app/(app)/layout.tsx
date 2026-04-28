/**
 * app/(app)/layout.tsx — Protected route layout guard + shell
 *
 * WHY THIS EXISTS: All authenticated pages live under the (app)/ route group.
 * This layout:
 * 1. Guards against unauthenticated access (redirects to /login)
 * 2. Renders the persistent shell (TopBar + CollapsibleSidebar) around page content
 * 3. Provides WorkspaceContext for workspace state management across the app
 *
 * WHY A ROUTE GROUP (app): Next.js route groups (parentheses in folder name)
 * let us apply a layout to a set of pages without adding the group name to the URL.
 * So `app/(app)/dashboard/page.tsx` maps to the URL `/dashboard` — clean URLs
 * without the "app" prefix showing up to users.
 *
 * WHY CLIENT COMPONENT: Auth state lives in React context (client-side only).
 * We cannot read auth state in a Server Component. The redirect must happen
 * client-side because the access token is never sent to the server
 * (security requirement: token in React state only, never in cookies or headers
 * that the server renders into HTML — PRD-0028 §8.1).
 *
 * WHO USES IT: All protected pages — Dashboard, Instrument Detail, Screener,
 * Portfolio, Chat, Alerts, Workspace, Settings.
 * DATA SOURCE: AuthContext (React state)
 * DESIGN REFERENCE: PRD-0031 §4.1 Shell Layout, §4.2 CollapsibleSidebar
 */

"use client";
// WHY "use client": Reads AuthContext via useAuth() and manages sidebar state
// (which reads from localStorage — browser-only). Server Components cannot
// access React context or browser APIs.

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { TopBar } from "@/components/shell/TopBar";
import { CollapsibleSidebar } from "@/components/shell/CollapsibleSidebar";
import { FlashOverlay } from "@/components/shell/FlashOverlay";
import { StatusBar } from "@/components/shell/StatusBar";
import { WorkspaceProvider } from "@/contexts/WorkspaceContext";
import { useAlertStream } from "@/contexts/AlertStreamContext";
import { createGateway } from "@/lib/gateway";

// ── Constants ─────────────────────────────────────────────────────────────────

const SIDEBAR_STORAGE_KEY = "worldview-sidebar-expanded";

/**
 * WHY a separate key for width: expanded/collapsed is a boolean toggle (two
 * states) while the drag width is a continuous number. Separating them means
 * collapsing does not reset the remembered expanded width, so when the user
 * re-expands the sidebar it restores to their last manual drag position.
 */
const SIDEBAR_WIDTH_KEY = "worldview-sidebar-width";

/** Default expanded width matches the original fixed 220px design */
const DEFAULT_SIDEBAR_WIDTH = 220;

// ── Layout component ──────────────────────────────────────────────────────────

interface AppLayoutProps {
  children: ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
  const { isLoading, isAuthenticated, accessToken } = useAuth();
  const router = useRouter();
  const { unreadCount } = useAlertStream();

  // WHY REST pending count: the WebSocket unreadCount only tracks alerts received
  // during this browser session — it resets to 0 on page refresh. The TopBar badge
  // must show the persistent DB pending count so it matches the AlarmsPanel sidebar.
  // We poll every 60s (low frequency — this is layout-level, not a critical widget).
  const { data: pendingAlertsData } = useQuery({
    queryKey: ["layout-pending-alert-count"],
    queryFn: () => createGateway(accessToken).getPendingAlerts({ limit: 1 }),
    enabled: !!accessToken && isAuthenticated,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
  // WHY Math.max: show the larger of REST total vs WS session count.
  // During active sessions new WS alerts may arrive before the 60s REST poll.
  const badgeCount = Math.max(pendingAlertsData?.total ?? 0, unreadCount);

  // Portfolio NAV for TopBar — uses the same query keys as PortfolioSummary so
  // TanStack Query deduplicates the HTTP calls (no extra network overhead).
  // WHY layout-level: TopBar is persistent across page navigations; the value
  // must not flicker on each route change.
  const { data: portfoliosData } = useQuery({
    queryKey: ["portfolios"],
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken && isAuthenticated,
    staleTime: 60_000,
  });
  const firstPortfolioId = portfoliosData?.[0]?.portfolio_id;
  const { data: holdingsResp } = useQuery({
    queryKey: ["holdings", firstPortfolioId],
    queryFn: () => createGateway(accessToken).getHoldings(firstPortfolioId!),
    enabled: !!accessToken && isAuthenticated && !!firstPortfolioId,
    staleTime: 30_000,
  });
  const navInstrumentIds = holdingsResp?.holdings.map((h) => h.instrument_id) ?? [];
  const { data: navQuotes } = useQuery({
    queryKey: ["holdings-quotes", navInstrumentIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(navInstrumentIds),
    enabled: navInstrumentIds.length > 0 && !!accessToken && isAuthenticated,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
  // Compute total NAV: sum(quantity × live_price) for all holdings
  const portfolioValue: number | null = holdingsResp?.holdings.length
    ? holdingsResp.holdings.reduce((sum, h) => {
        const quote = navQuotes?.quotes?.[h.instrument_id];
        const price = quote?.price ?? h.average_cost;
        return sum + price * h.quantity;
      }, 0)
    : null;

  // ── Day P&L + Unrealised P&L for TopBar (PLAN-0048 F-121 fix) ─────────────
  // WHY computed here (in the layout, not TopBar): the TopBar is a thin
  // presentational component — all financial computations live in the route
  // layer that already has portfolio data fetched. The layout already loads
  // holdings + navQuotes for portfolioValue, so we can derive both P&L
  // numbers from the same data without an extra network round-trip.
  //
  // WHY the TopBar audit (F-121) flagged this: the TopBar component was
  // designed to render Day P&L / Total P&L slots when both props are
  // non-null, but the layout never computed and forwarded them. As a result
  // every viewport showed only `PORT $42K` next to the bell — the rail's
  // most important fields were silently absent.
  //
  // Day P&L: sum across all holdings of (per-share daily price change × qty).
  // We require the quote AND its `change` field to be defined; if any quote is
  // still loading (q == null) the contribution is 0 — better to under-report
  // briefly during the 30s navQuotes refetch than to flicker between values.
  // We pass `null` only when there are no holdings — the TopBar then renders
  // its label slot empty rather than "$0.00", which is technically a value
  // and would mislead the user into thinking the day was flat.
  const dailyPnl: number | null = holdingsResp?.holdings.length
    ? holdingsResp.holdings.reduce((sum, h) => {
        const q = navQuotes?.quotes?.[h.instrument_id];
        // Treat missing quote / missing change as 0 contribution; once the
        // quote refetch resolves, the value snaps to the correct sum.
        return sum + (q?.change ?? 0) * h.quantity;
      }, 0)
    : null;

  // Total P&L (a.k.a. Unrealised): mark-to-market value − total cost basis.
  // WHY null when portfolioValue is null: without a current value we cannot
  // form a meaningful difference vs cost; the TopBar slot then stays empty.
  // WHY use h.average_cost (not q.price): cost basis is locked at purchase;
  // multiplying by current qty against the original avg cost is the textbook
  // unrealised P&L formula.
  const totalCost: number = holdingsResp?.holdings.reduce(
    (s, h) => s + h.average_cost * h.quantity,
    0,
  ) ?? 0;
  const unrealisedPnl: number | null =
    portfolioValue != null ? portfolioValue - totalCost : null;

  // WHY lazy initializer: reads localStorage once at mount, not on every render.
  // True (expanded) is the default so first-time users see the full labeled sidebar.
  // typeof window guard makes this safe during Next.js SSR pre-render.
  const [sidebarExpanded, setSidebarExpanded] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY);
    // WHY null check: first visit has no stored value — default to expanded (true)
    return stored === null ? true : stored === "true";
  });

  /**
   * WHY persist the drag width separately from the expanded boolean:
   * If the user drags to 280px, collapses, then re-expands, they expect to return
   * to 280px — not reset to 220px. Storing width independently achieves this.
   * The lazy initializer reads localStorage once at mount (SSR-safe with typeof guard).
   */
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    if (typeof window === "undefined") return DEFAULT_SIDEBAR_WIDTH;
    const stored = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    if (stored === null) return DEFAULT_SIDEBAR_WIDTH;
    const parsed = parseInt(stored, 10);
    // WHY NaN guard: if the stored value is corrupt (e.g. "undefined") parseInt
    // returns NaN — fall back to the default to avoid a zero-width sidebar.
    return isNaN(parsed) ? DEFAULT_SIDEBAR_WIDTH : parsed;
  });

  // Persist sidebar state whenever the user toggles it
  function handleSidebarToggle() {
    setSidebarExpanded((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
      }
      return next;
    });
  }

  /**
   * handleSidebarResize — called by CollapsibleSidebar on every mousemove during drag.
   *
   * WHY persist on every move (not just mouseup): if the page refreshes or the tab
   * is closed mid-drag, the last stored width is still close to the final position.
   * The performance cost is negligible — localStorage.setItem is synchronous but
   * O(1) and does not cause a React re-render on its own.
   */
  function handleSidebarResize(w: number) {
    setSidebarWidth(w);
    if (typeof window !== "undefined") {
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(w));
    }
  }

  useEffect(() => {
    // WHY check isLoading first: On first mount, AuthProvider fires a POST
    // /auth/refresh check. Until that resolves, isAuthenticated is false by default.
    // If we redirect immediately on false, we'd kick out users mid-session refresh.
    // Only redirect after isLoading === false confirms the auth check is complete.
    if (!isLoading && !isAuthenticated) {
      // Preserve the attempted URL so login can redirect back after success
      // WHY encode the path: the redirect_to param may contain slashes and query strings
      const currentPath = window.location.pathname + window.location.search;
      const redirectTo = encodeURIComponent(currentPath);
      router.replace(`/login?redirect_to=${redirectTo}`);
    }
  }, [isLoading, isAuthenticated, router]);

  // WHY show loading state: If we render children before auth check resolves,
  // protected components would fire S9 API calls without a valid token (→ 401s),
  // show blank panels, or flash incorrect states before redirecting.
  // A minimal loading screen prevents all of this.
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          {/* Animated ring spinner — minimal, no branding needed at this stage */}
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-primary" />
          <p className="text-sm text-muted-foreground">Initializing session…</p>
        </div>
      </div>
    );
  }

  // WHY render null when not authenticated: The useEffect above triggers
  // router.replace() asynchronously. There is a brief render cycle between
  // isLoading becoming false and the navigation completing. Rendering null
  // (instead of children) prevents a flash of protected content.
  if (!isAuthenticated) {
    return null;
  }

  // Authenticated: render the protected shell layout wrapped in WorkspaceProvider
  return (
    // WHY WorkspaceProvider at layout level: workspace state must be accessible
    // from WorkspaceTabs (workspace/page.tsx) AND potentially from the sidebar
    // (e.g. workspace name in TopBar). Providing at layout level avoids re-mounting
    // the context on page navigation within the (app) route group.
    <WorkspaceProvider>
      {/* WHY flex flex-col h-screen: pins the layout to viewport height so the
       * main content area scrolls independently without moving the TopBar/Sidebar */}
      <div className="flex h-screen flex-col bg-background">
        <TopBar
          unreadAlerts={badgeCount}
          portfolioValue={portfolioValue}
          dailyPnl={dailyPnl}
          unrealisedPnl={unrealisedPnl}
        />

        {/* WHY flex flex-1 overflow-hidden: the sidebar and main area share the
         * remaining height below the TopBar, each scrolling independently. */}
        <div className="flex flex-1 overflow-hidden">
          {/*
           * WHY pass width + onResize: CollapsibleSidebar uses these to implement the
           * drag-resize handle (introduced in the sidebar resizable enhancement).
           * When expanded=false the sidebar ignores width and renders at 48px.
           */}
          <CollapsibleSidebar
            expanded={sidebarExpanded}
            onToggle={handleSidebarToggle}
            width={sidebarWidth}
            onResize={handleSidebarResize}
          />

          {/* Main content area — fills remaining width, scrolls vertically */}
          {/* WHY overflow-y-auto not overflow-auto: prevent horizontal scroll on
           * the main content area (horizontal scroll should be per-panel, not global) */}
          <main className="flex-1 overflow-y-auto">
            {children}
          </main>
        </div>

        {/* Status bar — Bloomberg-inspired bottom bar with keyboard hints + connection status */}
        {/* WHY before FlashOverlay: StatusBar is a normal flow element (24px fixed height).
         * FlashOverlay uses position:fixed so it renders above everything at z-[9999] —
         * DOM order doesn't affect its visual stacking, but keeping it last in the tree
         * makes the layout structure clear: flow elements first, overlays after. */}
        <StatusBar />

        {/* FlashOverlay — full-screen critical alert overlay (z-[9999], above everything) */}
        {/* WHY outside the flex layout: overlay must be position:fixed, not flow-positioned */}
        <FlashOverlay />
      </div>
    </WorkspaceProvider>
  );
}
