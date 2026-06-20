/**
 * components/instrument/header/__tests__/InstrumentAlertButton.test.tsx
 * (PLAN-0113 Wave 5, T-5-01).
 *
 * Pins the instrument-page "＋ Alert" entry-point contract:
 *   1. Disabled while no instrument_id is resolved (can't scope a rule).
 *   2. Clicking it opens the AlertWizard pre-scoped to PRICE_CROSS with the
 *      instrument_id seeded and the ticker passed as the display name.
 *
 * STRATEGY: AlertWizard is mocked to a prop-capturing stub so the test focuses on
 * the wiring (open state + prefill), not the wizard internals (which have their
 * own tests + need the gateway/auth providers).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const wizardSpy = vi.fn();
vi.mock("@/components/alerts/AlertWizard", () => ({
  AlertWizard: (props: Record<string, unknown>) => {
    wizardSpy(props);
    return <div data-testid="alert-wizard" data-open={String(props.open)} />;
  },
}));

import { InstrumentAlertButton } from "@/components/instrument/header/InstrumentAlertButton";

describe("InstrumentAlertButton", () => {
  beforeEach(() => wizardSpy.mockReset());

  it("is disabled until an instrument_id resolves", () => {
    render(<InstrumentAlertButton instrumentId={null} ticker="AAPL" name="Apple Inc." />);
    expect(screen.getByTestId("instrument-alert-button")).toBeDisabled();
    // No wizard mounts without an id (nothing to scope).
    expect(screen.queryByTestId("alert-wizard")).toBeNull();
  });

  it("opens the wizard pre-scoped to PRICE_CROSS with the instrument seeded", () => {
    render(
      <InstrumentAlertButton instrumentId="ins-001" ticker="AAPL" name="Apple Inc." />,
    );

    // Wizard mounts (closed) as soon as the id is known.
    expect(screen.getByTestId("alert-wizard")).toHaveAttribute("data-open", "false");

    fireEvent.click(screen.getByTestId("instrument-alert-button"));

    const lastCall = wizardSpy.mock.calls.at(-1)?.[0];
    expect(lastCall?.open).toBe(true);
    expect(lastCall?.initialRuleType).toBe("PRICE_CROSS");
    expect(lastCall?.prefillCondition).toEqual({ instrument_id: "ins-001" });
    // Ticker preferred as the display label for the seeded chip + NL summary.
    expect(lastCall?.prefillNames).toEqual({ "ins-001": "AAPL" });
  });

  it("falls back to the company name when no ticker is available", () => {
    render(<InstrumentAlertButton instrumentId="ins-002" ticker={null} name="Beta Corp" />);
    fireEvent.click(screen.getByTestId("instrument-alert-button"));
    const lastCall = wizardSpy.mock.calls.at(-1)?.[0];
    expect(lastCall?.prefillNames).toEqual({ "ins-002": "Beta Corp" });
  });
});
