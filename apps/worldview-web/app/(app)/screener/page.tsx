/**
 * app/(app)/screener/page.tsx — Instrument Screener
 *
 * WHY THIS EXISTS: The screener is a power-user feature inspired by Finviz and
 * Bloomberg's equity screening tools. It lets research analysts and quant traders
 * filter the instrument universe by sector, market cap, and free-text name/ticker
 * search, then sort the result table to surface actionable ideas.
 *
 * WHY LAYOUT (filter panel + table):
 * Left panel holds filters (w-64 fixed). Right side is the results table (flex-1).
 * This mirrors Finviz's layout — users familiar with any screener tool will
 * recognise the pattern immediately, reducing cognitive load.
 *
 * WHY APPLY BUTTON (not live filter):
 * Sending a POST to S9 on every keystroke would hammer the backend unnecessarily.
 * The screener endpoint runs a database query. Gating the request behind an
 * explicit "Apply" gives the user control and S9 a chance to breathe.
 *
 * WHY CLIENT-SIDE SORT (not server-sort re-query):
 * For < 100 results the table fits in memory. Re-querying on every column click
 * adds 200–400ms of latency and is annoying. Client sort is instant.
 * For larger result sets, future work can add sort_by/sort_dir to the request.
 *
 * WHY OFFSET PAGINATION ("Load more"):
 * The screener can return thousands of rows. A "Load more" button accumulates
 * rows in state rather than replacing them — this lets the user scroll back to
 * compare rows they already saw without losing their place.
 *
 * WHO USES IT: Research analysts (F4 journey), quant traders (F5 journey)
 * DATA SOURCE: POST /api/v1/fundamentals/screen (S9 → S3 fundamentals)
 * DESIGN REFERENCE: PRD-0028 §6.5 Screener page, canvas State D (screener panel)
 */

"use client";
// WHY "use client": uses useState (filter form state, sort state, accumulated rows),
// useCallback (memoised handlers), and TanStack Query useQuery. These are all
// client-side React features not available in Server Components.

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { HeatCell } from "@/components/screener/HeatCell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatPercent,
  formatMarketCap,
  priceChangeClass,
} from "@/lib/utils";
import type { ScreenerResult, ScreenerRequest, ScreenerResponse } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20;

/**
 * GICS sectors — these are the 11 official Global Industry Classification
 * Standard sectors. Offering them as a dropdown is standard in all
 * professional screeners (Finviz, Koyfin, Bloomberg).
 */
const GICS_SECTORS = [
  "Information Technology",
  "Health Care",
  "Financials",
  "Consumer Discretionary",
  "Consumer Staples",
  "Communication Services",
  "Industrials",
  "Materials",
  "Real Estate",
  "Utilities",
  "Energy",
] as const;

/**
 * Market cap tier thresholds in USD.
 * Conventions from institutional research:
 * - Large cap: > $10B (Russell 1000 constituents typical range)
 * - Mid cap:   $2B–$10B
 * - Small cap: < $2B
 */
type CapTier = "ALL" | "LARGE" | "MID" | "SMALL";

const CAP_TIERS: Array<{ value: CapTier; label: string; description: string }> = [
  { value: "ALL",   label: "All",   description: "No market cap filter" },
  { value: "LARGE", label: "Large", description: "> $10B" },
  { value: "MID",   label: "Mid",   description: "$2B–$10B" },
  { value: "SMALL", label: "Small", description: "< $2B" },
];

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * SortState — tracks which column is active and its direction.
 * null key = no sort applied (data in S9 response order).
 */
interface SortState {
  key: keyof ScreenerResult | null;
  dir: "asc" | "desc";
}

/**
 * FilterState — the controlled values of the filter panel form.
 * Applied to the ScreenerRequest only when the user clicks "Apply".
 */
