/**
 * ContributorsStrip — 96px row showing top contributors + top detractors.
 *
 * WHY THIS EXISTS: After scanning the KPI strip and holdings table, a PM wants
 * to know instantly "what drove today's P&L?" The contributors strip answers that
 * in a fixed-height 96px band — no navigation needed.
 * WHO USES IT: portfolio overview page, below SemanticHoldingsTable.
 * DATA SOURCE: topMovers from useTopMovers hook (passed as props); no separate fetch.
 * DESIGN REFERENCE: PRD-0089 W2 §4.13
 */
"use client";
// WHY "use client": Link navigation + onClick handlers require the browser DOM.

import Link from "next/link";
import { formatPercent } from "@/lib/utils";

interface MoverEntry {
  ticker: string;
  pnlPct: number;
}

interface ContributorsStripProps {
  contributors: MoverEntry[];   // top 4 positive contributors
  detractors: MoverEntry[];     // top 4 detractors (most negative first)
  isLoading?: boolean;
}

export function ContributorsStrip({ contributors, detractors, isLoading }: ContributorsStripProps) {
  return (
    <div className="flex h-24 shrink-0 border-b border-border bg-card divide-x divide-border">
      {/* Top Contributors */}
      <div className="flex-1 flex flex-col px-3 py-1">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground mb-1">Top Contributors</span>
        {isLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-5 flex items-center">
              <span className="text-[11px] font-mono text-muted-foreground">—</span>
            </div>
          ))
        ) : contributors.length === 0 ? (
          <span className="text-[11px] font-mono text-muted-foreground">—</span>
        ) : (
          // Pad to 4 rows so the height is consistent regardless of how many holdings exist
          [...contributors.slice(0, 4), ...Array(Math.max(0, 4 - contributors.length)).fill(null)].map((entry, i) => (
            <div key={i} className="h-5 flex items-center gap-2">
              {entry ? (
                <>
                  <Link href={`/instruments/${encodeURIComponent((entry as MoverEntry).ticker)}`} className="font-mono text-[11px] text-primary hover:underline">{(entry as MoverEntry).ticker}</Link>
                  <span className="font-mono text-[11px] tabular-nums text-positive">{formatPercent((entry as MoverEntry).pnlPct / 100)}</span>
                </>
              ) : (
                <span className="font-mono text-[11px] text-muted-foreground">—</span>
              )}
            </div>
          ))
        )}
      </div>

      {/* Top Detractors */}
      <div className="flex-1 flex flex-col px-3 py-1">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground mb-1">Top Detractors</span>
        {isLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-5 flex items-center">
              <span className="text-[11px] font-mono text-muted-foreground">—</span>
            </div>
          ))
        ) : detractors.length === 0 ? (
          <span className="text-[11px] font-mono text-muted-foreground">—</span>
        ) : (
          [...detractors.slice(0, 4), ...Array(Math.max(0, 4 - detractors.length)).fill(null)].map((entry, i) => (
            <div key={i} className="h-5 flex items-center gap-2">
              {entry ? (
                <>
                  <Link href={`/instruments/${encodeURIComponent((entry as MoverEntry).ticker)}`} className="font-mono text-[11px] text-primary hover:underline">{(entry as MoverEntry).ticker}</Link>
                  <span className="font-mono text-[11px] tabular-nums text-negative">{formatPercent((entry as MoverEntry).pnlPct / 100)}</span>
                </>
              ) : (
                <span className="font-mono text-[11px] text-muted-foreground">—</span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
