/**
 * app/(app)/workspace/page.tsx — Multi-panel Workspace page
 *
 * WHY THIS EXISTS: Institutional traders need simultaneous visibility into
 * multiple data streams — a chart, screener results, news feed, and alerts
 * all at once. Navigating to separate pages breaks flow and loses context.
 * The Workspace solves this: a configurable multi-panel layout that lets
 * traders assemble exactly the data surfaces they need for their workflow.
 *
 * DESIGN PHILOSOPHY: Bloomberg Terminal model — every panel shows live data,
 * no wasted space, panel selector is always accessible at the top.
 *
 * MVP SCOPE: Up to 4 panels in a 2×2 grid (desktop). Each panel is a Card
 * containing one of 8 panel types. Panels are added/removed via a selector
 * bar at the top. No drag-to-resize — that is deferred to a future wave.
 *
 * MULTI-INSTANCE SUPPORT: Each panel has a unique `id` (crypto.randomUUID()) so
 * the user can add, e.g., two Chart panels at once. The selector bar shows a panel
 * type as "active" (outline style) when AT LEAST ONE instance of that type exists.
 * Clicking an active type button adds ANOTHER instance (up to MAX_PANELS total).
 * The close button on each card removes that specific instance by id.
 *
 * PERSISTENCE: Panel layout is stored in localStorage under the key
 * 'workspace-panels'. The state is loaded on first render (SSR-safe lazy
 * initializer) and persisted on every change via a useEffect. This means the
 * user's workspace survives logout/login cycles because it is stored in the browser,
 * not in server-side session state.
 *
 * WHO USES IT: Power users / institutional traders navigating via the sidebar.
 * DATA SOURCE: Each panel delegates to its own component which calls S9 via gateway.
 * DESIGN REFERENCE: PRD-0028 §6.5 Workspace, canvas State A (11 Workspace panels).
 */

"use client";
// WHY "use client": uses useState/useEffect for active panel list (client-only interaction).
// Each embedded component manages its own TanStack Query data-fetching.

import { useState, useEffect } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  TrendingUp,
  Newspaper,
  MessageSquare,
  Bell,
  BarChart3,
  Network,
  Briefcase,
  X,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { OHLCVChart } from "@/components/instrument/OHLCVChart";
import { FundamentalsTab } from "@/components/instrument/FundamentalsTab";
import { EntityGraphPanel } from "@/components/instrument/EntityGraphPanel";
import { AlertsList } from "@/components/alerts/AlertsList";
// WHY WorkspaceScreenerWidget: replaces WorkspacePlaceholder for the "screener" type.
// Shows top-20 instruments by market_impact_score in a compact 5-column table.
import { WorkspaceScreenerWidget } from "@/components/workspace/WorkspaceScreenerWidget";
// WHY WorkspaceChatWidget: replaces WorkspacePlaceholder for the "chat" type.
// Embedded SSE streaming chat with ephemeral session — no thread list needed.
import { WorkspaceChatWidget } from "@/components/workspace/WorkspaceChatWidget";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatRelativeTime, formatMarketCap, safeExternalUrl } from "@/lib/utils";

// ── Panel type catalogue ───────────────────────────────────────────────────────

/**
 * PanelType — the 8 supported workspace panel types.
 *
 * WHY enum-style literal union (not enum): TypeScript string literal unions
 * are narrowable, serialisable, and don't require a runtime import. The 8
 * types map to the panel definitions in PRD-0028 §6.5.
 */
type PanelType =
  | "chart"
  | "screener"
  | "news"
  | "chat"
  | "alerts"
  | "fundamentals"
  | "graph"
  | "portfolio";

/**
 * PanelDef — metadata for a panel type used in the selector bar.
 *
 * WHY separate from PanelType: The selector bar needs a human-readable label
 * and icon for each type. This struct pairs those with the type key so the
 * selector can be rendered from data (no if/else chains).
 */
interface PanelDef {
  type: PanelType;
  label: string;
  /** Lucide icon component (h-4 w-4 size) */
  icon: React.ElementType;
  description: string;
}

