/**
 * app/login/layout.tsx — route-segment metadata wrapper.
 *
 * WHY THIS EXISTS (HF-10 demo-blocker fix): the login page is a client
 * component (OIDC PKCE flow, dev-login form state) and cannot export
 * Next.js `metadata` directly. The App Router resolves metadata from the
 * deepest layout, so this server-component layout supplies the per-route
 * <title> without forcing the page to become a server component.
 *
 * SCOPE: pure passthrough — returns {children}.
 */
import type { ReactNode } from "react";

export const metadata = { title: "Sign in | Worldview" };

export default function LoginLayout({ children }: { children: ReactNode }) {
  return children;
}
