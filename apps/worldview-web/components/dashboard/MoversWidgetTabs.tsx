/**
 * components/dashboard/MoversWidgetTabs.tsx — Tabbed Holdings vs Watchlist movers (PLAN-0053 T-B-2-03)
 *
 * WHY THIS EXISTS: PLAN-0053 T-B-2-03 introduces HoldingsMoversWidget but
 * keeps WatchlistMoversWidget alongside (the plan explicitly says "adding
 * alongside as a tab is safer"). This wrapper hosts both behind a 2-tab
 * toggle so the dashboard cell footprint stays unchanged — users pick which
 * universe they want to see without losing either signal.
 *
 * WHY DEFAULT TO HOLDINGS:
 *   For a user with a brokerage connected, holdings IS the more useful
 *   universe than a curated watchlist. The first thing they want to see is
 *   "how are my OWNED names moving?". Watchlist (curation, candidate names,
 *   sector watching) is the secondary use case behind it.
 *
 * WHO USES IT: dashboard/page.tsx Row 2 col-span-5 (the slot that used to
 * mount WatchlistMoversWidget directly).
 */

"use client";
// WHY "use client": uses useState for the active tab.

import { useState } from "react";
import { HoldingsMoversWidget } from "./HoldingsMoversWidget";
import { WatchlistMoversWidget } from "./WatchlistMoversWidget";
import { cn } from "@/lib/utils";

// Tab identifier — kept as a literal union so the tabswitch is type-safe.
type Tab = "holdings" | "watchlist";

export function MoversWidgetTabs() {
  // WHY default holdings: see WHY-DEFAULT-TO-HOLDINGS at top of file.
  const [tab, setTab] = useState<Tab>("holdings");

  return (
    // WHY h-full + flex-col: the parent grid cell already manages the
    // height — we fill it and stack the tab strip above the active widget.
    <div className="flex h-full min-h-0 flex-col bg-background">
      {/* Tab strip — same h-6 / 10px text rhythm as other widget headers so
          this widget stays visually consistent with the rest of the row. */}
      <div className="flex h-6 shrink-0 border-b border-border bg-card">
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

      {/* Active panel — both widgets are mounted independently so switching
          tabs doesn't lose their internal state (period selector, sector
          pill, etc). WHY conditional render (not display:none toggle): the
          watchlist movers widget has internal queries we don't want firing
          while the user is on the holdings tab — mounting only the active
          widget keeps the network footprint scoped to what's visible. */}
      <div className="flex min-h-0 flex-1 flex-col">
        {tab === "holdings" ? <HoldingsMoversWidget /> : <WatchlistMoversWidget />}
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
