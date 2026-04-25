/**
 * app/(app)/screener/page.tsx — 12-Column Instrument Screener (Terminal Quality)
 *
 * WHY THIS EXISTS: The screener is the primary discovery tool for quant analysts
 * and institutional traders — equivalent to Bloomberg EQUITY SCREEN. Users filter
 * the instrument universe by sector, market cap, and text search, then scan the
 * 12-column results table to surface actionable ideas.
 *
 * WHY 12 COLUMNS (up from 7): PRD-0031 §7.1 mandates 12 columns for density
 * parity with Bloomberg. More data per row = fewer row navigations before
 * finding what the user wants. Columns without backend data show "—" to preserve
 * layout and signal future work.
 *
 * WHY VIRTUAL SCROLL: @tanstack/react-virtual renders only visible rows (~25 at
 * a time) regardless of total result count. A naïve map() render with 500 rows
 * causes visible frame drops when scrolling — unacceptable for a terminal tool.
 *
 * WHY CLIENT-SIDE SORT: For the loaded result set, client sort is instant (no
 * round-trip). S9 sorts are available via sort_by/sort_dir params for future
 * server-side sort if result sets grow beyond what fits comfortably in memory.
 *
 * WHO USES IT: Research analysts (F4), quant traders (F5)
 * DATA SOURCE: POST /v1/fundamentals/screen (S9 → S3 fundamentals)
 * DESIGN REFERENCE: PRD-0031 §7 Screener, canvas State D, Wave 3
 */

"use client";
// WHY "use client": uses useState (filter state, sort state), TanStack Query
// (S9 data fetching), and next/navigation (row click routing)

import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { ScreenerTable, type SortState, type SortableKey } from "@/components/screener/ScreenerTable";
import { ScreenerFilterBar, type FilterState } from "@/components/screener/ScreenerFilterBar";
import type { ScreenerResult, ScreenerRequest } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50; // WHY 50: larger page gives virtual scroll more rows to render

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * buildFilters — converts UI FilterState to ScreenerRequest.filters array.
 *
 * WHY separate helper: the ScreenerRequest.filters array uses a structured
 * {field, operator, value} format. The UI exposes friendlier controls (dropdowns,
 * text inputs). This function bridges the two without polluting the component.
 */
function buildFilters(filters: FilterState): ScreenerRequest["filters"] {
  const out: ScreenerRequest["filters"] = [];

  if (filters.search.trim()) {
    out.push({ field: "name_ticker", operator: "contains", value: filters.search.trim() });
  }

  if (filters.sector) {
    out.push({ field: "gics_sector", operator: "eq", value: filters.sector });
  }

  if (filters.capTier === "LARGE") {
    out.push({ field: "market_cap", operator: "gt", value: 10_000_000_000 });
  } else if (filters.capTier === "MID") {
    out.push({ field: "market_cap", operator: "gt", value: 2_000_000_000 });
    out.push({ field: "market_cap", operator: "lt", value: 10_000_000_000 });
  } else if (filters.capTier === "SMALL") {
    out.push({ field: "market_cap", operator: "lt", value: 2_000_000_000 });
  }

  return out;
}

/**
 * sortResults — client-side sort on the loaded result set.
 *
 * WHY null → bottom: null values sort to the bottom in both asc and desc
 * directions. Users want data-rich rows first — empty rows at the bottom
 * reduces cognitive noise during initial scan.
 */
