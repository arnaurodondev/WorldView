/**
 * __tests__/recent-alerts.test.tsx — PLAN-0049 T-D-4-05 regression coverage.
 *
 * WHY THIS EXISTS: RecentAlerts is the dashboard's primary alert surface.
 * PLAN-0049 introduced (a) an alert title fallback ladder and (b) deep-link
 * navigation via ``?selected={id}``. Both have failed silently in the past
 * (F-D-006, F-X-201, F-303). Pin them here so any drift trips the test suite.
 *
 * SCOPE OF THIS FILE (vs alerts-no-bare-severity.test.tsx):
 *   That file only asserts the "no bare severity" negative regex. THIS file
 *   exercises the FULL fallback chain (title → signal_label → entity_name →
 *   "{Type} alert") AND the deep-link href contract — broader coverage.
 *
 * WHY MOCK GATEWAY + AlertStreamContext: RecentAlerts merges live WS alerts
 * (from context) and historical REST alerts (from gateway). Mocking both keeps
 * the test deterministic without spinning up S10 or running real fetch.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Alert } from "@/types/api";

// ── AlertStreamContext mock — empty live stream so REST is the sole source ───
vi.mock("@/contexts/AlertStreamContext", () => ({
  useAlertStream: vi.fn(() => ({
    recentAlerts: [],
    unreadCount: 0,
    connectionStatus: "disconnected" as const,
    markAllRead: vi.fn(),
  })),
  AlertStreamProvider: ({ children }: { children: ReactNode }) => children,
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock — drive REST alert payload per test ─────────────────────────
// WHY getAlertHistory (not getPendingAlerts): the component was refactored in
// PLAN-0049 F-5 to read from the `alerts` table directly via getAlertHistory —
// the authoritative store. getPendingAlerts reads the delivery queue which is
// empty for seeded/acknowledged alerts. Tests must mirror what the component calls.
const mockGetAlertHistory = vi.fn();
vi.mock("@/lib/gateway", () => ({
  // RecentAlerts calls getPendingAlerts; alias to the same mock so existing
  // mockResolvedValueOnce setups continue to drive the test.
  createGateway: vi.fn(() => ({
    getAlertHistory: mockGetAlertHistory,
    getPendingAlerts: mockGetAlertHistory,
  })),
}));

import { RecentAlerts } from "@/components/dashboard/RecentAlerts";

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Fixture builder — typed Alert (no `any` per CLAUDE.md frontend rules) ────
function makeAlert(overrides: Partial<Alert>): Alert {
  return {
    alert_id: "a-1",
    entity_id: "e-1",
    ticker: null,
    alert_type: "graph_change",
    severity: "LOW",
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

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("RecentAlerts — PLAN-0049 T-D-4-04 fallback ladder + deep-links", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("title fallback chain — title → signal_label → entity_name → '{Type} alert'", async () => {
    // Four alerts, one per fallback rung. Each has only the field it needs to
    // exercise its rung. The test asserts the rendered title at every level.
    const alerts: Alert[] = [
      // Level 1: backend-composed title wins.
      makeAlert({
        alert_id: "00000000-0000-0000-0000-000000000001",
        title: "Apple Inc.: Q1 beat",
        signal_label: "Bullish guidance",
        entity_name: "Apple Inc.",
        ticker: "AAPL",
        created_at: "2026-04-29T09:00:00Z",
      }),
      // Level 2: signal_label only — formatter returns the bare label
      // (no subject available since title/ticker/entity_name are nulled here).
      makeAlert({
        alert_id: "00000000-0000-0000-0000-000000000002",
        title: null,
        signal_label: "Volatility spike",
        entity_name: null,
        ticker: null,
        created_at: "2026-04-29T08:50:00Z",
      }),
      // Level 3: entity_name only — formatter returns the subject as the title.
      makeAlert({
        alert_id: "00000000-0000-0000-0000-000000000003",
        title: null,
        signal_label: null,
        entity_name: "Microsoft Corp.",
        ticker: null,
        created_at: "2026-04-29T08:40:00Z",
      }),
      // Level 4: nothing populated — humanise alert_type ("Graph Change alert").
      makeAlert({
        alert_id: "00000000-0000-0000-0000-000000000004",
        alert_type: "graph_change",
        title: null,
        signal_label: null,
        entity_name: null,
        ticker: null,
        created_at: "2026-04-29T08:30:00Z",
      }),
    ];
    mockGetAlertHistory.mockResolvedValueOnce({
      alerts,
      total: alerts.length,
      offset: 0,
      limit: 8,
    });

    render(wrap(<RecentAlerts />));

    // Each rung's expected text — order in the rendered list is "newest first"
    // by created_at, but we only assert presence (not order).
    await waitFor(() => {
      expect(screen.getByText("Apple Inc.: Q1 beat")).toBeInTheDocument();
    });
    expect(screen.getByText("Volatility spike")).toBeInTheDocument();
    expect(screen.getByText("Microsoft Corp.")).toBeInTheDocument();
    // Humanised alert_type — formatter outputs "<Title Case Type> alert".
    expect(screen.getByText("Graph Change alert")).toBeInTheDocument();
  });

  it("never renders bare-severity strings even with a worst-case alert", async () => {
    // F-D-006 / F-X-201 regression — the fallback chain must NEVER produce
    // "LOW signal" / "MEDIUM alert". This test repeats the contract from
    // alerts-no-bare-severity.test.tsx but drives it through the merged path
    // (live + REST) to catch regressions in the merge logic too.
    mockGetAlertHistory.mockResolvedValueOnce({
      alerts: [
        makeAlert({
          alert_id: "00000000-0000-0000-0000-00000000000a",
          alert_type: "signal", // generic, no enrichment fields
          title: null,
          signal_label: null,
          entity_name: null,
          ticker: null,
        }),
      ],
      total: 1,
      offset: 0,
      limit: 8,
    });

    render(wrap(<RecentAlerts />));

    await waitFor(() => {
      const text = document.body.textContent ?? "";
      // F-QAC-10 fix: dropped the dead ``^...$`` regex that never matched
      // (textContent is a flat concatenated string with no ``\n``, so the
      // ``m`` flag had nothing to anchor against). The substring checks
      // below are the actual contract — any of these four strings
      // appearing anywhere in the rendered tree is the F-D-006 bug.
      expect(text).not.toContain("LOW signal");
      expect(text).not.toContain("MEDIUM signal");
      expect(text).not.toContain("HIGH signal");
      expect(text).not.toContain("CRITICAL signal");
      // Same for "alert" suffix variants the bug also produced.
      expect(text).not.toContain("LOW alert");
      expect(text).not.toContain("MEDIUM alert");
      expect(text).not.toContain("HIGH alert");
      expect(text).not.toContain("CRITICAL alert");
    });
  });

  it("each alert row deep-links to /alerts?selected={id}", async () => {
    // F-303 deep-link parity — clicking an alert row must open the AlertDetail
    // sheet via the ``?selected={id}`` query param. A regression here would
    // drop users on the bare /alerts list, forcing a second click.
    const alert = makeAlert({
      alert_id: "deadbeef-1234-5678-9abc-def012345678",
      title: "Apple: Bullish guidance",
      ticker: "AAPL",
      severity: "HIGH",
    });
    mockGetAlertHistory.mockResolvedValueOnce({
      alerts: [alert],
      total: 1,
      offset: 0,
      limit: 8,
    });

    render(wrap(<RecentAlerts />));

    // Find the row by its title text → climb to the wrapping <a>.
    const titleEl = await screen.findByText("Apple: Bullish guidance");
    const anchor = titleEl.closest("a");
    expect(anchor).not.toBeNull();
    // Next.js Link renders as <a href="..."> in jsdom — assert the href.
    expect(anchor!.getAttribute("href")).toBe(
      `/alerts?selected=${encodeURIComponent(alert.alert_id)}`,
    );
  });
});
