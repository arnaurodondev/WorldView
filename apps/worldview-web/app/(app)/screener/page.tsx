/**
 * app/(app)/screener/page.tsx — 12-Column Instrument Screener (Terminal Quality)
 *
 * WHY THIS EXISTS: The screener is the primary discovery tool for quant analysts
 * and institutional traders — equivalent to Bloomberg EQUITY SCREEN. Users filter
 * the instrument universe by sector, market cap, and ~16 fundamental / technical /
 * news filters, then scan the 12-column results table to surface ideas.
 *
 * WHY 12 COLUMNS (up from 7): PRD-0031 §7.1 mandates 12 columns for density
 * parity with Bloomberg.
 *
 * WHY VIRTUAL SCROLL: @tanstack/react-virtual renders only visible rows (~25 at
 * a time) regardless of total result count.
 *
 * WHY CLIENT-SIDE SORT: For the loaded result set, client sort is instant
 * (no round-trip).
 *
 * PLAN-0051 Wave B Part 1 changes:
 *   - Filter bar expanded: Valuation, Profitability, Growth, Leverage, Technical, News
 *     sub-sections with min/max range inputs (T-B-2-02..04).
 *   - "X of Y match" header indicator (T-B-2-08).
 *   - "Load More" pagination accumulator instead of single-page fetch (T-B-2-10).
 *   - Real backend metric names per docs/services/market-data.md (T-B-2-01).
 *   - Client-side fallback application for technical filters where the server
 *     does not yet expose the underlying field.
 *
 * WHO USES IT: Research analysts (F4), quant traders (F5)
 * DATA SOURCE: POST /v1/fundamentals/screen (S9 → S3 fundamentals)
 * DESIGN REFERENCE: PRD-0031 §7 Screener, PLAN-0051 Wave B
 */

"use client";
// WHY "use client": uses useState (filter state, sort state, accumulator), TanStack Query
// (S9 data fetching), and next/navigation (row click routing — used inside ScreenerTable).

import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQuery } from "@tanstack/react-query";
// PLAN-0059 C-6: URL-state for the two highest-cardinality screener filters
// (sector + cap tier). The full FilterState (25+ fields) intentionally stays
// in component state — encoding it would yield unreadable URLs. The two
// dimensions exposed here are what traders most often share via deep-link
// ("look at my Energy / Mid-cap screen"). Saved Screens cover the rest.
import { useQueryState, parseAsString, parseAsStringLiteral } from "nuqs";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { ScreenerTable, type SortState, type SortableKey } from "@/components/screener/ScreenerTable";
// PLAN-0059 G-2: ScreenerFilterBar is the largest component on /screener
// (~986 LOC + per-section validators). Dynamic-import code-splits it out
// of the initial bundle so the screener route's first paint shows the
// table sooner; the filter bar lazy-loads while the user reads results.
// Type-only imports remain static so the page can use FilterState.
import dynamic from "next/dynamic";
import {
  DEFAULT_FILTERS,
  type FilterState,
} from "@/components/screener/ScreenerFilterBar";
const ScreenerFilterBar = dynamic(
  () =>
    import("@/components/screener/ScreenerFilterBar").then(
      (m) => ({ default: m.ScreenerFilterBar }),
    ),
  { ssr: false },
);
import { DashboardEmptyState } from "@/components/ui/dashboard-empty-state";
import type { ScreenerResult, ScreenerRequest, ScreenerFilter } from "@/types/api";
// PLAN-0051 Wave B Part 2 imports — Saved Screens, Column Settings, Export, Sparklines.
import { SavedScreensDialog } from "@/components/screener/SavedScreensDialog";
import { ColumnSettingsPopover } from "@/components/screener/ColumnSettingsPopover";
import { ExportMenu, type ExportColumn } from "@/components/screener/ExportMenu";
import {
  loadColumnPrefs,
  saveColumnPrefs,
  type ScreenerColumn,
} from "@/lib/screener-columns";
import { useScreenerSparklines } from "@/hooks/useScreenerSparklines";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * PAGE_SIZE — server `limit` per request and the increment for Load More.
 *
 * WHY 50: balances "useful first page" against "bandwidth on each Load More click".
 * Backend caps at 200; choosing 50 keeps each page lightweight and gives the
 * virtualizer enough rows to render meaningful scroll content without paginating
 * too aggressively.
 */
