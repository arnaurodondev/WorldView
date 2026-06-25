/**
 * SortableHeaderCell.test.tsx — Wave-4 sortable header cell.
 *
 * Locks the a11y + interaction contract the holder/peer tables rely on:
 *   1. renders the label + a clickable button;
 *   2. fires onSort when clicked;
 *   3. carries the correct aria-sort token on the header cell (ascending /
 *      descending / none) for screen readers;
 *   4. supports both the `<th>` (table) and `<div>` (CSS-grid) layouts.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SortableHeaderCell } from "@/components/instrument/financials/SortableHeaderCell";

/** Wrap a `<th>`-mode cell in a valid table so role/aria are well-formed. */
function renderTh(props: Partial<React.ComponentProps<typeof SortableHeaderCell>> = {}) {
  return render(
    <table>
      <thead>
        <tr>
          <SortableHeaderCell
            label="Shares"
            active={false}
            direction="desc"
            onSort={() => {}}
            {...props}
          />
        </tr>
      </thead>
    </table>,
  );
}

describe("SortableHeaderCell", () => {
  it("renders the label inside a clickable button", () => {
    renderTh();
    expect(screen.getByRole("button", { name: /shares/i })).toBeInTheDocument();
  });

  it("fires onSort when clicked", () => {
    const onSort = vi.fn();
    renderTh({ onSort });
    fireEvent.click(screen.getByRole("button", { name: /shares/i }));
    expect(onSort).toHaveBeenCalledTimes(1);
  });

  it("reports aria-sort=none when inactive", () => {
    renderTh({ active: false });
    expect(screen.getByRole("columnheader")).toHaveAttribute("aria-sort", "none");
  });

  it("reports aria-sort=descending when active + desc", () => {
    renderTh({ active: true, direction: "desc" });
    expect(screen.getByRole("columnheader")).toHaveAttribute("aria-sort", "descending");
  });

  it("reports aria-sort=ascending when active + asc", () => {
    renderTh({ active: true, direction: "asc" });
    expect(screen.getByRole("columnheader")).toHaveAttribute("aria-sort", "ascending");
  });

  it("renders a columnheader role in div mode (CSS-grid layout)", () => {
    render(
      <SortableHeaderCell as="div" label="P/E" active direction="asc" onSort={() => {}} />,
    );
    const header = screen.getByRole("columnheader");
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getByRole("button", { name: /p\/e/i })).toBeInTheDocument();
  });
});
