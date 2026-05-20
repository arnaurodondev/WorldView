/**
 * __tests__/primitives/TableRow.test.tsx
 *
 * PRD-0089 F1: pins the role=row + interactive-hover contract so the
 * [data-table-grid] global rule resolves the row height correctly.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TableRow } from "@/components/primitives/TableRow";

describe("TableRow", () => {
  it("renders role=row by default and is not focusable when non-interactive", () => {
    render(
      <TableRow>
        <div role="cell">a</div>
      </TableRow>,
    );
    const row = screen.getByRole("row");
    expect(row).toBeInTheDocument();
    expect(row).toHaveAttribute("tabIndex", "-1");
  });

  it("applies hover transition class when interactive=true", () => {
    render(
      <TableRow interactive>
        <div role="cell">a</div>
      </TableRow>,
    );
    const row = screen.getByRole("row");
    expect(row.className).toContain("hover:bg-muted/50");
    expect(row).toHaveAttribute("tabIndex", "0");
  });
});
