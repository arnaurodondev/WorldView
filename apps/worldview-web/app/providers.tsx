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

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, type ReactNode } from "react";
import { AuthProvider } from "@/contexts/AuthContext";
import { AlertStreamProvider } from "@/contexts/AlertStreamContext";

// WHY useState for QueryClient (not module-level singleton):
// In Next.js App Router, module-level singletons are shared across ALL requests
// on the server. A QueryClient per-request (via useState) ensures cache isolation
// between different users. useState initializes once per component instance.
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
    // WHY QueryClientProvider wraps AuthProvider: Auth state depends on React Query
    // only indirectly (via the gateway client), but placing QueryClient at the top
    // ensures any future auth-related queries (e.g., user profile refresh) have access.
    // AuthProvider must be INSIDE QueryClientProvider for this reason.
    <QueryClientProvider client={queryClient}>
      {/* AuthProvider: manages OIDC session state (accessToken, user, isAuthenticated).
          Must wrap all children so protected layouts can read auth state via useAuth(). */}
      <AuthProvider>
        {/* AlertStreamProvider: opens S10 WebSocket for real-time alerts.
            Must be INSIDE AuthProvider so it can read accessToken for ws-token fetch.
            Wraps all children so TopBar, FlashOverlay, and AlertsPage share one WS connection. */}
        <AlertStreamProvider>
          {children}
        </AlertStreamProvider>
      </AuthProvider>
      {/* ReactQueryDevtools: visible only in development
          Shows cache state, query status, and timing — useful for debugging
          data freshness issues in complex dashboards */}
      {process.env.NODE_ENV === "development" && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </QueryClientProvider>
  );
}
