/**
 * components/instrument/graph/__tests__/GraphToolbar.test.tsx
 *
 * WHY THIS EXISTS (entity-type MULTISELECT enhancement 2026-06-15): the graph
 * toolbar's type filter was upgraded from a single-value <Select> (one type or
 * "All") to a Popover + checkbox MULTISELECT so the analyst can study a SUBSET
 * of types at once (e.g. people + organizations, hiding instruments). The
 * parent (GraphColumn) already held the whitelist as `string[]` and its
 * filter treats `[]` as "show all", so the contract here is:
 *   - toggling a type ADDS/REMOVES it from the whitelist array (multi),
 *   - "Show all types" clears the whitelist to [].
 * These tests pin that controlled-component contract (render → click →
 * assert the callback fired with the right array).
 *
 * The Popover is Radix; we open it by clicking the trigger, then interact with
 * the checkbox rows inside the rendered content.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// eslint-disable-next-line import/first
import { GraphToolbar } from "@/components/instrument/graph/GraphToolbar";

const TYPES = ["financial_instrument", "organization", "person"];

function renderToolbar(overrides: Partial<React.ComponentProps<typeof GraphToolbar>> = {}) {
  const onDepthChange = vi.fn();
  const onEntityTypesChange = vi.fn();
  const props = {
    depth: 2,
    onDepthChange,
    selectedEntityTypes: [] as string[],
    onEntityTypesChange,
    availableEntityTypes: TYPES,
    ...overrides,
  };
  render(<GraphToolbar {...props} />);
  return { onDepthChange, onEntityTypesChange };
}

describe("GraphToolbar entity-type multiselect", () => {
  it("shows 'All types' on the trigger when the whitelist is empty", () => {
    renderToolbar();
    expect(screen.getByTestId("entity-type-select")).toHaveTextContent(/all types/i);
  });

  it("disables the trigger when no types are available yet (loading)", () => {
    renderToolbar({ availableEntityTypes: [] });
    expect(screen.getByTestId("entity-type-select")).toBeDisabled();
  });

  it("adds a type to the whitelist when its checkbox is toggled on", () => {
    const { onEntityTypesChange } = renderToolbar();
    fireEvent.click(screen.getByTestId("entity-type-select")); // open popover
    fireEvent.click(screen.getByTestId("entity-type-checkbox-person"));
    expect(onEntityTypesChange).toHaveBeenCalledWith(["person"]);
  });

  it("ADDS a second type (multiselect) without dropping the first", () => {
    // Start with one type already selected → toggling another must keep both.
    const { onEntityTypesChange } = renderToolbar({ selectedEntityTypes: ["person"] });
    fireEvent.click(screen.getByTestId("entity-type-select"));
    fireEvent.click(screen.getByTestId("entity-type-checkbox-organization"));
    expect(onEntityTypesChange).toHaveBeenCalledWith(["person", "organization"]);
  });

  it("REMOVES a type when its already-checked box is toggled off", () => {
    const { onEntityTypesChange } = renderToolbar({
      selectedEntityTypes: ["person", "organization"],
    });
    fireEvent.click(screen.getByTestId("entity-type-select"));
    fireEvent.click(screen.getByTestId("entity-type-checkbox-person"));
    expect(onEntityTypesChange).toHaveBeenCalledWith(["organization"]);
  });

  it("shows an 'N types' count on the trigger when several are active", () => {
    renderToolbar({ selectedEntityTypes: ["person", "organization"] });
    expect(screen.getByTestId("entity-type-select")).toHaveTextContent(/2 types/i);
  });

  it("'Show all types' clears the whitelist to []", () => {
    const { onEntityTypesChange } = renderToolbar({ selectedEntityTypes: ["person"] });
    fireEvent.click(screen.getByTestId("entity-type-select"));
    fireEvent.click(screen.getByRole("button", { name: /show all types/i }));
    expect(onEntityTypesChange).toHaveBeenCalledWith([]);
  });
});
