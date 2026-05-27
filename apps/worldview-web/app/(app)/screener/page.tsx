/**
 * app/(app)/screener/page.tsx — 12-Column Instrument Screener (Terminal Quality)
 *
 * WHY THIS EXISTS: The screener is the primary discovery tool for quant analysts
 * and institutional traders — equivalent to Bloomberg EQUITY SCREEN. Users filter
 * the instrument universe by sector, market cap, and ~16 fundamental / technical /
 * news filters, then scan the result table to surface ideas.
 *
 * LAYOUT (top to bottom):
 *   ScreenerHeader (36px): title · count · PresetBar chips · Filters toggle · tools
 *   FilterChipStrip (22px, optional): active-filter chips with ✕ dismiss
 *   ScreenerFilterBar (collapsible): full filter form
 *   AgGrid table: paginated screener results
 *   Load More footer
 *
 * PLAN-0092 Wave D: replaced the inlined toolbar with ScreenerHeader + FilterChipStrip.
 * AG Grid + ScreenerFilterBar unchanged.
 *
 * WHO USES IT: Research analysts (F4), quant traders (F5)
 * DATA SOURCE: POST /v1/fundamentals/screen (S9 → S3 fundamentals)
 * DESIGN REF: docs/designs/0089/08-screener.md
 */

"use client";

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
import type { GridApi, GridReadyEvent, CellMouseOverEvent } from "ag-grid-community";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useQueryClient } from "@tanstack/react-query";
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
import { ScreenerHeader } from "@/components/screener/ScreenerHeader";
import { FilterChipStrip } from "@/components/screener/FilterChipStrip";
import { NLScreenerInput } from "@/components/screener/NLScreenerInput";
import { RowHoverToolbar } from "@/components/screener/RowHoverToolbar";
import { SCREENER_PRESETS } from "@/lib/screener/presets";
// PRD-0089 Wave I-A · T-IA-02: extracted "Load N more" footer.
import { LoadMoreBar } from "@/components/screener/LoadMoreBar";

// ── Constants ──────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Returns the preset id whose filters deep-equal the applied FilterState, or null. */
function detectActivePreset(filters: FilterState): string | null {
  const json = JSON.stringify(filters);
  for (const preset of SCREENER_PRESETS) {
    if (JSON.stringify(preset.filters) === json) return preset.id;
  }
  return null;
}

// ── ScreenerPage ───────────────────────────────────────────────────────────────

