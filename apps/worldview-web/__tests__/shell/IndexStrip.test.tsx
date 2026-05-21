/**
 * __tests__/shell/IndexStrip.test.tsx — PRD-0089 W1.
 *
 * Pins the contract that the static 10-cell IndexStrip:
 *   - renders one button per manifest entry once quotes resolve
 *   - includes ^TNX (TNX) per FU-4.3 (USO was swapped out for TNX in the plan,
 *     though USO still ships as the lowest-priority cell)
 *   - routes clicks to /indices/{label} (caret stripped — `^TNX` → /indices/TNX)
 *   - renders a 10-cell loading skeleton while ticker → ID resolution is pending
 *     (never collapses to zero width — prevents TopBar layout shift)
 *   - applies tabular-nums on numeric cells so columns line up across the strip
 *
 * Gateway is mocked at the module boundary so the suite never opens a network
 * call (mirrors the pattern in WatchlistMoversWidget.insights.test.tsx).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Module mocks — set before importing the component under test ──────────

const mockSearchInstruments = vi.fn();
const mockGetBatchQuotes = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    searchInstruments: mockSearchInstruments,
    getBatchQuotes: mockGetBatchQuotes,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

import { IndexStrip } from "@/components/shell/IndexStrip";

// ── Test fixtures ──────────────────────────────────────────────────────────

const MANIFEST_TICKERS = [
  "SPY", "QQQ", "IWM", "VIX", "DIA",
  "TLT", "^TNX", "BTC-USD", "GLD", "USO",
];

function makeWrapper() {
  // retry:false stops TanStack from masking thrown errors with hidden retries.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // searchInstruments returns the ticker as its own resolved instrument_id —
  // makes assertions about call routing trivial.
  mockSearchInstruments.mockImplementation((ticker: string) =>
    Promise.resolve({ results: [{ instrument_id: `id-${ticker}` }] }),
  );
  // Batch quotes returns a flat $100 / +0.50% for every resolved ID so we
  // know every cell renders a non-em-dash value.
  mockGetBatchQuotes.mockImplementation((ids: string[]) =>
    Promise.resolve({
      quotes: Object.fromEntries(
        ids.map((id) => [id, { price: 100, change_pct: 0.5 }]),
      ),
    }),
  );
});

describe("IndexStrip", () => {
  it("renders a button for every manifest entry once quotes resolve", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    // Each manifest entry becomes a button whose aria-label includes its
    // displayName (e.g. "S&P 500 ETF — view index detail").
    await waitFor(() => {
      const buttons = screen.getAllByRole("button", { name: /view index detail/i });
      expect(buttons).toHaveLength(MANIFEST_TICKERS.length);
    });
  });

  it("includes the TNX cell (^TNX swap from FU-4.3)", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /10-Year Treasury Yield/i })).toBeInTheDocument();
    });
  });

  it("routes click on SPY cell to /indices/SPY", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    const spy = await screen.findByRole("button", { name: /S&P 500 ETF/i });
    await user.click(spy);
    expect(mockPush).toHaveBeenCalledWith("/indices/SPY");
  });

  it("routes ^TNX click to /indices/TNX (caret stripped from URL)", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    const tnx = await screen.findByRole("button", { name: /10-Year Treasury Yield/i });
    await user.click(tnx);
    expect(mockPush).toHaveBeenCalledWith("/indices/TNX");
  });

  it("renders 10 loading-skeleton cells while resolution is pending", () => {
    // Return a never-resolving promise so the resolveIds query stays pending.
    mockSearchInstruments.mockImplementation(() => new Promise(() => {}));
    render(<IndexStrip />, { wrapper: makeWrapper() });
    const skeleton = screen.getByTestId("index-strip-loading");
    // The loading wrapper renders one placeholder div per manifest entry; we
    // assert the count matches so the TopBar never collapses to zero width.
    expect(skeleton.children.length).toBe(MANIFEST_TICKERS.length);
  });

  it("applies font-mono tabular-nums to numeric cells", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    const spy = await screen.findByRole("button", { name: /S&P 500 ETF/i });
    // Both price and change% spans must carry tabular-nums so columns align
    // when prices change digit count. The exact spans live as descendants of
    // the button.
    const numericSpans = within(spy)
      .getAllByText(/[0-9]/)
      .filter((el) => el.tagName === "SPAN");
    expect(numericSpans.length).toBeGreaterThan(0);
    for (const span of numericSpans) {
      expect(span.className).toMatch(/tabular-nums/);
    }
  });

  it("hides the entire strip below the lg breakpoint", () => {
    // CSS class assertion is the most we can verify in jsdom (no layout).
    // The wrapper carries `hidden lg:flex` so it is display:none in <1024px.
    const { container } = render(<IndexStrip />, { wrapper: makeWrapper() });
    const wrapper =
      container.querySelector("[data-testid='index-strip-loading']") ??
      container.querySelector("[data-testid='index-strip']");
    expect(wrapper).not.toBeNull();
    expect(wrapper?.className).toMatch(/\bhidden\b/);
    expect(wrapper?.className).toMatch(/lg:flex/);
  });
});
