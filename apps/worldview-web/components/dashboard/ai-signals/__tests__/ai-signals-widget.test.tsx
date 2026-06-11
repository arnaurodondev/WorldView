/**
 * ai-signals-widget.test.tsx — rendering tests for the overhauled AI Signals
 * widget (2026-06-10).
 *
 * Pins the value-delivering behaviours the overhaul introduced:
 *  1. NO UUID prefixes — unlisted entities render their NAME, never "9ECB";
 *  2. per-entity grouping with an expandable "×N" cluster toggle;
 *  3. signal-type chip + direction glyph + honest confidence tooltip;
 *  4. row click navigates ticker-first (entity_id fallback);
 *  5. expanded evidence rows link to the triggering article.
 *
 * Loading / empty / error states are already pinned by
 * __tests__/dashboard-round3.test.tsx and dashboard-round4.test.tsx (R19 —
 * those tests are untouched and keep passing against this redesign).
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AiSignalsWidget } from "@/components/dashboard/AiSignalsWidget";
import type { EnrichedAiSignal } from "@/components/dashboard/ai-signals/types";

// ── Next.js router mock — capture push() so navigation can be asserted ───────
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: pushMock, replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Gateway mock — per-test data via getAiSignals ─────────────────────────────
const gatewayMocks = {
  getAiSignals: vi.fn().mockResolvedValue({ signals: [] }),
};
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => gatewayMocks),
}));

// ── Auth mock — widget only reads accessToken ─────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token", isAuthenticated: true })),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => {
  pushMock.mockClear();
  gatewayMocks.getAiSignals.mockClear();
  gatewayMocks.getAiSignals.mockResolvedValue({ signals: [] });
});

/** Enriched-signal factory mirroring the live S9 payload shape. */
function sig(overrides: Partial<EnrichedAiSignal>): EnrichedAiSignal {
  return {
    signal_id: `sig-${Math.random().toString(36).slice(2)}`,
    entity_id: "0190aaaa-bbbb-cccc-dddd-eeeeffff0001",
    ticker: "LULU",
    entity_name: "Lululemon Athletica",
    label: "NEGATIVE",
    polarity: "negative",
    signal_type: "EARNINGS_GUIDANCE",
    signal_type_label: "Guidance",
    score: 0.95,
    market_impact_score: 0,
    article_title: "Lululemon Cuts Outlook as Growth Struggles Continue",
    article_url: "https://example.com/lulu",
    source_name: "Yahoo Finance",
    published_at: "2026-06-10T11:00:00Z",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("AiSignalsWidget — enriched rows", () => {
  it("renders ticker, entity name, signal-type chip and direction-colored confidence", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [sig({})] });
    render(<AiSignalsWidget />, { wrapper });

    expect(await screen.findByText("LULU")).toBeInTheDocument();
    // Entity name sits beside the ticker — the user learns WHO without hover.
    expect(screen.getByText("Lululemon Athletica")).toBeInTheDocument();
    // Signal-type chip — the user learns WHAT fired.
    expect(screen.getByText("Guidance")).toBeInTheDocument();
    // Confidence is direction-colored (negative claim → text-negative).
    expect(screen.getByText("95%").className).toContain("text-negative");
  });

  it("explains the confidence metric in a tooltip (title attribute)", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [sig({})] });
    render(<AiSignalsWidget />, { wrapper });

    const score = await screen.findByText("95%");
    // The % must be DEFINED for the user — including what it is NOT.
    expect(score.getAttribute("title")).toMatch(/extraction confidence/i);
    expect(score.getAttribute("title")).toMatch(/not a prediction of price movement/i);
  });

  it("never renders a UUID prefix — unlisted entities show their name instead", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [
        sig({
          ticker: null,
          entity_id: "9ecb1234-0000-0000-0000-000000000000",
          entity_name: "Strait of Hormuz",
          label: "NEUTRAL",
          signal_type_label: "Macro",
        }),
      ],
    });
    render(<AiSignalsWidget />, { wrapper });

    // The name takes the primary slot…
    expect(await screen.findByText("Strait of Hormuz")).toBeInTheDocument();
    // …and the old `entity_id.slice(0,4).toUpperCase()` stub must be gone.
    expect(screen.queryByText("9ECB")).not.toBeInTheDocument();
  });

  it("groups multiple signals per entity into one row with an ×N toggle", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [
        sig({ signal_id: "a", ticker: "BAC", entity_id: "e-bac", entity_name: "Bank of America" }),
        sig({ signal_id: "b", ticker: "BAC", entity_id: "e-bac", entity_name: "Bank of America" }),
        sig({ signal_id: "c", ticker: "BAC", entity_id: "e-bac", entity_name: "Bank of America" }),
      ],
    });
    render(<AiSignalsWidget />, { wrapper });

    // ONE row for BAC (the old widget rendered three undifferentiated rows).
    await waitFor(() => {
      expect(screen.getAllByText("BAC")).toHaveLength(1);
    });
    expect(screen.getByRole("button", { name: /3 signals for BAC/i })).toBeInTheDocument();
  });

  it("expands a cluster to its evidence rows with article links", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [
        sig({
          signal_id: "a",
          ticker: "GILD",
          entity_id: "e-gild",
          article_title: "Gilead announces new results",
          article_url: "https://example.com/gild-1",
        }),
        sig({
          signal_id: "b",
          ticker: "GILD",
          entity_id: "e-gild",
          article_title: "Gilead gains attention",
          article_url: "https://example.com/gild-2",
        }),
      ],
    });
    render(<AiSignalsWidget />, { wrapper });

    const toggle = await screen.findByRole("button", { name: /2 signals for GILD/i });
    // Collapsed: evidence rows hidden.
    expect(screen.queryByText("Gilead announces new results")).not.toBeInTheDocument();

    await userEvent.click(toggle);

    // Expanded: each signal shows its triggering headline as an outbound link.
    const link = screen.getByRole("link", { name: "Gilead announces new results" });
    expect(link).toHaveAttribute("href", "https://example.com/gild-1");
    expect(screen.getByRole("link", { name: "Gilead gains attention" })).toBeInTheDocument();
    // Expanding must NOT navigate the row (stopPropagation on the toggle).
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("navigates ticker-first on row click, entity_id fallback when unlisted", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [
        sig({ ticker: "TSLA", entity_id: "e-tsla", entity_name: "Tesla Inc" }),
        sig({ ticker: null, entity_id: "e-cloud", entity_name: "Google Cloud" }),
      ],
    });
    render(<AiSignalsWidget />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: /^TSLA/ }));
    expect(pushMock).toHaveBeenCalledWith("/instruments/TSLA");

    await userEvent.click(screen.getByRole("button", { name: /^Google Cloud/ }));
    expect(pushMock).toHaveBeenCalledWith("/instruments/e-cloud");
  });

  it("renders the direction glyph color semantically for positive signals", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [sig({ label: "POSITIVE", polarity: "positive", score: 0.87 })],
    });
    const { container } = render(<AiSignalsWidget />, { wrapper });

    await screen.findByText("87%");
    // Direction is encoded with the semantic tokens (§15.11) — both the text
    // utility on the confidence and the literal bg token on the row tick.
    expect(screen.getByText("87%").className).toContain("text-positive");
    expect(container.querySelector(".bg-positive")).not.toBeNull();
    expect(container.innerHTML).not.toContain("text-[hsl(var(--positive))]");
  });
});
