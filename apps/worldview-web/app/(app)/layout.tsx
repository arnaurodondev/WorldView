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

import { Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { useIdleLock } from "@/hooks/useIdleLock";
import { PreferencesProvider } from "@/contexts/PreferencesContext";
// W1.1 F-002 — active-portfolio selection shared between the
// PortfolioSwitcher chip (writer) and usePortfolioMetrics (reader).
import { ActivePortfolioProvider } from "@/contexts/ActivePortfolioContext";
import { TopBar } from "@/components/shell/TopBar";
import { CollapsibleSidebar } from "@/components/shell/CollapsibleSidebar";
import { FlashOverlay } from "@/components/shell/FlashOverlay";
import { StatusBar } from "@/components/shell/StatusBar";
import { AskAiPanel } from "@/components/shell/AskAiPanel";
// PLAN-0059 W1 (2026-04-30) — global hotkey infrastructure. HotkeyProvider
// holds the scope stack; GlobalHotkeyBindings registers app-wide chords AND
// mounts the document-level keydown listener; HotkeyCheatSheet is the `?` overlay.
// Together these close F-LAYOUT-001 (StatusBar advertised six chord shortcuts
// with no listener wired). The StatusBar now reads chord hints from the same
// registry — structurally impossible to advertise an unwired chord.
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { GlobalHotkeyBindings } from "@/components/shell/GlobalHotkeyBindings";
import { HotkeyCheatSheet } from "@/components/shell/HotkeyCheatSheet";
// PLAN-0059 B-6 — fixed-position banner that detects new build deploys and
// prompts the user to reload. Polls /api/version every 60s; user-driven reload.
import { ForceUpdateBanner } from "@/components/shell/ForceUpdateBanner";
// PLAN-0053 Wave G — feedback widget mounted at the shell so every
// authenticated page exposes the floating Send-Feedback button + modal.
import { FeedbackButton } from "@/components/feedback/FeedbackButton";
// PLAN-0053 Wave G T-G-7-08 — global NPS prompt host. Trigger sites
// dispatch a CustomEvent; this host decides whether to actually pop the
// modal based on eligibility.
import { NPSPromptHost } from "@/components/feedback/NPSPromptHost";
// PLAN-0052 Wave E T-E-5-08 — translates `?feedback=<kind>&page=<X>` URL
// query params into the open-feedback CustomEvent the FeedbackButton
// listens for. Wrapped in <Suspense> below because useSearchParams must
// be inside a Suspense boundary to avoid forcing the entire shell into
// fully-dynamic rendering on static-eligible routes.
import { FeedbackDeepLinkHandler } from "@/components/feedback/FeedbackDeepLinkHandler";
import { WorkspaceProvider } from "@/contexts/WorkspaceContext";
import { useAlertStream } from "@/contexts/AlertStreamContext";
import { createGateway } from "@/lib/gateway";
// WHY qk: replaces the inline ["layout-pending-alert-count"] literal with the
// factory so tests and the AlarmsPanel invalidation share the same key shape.
import { qk } from "@/lib/query/keys";
import { usePortfolioMetrics } from "@/hooks/usePortfolioMetrics";
// PLAN-0059-C C-4: corruption-safe localStorage wrapper. Replaces six
// hand-rolled `typeof window === "undefined"` guards + `parseInt` + NaN-fallback
// branches in this file. Stored values are validated on read; corrupt values
// fall back to the default instead of crashing or producing NaN widths.
import {
  safeStorage,
  isBoolean,
  isFiniteNumber,
} from "@/lib/storage/safe-storage";

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
  // PRD-0089 W1 §4.11 / C-22 — when the tab is hidden we pause every
  // shell-owned refetchInterval. The TanStack default is overridden via
  // queryClient.setDefaultOptions and restored on visibilityState=visible.
  // This is the W1 reading of the plan's "useIdleLock().locked" predicate:
  // visible-tab activity drives the gate so background tabs don't keep
  // billing S9 for quote refreshes. Future work can promote this to a
  // first-class field on the useIdleLock hook.
  const queryClient = useQueryClient();
  const lastRefetchOverrideRef = useRef<unknown>(undefined);

  // PLAN-0059 I-6: idle-lock — auto-redirect to /login after 15 minutes of
  // inactivity, preserving the user's current path via ?next=. Disabled
  // while we don't have a session yet (login page must not lock itself).
  // Multi-tab aware via BroadcastChannel — activity in any tab keeps every
  // tab unlocked.
  useIdleLock({ enabled: isAuthenticated });

  useEffect(() => {
    if (typeof document === "undefined") return;
    function onVisibilityChange() {
      const defaults = queryClient.getDefaultOptions();
      if (document.visibilityState === "hidden") {
        // Stash the current refetchInterval so we can restore the user's
        // configured value when the tab returns to the foreground.
        lastRefetchOverrideRef.current = defaults.queries?.refetchInterval;
        queryClient.setDefaultOptions({
          ...defaults,
          queries: { ...defaults.queries, refetchInterval: false },
        });
      } else if (document.visibilityState === "visible") {
        queryClient.setDefaultOptions({
          ...defaults,
          queries: {
            ...defaults.queries,
            // `undefined` lets individual queries fall back to their own
            // refetchInterval setting (which is how the codebase actually
            // configures them — per-query, not via default).
            refetchInterval: lastRefetchOverrideRef.current as undefined,
          },
        });
        lastRefetchOverrideRef.current = undefined;
      }
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [queryClient]);

  // WHY REST pending count: the WebSocket unreadCount only tracks alerts received
  // during this browser session — it resets to 0 on page refresh. The TopBar badge
  // must show the persistent DB pending count so it matches the AlarmsPanel sidebar.
  // We poll every 60s (low frequency — this is layout-level, not a critical widget).
  const { data: pendingAlertsData } = useQuery({
    // WHY qk.alerts.pendingCount(): factory wrapper for ["layout-pending-alert-count"].
    // The layout polls this lightweight count-only query at 60s; the full AlarmsPanel
    // list uses qk.alerts.list() — separate keys prevent the badge poll from
    // displacing the richer panel data from cache.
    queryKey: qk.alerts.pendingCount(),
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

  // PLAN-0071 P3-2: GlobalSearch "Open Analyst Panel" quick action dispatches
  // this event so GlobalSearch stays decoupled from layout state.
  useEffect(() => {
    function handleOpenAiPanel() { setAskAiOpen(true); }
    window.addEventListener("worldview:open-ai-panel", handleOpenAiPanel);
    return () => window.removeEventListener("worldview:open-ai-panel", handleOpenAiPanel);
  }, []);

  const handleAskAiClose = useCallback(() => {
    setAskAiOpen(false);
    // requestAnimationFrame ensures the trigger is in the DOM and focusable
    // before we attempt to focus it. Direct focus() inside the same tick
    // sometimes misses because React has not yet committed the unmount of
    // the panel + the panel's autoFocus may still hold the focus token.
    requestAnimationFrame(() => askAiButtonRef.current?.focus());
  }, []);

  // PLAN-0059-C C-4: safeStorage handles SSR + corruption-fallback in one line.
  // Lazy initializer still used so the read happens once at mount, not on every
  // render. True (expanded) is the default so first-time users see full labels.
  const [sidebarExpanded, setSidebarExpanded] = useState<boolean>(() =>
    safeStorage.get(SIDEBAR_STORAGE_KEY, isBoolean, true),
  );

  /**
   * WHY persist the drag width separately from the expanded boolean:
   * If the user drags to 280px, collapses, then re-expands, they expect to return
   * to 280px — not reset to 220px. Storing width independently achieves this.
   * isFiniteNumber rejects NaN/Infinity so a corrupt value can't produce a
   * zero-width sidebar (BP-180-class corruption-safety).
   */
  const [sidebarWidth, setSidebarWidth] = useState<number>(() =>
    safeStorage.get(SIDEBAR_WIDTH_KEY, isFiniteNumber, DEFAULT_SIDEBAR_WIDTH),
  );

  // Persist sidebar state whenever the user toggles it
  function handleSidebarToggle() {
    setSidebarExpanded((prev) => {
      const next = !prev;
      safeStorage.set(SIDEBAR_STORAGE_KEY, next);
      return next;
    });
  }

  /**
   * handleSidebarResize — called by CollapsibleSidebar on every mousemove during drag.
   *
   * WHY persist on every move (not just mouseup): if the page refreshes or the tab
   * is closed mid-drag, the last stored width is still close to the final position.
   * The performance cost is negligible — JSON.stringify of a number is O(1) and
   * does not cause a React re-render on its own.
   */
  function handleSidebarResize(w: number) {
    setSidebarWidth(w);
    safeStorage.set(SIDEBAR_WIDTH_KEY, w);
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
          <p className="text-[14px] text-muted-foreground">Initializing session…</p>
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

  // Authenticated: render the protected shell layout wrapped in HotkeyProvider +
  // WorkspaceProvider.
  // PLAN-0059 W1: HotkeyProvider must wrap WorkspaceProvider so the workspace
  // can later push "page" / "table" scopes from inside its tree. The hotkey
  // infrastructure components (GlobalHotkeyBindings + HotkeyCheatSheet) live
  // INSIDE the provider — without that they'd throw "missing provider".
  return (
    // PLAN-0059 I-4: PreferencesProvider supplies density/currency/timezone to
    // every consumer via usePreferences(). Mounted at the layout level so all
    // (app)/* pages share the same instance. Persists to localStorage today;
    // S1 backend persistence is a deferred follow-up.
    //
    // QA-iter1: this provider must mount INSIDE ApiClientProvider once the
    // backend swap lands. ApiClientProvider currently lives in
    // `app/providers.tsx` (root layout), an ancestor of this (app)/layout —
    // the layering is satisfied today by accident. When converting to API
    // persistence, keep this mount but document the dependency so a future
    // refactor doesn't relocate ApiClientProvider below us.
    <PreferencesProvider>
    <ActivePortfolioProvider>
    <HotkeyProvider>
      {/* GlobalHotkeyBindings has no DOM output — registers global chords
          (g d/p/i/s/w/a/n/c/, plus mod+b) AND mounts the document keydown
          listener via useChordHotkeys. Mounted FIRST so chords are live before
          children render. */}
      <GlobalHotkeyBindings onToggleSidebar={handleSidebarToggle} />

      {/* HotkeyCheatSheet — `?` overlay; auto-derives content from the registry. */}
      <HotkeyCheatSheet />

      <WorkspaceProvider>
        {/* WHY flex flex-col h-screen: pins the layout to viewport height so the
         * main content area scrolls independently without moving the TopBar/Sidebar.
         *
         * PRD-0089 W1 §4.11 / C-27 — Skip-to-content link is the first
         * focusable child of the shell. `sr-only focus:not-sr-only` makes
         * it invisible until a keyboard user tabs to it; on focus it
         * surfaces at the top-left as a focusable anchor that jumps to the
         * `<main id="main">` region defined below. This is the WCAG 2.4.1
         * Skip Mechanism. */}
        <div className="flex h-screen flex-col bg-background">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[60] focus:bg-background focus:px-2 focus:py-1 focus:text-[11px] focus:font-mono focus:text-foreground focus:outline focus:outline-2 focus:outline-primary"
        >
          Skip to main content
        </a>

        {/* PRD-0089 W1 §4.11 / C-25 — ForceUpdateBanner is rendered ABOVE
            the TopBar as a 24px sticky notice. When inactive the component
            returns null so the shell takes its full viewport height. */}
        <ForceUpdateBanner />
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

          {/* Main content area — fills remaining width, scrolls vertically.
              PRD-0089 W1 §4.11 / C-27 — explicit id="main" is the target of
              the skip-to-content anchor above. */}
          <main id="main" className="flex-1 overflow-y-auto">
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

        {/* PLAN-0052 Wave E T-E-5-08 — deep-link query-param translator.
            Reads ?feedback=<kind>&page=<X> on every navigation and fires
            the open-feedback event the button listens for. Suspense is
            required because useSearchParams suspends during route
            transitions; wrapping it here keeps the rest of the shell
            statically renderable. */}
        <Suspense fallback={null}>
          <FeedbackDeepLinkHandler />
        </Suspense>
      </div>
      </WorkspaceProvider>
    </HotkeyProvider>
    </ActivePortfolioProvider>
    </PreferencesProvider>
  );
}
