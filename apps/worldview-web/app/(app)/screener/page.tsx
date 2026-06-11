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
 * PLAN-0071 Phase 5 — AG Grid migration:
 *   - TanStack DataTable replaced with AgGridBase (ag-grid-community v35).
 *   - Column definitions moved to ag-screener-columns.tsx (ColDef factory).
 *   - AG Grid handles client-side sort internally — SortState + sortResults
 *     removed; onSortingChange callback removed.
 *   - Column visibility synced from ScreenerColumn[] prefs via applyColumnState.
 *   - Pinned TICKER column (lockPinned + suppressMovable on the ColDef).
 *   - Grouped column headers: PRICE (price, chg%) and FUNDAMENTALS (marketCap,
 *     pe, revenue, beta).
 *   - ExportMenu receives filteredRows (pre-sort) — sort-aware export is
 *     deferred to Phase 8.
 *   - Load More, filter bar, saved screens, column settings, sparklines, and
 *     URL-backed sector/capTier filters are all preserved unchanged.
 *
 * WHO USES IT: Research analysts (F4), quant traders (F5)
 * DATA SOURCE: POST /v1/fundamentals/screen (S9 → S3 fundamentals)
 * DESIGN REFERENCE: PRD-0031 §7 Screener, PLAN-0051 Wave B, PLAN-0071 Phase 5
 */

"use client";
// WHY "use client": uses useState (filter state, accumulator), TanStack Query
// (S9 data fetching), nuqs (URL-backed filters), and next/navigation (row click).

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { useQueryState, parseAsString, parseAsStringLiteral } from "nuqs";
import { useRouter } from "next/navigation";
import type { GridApi, GridReadyEvent } from "ag-grid-community";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { AgGridBase } from "@/components/ui/ag-grid/AgGridBase";
import { createAgScreenerColumns } from "@/components/screener/ag-screener-columns";
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
  {
    ssr: false,
    // ROUND-3 (item 4): the filter bar is a client-only async chunk — while it
    // downloads, render a shape-matched stub of its collapsed state (a 36px
    // header band) instead of nothing. WHY: with no fallback the chip strip
    // and grid visibly jumped up ~36px when the chunk arrived; the stub
    // reserves the exact height so the swap-in is invisible.
    // ROUND-4 (item 4 — §6.2 sweep): the stub bars are now STATIC bg-muted.
    // Tailwind's raw `animate-pulse` is BANNED for skeletons (DS §6.2 table) —
    // a chunk download is a sub-second load, nowhere near the >2s threshold
    // that would justify the opt-in `animate-skeleton-pulse`.
    loading: () => (
      <div
        data-testid="screener-filterbar-skeleton"
        className="flex h-9 shrink-0 items-center gap-2 border-b border-border px-2"
        aria-hidden
      >
        <div className="h-2 w-16 rounded-[1px] bg-muted" />
        <div className="h-2 w-10 rounded-[1px] bg-muted" />
      </div>
    ),
  },
);
// ROUND-3 (item 5): DashboardEmptyState replaced by the shared primitives
// EmptyState (icon + action props shipped in Round 2 — DS §15.12). Copy now
// resolves through lib/copy/empty-states.ts (screener.* keys).
import { EmptyState } from "@/components/primitives/EmptyState";
// Icons for the two distinct zero-states: Inbox = cold start (universe empty),
// SearchX = filters excluded everything (actionable — reset/widen filters).
// ROUND-4 (item 1): AlertTriangle = query-failure error state (with Retry).
import { AlertTriangle, Inbox, SearchX } from "lucide-react";
// ROUND-3 (item 4): shape-matched 20px-pitch skeleton shown while the first
// screener query is in flight (replaces the blank grid body).
import { ScreenerTableSkeleton } from "@/components/screener/ScreenerTableSkeleton";
import type { ScreenerResult, ScreenerRequest, OHLCVBar } from "@/types/api";
// Wave-2: typed view of the new flat backend fields (volume / high_52w /
// low_52w) — see lib/api/screener.ts for why this lives in the screener
// surface rather than on the shared types/api.ts ScreenerResult.
import type { ScreenerRowEnriched } from "@/lib/api/screener";
import { SavedScreensDialog } from "@/components/screener/SavedScreensDialog";
import { ColumnSettingsPopover } from "@/components/screener/ColumnSettingsPopover";
import { ExportMenu, type ExportColumn } from "@/components/screener/ExportMenu";
import {
  loadColumnPrefs,
  saveColumnPrefs,
  type ScreenerColumn,
} from "@/lib/screener-columns";
import { useScreenerSparklines } from "@/hooks/useScreenerSparklines";
import { buildScreenerFilters } from "@/features/screener/lib/build-filters";
import { applyClientFilters } from "@/features/screener/lib/apply-client-filters";
import { qk } from "@/lib/query/keys";
// PRD-0089 Wave I — new components
import { FilterChipStrip } from "@/components/screener/FilterChipStrip";
import { RowHoverToolbar } from "@/components/screener/RowHoverToolbar";
import { ScreenerHeader } from "@/components/screener/ScreenerHeader";
import { SCREENER_PRESETS } from "@/lib/screener/presets";
import { toast } from "sonner";

