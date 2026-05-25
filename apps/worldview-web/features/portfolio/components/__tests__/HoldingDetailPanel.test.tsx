/**
 * features/portfolio/components/__tests__/HoldingDetailPanel.test.tsx
 *
 * WHY THIS EXISTS: HoldingDetailPanel is the core slide-over component for
 * PRD-0089 SA-B. Tests pin:
 *  1. The panel renders nothing visible (translate-x-full) when holding=null.
 *  2. The panel header shows the ticker when a holding is provided.
 *  3. Pressing Escape calls the onClose callback.
 *
 * MOCKED MODULES:
 *  - @/hooks/useAuth      → stub token so auth gates pass.
 *  - @/lib/gateway        → stub all API calls to avoid real fetch in tests.
 *  - next/navigation      → stub useRouter so router.push doesn't error.
 *  - nuqs                 → not needed here (HoldingDetailPanel doesn't use
 *                           useQueryState directly; the parent does).
 *
 * WHY mock all gateway methods to vi.fn() returning promises: child components
 * (HoldingRealizedRow, HoldingContributionStat, etc.) each fire their own
 * queries. Returning unresolved promises keeps them in loading state, which
 * avoids async assertions for sub-component data we don't test here.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Holding } from "@/types/api";

// ── Auth stub ────────────────────────────────────────────────────────────────
// WHY vi.mock at module scope: Vitest hoists vi.mock() before imports so every
// test sees the stub without any real auth flow running.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "test@example.com", name: "Test User", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Router stub ──────────────────────────────────────────────────────────────
// WHY mock next/navigation: useRouter() from Next.js requires the framework
// routing context. In Vitest/jsdom there's no App Router — calling push()
// without a stub throws "invariant: useRouter only works inside of the app
// directory".
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: mockPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    refresh: vi.fn(),
  })),
}));

// ── Gateway stub ─────────────────────────────────────────────────────────────
// WHY return never-resolving promises: child components (HoldingRealizedRow,
// HoldingLotsPanel, etc.) fire their own queries inside the panel. Returning
// unresolved promises keeps them in the "loading" state for the test duration,
// which means we only need to test the panel's own rendering — not waiting for
// every child query to resolve.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getRealizedPnL: vi.fn(() => new Promise(() => {})),
    getHoldings: vi.fn(() => new Promise(() => {})),
    getValueHistory: vi.fn(() => new Promise(() => {})),
    getTransactions: vi.fn(() => new Promise(() => {})),
    getEntityNews: vi.fn(() => new Promise(() => {})),
    getHoldingLots: vi.fn(() => new Promise(() => {})),
  })),
}));

// ── SUT import ───────────────────────────────────────────────────────────────
// WHY after vi.mock calls: Vitest hoists vi.mock() before any imports, but the
// import order here still matters for clarity — SUT comes after all stubs.
import { HoldingDetailPanel } from "../HoldingDetailPanel";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Wraps the component under test in the minimal providers it needs.
 *
 * WHY retry: false — without this, TanStack Query retries failed queries 3×
 * before entering error state, which slows down error-path tests dramatically.
 */
function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Minimal Holding fixture that satisfies the Holding interface. */
const MOCK_HOLDING: Holding = {
  holding_id: "h-001",
  portfolio_id: "p-001",
  instrument_id: "i-001",
  entity_id: "e-001",
  ticker: "AAPL",
  name: "Apple Inc.",
  quantity: 10,
  average_cost: 150.0,
  current_price: 175.0,
  unrealised_pnl: 250.0,
  unrealised_pnl_pct: 0.1667,
  portfolio_weight: 0.15,
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HoldingDetailPanel", () => {
  beforeEach(() => {
    // WHY clearAllMocks: each test should start with a clean call count so
    // assertions like "expect(mockPush).toHaveBeenCalledWith(...)" don't carry
    // over from a prior test.
    vi.clearAllMocks();
  });

  it("renders with translate-x-full class (visually hidden) when holding is null", () => {
    render(
      wrap(
        <HoldingDetailPanel
          portfolioId="p-001"
          holding={null}
          onClose={vi.fn()}
          period="1M"
        />,
      ),
    );

    // WHY query by role "dialog": the panel has role="dialog" — a semantic
    // landmark that screen readers announce. Querying by role is more robust
    // than querying by class name (which is implementation detail).
    const panel = screen.getByRole("dialog");

    // WHY check the class string rather than visual presence: jsdom does not
    // run CSS — we can't assert that the element is "invisible". Instead we
    // verify the Tailwind class that drives the CSS transform is present.
    // translate-x-full → translateX(100%) → element slides off-screen to the right.
    expect(panel.className).toContain("translate-x-full");
  });

  it("renders translate-x-0 and shows the ticker in the header when holding is provided", () => {
    render(
      wrap(
        <HoldingDetailPanel
          portfolioId="p-001"
          holding={MOCK_HOLDING}
          onClose={vi.fn()}
          period="1M"
        />,
      ),
    );

    const panel = screen.getByRole("dialog");

    // translate-x-0 → the panel is visible (no offset transform)
    expect(panel.className).toContain("translate-x-0");
    // WHY not toContain("translate-x-full"): when open the class should NOT be
    // translate-x-full. We assert both sides to catch accidental double-class.
    expect(panel.className).not.toContain("translate-x-full");

    // The ticker should appear in the header — use getAllByText since AAPL
    // also appears in the HoldingLotsPanel dropdown <option> element.
    // WHY getAllByText (not getByText): HoldingLotsPanel renders an <option>
    // with the ticker text. We verify at least one instance is in the header
    // by checking the aria-label on the aside which includes the ticker.
    const allAapl = screen.getAllByText("AAPL");
    expect(allAapl.length).toBeGreaterThanOrEqual(1);

    // Verify the header span specifically via the panel's aria-label.
    // WHY aria-label check: the <aside role="dialog"> has aria-label="Holding detail for AAPL"
    // which is the most semantically correct assertion for "header shows ticker".
    expect(screen.getByRole("dialog", { name: "Holding detail for AAPL" })).toBeInTheDocument();

    // The company name should appear in the header sub-label.
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
  });

  it("calls onClose when the Escape key is pressed", () => {
    const onClose = vi.fn();

    render(
      wrap(
        <HoldingDetailPanel
          portfolioId="p-001"
          holding={MOCK_HOLDING}
          onClose={onClose}
          period="1M"
        />,
      ),
    );

    // WHY fireEvent.keyDown on document: the panel registers its keydown
    // listener on `window` (not on the panel element itself). fireEvent.keyDown
    // on document bubbles up to window, matching the real browser behavior.
    fireEvent.keyDown(document, { key: "Escape" });

    // onClose should have been called exactly once.
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT call onClose when a different key is pressed", () => {
    const onClose = vi.fn();

    render(
      wrap(
        <HoldingDetailPanel
          portfolioId="p-001"
          holding={MOCK_HOLDING}
          onClose={onClose}
          period="1M"
        />,
      ),
    );

    // Pressing Enter should NOT trigger onClose.
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("calls onClose when the ✕ button is clicked", () => {
    const onClose = vi.fn();

    render(
      wrap(
        <HoldingDetailPanel
          portfolioId="p-001"
          holding={MOCK_HOLDING}
          onClose={onClose}
          period="1M"
        />,
      ),
    );

    // The close button has aria-label="Close holding detail"
    const closeBtn = screen.getByRole("button", { name: "Close holding detail" });
    fireEvent.click(closeBtn);

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
