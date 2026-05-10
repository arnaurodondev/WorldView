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
import { PreMarketMoversWidget } from "./PreMarketMoversWidget";
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
          WHY PreMarketMoversWidget for MARKET tab: it already has the correct
          universe-wide gainers + losers layout with sector filter pills —
          re-using it avoids duplicating the fetching + rendering logic.
          WHY suppressHeader on PreMarketMoversWidget: PreMarketMoversWidget
          renders its own "TOP MOVERS" section header. In the tab context, the
          tab strip itself provides the navigation chrome, so the inner header
          would be redundant. We suppress it by wrapping in a div that hides
          the first child (the header). See inline comment below. */}
      <div className="flex min-h-0 flex-1 flex-col">
        {tab === "market" ? (
          // WHY [&>div>:first-child]:hidden: the PreMarketMoversWidget renders
          // a section header div as its first child. In the tab context, the
          // tab strip provides the chrome — hiding the inner header removes
          // double-labelling ("TOP MOVERS" header below "MARKET" tab label).
          // We use a narrow Tailwind selector rather than forking the widget,
          // which would require maintaining two versions of the same logic.
          <div className="flex min-h-0 flex-1 flex-col [&>div>div:first-child]:hidden">
            <PreMarketMoversWidget />
          </div>
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
      className={cn(
        "flex-1 px-2 font-mono text-[10px] uppercase tracking-[0.08em] transition-colors",
        active
          ? "border-b-2 border-primary text-primary"
          : "text-muted-foreground hover:text-foreground",
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