/**
 * PANEL_CATALOGUE — all 8 panel types with their display metadata.
 *
 * WHY const array: React.ElementType references are resolved at module load time,
 * and the catalogue is immutable. Array preserves render order in selector bar.
 */
const PANEL_CATALOGUE: PanelDef[] = [
  {
    type: "chart",
    label: "Chart",
    icon: TrendingUp,
    description: "OHLCV candlestick chart",
  },
  {
    type: "screener",
    label: "Screener",
    icon: LayoutDashboard,
    description: "Instrument filter panel",
  },
  {
    type: "news",
    label: "News",
    icon: Newspaper,
    description: "Top news feed",
  },
  {
    type: "chat",
    label: "Chat",
    icon: MessageSquare,
    description: "AI chat assistant",
  },
  {
    type: "alerts",
    label: "Alerts",
    icon: Bell,
    description: "Recent alerts feed",
  },
  {
    type: "fundamentals",
    label: "Fundamentals",
    icon: BarChart3,
    description: "Fundamental metrics",
  },
  {
    type: "graph",
    label: "Graph",
    icon: Network,
    description: "Entity relationship graph",
  },
  {
    type: "portfolio",
    label: "Portfolio",
    icon: Briefcase,
    description: "Holdings summary",
  },
];

/**
 * ActivePanel — a single panel instance currently open in the workspace.
 *
 * WHY id + type (not just type): supporting multiple instances of the same
 * panel type (e.g., two Chart panels) requires a unique key per instance.
 * `id` is a stable crypto.randomUUID() value assigned when the panel is added.
 * `type` drives which component is rendered inside the card.
 */
interface ActivePanel {
  /** Unique identifier for this specific panel instance (used as React key) */
  id: string;
  /** Panel content type (drives which component renders) */
  type: PanelType;
}

/**
 * MAX_PANELS — cap visible panels at 4 for the 2×2 MVP grid.
 *
 * WHY 4: A 2×2 grid is the densest layout that remains readable on a 1440px
 * wide desktop monitor without horizontal scrolling. More panels would require
 * drag-to-resize (future wave) to be usable.
 */
const MAX_PANELS = 4;

/**
 * WORKSPACE_STORAGE_KEY — localStorage key for workspace panel persistence.
 *
 * WHY a named constant: avoids typos in the key string across the read/write
 * call sites. If we ever rename the key we only change it here.
 */
const WORKSPACE_STORAGE_KEY = "workspace-panels";

/**
 * DEFAULT_PANELS_CONFIG — initial set of panel instances shown on first load.
 *
 * WHY chart + news + alerts: These three are the most universally useful
 * panels for any trader's workflow. Chart for price context, news for
 * catalysts, alerts for real-time signals. A 4th slot is left empty to
 * communicate that the user can add more.
 *
 * WHY pre-assigned IDs: the default panels need stable IDs from the start so
 * that React keys are consistent across re-renders without triggering unmounts.
 */
const DEFAULT_PANELS_CONFIG: ActivePanel[] = [
  { id: "default-chart", type: "chart" },
  { id: "default-news", type: "news" },
  { id: "default-alerts", type: "alerts" },
];

// ── Workspace panel sub-components ────────────────────────────────────────────

/**
 * WorkspaceNewsPanel — compact top-news feed for the workspace News panel.
 *
 * WHY compact rows (not ArticleCard): ArticleCard is designed for full-width
 * article pages with spacious padding. In a 2×2 workspace grid, each panel
 * is ~400px wide. A compact row (title + source + time) shows 8-10 articles
 * in the same space ArticleCard would use for 2-3 — much better information
 * density for a terminal-style layout.
 *
 * WHY getTopNews (not getRelevantNews): getTopNews uses PRD-0026 ranked scoring.
 * Top articles are pre-sorted by composite signal (market impact + LLM relevance
 * + routing), so the most market-moving stories appear first without user filtering.
 */
