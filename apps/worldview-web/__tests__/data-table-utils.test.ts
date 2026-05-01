/**
 * __tests__/data-table-utils.test.ts — TSV/CSV serialisation
 *
 * Locks the contract for the universal DataTable export helpers.
 * Spreadsheet round-trip behaviour matters: tabs in cells must not break
 * the TSV format, and special CSV characters must be quoted per RFC 4180.
 */

import { describe, it, expect } from "vitest";
import { rowsToTsv, rowsToCsv } from "@/components/ui/data-table/data-table";

interface Row {
  ticker: string;
  price: number;
  note: string | null;
}

const cols = [
  { id: "ticker", accessorKey: "ticker", header: "Ticker" },
  { id: "price", accessorKey: "price", header: "Price" },
  { id: "note", accessorKey: "note", header: "Note" },
] as const;

describe("rowsToTsv", () => {
  it("renders header + rows joined by tabs and newlines", () => {
    const rows: Row[] = [{ ticker: "AAPL", price: 188.5, note: "buy" }];
    const tsv = rowsToTsv(rows, cols as unknown as Parameters<typeof rowsToTsv<Row>>[1]);
    expect(tsv).toBe("Ticker\tPrice\tNote\nAAPL\t188.5\tbuy");
  });

  it("renders null cells as empty", () => {
    const rows: Row[] = [{ ticker: "AAPL", price: 188.5, note: null }];
    const tsv = rowsToTsv(rows, cols as unknown as Parameters<typeof rowsToTsv<Row>>[1]);
    expect(tsv.endsWith("AAPL\t188.5\t")).toBe(true);
  });

  it("sanitises tabs inside cells", () => {
    const rows: Row[] = [{ ticker: "AAPL", price: 188.5, note: "has\ttab" }];
    const tsv = rowsToTsv(rows, cols as unknown as Parameters<typeof rowsToTsv<Row>>[1]);
    expect(tsv).not.toMatch(/has\ttab/);
    expect(tsv).toMatch(/has tab/);
  });

  it("sanitises newlines inside cells", () => {
    const rows: Row[] = [{ ticker: "AAPL", price: 188.5, note: "two\nlines" }];
    const tsv = rowsToTsv(rows, cols as unknown as Parameters<typeof rowsToTsv<Row>>[1]);
    expect(tsv).not.toMatch(/two\nlines/);
    expect(tsv).toMatch(/two lines/);
  });

  it("excludes the internal __select__ column", () => {
    const colsWithSelect = [
      { id: "__select__", header: "" },
      ...cols,
    ];
    const rows: Row[] = [{ ticker: "AAPL", price: 188.5, note: "buy" }];
    const tsv = rowsToTsv(
      rows,
      colsWithSelect as unknown as Parameters<typeof rowsToTsv<Row>>[1],
    );
    expect(tsv.split("\n")[0]).toBe("Ticker\tPrice\tNote");
  });
});

describe("rowsToCsv", () => {
  it("renders simple rows with comma separator", () => {
    const rows: Row[] = [{ ticker: "AAPL", price: 188.5, note: "buy" }];
    const csv = rowsToCsv(rows, cols as unknown as Parameters<typeof rowsToCsv<Row>>[1]);
    expect(csv).toBe("Ticker,Price,Note\nAAPL,188.5,buy");
  });

  it("quotes cells containing commas", () => {
    const rows: Row[] = [{ ticker: "AAPL", price: 188.5, note: "Apple, Inc." }];
    const csv = rowsToCsv(rows, cols as unknown as Parameters<typeof rowsToCsv<Row>>[1]);
    expect(csv).toMatch(/"Apple, Inc\."/);
  });

  it("escapes embedded quotes (RFC 4180)", () => {
    const rows: Row[] = [{ ticker: "AAPL", price: 188.5, note: 'has "quote"' }];
    const csv = rowsToCsv(rows, cols as unknown as Parameters<typeof rowsToCsv<Row>>[1]);
    expect(csv).toMatch(/"has ""quote"""/);
  });

  it("quotes cells containing newlines", () => {
    const rows: Row[] = [{ ticker: "AAPL", price: 188.5, note: "two\nlines" }];
    const csv = rowsToCsv(rows, cols as unknown as Parameters<typeof rowsToCsv<Row>>[1]);
    expect(csv).toMatch(/"two\nlines"/);
  });
});
