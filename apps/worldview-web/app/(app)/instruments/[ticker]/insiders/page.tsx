/**
 * app/(app)/instruments/[ticker]/insiders/page.tsx — Insider Transactions stub
 *
 * WHY THIS EXISTS (T-16): InsiderTransactionsTable's "View all →" link navigates
 * here. The stub prevents a 404 while a full insider history page is deferred to
 * a future plan. The stub is intentionally minimal: just a back-link and a
 * "coming soon" notice so the navigation works end-to-end for QA.
 *
 * WHY STUB (not full page): The Financials tab ships the last-8 transactions
 * table. A 100-row scrollable history is useful but not in scope for W3. A future
 * PRD can build the full page against the same S9 endpoint.
 */

import Link from "next/link";

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export default async function InsidersPage({ params }: PageProps) {
  const { ticker } = await params;

  return (
    <div className="flex flex-col gap-4 p-6 max-w-2xl">
      <div className="flex items-center gap-2">
        <Link
          href={`/instruments/${ticker}`}
          className="text-[11px] text-muted-foreground hover:text-foreground transition-colors font-mono"
        >
          ← {ticker}
        </Link>
        <span className="text-muted-foreground/40 text-[11px]">/</span>
        <span className="text-[11px] text-foreground font-mono">INSIDERS</span>
      </div>

      <div className="border border-border rounded-sm p-4">
        <p className="text-[12px] text-muted-foreground font-mono">
          Full insider transaction history for{" "}
          <span className="text-foreground font-semibold">{ticker}</span> is
          coming in a future release. The last 8 transactions are available on
          the{" "}
          <Link
            href={`/instruments/${ticker}?tab=financials`}
            className="text-primary hover:underline"
          >
            Financials tab
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

export async function generateMetadata({ params }: PageProps) {
  const { ticker } = await params;
  return { title: `${ticker} — Insider Transactions` };
}