function sortResults(results: ScreenerResult[], sort: SortState): ScreenerResult[] {
  if (!sort.key || !sort.dir) return results;

  const key = sort.key;
  const dir = sort.dir === "asc" ? 1 : -1;

  return [...results].sort((a, b) => {
    const av = a[key];
    const bv = b[key];

    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;

    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
}

// ── ScreenerPage ──────────────────────────────────────────────────────────────

export default function ScreenerPage() {
  const { accessToken } = useAuth();

  // ── Applied filters — committed state that triggers the S9 query ──────────
  // WHY "applied" vs "pending": filter form state is pending until the user clicks
  // Apply. Separating them prevents partial inputs from firing API calls.
  const [appliedFilters, setAppliedFilters] = useState<FilterState>({
    search: "",
    sector: "",
    capTier: "ALL",
  });

  // ── Filter panel open/closed ──────────────────────────────────────────────
  // WHY default false (collapsed): terminal UIs default to maximum data density.
  // The filter panel is secondary chrome — data rows are primary.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // ── Sort state ────────────────────────────────────────────────────────────
  const [sort, setSort] = useState<SortState>({ key: null, dir: null });

  // ── Column sort handler — cycle: none → asc → desc → none ─────────────────
  const handleSort = useCallback((key: SortableKey) => {
    setSort((prev) => {
      if (prev.key !== key) {
        // WHY start with asc on new column: ascending is the natural first sort
        // for most financial columns (e.g., score high→low comes after one more click)
        return { key, dir: "asc" };
      }
      if (prev.dir === "asc") return { key, dir: "desc" };
      // WHY null dir on third click: removes sort (returns to S9 response order)
      return { key: null, dir: null };
    });
  }, []);

  // ── S9 screener query ─────────────────────────────────────────────────────
  const request: ScreenerRequest = {
    filters: buildFilters(appliedFilters),
    limit: PAGE_SIZE,
    offset: 0,
  };

  const { data, isLoading, isFetching } = useQuery({
    // WHY JSON.stringify in key: filter objects are new references on every render.
    // Stringifying makes the queryKey stable for cache hits.
    queryKey: ["screener", JSON.stringify(appliedFilters)],
    queryFn: () => createGateway(accessToken).runScreener(request),
    enabled: !!accessToken,
    // WHY 30s staleTime: screener fundamentals change infrequently during a session.
    // Avoiding re-fetches on every tab switch reduces S9 load significantly.
    staleTime: 30_000,
  });

  const rawResults = data?.results ?? [];
  const totalResults = data?.total ?? 0;

  // WHY sort after fetch: client sort is instant for in-memory arrays.
  // We sort ALL loaded results (up to PAGE_SIZE rows) — not just the visible ones.
  // useVirtualizer handles which of those rows to actually render.
  const sortedResults = sortResults(rawResults, sort);

  return (
    // WHY h-full flex-col: page must fill the shell's main content area (flex-1
    // in layout.tsx). flex-col gives us the header + scrollable table layout.
    <div className="flex flex-col h-full min-h-0">

      {/* ── Page heading ─────────────────────────────────────────────────── */}
      {/*
       * WHY 36px header (h-9): consistent with other terminal page headers.
       * Keeps the page chrome minimal so the table gets maximum vertical space.
       */}
      <div className="flex h-9 shrink-0 items-center border-b border-border px-3">
        <h1 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          Instrument Screener
        </h1>
        {/* WHY fetching indicator: shows a subtle pulse when the query is re-running
            (e.g., after applying new filters) without a full loading skeleton */}
        {/* WHY bg-primary static dot (no animate-pulse): §0.5 bans animate-pulse on status indicators
            — static color change is sufficient; pulse conveys consumer-app anxiety, not terminal authority */}
        {isFetching && !isLoading && (
          <span className="ml-2 h-1.5 w-1.5 rounded-full bg-primary shrink-0" aria-label="Loading" />
        )}
      </div>

      {/* ── Filter bar (collapsible) + result count ───────────────────────── */}
      <ScreenerFilterBar
        isOpen={filtersOpen}
        onToggle={() => setFiltersOpen((v) => !v)}
        onApply={(filters) => {
          setAppliedFilters(filters);
          // WHY reset sort on filter change: sort state from the previous result
          // set is meaningless after a new query — reset to S9 response order.
          setSort({ key: null, dir: null });
        }}
        totalResults={totalResults}
        isLoading={isLoading}
      />

      {/* ── 12-column virtualized table ───────────────────────────────────── */}
      {/*
       * WHY flex-1 min-h-0: the table must fill the remaining space after the
       * header and filter bar. min-h-0 overrides the default flex min-height so
       * the table doesn't push outside the flex container.
       */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <ScreenerTable
          rows={sortedResults}
          isLoading={isLoading}
          sort={sort}
          onSort={handleSort}
        />
      </div>

    </div>
  );
}
