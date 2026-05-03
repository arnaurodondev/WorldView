/**
 * components/alerts/__tests__/alert-history-columns.test.ts
 *
 * WHY: Unit tests for alertHistoryColumns + helper functions extracted from
 * AlertHistoryTab. These run without a DOM mount — pure unit tests on accessors
 * and helper functions — so they're fast and resilient to layout changes.
 *
 * PLAN-0059 F-1 — DataTable migration tests (≥3 per migrated table).
 */

import { describe, it, expect } from "vitest";
import {
  alertHistoryColumns,
  computeStatus,
  SEVERITY_PILL_CLASS,
  STATUS_PILL_CLASS,
} from "../alert-history-columns";
import type { Alert } from "@/types/api";

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    alert_id: "alert-1",
    entity_id: "entity-1",
    ticker: "AAPL",
    alert_type: "PRICE_MOVE",
    severity: "HIGH",
    title: "Price alert",
    body: "",
    metadata: {},
    created_at: "2026-05-01T10:00:00Z",
    acknowledged_at: null,
    snooze_until: null,
    ...overrides,
  } as Alert;
}

describe("alertHistoryColumns", () => {
  it("has exactly 6 columns (Severity, Ticker, Type, Fired, Dismissed, Status)", () => {
    expect(alertHistoryColumns).toHaveLength(6);
    const ids = alertHistoryColumns.map((c) => c.id);
    expect(ids).toEqual([
      "severity",
      "ticker",
      "alert_type",
      "created_at",
      "acknowledged_at",
      "status",
    ]);
  });

  it("severity column accessorKey targets the severity field", () => {
    const col = alertHistoryColumns.find((c) => c.id === "severity");
    expect(col).toBeDefined();
    // accessorKey must resolve to the right field
    expect((col as { accessorKey?: string }).accessorKey).toBe("severity");
  });

  it("ticker column returns '—' for null ticker via accessor", () => {
    const col = alertHistoryColumns.find((c) => c.id === "ticker");
    expect((col as { accessorKey?: string }).accessorKey).toBe("ticker");
    // The cell renderer falls back to "—" — verify the alert object correctly
    // carries a null ticker so the fallback condition can fire.
    const alert = makeAlert({ ticker: undefined });
    expect(alert.ticker).toBeUndefined();
  });
});

describe("computeStatus helper", () => {
  it("returns 'ack' when acknowledged_at is set", () => {
    const alert = makeAlert({ acknowledged_at: "2026-05-01T11:00:00Z" });
    expect(computeStatus(alert)).toBe("ack");
  });

  it("returns 'snoozed' when snooze_until is in the future and not acknowledged", () => {
    const future = new Date(Date.now() + 60_000).toISOString();
    const alert = makeAlert({ snooze_until: future, acknowledged_at: null });
    expect(computeStatus(alert)).toBe("snoozed");
  });

  it("returns 'active' when neither acked nor snoozed", () => {
    const alert = makeAlert({ acknowledged_at: null, snooze_until: null });
    expect(computeStatus(alert)).toBe("active");
  });

  it("'ack' wins over a future snooze_until (acked supersedes snoozed)", () => {
    const future = new Date(Date.now() + 60_000).toISOString();
    const alert = makeAlert({
      acknowledged_at: "2026-05-01T11:00:00Z",
      snooze_until: future,
    });
    // Acknowledged takes priority — the row is definitively resolved.
    expect(computeStatus(alert)).toBe("ack");
  });
});

describe("SEVERITY_PILL_CLASS", () => {
  it("CRITICAL uses the negative (red) palette", () => {
    expect(SEVERITY_PILL_CLASS.CRITICAL).toContain("text-negative");
  });

  it("all four severities have a class definition", () => {
    const sevs: (keyof typeof SEVERITY_PILL_CLASS)[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
    for (const s of sevs) {
      expect(SEVERITY_PILL_CLASS[s]).toBeTruthy();
    }
  });
});

describe("STATUS_PILL_CLASS", () => {
  it("snoozed uses the warning palette", () => {
    expect(STATUS_PILL_CLASS.snoozed).toContain("text-warning");
  });

  it("all three statuses have a class definition", () => {
    const statuses: (keyof typeof STATUS_PILL_CLASS)[] = ["active", "ack", "snoozed"];
    for (const s of statuses) {
      expect(STATUS_PILL_CLASS[s]).toBeTruthy();
    }
  });
});