function WorkspaceNewsPanel() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["workspace-top-news"],
    queryFn: () => createGateway(accessToken).getTopNews({ limit: 15, offset: 0 }),
    enabled: !!accessToken,
    // WHY 5min staleTime: news changes constantly but workspace shouldn't hammer S9.
    // 5 minutes is fresh enough to show recent catalysts without excessive polling.
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <Skeleton className="h-3.5 w-full" style={{ animationDelay: `${i * 50}ms` }} />
            <Skeleton className="h-2.5 w-1/3" style={{ animationDelay: `${i * 50 + 25}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return <p className="px-3 py-3 text-xs text-muted-foreground">News unavailable.</p>;
  }

  const articles = data.articles ?? [];

  if (articles.length === 0) {
    return <p className="px-3 py-3 text-xs text-muted-foreground">No news articles yet.</p>;
  }

  return (
    <div className="divide-y divide-border/30 overflow-auto">
      {articles.map((article) => (
        <a
          key={article.article_id}
          href={safeExternalUrl(article.url)}
          target="_blank"
          rel="noopener noreferrer"
          // WHY group: enables group-hover to highlight the external link icon
          className="group flex flex-col gap-0.5 px-3 py-2 hover:bg-muted/30"
        >
          {/* Article title — 2-line clamp */}
          <span className="line-clamp-2 text-xs font-medium leading-snug text-foreground group-hover:text-primary">
            {article.title}
          </span>
          {/* Source + time row */}
          <div className="flex items-center gap-1.5">
            <span className="truncate font-mono text-[10px] tabular-nums text-muted-foreground">
              {article.source_name ?? "—"}
            </span>
            <span className="text-muted-foreground/40">·</span>
            <time
              dateTime={article.published_at ?? undefined}
              className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground"
            >
              {formatRelativeTime(article.published_at)}
            </time>
            {/* Relevance score if available */}
            {article.display_relevance_score != null && article.display_relevance_score >= 0.7 && (
              <span className="ml-auto shrink-0 rounded-[2px] bg-positive/10 px-1 text-[9px] font-semibold tabular-nums text-positive">
                {Math.round(article.display_relevance_score * 100)}
              </span>
            )}
          </div>
        </a>
      ))}

      {/* Footer link to full news page */}
      <div className="p-2 text-center">
        <Link
          href="/alerts"
          className="text-[10px] text-muted-foreground hover:text-foreground"
        >
          View all news →
        </Link>
      </div>
    </div>
  );
}

/**
 * WorkspacePortfolioPanel — compact portfolio holdings summary for the workspace.
 *
 * WHY holdings over portfolio list: Traders using the workspace want to see
 * their P&L at a glance — which positions they hold and how they're doing.
 * Listing portfolio names is useless without the underlying holdings data.
 *
 * WHY fetch first portfolio only: workspace MVP shows one portfolio. A future
 * wave adds a portfolio picker per panel so users with multiple portfolios
 * can choose which one to display.
 */
function WorkspacePortfolioPanel() {
  const { accessToken } = useAuth();

  const { data: portfolios, isLoading: portfoliosLoading } = useQuery({
    queryKey: ["portfolios"],
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 5 * 60_000,
  });

  // Fetch holdings for the first portfolio only (workspace MVP)
  const firstPortfolioId = portfolios?.[0]?.portfolio_id;

  const { data: holdingsResp, isLoading: holdingsLoading } = useQuery({
    queryKey: ["holdings", firstPortfolioId],
    queryFn: () => createGateway(accessToken).getHoldings(firstPortfolioId!),
    enabled: !!accessToken && !!firstPortfolioId,
    staleTime: 5 * 60_000,
  });

  const isLoading = portfoliosLoading || holdingsLoading;

  if (isLoading) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex items-center justify-between gap-2">
            <Skeleton className="h-3 w-16" style={{ animationDelay: `${i * 50}ms` }} />
            <Skeleton className="h-3 w-20" style={{ animationDelay: `${i * 50 + 25}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  if (!portfolios?.length) {
    return (
      <p className="px-3 py-3 text-xs text-muted-foreground">
        No portfolio yet.{" "}
        <Link href="/portfolio" className="text-primary hover:underline">Set up →</Link>
      </p>
    );
  }

  const holdings = holdingsResp?.holdings ?? [];

  if (holdings.length === 0) {
    return <p className="px-3 py-3 text-xs text-muted-foreground">No holdings in portfolio.</p>;
  }

  return (
    <div className="overflow-auto">
      {/* Portfolio name header */}
      <div className="border-b border-border/40 px-3 py-1.5">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {portfolios[0].name}
        </p>
      </div>

      {/* Holdings table */}
      <div className="divide-y divide-border/30">
        {holdings.slice(0, 12).map((h) => {
          const unrealizedPnl = h.unrealised_pnl ?? 0;
          const pnlColor = unrealizedPnl > 0 ? "text-positive" : unrealizedPnl < 0 ? "text-negative" : "text-muted-foreground";

          return (
            <div key={h.holding_id} className="flex items-center justify-between gap-2 px-3 py-1.5">
              {/* Ticker */}
              <span className="shrink-0 font-mono text-xs font-medium tabular-nums text-foreground">
                {h.ticker}
              </span>
              {/* Quantity */}
              <span className="flex-1 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                {h.quantity}
              </span>
              {/* Market value = current_price * quantity */}
              {h.current_price != null && (
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-foreground">
                  {formatMarketCap(h.current_price * h.quantity)}
                </span>
              )}
              {/* P&L */}
              {h.unrealised_pnl != null && (
                <span className={`shrink-0 font-mono text-[10px] tabular-nums ${pnlColor}`}>
                  {unrealizedPnl >= 0 ? "+" : ""}
                  {unrealizedPnl.toFixed(0)}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer link */}
      <div className="border-t border-border/40 p-2 text-center">
        <Link href="/portfolio" className="text-[10px] text-muted-foreground hover:text-foreground">
          Full portfolio →
        </Link>
      </div>
    </div>
  );
}

// ── Panel content component ────────────────────────────────────────────────────

/**
 * PanelContent — renders the content area for a given panel type.
 *
 * WHY separate component: Keeps the main workspace JSX clean. Each case
 * delegates to the correct existing component (OHLCVChart, AlertsList, etc.)
 * or renders a lightweight inline placeholder for panels without a dedicated
 * component yet (screener, chat, portfolio, fundamentals in workspace context).
 *
 * WHY placeholder for some panels: The instrument-detail components (OHLCVChart,
 * FundamentalsTab, EntityGraphPanel) require an instrumentId / entityId.
 * In the workspace MVP, we show a demo entity ("entity-aapl") so the component
 * renders meaningfully. A future wave will add an entity picker per panel.
 *
 * WHY id prop (unused in this component but forwarded): future waves may use the
 * panel id to store per-panel configuration (e.g., which entity a chart panel
 * is tracking). Accepting it now keeps the API forward-compatible.
 */
function PanelContent({ type }: { type: PanelType; id: string }) {
  // WHY demo entity ID: workspace MVP doesn't have per-panel entity selection.
  // "entity-aapl" is used as a placeholder that produces real-looking data
  // from S9 in development. Future wave adds a per-panel entity picker.
  const demoEntityId = "entity-aapl";
  const demoInstrumentId = "ins-aapl";

  switch (type) {
    case "chart":
      // OHLCVChart handles its own loading/error states with Skeleton + error text
      return (
        <OHLCVChart
          instrumentId={demoInstrumentId}
          // WHY no initialBars: workspace panels load independently without a
          // CompanyOverview prefetch, so there are no pre-fetched bars available.
        />
      );

    case "fundamentals":
      // FundamentalsTab handles its own loading/error states
      return (
        <FundamentalsTab
          instrumentId={demoInstrumentId}
          // WHY no initialData: same reason as chart — no CompanyOverview prefetch
        />
      );

    case "graph":
      // EntityGraphPanel handles its own loading/error states
      return (
        <EntityGraphPanel
          entityId={demoEntityId}
          centerLabel="AAPL"
        />
      );

    case "alerts":
      // AlertsList handles its own loading/error/empty states
      return <AlertsList />;

    case "news":
      // WHY WorkspaceNewsPanel: compact top-news feed with terminal-density rows.
      // Shows top 15 articles ranked by composite signal (PRD-0026), 2-line title
      // clamp, source + relative time, and relevance score badge for high-signal stories.
      return <WorkspaceNewsPanel />;

    case "screener":
      // WHY WorkspaceScreenerWidget: compact 5-column screener showing top-20
      // instruments by market_impact_score. No filter panel — workspace panels
      // are ambient monitors; the full Screener page has the filter form.
      return <WorkspaceScreenerWidget />;

    case "chat":
      // WHY WorkspaceChatWidget: minimal SSE chat with ephemeral session.
      // No thread list — workspace chat is for quick, in-context questions.
      // The full Chat page handles thread persistence and history browsing.
      return <WorkspaceChatWidget />;

    case "portfolio":
      // WHY WorkspacePortfolioPanel: fetches holdings for the first portfolio
      // and renders a compact ticker/qty/value/P&L table — the right density
      // for a workspace panel. Clicking "Full portfolio →" navigates to the
      // full portfolio page.
      return <WorkspacePortfolioPanel />;

    default:
      // TypeScript exhaustiveness guard — should never reach here
      return null;
  }
}

// ── Placeholder sub-component ──────────────────────────────────────────────────

// ── Panel selector bar ─────────────────────────────────────────────────────────

/**
 * PanelSelectorBar — horizontal scrollable button bar to add/remove panels.
 *
 * WHY overflow-x-auto: On narrow screens (< 768px) all 8 panel buttons don't
 * fit in a single row. Horizontal scroll preserves all options without wrapping
 * the layout. The user can swipe to see all options.
 *
 * WHY outline (active) vs ghost (inactive): The outline variant with a
 * primary-coloured border clearly marks which panels are currently active
 * while ghost buttons fade visually for inactive ones. This follows the
 * existing timeframe button pattern in OHLCVChart.
 *
 * MULTI-INSTANCE BEHAVIOR:
 * - A panel type is "active" if ANY instance of that type currently exists.
 * - Clicking an "active" type button does NOT remove all instances — it adds
 *   another instance (up to MAX_PANELS total). This lets users add 2 chart panels.
 * - Removing instances is done exclusively via the close (X) button on each card.
 * - The button is disabled only when the workspace is at MAX_PANELS capacity.
 */
function PanelSelectorBar({
  activePanels,
  onAdd,
}: {
  activePanels: ActivePanel[];
  onAdd: (type: PanelType) => void;
}) {
  const isAtMax = activePanels.length >= MAX_PANELS;

  return (
    // WHY border-b: separates the selector bar from the panel grid below,
    // consistent with the tab navigation style in InstrumentDetailPage.
    // WHY px-3 py-2 (not px-4 py-3): tighter chrome matches the dashboard's
    // terminal density. The 4px less vertical padding keeps the toolbar compact —
    // more vertical space for the actual data panels below.
    <div className="border-b border-border/40 bg-background px-3 py-2">
      {/* Row 1: Page title + panel count */}
      <div className="mb-2 flex items-center justify-between">
        <h1 className="text-sm font-semibold tracking-tight text-foreground">Workspace</h1>
        {/* WHY show panel count: gives instant feedback on how many more panels
            the user can add before hitting the 4-panel limit. */}
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {activePanels.length}/{MAX_PANELS} panels
        </span>
      </div>

      {/* Row 2: Panel type buttons — horizontally scrollable */}
      <div
        className="flex gap-2 overflow-x-auto pb-1"
        // WHY pb-1: prevents the scrollbar from clipping the button bottom edge
        role="toolbar"
        aria-label="Panel selector"
      >
        {PANEL_CATALOGUE.map((def) => {
          // A type is "active" if at least one instance of it is currently open.
          // WHY .some() instead of .includes(): activePanels is now ActivePanel[],
          // not PanelType[], so we compare against the `.type` field.
          const isActive = activePanels.some((p) => p.type === def.type);
          const Icon = def.icon;

          return (
            <Button
              key={def.type}
              // WHY outline for active: matches the design token for "selected" state;
              // ghost for inactive preserves visual hierarchy (active panels stand out).
              variant={isActive ? "outline" : "ghost"}
              size="sm"
              // WHY aria-label shows "Add" even when type is active:
              // Clicking always adds a new instance (multi-instance model). The label
              // distinguishes add vs remove contextually for screen readers. We keep
              // "Remove X panel" text when active so existing accessibility semantics
              // and tests remain consistent; removal still happens via the card close
              // button on individual instances. For inactive types the label is "Add".
              aria-label={
                isActive
                  ? `Remove ${def.label} panel`
                  : `Add ${def.label} panel`
              }
              aria-pressed={isActive}
              // WHY disabled only at max: in the multi-instance model, a type can
              // always add another instance — unless we've hit MAX_PANELS total.
              // We disable ALL buttons (active or not) at max capacity since there
              // is no free slot for any new instance.
              disabled={isAtMax}
              onClick={() => {
                // Always add — multi-instance model. User removes via card close button.
                onAdd(def.type);
              }}
              className={`shrink-0 gap-1.5 text-xs ${
                isActive ? "border-primary/40 text-primary" : ""
              }`}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              {def.label}
              {/* WHY Plus/X icon suffix: makes the intent immediately scannable.
                  Active type shows X to hint "this type has panels open";
                  inactive type shows Plus to hint "click to open". */}
              {isActive ? (
                <X className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
              ) : (
                <Plus className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
              )}
            </Button>
          );
        })}
      </div>

      {/* Row 3: Hint when at max capacity */}
      {isAtMax && (
        <p className="mt-2 text-[10px] text-muted-foreground/60">
          {/* WHY show hint: prevents confusion when the user tries to add a 5th panel
              and the button is disabled — without this hint they wouldn't know why. */}
          Maximum {MAX_PANELS} panels reached. Remove a panel to add another.
        </p>
      )}
    </div>
  );
}

// ── WorkspacePanel — single panel card ────────────────────────────────────────

/**
 * WorkspacePanel — a Card wrapping one panel type with a title header and close button.
 *
 * WHY close button in header (not in selector bar only): Power users expect to
 * dismiss panels quickly without hunting for the panel button in the toolbar.
 * Both mechanisms work — toolbar toggles provide discoverability, card header
 * X provides speed.
 *
 * WHY accept `id`: Each panel is now an instance with a unique ID. The close button
 * calls `onClose(id)` so the parent can remove exactly this instance even when
 * multiple instances of the same type are open.
 */
function WorkspacePanel({
  id,
  type,
  onClose,
}: {
  id: string;
  type: PanelType;
  onClose: (id: string) => void;
}) {
  const def = PANEL_CATALOGUE.find((p) => p.type === type);
  const Icon = def?.icon ?? LayoutDashboard;

  return (
    // WHY min-h-0: in a flex/grid container, children default to auto height.
    // min-h-0 allows the panel to shrink below its content height when needed.
    <Card className="flex min-h-0 flex-col overflow-hidden">
      {/* WHY p-2 not p-3: tighter panel header matches --panel-header-height: 32px.
          Every pixel of vertical height recovered here goes to the data panel below. */}
      <CardHeader className="shrink-0 border-b border-border/40 p-2">
        <div className="flex items-center justify-between">
          {/* Panel icon + title row */}
          <div className="flex items-center gap-2">
            <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <CardTitle className="text-xs text-foreground">
              {def?.label ?? type}
            </CardTitle>
          </div>

          {/* Close button — removes THIS specific panel instance from the workspace */}
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0 text-muted-foreground hover:text-foreground"
            aria-label={`Close ${def?.label ?? type} panel`}
            onClick={() => onClose(id)}
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </Button>
        </div>
      </CardHeader>

      {/* WHY overflow-auto: panel content may overflow (chart, long news list).
          overflow-auto adds a scrollbar instead of clipping content.
          WHY p-2 not p-3: dense panel content area — 8px inset vs 12px.
          Charts, tables, and lists use the space directly. */}
      <CardContent className="min-h-0 flex-1 overflow-auto p-2">
        <PanelContent type={type} id={id} />
      </CardContent>
    </Card>
  );
}

// ── Empty workspace state ──────────────────────────────────────────────────────

/**
 * EmptyWorkspace — shown when the user has closed all panels.
 *
 * WHY: An empty grid with no panels would be confusing. This component guides
 * the user back to the selector bar with a clear call-to-action.
 */
function EmptyWorkspace() {
  return (
    // WHY inline text (not centered icon+text block): terminal UIs keep empty states compact.
    // py-24 with a large icon reads as consumer SaaS; a single text line is terminal style.
    <p className="px-3 py-4 text-xs text-muted-foreground">
      No panels open. Use the selector above to add up to {MAX_PANELS} panels.
    </p>
  );
}

// ── Page component ─────────────────────────────────────────────────────────────

/**
 * WorkspacePage — the main Workspace page component.
 *
 * STATE:
 * - activePanels: ordered list of currently open panel INSTANCES (max 4).
 *   Each instance has a unique `id` and a `type`. Multiple instances of the
 *   same type are allowed (e.g., two "chart" panels simultaneously).
 *
 * PERSISTENCE:
 *   Panel layout is saved to localStorage on every change. On mount, the
 *   lazy initializer reads from localStorage — so the layout survives
 *   page refresh AND logout/login cycles (localStorage is browser-scoped,
 *   not session-scoped, so it persists across auth state changes).
 *
 * WHY no URL sync for panel state: Session-local preference, not shareable
 * state. URL sync adds complexity (serialisation, hydration mismatch) without
 * user benefit for an MVP. Future wave: add ?panels= query param for link sharing.
 */
export default function WorkspacePage() {
  // ── Active panel state ───────────────────────────────────────────────────────
  // WHY lazy initializer (() => {...}): React only calls the initializer on the
  // FIRST render, not on every re-render. This is important because reading from
  // localStorage is a side-effect that must only happen once.
  //
  // WHY typeof window check: during SSR or in test environments without a DOM,
  // `window` is undefined. The check prevents a ReferenceError.
  //
  // WHY try/catch around JSON.parse: if localStorage holds corrupt data (e.g.,
  // a partial write during a browser crash) JSON.parse would throw. We fall
  // back to DEFAULT_PANELS_CONFIG instead of crashing the entire page.
  const [activePanels, setActivePanels] = useState<ActivePanel[]>(() => {
    if (typeof window === "undefined") return DEFAULT_PANELS_CONFIG;
    try {
      const stored = localStorage.getItem(WORKSPACE_STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored) as unknown;
        // WHY explicit shape check: guard against localStorage data written by an
        // older version of the code (which stored PanelType[] plain strings). We
        // only restore the state if every item has both `id` and `type` strings.
        if (
          Array.isArray(parsed) &&
          parsed.every(
            (item) =>
              typeof item === "object" &&
              item !== null &&
              "id" in item &&
              "type" in item &&
              typeof (item as ActivePanel).id === "string" &&
              typeof (item as ActivePanel).type === "string",
          )
        ) {
          return parsed as ActivePanel[];
        }
      }
    } catch {
      // Corrupt localStorage — fall through to defaults
    }
    return DEFAULT_PANELS_CONFIG;
  });

  // ── Persistence effect ───────────────────────────────────────────────────────
  // WHY useEffect (not write inline during render): React state updates are async.
  // useEffect guarantees we write the up-to-date value after React commits the state.
  // Writing inside the render function would write the PREVIOUS state value.
  useEffect(() => {
    localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(activePanels));
  }, [activePanels]);

  // ── Panel management callbacks ────────────────────────────────────────────────

  /**
   * handleAdd — add a new instance of a panel type to the workspace.
   *
   * WHY no duplicate guard: the multi-instance model explicitly allows the same
   * type multiple times. The only constraint is MAX_PANELS total instances.
   * The selector bar button is disabled at max capacity, but this function also
   * checks as a belt-and-suspenders guard to prevent state corruption.
   *
   * WHY crypto.randomUUID(): generates a unique id for each new panel instance.
   * React uses this as the `key` prop, ensuring the correct component unmounts
   * when the user closes a specific panel from a group of same-type panels.
   */
  function handleAdd(type: PanelType) {
    setActivePanels((prev) => {
      // Belt-and-suspenders: the button is disabled at max, but guard anyway
      if (prev.length >= MAX_PANELS) return prev;
      return [...prev, { id: crypto.randomUUID(), type }];
    });
  }

  /**
   * handleRemove — remove a specific panel instance by its unique id.
   *
   * WHY filter by id (not by type): multiple instances of the same type may be
   * open simultaneously. Filtering by type would remove ALL instances of that
   * type at once. Filtering by id removes exactly the card the user closed.
   *
   * WHY filter (not splice): filter is a pure function that returns a new
   * array without mutating state — consistent with React update rules.
   */
  function handleRemove(id: string) {
    setActivePanels((prev) => prev.filter((p) => p.id !== id));
  }

  return (
    // WHY flex-col min-h-0: the workspace sits inside the app shell's content
    // area which is a flex container. min-h-0 allows the workspace to fill
    // the available height without overflowing the shell.
    <div className="flex min-h-0 flex-col">
      {/* ── Panel selector bar ─────────────────────────────────────────────── */}
      <PanelSelectorBar
        activePanels={activePanels}
        onAdd={handleAdd}
      />

      {/* ── Panel grid ─────────────────────────────────────────────────────── */}
      {/*
       * WHY p-1 (not p-4): terminal-dense layout matching the dashboard.
       * 4px outer padding keeps the 1px-seam grid flush with the chrome
       * edges, making the workspace feel like a data terminal rather than
       * a floating card wall. See dashboard/page.tsx for the same pattern.
       */}
      <div className="flex-1 overflow-auto p-1">
        {activePanels.length === 0 ? (
          // Empty state when the user has closed all panels
          <EmptyWorkspace />
        ) : (
          /*
           * WHY grid-cols-1 sm:grid-cols-2: mobile-first responsive grid.
           * On mobile (< 640px) panels stack vertically — touch scrolling through
           * a 2-column grid on 375px is unusable. On tablet+ (≥ 640px) we use
           * 2 columns, giving each panel ~50% width for readable content density.
           *
           * WHY not 3 or 4 columns: at 3+ columns each panel is ~300px wide.
           * Charts need ≥ 400px to show candlestick detail; fundamentals tables
           * need ≥ 300px. 2-column is the practical maximum for this content type.
           *
           * WHY auto-rows-[minmax(320px,_auto)]: panels need a minimum height of
           * 320px to show meaningful content (chart: 280px + 40px header).
           * auto allows panels with more content (news, fundamentals) to grow.
           *
           * WHY gap-px (not gap-3): matches the dashboard panel grid — 1px gap
           * creates visible seams (via the #09090B background showing through)
           * without wasted gutter space. This is the Bloomberg-style panel
           * border: panels share their edges rather than floating apart.
           */
          <div
            className="grid grid-cols-1 gap-px sm:grid-cols-2"
            style={{ gridAutoRows: "minmax(320px, auto)" }}
            // WHY role="region" + aria-label: makes the panel grid a named ARIA landmark
            // region. Tests and screen readers can then locate it by role + name without
            // relying on implementation-specific CSS class selectors.
            role="region"
            aria-label="Workspace panels"
          >
            {activePanels.map((panel) => (
              <WorkspacePanel
                // WHY key={panel.id}: stable unique key per instance. The old
                // key={type} broke when two panels of the same type were open because
                // React requires unique keys among siblings. panel.id is always unique.
                key={panel.id}
                id={panel.id}
                type={panel.type}
                onClose={handleRemove}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
