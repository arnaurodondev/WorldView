/**
 * components/alerts/__tests__/AlertWizard.test.tsx — type-first wizard flow
 * (PLAN-0113 W4 T-4-03).
 *
 * Covers:
 *   - Step 1 renders all 5 type cards.
 *   - Selecting a card advances to Step 2 and mounts THAT type's editor.
 *   - A complete condition enables Save → useCreateAlertRule is called with the
 *     full structured input.
 *   - Edit mode opens straight to Step 2 and saves via useUpdateAlertRule.
 *
 * The condition editors are stubbed so the test stays focused on the wizard's
 * step controller + save wiring (the editors have their own emit tests).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { RuleCondition } from "@/lib/api/alertRules";
import type { ConditionEditorProps } from "@/components/alerts/condition-editors/types";

// ── Mutation hook mocks ───────────────────────────────────────────────────────
const createMutate = vi.fn().mockResolvedValue({});
const updateMutate = vi.fn().mockResolvedValue({});

vi.mock("@/lib/api/useAlertRules", () => ({
  useCreateAlertRule: () => ({ mutateAsync: createMutate, isPending: false }),
  useUpdateAlertRule: () => ({ mutateAsync: updateMutate, isPending: false }),
}));

// ── Editor stubs ──────────────────────────────────────────────────────────────
// Each stub immediately renders a button that, when clicked, emits a complete
// condition. A data-testid identifies WHICH editor mounted (type-selection test).
function makeEditorStub(testid: string, condition: RuleCondition) {
  return function Stub({ value, names, onChange }: ConditionEditorProps) {
    return (
      <button
        type="button"
        data-testid={testid}
        // Surface the seeded value/names so the prefill test can assert them
        // (PLAN-0113 W5 — the wizard passes the entry-point prefill down here).
        data-seeded-value={value ? JSON.stringify(value) : ""}
        data-seeded-names={names ? JSON.stringify(names) : ""}
        onClick={() => onChange(condition as never)}
      >
        complete {testid}
      </button>
    );
  };
}

vi.mock("@/components/alerts/condition-editors/PriceCrossEditor", () => ({
  PriceCrossEditor: makeEditorStub("editor-price", {
    instrument_id: "i-aapl",
    operator: "above",
    value: 250,
  }),
}));
vi.mock("@/components/alerts/condition-editors/FundamentalCrossEditor", () => ({
  FundamentalCrossEditor: makeEditorStub("editor-fundamental", {
    instrument_id: "i-aapl",
    metric_key: "pe_ratio",
    operator: "below",
    value: 25,
  }),
}));
vi.mock("@/components/alerts/condition-editors/NewsVolumeEditor", () => ({
  NewsVolumeEditor: makeEditorStub("editor-news", {
    entity_id: "e-nvda",
    window: "24h",
    threshold: 5,
  }),
}));
vi.mock("@/components/alerts/condition-editors/NewsMomentumEditor", () => ({
  NewsMomentumEditor: makeEditorStub("editor-momentum", {
    entity_id: "e-tsla",
    window_hours: 24,
    delta_pct: 50,
    min_count: 2,
  }),
}));
vi.mock("@/components/alerts/condition-editors/KgConnectionEditor", () => ({
  KgConnectionEditor: makeEditorStub("editor-kg", {
    source_entity_id: "a",
    target_entity_id: "b",
    max_hops: 3,
  }),
}));

import { AlertWizard } from "@/components/alerts/AlertWizard";
import type { AlertRule } from "@/lib/api/alertRules";

describe("AlertWizard — type selection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders all 5 type cards on Step 1", () => {
    render(<AlertWizard open onOpenChange={vi.fn()} />);
    expect(screen.getByTestId("rule-type-card-PRICE_CROSS")).toBeInTheDocument();
    expect(screen.getByTestId("rule-type-card-NEWS_COUNT")).toBeInTheDocument();
    expect(screen.getByTestId("rule-type-card-NEWS_MOMENTUM")).toBeInTheDocument();
    expect(screen.getByTestId("rule-type-card-KG_CONNECTION")).toBeInTheDocument();
    expect(screen.getByTestId("rule-type-card-FUNDAMENTAL_CROSS")).toBeInTheDocument();
  });

  it("selecting the Price card mounts the price editor (Step 2)", () => {
    render(<AlertWizard open onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getByTestId("rule-type-card-PRICE_CROSS"));
    expect(screen.getByTestId("editor-price")).toBeInTheDocument();
  });

  it("selecting the KG card mounts the kg-connection editor", () => {
    render(<AlertWizard open onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getByTestId("rule-type-card-KG_CONNECTION"));
    expect(screen.getByTestId("editor-kg")).toBeInTheDocument();
  });
});

describe("AlertWizard — entry-point prefill (PLAN-0113 W5)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("seeds the editor with a partial prefillCondition + names (create mode)", () => {
    render(
      <AlertWizard
        open
        onOpenChange={vi.fn()}
        initialRuleType="PRICE_CROSS"
        prefillCondition={{ instrument_id: "ins-001" }}
        prefillNames={{ "ins-001": "AAPL" }}
      />,
    );
    // Skips Step 1 (no type cards) and mounts the price editor straight away.
    expect(screen.queryByTestId("rule-type-card-PRICE_CROSS")).not.toBeInTheDocument();
    const editor = screen.getByTestId("editor-price");
    expect(JSON.parse(editor.getAttribute("data-seeded-value") || "{}")).toEqual({
      instrument_id: "ins-001",
    });
    expect(JSON.parse(editor.getAttribute("data-seeded-names") || "{}")).toEqual({
      "ins-001": "AAPL",
    });
  });

  it("keeps Save disabled until the partially-seeded editor reports complete", () => {
    render(
      <AlertWizard
        open
        onOpenChange={vi.fn()}
        initialRuleType="KG_CONNECTION"
        prefillCondition={{ source_entity_id: "a", target_entity_id: "b", max_hops: 3 }}
        prefillNames={{ a: "Apple", b: "Anthropic" }}
      />,
    );
    expect(screen.getByRole("button", { name: /Create rule/i })).toBeDisabled();
    const editor = screen.getByTestId("editor-kg");
    expect(JSON.parse(editor.getAttribute("data-seeded-value") || "{}")).toMatchObject({
      source_entity_id: "a",
      target_entity_id: "b",
    });
  });
});

describe("AlertWizard — save", () => {
  beforeEach(() => vi.clearAllMocks());

  it("Save is disabled until the editor reports a complete condition", () => {
    render(<AlertWizard open onOpenChange={vi.fn()} initialRuleType="PRICE_CROSS" />);
    const save = screen.getByRole("button", { name: /Create rule/i });
    expect(save).toBeDisabled();
  });

  it("creates a rule with the structured condition on Save", async () => {
    const onOpenChange = vi.fn();
    render(
      <AlertWizard open onOpenChange={onOpenChange} initialRuleType="PRICE_CROSS" />,
    );
    // Complete the (stubbed) editor → condition reported.
    fireEvent.click(screen.getByTestId("editor-price"));
    fireEvent.click(screen.getByRole("button", { name: /Create rule/i }));

    await waitFor(() => {
      expect(createMutate).toHaveBeenCalledTimes(1);
    });
    const input = createMutate.mock.calls[0][0];
    expect(input.rule_type).toBe("PRICE_CROSS");
    expect(input.condition).toEqual({ instrument_id: "i-aapl", operator: "above", value: 250 });
    expect(input.severity).toBe("medium");
  });

  it("edit mode opens to Step 2 and PATCHes via useUpdateAlertRule", async () => {
    const editRule: AlertRule = {
      rule_id: "r-1",
      tenant_id: "t1",
      user_id: "u1",
      rule_type: "PRICE_CROSS",
      name: "AAPL price",
      entity_id: "i-aapl",
      node_a_entity_id: null,
      node_b_entity_id: null,
      condition: { instrument_id: "i-aapl", operator: "above", value: 250 },
      severity: "high",
      enabled: true,
      cooldown_seconds: 3600,
      notify_in_app: true,
      notify_email: false,
      last_state: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    render(<AlertWizard open onOpenChange={vi.fn()} editRule={editRule} />);

    // Straight to Step 2 (editor visible, no type cards).
    expect(screen.queryByTestId("rule-type-card-PRICE_CROSS")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("editor-price"));
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() => {
      expect(updateMutate).toHaveBeenCalledTimes(1);
    });
    expect(updateMutate.mock.calls[0][0].ruleId).toBe("r-1");
  });
});
