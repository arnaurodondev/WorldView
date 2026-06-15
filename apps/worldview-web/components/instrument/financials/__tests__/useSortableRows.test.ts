/**
 * useSortableRows.test.ts — Wave-4 sortable-table primitive.
 *
 * WHY THIS EXISTS: the holder + peer tables on the Financials tab were made
 * interactive by routing their rows through useSortableRows. The hook owns the
 * ordering logic (direction toggle, null-to-bottom, no-mutation, default
 * directions) so it's the right place to lock that behaviour with unit tests —
 * the table component tests then only need to verify the WIRING.
 */

import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSortableRows, type SortAccessor } from "@/components/instrument/financials/useSortableRows";

interface Row {
  name: string;
  shares: number | null;
}

const ROWS: Row[] = [
  { name: "Charlie", shares: 30 },
  { name: "Alice", shares: 10 },
  { name: "Bob", shares: null }, // null → always sinks to the bottom
  { name: "Dave", shares: 20 },
];

const accessors: Record<"name" | "shares", SortAccessor<Row>> = {
  name: (r) => r.name,
  shares: (r) => r.shares,
};

describe("useSortableRows", () => {
  it("preserves the input order when no column is active", () => {
    const { result } = renderHook(() => useSortableRows({ rows: ROWS, accessors }));
    expect(result.current.sortedRows.map((r) => r.name)).toEqual([
      "Charlie",
      "Alice",
      "Bob",
      "Dave",
    ]);
    expect(result.current.sort.key).toBeNull();
  });

  it("sorts numeric columns descending by default on first click", () => {
    const { result } = renderHook(() => useSortableRows({ rows: ROWS, accessors }));
    act(() => result.current.toggleSort("shares"));
    // 30, 20, 10, then null last. Default direction for numeric = desc.
    expect(result.current.sortedRows.map((r) => r.name)).toEqual([
      "Charlie",
      "Dave",
      "Alice",
      "Bob",
    ]);
    expect(result.current.sort).toEqual({ key: "shares", direction: "desc" });
  });

  it("flips direction when the same column is clicked again", () => {
    const { result } = renderHook(() => useSortableRows({ rows: ROWS, accessors }));
    act(() => result.current.toggleSort("shares")); // desc
    act(() => result.current.toggleSort("shares")); // asc
    // Ascending: 10, 20, 30, null still last (unknowns always bottom).
    expect(result.current.sortedRows.map((r) => r.name)).toEqual([
      "Alice",
      "Dave",
      "Charlie",
      "Bob",
    ]);
    expect(result.current.sort.direction).toBe("asc");
  });

  it("honours a per-column default direction (name → asc)", () => {
    const { result } = renderHook(() =>
      useSortableRows({ rows: ROWS, accessors, defaultDirections: { name: "asc" } }),
    );
    act(() => result.current.toggleSort("name"));
    expect(result.current.sortedRows.map((r) => r.name)).toEqual([
      "Alice",
      "Bob",
      "Charlie",
      "Dave",
    ]);
  });

  it("keeps nulls at the bottom in BOTH directions", () => {
    const { result } = renderHook(() => useSortableRows({ rows: ROWS, accessors }));
    act(() => result.current.toggleSort("shares")); // desc
    expect(result.current.sortedRows.at(-1)?.name).toBe("Bob");
    act(() => result.current.toggleSort("shares")); // asc
    expect(result.current.sortedRows.at(-1)?.name).toBe("Bob");
  });

  it("does not mutate the input rows array (TanStack cache safety)", () => {
    const original = [...ROWS];
    const { result } = renderHook(() => useSortableRows({ rows: ROWS, accessors }));
    act(() => result.current.toggleSort("shares"));
    // The source array order is unchanged — only the returned copy is sorted.
    expect(ROWS).toEqual(original);
  });

  it("respects initialSort so a table can render pre-sorted", () => {
    const { result } = renderHook(() =>
      useSortableRows({
        rows: ROWS,
        accessors,
        initialSort: { key: "shares", direction: "asc" },
      }),
    );
    expect(result.current.sortedRows.map((r) => r.name)).toEqual([
      "Alice",
      "Dave",
      "Charlie",
      "Bob",
    ]);
  });
});