const PAGE_SIZE = 50;

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * pushIfRange — append a `{metric, min_value, max_value}` filter when at least
 * one bound is set, otherwise no-op. Centralises the "do not send empty filters"
 * rule so we never POST an empty-bound filter (which the backend rejects with 422).
 */
function pushIfRange(
  out: ScreenerFilter[],
  metric: string,
  min: number | undefined,
  max: number | undefined,
): void {
  if (min === undefined && max === undefined) return;
  out.push({ metric, min_value: min, max_value: max });
}

/**
 * buildScreenerFilters — converts UI FilterState to ScreenerRequest.filters[].
 *
 * Maps each fundamental UI filter to the canonical backend metric name from
 * docs/services/market-data.md (PLAN-0051 T-B-2-01):
 *   pe_ratio, pb_ratio, price_sales_ttm, dividend_yield,
 *   roe_ttm, profit_margin, operating_margin_ttm,
 *   quarterly_revenue_growth_yoy, quarterly_earnings_growth_yoy,
 *   market_capitalization.
 *
 * Backend-pending filters (gross margin, debt/equity, current ratio) are
 * skipped — the UI inputs are disabled but the FilterState may still carry
 * stale values from a saved screen.
 *
 * Technical, news, and signal filters are NOT sent to the backend; they are
 * applied client-side after fetch (see applyClientFilters).
 */
function buildScreenerFilters(f: FilterState): ScreenerFilter[] {
  const filters: ScreenerFilter[] = [];

  // ── Top-row primary filters ────────────────────────────────────────────────
  // Search by ticker / name → backend has no text search on the screener
  // endpoint; this remains a CLIENT_SIDE_FILTER applied in applyClientFilters.

  // Sector → applied at the SCREEN_FILTER level via the optional `sector` field
  // on a single filter. Per S3 semantics: specifying sector on any filter
  // restricts the entire result set. We attach it to the first filter we push.
  // If no other filters exist, we synthesize a benign filter so the request
  // still has at least one entry (backend min_length=1).

  // Cap tier → market_capitalization range
  let capMin: number | undefined;
  let capMax: number | undefined;
  if (f.capTier === "LARGE") capMin = 10_000_000_000;
  else if (f.capTier === "MID") {
    capMin = 2_000_000_000;
    capMax = 10_000_000_000;
  } else if (f.capTier === "SMALL") capMax = 2_000_000_000;
  pushIfRange(filters, "market_capitalization", capMin, capMax);

  // ── Valuation (SERVER_SIDE) ────────────────────────────────────────────────
  pushIfRange(filters, "pe_ratio", f.peMin, f.peMax);
  pushIfRange(filters, "pb_ratio", f.pbMin, f.pbMax);
  pushIfRange(filters, "price_sales_ttm", f.psMin, f.psMax);
  pushIfRange(filters, "dividend_yield", f.divYieldMin, f.divYieldMax);

  // ── Profitability (SERVER_SIDE) ────────────────────────────────────────────
  pushIfRange(filters, "roe_ttm", f.roeMin, f.roeMax);
  // Gross margin SKIPPED — BACKEND_PENDING (gross_margin not derived).
  pushIfRange(filters, "profit_margin", f.netMarginMin, f.netMarginMax);
  pushIfRange(filters, "operating_margin_ttm", f.opMarginMin, f.opMarginMax);

  // ── Growth (SERVER_SIDE) ───────────────────────────────────────────────────
  pushIfRange(filters, "quarterly_revenue_growth_yoy", f.revGrowthMin, f.revGrowthMax);
  pushIfRange(filters, "quarterly_earnings_growth_yoy", f.earningsGrowthMin, f.earningsGrowthMax);

  // ── Leverage SKIPPED — BACKEND_PENDING (debt/equity, current ratio not derived).

  // Attach sector restriction (if any) to the first filter — S3 applies it as
  // a global universe constraint, not per-filter, but the ScreenFilter schema
  // requires placing it on ≥1 filter. If no filters exist yet, fall through —
  // the synth path below will handle the empty case.
  if (f.sector && filters.length > 0) {
    filters[0] = { ...filters[0], sector: f.sector };
  }

  // ── Synthesize a benign filter when nothing else is set ────────────────────
  // Backend rejects empty filter lists (min_length=1). When the user opens the
  // page with no filters at all, we send a permissive market_capitalization
  // bound (≥ $0) so we always get a result page. This is the same trick
  // documented in PLAN-0017 Wave C-1 for "browse all" queries.
  if (filters.length === 0) {
    filters.push({
      metric: "market_capitalization",
      min_value: 0,
      // Apply sector if requested
      ...(f.sector ? { sector: f.sector } : {}),
    });
  }

  return filters;
}

