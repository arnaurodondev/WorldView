/**
 * __tests__/rule-manager-dialog.test.tsx — server-backed RuleManagerDialog
 * (PLAN-0113 W4 T-4-06; rewritten from the legacy localStorage version).
 *
 * The old dialog stored rules in localStorage and showed a "(local only)" badge.
 * PLAN-0113 retired that — the manager now lists rules from the server
 * (`useAlertRules`) and pauses/deletes via the mutation hooks. These tests mock
 * the hooks module so we can assert the dialog renders server rows and wires
 * pause/delete to the right calls, without a real gateway.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RuleManagerDialog } from "@/components/alerts/RuleManagerDialog";
import type { AlertRule } from "@/lib/api/alertRules";

// ── Mock the alert-rules hooks ────────────────────────────────────────────────
// WHY mock the hooks (not the gateway): the dialog talks only to these hooks. A
// hook-level mock keeps the test focused on the dialog's behaviour + the calls
// it issues, and avoids standing up ApiClientProvider / QueryClient plumbing.

const deleteMutate = vi.fn().mockResolvedValue(undefined);
const updateMutate = vi.fn().mockResolvedValue({});
const listResult: {
  data: { items: AlertRule[]; total: number };
  isLoading: boolean;
  isError: boolean;
} = {
  data: { items: [], total: 0 },
  isLoading: false,
  isError: false,
};

vi.mock("@/lib/api/useAlertRules", () => ({
  useAlertRules: () => listResult,
  useDeleteAlertRule: () => ({ mutateAsync: deleteMutate, isPending: false }),
  useUpdateAlertRule: () => ({ mutateAsync: updateMutate, isPending: false }),
  useCreateAlertRule: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

// AlertWizard is exercised in its own test; stub it here so opening the wizard
// doesn't pull the full picker/editor tree into this dialog-focused test.
vi.mock("@/components/alerts/AlertWizard", () => ({
  AlertWizard: ({ open }: { open: boolean }) =>
    open ? <div data-testid="alert-wizard-stub">wizard</div> : null,
}));

// ── Fixture ───────────────────────────────────────────────────────────────────

const PRICE_RULE: AlertRule = {
  rule_id: "rule-1",
  tenant_id: "t1",
  user_id: "u1",
  rule_type: "PRICE_CROSS",
  name: "AAPL price alert",
  entity_id: "i-aapl",
  node_a_entity_id: null,
  node_b_entity_id: null,
  condition: { instrument_id: "i-aapl", operator: "above", value: 250 },
  severity: "medium",
  enabled: true,
  cooldown_seconds: 3600,
  notify_in_app: true,
  notify_email: false,
  last_state: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

describe("RuleManagerDialog (server-backed)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listResult.data = { items: [], total: 0 };
    listResult.isLoading = false;
    listResult.isError = false;
  });

  it("shows the empty state when the server returns no rules", async () => {
    const user = userEvent.setup();
    render(<RuleManagerDialog />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));
    expect(await screen.findByText(/No alert rules defined yet/i)).toBeInTheDocument();
    // The legacy "(local only)" badge must be gone.
    expect(screen.queryByText(/local only/i)).not.toBeInTheDocument();
  });

  it("lists server rules with an NL summary (no local-only badge)", async () => {
    listResult.data = { items: [PRICE_RULE], total: 1 };
    const user = userEvent.setup();
    render(<RuleManagerDialog />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));

    expect(await screen.findByText(/AAPL price alert/i)).toBeInTheDocument();
    // NL summary derived from the structured condition.
    expect(screen.getByText(/price crosses above 250/i)).toBeInTheDocument();
    expect(screen.queryByText(/local only/i)).not.toBeInTheDocument();
  });

  it("toggling enabled calls updateAlertRule with the new flag", async () => {
    listResult.data = { items: [PRICE_RULE], total: 1 };
    const user = userEvent.setup();
    render(<RuleManagerDialog />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));

    const toggle = await screen.findByRole("checkbox", {
      name: /Toggle rule AAPL price alert/i,
    });
    await user.click(toggle); // currently enabled → un-checking pauses it

    await waitFor(() => {
      expect(updateMutate).toHaveBeenCalledWith({
        ruleId: "rule-1",
        patch: { enabled: false },
      });
    });
  });

  it("delete calls deleteAlertRule with the rule id", async () => {
    listResult.data = { items: [PRICE_RULE], total: 1 };
    const user = userEvent.setup();
    render(<RuleManagerDialog />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));

    await user.click(
      await screen.findByRole("button", { name: /Delete rule AAPL price alert/i }),
    );
    await waitFor(() => {
      expect(deleteMutate).toHaveBeenCalledWith("rule-1");
    });
  });

  it("opens the wizard when 'New rule' is clicked", async () => {
    const user = userEvent.setup();
    render(<RuleManagerDialog />);
    await user.click(screen.getByRole("button", { name: /Manage alert rules/i }));
    await user.click(
      await screen.findByRole("button", { name: /Create new alert rule/i }),
    );
    expect(await screen.findByTestId("alert-wizard-stub")).toBeInTheDocument();
  });
});
