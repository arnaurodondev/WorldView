/**
 * app/(app)/portfolio/layout.tsx — route-segment metadata wrapper.
 *
 * WHY THIS EXISTS (HF-10 demo-blocker fix): the portfolio page is a client
 * component (TanStack Query, SnapTrade callback flow, interactive tabs) and
 * cannot export Next.js `metadata` directly. The App Router resolves
 * metadata from the deepest layout, so this server-component layout
 * supplies the per-route <title> without forcing the page to become RSC.
 *
 * SCOPE: pure passthrough — returns {children}.
 */
import type { ReactNode } from "react";

export const metadata = { title: "Portfolio | Worldview" };

export default function PortfolioLayout({ children }: { children: ReactNode }) {
  return children;
}