// ── Constants ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

// ROUND-4 (item 3a — columnDefs identity stability): module-level frozen empty
// map used as the sparklines fallback.
//
// WHY THIS EXISTS: useScreenerSparklines returns `query.data ?? {}` — a FRESH
// `{}` object literal on every render whenever sparkline data is absent
// (column hidden, query suppressed at >200 rows, query still in flight, or
// query errored). That fresh identity flows into the `agColumns` useMemo dep
// array, so `createAgScreenerColumns` re-ran — and AG Grid received brand-new
// columnDefs — on EVERY page render, including completely unrelated state
// changes (filter-panel toggle, row hover, dialog open). AG Grid diffs
// columnDefs by reference, so each re-creation forces an expensive column
// reconciliation pass. Substituting one module-level constant whenever the map
// is empty restores referential stability; when data IS present, TanStack
// Query's own caching keeps `query.data` stable across renders, so no extra
// handling is needed on that side.
const EMPTY_SPARKLINES: Record<string, OHLCVBar[]> = Object.freeze({});

// ── ScreenerPage ──────────────────────────────────────────────────────────────

export default function ScreenerPage() {
  const { accessToken } = useAuth();
  const router = useRouter();

  // ── URL-backed dimensions ─────────────────────────────────────────────────
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

  // ── Applied filters ───────────────────────────────────────────────────────
  const [appliedFilters, setAppliedFilters] = useState<FilterState>(() => ({
    ...DEFAULT_FILTERS,
    sector: urlSector,
    capTier: urlCapTier,
  }));

  useEffect(() => {
    if (appliedFilters.sector !== urlSector) {
      void setUrlSector(appliedFilters.sector || "");
    }
    if (appliedFilters.capTier !== urlCapTier) {
      void setUrlCapTier(appliedFilters.capTier);
    }
  }, [appliedFilters.sector, appliedFilters.capTier, urlSector, urlCapTier, setUrlSector, setUrlCapTier]);

  // ── Filter panel, dialogs ─────────────────────────────────────────────────
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [savedDialogOpen, setSavedDialogOpen] = useState(false);

  // ── Active preset detection (for PresetBar highlight) ────────────────────
  // WHY JSON.stringify comparison: FilterState is a plain object with no
  // referential identity — deep-comparing stringified versions is the simplest
  // way to detect which (if any) preset matches the current filter state.
  const activePresetId = useMemo(() => {
    for (const preset of SCREENER_PRESETS) {
      if (JSON.stringify(preset.filters) === JSON.stringify(appliedFilters)) {
        return preset.id;
      }
    }
    return null;
  }, [appliedFilters]);

  // ── Default-filter detection (ROUND-3 item 5 — distinct zero-states) ──────
  // WHY: an empty result with DEFAULT filters means the instrument UNIVERSE is
  // empty (cold start — resetting filters cannot help), while an empty result
  // with ACTIVE filters means the user filtered everything out (actionable —
  // show the Reset CTA). The two situations need different copy + affordances.
  // WHY JSON.stringify: same plain-object deep-compare idiom as activePresetId
  // above — FilterState has no referential identity to lean on.
  const isDefaultFilters = useMemo(
    () => JSON.stringify(appliedFilters) === JSON.stringify(DEFAULT_FILTERS),
    [appliedFilters],
  );

  // ── Row hover toolbar state (PRD-0089 Wave I) ─────────────────────────────
  // WHY rowRect (not instrumentId only): the RowHoverToolbar is fixed-positioned
  // to the viewport using the row's bounding rect. We store null when no row is
  // hovered so the toolbar is unmounted (not just hidden) to avoid stale rects.
  const [hoveredRow, setHoveredRow] = useState<{
    rowRect: DOMRect;
    ticker: string;
    instrumentId: string;
  } | null>(null);

  // ── Compare set (PRD-0089 Wave I, max 3 tickers) ─────────────────────────
  // WHY sessionStorage is deferred: the compare page (`/compare`) is not built
  // in Wave I. We track tickers in-memory so the badge shows correctly without
  // needing persistence. A follow-up wave will persist to sessionStorage.
  const [compareSet, setCompareSet] = useState<string[]>([]);

  // ── Column preferences ────────────────────────────────────────────────────
  const [columns, setColumns] = useState<ScreenerColumn[]>(() => loadColumnPrefs());
  const handleColumnsChange = useCallback((next: ScreenerColumn[]) => {
    setColumns(next);
    saveColumnPrefs(next);
  }, []);

  // ── Pagination ────────────────────────────────────────────────────────────
  const [offset, setOffset] = useState(0);
  const [accumulator, setAccumulator] = useState<ScreenerResult[]>([]);
  const [serverTotal, setServerTotal] = useState(0);

  // ── Filter serialisation ──────────────────────────────────────────────────
  const filterSerialized = useMemo(
    () => JSON.stringify(appliedFilters),
    [appliedFilters],
  );

  // ── Build request ─────────────────────────────────────────────────────────
  const request: ScreenerRequest = useMemo(
    () => ({
      filters: buildScreenerFilters(appliedFilters),
      limit: PAGE_SIZE,
      offset,
    }),
    [appliedFilters, offset],
  );

  // ── S9 screener query ─────────────────────────────────────────────────────
  // ROUND-4 (item 1): `refetch` is destructured so the error state can offer a
  // real Retry (re-fires the SAME query — filters + offset preserved) instead
  // of forcing the user to reload the page or wiggle a filter to recover.
  //
  // CHG% DATA DECISION (Wave-2 investigation, 2026-06-10): the CHG% column
  // stays sourced from `daily_return`, which only ~32/596 instruments carry —
  // most rows truthfully show "—". Quote-derived enrichment was investigated
  // and REJECTED for now:
  //   - POST /v1/quotes/batch (the only no-N+1 option) returns ONLY
  //     {bid, ask, last, volume} — no change / change_pct / previous close,
  //     so a day-change cannot be computed from it (live-verified).
  //   - GET /v1/quotes/{id} DOES carry change_pct, but calling it per row is
  //     exactly the 50–200-request N+1 this page must avoid.
  //   - Batch-quote coverage is the SAME sparse ~32-instrument set that
  //     already has daily_return, so even a fixed batch endpoint would not
  //     widen CHG% coverage today.
  // UNBLOCK PATH (backend): add change_pct (or previous_close) to the
  // /v1/quotes/batch response — then a single batch call here can fill CHG%
  // for every quoted row.
  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: qk.screener.page(filterSerialized, offset),
    queryFn: () => createGateway(accessToken).runScreener(request),
    enabled: !!accessToken,
    staleTime: 30_000,
  });

  // ── Accumulator merge ─────────────────────────────────────────────────────
  const lastMergedOffset = useRef<number | null>(null);
  useEffect(() => {
    if (!data) return;
    if (lastMergedOffset.current === offset) return;
    lastMergedOffset.current = offset;

    setServerTotal(data.total);

    if (offset === 0) {
      setAccumulator(data.results);
    } else {
      setAccumulator((prev) => {
        const seen = new Set(prev.map((r) => r.instrument_id));
        const next = data.results.filter((r) => !seen.has(r.instrument_id));
        return [...prev, ...next];
      });
    }
  }, [data, offset]);

  // ── AG Grid API ref ───────────────────────────────────────────────────────
  // Captured from onGridReady so we can call applyColumnState on visibility
  // changes and reset sort on filter Apply — without needing a React ref to
  // the AgGridReact instance itself.
  const gridApiRef = useRef<GridApi<ScreenerResult> | null>(null);

  const handleGridReady = useCallback(
    (params: GridReadyEvent<ScreenerResult>) => {
      gridApiRef.current = params.api;
      // Apply initial column visibility from localStorage prefs.
      params.api.applyColumnState({
        state: columns.map((c) => ({ colId: c.key, hide: !c.visible })),
      });
    },
    // columns is stable on mount (lazy-initialised from localStorage once).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // Sync column visibility whenever ColumnSettingsPopover changes columns.
  useEffect(() => {
    if (!gridApiRef.current) return;
    gridApiRef.current.applyColumnState({
      state: columns.map((c) => ({ colId: c.key, hide: !c.visible })),
    });
  }, [columns]);

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleApply = useCallback((filters: FilterState) => {
    setAppliedFilters(filters);
    // Reset AG Grid sort state so the new result set starts unsorted.
    gridApiRef.current?.applyColumnState({ defaultState: { sort: null } });
    setOffset(0);
    setAccumulator([]);
    lastMergedOffset.current = null;
  }, []);

  const handleLoadMore = useCallback(() => {
    setOffset((o) => o + PAGE_SIZE);
  }, []);

  // ── Row hover toolbar handlers (PRD-0089 Wave I) ──────────────────────────

  const handleWatch = useCallback((_instrumentId: string) => {
    // WHY stub: POST /v1/watchlists/{id}/items requires a default watchlist
    // endpoint not yet shipped (design §10 Q2). We stub with a toast so the
    // button is functional (visible affordance) while the endpoint is pending.
    toast.success("Added to watchlist", {
      description: "This will persist when the watchlist endpoint ships.",
    });
  }, []);

  const handleAlert = useCallback((_instrumentId: string) => {
    // WHY stub: POST /v1/alerts requires a threshold input popover (design §7.3).
    // The alert popover is deferred to a follow-up wave. Show a toast for now.
    toast("Alert creation coming soon", {
      description: "Set a price or % change threshold to trigger an alert.",
    });
  }, []);

  const handleCompare = useCallback((ticker: string) => {
    setCompareSet((prev) => {
      // WHY max 3: the compare page design limits to 3 tickers for readability.
      if (prev.includes(ticker)) return prev;
      if (prev.length >= 3) {
        toast.error("Compare set full", {
          description: "Remove one ticker before adding another.",
        });
        return prev;
      }
      const next = [...prev, ticker];
      toast(`${ticker} added to compare set (${next.length})`, {
        description:
          next.length >= 2
            ? `Click the Compare badge to open /compare?tickers=${next.join(",")}`
            : "Add at least 2 tickers to compare.",
      });
      return next;
    });
  }, []);

  // ── Client-side filtering ─────────────────────────────────────────────────
  const filteredRows = useMemo(
    () => applyClientFilters(accumulator, appliedFilters),
    [accumulator, appliedFilters],
  );

  // ── Sparklines ────────────────────────────────────────────────────────────
  const SPARKLINE_ROW_LIMIT = 200;
  const sparklineColumnVisible = useMemo(
    () => columns.some((c) => c.key === "sparkline" && c.visible),
    [columns],
  );
  const sparklineSuppressed = sparklineColumnVisible && filteredRows.length > SPARKLINE_ROW_LIMIT;
  const sparklineEnabled = sparklineColumnVisible && !sparklineSuppressed;
  const visibleInstrumentIds = useMemo(
    () => filteredRows.map((r) => r.instrument_id),
    [filteredRows],
  );
  const { sparklines: sparklinesRaw } = useScreenerSparklines(visibleInstrumentIds, {
    timeframe: "1d",
    limit: 30,
    enabled: sparklineEnabled,
  });
  // ROUND-4 (item 3a): identity-stabilise the empty case. The hook's `?? {}`
  // fallback allocates a new object per render, which would invalidate the
  // agColumns useMemo below on every render — see EMPTY_SPARKLINES above for
  // the full rationale. Non-empty maps keep the hook's (TanStack-stable)
  // `query.data` reference untouched.
  const sparklines =
    Object.keys(sparklinesRaw).length > 0 ? sparklinesRaw : EMPTY_SPARKLINES;

  // ── AG Grid column definitions ────────────────────────────────────────────
  // FR-4.5: pass sparklineSuppressed so the TREND column renders "—" (not an
  // empty flat line) when >200 rows are loaded and sparkline fetch is skipped.
  const agColumns = useMemo(
    () => createAgScreenerColumns(sparklines, sparklineSuppressed),
    [sparklines, sparklineSuppressed],
  );

  // ── Export rows (Round 2 — sort-aware) ────────────────────────────────────
  // WHY a getter (not a memo): AG Grid owns its sort state internally and
  // doesn't notify React on header clicks, so any render-time snapshot would
  // go stale the moment the user sorts. Reading the grid at CLICK TIME via
  // forEachNodeAfterFilterAndSort yields the rows in exactly the order
  // rendered on screen — "what you see is what you export". Falls back to
  // filteredRows (the pre-sort base) when the grid isn't ready, which is also
  // ExportMenu's own fallback if this getter returns [].
  const getExportRows = useCallback((): readonly ScreenerResult[] => {
    const api = gridApiRef.current;
    if (!api) return filteredRows;
    const out: ScreenerResult[] = [];
    // forEachNodeAfterFilterAndSort iterates the client-side row model in
    // display order (post grid-filter, post grid-sort) — the canonical
    // "as rendered" traversal in AG Grid Community.
    api.forEachNodeAfterFilterAndSort((node) => {
      if (node.data) out.push(node.data);
    });
    return out;
  }, [filteredRows]);

  // ── Export columns ────────────────────────────────────────────────────────
  // Visible columns only ("what you see is what you export") — hidden columns
  // are excluded because the user hid them deliberately; row ORDER comes from
  // getExportRows above (grid-sorted), so the file mirrors the on-screen view.
  const exportColumns = useMemo<ExportColumn<ScreenerResult>[]>(() => {
    return columns
      .filter((c) => c.visible)
      .map((c) => {
        const accessor = (row: ScreenerResult): string | number | null | undefined => {
          switch (c.key) {
            case "ticker":    return row.ticker;
            case "name":      return row.name;
            case "sector":    return row.gics_sector ?? "";
            case "price":     return row.current_price ?? null;
            case "change":    return row.daily_return != null ? row.daily_return * 100 : null;
            case "marketCap": return row.market_cap ?? null;
            case "pe":        return row.pe_ratio ?? null;
            case "revenue":   return row.revenue ?? null;
            case "beta":      return row.beta ?? null;
            case "score":     return row.market_impact_score != null ? Math.round(row.market_impact_score * 100) : null;
            // ROUND-1 fix: range52w and volume used to export "" even when data
            // existed. range52w exports the position-in-range percent (0 = at
            // 52W low, 100 = at 52W high) — the same number the bar visualises.
            case "range52w": {
              const lo = row.dist_from_52w_low_pct;
              const hi = row.dist_from_52w_high_pct;
              if (lo == null || hi == null) return null;
              const span = lo + Math.abs(hi);
              return span === 0 ? 100 : Math.round(Math.min(100, Math.max(0, (lo / span) * 100)));
            }
            // Wave-2: the VOLUME column now displays the latest 1-day volume
            // (`volume`, new flat backend field) — export the same field so
            // the file mirrors the on-screen cell. The 30d average remains a
            // separate (non-exported) brightness input.
            case "volume":    return (row as ScreenerRowEnriched).volume ?? null;
            case "sparkline": return "";
            default:          return "";
          }
        };
        return { header: c.label, accessor };
      });
  }, [columns]);

  // ── Load More state ───────────────────────────────────────────────────────
  const remaining = Math.max(0, serverTotal - accumulator.length);
  // ROUND-4 (item 1): `!error` guard — when a Load More page fails, the Load
  // More button is replaced by the inline error strip below (which owns the
  // Retry affordance). Showing BOTH would offer two competing recovery paths
  // for the same failed request.
  const canLoadMore = remaining > 0 && !isFetching && !error;
  const nextBatch = Math.min(PAGE_SIZE, remaining);

  const loadedDisplayed = filteredRows.length;

  return (
    // Density bundle 2026-05-09: explicit ``bg-background`` on the page root.
    // Without it the AG Grid wrapper (``ag-theme-alpine-dark``) leaks the
    // alpine theme's default ``--ag-background-color`` (white) through any
    // gap above the grid — most visibly during the empty/loading state and on
    // the seam between toolbar and grid. Applying ``bg-background`` here
    // forces the platform dark token (#09090B) so the page always reads as
    // the rest of the terminal regardless of AG Grid mount state.
    <div className="flex flex-col h-full min-h-0 bg-background">

      {/* ── Toolbar (ScreenerHeader — PRD-0089 Wave I) ──────────────────── */}
      {/* WHY ScreenerHeader (not inline): extracts the toolbar + preset strip
          so the page.tsx focuses on data orchestration only. The header renders
          the title, result count, preset bar, Filters toggle, and tool buttons. */}
      <ScreenerHeader
        totalResults={serverTotal}
        isLoading={isLoading}
        isFetching={isFetching}
        filtersOpen={filtersOpen}
        onToggleFilters={() => setFiltersOpen((v) => !v)}
        onApplyPreset={handleApply}
        activePresetId={activePresetId}
        toolbarActions={
          <div className="flex items-center gap-1">
            {/* Compare badge — shown when ≥1 ticker added via RowHoverToolbar */}
            {compareSet.length > 0 && (
              <a
                href={`/compare?tickers=${compareSet.join(",")}`}
                target="_blank"
                rel="noopener noreferrer"
                // ROUND-3 item 6: every toolbar control gets the shared
                // keyboard-focus treatment (focus-visible ring in --ring
                // yellow) on top of its existing hover affordance.
                className="flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-primary/10 border border-primary/60 text-primary rounded-[2px] transition-colors hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                Compare ({compareSet.length})
              </a>
            )}
            <button
              type="button"
              aria-label="Saved screens"
              onClick={() => setSavedDialogOpen(true)}
              className="flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground hover:text-foreground hover:border-border/80 rounded-[2px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              Saved Screens
            </button>
            <ColumnSettingsPopover
              columns={columns}
              onChange={handleColumnsChange}
              sparklineSuppressed={sparklineSuppressed}
            />
            <ExportMenu
              rows={filteredRows}
              // Round 2: sort-aware export — rows are pulled from the AG Grid
              // API at click time so the file order matches the on-screen sort.
              getRows={getExportRows}
              columns={exportColumns}
              filenameBase="screener"
              pdfTitle="Screener Results"
              disabled={isLoading || filteredRows.length === 0}
            />
          </div>
        }
      />

      <SavedScreensDialog
        open={savedDialogOpen}
        onOpenChange={setSavedDialogOpen}
        currentFilters={appliedFilters}
        onLoad={(filters) => {
          handleApply(filters);
        }}
      />

      {/* ── Filter chip strip (PRD-0089 Wave I) ────────────────────────── */}
      {/* WHY FilterChipStrip before ScreenerFilterBar: the chip strip is the
          always-visible "what's active" summary row. The FilterBar slides in
          below it only when Filters is toggled — the chip strip stays. */}
      <FilterChipStrip
        appliedFilters={appliedFilters}
        onApply={handleApply}
        onSave={() => setSavedDialogOpen(true)}
        onReset={() => handleApply(DEFAULT_FILTERS)}
      />

      {/* ── Filter bar ───────────────────────────────────────────────────── */}
      <ScreenerFilterBar
        isOpen={filtersOpen}
        onToggle={() => setFiltersOpen((v) => !v)}
        onApply={handleApply}
        totalResults={serverTotal}
        loadedCount={loadedDisplayed}
        isLoading={isLoading}
      />

      {/* ── AG Grid table ────────────────────────────────────────────────── */}
      {/* WHY relative: the RowHoverToolbar is fixed-positioned so it doesn't
          need a relative ancestor, but we still want the overflow:hidden wrapper
          to clip the grid correctly. The toolbar escapes this container by
          design (fixed positioning). */}
      {/* ROUND-4 (item 2): role="region" + aria-label on the grid container.
          AgGridBase is a shared component (not owned by this surface) and does
          not forward an aria-label to AG Grid's internal role="grid" element,
          so screen-reader users previously hit an unlabeled grid landmark.
          Labelling the wrapping region gives the table a navigable, named
          landmark without touching the shared wrapper. */}
      <div
        role="region"
        aria-label="Screener results"
        className="flex-1 min-h-0 flex flex-col overflow-hidden relative"
      >
        {/* ── Sorting (ROUND-1 item 5) ─────────────────────────────────────
            Single-column sort: click any header (all numeric columns set
            sortable: true in ag-screener-columns.tsx).
            Multi-column sort: Shift+Click additional headers — this is AG
            Grid's NATIVE default (gridOptions.suppressMultiSort defaults to
            false and the default multi-sort modifier key is Shift; only
            setting multiSortKey="ctrl" would change it). AgGridBase does not
            override either option, so no extra config is required here —
            this comment exists so nobody "adds" multi-sort again. */}
        <AgGridBase<ScreenerResult>
          rowData={filteredRows}
          columnDefs={agColumns}
          // ── Density adoption (ROUND-3 item 1) ───────────────────────────
          // 20px rows + 20px header via AgGridBase's Round-2 props (§15.10).
          // WHY 20 and NOT the 22px token: the screener is the ONE surface
          // locked to 20px by the T-IA-14 architecture guard
          // (__tests__/architecture/screener-row-height.test.ts) — 22px rows
          // drop it below the "≥240 body cells above the fold at 1440×900"
          // acceptance gate (see lib/screener-columns.ts density math:
          // 20 rows × 14 cols). The guard literally forbids `rowHeight={22}`
          // in this folder, so do not "fix" this to 22.
          // WHY headerHeight matches rowHeight: §15.10 rule 3 — Bloomberg
          // keeps header and data rows equal; a taller header over denser
          // rows reads as misalignment.
          // Renderer audit for 20px (per §15.10 rule 1, done Round 3):
          //   HeatCell shrunk h-6→h-[18px]; MiniChart is 18px (fits);
          //   RowHoverToolbar overlay shrunk to 20px; CHG% chip is unsized
          //   inline-flex (fits); 52W bar is h-1 (fits).
          rowHeight={20}
          headerHeight={20}
          getRowId={(p) => p.data.instrument_id}
          onGridReady={handleGridReady}
          onRowClicked={(row) =>
            // ROUND-1 fix (2026-06-10): navigate by TICKER, not entity_id.
            // PRD-0089 F2 unified the instrument detail route on the
            // human-readable ticker slug — the live route is
            // app/(app)/instruments/[ticker]/page.tsx and /instruments/AAPL
            // is the canonical URL (the middleware uppercases the slug).
            // The previous entity_id navigation only worked because the S9
            // resolve_security_id resolver tolerates UUIDs; it produced ugly
            // non-canonical /instruments/<uuid> URLs that broke link sharing
            // conventions. Every row has a ticker (it is the screener's
            // primary key column), so this is always safe.
            router.push(`/instruments/${row.ticker}`)
          }
          // ── Row hover for RowHoverToolbar (PRD-0089 Wave I) ─────────────
          // WHY CellMouseOver (not RowMouseOver): AG Grid v35 doesn't expose a
          // row-level mouse-over/out event. CellMouseOverEvent fires reliably for
          // each cell entry and carries both `data` and the native MouseEvent.
          // We extract the row element by walking up from the cell target to the
          // .ag-row element so we get the full row's bounding rect.
          onCellMouseOver={(e) => {
            if (!e.data) return;
            // Walk up from the native event target to find the AG Grid row element.
            // WHY not e.event.currentTarget: in AG Grid the currentTarget is the
            // cell wrapper, not the row wrapper. We need the full row height/position.
            let el = e.event?.target as HTMLElement | null;
            while (el && !el.classList.contains("ag-row")) {
              el = el.parentElement;
            }
            if (!el) return;
            setHoveredRow({
              rowRect: el.getBoundingClientRect(),
              ticker: e.data.ticker,
              instrumentId: e.data.instrument_id,
            });
          }}
          onCellMouseOut={(e) => {
            // Clear on mouse-out only when leaving to outside the row.
            // WHY check relatedTarget: moving mouse between cells in the same row
            // fires cellMouseOut on the source cell — we only want to hide the
            // toolbar when the pointer leaves the row entirely.
            // WHY cast through MouseEvent: AG Grid's event is typed as base Event;
            // relatedTarget is only on MouseEvent. We know cell mouse-out fires a
            // native mouseleave, so the cast is safe.
            const related = (e.event as MouseEvent | undefined)?.relatedTarget as HTMLElement | null;
            let inRow = false;
            let el = related;
            while (el) {
              if (el.classList?.contains("ag-row")) {
                inRow = true;
                break;
              }
              el = el.parentElement;
            }
            if (!inRow) setHoveredRow(null);
          }}
          className="flex-1"
        />

        {/* ── Row hover toolbar (fixed-positioned overlay) ───────────── */}
        {hoveredRow && (
          <RowHoverToolbar
            rowRect={hoveredRow.rowRect}
            ticker={hoveredRow.ticker}
            instrumentId={hoveredRow.instrumentId}
            onWatch={handleWatch}
            onAlert={handleAlert}
            onCompare={handleCompare}
          />
        )}

        {/* ── Initial-load skeleton (ROUND-3 item 4) ───────────────────── */}
        {/* WHY an OVERLAY (absolute, on top of the grid) rather than swapping
            the grid out: __tests__/screener.test.tsx asserts the 34 column
            headers synchronously (before the first query resolves), so
            AgGridBase must stay mounted during isLoading. The skeleton covers
            the grid visually (z-10 + opaque bg) while keeping it in the DOM.
            WHY only while accumulator is empty: a background REFETCH
            (isFetching) over existing rows must never blank the table —
            Bloomberg never flashes; data updates in place. */}
        {isLoading && accumulator.length === 0 && (
          <div className="absolute inset-0 z-10 bg-background">
            <ScreenerTableSkeleton rows={20} />
          </div>
        )}

        {/* ── Query-failure error state (ROUND-4 item 1) ───────────────── */}
        {/* WHY THIS EXISTS: before Round 4 a failed screener query rendered a
            BLANK grid — `error` was destructured but never rendered, and the
            zero-state below is guarded by `!error`, so the user saw 34 column
            headers over nothing, with no way to recover except a full reload.
            DS §6.1 mandates error + retry for every data fetch.
            WHY an OVERLAY (same absolute/z-10 treatment as the skeleton): the
            grid must stay mounted (header assertions in screener.test.tsx run
            synchronously), and an opaque cover reads as "the table is down",
            which is the truth.
            WHY only when accumulator is empty: if the user already has rows
            loaded and a Load More page fails, blanking 200 loaded rows to
            show an error card would destroy their work — the inline strip
            below handles that case instead.
            WHY not a stuck skeleton: TanStack settles `isLoading` to false
            once retries are exhausted, so the skeleton overlay above
            unmounts and this card takes over — verified by
            __tests__/screener-error-state.test.tsx. */}
        {!isLoading && !!error && accumulator.length === 0 && (
          <div className="absolute inset-0 z-10 bg-background flex items-center justify-center">
            <EmptyState
              condition="error"
              // WHY generic.error (not a screener.* key): the copy dictionary
              // (lib/copy/empty-states.ts) is a SHARED file outside this
              // surface's ownership; generic.error already carries the right
              // "Couldn't load / Retry" copy, so no new key is needed.
              copyKey="generic.error"
              icon={AlertTriangle}
              action={
                <button
                  type="button"
                  aria-label="Retry screener query"
                  // WHY disabled while isFetching: refetch() is already in
                  // flight — double-firing would just queue a duplicate POST.
                  disabled={isFetching}
                  // WHY refetch (not handleApply): Retry must re-run the SAME
                  // query (same filters, same offset). handleApply would reset
                  // pagination and clear the accumulator — wrong semantics for
                  // "try that again".
                  onClick={() => void refetch()}
                  className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-primary/10 border border-primary/60 text-primary rounded-[2px] hover:bg-primary/20 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {isFetching ? "Retrying…" : "Retry"}
                </button>
              }
            />
          </div>
        )}

        {/* ── Load More failure strip (ROUND-4 item 1, partial-data case) ── */}
        {/* Rendered in the Load More bar's slot (same height/border) so the
            pagination chrome doesn't jump — the failed "load 50 more" action
            is replaced in place by its own retry affordance while the already
            loaded rows stay fully usable above. */}
        {!!error && accumulator.length > 0 && (
          <div
            role="alert"
            className="shrink-0 border-t border-border flex items-center justify-center gap-3 px-3 py-1.5 bg-card"
          >
            <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-negative">
              Couldn&apos;t load more results
            </span>
            <button
              type="button"
              aria-label="Retry loading more results"
              disabled={isFetching}
              onClick={() => void refetch()}
              className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground rounded-[2px] hover:text-foreground hover:border-primary/60 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isFetching ? "Retrying…" : "Retry"}
            </button>
          </div>
        )}

        {/* Post-load empty state — rendered below the grid so column headers
            stay mounted (preserves sort test assertions).
            ROUND-3 item 5: migrated from DashboardEmptyState onto the shared
            primitives EmptyState (icon + action props, DS §15.12), with TWO
            distinct zero-states:
              cold start        — default filters + empty universe (no Reset
                                  CTA: there is nothing to widen)
              filtered-to-zero  — "No results match your filters" + Reset CTA
                                  (headline pinned by __tests__/screener.test.tsx) */}
        {!isLoading && !error && lastMergedOffset.current !== null && filteredRows.length === 0 && (
          isDefaultFilters && accumulator.length === 0 ? (
            // Cold start: nothing ingested yet. Inbox icon = "awaiting data".
            <EmptyState
              condition="empty-cold-start"
              copyKey="screener.cold-start"
              icon={Inbox}
            />
          ) : (
            // Filtered-to-zero: actionable — offer the Reset CTA via the
            // primitive's `action` slot. WHY a real <button> (not the legacy
            // `cta` Link): resetting filters is a state mutation
            // (handleApply), not a navigation.
            <EmptyState
              condition="empty-no-data"
              // Server returned zero rows vs client-side filters excluded the
              // loaded page — same headline, different actionable body copy.
              // (Both keys are registered literally in lib/copy/empty-states.ts;
              // the dictionary arch test scans literal copyKey strings, so the
              // computed expression here is additive-safe.)
              copyKey={
                accumulator.length === 0
                  ? "screener.no-filter-matches"
                  : "screener.no-loaded-matches"
              }
              icon={SearchX}
              action={
                <button
                  type="button"
                  // WHY a unique aria-label (visible text stays "Reset filters"):
                  // ScreenerFilterBar's bottom toolbar already has a button with
                  // aria-label "Reset filters". Duplicated accessible names are an
                  // a11y smell (screen readers can't disambiguate) and break
                  // getByRole queries in tests.
                  aria-label="Reset filters and show all instruments"
                  // WHY handleApply(DEFAULT_FILTERS) (same as the chip strip's
                  // Reset): clears every applied filter AND re-fires the query at
                  // offset 0 so the full instrument universe reloads immediately.
                  onClick={() => handleApply(DEFAULT_FILTERS)}
                  className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-primary/10 border border-primary/60 text-primary rounded-[2px] hover:bg-primary/20 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  Reset filters
                </button>
              }
            />
          )
        )}

        {/* ── Load More ────────────────────────────────────────────────── */}
        {canLoadMore && (
          <div className="shrink-0 border-t border-border flex items-center justify-center px-3 py-1.5 bg-card">
            <button
              type="button"
              aria-label={
                isFetching ? "Loading more results" : `Load ${nextBatch} more results`
              }
              aria-busy={isFetching}
              onClick={handleLoadMore}
              disabled={isFetching}
              className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground rounded-[2px] hover:text-foreground hover:border-primary/60 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isFetching ? "Loading…" : `Load ${nextBatch} more`}
            </button>
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
