/**
 * components/instrument/brief/__tests__/AiBriefBanner.test.tsx
 *
 * WHY THIS EXISTS: AiBriefBanner (T-23) is the always-visible AI brief
 * banner between InstrumentHeader and the tab strip. It uses the
 * useInstrumentBrief hook (T-04) for the lazy-generate lifecycle.
 *
 * PRE-W5 behaviour (now replaced):
 *   - Returned null when brief was not available → empty DOM.
 *
 * W5-T-23 behaviour (what we test):
 *   1. Banner is ALWAYS visible — never renders an empty element (Δ27, §1.4).
 *      Even when status is "unavailable", the 24-px banner row is present.
 *   2. Shows "BRIEF" label + status text in collapsed mode.
 *   3. Expand/collapse toggle via the button still works when status="ready".
 *   4. sessionStorage `wv:brief-collapsed:{entityId}` persists expand pref.
 *   5. Hydrates expand pref from sessionStorage on mount.
 *
 * MOCK STRATEGY: mock `useInstrumentBrief` directly — that is the hook's
 * public API surface. Avoids threading a QueryClientProvider + AuthContext
 * + gateway fetch through a component that no longer does those things itself.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// WHY mock useInstrumentBrief directly: T-23's AiBriefBanner receives its
// data exclusively from this hook. Mocking at this layer is cheaper and
// more reliable than mocking the gateway + QueryClient + auth chain.
const mockUseInstrumentBrief = vi.hoisted(() => vi.fn());

vi.mock("@/components/instrument/hooks/useInstrumentBrief", () => ({
  useInstrumentBrief: mockUseInstrumentBrief,
}));

// WHY mock formatRelativeTime: it reads Date.now() internally; mocking keeps
// snapshot tests stable without time-freezing the entire test suite.
vi.mock("@/lib/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/utils")>();
  return { ...actual, formatRelativeTime: vi.fn(() => "3h ago") };
});

// IMPORTANT: import AFTER vi.mock calls so mocks are wired.
// eslint-disable-next-line import/first
import { AiBriefBanner } from "@/components/instrument/brief/AiBriefBanner";

// ── Helpers ──────────────────────────────────────────────────────────────────

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
  mockUseInstrumentBrief.mockReset();
  window.sessionStorage.clear();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("AiBriefBanner (W5-T-23 — always-visible rewrite)", () => {
  it("is always visible — renders the BRIEF label even when unavailable", () => {
    // WHY "unavailable": simulates a cold-cache + generation timeout scenario.
    // Pre-W5 the banner would return null here; W5 keeps the 24px layout slot.
    mockUseInstrumentBrief.mockReturnValue({
      data: undefined,
      status: "unavailable",
      retryAfter: undefined,
      refetch: vi.fn(),
    });
    render(<AiBriefBanner entityId="ent-001" />);
    // Banner is visible with BRIEF label (always-visible contract §1.4).
    expect(screen.getByText("BRIEF")).toBeInTheDocument();
    // Status label "Unavailable" appears in the collapsed preview area.
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });

  it("shows 'Generating…' when status is generating", () => {
    mockUseInstrumentBrief.mockReturnValue({
      data: undefined,
      status: "generating",
      retryAfter: undefined,
      refetch: vi.fn(),
    });
    render(<AiBriefBanner entityId="ent-001" />);
    expect(screen.getByText("Generating…")).toBeInTheDocument();
  });

  it("expands on first click and collapses on second click when ready", async () => {
    mockUseInstrumentBrief.mockReturnValue({
      data: fakeBrief("Apple beat EPS by 5c on iPhone strength."),
      status: "ready",
      retryAfter: undefined,
      refetch: vi.fn(),
    });
    render(<AiBriefBanner entityId="ent-001" />);
    const toggleButton = screen.getByRole("button");

    // Default state: collapsed → aria-expanded="false" (ready + not expanded).
    expect(toggleButton).toHaveAttribute("aria-expanded", "false");

    // First click → expand (aria-expanded goes true when ready + expanded).
    fireEvent.click(toggleButton);
    await waitFor(() =>
      expect(toggleButton).toHaveAttribute("aria-expanded", "true"),
    );

    // Second click → collapse.
    fireEvent.click(toggleButton);
    await waitFor(() =>
      expect(toggleButton).toHaveAttribute("aria-expanded", "false"),
    );
  });

  it("persists collapse state to sessionStorage keyed by entityId", async () => {
    mockUseInstrumentBrief.mockReturnValue({
      data: fakeBrief("Some narrative content here."),
      status: "ready",
      retryAfter: undefined,
      refetch: vi.fn(),
    });
    render(<AiBriefBanner entityId="ent-001" />);
    const toggleButton = screen.getByRole("button");

    // Expand → sessionStorage should now hold "expanded".
    fireEvent.click(toggleButton);
    await waitFor(() =>
      expect(window.sessionStorage.getItem("wv:brief-collapsed:ent-001")).toBe("expanded"),
    );

    // Collapse → "collapsed".
    fireEvent.click(toggleButton);
    await waitFor(() =>
      expect(window.sessionStorage.getItem("wv:brief-collapsed:ent-001")).toBe("collapsed"),
    );
  });

  it("hydrates from sessionStorage='expanded' on mount when ready", async () => {
    // Pre-seed sessionStorage to simulate previous session leaving banner expanded.
    window.sessionStorage.setItem("wv:brief-collapsed:ent-001", "expanded");
    mockUseInstrumentBrief.mockReturnValue({
      data: fakeBrief("Persisted-expanded narrative."),
      status: "ready",
      retryAfter: undefined,
      refetch: vi.fn(),
    });
    render(<AiBriefBanner entityId="ent-001" />);
    const toggleButton = screen.getByRole("button");
    // WHY waitFor: the useEffect that reads sessionStorage runs after the first
    // paint — give React a tick to flush the state update.
    await waitFor(() =>
      expect(toggleButton).toHaveAttribute("aria-expanded", "true"),
    );
  });
});
