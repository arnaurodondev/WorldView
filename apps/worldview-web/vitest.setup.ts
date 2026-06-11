/**
 * vitest.setup.ts — Global test setup
 *
 * WHY THIS EXISTS: Imports @testing-library/jest-dom which extends Vitest's
 * expect() with DOM-specific matchers like toBeInTheDocument(), toHaveValue(),
 * toBeVisible(), etc. Without this, React Testing Library tests would need to
 * use lower-level querySelector() checks which are more brittle.
 *
 * WHY scrollIntoView mock: jsdom (the DOM simulation used by Vitest) does not
 * implement layout APIs like scrollIntoView() — it throws "not a function".
 * Components that call el.scrollIntoView() for UX polish (auto-scroll to bottom
 * of message list) would break all tests in the file. The mock is a no-op that
 * satisfies jsdom without any side effects.
 *
 * WHY ag-grid-react mock: AG Grid requires real browser layout APIs
 * (ResizeObserver, getBoundingClientRect) that jsdom does not implement.
 * Without a mock, AgGridBase renders an empty div — no column headers, no rows.
 * This mock renders a semantic <table> that exposes headers (role="columnheader")
 * and row data to the DOM so tests can assert on content. It tracks sort state
 * internally and calls onSortChanged / onGridReady with a minimal mock API.
 */
import "@testing-library/jest-dom";
import { vi } from "vitest";
import * as React from "react";

// ── AG Grid jsdom shim ─────────────────────────────────────────────────────────
// Flatten ColGroupDef.children into leaf ColDef entries (handles column groups
// like PRICE[PRICE, CHG%] and FUNDAMENTALS[MKT CAP, P/E, REVENUE, BETA]).
function _agFlattenCols(defs: unknown[]): unknown[] {
  const result: unknown[] = [];
  for (const d of defs as Array<Record<string, unknown>>) {
    if (Array.isArray(d.children)) result.push(..._agFlattenCols(d.children as unknown[]));
    else result.push(d);
  }
  return result;
}

