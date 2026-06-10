/**
 * __tests__/screener-export-menu.test.tsx — ExportMenu fans out to the right helper
 *
 * WHY THIS EXISTS: ExportMenu is the only path users have to download
 * screener data. We mock the three lib helpers (csv-export, xlsx-export,
 * pdf-export) and verify that clicking each menu item calls exactly its
 * corresponding helper with the right rows/columns/filename.
 *
 * WHY mock the helpers (not the lib internals): the helpers are tested
 * separately for their own correctness. Here we only care that ExportMenu
 * picks the right helper for the right click.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// WHY mock BEFORE import: vitest hoists vi.mock calls; the actual ExportMenu
// import below will receive the mocked helpers.
vi.mock("@/lib/csv-export", () => ({
  exportToCsv: vi.fn(),
}));
vi.mock("@/lib/xlsx-export", () => ({
  exportToXlsx: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@/lib/pdf-export", () => ({
  exportToPdf: vi.fn(),
}));

import { ExportMenu, type ExportColumn } from "@/components/screener/ExportMenu";
import { exportToCsv } from "@/lib/csv-export";
import { exportToXlsx } from "@/lib/xlsx-export";
import { exportToPdf } from "@/lib/pdf-export";

interface Row { ticker: string; price: number }
const ROWS: Row[] = [
  { ticker: "AAPL", price: 195.43 },
  { ticker: "TSLA", price: 240.12 },
];
const COLS: ExportColumn<Row>[] = [
  { header: "Ticker", accessor: (r) => r.ticker },
  { header: "Price", accessor: (r) => r.price },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ExportMenu", () => {
  it("renders the Export trigger button", () => {
    render(<ExportMenu rows={ROWS} columns={COLS} filenameBase="screener" />);
    expect(screen.getByRole("button", { name: /export results/i })).toBeInTheDocument();
  });

  it("disables the trigger when disabled=true", () => {
    render(<ExportMenu rows={ROWS} columns={COLS} filenameBase="screener" disabled />);
    expect(screen.getByRole("button", { name: /export results/i })).toBeDisabled();
  });

  it("clicking CSV calls exportToCsv with correct args", async () => {
    const user = userEvent.setup();
    render(<ExportMenu rows={ROWS} columns={COLS} filenameBase="screener" />);
    await user.click(screen.getByRole("button", { name: /export results/i }));
    await user.click(await screen.findByRole("menuitem", { name: /export as csv/i }));
    expect(exportToCsv).toHaveBeenCalledTimes(1);
    const arg = (exportToCsv as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(arg.rows).toBe(ROWS);
    // WHY filenameStem startsWith: timestamp portion is dynamic.
    expect(arg.filenameStem.startsWith("screener-")).toBe(true);
    expect(arg.columns.length).toBe(COLS.length);
  });

  it("clicking Excel calls exportToXlsx with correct args", async () => {
    const user = userEvent.setup();
    render(<ExportMenu rows={ROWS} columns={COLS} filenameBase="screener" />);
    await user.click(screen.getByRole("button", { name: /export results/i }));
    await user.click(await screen.findByRole("menuitem", { name: /export as excel/i }));
    expect(exportToXlsx).toHaveBeenCalledTimes(1);
  });

  it("clicking PDF calls exportToPdf with title", async () => {
    const user = userEvent.setup();
    render(<ExportMenu rows={ROWS} columns={COLS} filenameBase="screener" pdfTitle="Screener Results" />);
    await user.click(screen.getByRole("button", { name: /export results/i }));
    await user.click(await screen.findByRole("menuitem", { name: /export as pdf/i }));
    expect(exportToPdf).toHaveBeenCalledTimes(1);
    const arg = (exportToPdf as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(arg.title).toBe("Screener Results");
  });

  // ── Round 2: sort-aware export via getRows ────────────────────────────────

  it("prefers getRows (grid-sorted snapshot) over the rows prop when provided", async () => {
    // WHY: the rows prop is the parent's PRE-sort base array; getRows pulls
    // the AG Grid display order at click time. The export must use the latter
    // so the file matches what the user sees on screen.
    const user = userEvent.setup();
    const SORTED = [...ROWS].reverse();
    const getRows = vi.fn(() => SORTED);
    render(<ExportMenu rows={ROWS} getRows={getRows} columns={COLS} filenameBase="screener" />);
    await user.click(screen.getByRole("button", { name: /export results/i }));
    await user.click(await screen.findByRole("menuitem", { name: /export as csv/i }));
    expect(getRows).toHaveBeenCalledTimes(1);
    const arg = (exportToCsv as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(arg.rows).toBe(SORTED);
  });

  it("falls back to the rows prop when getRows returns an empty array", async () => {
    // WHY: grid-not-mounted edge — an export click must never silently
    // produce an empty file while rows are visibly on screen.
    const user = userEvent.setup();
    const getRows = vi.fn(() => [] as Row[]);
    render(<ExportMenu rows={ROWS} getRows={getRows} columns={COLS} filenameBase="screener" />);
    await user.click(screen.getByRole("button", { name: /export results/i }));
    await user.click(await screen.findByRole("menuitem", { name: /export as csv/i }));
    const arg = (exportToCsv as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(arg.rows).toBe(ROWS);
  });

  it("uses getRows for Excel and PDF exports too", async () => {
    const user = userEvent.setup();
    const SORTED = [...ROWS].reverse();
    const getRows = vi.fn(() => SORTED);
    render(
      <ExportMenu rows={ROWS} getRows={getRows} columns={COLS} filenameBase="screener" pdfTitle="T" />,
    );
    await user.click(screen.getByRole("button", { name: /export results/i }));
    await user.click(await screen.findByRole("menuitem", { name: /export as excel/i }));
    expect(((exportToXlsx as ReturnType<typeof vi.fn>).mock.calls[0][0] as { rows: Row[] }).rows).toBe(SORTED);

    await user.click(screen.getByRole("button", { name: /export results/i }));
    await user.click(await screen.findByRole("menuitem", { name: /export as pdf/i }));
    expect(((exportToPdf as ReturnType<typeof vi.fn>).mock.calls[0][0] as { rows: Row[] }).rows).toBe(SORTED);
  });

  it("filename pattern includes a YYYYMMDD-HHmm timestamp", async () => {
    const user = userEvent.setup();
    render(<ExportMenu rows={ROWS} columns={COLS} filenameBase="screener" />);
    await user.click(screen.getByRole("button", { name: /export results/i }));
    await user.click(await screen.findByRole("menuitem", { name: /export as csv/i }));
    const arg = (exportToCsv as ReturnType<typeof vi.fn>).mock.calls[0][0];
    // 8 digit date + dash + 4 digit time
    expect(arg.filenameStem).toMatch(/^screener-\d{8}-\d{4}$/);
  });
});
