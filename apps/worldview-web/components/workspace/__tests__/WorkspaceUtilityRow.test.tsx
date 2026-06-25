/**
 * components/workspace/__tests__/WorkspaceUtilityRow.test.tsx
 *
 * WHY: Unit tests for WorkspaceUtilityRow (PRD-0089 Wave J).
 * Tests verify:
 *   1. All three action buttons render with correct labels.
 *   2. Each button fires its callback when clicked.
 *   3. The CrosshairSyncToggle flips state on click.
 *   4. The toggle's aria-pressed attribute reflects current sync state.
 *
 * WHY these test scenarios (not implementation details):
 * WorkspaceUtilityRow is a 24px strip — its contract is "render buttons,
 * fire callbacks". Tests at this level give fast feedback on regressions
 * without coupling to CSS class names or internal state shape.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WorkspaceUtilityRow } from "../WorkspaceUtilityRow";
import { WorkspaceSyncProvider } from "@/contexts/WorkspaceSyncContext";
import type { WorkspaceConfig } from "@/contexts/WorkspaceContext";

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Minimal WorkspaceConfig for tests — only fields WorkspaceUtilityRow reads. */
function makeWorkspace(overrides: Partial<WorkspaceConfig> = {}): WorkspaceConfig {
  return {
    id: "ws-1",
    name: "Test Workspace",
    rows: [],
    ...overrides,
  };
}

/**
 * renderUtilityRow — wraps in WorkspaceSyncProvider (required by CrosshairSyncToggle)
 * and supplies default no-op callbacks.
 */
function renderUtilityRow(props: {
  onAddPanel?: () => void;
  onTemplate?: () => void;
  onShare?: () => void;
}) {
  return render(
    <WorkspaceSyncProvider>
      <WorkspaceUtilityRow
        workspace={makeWorkspace()}
        onAddPanel={props.onAddPanel ?? vi.fn()}
        onTemplate={props.onTemplate ?? vi.fn()}
        onShare={props.onShare ?? vi.fn()}
      />
    </WorkspaceSyncProvider>,
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("WorkspaceUtilityRow", () => {
  it("renders the Add panel button", () => {
    renderUtilityRow({});
    expect(screen.getByTestId("add-panel-button")).toBeInTheDocument();
    expect(screen.getByTestId("add-panel-button")).toHaveAccessibleName(/add a new panel/i);
  });

  it("renders the Template button", () => {
    renderUtilityRow({});
    expect(screen.getByTestId("template-button")).toBeInTheDocument();
    expect(screen.getByTestId("template-button")).toHaveAccessibleName(/template/i);
  });

  it("renders the Share button", () => {
    renderUtilityRow({});
    expect(screen.getByTestId("share-button")).toBeInTheDocument();
    expect(screen.getByTestId("share-button")).toHaveAccessibleName(/share/i);
  });

  it("calls onAddPanel when Add panel button is clicked", () => {
    const onAddPanel = vi.fn();
    renderUtilityRow({ onAddPanel });
    fireEvent.click(screen.getByTestId("add-panel-button"));
    expect(onAddPanel).toHaveBeenCalledTimes(1);
  });

  it("calls onTemplate when Template button is clicked", () => {
    const onTemplate = vi.fn();
    renderUtilityRow({ onTemplate });
    fireEvent.click(screen.getByTestId("template-button"));
    expect(onTemplate).toHaveBeenCalledTimes(1);
  });

  it("calls onShare when Share button is clicked", () => {
    const onShare = vi.fn();
    renderUtilityRow({ onShare });
    fireEvent.click(screen.getByTestId("share-button"));
    expect(onShare).toHaveBeenCalledTimes(1);
  });

  describe("CrosshairSyncToggle", () => {
    it("renders the sync toggle button", () => {
      renderUtilityRow({});
      expect(screen.getByTestId("crosshair-sync-toggle")).toBeInTheDocument();
    });

    it("starts with sync disabled (aria-pressed=false)", () => {
      renderUtilityRow({});
      const toggle = screen.getByTestId("crosshair-sync-toggle");
      expect(toggle).toHaveAttribute("aria-pressed", "false");
    });

    it("enables sync on first click (aria-pressed=true)", () => {
      renderUtilityRow({});
      const toggle = screen.getByTestId("crosshair-sync-toggle");
      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-pressed", "true");
    });

    it("toggles back to disabled on second click", () => {
      renderUtilityRow({});
      const toggle = screen.getByTestId("crosshair-sync-toggle");
      fireEvent.click(toggle); // → enabled
      fireEvent.click(toggle); // → disabled
      expect(toggle).toHaveAttribute("aria-pressed", "false");
    });

    it("shows 'Sync on' label when enabled", () => {
      renderUtilityRow({});
      const toggle = screen.getByTestId("crosshair-sync-toggle");
      fireEvent.click(toggle);
      // WHY textContent check: the toggle uses a <span> for the label text.
      expect(toggle.textContent).toContain("Sync on");
    });

    it("shows 'Sync off' label when disabled", () => {
      renderUtilityRow({});
      const toggle = screen.getByTestId("crosshair-sync-toggle");
      // Default state is off
      expect(toggle.textContent).toContain("Sync off");
    });
  });
});
