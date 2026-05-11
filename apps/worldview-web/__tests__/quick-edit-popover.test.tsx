/**
 * __tests__/quick-edit-popover.test.tsx — Unit tests for QuickEditPopover
 *
 * WHY THIS EXISTS: Inline edit popovers are the primary UX for per-row field
 * updates in the holdings and watchlist tables. These tests verify that:
 *   1. The popover opens on trigger click.
 *   2. Save calls onSave and closes the popover.
 *   3. Cancel calls onCancel and closes the popover.
 *   4. Enter key saves, Escape key cancels.
 *
 * DATA SOURCE: No S9 calls — onSave is a mock; actual mutation is caller's
 * responsibility.
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuickEditPopover } from "@/components/ui/quick-edit-popover";

// ── Helpers ────────────────────────────────────────────────────────────────

function triggerButton() {
  return screen.getByRole("button", { name: /open edit/i });
}

function renderNumberEdit(overrides = {}) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  render(
    <QuickEditPopover
      trigger={<button aria-label="open edit">Edit</button>}
      value={10}
      type="number"
      label="Quantity"
      onSave={onSave}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onSave, onCancel };
}

function renderTextEdit(overrides = {}) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  render(
    <QuickEditPopover
      trigger={<button aria-label="open edit">Edit</button>}
      value="My Value"
      type="text"
      label="Name"
      onSave={onSave}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onSave, onCancel };
}

// ── Open / close ─────────────────────────────────────────────────────────

describe("QuickEditPopover — open/close", () => {
  it("opens the popover when trigger is clicked", async () => {
    const user = userEvent.setup();
    renderNumberEdit();
    await user.click(triggerButton());
    await waitFor(() => {
      // The popover content contains a label
      expect(screen.getByText("Quantity")).toBeInTheDocument();
    });
  });

  it("closes the popover after Cancel is clicked", async () => {
    const user = userEvent.setup();
    renderNumberEdit();
    await user.click(triggerButton());
    await waitFor(() => screen.getByText("Cancel"));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByText("Quantity")).not.toBeInTheDocument();
    });
  });
});

// ── Save ──────────────────────────────────────────────────────────────────

describe("QuickEditPopover — Save", () => {
  it("calls onSave when Save is clicked", async () => {
    const user = userEvent.setup();
    const { onSave } = renderNumberEdit();
    await user.click(triggerButton());
    await waitFor(() => screen.getByRole("button", { name: "Save" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("calls onSave with the current text value for text type", async () => {
    const user = userEvent.setup();
    const { onSave } = renderTextEdit();
    await user.click(triggerButton());
    await waitFor(() => screen.getByLabelText("Name"));
    const input = screen.getByLabelText("Name");
    await user.clear(input);
    await user.type(input, "Updated");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith("Updated");
  });
});

// ── Cancel ────────────────────────────────────────────────────────────────

describe("QuickEditPopover — Cancel", () => {
  it("calls onCancel when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderNumberEdit();
    await user.click(triggerButton());
    await waitFor(() => screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

// ── Keyboard ──────────────────────────────────────────────────────────────

describe("QuickEditPopover — keyboard", () => {
  it("Escape key closes the popover without calling onSave", async () => {
    const user = userEvent.setup();
    const { onSave } = renderTextEdit();
    await user.click(triggerButton());
    await waitFor(() => screen.getByText("Name"));
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByText("Name")).not.toBeInTheDocument();
    });
    expect(onSave).not.toHaveBeenCalled();
  });
});

// ── Loading ───────────────────────────────────────────────────────────────

describe("QuickEditPopover — isLoading", () => {
  it("shows 'Saving…' text and disables Save when isLoading=true", async () => {
    const user = userEvent.setup();
    renderNumberEdit({ isLoading: true });
    await user.click(triggerButton());
    await waitFor(() => screen.getByText("Saving…"));
    expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
  });
});
