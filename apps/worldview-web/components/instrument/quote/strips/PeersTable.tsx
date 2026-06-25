/**
 * components/instrument/quote/strips/PeersTable.tsx — same-industry peers table
 *
 * WHY THIS EXISTS (Wave-2, replaces the "PEERS — Unavailable (B-Q-1)"
 * placeholder): relative-value triage in one glance — "AAPL at 35× vs NVDA at
 * 32×, who's cheap?" Up to 8 rows of ticker / name / last / chg% / mkt cap /
 * P/E; clicking a row navigates to that peer's instrument page.
 *
 * DATA SOURCE: GET /v1/instruments/{id}/peers?n=8 (Wave-1 backend,
 * live-verified 2026-06-10). UNIT QUIRK: change_pct is PERCENT-FORM
 * (1.61 = +1.61%) while return_1y is decimal — this table renders change_pct
 * only, with formatPercentDirect.
 *
 * WHO USES IT: QuoteTab bottom strip (left column, widest cell).
 * DESIGN: 16px data rows, mono numerics, row hover affordance.
 */

"use client";
// WHY "use client": useQuery + useRouter require the browser runtime.

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { formatMarketCap, formatPercentDirect } from "@/lib/utils";

interface PeersTableProps {
  readonly instrumentId: string;
}

// WHY 10 minutes: the peer SET (industry + market-cap ranking) changes
// rarely; the embedded quotes are context, not execution data.
const PEERS_STALE_MS = 10 * 60 * 1000;
// WHY 8: the spec's row budget for the bottom strip — enough for the
// big-cap neighbourhood without scrolling.
const PEER_COUNT = 8;

export function PeersTable({ instrumentId }: PeersTableProps) {
  const router = useRouter();
  const token = useAccessToken();
  const { data } = useQuery({
    queryKey: qk.instruments.peers(instrumentId),
    queryFn: () => createGateway(token).getPeers(instrumentId, PEER_COUNT),
    // Token-gated (sidebar-fix pattern): never fire a doomed 401 request.
    enabled: !!instrumentId && !!token,
    staleTime: PEERS_STALE_MS,
  });

  const peers = (data?.peers ?? []).slice(0, PEER_COUNT);

  return (
    <div className="flex flex-col h-full overflow-hidden" data-testid="peers-table">
      {/* Column header — industry label qualifies the peer set when known. */}
      <div className="flex items-center gap-2 h-[20px] px-2 border-b border-border/40 flex-shrink-0">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">Peers</span>
        {data?.industry && (
          <span className="truncate text-[9px] text-muted-foreground/40">{data.industry}</span>
        )}
      </div>

      {peers.length === 0 ? (
        // Honest empty state — peers genuinely unavailable (no industry match).
        <div className="flex flex-1 items-center justify-center">
          <span className="text-[9px] text-muted-foreground/50">No peer data</span>
        </div>
      ) : (
        // WHY a real <table>: 6 aligned numeric columns — grid-of-divs would
        // re-implement column sizing that the table layout engine gives free.
        <table className="w-full border-collapse">
          <thead>
            <tr className="text-[8px] uppercase tracking-wider text-muted-foreground/50">
              <th className="px-2 py-0.5 text-left font-medium">Tkr</th>
              <th className="py-0.5 text-left font-medium">Name</th>
              <th className="py-0.5 text-right font-medium">Last</th>
              <th className="py-0.5 text-right font-medium">Chg%</th>
              <th className="py-0.5 text-right font-medium">MCap</th>
              <th className="px-2 py-0.5 text-right font-medium">P/E</th>
            </tr>
          </thead>
          <tbody>
            {peers.map((p) => (
              <tr
                key={p.instrument_id}
                // Row click → peer's instrument page. WHY router.push (not a
                // <Link> per cell): one navigation affordance for the whole
                // row keeps the 16px rows uncluttered; keyboard users get the
                // same affordance via the button-role + Enter handler.
                role="button"
                tabIndex={0}
                onClick={() => router.push(`/instruments/${p.instrument_id}`)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") router.push(`/instruments/${p.instrument_id}`);
                }}
                className="h-[16px] cursor-pointer border-b border-border/20 text-[10px] hover:bg-muted/30 focus-visible:bg-muted/30 focus-visible:outline-none"
              >
                <td className="px-2 font-mono font-semibold text-foreground">{p.ticker}</td>
                <td className="max-w-[110px] truncate text-muted-foreground">{p.name}</td>
                <td className="text-right font-mono tabular-nums text-foreground">
                  {p.last_price != null ? p.last_price.toFixed(2) : "—"}
                </td>
                {/* change_pct is PERCENT-FORM (see module doc) → Direct formatter. */}
                <td
                  className={`text-right font-mono tabular-nums ${
                    p.change_pct == null
                      ? "text-muted-foreground/50"
                      : p.change_pct >= 0
                        ? "text-positive"
                        : "text-negative"
                  }`}
                >
                  {p.change_pct != null ? formatPercentDirect(p.change_pct) : "—"}
                </td>
                <td className="text-right font-mono tabular-nums text-muted-foreground">
                  {formatMarketCap(p.market_cap)}
                </td>
                <td className="px-2 text-right font-mono tabular-nums text-muted-foreground">
                  {p.pe_ratio != null ? p.pe_ratio.toFixed(1) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
