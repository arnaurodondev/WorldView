/**
 * __tests__/brokerage-connect-copy.test.tsx — PLAN-0122 W-C §6.2 trust + timing copy.
 *
 * WHY THIS EXISTS: two pure copy changes remove the #1 brokerage-linking trust
 * barrier (R-8) and set honest sync expectations (R-9/R-10):
 *   1. ConnectBrokerageModal gains a credentials-safety reassurance block.
 *   2. The OAuth callback success view replaces the misleading "syncing shortly"
 *      sub-copy with explicit timing (minutes → a few hours + "Sync Now"), while
 *      KEEPING the e2e-pinned success heading.
 *
 * DATA SOURCE: fully mocked — no network, no real router/query client.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Modal deps ────────────────────────────────────────────────────────────────
// The modal calls useInitiateBrokerageConnection() for the Connect mutation. We
// stub it so the modal renders without a real gateway/query client.
const { mockInitiate, mockReset } = vi.hoisted(() => ({
  mockInitiate: vi.fn(),
  mockReset: vi.fn(),
}));
vi.mock("@/hooks/use-brokerage-connections", () => ({
  useInitiateBrokerageConnection: () => ({
    mutate: mockInitiate,
    isPending: false,
    error: null,
    reset: mockReset,
  }),
}));

import { ConnectBrokerageModal } from "@/components/brokerage/ConnectBrokerageModal";

describe("ConnectBrokerageModal — credentials trust block (PLAN-0122 R-8)", () => {
  beforeEach(() => {
    mockInitiate.mockReset();
    mockReset.mockReset();
  });

  function renderModal() {
    render(
      <ConnectBrokerageModal
        portfolioId="port-1"
        portfolioName="My Portfolio"
        open={true}
        onOpenChange={vi.fn()}
      />,
    );
  }

  it("renders the credentials-stay-with-SnapTrade reassurance block", () => {
    renderModal();
    const block = screen.getByTestId("brokerage-trust-block");
    expect(block).toBeInTheDocument();
    // The core reassurance: credentials never reach Worldview + read-only.
    expect(block).toHaveTextContent(/credentials stay with SnapTrade — never Worldview/i);
    expect(block).toHaveTextContent(/read-only/i);
    expect(block).toHaveTextContent(/never place trades or move money/i);
  });

  it("still gates Connect on the ToS consent checkbox (unchanged behaviour)", async () => {
    const user = userEvent.setup();
    renderModal();

    // The trust block is informational — it does NOT replace consent. Connect
    // stays disabled until the ToS checkbox is ticked.
    const connectBtn = screen.getByRole("button", { name: /^connect$/i });
    expect(connectBtn).toBeDisabled();

    await user.click(screen.getByRole("checkbox"));
    expect(connectBtn).not.toBeDisabled();
  });
});

// ── Callback timing copy ───────────────────────────────────────────────────────
//
// The callback page drives an activation state machine. We mock its navigation,
// auth, and gateway deps so it reaches the "success" branch, then assert the
// honest timing sub-copy AND the still-pinned success heading.

const { mockActivate, mockPush } = vi.hoisted(() => ({
  mockActivate: vi.fn(),
  mockPush: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  // connectionId + authorizationId present → the effect proceeds to activation.
  useSearchParams: () => new URLSearchParams("connectionId=conn-1&authorizationId=auth-1"),
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({ activateBrokerageConnection: mockActivate }),
}));

import BrokerageCallbackPage from "@/app/(app)/portfolio/brokerage/callback/page";

function qcWrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("BrokerageCallbackPage — honest sync-timing copy (PLAN-0122 R-9/R-10)", () => {
  beforeEach(() => {
    mockActivate.mockReset();
    mockPush.mockReset();
  });

  it("shows the honest timing copy and keeps the pinned success heading", async () => {
    // Activation resolves → the success branch renders.
    mockActivate.mockResolvedValue({});
    render(<BrokerageCallbackPage />, { wrapper: qcWrapper });

    // Heading is intentionally UNCHANGED (e2e/qa pin it).
    await waitFor(() => {
      expect(
        screen.getByText("Brokerage account connected successfully!"),
      ).toBeInTheDocument();
    });

    // Sub-copy is the new explicit-timing string.
    expect(screen.getByText(/few minutes/i)).toBeInTheDocument();
    expect(screen.getByText(/few hours/i)).toBeInTheDocument();
    expect(screen.getByText(/Sync Now/i)).toBeInTheDocument();

    // The misleading legacy phrasing is gone.
    expect(screen.queryByText(/begin syncing shortly/i)).not.toBeInTheDocument();
  });
});
