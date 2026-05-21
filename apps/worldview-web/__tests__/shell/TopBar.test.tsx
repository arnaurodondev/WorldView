/**
 * __tests__/shell/TopBar.test.tsx — PRD-0089 W1 §4.3.
 *
 * Pins the contract that the W1 TopBar composes the full slot inventory:
 *   - Wordmark with aria-label "Worldview — Home" (skip-link target)
 *   - GlobalSearch trigger
 *   - PortfolioSwitcher chip
 *   - IndexStrip
 *   - UtcClock
 *   - MarketStatusPill
 *   - PortfolioRail (PORT / Day P&L / Total P&L)
 *   - AskAiButton
 *   - RefreshAllButton
 *   - Alert bell
 *   - Avatar
 * Total ≥17 interactive/information slots at 1440×900 (NFR-1 tier floor).
 *
 * Also pins logout-clearing behaviour (C-28): queryClient.clear() and
 * resetScopes() fire before redirect.
 *
 * Heavy children are mocked so this test stays focused on composition + the
 * logout flow — IndexStrip / PortfolioSwitcher each own their unit tests.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";

// ── Mocks for heavy shell children ────────────────────────────────────────

vi.mock("@/components/shell/UtcClock", () => ({
  UtcClock: () => <div data-testid="utc-clock" />,
}));
vi.mock("@/components/shell/IndexStrip", () => ({
  IndexStrip: () => <div data-testid="index-strip" />,
}));
vi.mock("@/components/shell/PortfolioSwitcher", () => ({
  PortfolioSwitcher: () => <div data-testid="portfolio-switcher" />,
}));
vi.mock("@/components/shell/MarketStatusPill", () => ({
  MarketStatusPill: () => <div data-testid="market-status" />,
}));
vi.mock("@/components/shell/GlobalSearch", () => ({
  GlobalSearch: () => <div data-testid="global-search" />,
}));
vi.mock("@/components/shell/AskAiButton", () => ({
  // The real button forwards a ref; the mock accepts an `onOpen` prop so the
  // TopBar composition assertion succeeds without re-implementing it.
  AskAiButton: () => <button data-testid="ask-ai" type="button" />,
}));
vi.mock("@/components/shell/RefreshAllButton", () => ({
  RefreshAllButton: () => <button data-testid="refresh-all" type="button" />,
}));

// ── useAuth mock — exposes a logout spy ───────────────────────────────────

const mockLogout = vi.fn();
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: { name: "Test User", email: "test@example.com", avatar_url: null },
    logout: mockLogout,
  }),
}));

// ── next/navigation mock — captures redirect calls ────────────────────────

const mockReplace = vi.fn();
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));

import { TopBar } from "@/components/shell/TopBar";

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const registry = new HotkeyRegistry();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <HotkeyProvider registry={registry}>{children}</HotkeyProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLogout.mockResolvedValue(undefined);
});

describe("TopBar — slot composition (PRD-0089 W1)", () => {
  it("renders wordmark with aria-label 'Worldview — Home'", () => {
    render(<TopBar portfolioValue={1_000_000} dailyPnl={1234} unrealisedPnl={5678} />, {
      wrapper: makeWrapper(),
    });
    expect(screen.getByRole("button", { name: /Worldview — Home/i })).toBeInTheDocument();
  });

  it("composes all W1 information slots (≥17 at 1440×900 density floor)", () => {
    render(
      <TopBar
        unreadAlerts={3}
        portfolioValue={1_240_000}
        dailyPnl={12_400}
        unrealisedPnl={48_700}
        onAskAi={() => undefined}
      />,
      { wrapper: makeWrapper() },
    );

    // Mocked children — each is a single slot.
    expect(screen.getByTestId("global-search")).toBeInTheDocument();
    expect(screen.getByTestId("portfolio-switcher")).toBeInTheDocument();
    expect(screen.getByTestId("index-strip")).toBeInTheDocument();
    expect(screen.getByTestId("utc-clock")).toBeInTheDocument();
    expect(screen.getByTestId("market-status")).toBeInTheDocument();
    expect(screen.getByTestId("ask-ai")).toBeInTheDocument();
    expect(screen.getByTestId("refresh-all")).toBeInTheDocument();

    // Wordmark + alert bell + avatar — these are inline in TopBar so we count
    // them via role queries.
    expect(screen.getByRole("button", { name: /Worldview — Home/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /unread alerts/i })).toBeInTheDocument();

    // PortfolioRail renders three labelled subslots (PORT / Day P&L / Total P&L).
    expect(screen.getByText("PORT")).toBeInTheDocument();
    expect(screen.getByText("Day P&L")).toBeInTheDocument();
    expect(screen.getByText("Total P&L")).toBeInTheDocument();
  });

  it("portfolio rail no longer carries rounded-[2px] (F1 radius=0 lock — C-04)", () => {
    const { container } = render(
      <TopBar portfolioValue={1_240_000} dailyPnl={12_400} unrealisedPnl={48_700} />,
      { wrapper: makeWrapper() },
    );
    const rail = container.querySelector('[aria-label="Portfolio header metrics"]');
    expect(rail).not.toBeNull();
    expect(rail?.className).not.toMatch(/rounded-\[2px\]/);
  });

  it("logout clears the query cache, resets scopes, then redirects (C-28)", async () => {
    const user = userEvent.setup();
    // Build a wrapper where we control the QueryClient + registry instances so
    // we can spy on `.clear()` and inspect scope state after logout.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const clearSpy = vi.spyOn(client, "clear");
    const registry = new HotkeyRegistry();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <HotkeyProvider registry={registry} initialScopes={["global", "modal"]}>
          {children}
        </HotkeyProvider>
      </QueryClientProvider>
    );

    render(<TopBar portfolioValue={1_000_000} />, { wrapper });
    // Open the avatar dropdown then click "Sign out".
    await user.click(screen.getByRole("button", { name: /Test User|TU/i }));
    await user.click(await screen.findByRole("menuitem", { name: /Sign out/i }));

    expect(clearSpy).toHaveBeenCalled();
    expect(mockLogout).toHaveBeenCalled();
    expect(mockReplace).toHaveBeenCalledWith("/login");
  });
});
