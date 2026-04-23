/**
 * components/shell/MarketStatusPill.tsx — Market open/closed status indicator
 *
 * WHY THIS EXISTS: Traders need to know at a glance whether they can trade.
 * A colored pill in the TopBar gives instant visual confirmation: green = open,
 * amber = pre/after-hours (prices moving but no liquidity), red = all closed.
 *
 * WHY PURE COMPUTATION (no API call):
 * Market hours are deterministic rules, not live data. Computing from the system
 * clock avoids a round-trip and works offline. PRD §6.5.1 confirmed this pattern.
 *
 * WHY POPOVER on hover (not a separate page):
 * Finance users want quick context without losing their workflow. A hover popover
 * showing all 8 exchange statuses gives full detail without navigation.
 *
 * WHO USES IT: components/shell/TopBar.tsx (right side)
 * DATA SOURCE: system clock (lib/market-schedule.ts)
 * DESIGN REFERENCE: PRD-0028 §6.5.1 MarketStatusPill
 */

"use client";
// WHY "use client": Uses useMarketStatus hook (setInterval-based reactive state).
// Server Components cannot have interval-driven state updates.

import { useMarketStatus } from "@/hooks/useMarketStatus";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import type { MarketSessionStatus } from "@/lib/market-schedule";

// ── Color mapping ─────────────────────────────────────────────────────────────

/**
 * pillClasses — map overall market status to Bloomberg Dark color classes
 *
 * WHY these specific colors:
 * - Green (#26A69A = --positive): equity market in regular session
 * - Amber (yellow-500): pre/after-hours — activity but limited liquidity
 * - Red (#EF5350 = --negative): all markets closed
 *
 * Using CSS custom property classes ensures consistency with the design system.
 */
const PILL_CLASSES: Record<string, string> = {
  open: "bg-positive/20 text-positive border-positive/30",
  "pre-after-hours": "bg-warning/20 text-warning border-warning/30",
  closed: "bg-destructive/20 text-destructive border-destructive/30",
};

const PILL_LABELS: Record<string, string> = {
  open: "Open",
  "pre-after-hours": "Ext Hrs",
  closed: "Closed",
};

// Exchange session status dot color
const SESSION_DOT: Record<MarketSessionStatus, string> = {
  open: "bg-positive",
  "pre-market": "bg-warning",
  "after-hours": "bg-warning",
  closed: "bg-destructive",
};

const SESSION_LABEL: Record<MarketSessionStatus, string> = {
  open: "Open",
  "pre-market": "Pre-market",
  "after-hours": "After-hours",
  closed: "Closed",
};

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketStatusPill() {
  const { overall, exchanges } = useMarketStatus();

  const pillClass = PILL_CLASSES[overall] ?? PILL_CLASSES["closed"];
  const pillLabel = PILL_LABELS[overall] ?? "Closed";

  return (
    <Popover>
      {/* WHY asChild: passes pill styling directly to the trigger without extra div */}
      <PopoverTrigger asChild>
        <button
          // WHY rounded-[2px]: terminal design mandates 2px radius on all interactive
          // elements. rounded-full (pill shape) is a consumer-app pattern. The status
          // signal is communicated by color and the dot, not by pill shape.
          className={`flex cursor-default items-center gap-1.5 rounded-[2px] border px-2.5 py-1 text-xs font-medium transition-opacity hover:opacity-80 ${pillClass}`}
          aria-label={`Market status: ${pillLabel}. Click for details.`}
        >
          {/* Status dot */}
          <span
            className={`h-1.5 w-1.5 rounded-full ${overall === "open" ? "bg-positive animate-pulse" : ""} ${overall === "pre-after-hours" ? "bg-warning" : ""} ${overall === "closed" ? "bg-destructive" : ""}`}
          />
          {pillLabel}
        </button>
      </PopoverTrigger>

      {/* Popover: per-exchange breakdown */}
      <PopoverContent className="w-80 p-0" align="end">
        <div className="border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold text-foreground">Exchange Hours</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">Times in UTC</p>
        </div>

        <div className="px-4 py-2">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="pb-1 text-left font-medium">Exchange</th>
                <th className="pb-1 text-left font-medium">Status</th>
                <th className="pb-1 text-right font-medium">Hours</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {exchanges.map((exchange) => (
                <tr key={exchange.name} className="py-1">
                  <td className="py-1.5 pr-2 text-left text-foreground">{exchange.name}</td>
                  <td className="py-1.5 pr-2">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${SESSION_DOT[exchange.status]}`}
                      />
                      <span className="text-muted-foreground">{SESSION_LABEL[exchange.status]}</span>
                    </div>
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                    {exchange.days === "24/7"
                      ? "24/7"
                      : `${exchange.utcOpen}–${exchange.utcClose}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Current UTC time at bottom — helps traders cross-reference */}
        <div className="border-t border-border px-4 py-2">
          <p className="text-right font-mono text-xs tabular-nums text-muted-foreground" suppressHydrationWarning>
            Now: {new Date().toISOString().slice(11, 16)} UTC
          </p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