interface FilterState {
  search: string;
  sector: string; // "" = all sectors
  capTier: CapTier;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * buildFilters — converts the UI filter state into ScreenerFilter[] for the API.
 *
 * WHY separate from component state: the ScreenerRequest.filters array uses a
 * structured {field, operator, value} format (PRD-0028 §6.2). The UI exposes
 * friendlier controls (dropdowns, radio groups). This function bridges the two.
 */
function buildFilters(filters: FilterState): ScreenerRequest["filters"] {
  const result: ScreenerRequest["filters"] = [];

  // Free-text search: pass as a "name_ticker" field (S9 handles OR matching)
  // WHY "contains" operator: ticker and name are string fields on the instrument
  if (filters.search.trim()) {
    result.push({
      field: "name_ticker",
      operator: "contains",
      value: filters.search.trim(),
    });
  }

  // Sector filter — exact match on gics_sector GICS string
  if (filters.sector) {
    result.push({
      field: "gics_sector",
      operator: "eq",
      value: filters.sector,
    });
  }

  // Market cap tier — translated into gt/lt numeric range filters
  if (filters.capTier === "LARGE") {
    result.push({ field: "market_cap", operator: "gt", value: 10_000_000_000 });
  } else if (filters.capTier === "MID") {
    result.push({ field: "market_cap", operator: "gt", value: 2_000_000_000 });
    result.push({ field: "market_cap", operator: "lt", value: 10_000_000_000 });
  } else if (filters.capTier === "SMALL") {
    result.push({ field: "market_cap", operator: "lt", value: 2_000_000_000 });
  }

  return result;
}

/**
 * sortResults — pure client-side sort for the accumulated results array.
 *
 * WHY handle null values: many fundamental fields (market_cap, daily_return,
 * market_impact_score) are nullable. Null values sort to the bottom in both
 * asc and desc directions so the user always sees data-rich rows first.
 */
function sortResults(
  results: ScreenerResult[],
  sort: SortState,
): ScreenerResult[] {
  if (!sort.key) return results;

  const key = sort.key;
  const dir = sort.dir === "asc" ? 1 : -1;

  return [...results].sort((a, b) => {
    const av = a[key];
    const bv = b[key];

    // Nulls always go to the bottom regardless of direction
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;

    // Numeric comparison
    if (typeof av === "number" && typeof bv === "number") {
      return (av - bv) * dir;
    }

    // String comparison (ticker, name)
    return String(av).localeCompare(String(bv)) * dir;
  });
}

// ── Column definitions ────────────────────────────────────────────────────────

/**
 * Column — metadata for a table column.
 * WHY header + sortKey separate: the display label ("Change%") differs from the
 * ScreenerResult field name ("daily_return"). Also, some columns may not be
 * sortable (e.g., "Score" when all scores are null).
 */
interface Column {
  header: string;
  sortKey: keyof ScreenerResult | null;
  align: "left" | "right";
}

const COLUMNS: Column[] = [
  { header: "Ticker",    sortKey: "ticker",             align: "left"  },
  { header: "Name",      sortKey: "name",               align: "left"  },
  { header: "Price",     sortKey: null,                 align: "right" }, // no price in ScreenerResult
  { header: "Change%",   sortKey: "daily_return",       align: "right" },
  { header: "Mkt Cap",   sortKey: "market_cap",         align: "right" },
  { header: "Score",     sortKey: "market_impact_score", align: "right" },
];

// ── Page component ────────────────────────────────────────────────────────────

export default function ScreenerPage() {
  const router = useRouter();
  const { accessToken } = useAuth();

  // ── Filter form state (pending — not yet submitted) ────────────────────────
  // WHY "pending" naming: distinguishes form state from applied/committed state.
  // The query only fires when the user clicks Apply (appliedFilters changes).
  const [pendingFilters, setPendingFilters] = useState<FilterState>({
    search: "",
    sector: "",
    capTier: "ALL",
  });

  // ── Applied filters (committed — triggers the S9 query) ───────────────────
  const [appliedFilters, setAppliedFilters] = useState<FilterState>({
    search: "",
    sector: "",
    capTier: "ALL",
  });

  // ── Pagination offset ─────────────────────────────────────────────────────
  // WHY accumulated rows (not page replace): "Load more" appends to allResults
  // so users can scroll back to compare previously loaded rows.
  const [offset, setOffset] = useState(0);
  const [allResults, setAllResults] = useState<ScreenerResult[]>([]);

  // ── Sort state ────────────────────────────────────────────────────────────
  const [sort, setSort] = useState<SortState>({ key: null, dir: "desc" });

  // ── S9 screener query ─────────────────────────────────────────────────────
  const request: ScreenerRequest = {
    filters: buildFilters(appliedFilters),
    limit: PAGE_SIZE,
    offset,
  };

  const { data, isLoading, isError, isFetching } = useQuery<ScreenerResponse>({
    // WHY include filters+offset in key: different filter combinations and pages
    // must be cached separately. JSON.stringify is safe here — shallow object.
    queryKey: ["screener", JSON.stringify(appliedFilters), offset],
    queryFn: () => createGateway(accessToken).runScreener(request),
    enabled: !!accessToken,
    // WHY no refetchInterval: screener is user-initiated. Automatic refetch would
    // discard the user's scroll position and re-sort, which is disorienting.
    staleTime: 60_000,
    // WHY no retry: screener query failures should be reported immediately, not
    // silently retried 3 times causing the user to wonder if the page is stuck.
    retry: false,
  });

  // ── Accumulate results across pages ───────────────────────────────────────
  // WHY useCallback + data dependency: when data arrives for a new page,
  // append to allResults. Reset on filter change (offset resets to 0).
  // This runs in the render path (not useEffect) to avoid a render cycle.
  const currentPageKey = JSON.stringify(appliedFilters) + offset;
  const [lastPageKey, setLastPageKey] = useState(currentPageKey);

  if (data && currentPageKey !== lastPageKey) {
    setLastPageKey(currentPageKey);
    if (offset === 0) {
      // WHY replace on offset=0: this is a new filter run, not load-more.
      setAllResults(data.results);
    } else {
      // WHY spread: React state must be a new array reference to trigger re-render
      setAllResults((prev) => [...prev, ...data.results]);
    }
  } else if (data && offset === 0 && allResults.length === 0 && data.results.length > 0) {
    // Initial load: populate results
    setAllResults(data.results);
  }

  // ── Handlers ──────────────────────────────────────────────────────────────

  /**
   * handleApply — commit the pending filter form state to trigger a new query.
   * WHY reset offset to 0: a new filter run always starts from the first page.
   */
  const handleApply = useCallback(() => {
    setOffset(0);
    setAllResults([]);
    setLastPageKey(""); // force accumulation logic to re-run
    setAppliedFilters({ ...pendingFilters });
  }, [pendingFilters]);

  /**
   * handleReset — clear all filters back to defaults.
   */
  const handleReset = useCallback(() => {
    const empty: FilterState = { search: "", sector: "", capTier: "ALL" };
    setPendingFilters(empty);
    setAppliedFilters(empty);
    setOffset(0);
    setAllResults([]);
    setLastPageKey("");
  }, []);

  /**
   * handleLoadMore — increment offset to fetch the next page.
   * The query key changes → TanStack Query fires the next request.
   */
  const handleLoadMore = useCallback(() => {
    setOffset((prev) => prev + PAGE_SIZE);
  }, []);

  /**
   * handleRowClick — navigate to the instrument detail page.
   * WHY entity_id (not instrument_id): per ADR-F-12, the instrument detail route
   * is keyed on entity_id because the entity is the stable identity (one entity
   * can have multiple instrument_ids across exchanges).
   */
  const handleRowClick = useCallback(
    (result: ScreenerResult) => {
      router.push(`/instruments/${result.entity_id}`);
    },
    [router],
  );

  /**
   * handleSort — toggle sort column/direction.
   * Same column → flip direction. New column → default to desc.
   * WHY default desc: high values (large market cap, high score) are more
   * interesting than low values, so descending is the natural default.
   */
  const handleSort = useCallback((key: keyof ScreenerResult | null) => {
    if (!key) return; // unsortable column (e.g., Price, which isn't in ScreenerResult)
    setSort((prev) => ({
      key,
      dir: prev.key === key && prev.dir === "desc" ? "asc" : "desc",
    }));
  }, []);

  // ── Derived data ──────────────────────────────────────────────────────────

  // Sort accumulated results client-side — fast for < 100 rows, acceptable up to 500
  const sortedResults = sortResults(allResults, sort);

  // Total count from the last successful response (or accumulated count)
  const totalCount = data?.total ?? allResults.length;
  const hasMore = data ? offset + PAGE_SIZE < data.total : false;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    // WHY h-full overflow-hidden: the (app) layout fills the viewport height.
    // We want the table to scroll independently, not the whole page.
    <div className="flex h-full overflow-hidden">

      {/* ── Filter Panel (left, fixed width) ───────────────────────────────── */}
      {/*
        WHY w-64: narrower than the spec's w-72 — the filter panel has only 3
        controls. w-64 gives the results table more breathing room.
        shrink-0 prevents the panel from collapsing when the table grows.
      */}
      <aside
        className="flex w-64 shrink-0 flex-col gap-4 border-r border-border bg-card p-4 overflow-y-auto"
        aria-label="Filter panel"
      >
        {/* Panel heading */}
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Filters
          </h2>
        </div>

        {/* ── Search input ────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="screener-search"
            className="text-xs font-medium text-muted-foreground"
          >
            Name / Ticker
          </label>
          <Input
            id="screener-search"
            type="search"
            placeholder="e.g. AAPL, Apple..."
            value={pendingFilters.search}
            onChange={(e) =>
              setPendingFilters((prev) => ({ ...prev, search: e.target.value }))
            }
            // WHY onKeyDown Enter: power users expect Enter to submit the form
            // instead of clicking Apply — standard web form behaviour
            onKeyDown={(e) => {
              if (e.key === "Enter") handleApply();
            }}
            aria-label="Search instruments by name or ticker"
          />
        </div>

        {/* ── Sector dropdown ─────────────────────────────────────────────── */}
        {/*
          WHY native <select>: no shadcn Select component exists in this project.
          Adding Radix Select for a single filter would pull in extra bundle weight.
          The native <select> is accessible, keyboard-navigable, and easier to
          style with Tailwind's appearance-none approach.
        */}
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="screener-sector"
            className="text-xs font-medium text-muted-foreground"
          >
            Sector (GICS)
          </label>
          <select
            id="screener-sector"
            value={pendingFilters.sector}
            onChange={(e) =>
              setPendingFilters((prev) => ({ ...prev, sector: e.target.value }))
            }
            // WHY these classes: matches the Input component's visual style
            // (border-border, bg-muted, h-9) for visual consistency.
            // appearance-none removes the OS-default dropdown arrow so we
            // have full control over padding and text colour.
            className="h-9 w-full rounded-md border border-border bg-muted px-3 py-1 text-sm text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring appearance-none"
            aria-label="Filter by GICS sector"
          >
            <option value="">All sectors</option>
            {GICS_SECTORS.map((sector) => (
              <option key={sector} value={sector}>
                {sector}
              </option>
            ))}
          </select>
        </div>

        {/* ── Market cap tier buttons ──────────────────────────────────────── */}
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">
            Market Cap
          </span>
          {/*
            WHY radio-button-style segment control:
            Cap tier is mutually exclusive (you can't be LARGE and SMALL at the
            same time). A visual segment control communicates exclusivity better
            than a dropdown. Uses button elements with active/inactive variants.
          */}
          <div className="grid grid-cols-2 gap-1">
            {CAP_TIERS.map((tier) => (
              <button
                key={tier.value}
                type="button"
                title={tier.description}
                onClick={() =>
                  setPendingFilters((prev) => ({ ...prev, capTier: tier.value }))
                }
                // WHY conditional classes: active tier gets primary colour so
                // users see which filter is selected at a glance.
                className={
                  pendingFilters.capTier === tier.value
                    ? "rounded-md px-2 py-1 text-xs font-medium bg-primary text-primary-foreground"
                    : "rounded-md px-2 py-1 text-xs font-medium border border-border bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground"
                }
                aria-pressed={pendingFilters.capTier === tier.value}
                aria-label={`${tier.label} cap: ${tier.description}`}
              >
                {tier.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Action buttons ───────────────────────────────────────────────── */}
        <div className="mt-auto flex flex-col gap-2 pt-4">
          {/*
            WHY Apply first: primary action should have primary visual weight.
            Reset is secondary — it's destructive (clears filters) so it gets
            the outline variant that's visually recessive.
          */}
          <Button
            onClick={handleApply}
            disabled={isFetching}
            className="w-full"
            aria-label="Apply filters and run screener"
          >
            {isFetching ? "Running…" : "Apply"}
          </Button>
          <Button
            variant="outline"
            onClick={handleReset}
            disabled={isFetching}
            className="w-full"
            aria-label="Reset all filters to defaults"
          >
            Reset
          </Button>
        </div>
      </aside>

      {/* ── Results Area (right, flex-1) ─────────────────────────────────────── */}
      <main className="flex flex-1 flex-col overflow-hidden">

        {/* ── Results header bar ────────────────────────────────────────────── */}
        <div className="flex items-center justify-between border-b border-border px-4 py-2">
          <h1 className="text-sm font-semibold text-foreground">
            Instrument Screener
          </h1>
          {/* WHY show count even during fetch: keeps the user oriented.
              "Loading…" is shown only when there are no accumulated results yet. */}
          <span className="text-xs text-muted-foreground font-mono tabular-nums">
            {isLoading && allResults.length === 0
              ? "Loading…"
              : `${totalCount.toLocaleString()} instruments found`}
          </span>
        </div>

        {/* ── Scrollable table area ────────────────────────────────────────── */}
        <div className="flex-1 overflow-auto">

          {/* ── Error state ─────────────────────────────────────────────────── */}
          {isError && allResults.length === 0 && (
            <div
              className="flex h-32 items-center justify-center"
              role="alert"
              aria-live="assertive"
            >
              <p className="text-sm text-destructive">
                Screener unavailable. Please try again.
              </p>
            </div>
          )}

          {/* ── Results table ───────────────────────────────────────────────── */}
          {/* WHY show table even during isLoading: if we already have allResults
              from a prior query, keep showing them while load-more fetches.
              Only show skeleton rows on the very first load (allResults empty). */}
          {(allResults.length > 0 || isLoading) && !isError && (
            <table
              className="w-full border-collapse text-sm"
              aria-label="Screener results"
            >
              {/* ── Table header ────────────────────────────────────────────── */}
              <thead className="sticky top-0 z-10 bg-card">
                <tr className="border-b border-border">
                  {COLUMNS.map((col) => (
                    <th
                      key={col.header}
                      // WHY cursor-pointer + hover only when sortKey exists:
                      // unsortable columns (Price) should not imply clickability
                      className={[
                        "px-3 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground",
                        col.align === "right" ? "text-right" : "text-left",
                        col.sortKey ? "cursor-pointer select-none hover:text-foreground" : "",
                      ].join(" ")}
                      onClick={() => col.sortKey && handleSort(col.sortKey)}
                      aria-sort={
                        sort.key === col.sortKey
                          ? sort.dir === "asc"
                            ? "ascending"
                            : "descending"
                          : col.sortKey
                          ? "none"
                          : undefined
                      }
                      scope="col"
                    >
                      {col.header}
                      {/* Sort indicator — only shown for the active column */}
                      {sort.key === col.sortKey && (
                        <span
                          className="ml-1 inline-block"
                          aria-hidden="true"
                        >
                          {sort.dir === "asc" ? "↑" : "↓"}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>

              {/* ── Table body ──────────────────────────────────────────────── */}
              <tbody>
                {/* ── Loading skeleton rows (initial load only) ─────────────── */}
                {isLoading && allResults.length === 0 &&
                  Array.from({ length: 8 }).map((_, i) => (
                    <tr key={`skel-${i}`} className="border-b border-border/50">
                      {COLUMNS.map((col) => (
                        <td key={col.header} className="px-3 py-2">
                          {/* WHY varying widths: mimics real data shapes so the
                              skeleton gives a realistic preview of the layout */}
                          <Skeleton
                            className={[
                              "h-4",
                              col.header === "Name" ? "w-36" :
                              col.header === "Ticker" ? "w-12" :
                              col.header === "Score" ? "w-10" :
                              "w-20",
                            ].join(" ")}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}

                {/* ── Data rows ─────────────────────────────────────────────── */}
                {sortedResults.map((result) => (
                  <ScreenerRow
                    key={result.instrument_id}
                    result={result}
                    onClick={handleRowClick}
                  />
                ))}
              </tbody>
            </table>
          )}

          {/* ── Empty state (no results, not loading, no error) ───────────────── */}
          {!isLoading && !isError && allResults.length === 0 && (
            <div
              className="flex h-32 items-center justify-center"
              role="status"
              aria-live="polite"
            >
              <p className="text-sm text-muted-foreground">
                No instruments match the current filters
              </p>
            </div>
          )}

          {/* ── Load more button ──────────────────────────────────────────────── */}
          {hasMore && !isLoading && (
            <div className="flex justify-center py-4">
              <Button
                variant="outline"
                size="sm"
                onClick={handleLoadMore}
                disabled={isFetching}
                aria-label={`Load more instruments (currently showing ${allResults.length} of ${totalCount})`}
              >
                {isFetching ? "Loading…" : `Load more (${allResults.length} / ${totalCount})`}
              </Button>
            </div>
          )}

          {/* WHY bottom padding: prevents the last table row from being hidden
              behind the browser's scroll-to-bottom gutter on macOS */}
          <div className="h-4" aria-hidden="true" />
        </div>
      </main>
    </div>
  );
}

// ── ScreenerRow sub-component ─────────────────────────────────────────────────

/**
 * ScreenerRow — renders a single row in the results table.
 *
 * WHY a separate component (not inline):
 * The row has its own hover state and click handler. Extracting it to a named
 * component gives React a stable reference for reconciliation, avoiding full
 * re-renders of the entire tbody on sort/load-more operations.
 *
 * WHY no memo: the parent only re-renders when sortedResults changes, which means
 * all rows need to re-render anyway (order may have changed). memo would cost
 * more than it saves here.
 */
interface ScreenerRowProps {
  result: ScreenerResult;
  onClick: (result: ScreenerResult) => void;
}

function ScreenerRow({ result, onClick }: ScreenerRowProps) {
  return (
    <tr
      className="cursor-pointer border-b border-border/50 transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      onClick={() => onClick(result)}
      // WHY role="row" + tabIndex: table rows are keyboard-navigable
      // (Tab to row, Enter to navigate) for accessibility compliance.
      role="row"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick(result);
        }
      }}
      aria-label={`${result.ticker} ${result.name} — click to open instrument detail`}
    >
      {/* Ticker — monospace, bold for quick visual scanning */}
      <td className="px-3 py-2 font-mono text-xs font-semibold tabular-nums text-primary">
        {result.ticker}
      </td>

      {/* Name — truncated with title tooltip for full text on hover */}
      <td
        className="max-w-[200px] truncate px-3 py-2 text-xs text-foreground"
        title={result.name}
      >
        {result.name}
      </td>

      {/*
        Price — ScreenerResult does not include a live price field (the screener
        returns fundamentals + scores, not real-time quotes). Show an em-dash.
        WHY not fetch live prices here: fetching 20+ individual quotes per row
        would create 20+ simultaneous requests on render — not acceptable.
        The instrument detail page fetches the live quote when the user navigates.
      */}
      <td className="px-3 py-2 text-right font-mono text-xs tabular-nums text-muted-foreground">
        —
      </td>

      {/* Change% (daily_return) — coloured positive/negative */}
      <td
        className={[
          "px-3 py-2 text-right font-mono text-xs tabular-nums",
          priceChangeClass(result.daily_return),
        ].join(" ")}
      >
        {/* WHY formatPercent: daily_return is already a decimal (0.0234 = 2.34%) */}
        {formatPercent(result.daily_return)}
      </td>

      {/* Market Cap — compact notation ($2.45T, $345.00B) */}
      <td className="px-3 py-2 text-right font-mono text-xs tabular-nums text-foreground">
        {formatMarketCap(result.market_cap)}
      </td>

      {/* Score — HeatCell component with 7-step color scale */}
      <td className="px-3 py-2 text-right">
        <div className="flex justify-end">
          <HeatCell score={result.market_impact_score} />
        </div>
      </td>
    </tr>
  );
}
