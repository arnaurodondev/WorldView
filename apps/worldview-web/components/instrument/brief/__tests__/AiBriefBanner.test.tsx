/**
 * components/instrument/brief/__tests__/AiBriefBanner.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-E-02): AiBriefBanner is the 1-line collapsible
 * AI brief that sits between the instrument header and tab bar (PRD-0088 §6.5).
 * This test pins three behaviours:
 *
 *   1. test_AiBriefBanner_hides_when_brief_null
 *      The banner MUST render nothing when the gateway returns no brief — no
 *      empty box, no skeleton (spec: "banner hidden entirely if brief returns
 *      404 or is null"). A regression that leaves an empty 24-px row would
 *      shift the chart by 24 px on every cold-cache instrument.
 *
 *   2. test_AiBriefBanner_expands_on_click
 *      First click expands; second click collapses. The visual toggle is the
 *      whole point of the component.
 *
 *   3. test_AiBriefBanner_persists_state_to_sessionStorage
 *      The collapse pref is persisted in sessionStorage so navigating away and
 *      back keeps the user's choice. Spec mandates sessionStorage (NOT local-
 *      storage) so the pref doesn't outlive the tab.
 *
 * MOCK STRATEGY: we mock @/lib/gateway so the brief query resolves to whatever
 * the test scenario needs. useAuth is mocked to provide a token so the query
 * is enabled. next/navigation is mocked because some sibling code reads
 * usePathname() during render. We use a per-test fresh QueryClient.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ────────────────────────────────────────────────────────────────────
// WHY a hoisted vi.mock for gateway: hoist makes the mock replace the import
// before the component module pulls it in. Without hoist, the component would
// import the real module and we'd hit the network in jsdom.

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// WHY per-test mock of gateway: each scenario needs a different return value
// (null vs a populated brief). We use vi.hoisted to share a handle so each
// test can override the mock function via `mockGateway.getInstrumentBrief
// .mockResolvedValue(...)`.
const mockGateway = vi.hoisted(() => ({
  getInstrumentBrief: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// IMPORTANT: import the component AFTER vi.mock calls so the mocks are wired.
// eslint-disable-next-line import/first
import { AiBriefBanner } from "@/components/instrument/brief/AiBriefBanner";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Fresh QueryClient per test — see makeWrapper pattern in wave-f-remainder. */
function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/**
 * Minimal valid BriefingResponse — only the fields the banner reads.
 * Cast to any-then-explicit because the full type pulls in many unrelated
 * fields (sections, entity_mentions, etc.) the banner doesn't touch.
 */
function fakeBrief(narrative: string) {
  return {
    narrative,
    generated_at: new Date().toISOString(),
    cached: false,
    entity_id: "ent-001",
    risk_summary: null,
    citations: [],
  };
}

// ── Test resets ──────────────────────────────────────────────────────────────

beforeEach(() => {
  // Reset mocks + clear sessionStorage between tests so persistence assertions
  // are deterministic (no cross-test contamination).
  mockGateway.getInstrumentBrief.mockReset();
  window.sessionStorage.clear();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("AiBriefBanner", () => {
  it("renders nothing when the brief is null (banner hidden entirely)", async () => {
    // Resolve to null = brief 404 / cold-cache path. Component should bail
    // before rendering any DOM at all.
    mockGateway.getInstrumentBrief.mockResolvedValue(null);
    const { container } = render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    // WHY waitFor: the query is async; first render returns undefined data
    // (which also yields null). We just need the empty render to stabilise.
    await waitFor(() => {
      expect(container).toBeEmptyDOMElement();
    });
  });

  it("expands on first click and collapses on second click", async () => {
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief("Apple beat EPS by 5c on iPhone strength."));
    render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    // WHY waitFor: query resolution is async — wait for the BRIEF label.
    const toggleButton = await waitFor(() => screen.getByRole("button"));
    // Default state: collapsed → aria-expanded="false".
    expect(toggleButton).toHaveAttribute("aria-expanded", "false");

    // First click → expand.
    fireEvent.click(toggleButton);
    expect(toggleButton).toHaveAttribute("aria-expanded", "true");

    // Second click → collapse again.
    fireEvent.click(toggleButton);
    expect(toggleButton).toHaveAttribute("aria-expanded", "false");
  });

  it("persists collapse state to sessionStorage keyed by entityId", async () => {
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief("Some narrative content here."));
    render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    const toggleButton = await waitFor(() => screen.getByRole("button"));
    // Expand → sessionStorage should now hold "expanded".
    fireEvent.click(toggleButton);
    expect(window.sessionStorage.getItem("wv:brief-collapsed:ent-001")).toBe("expanded");
    // Collapse → "collapsed".
    fireEvent.click(toggleButton);
    expect(window.sessionStorage.getItem("wv:brief-collapsed:ent-001")).toBe("collapsed");
  });

  it("hydrates from sessionStorage='expanded' on mount", async () => {
    // Pre-seed sessionStorage to simulate a previous session leaving the
    // banner expanded. On mount the useEffect should pick this up.
    window.sessionStorage.setItem("wv:brief-collapsed:ent-001", "expanded");
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief("Persisted-expanded narrative."));
    render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    const toggleButton = await waitFor(() => screen.getByRole("button"));
    // WHY waitFor: the useEffect that reads sessionStorage runs after the
    // first paint — give React a tick to flush the state update.
    await waitFor(() => {
      expect(toggleButton).toHaveAttribute("aria-expanded", "true");
    });
  });
});
