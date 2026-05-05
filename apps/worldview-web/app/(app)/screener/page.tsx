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
  const agColumns = useMemo(
    () => createAgScreenerColumns(sparklines),
    [sparklines],
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
            case "range52w":  return "";
            case "volume":    return "";
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
    <div className="flex flex-col h-full min-h-0">

      {/* ── Toolbar ─────────────────────────────────────────────────────── */}
      <div className="flex h-9 shrink-0 items-center border-b border-border px-3 gap-2">
        <h1 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          Instrument Screener
        </h1>
        {isFetching && !isLoading && (
          <span className="ml-2 h-1.5 w-1.5 rounded-full bg-primary shrink-0" aria-label="Loading" />
        )}
        <div className="ml-auto flex items-center gap-1">
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
      </div>

      <SavedScreensDialog
        open={savedDialogOpen}
        onOpenChange={setSavedDialogOpen}
        currentFilters={appliedFilters}
        onLoad={(filters) => {
          handleApply(filters);
        }}
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
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <AgGridBase<ScreenerResult>
          rowData={filteredRows}
          columnDefs={agColumns}
          getRowId={(p) => p.data.instrument_id}
          onGridReady={handleGridReady}
          onRowClicked={(row) =>
            router.push(`/instruments/${row.instrument_id ?? row.entity_id}`)
          }
          className="flex-1"
        />

        {/* Post-load empty state — rendered below the grid so column headers
            stay mounted (preserves sort test assertions). */}
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
