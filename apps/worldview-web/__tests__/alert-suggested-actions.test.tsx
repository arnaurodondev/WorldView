/**
 * __tests__/alert-suggested-actions.test.tsx — PLAN-0051 T-D-4-05.
 *
 * Covers the SuggestedActions strip rendered inside AlertDetailSheet.
 * Each test renders the sheet with a fixture alert and verifies:
 *   - Buttons are present.
 *   - "View instrument" navigates to /instruments/{entity_id}.
 *   - "View instrument" is disabled when the alert lacks a ticker.
 *   - "Open in chat" navigates to /chat with entity_id + starter.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AlertDetailSheet } from "@/components/alerts/AlertDetailSheet";
import type { Alert } from "@/types/api";

// ── Router mock — capture push() calls ─────────────────────────────────────
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: pushMock, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  usePathname: vi.fn(() => "/alerts"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "T", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// Gateway stub — needed because AddToWatchlistDialog (rendered by the action
// strip) calls getWatchlists when opened. We don't open that dialog in these
// tests, but the import wiring still needs to resolve.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getWatchlists: vi.fn().mockResolvedValue([]),
    addWatchlistMember: vi.fn().mockResolvedValue({}),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}
function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={makeQueryClient()}>{children}</QueryClientProvider>;
}

const ALERT_WITH_INSTRUMENT: Alert = {
  alert_id: "alert-001",
  entity_id: "entity-aapl",
  ticker: "AAPL",
  alert_type: "PRICE_MOVE",
  severity: "HIGH",
  title: "AAPL +5%",
  body: "Apple +5%",
  metadata: {},
  created_at: new Date().toISOString(),
  acknowledged_at: null,
};

const ALERT_NO_TICKER: Alert = {
  ...ALERT_WITH_INSTRUMENT,
  alert_id: "alert-macro",
  ticker: null,
  payload: {},
};

const ALERT_NO_ENTITY: Alert = {
  ...ALERT_WITH_INSTRUMENT,
  alert_id: "alert-orphan",
  entity_id: "",
  ticker: null,
  payload: {},
};

beforeEach(() => {
  pushMock.mockClear();
});

describe("AlertDetailSheet — Suggested Actions", () => {
  it("renders all four action buttons when the alert has full context", () => {
    render(
      <AlertDetailSheet
        alert={ALERT_WITH_INSTRUMENT}
        open={true}
        onClose={() => {}}
        onAck={() => {}}
        onSnooze={() => {}}
      />,
      { wrapper },
    );
    expect(screen.getByRole("button", { name: /View instrument/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Add to watchlist/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Set alert rule/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open in chat/i })).toBeEnabled();
  });

  it("View instrument navigates to /instruments/{entity_id}", async () => {
    const user = userEvent.setup();
    render(
      <AlertDetailSheet
        alert={ALERT_WITH_INSTRUMENT}
        open={true}
        onClose={() => {}}
        onAck={() => {}}
        onSnooze={() => {}}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("button", { name: /View instrument/i }));
    expect(pushMock).toHaveBeenCalledWith("/instruments/entity-aapl");
  });

  it("Open in chat navigates to /chat with entity_id + starter params", async () => {
    const user = userEvent.setup();
    render(
      <AlertDetailSheet
        alert={ALERT_WITH_INSTRUMENT}
        open={true}
        onClose={() => {}}
        onAck={() => {}}
        onSnooze={() => {}}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("button", { name: /Open in chat/i }));
    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    const target = pushMock.mock.calls.at(-1)?.[0] as string;
    expect(target).toContain("/chat");
    expect(target).toContain("entity_id=entity-aapl");
    expect(target).toContain("starter=alert_alert-001");
  });

  it("disables View instrument when the alert has no ticker", () => {
    render(
      <AlertDetailSheet
        alert={ALERT_NO_TICKER}
        open={true}
        onClose={() => {}}
        onAck={() => {}}
        onSnooze={() => {}}
      />,
      { wrapper },
    );
    const view = screen.getByRole("button", { name: /View instrument/i });
    expect(view).toBeDisabled();
  });

  it("disables Add to watchlist + Open in chat when no entity_id", () => {
    render(
      <AlertDetailSheet
        alert={ALERT_NO_ENTITY}
        open={true}
        onClose={() => {}}
        onAck={() => {}}
        onSnooze={() => {}}
      />,
      { wrapper },
    );
    expect(screen.getByRole("button", { name: /Add to watchlist/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Open in chat/i })).toBeDisabled();
  });
});
