/**
 * __tests__/primitives/BulkActionToolbar.test.tsx
 *
 * PRD-0089 F1: pins the hide-when-zero contract + action wiring.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { BulkActionToolbar } from "@/components/primitives/BulkActionToolbar";

describe("BulkActionToolbar", () => {
  it("renders null when selectedCount is 0", () => {
    const { container } = render(
      <BulkActionToolbar selectedCount={0} actions={[]} onClear={() => {}} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders count + clear button + actions when selectedCount > 0", () => {
    const onClear = vi.fn();
    const onAction = vi.fn();
    render(
      <BulkActionToolbar
        selectedCount={3}
        actions={[{ label: "Delete", onAction, destructive: true }]}
        onClear={onClear}
      />,
    );
    expect(screen.getByText(/3 rows selected/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Clear"));
    expect(onClear).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByText("Delete"));
    expect(onAction).toHaveBeenCalledOnce();
  });
});
