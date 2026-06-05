/**
 * app/(app)/instruments/[entityId]/layout.tsx — dynamic-route metadata wrapper.
 *
 * WHY THIS EXISTS (HF-10 demo-blocker fix): the instrument detail page is a
 * client component (uses TanStack Query + tab state) and cannot export
 * Next.js `metadata` directly. App Router resolves metadata from the deepest
 * layout, so this server-component layout supplies a per-route title.
 *
 * WHY THE TITLE INCLUDES entityId (not the ticker): the ticker lives in the
 * S9 response which requires the user's RS256 access token — a server-side
 * generateMetadata cannot fetch it without forwarding the token, and that
 * would leak credentials. The page itself updates document.title at runtime
 * with the ticker once the company overview query resolves (see useEffect in
 * the page). The static metadata here is the "before-data" fallback so tab
 * titles remain distinct in browser history.
 *
 * SCOPE: pure passthrough — returns {children}.
 */
import type { ReactNode } from "react";

// WHY async + Promise<{entityId}>: Next.js 15 turned route params into a
// Promise to support partial-prerendering. We await it for the title.
export async function generateMetadata({
  params,
}: {
  params: Promise<{ entityId: string }>;
}) {
  const { entityId } = await params;
  // entityId is a UUID — show a truncated form so the tab is identifiable
  // but not dominated by a 36-char hex string.
  const short = entityId.length > 8 ? `${entityId.slice(0, 8)}…` : entityId;
  return { title: `${short} | Worldview` };
}

export default function InstrumentLayout({ children }: { children: ReactNode }) {
  return children;
}
