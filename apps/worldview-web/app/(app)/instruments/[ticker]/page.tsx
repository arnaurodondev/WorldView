/**
 * app/(app)/instruments/[ticker]/page.tsx — Instrument Detail server entry.
 *
 * WHY THIS EXISTS (PRD-0089 F2 step 9): the dynamic-route slug has been
 * unified on the analyst-facing ticker symbol (e.g. `/instruments/AAPL`).
 * The pre-F2 form used a `[entityId]` slug carrying a UUID — that surface
 * was discontinued when F2 collapsed the dual instrument_id / entity_id
 * identifiers into a single canonical `instrument_id` and standardised
 * the URL on the human ticker (PRD-0089 §2).
 *
 * WHY SERVER COMPONENT: in Next.js 15 the `params` prop is a Promise that
 * must be awaited. Doing this on the server keeps the client bundle smaller
 * and removes the need for a client-side `useParams` indirection.
 * All interactive logic lives in <InstrumentPageClient/> (T-A-05).
 *
 * WHY WE KEEP THE CLIENT PROP NAMED `entityId`: InstrumentPageClient and
 * its deeply-nested children (IntelligenceTab, AiBriefBanner, FinancialsTab)
 * thread this identifier through TanStack Query keys and downstream gateway
 * calls. The backend `resolve_security_id` (S9) accepts either a ticker or
 * a UUID at every endpoint, so the semantic of the prop is "url-supplied
 * identifier; resolver-handled". Renaming the prop through the whole tree
 * is out of scope for this routing step — that's the F2 v1.1 cleanup pass.
 */
import { InstrumentPageClient } from "@/components/instrument/InstrumentPageClient";

export default async function InstrumentDetailPage({
  params,
}: {
  // WHY ticker is `string` (not validated here): the middleware
  // (`apps/worldview-web/middleware.ts`) canonicalises and uppercases
  // the slug BEFORE this server component runs. By the time we read
  // `params.ticker` it is already the canonical form. Bad inputs fall
  // through to the page-bundle 404 path which renders InstrumentNotFound.
  params: Promise<{ ticker: string }>;
}) {
  // WHY decodeURIComponent: a slug like `BRK.B` is safe but historical
  // links may contain percent-encoded special chars. Decoding here is
  // belt-and-suspenders — the middleware also handles canonicalisation.
  const { ticker } = await params;
  return <InstrumentPageClient entityId={decodeURIComponent(ticker)} />;
}
