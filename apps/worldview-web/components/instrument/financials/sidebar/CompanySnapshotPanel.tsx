/**
 * sidebar/CompanySnapshotPanel.tsx — Company profile snapshot panel
 *
 * WHY THIS EXISTS (T-23): The bottom sidebar panel closes the loop between
 * market data (what the stock is doing) and company identity (who the company
 * is). Sector/Industry/Country/Description gives analysts a sanity-check that
 * they're looking at the right instrument before acting on the metrics above.
 *
 * WHY qk.instruments.overview (not a new fetch): InstrumentPageClient seeds
 * the TanStack Query cache with bundle.overview (CompanyOverview) on page
 * load. Reading from the same key gives zero extra HTTP calls — the data is
 * already in memory. The Instrument sub-field has sector, industry, country,
 * and description (EODHD General.Description field).
 *
 * WHY 4-line clamp + "more" toggle: descriptions can be >500 words. Clamping
 * prevents the sidebar from pushing the analyst tabs below the fold. The "more"
 * toggle is a simple state toggle — no need for a Dialog at this density.
 *
 * WHO USES IT: AnalystSidebar.tsx (T-24).
 * DATA SOURCE: qk.instruments.overview(instrumentId) → CompanyOverview.instrument.
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §5.7
 */

"use client";
// WHY "use client": useState for description expand + useQuery for overview.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";

interface CompanySnapshotPanelProps {
  instrumentId: string;
}

function SnapshotRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex items-start gap-1 h-[var(--row-h,20px)]">
      <span className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground/60 w-[56px] shrink-0 pt-[2px]">
        {label}
      </span>
      <span className="text-[10px] text-foreground font-mono truncate flex-1 min-w-0">
        {value}
      </span>
    </div>
  );
}

export function CompanySnapshotPanel({ instrumentId }: CompanySnapshotPanelProps) {
  const token = useAccessToken();
  const [expanded, setExpanded] = useState(false);

  // WHY staleTime 30min: overview is seeded by the page bundle at load time.
  // 30min staleTime means it won't refetch in the background during a normal
  // analysis session (< 30min). The bundle seed makes the initial render free.
  const { data: overview } = useQuery({
    queryKey: qk.instruments.overview(instrumentId),
    queryFn: () => createGateway(token).getCompanyOverview(instrumentId),
    enabled: !!instrumentId && !!token,
    staleTime: 30 * 60 * 1000,
  });

  const instrument = overview?.instrument;
  if (!instrument) return null;

  const hq = [instrument.country].filter(Boolean).join(", ");
  const description = instrument.description;

  return (
    <div className="flex flex-col gap-0.5 px-2 py-2">
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70 mb-1">
        COMPANY SNAPSHOT
      </span>

      <SnapshotRow label="SECTOR"   value={instrument.gics_sector} />
      <SnapshotRow label="INDUSTRY" value={instrument.gics_industry} />
      {/* WHY toLocaleString(): formats 147000 → "147,000" for readability.
          Spec: docs/designs/0089/06-instrument-financials.md §5.2 (F-009). */}
      <SnapshotRow
        label="EMPLOYEES"
        value={instrument.full_time_employees ? instrument.full_time_employees.toLocaleString() : undefined}
      />
      <SnapshotRow label="COUNTRY"  value={hq} />

      {description && (
        <div className="mt-1.5">
          <p
            className={`text-[10px] text-muted-foreground leading-[14px] ${
              expanded ? "" : "line-clamp-4"
            }`}
          >
            {description}
          </p>
          {description.length > 200 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-[9px] text-primary/70 hover:text-primary transition-colors mt-0.5"
            >
              {expanded ? "less ↑" : "more ↓"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
