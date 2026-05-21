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
  // W1.1 H-001: the marquee renders the manifest TWICE in the DOM (first
  // pass + seamless loop duplicate) but the duplicate sits inside an
  // `aria-hidden role=presentation` subtree so AT / getByRole queries only
  // see the first pass — exactly manifest.length buttons. That's the
  // intended behaviour: screen readers never announce double.
  it("renders a button per manifest entry in the accessibility tree (a11y)", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => {
      const buttons = screen.getAllByRole("button", { name: /view index detail/i });
      expect(buttons).toHaveLength(MANIFEST_TICKERS.length);
    });
  });

  // Pin the doubled-DOM render too — without the duplicate the marquee
  // loops with a visible seam. We count via querySelectorAll on data-ticker
  // (the dup is aria-hidden, so we can't use getAllByRole).
  it("renders the cell DOM twice (first pass + aria-hidden loop duplicate)", async () => {
    const { container } = render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => {
      const tickerNodes = container.querySelectorAll("[data-ticker]");
      expect(tickerNodes.length).toBe(MANIFEST_TICKERS.length * 2);
    });
  });

  it("includes the TNX cell (^TNX swap from FU-4.3)", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => {
      const tnx = screen.getAllByRole("button", { name: /10-Year Treasury Yield/i });
      expect(tnx.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("routes click on SPY cell to /indices/SPY", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    const spy = await waitFor(() => {
      const all = screen.getAllByRole("button", { name: /S&P 500 ETF/i });
      if (all.length === 0) throw new Error("no SPY button yet");
      return all[0];
    });
    await user.click(spy);
    expect(mockPush).toHaveBeenCalledWith("/indices/SPY");
  });

  it("routes ^TNX click to /indices/TNX (caret stripped from URL)", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    const tnx = await waitFor(() => {
      const all = screen.getAllByRole("button", { name: /10-Year Treasury Yield/i });
      if (all.length === 0) throw new Error("no TNX button yet");
      return all[0];
    });
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
    const spy = await waitFor(() => {
      const all = screen.getAllByRole("button", { name: /S&P 500 ETF/i });
      if (all.length === 0) throw new Error("no SPY button yet");
      return all[0];
    });
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

  // QA F-004 regression: caret-prefixed tickers like ^TNX don't match in
  // the S1 search index. Pre-fix the ^TNX cell rendered "TNX — —" because
  // searchInstruments("^TNX") returned no results. Fix: strip the caret
  // first, fall back to literal if that misses.
  it("(F-004 regression) ^TNX resolves via caret-stripped search first", async () => {
    // Mock returns a hit ONLY for the caret-stripped form to prove the
    // resolver tried it first.
    mockSearchInstruments.mockImplementation((ticker: string) => {
      if (ticker === "TNX") {
        return Promise.resolve({ results: [{ instrument_id: "id-TNX-stripped" }] });
      }
      if (ticker === "^TNX") {
        // Literal form returns empty — the resolver should never need this
        // result because the stripped form already succeeded.
        return Promise.resolve({ results: [] });
      }
      // All other manifest tickers resolve normally.
      return Promise.resolve({ results: [{ instrument_id: `id-${ticker}` }] });
    });
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => {
      const all = screen.getAllByRole("button", { name: /10-Year Treasury Yield/i });
      if (all.length === 0) throw new Error("no TNX button yet");
    });
    // The caret-stripped query must have been issued before any literal "^TNX" call.
    const tnxCalls = mockSearchInstruments.mock.calls
      .map((call) => call[0] as string)
      .filter((t) => t === "TNX" || t === "^TNX");
    expect(tnxCalls[0]).toBe("TNX");
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
