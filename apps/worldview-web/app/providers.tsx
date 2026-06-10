/**
 * app/providers.tsx — Client-side provider tree
 *
 * "use client" — WHY: QueryClientProvider and AuthProvider both use React context
 * which requires client-side rendering. Separating providers from layout.tsx
 * keeps the root layout as a pure Server Component (better performance, proper
 * metadata generation) while still providing client state to all child components.
 *
 * WHO USES IT: app/layout.tsx wraps all children with this.
 * DATA SOURCE: No external data — sets up React context trees only.
 * DESIGN REFERENCE: PRD-0028 §6.4 Frontend App Structure
 */

"use client";

import * as Sentry from "@sentry/nextjs";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";
// PLAN-0059 C-6: nuqs URL-state adapter. The Next.js App-Router adapter wires
// useQueryState* hooks into Next's router so back/forward buttons work and
// deep-links round-trip without the page authors writing any router glue.
// Mounted at the very top of the tree so any descendant (sidebar, modal,
// chart) can adopt URL-backed state without further wiring.
import { NuqsAdapter } from "nuqs/adapters/next/app";
// AG Grid module registration — must happen exactly once before any AgGridReact
// renders. Placing it here (inside the "use client" providers bundle, module-level)
// guarantees it runs before the first AgGridBase mount regardless of which page
// the user lands on. AllCommunityModule includes all Community features (sorting,
// filtering, column groups, etc.) without requiring an Enterprise license.
// WHY not in AgGridBase.tsx: registerModules is designed to be called once;
// calling it inside a component render would fire on every mount.
import { ModuleRegistry, AllCommunityModule } from "ag-grid-community";
ModuleRegistry.registerModules([AllCommunityModule]);

import { AuthProvider } from "@/contexts/AuthContext";
import { AlertStreamProvider } from "@/contexts/AlertStreamContext";
// PLAN-0059-C C-3: ApiClientProvider memoises createGateway(accessToken) so
// the gateway is constructed once per token (not once per queryFn call).
// Must be INSIDE AuthProvider (reads accessToken) and INSIDE
// QueryClientProvider (so useAuthedQuery has the cache).
import { ApiClientProvider } from "@/lib/api-client";
// PLAN-0065 T-D-02: Fallback shown by Sentry.ErrorBoundary when an unhandled
// render error propagates to the root of the React tree.
import { GlobalErrorFallback } from "@/components/sentry/GlobalErrorFallback";

