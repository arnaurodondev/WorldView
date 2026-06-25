/**
 * Tests for components/alerts/alert-row-content.ts — the pure helpers that turn
 * an Alert into the distinct, scannable row columns (roadmap item #2 / A-1 / B2).
 *
 * The point of these helpers is that rows stop being identical: each surfaces a
 * differentiated "what changed" summary, a humanised type, and the subject —
 * composed from whatever fields ARE populated, never inventing data and never
 * emitting a bare "<SEVERITY> signal" string.
 */
import { describe, expect, it } from "vitest";
import { alertSubject, alertSummary, humaniseAlertType } from "../alert-row-content";
import type { Alert } from "@/types/api";

/** Build a minimal Alert with sane defaults; override only the fields under test. */
function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    alert_id: "a-1",
    entity_id: "e-1",
    ticker: null,
    alert_type: "graph_change",
    severity: "MEDIUM",
    title: null,
    body: "",
    entity_name: null,
    signal_label: null,
    payload: {},
    metadata: {},
    created_at: new Date().toISOString(),
    acknowledged_at: null,
    ...overrides,
  };
}

describe("humaniseAlertType", () => {
  it("upper-cases and spaces a screaming-snake token", () => {
    expect(humaniseAlertType("graph_change")).toBe("GRAPH CHANGE");
    expect(humaniseAlertType("PRICE_MOVE")).toBe("PRICE MOVE");
  });

  it("returns empty string for null/undefined/empty", () => {
    expect(humaniseAlertType(null)).toBe("");
    expect(humaniseAlertType(undefined)).toBe("");
    expect(humaniseAlertType("")).toBe("");
  });
});

describe("alertSubject", () => {
  it("prefers the top-level ticker", () => {
    expect(alertSubject(makeAlert({ ticker: "AAPL", entity_name: "Apple Inc." }))).toBe("AAPL");
  });

  it("falls back to entity_name when no ticker", () => {
    expect(alertSubject(makeAlert({ ticker: null, entity_name: "Apple Inc." }))).toBe("Apple Inc.");
  });

  it("reads ticker/entity_name from the free-form payload for legacy alerts", () => {
    expect(alertSubject(makeAlert({ payload: { ticker: "TSLA" } }))).toBe("TSLA");
    expect(alertSubject(makeAlert({ payload: { entity_name: "Nvidia" } }))).toBe("Nvidia");
  });

  it("returns null when no subject is known (caller renders the — sentinel)", () => {
    expect(alertSubject(makeAlert())).toBeNull();
  });
});

describe("alertSummary", () => {
  it("prefers an explicit body when populated", () => {
    const a = makeAlert({ body: "Tesla critical news signal detected — review immediately" });
    expect(alertSummary(a)).toBe("Tesla critical news signal detected — review immediately");
  });

  it("composes from title/signal_label when body is empty (sidebar parity)", () => {
    const a = makeAlert({ body: "", title: null, ticker: "AAPL", signal_label: "Bullish guidance" });
    // The shared composer yields "AAPL: Bullish guidance"; since the subject is
    // already shown in its own column, the summary strips the redundant prefix.
    expect(alertSummary(a)).toBe("Bullish guidance");
  });

  it("keeps the composed title intact when it carries no subject prefix", () => {
    const a = makeAlert({ body: "", title: "5 new edges to NVDA, AMD" });
    expect(alertSummary(a)).toBe("5 new edges to NVDA, AMD");
  });

  it("NEVER returns a bare '<SEVERITY> signal/alert' string for a naked alert", () => {
    // Worst case: no body, title, signal_label, ticker or entity_name.
    const a = makeAlert({
      body: "",
      title: null,
      ticker: null,
      entity_name: null,
      signal_label: null,
      alert_type: "graph_change",
      severity: "LOW",
    });
    const summary = alertSummary(a);
    expect(summary).not.toMatch(/^(LOW|MEDIUM|HIGH|CRITICAL)\s+(signal|alert)$/i);
    // Humanised alert_type fallback kicks in instead.
    expect(summary).toBe("Graph Change alert");
  });
});
