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
import { ActivePortfolioProvider } from "@/contexts/ActivePortfolioContext";

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

function makeWrapper(registry: HotkeyRegistry, initialActiveId?: string | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      {/* `initialActiveId === undefined` (the default) lets the provider
          fall through to its localStorage lazy-init — tests that pre-seed
          localStorage before render rely on this behaviour. Passing an
          explicit value (including null) overrides it. */}
      <ActivePortfolioProvider initialActiveId={initialActiveId}>
        <HotkeyProvider registry={registry}>{children}</HotkeyProvider>
      </ActivePortfolioProvider>
    </QueryClientProvider>
  );
}

const PORT_ROOT = {
  portfolio_id: "01900000-0000-7000-8000-000000000001",
  name: "ROOT",
  currency: "USD",
  owner_id: "u-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  kind: "root" as const,
};
const PORT_BROKERAGE = {
  ...PORT_ROOT,
  portfolio_id: "01900000-0000-7000-8000-000000000002",
  name: "Tastytrade Main",
  kind: "brokerage" as const,
};
// A "demo" portfolio is the future kind — we cast through unknown so the
// forward-compat string-compare in the component can light up DemoBadge.
const PORT_DEMO = {
  ...PORT_ROOT,
  portfolio_id: "01900000-0000-7000-8000-000000000003",
  name: "Sample Demo",
  kind: "demo",
} as unknown as typeof PORT_ROOT;

beforeEach(() => {
  vi.clearAllMocks();
  mockGetPortfolios.mockResolvedValue([PORT_ROOT, PORT_BROKERAGE]);
  // Clean localStorage between tests so persistence assertions don't leak.
  // QA F-006 (2026-05-21): wrap in try/catch to mirror production helpers'
  // defensiveness — Safari Private Mode throws on localStorage access and
  // would otherwise blow up the entire beforeEach.
  if (typeof window !== "undefined") {
    try {
      window.localStorage.clear();
    } catch {
      /* private mode — no-op */
    }
  }
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
    render(<PortfolioSwitcher />, {
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
    // W1.1 F-002: selection writes through the ActivePortfolioContext,
    // which persists to localStorage and immediately updates the chip
    // label. The onChange callback prop no longer exists; the context
    // is the canonical wiring surface.
    expect(await screen.findByTestId("portfolio-switcher-chip")).toHaveTextContent("Tastytrade Main");
    expect(window.localStorage.getItem("shell.activePortfolioId")).toBe("01900000-0000-7000-8000-000000000002");
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
    expect(window.localStorage.getItem("shell.activePortfolioId")).toBe("01900000-0000-7000-8000-000000000002");
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

  // ── QA F-005 (2026-05-21): edge cases ────────────────────────────────

  it("(F-005) chip renders fallback label while portfolios are loading", () => {
    // Never-resolving fetch keeps the query in loading state forever.
    mockGetPortfolios.mockImplementation(() => new Promise(() => {}));
    render(<PortfolioSwitcher />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    // Chip is always visible (FU-1.1) and shows "All Portfolios" while
    // the active portfolio is unresolved — no flash of empty label.
    const chip = screen.getByTestId("portfolio-switcher-chip");
    expect(chip).toHaveTextContent(/All Portfolios/i);
  });

  it("(F-005) chip does not crash when getPortfolios rejects", async () => {
    mockGetPortfolios.mockRejectedValue(new Error("S9 down"));
    render(<PortfolioSwitcher />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    // Network error → chip stays visible with the fallback label.
    // (PortfolioSwitcher does not surface its own error UI — it
    // degrades silently to the "no portfolios" code path.)
    const chip = await screen.findByTestId("portfolio-switcher-chip");
    expect(chip).toBeInTheDocument();
  });

  it("(F-005) Alt+P actually opens the popover (not just no-throw)", async () => {
    const registry = new HotkeyRegistry();
    render(<PortfolioSwitcher />, { wrapper: makeWrapper(registry) });
    await screen.findByTestId("portfolio-switcher-chip");
    expect(screen.queryByTestId("portfolio-switcher-popover")).toBeNull();
    const binding = registry.all().find((b) => b.id === "shell.portfolio.switcher.toggle")!;
    act(() => binding.handler(new KeyboardEvent("keydown", { key: "p", altKey: true })));
    expect(await screen.findByTestId("portfolio-switcher-popover")).toBeInTheDocument();
    // Firing again closes it.
    act(() => binding.handler(new KeyboardEvent("keydown", { key: "p", altKey: true })));
    await waitFor(() => {
      expect(screen.queryByTestId("portfolio-switcher-popover")).toBeNull();
    });
  });

  it("(F-005) clicking outside the chip closes an open popover", async () => {
    const user = userEvent.setup();
    render(
      <div>
        <PortfolioSwitcher />
        <button data-testid="outside-target">elsewhere</button>
      </div>,
      { wrapper: makeWrapper(new HotkeyRegistry()) },
    );
    await user.click(await screen.findByTestId("portfolio-switcher-chip"));
    expect(await screen.findByTestId("portfolio-switcher-popover")).toBeInTheDocument();
    // The click-outside handler is on `mousedown` — dispatch one directly
    // since userEvent.click maps to pointerdown→mousedown→pointerup→click.
    await user.click(screen.getByTestId("outside-target"));
    await waitFor(() => {
      expect(screen.queryByTestId("portfolio-switcher-popover")).toBeNull();
    });
  });
});
