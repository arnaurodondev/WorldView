/**
 * components/ui/data-table/data-table.stories.tsx — Storybook stories for DataTable
 *
 * WHY THIS EXISTS: DataTable is the most complex UI primitive in the app —
 * it powers Holdings, Transactions, Screener results, and Alerts tables.
 * Stories here validate that the three primary render states (populated,
 * loading skeleton, empty) all look correct under the Midnight Pro palette
 * without requiring a real API or TanStack Query provider.
 *
 * DESIGN SYSTEM: Midnight Pro dark palette (#131722 bg, compact 22px rows)
 *
 * NOTE: Stories use plain mock data (no API) — DataTable is a "dumb" presenter
 * that receives columns + data as props, so no mocking infra is needed.
 */

import type { Decorator, Meta, StoryObj } from "@storybook/react";
import type { ColumnDef } from "@tanstack/react-table";
import * as React from "react";
import { DataTable } from "./data-table";

// ── Mock data shape ───────────────────────────────────────────────────────────
// WHY a simple flat record (not a real API type): stories should be self-contained.
// Using real API response types would couple stories to backend schema changes.
interface MockRow {
  id: string;
  ticker: string;
  name: string;
  price: number;
  change: number;
  marketCap: string;
}

const MOCK_DATA: MockRow[] = [
  { id: "1", ticker: "AAPL", name: "Apple Inc.", price: 189.42, change: 1.23, marketCap: "2.93T" },
  { id: "2", ticker: "MSFT", name: "Microsoft Corp.", price: 415.87, change: -0.54, marketCap: "3.09T" },
  { id: "3", ticker: "GOOGL", name: "Alphabet Inc.", price: 178.55, change: 2.11, marketCap: "2.20T" },
  { id: "4", ticker: "NVDA", name: "NVIDIA Corp.", price: 875.30, change: 15.20, marketCap: "2.16T" },
  { id: "5", ticker: "AMZN", name: "Amazon.com Inc.", price: 185.70, change: -1.30, marketCap: "1.97T" },
];

// ── Column definitions ────────────────────────────────────────────────────────
// WHY explicit size values: DataTable is role="table" with absolutely-sized
// columns via `style={{ width: cell.column.getSize() }}`. Without an explicit
// size each column defaults to 150px (TanStack default).
const MOCK_COLUMNS: ColumnDef<MockRow>[] = [
  {
    id: "ticker",
    accessorKey: "ticker",
    header: "Ticker",
    size: 80,
    // WHY font-mono font-semibold: tickers are identifiers, not prose — monospace
    // prevents layout shift as text changes. Semibold for visual priority.
    cell: ({ getValue }) => (
      <span className="font-mono font-semibold text-foreground">{String(getValue())}</span>
    ),
  },
  {
    id: "name",
    accessorKey: "name",
    header: "Name",
    size: 200,
  },
  {
    id: "price",
    accessorKey: "price",
    header: "Price",
    size: 90,
    // WHY tabular-nums: price digits must align vertically across rows —
    // tabular-nums uses fixed-width digits that line up in columns.
    cell: ({ getValue }) => (
      <span className="tabular-nums font-mono">${Number(getValue()).toFixed(2)}</span>
    ),
  },
  {
    id: "change",
    accessorKey: "change",
    header: "Chg %",
    size: 80,
    cell: ({ getValue }) => {
      const v = Number(getValue());
      return (
        // WHY text-green-400 / text-red-400: financial convention (green=up, red=down)
        // using the palette-safe 400-shade that passes WCAG AA on #131722.
        <span className={`tabular-nums font-mono ${v >= 0 ? "text-green-400" : "text-red-400"}`}>
          {v >= 0 ? "+" : ""}
          {v.toFixed(2)}%
        </span>
      );
    },
  },
  {
    id: "marketCap",
    accessorKey: "marketCap",
    header: "Mkt Cap",
    size: 90,
    cell: ({ getValue }) => (
      <span className="tabular-nums font-mono text-muted-foreground">{String(getValue())}</span>
    ),
  },
];

