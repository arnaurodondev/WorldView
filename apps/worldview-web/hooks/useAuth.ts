/**
 * hooks/useAuth.ts — Public hook for accessing authentication state
 *
 * WHY THIS EXISTS: AuthContext exports `useAuthContext` but it lives in a deep
 * contexts/ directory. This hook re-exports it under a cleaner import path
 * (`@/hooks/useAuth`) that matches the convention for all other hooks in this app.
 *
 * This is a thin wrapper — all logic lives in AuthContext.tsx. The separation
 * keeps the context file focused on state management while this file provides
 * a discoverable entry point for consumers.
 *
 * WHO USES IT: Every protected component that needs auth state:
 *   - TopBar: reads `user` for display name, `logout` for sign-out button
 *   - Every useQuery hook: reads `accessToken` to attach Bearer header
 *   - Route guards: reads `isAuthenticated` + `isLoading` to decide on redirects
 *
 * DATA SOURCE: AuthContext (React state — no S9 calls in this hook itself)
 * DESIGN REFERENCE: PRD-0028 §6.6 Auth Flows
 */

export { useAuthContext as useAuth } from "@/contexts/AuthContext";
