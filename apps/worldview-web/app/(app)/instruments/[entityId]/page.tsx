/**
 * app/(app)/instruments/[entityId]/page.tsx — Instrument Detail server entry.
 *
 * WHY SERVER COMPONENT: in Next.js 15 the `params` prop is a Promise that
 * must be awaited. Doing this on the server keeps the client bundle smaller
 * and removes the need for a client-side `useParams` indirection.
 * All interactive logic lives in <InstrumentPageClient/> (T-A-05).
 */
import { InstrumentPageClient } from "@/components/instrument/InstrumentPageClient";

export default async function InstrumentDetailPage({
  params,
}: {
  params: Promise<{ entityId: string }>;
}) {
  // WHY decodeURIComponent: entity_id from the URL may be percent-encoded.
  const { entityId } = await params;
  return <InstrumentPageClient entityId={decodeURIComponent(entityId)} />;
}