// WHY useState for QueryClient (not module-level singleton):
// In Next.js App Router, module-level singletons are shared across ALL requests
// on the server. A QueryClient per-request (via useState) ensures cache isolation
// between different users. useState initializes once per component instance.
//
// The defaults below are the platform-wide cache policy — documented in
// DESIGN_SYSTEM.md §9 and pinned by __tests__/query-client-defaults.test.ts
// (a source-contract test — rendering/importing the full provider tree in a
// unit test would drag in the Sentry SDK and every context provider).
function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // WHY 30s staleTime: prevents refetching on every component mount.
        // Finance data changes infrequently enough that 30s staleness is fine
        // for most queries. Individual queries override this where needed
        // (e.g., quotes use 5s staleTime).
        staleTime: 30 * 1000,

        // WHY retry 1: API failures in finance apps should be surfaced quickly.
        // Retrying 3 times (default) adds 3+ seconds of delay before showing
        // error state, which is unacceptable for a Bloomberg-grade terminal.
        retry: 1,

        // WHY refetchOnWindowFocus: true by default in TanStack Query.
        // Useful for finance: re-fetching prices when user switches back to tab.
        // Individual queries can override to false for cached/slow data.
        refetchOnWindowFocus: true,

        // gcTime intentionally left at the TanStack default (5 min): unmounted
        // query data survives 5 minutes so tab-switching within the terminal
        // re-renders instantly from cache. Don't raise it globally — quote
        // data has a 22ms-row × thousands-of-instruments footprint.
      },
      mutations: {
        // WHY retry 0 (explicit, Round-4 hardening): mutations are writes —
        // auto-retrying a write that may have partially succeeded risks
        // duplicate orders/alerts/watchlist entries. 0 is TanStack's default,
        // but we pin it explicitly so a library default change can never
        // silently introduce write retries. Surfaces that KNOW a mutation is
        // idempotent may override per-call.
        retry: 0,
      },
    },
  });
}

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  // useState ensures QueryClient is created once per component instance
  // and is stable across re-renders (not recreated on parent re-render)
  const [queryClient] = useState(() => makeQueryClient());

  return (
    // PLAN-0065 T-D-02: Sentry.ErrorBoundary is the outermost wrapper.
    //
    // WHY OUTERMOST: any unhandled render error inside ANY provider or page
    // component is caught here. If it were inside QueryClientProvider, errors
    // from the auth layer would escape. Outermost = maximum coverage.
    //
    // WHY Sentry.ErrorBoundary vs React's built-in error.tsx:
    // Next.js's error.tsx catches errors at the route segment level and shows
    // a "Try again" button. Sentry.ErrorBoundary runs BEFORE that (the outer
    // catch) and also sends the error to Sentry with a full stack trace +
    // React component tree context. The two are complementary — error.tsx
    // handles per-route errors cleanly; this handles catastrophic failures
    // where the entire provider tree collapses.
    //
    // WHEN DISABLED: if NEXT_PUBLIC_SENTRY_DSN is empty (""), the SDK is
    // in disabled mode — Sentry.ErrorBoundary still catches errors and renders
    // the fallback, but does NOT send them to Sentry. Fallback UX works in dev.
    <Sentry.ErrorBoundary fallback={<GlobalErrorFallback />}>
    {/* C-6: NuqsAdapter wraps everything else so any component in the tree
        can call useQueryState/useQueryStates without further provider
        configuration. The adapter does NOT render any DOM — it only wires
        nuqs's internals to Next.js router events. */}
    <NuqsAdapter>
    {/* WHY QueryClientProvider wraps AuthProvider: Auth state depends on React Query
        only indirectly (via the gateway client), but placing QueryClient at the top
        ensures any future auth-related queries (e.g., user profile refresh) have access.
        AuthProvider must be INSIDE QueryClientProvider for this reason. */}
    <QueryClientProvider client={queryClient}>
      {/* AuthProvider: manages OIDC session state (accessToken, user, isAuthenticated).
          Must wrap all children so protected layouts can read auth state via useAuth(). */}
      <AuthProvider>
        {/* ApiClientProvider: memoises createGateway(accessToken). Mounts
            BEFORE AlertStreamProvider so any future query inside the alert
            stream can use useApiClient() / useAuthedQuery(). */}
        <ApiClientProvider>
          {/* AlertStreamProvider: opens S10 WebSocket for real-time alerts.
              Must be INSIDE AuthProvider so it can read accessToken for ws-token fetch.
              Wraps all children so TopBar, FlashOverlay, and AlertsPage share one WS connection. */}
          <AlertStreamProvider>
            {children}
          </AlertStreamProvider>
        </ApiClientProvider>
      </AuthProvider>
      {/*
       * PLAN-0059 W0 F-COMP-NEW-TOAST-001: sonner Toaster mounted globally.
       * The previous @radix-ui/react-toast was a dead dep (no Toaster mounted, no
       * imports). Inline `{error && <p className="text-destructive">...</p>}` was
       * scattered across 38 sites. sonner gives a single import-anywhere API:
       *   import { toast } from "sonner";
       *   toast.error(msg) | toast.success(msg) | toast.info(msg)
       *
       * Position bottom-right matches Bloomberg / Aladdin chrome conventions
       * (StatusBar lives at the bottom, so toast above it). richColors uses our
       * semantic tokens. font-mono + tabular-nums + text-[11px] keeps the toast
       * visually consistent with the terminal-grade row rhythm.
       */}
      {/*
       * PRD-0089 W1 §4.11 / C-26 / FU-10.3 — Toaster moves to top-right
       * with z-60 so it sits above the shell chrome (TopBar z-50, sidebar
       * z-40) but below the FlashOverlay (z-[9999]). Top-right is the
       * Sonner default and matches the locked FU-10.3 decision: the
       * bottom-right position collided visually with the floating
       * ForceUpdateBanner before that banner moved to the top in W1.
       */}
      {/*
       * Round-3 polish (2026-06-10) — toast behavior is centralized HERE and
       * only here (DESIGN_SYSTEM.md §6.16). Call sites use the bare sonner
       * API (toast.success/error/info/…) and must NOT pass duration/position
       * overrides; the one sanctioned exception is useConfirmable's Undo
       * toast, whose duration IS the undo window (a functional timer, not
       * styling). A source-contract test (__tests__/toast-config.test.ts)
       * pins the single-Toaster rule and this config.
       */}
      <Toaster
        position="top-right"
        richColors
        theme="dark"
        closeButton
        expand
        // WHY 3 (was 5): with 5 stacked toasts the top-right column overlapped
        // the IndexStrip/TopBar content row on 768px-tall laptops. Three is
        // enough for any realistic burst (mutation result + WS alert + undo);
        // older toasts collapse into the stack and re-expand on hover.
        visibleToasts={3}
        // WHY style + className: Sonner attaches className to each toast
        // (mono font for terminal density) and style to the viewport root.
        // z:60 belongs on the viewport, not the per-toast element.
        style={{ zIndex: 60 } as React.CSSProperties}
        toastOptions={{
          // WHY explicit 4000ms (sonner's default, pinned): the auto-dismiss
          // window is a design-system contract — relying on the library
          // default means a sonner upgrade could silently change UX.
          duration: 4000,
          className: "font-mono text-[11px] tabular-nums",
        }}
      />
      {/* ReactQueryDevtools: visible only in development
          Shows cache state, query status, and timing — useful for debugging
          data freshness issues in complex dashboards */}
      {process.env.NODE_ENV === "development" && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </QueryClientProvider>
    </NuqsAdapter>
    </Sentry.ErrorBoundary>
  );
}