/**
 * applyClientFilters — filters that the backend cannot apply yet.
 *
 * For each technical / news control set in FilterState, drop rows that do not
 * satisfy the constraint. When the data field is missing on the row (most
 * common case today), we keep the row so partial-data instruments are not
 * accidentally hidden. Conservative behaviour matches Bloomberg's "soft" filters
 * where missing data means "uncertain" rather than "exclude".
 *
 * TODO(server): once S3 / S6 surface these fields, move them to buildScreenerFilters.
 */
function applyClientFilters(rows: ScreenerResult[], f: FilterState): ScreenerResult[] {
  let out = rows;

  // Free-text search on ticker / name — NOT supported by backend.
  if (f.search.trim()) {
    const q = f.search.trim().toLowerCase();
    out = out.filter((r) => {
      const t = (r.ticker ?? "").toLowerCase();
      const n = (r.name ?? "").toLowerCase();
      return t.includes(q) || n.includes(q);
    });
  }

  // Above 50d MA — TODO server: requires `current_price` and `ma_50` on response.
  // Today neither is consistently populated; we skip this filter when data missing.
  // (No-op until backend ships moving averages.)

  // RSI band — TODO server. No `rsi_14` field on response yet.

  // Volume vs 30d average — TODO server. Requires daily volume + avg_volume_30d on response.
  // (avg_volume_30d is in instrument_fundamentals_snapshot but not on screener row.)

  // Distance from 52W high — TODO server. Requires high_52w on response.
  // Distance from 52W low — TODO server. Requires low_52w on response.

  // News & signals — all TODO server (S6/S7). Inputs are accepted but not applied.

  return out;
}

/**
 * SORT_KEY_TO_FIELD — map display column keys → ScreenerResult fields.
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-06): the column popover names columns by
 * display key ("price", "change") but the actual data lives under API field
 * names ("current_price", "daily_return"). One central map keeps the renderer
 * and the sorter in sync — adding a new sortable column is a single line here
 * plus the renderCell branch in ScreenerTable.
 */
const SORT_KEY_TO_FIELD: Record<SortableKey, keyof ScreenerResult> = {
  ticker: "ticker",
  name: "name",
  sector: "gics_sector",
  price: "current_price",
  change: "daily_return",
  marketCap: "market_cap",
  pe: "pe_ratio",
  revenue: "revenue",
  beta: "beta",
  score: "market_impact_score",
};

/**
 * sortResults — client-side sort on the loaded result set.
 *
 * WHY null → bottom: null values sort to the bottom in both asc and desc
 * directions. Users want data-rich rows first.
 */
