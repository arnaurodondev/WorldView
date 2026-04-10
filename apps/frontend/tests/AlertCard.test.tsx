import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AlertCard } from "../src/components/alerts/AlertCard";
import type { AlertPayload } from "../src/hooks/useAlertStream";

function makeAlert(overrides: Partial<AlertPayload> = {}): AlertPayload {
  return {
    alert_id: "alert-001",
    entity_id: "entity-abcdefghij",
    alert_type: "price_surge",
    topic: "market",
    occurred_at: "2026-04-10T14:35:00Z",
    severity: "high",
    ...overrides,
  };
}

describe("AlertCard", () => {
  it("renders_SeverityBadge_with_correct_severity", () => {
    render(<AlertCard alert={makeAlert({ severity: "critical" })} />);
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
  });

  it("shows_alert_type_text", () => {
    render(<AlertCard alert={makeAlert({ alert_type: "earnings_beat" })} />);
    expect(screen.getByText("earnings_beat")).toBeInTheDocument();
  });

  it("truncates_entity_id_to_8_chars_with_ellipsis", () => {
    render(<AlertCard alert={makeAlert({ entity_id: "entity-abcdefghij" })} />);
    // entity_id.slice(0,8) = "entity-a"
    expect(screen.getByText("entity-a\u2026")).toBeInTheDocument();
  });

  it("shows_full_entity_id_in_title_attribute", () => {
    const entityId = "entity-abcdefghij";
    render(<AlertCard alert={makeAlert({ entity_id: entityId })} />);
    expect(screen.getByTitle(entityId)).toBeInTheDocument();
  });

  it("formats_time_from_iso_string", () => {
    // occurred_at "2026-04-10T14:35:00Z" — toLocaleTimeString produces "HH:MM" variants
    render(<AlertCard alert={makeAlert({ occurred_at: "2026-04-10T14:35:00Z" })} />);
    // The formatted time must contain "35" (the minutes portion is stable across locales)
    const timeEl = screen.getByText(/35/);
    expect(timeEl).toBeInTheDocument();
  });
});
