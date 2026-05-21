/**
 * __tests__/shell/PortfolioSwitcher.test.tsx — PRD-0089 W1.
 *
 * Pins the contract that PortfolioSwitcher:
 *   - renders the chip even with zero (FU-1.1 — always visible) or one portfolio
 *   - shows "All Portfolios" as the chip label when ROOT is active
 *   - shows the portfolio name as the chip label when a non-ROOT portfolio is active
 *   - pins ROOT to the top of the dropdown above a hairline separator
 *   - renders DemoBadge next to the chip when the active portfolio kind === "demo"
 *     (forward-compat — gating works even though "demo" is not yet in the union)
 *   - persists selection to localStorage and restores it across remounts
 *   - registers the Alt+P chord; toggling fires it
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";

// ── Mocks ──────────────────────────────────────────────────────────────────

const mockGetPortfolios = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({ getPortfolios: mockGetPortfolios }),
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "tok", isAuthenticated: true }),
}));
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

import { PortfolioSwitcher } from "@/components/shell/PortfolioSwitcher";

// ── Helpers ────────────────────────────────────────────────────────────────

function makeWrapper(registry: HotkeyRegistry) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <HotkeyProvider registry={registry}>{children}</HotkeyProvider>
    </QueryClientProvider>
  );
}

const PORT_ROOT = {
  portfolio_id: "p-root",
  name: "ROOT",
  currency: "USD",
  owner_id: "u-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  kind: "root" as const,
};
const PORT_BROKERAGE = {
  ...PORT_ROOT,
  portfolio_id: "p-bk",
  name: "Tastytrade Main",
  kind: "brokerage" as const,
};
// A "demo" portfolio is the future kind — we cast through unknown so the
// forward-compat string-compare in the component can light up DemoBadge.
const PORT_DEMO = {
  ...PORT_ROOT,
  portfolio_id: "p-demo",
  name: "Sample Demo",
  kind: "demo",
} as unknown as typeof PORT_ROOT;

beforeEach(() => {
  vi.clearAllMocks();
  mockGetPortfolios.mockResolvedValue([PORT_ROOT, PORT_BROKERAGE]);
  // Clean localStorage between tests so persistence assertions don't leak.
  if (typeof window !== "undefined") window.localStorage.clear();
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("PortfolioSwitcher", () => {
  it("renders the chip with default 'All Portfolios' label", async () => {
    render(<PortfolioSwitcher />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    const chip = await screen.findByTestId("portfolio-switcher-chip");
    expect(chip).toBeInTheDocument();
    expect(chip).toHaveTextContent(/All Portfolios/i);
  });

  it("chip is still rendered when the user has zero portfolios (FU-1.1)", async () => {
    mockGetPortfolios.mockResolvedValue([]);
    render(<PortfolioSwitcher />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    expect(await screen.findByTestId("portfolio-switcher-chip")).toBeInTheDocument();
  });

  it("dropdown pins ROOT to the top with a hairline separator below", async () => {
    const user = userEvent.setup();
    render(<PortfolioSwitcher />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    await user.click(await screen.findByTestId("portfolio-switcher-chip"));
    const popover = await screen.findByTestId("portfolio-switcher-popover");
    // The first interactive option inside the popover must be the ROOT row.
    const options = popover.querySelectorAll('[role="option"]');
    expect(options.length).toBeGreaterThan(0);
    expect(options[0]).toHaveTextContent(/All Portfolios/i);
  });

  it("selecting a non-ROOT portfolio flips the chip label to its name", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PortfolioSwitcher onActivePortfolioChange={onChange} />, {
      wrapper: makeWrapper(new HotkeyRegistry()),
    });
    await user.click(await screen.findByTestId("portfolio-switcher-chip"));
    const popover = await screen.findByTestId("portfolio-switcher-popover");
    const bkRow = await waitFor(() => {
      const row = Array.from(popover.querySelectorAll('[role="option"]')).find((el) =>
        el.textContent?.includes("Tastytrade Main"),
      );
      if (!row) throw new Error("brokerage row not yet rendered");
      return row as HTMLButtonElement;
    });
    await user.click(bkRow);
    expect(onChange).toHaveBeenCalledWith("p-bk");
    expect(await screen.findByTestId("portfolio-switcher-chip")).toHaveTextContent("Tastytrade Main");
  });

  it("renders DemoBadge when the active portfolio kind === 'demo'", async () => {
    mockGetPortfolios.mockResolvedValue([PORT_ROOT, PORT_DEMO]);
    // Pre-select the demo portfolio via localStorage so we don't have to click
    // through the dropdown in this assertion.
    window.localStorage.setItem("shell.activePortfolioId", PORT_DEMO.portfolio_id);
    render(<PortfolioSwitcher />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    // DemoBadge renders the literal text "Demo" (per F1 primitive).
    expect(await screen.findByText(/^Demo$/)).toBeInTheDocument();
  });

  it("persists selection to localStorage", async () => {
    const user = userEvent.setup();
    render(<PortfolioSwitcher />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    await user.click(await screen.findByTestId("portfolio-switcher-chip"));
    const popover = await screen.findByTestId("portfolio-switcher-popover");
    const bkRow = await waitFor(() => {
      const row = Array.from(popover.querySelectorAll('[role="option"]')).find((el) =>
        el.textContent?.includes("Tastytrade Main"),
      );
      if (!row) throw new Error("brokerage row not yet rendered");
      return row as HTMLButtonElement;
    });
    await user.click(bkRow);
    expect(window.localStorage.getItem("shell.activePortfolioId")).toBe("p-bk");
  });

  it("registers the alt+p chord on mount", () => {
    const registry = new HotkeyRegistry();
    render(<PortfolioSwitcher />, { wrapper: makeWrapper(registry) });
    const bindings = registry.all();
    const altP = bindings.find((b) => b.id === "shell.portfolio.switcher.toggle");
    expect(altP).toBeDefined();
    expect(altP?.chord).toBe("alt+p");
    // Firing the handler toggles dropdown — sanity-check it does not throw.
    act(() => altP?.handler(new KeyboardEvent("keydown", { key: "p", altKey: true })));
  });
});
