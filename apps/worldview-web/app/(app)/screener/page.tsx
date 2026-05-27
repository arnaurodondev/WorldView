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
import type { GridApi, GridReadyEvent } from "ag-grid-community";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useQueryClient } from "@tanstack/react-query";
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
import { SCREENER_PRESETS } from "@/lib/screener/presets";
// PRD-0089 Wave I-A · T-IA-02: extracted "Load N more" footer.
import { LoadMoreBar } from "@/components/screener/LoadMoreBar";
// PRD-0089 Wave I-A · T-IA-03: extracted AG-Grid + row-hover toolbar.
import { ScreenerTable } from "@/components/screener/ScreenerTable";

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
  // T-IA-03: hovered-row state moved into <ScreenerTable>. The page no
  // longer tracks individual cell hovers — ScreenerTable owns that.

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

  // ── Page-scoped hotkey table ────────────────────────────────────────────
  // PRD-0089 Wave I-A · T-IA-09. Per plan §5.1 + R-2 risk:
  //   • `useScopedHotkeys` does NOT exist in this codebase (plan §4 pre-flight
  //     item 8 documented uncertainty; verified empty here). We use the
  //     fallback pattern documented in R-2: a single window-level keydown
  //     listener registered in CAPTURE phase. Capture phase fires BEFORE
  //     the global command-palette listener that lives further down in the
  //     bubble tree, so the `/` chord overrides the palette cleanly.
  //   • Every chord no-ops when the user is typing in an editable element
  //     (input / textarea / contenteditable) — pressing "f" inside a search
  //     box should not open the filter popover.
  //   • Every chord that owns its own preventDefault MUST call it BEFORE
  //     setting state; otherwise the browser fires the native "/" quick-find
  //     in Firefox or the "f" letter into a focused input on the parent
  //     keydown bubble.
  //
  // Hotkey table (matches plan §5.1 T-IA-09):
  //   /          → focus NL input    (open if hidden; preventDefault always)
  //   f          → toggle filter panel
  //   s          → open saved screens dialog
  //   r          → reset filters     (confirm if any active)
  //   e          → open export menu  (programmatic — click the trigger via ref)
  //   n          → save current screen (calls SavedScreensDialog save path)
  //   Esc        → close any open popover; else clear search input via filter reset
  //   ⌘ + ↓     → jump to bottom of AG-Grid + trigger Load More
  //
  // WHY a ref to the NL input wrapper: we need to focus the inner <input>
  // when the user hits "/" on a visible bar. The NLScreenerInput component
  // does not currently accept an autoFocus prop; we resolve this by
  // querying for the first <input> inside the wrapper. This is the
  // narrowest-possible coupling — if NLScreenerInput later grows an
  // imperative API we swap the queryselector for a proper ref.handle.
  const nlWrapperRef = useRef<HTMLDivElement | null>(null);
  // WHY a ref to ExportMenu trigger: ExportMenu uses an internal Popover;
  // it does not expose an `open` prop. We open it by clicking its trigger
  // programmatically when the user hits "e".
  const exportMenuWrapperRef = useRef<HTMLDivElement | null>(null);

  // Helper: detect whether keydown target is "typing context". Used to
  // suppress every single-letter chord that would otherwise eat into typed
  // text (`f` in a textarea must remain the letter `f`).
  const isTypingTarget = useCallback((el: EventTarget | null): boolean => {
    if (!(el instanceof HTMLElement)) return false;
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (el.isContentEditable) return true;
    return false;
  }, []);

  // Helper: count active (non-default) filters. Used to gate the "r" reset
  // confirmation prompt — pressing r with no filters set is a no-op so it
  // shouldn't prompt the user.
  const activeFilterCount = useMemo(() => {
    let n = 0;
    if (appliedFilters.sector) n += 1;
    if (appliedFilters.capTier && appliedFilters.capTier !== "ALL") n += 1;
    // Search box + technical filters live on the FilterState too; count
    // them roughly by JSON-diffing against DEFAULT_FILTERS. WHY string
    // compare instead of per-field: the FilterState type has ~20 fields
    // and we'd need to keep this in sync with every new filter. The
    // string compare is correct enough for the "should we confirm?" gate.
    if (JSON.stringify(appliedFilters) !== JSON.stringify({
      ...DEFAULT_FILTERS,
      sector: appliedFilters.sector,
      capTier: appliedFilters.capTier,
    })) {
      n += 1;
    }
    return n;
  }, [appliedFilters]);

  useEffect(() => {
    // WHY `capture: true`: the global command palette also listens for "/"
    // at the window level. Registering capture phase guarantees we see the
    // event FIRST and can call stopPropagation before the palette opens.
    const onKeyDown = (e: KeyboardEvent) => {
      // Always-allow chords (work even from inside inputs): Esc + ⌘↓.
      // WHY: Esc must always be able to close popovers regardless of focus;
      // ⌘↓ is a chord (modifier present) so it doesn't conflict with typing.

      if (e.key === "Escape") {
        // Close popovers/dialogs in priority order; if none open, clear the
        // search input via a filter reset on the search field only.
        if (savedDialogOpen) {
          setSavedDialogOpen(false);
          e.preventDefault();
          return;
        }
        if (filtersOpen) {
          setFiltersOpen(false);
          e.preventDefault();
          return;
        }
        if (nlVisible) {
          setNlVisible(false);
          e.preventDefault();
          return;
        }
        // Nothing to close: fall through — let the table handle Esc-deselect.
        return;
      }

      if ((e.metaKey || e.ctrlKey) && e.key === "ArrowDown") {
        // ⌘↓ — jump to last row + trigger Load More if any remain.
        const api = gridApiRef.current;
        if (api) {
          const lastIndex = api.getDisplayedRowCount() - 1;
          if (lastIndex >= 0) {
            api.ensureIndexVisible(lastIndex, "bottom");
            // WHY focus the cell: keyboard users expect arrow keys to keep
            // working after the jump. AG default focus is on row 0 after a
            // sort/filter change; explicitly setting it here makes ⌘↑ /
            // PageUp predictable.
            api.setFocusedCell(lastIndex, "ticker");
          }
        }
        // WHY ref (not closed-over value): canLoadMore is computed later in
        // the render function; the effect reads the latest value via a ref
        // updated each render below.
        if (canLoadMoreRef.current) handleLoadMore();
        e.preventDefault();
        return;
      }

      // Letter chords below: skip when the user is typing.
      if (isTypingTarget(e.target)) return;

      switch (e.key) {
        case "/": {
          // Open the NL input bar (toggle off if it's already visible AND
          // currently focused — pressing / a second time should hide it).
          e.preventDefault();
          e.stopPropagation();
          if (!nlVisible) {
            setNlVisible(true);
            // Defer focus until the input has actually mounted in the DOM.
            // requestAnimationFrame fires after React commits + paint, so
            // the <input> queried below is guaranteed to exist.
            requestAnimationFrame(() => {
              const input =
                nlWrapperRef.current?.querySelector<HTMLInputElement>("input");
              input?.focus();
            });
          } else {
            setNlVisible(false);
          }
          break;
        }
        case "f":
          // Toggle filter popover. Stop propagation so an AG-Grid cell
          // focused beneath us doesn't also process the letter.
          e.preventDefault();
          setFiltersOpen((v) => !v);
          break;
        case "s":
          // Saved screens dialog.
          e.preventDefault();
          setSavedDialogOpen(true);
          break;
        case "n":
          // "n" = New screen. Today the SavedScreensDialog handles the
          // save-current path; opening the dialog deposits the user in
          // the save flow naturally.
          e.preventDefault();
          setSavedDialogOpen(true);
          break;
        case "e":
          // Open the Export menu by clicking its trigger button. WHY click
          // vs imperative API: ExportMenu uses a Radix Popover whose state
          // is internal; clicking the trigger is the documented way to
          // open it from outside without making the component contract
          // more complex than this one hotkey requires.
          e.preventDefault();
          {
            const btn = exportMenuWrapperRef.current?.querySelector<HTMLButtonElement>(
              "button",
            );
            btn?.click();
          }
          break;
        case "r":
          // Reset filters. Confirm if any are active to avoid accidental
          // wipeouts when the user is mid-screen.
          e.preventDefault();
          if (activeFilterCount > 0) {
            // window.confirm is the simplest path — a custom modal would
            // need its own scoped a11y dance for the keyboard user. The
            // chord is for power users who can read a one-line prompt.
            if (!window.confirm("Reset all filters?")) return;
          }
          handleApply({ ...DEFAULT_FILTERS });
          break;
        default:
          // No-op. Other keys handled by AG-Grid (up/down/shift-down) or
          // by their respective component listeners.
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () =>
      window.removeEventListener("keydown", onKeyDown, { capture: true });
    // WHY the dependency array: the handler closes over many state values;
    // listing them ensures the listener sees fresh values without forcing
    // a re-register on every parent render (the dep list only changes when
    // one of these inputs changes).
  }, [
    nlVisible,
    filtersOpen,
    savedDialogOpen,
    handleLoadMore,
    handleApply,
    activeFilterCount,
    isTypingTarget,
  ]);

  // Ref that mirrors `canLoadMore` for the ⌘↓ hotkey closure. WHY a ref
  // (not a dep): adding `canLoadMore` to the deps would re-register the
  // capture-phase listener on every page render (the value flips with
  // every fetch). Re-registering is harmless but noisy in profilers; the
  // ref keeps the listener stable while exposing the latest value.
  const canLoadMoreRef = useRef(false);

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

  // Mirror to the ref so the hotkey closure ⌘↓ branch reads the current
  // value without re-registering on every render. (See `canLoadMoreRef`
  // declaration near the hotkey effect.)
  canLoadMoreRef.current = canLoadMore;

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
      {/* WHY wrapper div with ref: "e" hotkey opens the export menu by
       *  clicking its underlying trigger button. ExportMenu owns the Radix
       *  Popover internally and does not expose an `open` prop, so we reach
       *  into the rendered DOM via the wrapper ref. Narrowest-possible
       *  coupling: when ExportMenu later exposes an imperative open() handle
       *  we drop this ref and call the handle. */}
      <div ref={exportMenuWrapperRef} className="contents">
        <ExportMenu
          rows={filteredRows}
          columns={exportColumns}
          filenameBase="screener"
          pdfTitle="Screener Results"
          disabled={isLoading || filteredRows.length === 0}
        />
      </div>
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
      {/* WHY wrapper div: the "/" hotkey focuses the first <input> inside
       *  this subtree (see hotkey effect). NLScreenerInput does not yet
       *  expose an imperative focus handle; the wrapper ref is the
       *  narrowest path to focus its inner input without modifying the
       *  component's public contract. */}
      <div ref={nlWrapperRef}>
        <NLScreenerInput
          visible={nlVisible}
          onApply={handleNLApply}
          onDismiss={() => setNlVisible(false)}
        />
      </div>

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
      {/* T-IA-03: extracted to <ScreenerTable>. The wrapper owns the
       *  row-hover toolbar state (CellMouseOver/Out + rAF debounce). The
       *  page only orchestrates: gives it rows + columns, listens for the
       *  row-click event, and supplies the compare handler. Row height is
       *  hard-locked to 20px inside ScreenerTable (Terminal-Dark density). */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden relative">
        <ScreenerTable
          rows={filteredRows}
          columnDefs={agColumns}
          onGridReady={handleGridReady}
          onRowClick={(row) =>
            router.push(`/instruments/${row.ticker || row.instrument_id}`)
          }
          onCompare={handleCompare}
        />

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
