/**
 * app/(app)/alerts/layout.tsx — route-segment metadata wrapper.
 *
 * WHY THIS EXISTS (HF-10 demo-blocker fix): the alerts page is a client
 * component (WebSocket subscription, live updates) and cannot export
 * Next.js `metadata` directly. The App Router resolves metadata from the
 * deepest layout, so this server-component layout supplies the per-route
 * <title> without forcing the page to become a server component.
 *
 * SCOPE: pure passthrough — returns {children}.
 */
import type { ReactNode } from "react";

export const metadata = { title: "Alerts | Worldview" };

export default function AlertsLayout({ children }: { children: ReactNode }) {
  return children;
}
