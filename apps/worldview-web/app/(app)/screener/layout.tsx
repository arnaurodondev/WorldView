/**
 * app/(app)/screener/layout.tsx — route-segment metadata wrapper.
 *
 * WHY THIS EXISTS (HF-10 demo-blocker fix): the screener page is a client
 * component (uses TanStack Query hooks + interactive filter state) and
 * therefore cannot export Next.js `metadata` directly. The App Router resolves
 * `metadata` from the deepest layout, so this server-component layout
 * supplies the per-route <title> without forcing the page to become RSC.
 *
 * WHY A LAYOUT (not generateMetadata in page): generateMetadata is only
 * supported on server components. The page is "use client" — splitting it
 * into a server wrapper would require lifting all hooks into a child
 * component. The layout pattern is the standard Next.js 15 escape hatch.
 *
 * SCOPE: pure passthrough — returns {children}. No additional UI, no nesting
 * effects. The (app) layout above this still wraps the page in TopBar /
 * sidebar / WorkspaceContext.
 */
import type { ReactNode } from "react";

export const metadata = { title: "Screener | Worldview" };

export default function ScreenerLayout({ children }: { children: ReactNode }) {
  return children;
}
