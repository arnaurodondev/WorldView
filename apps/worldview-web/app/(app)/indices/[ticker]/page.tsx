/**
 * app/(app)/indices/[ticker]/page.tsx — Index detail (W1 stub).
 *
 * WHY THIS EXISTS: PRD-0089 W1 §4.9 — the new IndexStrip in the TopBar
 *   routes clicks to /indices/{ticker} (caret stripped). Without this
 *   route every cell would 404. W1 ships a minimal stub: ticker / full
 *   name / latest value / daily change / 1-day intraday sparkline. A
 *   richer index page is scheduled for a later wave; this is enough to
 *   make the IndexStrip cells land somewhere meaningful.
 *
 * WHY SERVER COMPONENT shell: Next.js 15's `params` is now a Promise that
 *   has to be awaited. Doing it server-side avoids a client-side
 *   useParams indirection and keeps the bundle small.
 *
 * DATA SOURCE: searchInstruments(ticker, 1) resolves the symbol to its
 *   canonical instrument_id, then getBatchQuotes + getBatchOhlcvBars give
 *   us the spot value and the 1-day intraday line. We deliberately reuse
 *   the same gateway methods the IndexStrip uses so the TanStack cache is
 *   shared (no extra round trip).
 */

import { IndexDetailClient } from "./IndexDetailClient";

export default async function IndexDetailPage({
  params,
}: {
  // WHY ticker is `string` (not validated here): IndexStrip emits the
  // form already stripped of `^` (i.e. `/indices/TNX`, not `/indices/^TNX`).
  // Anything unrecognised falls through to <InstrumentNotFound>.
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  return <IndexDetailClient ticker={decodeURIComponent(ticker).toUpperCase()} />;
}
