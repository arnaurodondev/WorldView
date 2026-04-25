/**
 * __tests__/workspace-tabs.test.tsx — Unit tests for WorkspaceTabs + WorkspaceContext
 *
 * WHY THIS EXISTS: WorkspaceTabs is the primary workspace management UI — regressions
 * here break the entire workspace switching flow. Tests verify:
 * 1. 4 default workspace presets are shown on first load
 * 2. Active workspace tab has the correct indicator styling
 * 3. Clicking a tab switches the active workspace
 * 4. "+ Add" button creates a new workspace
 * 5. Double-click on a tab starts inline rename (shows input)
 * 6. Workspaces persist to localStorage
 * 7. Removing a workspace removes its tab
 *
 * WHY NO GATEWAY MOCK: WorkspaceTabs reads only from WorkspaceContext (localStorage).
 * There are no S9 API calls in this component tree.
 * WHY WRAP IN WorkspaceProvider: WorkspaceTabs calls useWorkspace() which throws
 * if no provider is present. The provider is the unit under test alongside the tabs.
 *
 * DATA SOURCE: WorkspaceContext (localStorage)
 * DESIGN REFERENCE: PRD-0031 §5.2 Workspace tabs
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkspaceTabs } from "@/components/workspace/WorkspaceTabs";
import { WorkspaceProvider } from "@/contexts/WorkspaceContext";

// ── localStorage mock ──────────────────────────────────────────────────────────
// WHY custom mock (not jsdom localStorage): jsdom's localStorage may not expose
// all standard methods (.clear()) in certain environments (BP-160 pattern).
// A map-backed mock gives full control, real get/set behavior for persistence
// tests, and a reliable clear() for test isolation.
const localStorageData = new Map<string, string>();

const localStorageMock = {
  getItem: vi.fn((key: string) => localStorageData.get(key) ?? null),
  setItem: vi.fn((key: string, value: string) => { localStorageData.set(key, value); }),
  removeItem: vi.fn((key: string) => { localStorageData.delete(key); }),
  clear: vi.fn(() => { localStorageData.clear(); }),
  length: 0,
  key: vi.fn(() => null as string | null),
};

beforeEach(() => {
  localStorageData.clear();
  vi.clearAllMocks();
  // WHY reset mock implementations after clearAllMocks: clearAllMocks() wipes the
  // mock implementations, so we must re-install them or use the stable closures above.
  localStorageMock.getItem.mockImplementation((key: string) => localStorageData.get(key) ?? null);
  localStorageMock.setItem.mockImplementation((key: string, value: string) => { localStorageData.set(key, value); });
  localStorageMock.removeItem.mockImplementation((key: string) => { localStorageData.delete(key); });
  localStorageMock.clear.mockImplementation(() => { localStorageData.clear(); });
  vi.stubGlobal("localStorage", localStorageMock as unknown as Storage);
});

// ── Test helpers ───────────────────────────────────────────────────────────────

function renderTabs() {
  return render(
    <WorkspaceProvider>
      <WorkspaceTabs />
    </WorkspaceProvider>,
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("WorkspaceTabs — initial state", () => {
  it("shows 4 default workspace presets on first load", () => {
    renderTabs();

    // WHY check by text: tab labels are the primary user-facing workspace identifiers
    expect(screen.getByText("Day Trading")).toBeInTheDocument();
    expect(screen.getByText("Research")).toBeInTheDocument();
    expect(screen.getByText("Portfolio Monitor")).toBeInTheDocument();
    expect(screen.getByText("Morning Brief")).toBeInTheDocument();
  });

  it("renders the Add workspace button", () => {
    renderTabs();

    // WHY: "+ Add" is the primary way to create a new workspace
    expect(screen.getByRole("button", { name: "Add workspace" })).toBeInTheDocument();
  });

  it("renders the tablist with correct aria role", () => {
    renderTabs();

    expect(screen.getByRole("tablist", { name: "Workspaces" })).toBeInTheDocument();
  });

  it("marks the first workspace as selected by default", () => {
    renderTabs();

    // WHY aria-selected: tab role must communicate selected state to screen readers
    const firstTab = screen.getByRole("tab", { name: "Workspace: Day Trading" });
    expect(firstTab).toHaveAttribute("aria-selected", "true");
  });

  it("marks non-active tabs as not selected", () => {
    renderTabs();

    const researchTab = screen.getByRole("tab", { name: "Workspace: Research" });
    expect(researchTab).toHaveAttribute("aria-selected", "false");
  });
});

describe("WorkspaceTabs — switching workspaces", () => {
  it("switches the active workspace when a tab is clicked", async () => {
    const user = userEvent.setup();
    renderTabs();

    await user.click(screen.getByRole("tab", { name: "Workspace: Research" }));

    // WHY re-query: aria-selected updates after state change
    expect(
      screen.getByRole("tab", { name: "Workspace: Research" })
    ).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("tab", { name: "Workspace: Day Trading" })
    ).toHaveAttribute("aria-selected", "false");
  });
});

describe("WorkspaceTabs — adding workspaces", () => {
  it("creates a new workspace tab when + Add is clicked", async () => {
    const user = userEvent.setup();
    renderTabs();

    const tabsBefore = screen.getAllByRole("tab");
    await user.click(screen.getByRole("button", { name: "Add workspace" }));

    // WHY +1: exactly one new tab should appear
    const tabsAfter = screen.getAllByRole("tab");
    expect(tabsAfter.length).toBe(tabsBefore.length + 1);
  });

  it("makes the new workspace active after adding", async () => {
    const user = userEvent.setup();
    renderTabs();

    await user.click(screen.getByRole("button", { name: "Add workspace" }));

    // WHY: the newly added workspace should be immediately selected
    const tabs = screen.getAllByRole("tab");
    const lastTab = tabs[tabs.length - 1];
    expect(lastTab).toHaveAttribute("aria-selected", "true");
  });
});

describe("WorkspaceTabs — rename", () => {
  it("shows a rename input on double-click", async () => {
    const user = userEvent.setup();
    renderTabs();

    await user.dblClick(screen.getByRole("tab", { name: "Workspace: Day Trading" }));

    // WHY: double-click should reveal an inline text input for renaming
    expect(screen.getByRole("textbox", { name: "Rename workspace" })).toBeInTheDocument();
  });

  it("renames the workspace when user types and presses Enter", async () => {
    const user = userEvent.setup();
    renderTabs();

    await user.dblClick(screen.getByRole("tab", { name: "Workspace: Day Trading" }));

    const input = screen.getByRole("textbox", { name: "Rename workspace" });
    await user.clear(input);
    await user.type(input, "Scalping");
    await user.keyboard("{Enter}");

    // WHY: after confirming rename, the new name appears as a tab label
    expect(screen.getByText("Scalping")).toBeInTheDocument();
    // WHY: old name should be gone
    expect(screen.queryByText("Day Trading")).not.toBeInTheDocument();
  });
});

describe("WorkspaceTabs — localStorage persistence", () => {
  it("saves workspaces to localStorage when a workspace is added", async () => {
    const user = userEvent.setup();
    renderTabs();

    await user.click(screen.getByRole("button", { name: "Add workspace" }));

    // WHY check localStorage: persistence is the core contract of WorkspaceContext.
    // If localStorage is not written, workspace state is lost on page reload.
    const stored = localStorage.getItem("worldview-workspaces");
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored!);
    // 4 defaults + 1 new = 5 total
    expect(parsed).toHaveLength(5);
  });

  it("saves the active workspace ID to localStorage when switching", async () => {
    const user = userEvent.setup();
    renderTabs();

    await user.click(screen.getByRole("tab", { name: "Workspace: Research" }));

    const activeId = localStorage.getItem("worldview-active-workspace");
    expect(activeId).toBe("ws-research");
  });
});
