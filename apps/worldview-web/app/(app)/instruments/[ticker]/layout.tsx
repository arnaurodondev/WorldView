/**
 * app/(app)/instruments/[ticker]/layout.tsx — dynamic-route metadata wrapper.
 *
 * WHY THIS EXISTS (HF-10 demo-blocker fix): the instrument detail page is a
 * client component (uses TanStack Query + tab state) and cannot export
 * Next.js `metadata` directly. App Router resolves metadata from the deepest
 * layout, so this server-component layout supplies a per-route title.
 *
 * WHY THE TITLE IS THE TICKER (PRD-0089 F2 step 9): post-F2 the URL slug
 * IS the analyst-facing ticker (e.g. `AAPL`). Before F2 the slug was a
 * raw UUID, which produced unreadable tab titles like "f6ade512… | Worldview".
 * Now the title is the canonical uppercase ticker, which is short, unique,
 * and tab-identifiable without any S9 fetch.
 *
 * NOTE: the page itself may still update document.title at runtime with the
 * company name once the bundle resolves — generateMetadata only provides
 * the static "before-data" fallback that appears in browser history /
 * back-forward navigation.
 *
 * SCOPE: pure passthrough — returns {children}.
 */
import type { ReactNode } from "react";

// WHY async + Promise<{ticker}>: Next.js 15 turned route params into a
// Promise to support partial-prerendering. We await it for the title.
export async function generateMetadata({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  // WHY toUpperCase: the middleware redirects lowercase → uppercase but a
  // direct server render (e.g. from a test client that bypasses middleware)
  // could hit us with a lowercase slug. Cheap, idempotent defence.
  const display = ticker.toUpperCase();
  return { title: `${display} | Worldview` };
}

export default function InstrumentLayout({ children }: { children: ReactNode }) {
  return children;
}
