import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { FlashOverlay } from "../src/components/alerts/FlashOverlay";
import type { AlertPayload } from "../src/hooks/useAlertStream";

const makeAlert = (overrides: Partial<AlertPayload> = {}): AlertPayload => ({
  alert_id: "test-alert-1",
  entity_id: "entity-abc-123",
  alert_type: "price_surge",
  topic: "nlp.signal.detected.v1",
  occurred_at: "2026-04-10T10:00:00Z",
  severity: "critical",
  ...overrides,
});

describe("FlashOverlay", () => {
  let onDismiss: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onDismiss = vi.fn();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders_for_critical_alert", () => {
    render(<FlashOverlay alert={makeAlert()} onDismiss={onDismiss} />);

    expect(screen.getByText("⚡ CRITICAL ALERT")).toBeInTheDocument();
    expect(screen.getByText("price_surge")).toBeInTheDocument();
    expect(screen.getByText("entity-abc-123")).toBeInTheDocument();
    // SeverityBadge for "critical" renders "CRITICAL"
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
  });

  it("auto_dismisses_after_12s", () => {
    render(<FlashOverlay alert={makeAlert()} onDismiss={onDismiss} />);
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(12_000);
    });

    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("dismisses_on_escape_key", () => {
    render(<FlashOverlay alert={makeAlert()} onDismiss={onDismiss} />);

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("dismisses_on_background_click", () => {
    render(<FlashOverlay alert={makeAlert()} onDismiss={onDismiss} />);

    fireEvent.click(screen.getByTestId("flash-overlay"));

    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("does_not_dismiss_on_card_click", () => {
    render(<FlashOverlay alert={makeAlert()} onDismiss={onDismiss} />);

    // Click inside the card — stopPropagation prevents overlay onClick
    fireEvent.click(screen.getByTestId("flash-card"));

    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("shows_alert_type_and_entity_id", () => {
    render(
      <FlashOverlay
        alert={makeAlert({ alert_type: "market_crash", entity_id: "aapl-uuid-456" })}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.getByText("market_crash")).toBeInTheDocument();
    expect(screen.getByText("aapl-uuid-456")).toBeInTheDocument();
  });
});
