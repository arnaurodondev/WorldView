/**
 * __tests__/shell/IndexStrip.test.tsx — ticker tape contract
 *
 * Pins the contract that IndexStrip (marquee rewrite, 2026-06-10):
 *   - renders skeleton cells while resolving instrument IDs (aria-busy)
 *   - renders the FULL 16-ticker manifest after data loads
 *   - clicking a cell navigates to /indices/{ticker} (not /instruments/*)
 *   - strips "^" caret from URL segments (^TNX → /indices/TNX)
 *   - marquee structure: animated track (.marquee-strip + --marquee-duration)
 *     with TWO copies; duplicate copy is aria-hidden and keyboard-inert
 *   - reduced-motion fallback: a single-copy static row exists with the
 *     .marquee-static-fallback class (the global CSS swaps display between
 *     the animated track and this row under prefers-reduced-motion)
 *
 * NOTE on getAllByText: each ticker label legitimately appears 3× in the DOM
 * (track copy #1, aria-hidden track copy #2, static fallback). Tests assert
 * against the FIRST (interactive) instance.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ──────────────────────────────────────────────────────────────────

const mockResolveTickersBatch = vi.fn();
const mockGetBatchQuotes = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    resolveTickersBatch: mockResolveTickersBatch,
    getBatchQuotes: mockGetBatchQuotes,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

import { IndexStrip, INDEX_STRIP_TICKERS } from "@/components/shell/IndexStrip";

// ── Helpers ────────────────────────────────────────────────────────────────

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

/** Build a mock resolveTickersBatch result mapping each ticker to a fake UUID */
function makeTickerMap(tickers: readonly string[]) {
  const map: Record<string, string> = {};
  tickers.forEach((t, i) => { map[t] = `instrument-id-${i}`; });
  return map;
}

/** Build a mock getBatchQuotes result with price/change_pct for each UUID */
function makeQuotes(ids: string[]) {
  const quotes: Record<string, { price: number; change_pct: number }> = {};
  ids.forEach((id, i) => { quotes[id] = { price: 100 + i * 10, change_pct: i % 2 === 0 ? 1.5 : -0.5 }; });
  return { quotes };
}

const ALL_TICKERS = INDEX_STRIP_TICKERS.map((t) => t.canonicalTicker);

