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
  { ssr: false },
);
import { DashboardEmptyState } from "@/components/ui/dashboard-empty-state";
import type { ScreenerResult, ScreenerRequest } from "@/types/api";
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
  const { data, isLoading, isFetching, error } = useQuery({
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
  const { sparklines } = useScreenerSparklines(visibleInstrumentIds, {
    timeframe: "1d",
    limit: 30,
    enabled: sparklineEnabled,
  });

  // ── AG Grid column definitions ────────────────────────────────────────────
  // FR-4.5: pass sparklineSuppressed so the TREND column renders "—" (not an
  // empty flat line) when >200 rows are loaded and sparkline fetch is skipped.
  const agColumns = useMemo(
    () => createAgScreenerColumns(sparklines, sparklineSuppressed),
    [sparklines, sparklineSuppressed],
  );

  // ── Export columns ────────────────────────────────────────────────────────
  // WHY filteredRows (not grid-sorted rows): AG Grid manages its own sort state
  // internally. Extracting the sort order from the grid API for the export is
  // deferred to Phase 8. filteredRows is the pre-sort base and is the correct
  // set to export (all matches, not just what fits on screen).
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
            // volume column displays avg_volume_30d — export the same field.
            case "volume":    return row.avg_volume_30d ?? null;
            case "sparkline": return "";
            default:          return "";
          }
        };
        return { header: c.label, accessor };
      });
  }, [columns]);

  // ── Load More state ───────────────────────────────────────────────────────
  const remaining = Math.max(0, serverTotal - accumulator.length);
  const canLoadMore = remaining > 0 && !isFetching;
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
                className="flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-primary/10 border border-primary/60 text-primary rounded-[2px] transition-colors hover:bg-primary/20"
              >
                Compare ({compareSet.length})
              </a>
            )}
            <button
              type="button"
              aria-label="Saved screens"
              onClick={() => setSavedDialogOpen(true)}
              className="flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground hover:text-foreground hover:border-border/80 rounded-[2px] transition-colors"
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
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden relative">
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

        {/* Post-load empty state — rendered below the grid so column headers
            stay mounted (preserves sort test assertions).
            ROUND-1 item 8: title standardised to "No results match your filters"
            plus an explicit "Reset filters" CTA. WHY a sibling button (not the
            DashboardEmptyState `cta` prop): that prop renders a <Link href>,
            but resetting filters is a state mutation (handleApply), not a
            navigation — so we render our own button below the shared block. */}
        {!isLoading && !error && lastMergedOffset.current !== null && filteredRows.length === 0 && (
          <div className="flex flex-col items-center">
            <DashboardEmptyState
              title="No results match your filters"
              message={
                accumulator.length === 0
                  ? "No instruments match the current filters. Adjust filters and apply."
                  : "The technical / search filters excluded all rows in the loaded page. Try widening them or loading more."
              }
            />
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
              className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-primary/10 border border-primary/60 text-primary rounded-[2px] hover:bg-primary/20 transition-colors"
            >
              Reset filters
            </button>
          </div>
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
              className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground rounded-[2px] hover:text-foreground hover:border-primary/60 transition-colors disabled:cursor-not-allowed disabled:opacity-60"
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
