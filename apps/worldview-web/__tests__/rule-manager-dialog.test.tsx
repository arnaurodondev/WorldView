/**
 * __tests__/rule-manager-dialog.test.tsx — PLAN-0051 T-D-4-06 RuleManager.
 *
 * Covers the full CRUD flow through the dialog UI:
 *   - List tab shows seeded rules + a "(local only)" badge.
 *   - Create flow: switching to Edit, filling the form, Save returns to List.
 *   - Edit flow: clicking the pencil icon pre-fills the form.
 *   - Delete flow: clicking the trash icon removes the row.
 *   - Toggle enabled inline.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RuleManagerDialog } from "@/components/alerts/RuleManagerDialog";
import { createAlertRule, listAlertRules } from "@/lib/alerts/rules";

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

async function seedRule() {
  // Helper: pre-populate localStorage with one rule so the List tab has content.
  await createAlertRule({
    name: "AAPL price alert",
    type: "price_threshold",
    entitySearch: "AAPL",
    condition: "price > 200",
    enabled: true,
    notifyInApp: true,
    notifyEmail: false,
  });
}

describe("RuleManagerDialog", () => {
  it("opens and shows existing rules with a 'local only' badge", async () => {
    const user = userEvent.setup();
    await seedRule();

    render(<RuleManagerDialog />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));

    expect(await screen.findByText(/AAPL price alert/i)).toBeInTheDocument();
    expect(screen.getByText(/local only/i)).toBeInTheDocument();
    expect(screen.getByText(/price > 200/)).toBeInTheDocument();
  });

  it("creates a new rule via the Edit tab and returns to List", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    render(<RuleManagerDialog onRulesChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));

    await user.click(await screen.findByRole("button", { name: /Create new alert rule/i }));

    // Fill condition (required) — the others have defaults.
    const conditionInput = await screen.findByLabelText(/Rule condition/i);
    await user.type(conditionInput, "vol > 1m");
    await user.click(screen.getByRole("button", { name: /Create rule/i }));

    // After save we land back on the List tab and the rule is persisted.
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const rules = await listAlertRules();
    expect(rules).toHaveLength(1);
    expect(rules[0].condition).toBe("vol > 1m");
  });

  it("loads a rule into the Edit tab when clicking the pencil icon", async () => {
    const user = userEvent.setup();
    await seedRule();
    render(<RuleManagerDialog />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));

    await user.click(await screen.findByRole("button", { name: /Edit rule AAPL price alert/i }));

    const conditionInput = await screen.findByLabelText(/Rule condition/i);
    expect(conditionInput).toHaveValue("price > 200");
  });

  it("deletes a rule via the trash icon", async () => {
    const user = userEvent.setup();
    await seedRule();
    const onChanged = vi.fn();
    render(<RuleManagerDialog onRulesChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));

    await user.click(await screen.findByRole("button", { name: /Delete rule AAPL price alert/i }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const remaining = await listAlertRules();
    expect(remaining).toHaveLength(0);
  });

  it("toggles enabled flag inline without leaving the List tab", async () => {
    const user = userEvent.setup();
    await seedRule();
    render(<RuleManagerDialog />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));

    const li = (await screen.findByText(/AAPL price alert/)).closest("li");
    expect(li).not.toBeNull();
    const toggle = within(li!).getByRole("checkbox", { name: /Toggle rule AAPL price alert/i });
    await user.click(toggle);

    await waitFor(async () => {
      const rules = await listAlertRules();
      expect(rules[0].enabled).toBe(false);
    });
  });

  it("supports an entity prefill for the Edit tab", async () => {
    const user = userEvent.setup();
    render(<RuleManagerDialog prefillEntity="TSLA" />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));

    // Switch to Edit tab — the prefill should populate the entity input.
    await user.click(await screen.findByRole("button", { name: /Create new alert rule/i }));
    const entityInput = await screen.findByPlaceholderText(/AAPL/i);
    expect(entityInput).toHaveValue("TSLA");
  });
});