// ── Meta ─────────────────────────────────────────────────────────────────────
const meta: Meta<typeof DataTable<MockRow>> = {
  title: "UI/DataTable",
  component: DataTable,
  // WHY layout: 'fullscreen': DataTable fills its container and uses flex
  // sizing — centering it would clip the table. Fullscreen lets it use natural
  // page width, matching real usage in panel layouts.
  parameters: { layout: "fullscreen" },
  tags: ["autodocs"],
  decorators: [
    // WHY height constraint: DataTable is a flex child that grows to fill the
    // available height. In Storybook there's no parent panel to constrain it,
    // so we add a fixed-height wrapper to simulate a panel.
    // WHY Decorator type: strict mode requires explicit parameter types on
    // decorator functions; importing Decorator from @storybook/react provides it.
    ((Story: React.ComponentType) => (
      <div className="h-[400px] bg-[#131722] p-4 flex flex-col">
        <Story />
      </div>
    )) as Decorator,
  ],
};
export default meta;
type Story = StoryObj<typeof meta>;

// ── Populated table ───────────────────────────────────────────────────────────
// WHY this is the primary story: it shows the full-featured table (sortable
// headers, compact 22px rows, zebra striping) with real-looking data.
// WHY typed helper: `Story` is `StoryObj<typeof meta>` which erases the generic
// parameter <MockRow> from DataTable. `getRowId: (row) => row.id` would leave
// `row` as `any` under strict mode. Extracting the row-ID function with an
// explicit type annotation avoids the implicit `any` error without needing
// to cast the entire story.
const getRowId = (row: MockRow): string => row.id;

export const Populated: Story = {
  args: {
    columns: MOCK_COLUMNS,
    data: MOCK_DATA,
    getRowId,
    density: "compact",
    ariaLabel: "Equity screener results",
  },
};

// ── Loading skeleton ──────────────────────────────────────────────────────────
// WHY: when data is fetching, DataTable renders animated skeleton rows instead
// of empty content, preventing layout shift. This story validates the skeleton
// pulse animation appears under the dark background.
export const LoadingSkeleton: Story = {
  args: {
    columns: MOCK_COLUMNS,
    data: [],
    getRowId,
    density: "compact",
    isLoading: true,
    ariaLabel: "Loading equity data",
  },
};

// ── Empty state ───────────────────────────────────────────────────────────────
// WHY: when a screener returns 0 results (e.g. over-filtered), the table
// shows the emptyMessage prop instead of phantom rows. This story ensures
// the message is readable at muted-foreground on the dark background.
export const Empty: Story = {
  args: {
    columns: MOCK_COLUMNS,
    data: [],
    getRowId,
    density: "compact",
    emptyMessage: "No results match your filters. Try widening your criteria.",
    ariaLabel: "Empty screener results",
  },
};

// ── Selectable with bulk actions ──────────────────────────────────────────────
// WHY: the selectable + bulkActions combination powers the Transactions table
// (bulk-delete) and the Holdings table (bulk-export). This story shows the
// checkbox column + bulk toolbar in Storybook so it can be reviewed separately.
export const Selectable: Story = {
  args: {
    columns: MOCK_COLUMNS,
    data: MOCK_DATA,
    getRowId,
    density: "compact",
    selectable: true,
    bulkActions: [
      {
        id: "export",
        label: "Export",
        onClick: () => {},
      },
      {
        id: "delete",
        label: "Delete",
        onClick: () => {},
        destructive: true,
      },
    ],
    ariaLabel: "Selectable equity table",
  },
};

// ── Comfortable density ───────────────────────────────────────────────────────
// WHY: the app supports three densities. Some panels (e.g. the Detail page
// transactions list) use "comfortable" (40px rows) for readability on large
// screens. This story validates the taller row variant.
export const ComfortableDensity: Story = {
  args: {
    columns: MOCK_COLUMNS,
    data: MOCK_DATA,
    getRowId,
    density: "comfortable",
    ariaLabel: "Comfortable density table",
  },
};
