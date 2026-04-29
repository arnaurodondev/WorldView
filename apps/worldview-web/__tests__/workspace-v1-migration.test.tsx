/**
 * __tests__/workspace-v1-migration.test.tsx — v1 → v2 migration cleanup.
 *
 * QA-iter1 MIN-2: ``migrateV1`` previously kept panels whose ``type`` was
 * removed from the catalogue, leaving behind empty placeholder cells. We
 * now filter out unsupported types — pinned by this test so a future tweak
 * to the PanelType union can't quietly regress this behaviour.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import React from "react";
import {
  WorkspaceProvider,
  useWorkspace,
} from "@/contexts/WorkspaceContext";

// Probe component that exposes the resolved workspaces shape via JSON.
function Probe() {
  const ctx = useWorkspace();
  return <div data-testid="probe">{JSON.stringify(ctx.workspaces)}</div>;
}

beforeEach(() => {
  // Wipe both keys so each test starts clean.
  try {
    localStorage.removeItem("worldview-workspaces");
    localStorage.removeItem("worldview:workspaces:v2");
    localStorage.removeItem("worldview:workspaces:v2:active");
  } catch {
    /* opaque-origin tolerant */
  }
});

describe("WorkspaceContext.migrateV1 — unsupported panel pruning", () => {
  it("drops panels whose type is not in the catalogue (QA-iter1 MIN-2)", async () => {
    // Seed legacy storage with a v1 config containing one valid + one
    // unsupported panel type. After the provider mounts, the migration
    // path should drop the unsupported entry.
    const legacy = [
      {
        id: "ws-1",
        name: "Legacy",
        rows: [
          {
            panels: [
              { id: "p-1", type: "chart" },
              // "old-experimental-widget" was never (or no longer) in PanelType
              { id: "p-2", type: "old-experimental-widget" },
            ],
          },
        ],
      },
    ];
    localStorage.setItem("worldview-workspaces", JSON.stringify(legacy));

    // Silence the expected warning so the test output stays clean.
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const { getByTestId } = render(
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>,
    );

    await waitFor(() => {
      const json = getByTestId("probe").textContent ?? "";
      expect(json).toContain("chart");
      // The unsupported type MUST NOT survive the migration.
      expect(json).not.toContain("old-experimental-widget");
    });

    // The migrator MUST have surfaced a warning so debugging is possible.
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("preserves all panels when every type is supported", async () => {
    const legacy = [
      {
        id: "ws-1",
        name: "Legacy",
        rows: [
          {
            panels: [
              { id: "p-1", type: "chart" },
              { id: "p-2", type: "watchlist" },
            ],
          },
        ],
      },
    ];
    localStorage.setItem("worldview-workspaces", JSON.stringify(legacy));

    const { getByTestId } = render(
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>,
    );

    await waitFor(() => {
      const json = getByTestId("probe").textContent ?? "";
      expect(json).toContain("chart");
      expect(json).toContain("watchlist");
    });
  });
});