function sortResults(results: ScreenerResult[], sort: SortState): ScreenerResult[] {
  if (!sort.key || !sort.dir) return results;

  const field = SORT_KEY_TO_FIELD[sort.key];
  const dir = sort.dir === "asc" ? 1 : -1;

  return [...results].sort((a, b) => {
    const av = a[field];
    const bv = b[field];

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

  // ── URL-backed dimensions (C-6) ───────────────────────────────────────────
  // WHY just sector + capTier: these are the top-level "axis" filters most
  // often shared via link. parseAsString accepts any GICS string (the bar's
  // own validation rejects unknowns). parseAsStringLiteral pins capTier to
  // the typed enum.
  const [urlSector, setUrlSector] = useQueryState(
    "sector",
    parseAsString.withDefault("").withOptions({ clearOnDefault: true }),
  );
  const [urlCapTier, setUrlCapTier] = useQueryState(
    "capTier",
    parseAsStringLiteral(["ALL", "LARGE", "MID", "SMALL"] as const)
      .withDefault("ALL")
      .withOptions({ clearOnDefault: true }),
  );

  // ── Applied filters — committed state that triggers the S9 query ──────────
  // WHY "applied" vs "pending": filter form state in ScreenerFilterBar is pending
  // until the user clicks Apply. Separating them prevents partial inputs from
  // firing API calls.
  // Lazy initialiser merges URL params into DEFAULT_FILTERS so a deep-link
  // pre-applies the URL-backed dimensions on first paint without an extra
  // render cycle.
  const [appliedFilters, setAppliedFilters] = useState<FilterState>(() => ({
    ...DEFAULT_FILTERS,
    sector: urlSector,
    capTier: urlCapTier,
  }));

  // Keep the URL in sync when applied filters change for the URL-backed
  // dimensions. Other filters intentionally stay out of the URL (see comment
  // on the import above).
  useEffect(() => {
    if (appliedFilters.sector !== urlSector) {
      void setUrlSector(appliedFilters.sector || "");
    }
    if (appliedFilters.capTier !== urlCapTier) {
      void setUrlCapTier(appliedFilters.capTier);
    }
    // Read the URL for changes too — when the user hits back/forward the URL
    // updates first; reflect that into appliedFilters so the table re-queries.
  }, [appliedFilters.sector, appliedFilters.capTier, urlSector, urlCapTier, setUrlSector, setUrlCapTier]);

  // ── Filter panel open/closed ──────────────────────────────────────────────
  // WHY default false (collapsed): terminal UIs default to maximum data density.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // ── Sort state ────────────────────────────────────────────────────────────
  const [sort, setSort] = useState<SortState>({ key: null, dir: null });

  // ── Saved Screens dialog (PLAN-0051 T-B-2-05) ─────────────────────────────
  // WHY local boolean (not URL state): the dialog is ephemeral chrome — closing
  // it should not pollute browser history with a back-button entry.
  const [savedDialogOpen, setSavedDialogOpen] = useState(false);

  // ── Column preferences (PLAN-0051 T-B-2-06) ───────────────────────────────
  // WHY a lazy initialiser: loadColumnPrefs reads localStorage. Calling it once
  // on mount avoids re-parsing on every render. The Popover writes back to
  // localStorage on each toggle/reorder; we mirror in state so the table
  // re-renders immediately.
  const [columns, setColumns] = useState<ScreenerColumn[]>(() => loadColumnPrefs());
  const handleColumnsChange = useCallback((next: ScreenerColumn[]) => {
    setColumns(next);
    saveColumnPrefs(next);
  }, []);

  // ── Pagination state (T-B-2-10 Load More) ─────────────────────────────────
  // WHY accumulator + offset (not cursor): we accumulate rows from each page and
  // append. The next request's offset = current rows length. This is simpler
  // than a cursor pattern and matches the backend's offset/limit contract
  // (S3 caps offset at 5000 — plenty for a screener).
  const [offset, setOffset] = useState(0);
  const [accumulator, setAccumulator] = useState<ScreenerResult[]>([]);
  // serverTotal — `total` from the most recent response. Used for "X of Y" and
  // for hiding the Load More button when accumulator.length >= total.
  const [serverTotal, setServerTotal] = useState(0);

  // ── Column sort handler — cycle: none → asc → desc → none ─────────────────
  const handleSort = useCallback((key: SortableKey) => {
    setSort((prev) => {
      if (prev.key !== key) {
        return { key, dir: "asc" };
      }
      if (prev.dir === "asc") return { key, dir: "desc" };
      return { key: null, dir: null };
    });
  }, []);

  // ── Stable key for the active filter set ──────────────────────────────────
  // WHY useMemo: queryKey must be stable across renders so React Query caches
  // page fetches keyed by the filter set + offset. JSON.stringify gives us a
  // canonical representation since filter objects are new references each render.
  const filterSerialized = useMemo(
    () => JSON.stringify(appliedFilters),
    [appliedFilters],
  );

  // ── Build the request for the *current* page ──────────────────────────────
  const request: ScreenerRequest = useMemo(
    () => ({
      filters: buildScreenerFilters(appliedFilters),
      limit: PAGE_SIZE,
      offset,
    }),
    [appliedFilters, offset],
  );

  // ── S9 screener query ─────────────────────────────────────────────────────
  // WHY a single query keyed by [filters, offset]: each Load More click bumps
  // the offset which invalidates the cached entry and triggers a fresh fetch.
  // The previous accumulator stays in component state — React Query just
  // returns the next page; we merge in a useEffect below.
  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ["screener", filterSerialized, offset],
    queryFn: () => createGateway(accessToken).runScreener(request),
    enabled: !!accessToken,
    // WHY 30s staleTime: screener fundamentals change infrequently during a session.
    staleTime: 30_000,
    // WHY keepPreviousData via placeholderData would flicker; we manage our own
    // accumulator instead — see the merge effect below.
  });

  // ── Merge each fetched page into the accumulator ──────────────────────────
  // WHY a ref + dedup on offset: useEffect runs on every render where data
  // changes. We must not re-append the same page twice (would duplicate rows
  // when React StrictMode double-renders). Tracking the last offset we merged
  // keeps the merge idempotent.
  const lastMergedOffset = useRef<number | null>(null);
  useEffect(() => {
    if (!data) return;
    if (lastMergedOffset.current === offset) return;
    lastMergedOffset.current = offset;

    setServerTotal(data.total);

    if (offset === 0) {
      // First page (after filter Apply or initial load) → replace accumulator
      setAccumulator(data.results);
    } else {
      // Subsequent page → append. Dedup by instrument_id to be safe if the
      // backend ever returns overlapping pages (e.g. tied sort values).
      setAccumulator((prev) => {
        const seen = new Set(prev.map((r) => r.instrument_id));
        const next = data.results.filter((r) => !seen.has(r.instrument_id));
        return [...prev, ...next];
      });
    }
  }, [data, offset]);

  // ── Filter Apply / Reset → reset accumulator ──────────────────────────────
  const handleApply = useCallback((filters: FilterState) => {
    setAppliedFilters(filters);
    setSort({ key: null, dir: null });
    setOffset(0);
    setAccumulator([]); // discard previous page so the new query rebuilds from scratch
    lastMergedOffset.current = null;
  }, []);

  // ── Load More handler ─────────────────────────────────────────────────────
  const handleLoadMore = useCallback(() => {
    setOffset((o) => o + PAGE_SIZE);
  }, []);

  // ── Apply client-side filters + sort to the accumulator ───────────────────
  // WHY sort after filter: filtering reduces the row set; sorting the smaller
  // set is cheaper and matches user intent ("show me what matched, in order").
  const filteredRows = useMemo(
    () => applyClientFilters(accumulator, appliedFilters),
    [accumulator, appliedFilters],
  );

  // PLAN-0059 G-3: useDeferredValue tells React to schedule the heavy
  // sort + downstream table render at a lower priority than the input that
  // triggered the change. When `filteredRows` changes (Apply clicked,
  // accumulator grew via Load More, sort key flipped), the table body
  // re-renders LATE — meanwhile the filter bar / sort header / Load More
  // button keep responding instantly. With 5000-row accumulators the
  // sort+memoization pass otherwise blocks the main thread for 30-80ms.
  const deferredFilteredRows = useDeferredValue(filteredRows);
  const sortedRows = useMemo(
    () => sortResults(deferredFilteredRows, sort),
    [deferredFilteredRows, sort],
  );

  // ── Sparklines (PLAN-0051 T-B-2-09) ───────────────────────────────────────
  // WHY only fetch when the sparkline column is visible: bandwidth/latency
  // saving — if the user has hidden the column, there is no point hammering
  // /quotes/bars/batch.
  //
  // PLAN-0053 T-F-6-07: also auto-disable when >200 rows are loaded. Each
  // sparkline = one /quotes/bars/batch fetch entry; with 200+ rows the
  // batch payload becomes large enough to noticeably stall the table render.
  // The user's checkbox in ColumnSettingsPopover stays "on" but the actual
  // fetch is short-circuited; a tooltip in the popover explains why.
  const SPARKLINE_ROW_LIMIT = 200;
  const sparklineColumnVisible = useMemo(
    () => columns.some((c) => c.key === "sparkline" && c.visible),
    [columns],
  );
  const sparklineSuppressed = sparklineColumnVisible && sortedRows.length > SPARKLINE_ROW_LIMIT;
  const sparklineEnabled = sparklineColumnVisible && !sparklineSuppressed;
  const visibleInstrumentIds = useMemo(
    () => sortedRows.map((r) => r.instrument_id),
    [sortedRows],
  );
  const { sparklines } = useScreenerSparklines(visibleInstrumentIds, {
    timeframe: "1d",
    limit: 30,
    enabled: sparklineEnabled,
  });

  // ── Export columns — only currently-visible columns (T-B-2-07) ────────────
  // WHY derived (not state): when the user hides/shows a column the export
  // menu picks the change up immediately on next render. Storing this in
  // state would invite drift bugs.
  const exportColumns = useMemo<ExportColumn<ScreenerResult>[]>(() => {
    return columns
      .filter((c) => c.visible)
      .map((c) => {
        // WHY explicit per-column accessor: each column extracts a different
        // ScreenerResult field (or computes a display value like "+1.24%").
        // Centralising the mapping here keeps CSV/Excel/PDF identical.
        const accessor = (row: ScreenerResult): string | number | null | undefined => {
          switch (c.key) {
            case "ticker":     return row.ticker;
            case "name":       return row.name;
            case "sector":     return row.gics_sector ?? "";
            case "price":      return row.current_price ?? null;
            case "change":     return row.daily_return != null ? row.daily_return * 100 : null;
            case "marketCap":  return row.market_cap ?? null;
            case "pe":         return row.pe_ratio ?? null;
            case "revenue":    return row.revenue ?? null;
            case "beta":       return row.beta ?? null;
            case "score":      return row.market_impact_score != null ? Math.round(row.market_impact_score * 100) : null;
            case "range52w":   return ""; // backend pending
            case "volume":     return ""; // backend pending
            case "sparkline":  return ""; // not exportable as a single value
            default:           return "";
          }
        };
        return { header: c.label, accessor };
      });
  }, [columns]);

  // ── Derive Load More visibility ───────────────────────────────────────────
  // We can load more iff (a) accumulator hasn't yet covered the server total
  // AND (b) we are not currently fetching the next page.
  const remaining = Math.max(0, serverTotal - accumulator.length);
  const canLoadMore = remaining > 0 && !isFetching;
  const nextBatch = Math.min(PAGE_SIZE, remaining);

  // Display values
  // WHY `loadedDisplayed`: the filter bar's "X of Y match" should reflect what
  // the user is actually seeing post client-side filter — not the raw server count.
  const loadedDisplayed = filteredRows.length;
  // For "of Y match" we use serverTotal (universe size matching the *server* filters).
  // The number after client filters is included in `loadedDisplayed`.

  return (
    <div className="flex flex-col h-full min-h-0">

      {/* ── Page heading + chrome (Saved Screens / Columns / Export) ─────── */}
      {/*
       * WHY one toolbar row (not two): keeps the page chrome ≤36px tall so the
       * data table gets max vertical real estate. The screener is data-first.
       * Spacing: `ml-auto` pushes the action group to the right edge.
       */}
      <div className="flex h-9 shrink-0 items-center border-b border-border px-3 gap-2">
        <h1 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          Instrument Screener
        </h1>
        {/* WHY fetching indicator: shows a subtle pulse when the query is re-running */}
        {/* WHY bg-primary static dot (no animate-pulse): §0.5 bans animate-pulse on status indicators */}
        {isFetching && !isLoading && (
          <span className="ml-2 h-1.5 w-1.5 rounded-full bg-primary shrink-0" aria-label="Loading" />
        )}
        <div className="ml-auto flex items-center gap-1">
          {/* Saved Screens — opens dialog with Save/Load tabs (T-B-2-05) */}
          <button
            type="button"
            aria-label="Saved screens"
            onClick={() => setSavedDialogOpen(true)}
            className="flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground hover:text-foreground hover:border-border/80 rounded-[2px] transition-colors"
          >
            Saved Screens
          </button>
          {/* Column visibility / order (T-B-2-06).
              PLAN-0053 T-F-6-07: pass sparklineSuppressed so the popover can
              render the "hidden for >200 rows" explainer next to the
              sparkline checkbox. */}
          <ColumnSettingsPopover
            columns={columns}
            onChange={handleColumnsChange}
            sparklineSuppressed={sparklineSuppressed}
          />
          {/* Export menu (T-B-2-07) — disabled while data is loading */}
          <ExportMenu
            rows={sortedRows}
            columns={exportColumns}
            filenameBase="screener"
            pdfTitle="Screener Results"
            disabled={isLoading || sortedRows.length === 0}
          />
        </div>
      </div>

      {/* Saved Screens dialog — controlled open/close so we can wire it from
          the toolbar button. onLoad applies filters via the existing handleApply
          so the Apply pipeline (sort reset, accumulator clear, query refire) is
          reused — no duplicate logic. */}
      <SavedScreensDialog
        open={savedDialogOpen}
        onOpenChange={setSavedDialogOpen}
        currentFilters={appliedFilters}
        onLoad={(filters) => {
          handleApply(filters);
        }}
      />

      {/* ── Filter bar (collapsible) + result count ───────────────────────── */}
      <ScreenerFilterBar
        isOpen={filtersOpen}
        onToggle={() => setFiltersOpen((v) => !v)}
        onApply={handleApply}
        // onSaveScreen left undefined → button hidden until PLAN-0051 Part 2 wires it.
        totalResults={serverTotal}
        loadedCount={loadedDisplayed}
        isLoading={isLoading}
      />

      {/* ── 12-column virtualized table ───────────────────────────────────── */}
      {/*
       * WHY ALWAYS render ScreenerTable: keeping the table mounted across all
       * states (loading, empty, populated) avoids unmounting the column headers
       * when transient empty-state conditions flip during the data merge.
       *
       * The table itself shows skeletons while loading, an inline "No results"
       * line when rows are empty, and the data when populated — see ScreenerTable.
       *
       * For the *deliberate, post-load* empty state we render the shared
       * DashboardEmptyState BELOW the table headers (sticky) so users see
       * the matched count chrome alongside the message. We only show the
       * empty-state OVERLAY once data has actually been merged into the
       * accumulator, to avoid the race where data arrives but the merge
       * effect hasn't yet bumped serverTotal — which would briefly mount
       * an empty state and unmount the table headers (breaking sort tests).
       */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <ScreenerTable
          rows={sortedRows}
          isLoading={isLoading}
          sort={sort}
          onSort={handleSort}
          columns={columns}
          sparklines={sparklines}
        />
        {/*
         * Post-load empty messaging — only shows when:
         *   - we are not loading
         *   - the merge has actually run (lastMergedOffset.current is set)
         *   - both accumulator AND filteredRows are empty
         * Rendered BELOW the table so column headers stay mounted.
         */}
        {!isLoading && !error && lastMergedOffset.current !== null && filteredRows.length === 0 && (
          <DashboardEmptyState
            title={accumulator.length === 0 ? "No matches" : "No matches after client filters"}
            message={
              accumulator.length === 0
                ? "No instruments match the current filters. Adjust filters and apply."
                : "The technical / search filters excluded all rows in the loaded page. Try widening them or loading more."
            }
          />
        )}

        {/* ── Load More toolbar ─────────────────────────────────────────── */}
        {/*
         * WHY only when canLoadMore: when we've loaded the full server universe
         * (or filters returned 0), there is nothing more to fetch. Hiding the
         * button avoids a click that would just spam an empty fetch.
         */}
        {canLoadMore && (
          <div className="shrink-0 border-t border-border flex items-center justify-center px-3 py-1.5 bg-card">
            {/* PLAN-0053 T-H-8-13: button reflects in-flight state. WHY
                isFetching && offset > 0: the FIRST page is gated by isLoading
                (shows a different skeleton); subsequent pages flip isFetching
                to true. Combining lets us show "Loading…" only on Load More
                clicks. WHY disabled while fetching: prevents double-clicks
                from queueing redundant offset bumps that would skip pages. */}
            <button
              type="button"
              aria-label={
                isFetching ? "Loading more results" : `Load ${nextBatch} more results`
              }
              aria-busy={isFetching}
              onClick={handleLoadMore}
              disabled={isFetching}
              className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground rounded-[2px] hover:text-foreground hover:border-primary/60 transition-colors disabled:cursor-not-allowed disabled:opacity-60"
            >
              {/* WHY explicit batch number: the user knows precisely how many will arrive,
               *  avoiding the surprise of "Load More" loading a different number than expected. */}
              {isFetching ? "Loading…" : `Load ${nextBatch} more`}
            </button>
            {/* Right-side detail: show "currently showing N of TOTAL" so the user
             *  has continuous reinforcement of where they are in the universe. */}
            <span
              className="ml-3 font-mono text-[10px] tabular-nums uppercase tracking-[0.06em] text-muted-foreground"
              aria-live="polite"
            >
              {accumulator.length.toLocaleString()} of {serverTotal.toLocaleString()} loaded
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
