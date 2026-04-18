/**
 * app/(app)/layout.tsx — Protected route layout guard
 *
 * WHY THIS EXISTS: All authenticated pages live under the (app)/ route group.
 * This layout checks auth state on every render and redirects unauthenticated
 * users to /login BEFORE rendering any protected content.
 *
 * WHY A ROUTE GROUP (app): Next.js route groups (parentheses in folder name)
 * let us apply a layout to a set of pages without adding the group name to the URL.
 * So `/app/(app)/dashboard/page.tsx` maps to the URL `/dashboard` — clean URLs
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
 * DESIGN REFERENCE: PRD-0028 §6.6.1 Auth Guard
 */

"use client";
// WHY "use client": Reads AuthContext via useAuth() hook — requires client-side
// React rendering. Server Components cannot access React context.

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";

interface AppLayoutProps {
  children: ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
  const { isLoading, isAuthenticated } = useAuth();
  const router = useRouter();

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

  // Authenticated: render the protected page content
  return <>{children}</>;
}
