/**
 * components/ui/StaleBadge.tsx — Freshness indicator badge for market data
 *
 * WHY THIS EXISTS: When a price quote is delayed or stale (e.g. no EODHD call
 * succeeded recently), the user needs a visual cue so they know the displayed
 * price is not a live tick. Bloomberg shows a yellow "DELAYED" indicator;
 * we show a muted badge with tooltip.
 *
 * DESIGN REFERENCE: PRD-0028 §6.8 product surface freshness requirements
 * DATA SOURCE: Quote.freshness_status from S9 (PLAN-0036 Wave 1)
 *
 * USAGE:
 *   <StaleBadge status="delayed" staleReason="No quote in last 15 min" />
 *   <StaleBadge status="stale" />
 *   {quote.freshness_status === "live" && <span>·</span>}
 */

import * as Tooltip from "@radix-ui/react-tooltip";
import { Clock } from "lucide-react";
import type { Quote } from "@/types/api";

// ── Types ──────────────────────────────────────────────────────────────────────

interface StaleBadgeProps {
  /**
   * The freshness_status from the Quote object.
   * If "live" or "recent", nothing is rendered — data is fresh enough.
   * If "delayed", a yellow DELAYED badge appears.
   * If "stale" or "unavailable", a red STALE badge appears.
   */
  status: Quote["freshness_status"];
  /** Optional human-readable reason from Quote.stale_reason */
  staleReason?: string | null;
  /** Optional ISO timestamp for "as of" display in the tooltip */
  dataAsOf?: string | null;
}

// ── Helper: badge config per freshness level ──────────────────────────────────

// WHY separate config: keeps the JSX clean and makes it easy to adjust
// colors/labels without hunting through conditional chains.
const BADGE_CONFIG: Record<
  "delayed" | "stale" | "unavailable",
  { label: string; className: string }
> = {
  delayed: {
    label: "DELAYED",
    // WHY amber: yellow/amber signals "caution" not "error" — price exists
    // but is older than 15 min. Following Bloomberg convention.
    className:
      "inline-flex items-center gap-1 rounded-[2px] bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-400",
  },
  stale: {
    label: "STALE",
    // WHY red-muted: stronger signal than delayed — data is >1 day old.
    className:
      "inline-flex items-center gap-1 rounded-[2px] bg-red-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-red-400",
  },
  unavailable: {
    label: "N/A",
    // WHY gray: "no data" is not an error state, just absent.
    className:
      "inline-flex items-center gap-1 rounded-[2px] bg-muted px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground",
  },
};

// ── Component ─────────────────────────────────────────────────────────────────

export function StaleBadge({ status, staleReason, dataAsOf }: StaleBadgeProps) {
  // WHY return null for live/recent: the badge is only shown when data is stale.
  // Showing "LIVE" on every quote would be noisy — Bloomberg omits it too.
  if (!status || status === "live" || status === "recent") {
    return null;
  }

  const config = BADGE_CONFIG[status];
  if (!config) {
    return null;
  }

  // Tooltip text: prefer stale_reason from backend, fall back to dataAsOf,
  // then a generic explanation.
  const tooltipContent = staleReason
    ? staleReason
    : dataAsOf
      ? `Price as of ${new Date(dataAsOf).toLocaleString("en-GB", {
          dateStyle: "short",
          timeStyle: "short",
          timeZone: "UTC",
        })} UTC`
      : "Price data may not reflect the latest market activity";

  return (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          {/* WHY asChild with span: avoids nested <button> in inline badge context */}
          <span className={config.className} role="status" aria-label={`Data is ${status}`}>
            <Clock className="h-2.5 w-2.5" aria-hidden="true" />
            {config.label}
          </span>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            side="bottom"
            align="center"
            sideOffset={4}
            className="z-50 max-w-[220px] rounded-[2px] bg-popover px-2.5 py-1.5 text-[11px] text-popover-foreground shadow-md"
          >
            {tooltipContent}
            <Tooltip.Arrow className="fill-popover" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