beforeEach(() => {
  vi.clearAllMocks();
  const map = makeTickerMap(ALL_TICKERS);
  mockResolveTickersBatch.mockResolvedValue(map);
  const ids = Object.values(map);
  mockGetBatchQuotes.mockResolvedValue(makeQuotes(ids));
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("IndexStrip (ticker tape)", () => {
  it("renders loading skeleton cells before data resolves", () => {
    // Keep the mock pending forever so we stay in loading state.
    mockResolveTickersBatch.mockImplementation(() => new Promise(() => {}));
    const { container } = render(<IndexStrip />, { wrapper: makeWrapper() });
    // The skeleton container has aria-busy="true" while loading.
    expect(container.querySelector("[aria-busy='true']")).toBeInTheDocument();
  });

  it("carries a LARGER instrument set than the old static strip (≥16 incl. crypto/commodities/sectors)", () => {
    // The whole point of the marquee (user feedback 2026-06-10) is a larger
    // tape. Pin the manifest floor + the new asset-class coverage so a future
    // edit can't silently shrink it back to the 10-cell static set.
    expect(INDEX_STRIP_TICKERS.length).toBeGreaterThanOrEqual(16);
    const tickers = INDEX_STRIP_TICKERS.map((t) => t.canonicalTicker);
    expect(tickers).toContain("BTC-USD");
    expect(tickers).toContain("ETH-USD");
    expect(tickers).toContain("SLV");
    expect(tickers).toContain("XLK");
  });

  it("renders all manifest display labels after data loads", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => {
      // Labels render in BOTH track copies + the static fallback (3×) —
      // assert presence, not uniqueness.
      expect(screen.getAllByText("SPY").length).toBeGreaterThan(0);
      expect(screen.getAllByText("QQQ").length).toBeGreaterThan(0);
    });
    // BTC-USD / ETH-USD display as "BTC" / "ETH" (short labels).
    expect(screen.getAllByText("BTC").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ETH").length).toBeGreaterThan(0);
    // "^TNX" displays as "TNX" (caret stripped from label).
    expect(screen.getAllByText("TNX").length).toBeGreaterThan(0);
  });

  it("clicking SPY cell navigates to /indices/SPY", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getAllByText("SPY"));
    await user.click(screen.getAllByText("SPY")[0].closest("button")!);
    expect(mockPush).toHaveBeenCalledWith("/indices/SPY");
  });

  it("clicking TNX cell navigates to /indices/TNX (caret stripped)", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getAllByText("TNX"));
    await user.click(screen.getAllByText("TNX")[0].closest("button")!);
    // WHY /indices/TNX (not /indices/^TNX): caret is stripped from URL segments
    // per C-10 — the "^" character is meta in URLs and looks odd in routes.
    expect(mockPush).toHaveBeenCalledWith("/indices/TNX");
  });

  it("clicking BTC cell navigates to /indices/BTC-USD", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getAllByText("BTC"));
    await user.click(screen.getAllByText("BTC")[0].closest("button")!);
    expect(mockPush).toHaveBeenCalledWith("/indices/BTC-USD");
  });

  it("shows '—' price when no quote is available for a ticker", async () => {
    // Return an empty quotes object so no ticker has price data.
    mockGetBatchQuotes.mockResolvedValue({ quotes: {} });
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getAllByText("SPY"));
    // All price slots should show "—" (em-dash fallback per plan §4.1).
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });

  // ── Marquee-specific contract ─────────────────────────────────────────────

  it("animated track uses .marquee-strip with a --marquee-duration variable", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getAllByText("SPY"));
    const track = screen.getByTestId("index-strip-marquee");
    // .marquee-strip wires the keyframes + hover pause + reduced-motion hide
    // (all defined in app/globals.css — this class IS the animation contract).
    expect(track.className).toContain("marquee-strip");
    // Duration scales with manifest size so the pixel velocity is constant.
    expect(track.style.getPropertyValue("--marquee-duration")).toMatch(/^\d+s$/);
  });

  it("renders a duplicate track copy that is aria-hidden and keyboard-inert (seamless loop)", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getAllByText("SPY"));
    const duplicate = screen.getByTestId("index-strip-copy-duplicate");
    // The duplicate exists purely for visual loop continuity — it must be
    // invisible to screen readers AND unreachable by Tab.
    expect(duplicate.getAttribute("aria-hidden")).toBe("true");
    const dupButtons = duplicate.querySelectorAll("button");
    expect(dupButtons.length).toBe(INDEX_STRIP_TICKERS.length);
    dupButtons.forEach((b) => expect(b.tabIndex).toBe(-1));
    // The PRIMARY copy stays interactive (no tabIndex override). Two
    // "index-strip-copy" nodes exist (track primary + static fallback copy) —
    // [0] is the in-track primary by DOM order.
    const primary = screen.getAllByTestId("index-strip-copy")[0];
    expect(primary.getAttribute("aria-hidden")).toBeNull();
  });

  it("renders a static reduced-motion fallback row (single copy, scrollable)", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getAllByText("SPY"));
    const fallback = screen.getByTestId("index-strip-static-fallback");
    // .marquee-static-fallback + hidden: display:none by default; the global
    // @media (prefers-reduced-motion: reduce) block in app/globals.css flips
    // it to display:flex AND hides .marquee-strip — full animation opt-out.
    expect(fallback.className).toContain("marquee-static-fallback");
    expect(fallback.className).toContain("hidden");
    // overflow-x-auto: under reduced motion the full tape is reachable by
    // scrolling instead of waiting for the loop to bring cells around.
    expect(fallback.className).toContain("overflow-x-auto");
    // Exactly ONE copy inside the fallback (no duplicate needed when static).
    expect(fallback.querySelectorAll("[data-testid='index-strip-copy']").length).toBe(1);
  });
});