vi.mock("ag-grid-react", () => {
  function AgGridReact(props: Record<string, unknown>) {
    const rowData = (props.rowData as unknown[] | undefined) ?? [];
    const columnDefs = (props.columnDefs as unknown[] | undefined) ?? [];
    const onGridReady = props.onGridReady as ((e: unknown) => void) | undefined;
    const onSortChanged = props.onSortChanged as ((e: unknown) => void) | undefined;
    const onRowClicked = props.onRowClicked as ((e: unknown) => void) | undefined;
    const getRowId = props.getRowId as ((p: unknown) => string) | undefined;

    const [sortState, setSortState] = React.useState<Array<{ colId: string; sort: string | null }>>([]);
    const sortRef = React.useRef(sortState);
    sortRef.current = sortState;
    // Keep rowData ref fresh so forEachNode always sees the latest rows.
    const rowDataRef = React.useRef(rowData);
    rowDataRef.current = rowData;

    const leafCols = _agFlattenCols(columnDefs) as Array<Record<string, unknown>>;

    const mockApi = React.useRef({
      getColumnState: () => sortRef.current,
      applyColumnState: ({ state }: { state: Array<{ colId: string; sort: string | null }> }) => {
        const active = (state ?? []).filter((s) => s.sort != null);
        setSortState(active);
      },
      flashCells: () => {},
      getColumnDef: () => null,
      getRowNode: () => null,
      refreshCells: () => {},
      forEachNode: (cb: (node: { data: unknown }, index: number) => void) => {
        rowDataRef.current.forEach((data, i) => cb({ data }, i));
      },
    });
    // Keep getColumnState closure fresh after each sort change.
    mockApi.current.getColumnState = () => sortRef.current;

    React.useEffect(() => {
      onGridReady?.({ api: mockApi.current });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    function handleHeaderClick(colId: string) {
      const existing = sortRef.current.find((s) => s.colId === colId);
      let next: "asc" | "desc" | null;
      if (!existing || existing.sort == null) next = "asc";
      else if (existing.sort === "asc") next = "desc";
      else next = null;
      const newState = next ? [{ colId, sort: next }] : [];
      setSortState(newState);
      sortRef.current = newState;
      onSortChanged?.({ api: { getColumnState: () => newState } });
    }

    return React.createElement(
      "table",
      null,
      // ── Header row ────────────────────────────────────────────────────────
      React.createElement(
        "thead",
        null,
        React.createElement(
          "tr",
          null,
          ...leafCols.map((col, i) => {
            const id = (col.colId ?? col.field ?? col.headerName ?? i) as string;
            const entry = sortState.find((s) => s.colId === id);
            const ariaSort = entry?.sort === "asc" ? "ascending" : entry?.sort === "desc" ? "descending" : "none";
            return React.createElement(
              "th",
              { key: id, role: "columnheader", "aria-sort": ariaSort, onClick: () => handleHeaderClick(id) },
              // Separate span so getByText("QTY") matches only the label,
              // and parentElement.textContent includes the sort indicator.
              React.createElement("span", null, (col.headerName ?? col.field ?? id) as string),
              entry?.sort === "asc" ? React.createElement("span", null, " ▲") : null,
              entry?.sort === "desc" ? React.createElement("span", null, " ▼") : null,
            );
          }),
        ),
      ),
      // ── Data rows ─────────────────────────────────────────────────────────
      React.createElement(
        "tbody",
        null,
        ...(rowData as Array<Record<string, unknown>>).map((row, ri) => {
          const rowId = getRowId ? getRowId({ data: row }) : String(ri);
          return React.createElement(
            "tr",
            { key: rowId, onClick: () => onRowClicked?.({ data: row }) },
            ...leafCols.map((col, ci) => {
              const field = col.field as string | undefined;
              const rawValue = field ? row[field] : undefined;
              let content: React.ReactNode;
              const renderer = col.cellRenderer as ((p: unknown) => unknown) | undefined;
              if (renderer && typeof renderer === "function") {
                // Call the cell renderer as a React element factory.
                content = React.createElement(
                  renderer as React.ComponentType<{ data: unknown; value: unknown }>,
                  { data: row, value: rawValue },
                );
              } else if (typeof col.valueFormatter === "function") {
                const fmt = (col.valueFormatter as (p: unknown) => string)({ value: rawValue, data: row });
                content = fmt != null ? fmt : rawValue != null ? String(rawValue) : "";
              } else {
                content = rawValue != null ? String(rawValue) : "";
              }
              return React.createElement("td", { key: ci }, content);
            }),
          );
        }),
      ),
    );
  }

  return { AgGridReact };
});

// jsdom does not implement scrollIntoView — stub it globally as a no-op
if (typeof window !== "undefined") {
  window.HTMLElement.prototype.scrollIntoView = function () {};
}

// WHY ResizeObserver stub: jsdom does not implement ResizeObserver (a browser
// layout API). OHLCVChart uses ResizeObserver to resize the chart when the
// container changes. The stub is a no-op class that satisfies the constructor
// call without triggering layout operations.
if (typeof window !== "undefined" && !window.ResizeObserver) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// WHY IntersectionObserver stub (2026-06-10): jsdom does not implement
// IntersectionObserver. PredictionMarketsWidget (dashboard infinite scroll)
// constructs one for its bottom sentinel; AlertHistoryTab / docs pages did
// too but carried per-file stubs. A global no-op stub (same pattern as
// ResizeObserver above) lets any component mount; tests that need to DRIVE
// intersection events still override this with their own capturing stub.
if (typeof window !== "undefined" && !window.IntersectionObserver) {
  class IntersectionObserverStub {
    root = null;
    rootMargin = "";
    thresholds: number[] = [];
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }
  }
  window.IntersectionObserver =
    IntersectionObserverStub as unknown as typeof IntersectionObserver;
  globalThis.IntersectionObserver =
    IntersectionObserverStub as unknown as typeof IntersectionObserver;
}

// PLAN-0050 T-F-6-20: jsdom's `localStorage` shim in this project's vitest
// config does not expose getItem/setItem/clear on the prototype — every
// test that calls a hook backed by localStorage explodes with
// "X is not a function". Install a minimal Map-backed Storage on both
// `window.localStorage` and the global so every test sees a working
// implementation. Reset the contents in vitest's beforeEach below.
if (typeof window !== "undefined") {
  const storeMap = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return storeMap.size;
    },
    clear() {
      storeMap.clear();
    },
    getItem(k) {
      return storeMap.get(k) ?? null;
    },
    key(i) {
      return Array.from(storeMap.keys())[i] ?? null;
    },
    removeItem(k) {
      storeMap.delete(k);
    },
    setItem(k, v) {
      storeMap.set(k, String(v));
    },
  };
  // Some specs explicitly Object.defineProperty(window, "localStorage", ...)
  // — keep our shim configurable so they can replace it without erroring.
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: storage,
  });
  // Also expose on the bare `globalThis` so non-DOM module code that calls
  // `localStorage` directly (no `window.` prefix) sees the same store.
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: storage,
  });
}
