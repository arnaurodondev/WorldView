/**
 * hooks/useMarketStatus.ts — Reactive market status hook
 *
 * WHY THIS EXISTS: MarketStatusPill needs to update automatically as markets open
 * and close throughout the trading day. A hook that recomputes every 60 seconds
 * ensures the TopBar always shows accurate status without user interaction.
 *
 * WHY 60s interval (not 1s or real-time):
 * Market open/close events happen at fixed UTC times (e.g., 14:30, 21:00).
 * Checking every 60s means the pill updates within 1 minute of a state change —
 * acceptable latency for an indicator that changes at most a few times per day.
 * 1s interval would trigger 60× more re-renders for no visible benefit.
 *
 * WHY NOT TanStack Query: No API call involved. Pure computation from system clock.
 * useQuery is for server state; this is entirely client-derived state.
 *
 * WHO USES IT: components/shell/MarketStatusPill.tsx
 * DATA SOURCE: system clock (no S9 calls)
 * DESIGN REFERENCE: PRD-0028 §6.5.1 MarketStatusPill
 */

import { useEffect, useState } from "react";
import { computeMarketStatus, type MarketStatusResult } from "@/lib/market-schedule";

export function useMarketStatus(): MarketStatusResult {
  // WHY useState with initializer function: avoids stale first render.
  // If we initialize to a hardcoded "closed" value, there would be a flash of
  // "closed" on the first paint before the effect runs. Computing immediately
  // ensures the correct status on first render.
  const [status, setStatus] = useState<MarketStatusResult>(() =>
    computeMarketStatus(new Date()),
  );

  useEffect(() => {
    // Update every 60 seconds to catch market open/close transitions
    const id = setInterval(() => {
      setStatus(computeMarketStatus(new Date()));
    }, 60_000);

    // WHY cleanup: Without clearInterval, the timer fires even after the
    // component unmounts (e.g., user navigates away). This causes a setState
    // on an unmounted component — a memory leak warning in React 17, and
    // potentially incorrect state in React 18 concurrent mode.
    return () => clearInterval(id);
  }, []); // Empty deps: set up once on mount, clean up on unmount

  return status;
}
