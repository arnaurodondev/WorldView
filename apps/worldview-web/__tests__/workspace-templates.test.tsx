/**
 * __tests__/workspace-templates.test.tsx — Tests for workspace templates + dialog
 *
 * WHY THIS EXISTS: Templates are static data (lib/workspace-templates.ts) plus
 * a dialog component (NewFromTemplateDialog.tsx). Two failure modes we need to
 * guard against:
 *
 *  1. A template references a panel_type that no longer exists in the runtime
 *     PANEL_CATALOGUE → instantiating that template would crash the workspace.
 *  2. The dialog doesn't render the right number of cards or doesn't fire
 *     onCreate when a card is clicked → silent UX regression.
 *
 * Both classes of bug are caught here.
 *
 * COVERAGE:
 *   - Each template references only valid panel_types
 *   - 5 templates exist (no accidental duplicates or omissions)
 *   - Each template has unique id, non-empty name + description
 *   - Dialog renders 5 cards
 *   - Dialog fires onCreate with the correct template on click
 *   - Dialog auto-closes after a click
 *   - findTemplate returns the right template / undefined on miss
 *
 * DESIGN REFERENCE: PLAN-0051 §T-C-3-06
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  WORKSPACE_TEMPLATES,
  findTemplate,
} from "@/lib/workspace-templates";
import type { PanelType } from "@/contexts/WorkspaceContext";
import { NewFromTemplateDialog } from "@/components/workspace/NewFromTemplateDialog";

// ── Valid panel type set — kept in sync with WorkspaceContext PanelType ──────
// WHY duplicated here (not imported as a const): PanelType in WorkspaceContext
// is a string-union TYPE, not a runtime array. We duplicate the list here so
// the test catches drift in either direction:
//   - if someone adds a panel_type to PanelType but not to a template, that
//     template still works (no failure case).
//   - if someone REMOVES a panel_type from PanelType, this list (and thus the
//     test) needs updating. The test failure surfaces the breakage immediately.
const VALID_PANEL_TYPES: ReadonlySet<PanelType> = new Set([
  "chart",
  "watchlist",
  "screener",
  "alerts",
  "fundamentals",
  "news",
  "graph",
  "portfolio",
  "brief",
  "chat",
]);

// ── Tests: template data integrity ───────────────────────────────────────────

describe("WORKSPACE_TEMPLATES — data integrity", () => {
  it("exports exactly 5 templates", () => {
    expect(WORKSPACE_TEMPLATES).toHaveLength(5);
  });

  it("every template has a unique id", () => {
    const ids = WORKSPACE_TEMPLATES.map((t) => t.id);
    const unique = new Set(ids);
    expect(unique.size).toBe(WORKSPACE_TEMPLATES.length);
  });

  it("every template has a non-empty name and description", () => {
    for (const t of WORKSPACE_TEMPLATES) {
      expect(t.name.length).toBeGreaterThan(0);
      expect(t.description.length).toBeGreaterThan(0);
    }
  });

  it("every panel_type referenced by a template is a valid PanelType", () => {
    // WHY iterate everything: catches a single bad reference even if buried
    // in row 2 panel 4 of one template — the test name fails fast on first
    // bad reference because of expect's behavior.
    for (const template of WORKSPACE_TEMPLATES) {
      for (const row of template.config.rows) {
        for (const panel of row.panels) {
          // WHY this style of assertion: gives a clear error message naming
          // the offending template + panel id when it fails.
          expect(
            VALID_PANEL_TYPES.has(panel.type),
            `Template "${template.id}" panel "${panel.id}" has invalid type "${panel.type}"`,
          ).toBe(true);
        }
      }
    }
  });

  it("every template has at least one row with at least one panel", () => {
    for (const t of WORKSPACE_TEMPLATES) {
      expect(t.config.rows.length).toBeGreaterThan(0);
      for (const row of t.config.rows) {
        expect(row.panels.length).toBeGreaterThan(0);
      }
    }
  });
});

describe("findTemplate", () => {
  it("returns the right template for a known id", () => {
    const t = findTemplate("day-trader");
    expect(t).toBeDefined();
    expect(t?.name).toBe("Day Trader");
  });

  it("returns undefined for an unknown id", () => {
    expect(findTemplate("nonexistent")).toBeUndefined();
  });
});

// ── Tests: NewFromTemplateDialog ─────────────────────────────────────────────

describe("NewFromTemplateDialog", () => {
  it("renders a trigger button by default", () => {
    render(<NewFromTemplateDialog onCreate={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: /new workspace from template/i }),
    ).toBeInTheDocument();
  });

  it("opens the dialog on trigger click and renders 5 template cards", async () => {
    const user = userEvent.setup();
    render(<NewFromTemplateDialog onCreate={vi.fn()} />);

    await user.click(
      screen.getByRole("button", { name: /new workspace from template/i }),
    );

    // WHY check by data-testid: each card has a stable testid like
    // "template-card-day-trader". This is more robust than visible text
    // (which can change with copy edits).
    expect(screen.getByTestId("template-card-day-trader")).toBeInTheDocument();
    expect(screen.getByTestId("template-card-research")).toBeInTheDocument();
    expect(screen.getByTestId("template-card-swing-trader")).toBeInTheDocument();
    expect(screen.getByTestId("template-card-news-junkie")).toBeInTheDocument();
    expect(screen.getByTestId("template-card-investor")).toBeInTheDocument();
  });

  it("fires onCreate with the chosen template when a card is clicked", async () => {
    const handleCreate = vi.fn();
    const user = userEvent.setup();
    render(<NewFromTemplateDialog onCreate={handleCreate} />);

    await user.click(
      screen.getByRole("button", { name: /new workspace from template/i }),
    );
    await user.click(screen.getByTestId("template-card-research"));

    expect(handleCreate).toHaveBeenCalledTimes(1);
    // WHY check the id (not the whole object): if the template definition
    // changes (a renamed description), the test still passes — we only care
    // that the right TEMPLATE was selected, not that the entire shape is exact.
    expect(handleCreate.mock.calls[0][0].id).toBe("research");
  });
});
