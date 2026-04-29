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

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { TopBar } from "@/components/shell/TopBar";
import { CollapsibleSidebar } from "@/components/shell/CollapsibleSidebar";
import { FlashOverlay } from "@/components/shell/FlashOverlay";
import { StatusBar } from "@/components/shell/StatusBar";
import { AskAiPanel } from "@/components/shell/AskAiPanel";
// PLAN-0053 Wave G — feedback widget mounted at the shell so every
// authenticated page exposes the floating Send-Feedback button + modal.
import { FeedbackButton } from "@/components/feedback/FeedbackButton";
// PLAN-0053 Wave G T-G-7-08 — global NPS prompt host. Trigger sites
// dispatch a CustomEvent; this host decides whether to actually pop the
// modal based on eligibility.
import { NPSPromptHost } from "@/components/feedback/NPSPromptHost";
import { WorkspaceProvider } from "@/contexts/WorkspaceContext";
import { useAlertStream } from "@/contexts/AlertStreamContext";
import { createGateway } from "@/lib/gateway";
import { usePortfolioMetrics } from "@/hooks/usePortfolioMetrics";

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

  // PLAN-0050 T-A-1-02: portfolio rail values + 15s refetch are now owned by
  // hooks/usePortfolioMetrics so any TopBar consumer (and a future account
  // sheet) gets the same values from the same TanStack query cache.
  const { portfolioValue, dailyPnl, unrealisedPnl } = usePortfolioMetrics();

  // ── Ask AI panel open/close (PLAN-0050 T-A-1-03) ─────────────────────────
  // WHY layout-level state: the AskAiPanel is fixed-positioned (bottom-right)
  // and must mount above the shell's overflow context. The TopBar holds the
  // trigger button but only forwards the toggle callback — see TopBarProps.
  const [askAiOpen, setAskAiOpen] = useState(false);
  // F-QA-05 fix: keep a ref to the AskAi trigger so we can restore focus
  // when the panel closes. WCAG 2.4.3 requires focus to return to the
  // originating control after a transient overlay closes; without this
  // refocus, focus falls back to <body> and keyboard users lose context.
  const askAiButtonRef = useRef<HTMLButtonElement | null>(null);
  const handleAskAiOpen = useCallback(() => setAskAiOpen(true), []);
  const handleAskAiClose = useCallback(() => {
    setAskAiOpen(false);
    // requestAnimationFrame ensures the trigger is in the DOM and focusable
    // before we attempt to focus it. Direct focus() inside the same tick
    // sometimes misses because React has not yet committed the unmount of
    // the panel + the panel's autoFocus may still hold the focus token.
    requestAnimationFrame(() => askAiButtonRef.current?.focus());
  }, []);

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
          onAskAi={handleAskAiOpen}
          askAiOpen={askAiOpen}
          askAiButtonRef={askAiButtonRef}
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

        {/* AskAiPanel — floating mini-chat panel (PLAN-0050 T-A-1-03).
            WHY rendered here at layout root: the panel is fixed bottom-right
            and must escape any deeper overflow:hidden ancestor (it sits above
            page content but below FlashOverlay). Conditional mount keeps the
            SSE EventSource off the page while the panel is closed — opening
            it is what initiates the connection. */}
        {askAiOpen && <AskAiPanel onClose={handleAskAiClose} />}

        {/* PLAN-0053 Wave G — fixed bottom-right feedback widget.
            WHY here (not inside a page): the button + modal are global —
            available from every authenticated route without each page
            having to mount its own. The component self-guards on auth
            and renders nothing for unauthenticated visitors. */}
        <FeedbackButton />

        {/* PLAN-0053 Wave G T-G-7-08 — NPS prompt host. Listens for
            `worldview:request-nps` CustomEvents and opens the prompt iff
            the user is eligible (≥3 sessions, no submission in 30d, none
            this quarter). */}
        <NPSPromptHost />
      </div>
    </WorkspaceProvider>
  );
}
