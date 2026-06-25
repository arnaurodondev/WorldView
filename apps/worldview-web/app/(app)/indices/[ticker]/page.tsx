/**
 * app/(app)/indices/[ticker]/page.tsx — Index instrument detail stub
 *
 * WHY THIS EXISTS: PRD-0089 W1 §4.9 — the IndexStrip cells route to
 * `/indices/{ticker}` (e.g. `/indices/SPY`). Without this page those clicks
 * would land on a Next.js 404. This stub provides a functional landing page
 * (symbol + name + latest quote + daily change + 1Y chart) so the IndexStrip
 * is immediately useful on W1 ship. A full design-led page is deferred to a
 * later wave.
 *
 * WHY a stub (not the full page design):
 * The full design requires wireframes, entity graph, and fundamentals tabs that
 * are out of scope for Wave 1. The stub satisfies the W1 acceptance criteria
 * (§7 gate #10: IndexStrip cell click lands on a functional page) without
 * blocking the shell redesign ship.
 *
 * ROUTE: /indices/[ticker] — ticker is the URL form (no "^" caret).
 * The canonical ticker (with caret for yield indices) is reconstructed at
 * query time by the entity-lookup fallback logic.
 *
 * DATA: POST /v1/entities/lookup?ticker={TICKER} (S9 entity lookup)
 * 404 → <InstrumentNotFound> (F1 primitive, same as instruments/[ticker])
 *
 * WHO LINKS HERE: components/shell/IndexStrip.tsx (click handler)
 */

// WHY async server component: Next.js 15 params is a Promise — we must await it.
// This is a standard Next.js 15 Server Component — data can be fetched here
// server-side in a future iteration. For now the page is a client-side stub.
import type { ReactNode } from "react";
import { IndexDetailClient } from "./IndexDetailClient";

interface PageParams {
  ticker: string;
}

export default async function IndexDetailPage({
  params,
}: {
  params: Promise<PageParams>;
}): Promise<ReactNode> {
  // WHY await params: Next.js 15 requires awaiting params (it's a Promise).
  const { ticker } = await params;

  // Decode URL-encoded ticker (e.g. "%5ETNX" → "^TNX" is NOT the case here
  // because we strip the caret in IndexStrip; "TNX" → "^TNX" is recovered below
  // in the client component's lookup logic).
  return <IndexDetailClient ticker={ticker} />;
}

/**
 * generateMetadata — sets the page <title> to the ticker symbol.
 * WHY: search engines and browser tabs benefit from a meaningful title.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<PageParams>;
}) {
  const { ticker } = await params;
  return {
    title: `${ticker.toUpperCase()} — Worldview`,
    description: `Market data and analysis for ${ticker.toUpperCase()}`,
  };
}
