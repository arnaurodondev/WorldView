import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import {
  AlertStreamContext,
  useAlertStreamContext,
} from "../src/contexts/AlertStreamContext";
import type { AlertPayload } from "../src/hooks/useAlertStream";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Renders a component that exposes context values via data-testid attributes. */
function ContextReader() {
  const { criticalQueue, recentAlerts, dequeueCritical } =
    useAlertStreamContext();

  return (
    <div>
      <span data-testid="critical-len">{criticalQueue.length}</span>
      <span data-testid="recent-len">{recentAlerts.length}</span>
      <button data-testid="dequeue-btn" onClick={dequeueCritical}>
        dequeue
      </button>
    </div>
  );
}

const sampleAlert: AlertPayload = {
  alert_id: "a1",
  entity_id: "entity-xyz",
  alert_type: "price_surge",
  topic: "market",
  occurred_at: "2026-04-10T10:00:00Z",
  severity: "critical",
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("useAlertStreamContext", () => {
  it("returns_default_empty_arrays_outside_provider", () => {
    render(<ContextReader />);

    expect(screen.getByTestId("critical-len").textContent).toBe("0");
    expect(screen.getByTestId("recent-len").textContent).toBe("0");
  });

  it("noop_dequeueCritical_outside_provider_does_not_throw", () => {
    render(<ContextReader />);

    // Clicking dequeue when using the default noop should not throw
    expect(() => {
      fireEvent.click(screen.getByTestId("dequeue-btn"));
    }).not.toThrow();

    expect(screen.getByTestId("critical-len").textContent).toBe("0");
  });

  it("returns_values_from_wrapping_provider", () => {
    const value = {
      criticalQueue: [sampleAlert],
      recentAlerts: [],
      dequeueCritical: () => {},
    };

    render(
      <AlertStreamContext.Provider value={value}>
        <ContextReader />
      </AlertStreamContext.Provider>,
    );

    expect(screen.getByTestId("critical-len").textContent).toBe("1");
    expect(screen.getByTestId("recent-len").textContent).toBe("0");
  });

  it("custom_dequeueCritical_from_provider_is_callable", () => {
    const dequeueCritical = vi.fn();

    const value = {
      criticalQueue: [sampleAlert],
      recentAlerts: [],
      dequeueCritical,
    };

    render(
      <AlertStreamContext.Provider value={value}>
        <ContextReader />
      </AlertStreamContext.Provider>,
    );

    fireEvent.click(screen.getByTestId("dequeue-btn"));
    expect(dequeueCritical).toHaveBeenCalledOnce();
  });
});