export default function ScreenerPage() {
  const { accessToken } = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();

  // ── URL-backed dimensions ───────────────────────────────────────────────
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

  // ── Applied filters ─────────────────────────────────────────────────────
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

  // ── UI state ────────────────────────────────────────────────────────────
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [savedDialogOpen, setSavedDialogOpen] = useState(false);
  const [nlVisible, setNlVisible] = useState(false);
  const [hoveredRow, setHoveredRow] = useState<{ data: ScreenerResult; rect: DOMRect } | null>(null);

  // ── Column preferences ──────────────────────────────────────────────────
  const [columns, setColumns] = useState<ScreenerColumn[]>(() => loadColumnPrefs());
  const handleColumnsChange = useCallback((next: ScreenerColumn[]) => {
    setColumns(next);
    saveColumnPrefs(next);
  }, []);

  // ── Pagination ──────────────────────────────────────────────────────────
  const [offset, setOffset] = useState(0);
  const [accumulator, setAccumulator] = useState<ScreenerResult[]>([]);
  const [serverTotal, setServerTotal] = useState(0);

  const filterSerialized = useMemo(() => JSON.stringify(appliedFilters), [appliedFilters]);

  const request: ScreenerRequest = useMemo(
    () => ({ filters: buildScreenerFilters(appliedFilters), limit: PAGE_SIZE, offset }),
    [appliedFilters, offset],
  );

  // ── S9 screener query ───────────────────────────────────────────────────
  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: qk.screener.page(filterSerialized, offset),
    queryFn: () => createGateway(accessToken).runScreener(request),
    enabled: !!accessToken,
    staleTime: 30_000,
  });

  // ── Accumulator merge ───────────────────────────────────────────────────
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
        return [...prev, ...data.results.filter((r) => !seen.has(r.instrument_id))];
      });
    }
  }, [data, offset]);

  // ── AG Grid API ref ─────────────────────────────────────────────────────
  const gridApiRef = useRef<GridApi<ScreenerResult> | null>(null);

  const handleGridReady = useCallback(
    (params: GridReadyEvent<ScreenerResult>) => {
      gridApiRef.current = params.api;
      params.api.applyColumnState({
        state: columns.map((c) => ({ colId: c.key, hide: !c.visible })),
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    if (!gridApiRef.current) return;
    gridApiRef.current.applyColumnState({
      state: columns.map((c) => ({ colId: c.key, hide: !c.visible })),
    });
  }, [columns]);

  // ── Handlers ────────────────────────────────────────────────────────────
  const handleApply = useCallback((filters: FilterState) => {
    setAppliedFilters(filters);
    gridApiRef.current?.applyColumnState({ defaultState: { sort: null } });
    setOffset(0);
    setAccumulator([]);
    lastMergedOffset.current = null;
  }, []);

  const handleLoadMore = useCallback(() => {
    setOffset((o) => o + PAGE_SIZE);
  }, []);

  // ── NL screener handlers ────────────────────────────────────────────────
  const handleNLApply = useCallback((patch: Partial<FilterState>) => {
    const merged = { ...appliedFilters, ...patch };
    handleApply(merged);
    setNlVisible(false);
  }, [appliedFilters, handleApply]);

  // "/" hotkey toggles the NL input bar; guarded against input, textarea, and
  // contenteditable regions so it doesn't fire while the user is typing.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "/") return;
      const el = e.target as HTMLElement;
      const tag = el.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || el.contentEditable === "true") return;
      e.preventDefault();
      setNlVisible((v) => !v);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // ── Row hover handlers ──────────────────────────────────────────────────
  // WHY CellMouseOver (not RowMouseEnter): AG Grid React doesn't expose row-level
  // mouse events. Cell events fire on every cell entry; we deduplicate by rowIndex.
  const lastHoveredRowIndex = useRef<number | null>(null);
  // WHY mouseOutPending: CellMouseOut fires between cells in the same row. The rAF
  // delay lets CellMouseOver cancel the clear before it commits. Without this flag
  // the toolbar flickers every time the cursor crosses a column boundary.
  const mouseOutPendingRef = useRef(false);

  const handleCellMouseOver = useCallback((e: CellMouseOverEvent<ScreenerResult>) => {
    mouseOutPendingRef.current = false;
    if (e.rowIndex === lastHoveredRowIndex.current) return;
    lastHoveredRowIndex.current = e.rowIndex;
    if (!e.data || !e.event) return;
    const rowEl = (e.event.target as HTMLElement).closest(".ag-row");
    if (!rowEl) return;
    setHoveredRow({ data: e.data, rect: rowEl.getBoundingClientRect() });
  }, []);

  const handleCellMouseOut = useCallback(() => {
    mouseOutPendingRef.current = true;
    requestAnimationFrame(() => {
      if (!mouseOutPendingRef.current) return;
      lastHoveredRowIndex.current = null;
      setHoveredRow(null);
    });
  }, []);

  // ── Compare set (session-scoped) ────────────────────────────────────────
  const handleCompare = useCallback((ticker: string) => {
    // WHY void queryClient: import is satisfied; future compare feature will
    // use a session-scoped set stored here. For now show a browser toast.
    void queryClient;
    // eslint-disable-next-line no-console
    console.info(`[compare] ${ticker} added to compare set`);
  }, [queryClient]);

  // ── Client-side filtering + sparklines ──────────────────────────────────
  const filteredRows = useMemo(
    () => applyClientFilters(accumulator, appliedFilters),
    [accumulator, appliedFilters],
  );

  const SPARKLINE_ROW_LIMIT = 200;
  const sparklineColumnVisible = useMemo(
    () => columns.some((c) => c.key === "sparkline" && c.visible),
    [columns],
  );
  const sparklineSuppressed = sparklineColumnVisible && filteredRows.length > SPARKLINE_ROW_LIMIT;
  const sparklineEnabled = sparklineColumnVisible && !sparklineSuppressed;
  const visibleInstrumentIds = useMemo(() => filteredRows.map((r) => r.instrument_id), [filteredRows]);
  const { sparklines } = useScreenerSparklines(visibleInstrumentIds, {
    timeframe: "1d",
    limit: 30,
    enabled: sparklineEnabled,
  });

  const agColumns = useMemo(
    () => createAgScreenerColumns(sparklines, sparklineSuppressed),
    [sparklines, sparklineSuppressed],
  );

  // ── Export columns ───────────────────────────────────────────────────────
  const exportColumns = useMemo<ExportColumn<ScreenerResult>[]>(() => {
    return columns
      .filter((c) => c.visible)
      .map((c) => {
        const accessor = (row: ScreenerResult): string | number | null | undefined => {
          switch (c.key) {
            case "ticker":        return row.ticker;
            case "name":          return row.name;
            case "sector":        return row.gics_sector ?? "";
            case "price":         return row.current_price ?? null;
            case "change":        return row.daily_return != null ? row.daily_return * 100 : null;
            case "marketCap":     return row.market_cap ?? null;
            case "pe":            return row.pe_ratio ?? null;
            case "revenueGrowth": return row.revenue_growth_yoy != null ? row.revenue_growth_yoy * 100 : null;
            case "forwardPe":     return row.forward_pe ?? null;
            case "divYield":      return row.dividend_yield != null ? row.dividend_yield * 100 : null;
            case "roe":           return row.roe != null ? row.roe * 100 : null;
            case "beta":          return row.beta ?? null;
            case "score":         return row.market_impact_score != null ? Math.round(row.market_impact_score * 100) : null;
            case "opMargin":      return row.operating_margin_ttm != null ? row.operating_margin_ttm * 100 : null;
            case "evEbitda":      return row.enterprise_value_ebitda ?? null;
            case "avgVol":        return row.avg_volume_30d ?? null;
            default:              return "";
          }
        };
        return { header: c.label, accessor };
      });
  }, [columns]);

  // ── Active preset detection ──────────────────────────────────────────────
  const activePresetId = useMemo(() => detectActivePreset(appliedFilters), [appliedFilters]);

  // ── Load More state ──────────────────────────────────────────────────────
  const remaining = Math.max(0, serverTotal - accumulator.length);
  const canLoadMore = remaining > 0 && !isFetching;
  const nextBatch = Math.min(PAGE_SIZE, remaining);

  // ── Toolbar actions (memoized to avoid ScreenerHeader re-render) ─────────
  const toolbarActions = useMemo(() => (
    <>
      <button
        type="button"
        aria-label="Saved screens"
        onClick={() => setSavedDialogOpen(true)}
        className="flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] bg-background border border-border text-muted-foreground hover:text-foreground hover:border-border/80 rounded-[2px] transition-colors"
      >
        Saved
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
    </>
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ), [columns, handleColumnsChange, sparklineSuppressed, filteredRows, exportColumns, isLoading]);

  return (
    <div className="flex flex-col h-full min-h-0 bg-background">

      {/* ── Header: title + presets + filter toggle + tools ─────────── */}
      <ScreenerHeader
        totalResults={serverTotal}
        isLoading={isLoading}
        isFetching={isFetching}
        filtersOpen={filtersOpen}
        onToggleFilters={() => setFiltersOpen((v) => !v)}
        onApplyPreset={handleApply}
        activePresetId={activePresetId}
        toolbarActions={toolbarActions}
      />

      <SavedScreensDialog
        open={savedDialogOpen}
        onOpenChange={setSavedDialogOpen}
        currentFilters={appliedFilters}
        onLoad={handleApply}
      />

      {/* ── Active-filter chip strip (hidden when no filters set) ────── */}
      <FilterChipStrip filters={appliedFilters} onApply={handleApply} />

      {/* ── NL screener bar (toggled by "/" hotkey) ──────────────────── */}
      <NLScreenerInput
        visible={nlVisible}
        onApply={handleNLApply}
        onDismiss={() => setNlVisible(false)}
      />

      {/* ── Collapsible filter panel ─────────────────────────────────── */}
      <ScreenerFilterBar
        isOpen={filtersOpen}
        onToggle={() => setFiltersOpen((v) => !v)}
        onApply={handleApply}
        totalResults={serverTotal}
        loadedCount={filteredRows.length}
        isLoading={isLoading}
      />

      {/* ── AG Grid table ────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden relative">
        <AgGridBase<ScreenerResult>
          rowData={filteredRows}
          columnDefs={agColumns}
          getRowId={(p) => p.data.instrument_id}
          onGridReady={handleGridReady}
          onRowClicked={(row) =>
            router.push(`/instruments/${row.ticker || row.instrument_id}`)
          }
          onCellMouseOver={handleCellMouseOver}
          onCellMouseOut={handleCellMouseOut}
          className="flex-1"
        />

        {/* ── Row hover action toolbar ───────────────────────────────── */}
        {hoveredRow && (
          <RowHoverToolbar
            rowRect={hoveredRow.rect}
            ticker={hoveredRow.data.ticker ?? ""}
            instrumentId={hoveredRow.data.instrument_id}
            onWatch={() => { /* watchlist endpoint not yet available */ }}
            onAlert={() => { /* alert dialog integration pending */ }}
            onCompare={handleCompare}
          />
        )}

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

        {/* ── Load More ─────────────────────────────────────────────── */}
        {/* T-IA-02: extracted to <LoadMoreBar>. The bar is sticky-bottom so
         *  it stays visible while the user scrolls the AG-Grid above. We
         *  still gate the mount on `canLoadMore` so a fully-loaded table
         *  shows no footer at all (cleaner end-of-list state). */}
        {canLoadMore && (
          <LoadMoreBar
            canLoadMore={canLoadMore}
            isFetching={isFetching}
            accumulatorCount={accumulator.length}
            total={serverTotal}
            nextBatchSize={nextBatch}
            onLoadMore={handleLoadMore}
          />
        )}
      </div>
    </div>
  );
}
