/**
 * components/dashboard/MoversWidgetTabs.tsx — Tabbed MARKET / HOLDINGS / WATCHLIST movers
 *
 * WHY THIS EXISTS: PLAN-0053 T-B-2-03 introduced Holdings and Watchlist tabs.
 * SA-2 PLAN-0088 Demo P1 adds a MARKET tab (universe-wide top movers from
 * PreMarketMoversWidget) so traders can scan the full market alongside their
 * personal positions in a single widget slot.
 *
 * WHY THREE TABS:
 *   MARKET   — universe-wide top gainers + losers with sector filter.
 *              Best for: "what's the biggest market story today?"
 *   HOLDINGS — movers among owned positions (brokerage-connected users).
 *              Best for: "how is my capital performing today?"
 *   WATCHLIST — movers among curated watchlist names.
 *              Best for: "what's happening in my tracked universe?"
 *
 * WHY DEFAULT TO MARKET:
 *   In the demo context (analyst doing a morning walkthrough) the MARKET
 *   tab is the highest-value first view — it shows the broadest context.
 *   Users with an active brokerage can click to HOLDINGS in one tap.
 *   (Prior default was HOLDINGS; changed for demo P1 to highlight market context.)
 *
 * WHO USES IT: dashboard/page.tsx Row 2 col-span-5.
 */

"use client";
// WHY "use client": uses useState for the active tab.

import { useState } from "react";
import { HoldingsMoversWidget } from "./HoldingsMoversWidget";
import { WatchlistMoversWidget } from "./WatchlistMoversWidget";
// Round 1 foundation (2026-06-10): the MARKET tab now hosts the redesigned
// TopMovers (Gainers/Losers shadcn Tabs, rows with ticker · name · 5-day
// sparkline · price · %chg) instead of PreMarketMoversWidget. TopMovers reads
// qk.dashboard.topMovers(...) which DashboardBundleHydrator seeds from the
// F-2 bundle — so the MARKET tab renders on cold start without its own fetch.
import { TopMovers } from "./TopMovers";
import { cn } from "@/lib/utils";

// Tab identifier — kept as a literal union so the tabswitch is type-safe.
type Tab = "market" | "holdings" | "watchlist";

export function MoversWidgetTabs() {
  // WHY default market: see WHY-DEFAULT-TO-MARKET at top of file.
  const [tab, setTab] = useState<Tab>("market");

  return (
    // WHY h-full + flex-col: the parent grid cell already manages the
    // height — we fill it and stack the tab strip above the active widget.
    <div className="flex h-full min-h-0 flex-col bg-background">
      {/* Tab strip — same h-6 / 10px text rhythm as other widget headers.
          Three equal-width tabs using flex-1 on each button so the strip
          fills the full header row without leaving gaps. */}
      <div className="flex h-6 shrink-0 border-b border-border bg-card">
        <TabButton
          active={tab === "market"}
          onClick={() => setTab("market")}
          label="MARKET"
        />
        <TabButton
          active={tab === "holdings"}
          onClick={() => setTab("holdings")}
          label="HOLDINGS"
        />
        <TabButton
          active={tab === "watchlist"}
          onClick={() => setTab("watchlist")}
          label="WATCHLIST"
        />
      </div>

      {/* Active panel — WHY conditional render (not display:none):
          each widget has internal queries we don't want firing when the tab
          is not visible. Mounting only the active widget keeps the network
          footprint scoped to what the user is looking at.
          WHY TopMovers for MARKET tab (Round 1, replaces PreMarketMoversWidget):
          the redesigned TopMovers renders rows with ticker · name · 5-day
          sparkline · price · %chg behind Gainers/Losers shadcn Tabs — the
          Round 1 foundation spec shape. Its tab strip doubles as the panel
          chrome, so the previous hide-first-child CSS hack (which suppressed
          PreMarketMoversWidget's redundant "TOP MOVERS" header) is gone — it
          would now wrongly hide the new Gainers/Losers tab strip. */}
      <div className="flex min-h-0 flex-1 flex-col">
        {tab === "market" ? (
          <TopMovers />
        ) : tab === "holdings" ? (
          <HoldingsMoversWidget />
        ) : (
          <WatchlistMoversWidget />
        )}
      </div>
    </div>
  );
}

// ── TabButton ────────────────────────────────────────────────────────────────

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  label: string;
}

/**
 * TabButton — minimal tab control. We don't pull in shadcn/ui Tabs here
 * because we already render WatchlistMoversWidget which has its own header;
 * a heavyweight Tabs component would double-render the chrome.
 */
function TabButton({ active, onClick, label }: TabButtonProps) {
  return (
    <button
      onClick={onClick}
      // Round 3 (item 5): bg-muted hover convention + keyboard focus ring
      // (inset — the tab strip is flush against the panel border, an outset
      // ring would be clipped). Tier-1 transition-colors stays ≤150ms.
      className={cn(
        "flex-1 px-2 font-mono text-[10px] uppercase tracking-[0.08em] transition-colors",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
        active
          ? "border-b-2 border-primary text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
      // role=tab uses aria-selected (not aria-pressed) per WAI-ARIA. This
      // matches the rest of the codebase's tab-button pattern.
      role="tab"
      aria-selected={active}
    >
      {label}
    </button>
  );
}
