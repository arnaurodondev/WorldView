/**
 * sidebar/__tests__/AIBriefPanel.test.tsx — T-30 unit tests
 *
 * WHY THIS EXISTS (T-30): AIBriefPanel is the "AI BRIEF" block at the bottom
 * of the 7-panel sidebar (T-22). These tests verify the rendering contract:
 *   1. Loading state renders 3 skeleton divs.
 *   2. Triggering state renders "Generating brief…"
 *   3. Ready state renders up to 3 bullets with Δ28 kind chips.
 *   4. Error state renders error text + retry button.
 *   5. "Expand →" button opens the full brief dialog when brief is available.
 *
 * WHY mock useInstrumentBrief: the hook uses useEffect + polling via
 * setTimeout/useQuery + GatewayError detection. Testing through the real hook
 * would require a full TanStack Query + Auth provider tree. Mocking isolates
 * the panel's rendering contract from the hook's async state machine.
 *
 * WHY vi.mock before imports: ESM hoisting requires vi.mock calls to appear
 * before any import that resolves through the mocked path. Putting vi.mock
 * at the top prevents "ReferenceError: Cannot access before initialization".
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { BriefingResponse as InstrumentBrief } from "@/types/api";

// WHY mock the hook: useInstrumentBrief polls the S9 briefings endpoint with
// async state transitions. Mocking lets us exercise each status branch
// independently without timers, network, or providers.
vi.mock("@/components/instrument/hooks/useInstrumentBrief", () => ({
  useInstrumentBrief: vi.fn(),
}));

import { AIBriefPanel } from "@/components/instrument/financials/sidebar/AIBriefPanel";
import { useInstrumentBrief } from "@/components/instrument/hooks/useInstrumentBrief";

// ── Test helpers ───────────────────────────────────────────────────────────────

const mockUseInstrumentBrief = useInstrumentBrief as ReturnType<typeof vi.fn>;

// Sample brief matching the InstrumentBrief contract.
const SAMPLE_BRIEF: Partial<InstrumentBrief> = {
  entity_id: "test-entity-id",
  narrative: "Apple is a leading consumer electronics company with strong services revenue.",
  sections: [
    {
      title: "BULL CASE",
      bullets: [
        { text: "Record iPhone 15 demand driving Q4 upside." },
        { text: "Services ARR approaching $100B run rate." },
      ],
    },
    {
      title: "BEAR CASE",
      bullets: [
        { text: "China regulatory headwinds risk supply chain." },
      ],
    },
  ],
  risk_summary: undefined,
  generated_at: "2026-05-19T12:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("AIBriefPanel (T-30 rendering contract)", () => {
  it("renders the AI BRIEF section header in all states", () => {
    mockUseInstrumentBrief.mockReturnValue({
      brief: null, status: "idle", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    expect(screen.getByText("AI BRIEF")).toBeInTheDocument();
  });

  it("renders 3 skeleton divs in loading state", () => {
    mockUseInstrumentBrief.mockReturnValue({
      brief: null, status: "loading", errorMessage: null, retry: vi.fn(),
    });
    const { container } = render(<AIBriefPanel entityId="test-entity" />);
    // Round-4 item 4: skeletons are STATIC per DS §6.2 (raw animate-pulse is
    // banned) — target the stable testid instead of an animation class, and
    // pin the ban itself so the fast pulse can't sneak back in.
    const skeletons = container.querySelectorAll("[data-testid='brief-skeleton-row']");
    expect(container.querySelectorAll(".animate-pulse").length).toBe(0);
    expect(skeletons.length).toBe(3);
  });

  it("renders 'Generating brief…' text in triggering state", () => {
    mockUseInstrumentBrief.mockReturnValue({
      brief: null, status: "triggering", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    expect(screen.getByText("Generating brief…")).toBeInTheDocument();
  });

  it("renders 'Generating…' in polling state", () => {
    mockUseInstrumentBrief.mockReturnValue({
      brief: null, status: "polling", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    expect(screen.getByText("Generating…")).toBeInTheDocument();
  });

  it("renders error text and retry button in error state", () => {
    const retryFn = vi.fn();
    mockUseInstrumentBrief.mockReturnValue({
      brief: null, status: "error", errorMessage: "Generation failed", retry: retryFn,
    });
    render(<AIBriefPanel entityId="test-entity" />);
    expect(screen.getByText("Generation failed")).toBeInTheDocument();
    const retryBtn = screen.getByRole("button", { name: "Retry" });
    fireEvent.click(retryBtn);
    expect(retryFn).toHaveBeenCalledOnce();
  });

  it("renders default error message when errorMessage is null in error state", () => {
    mockUseInstrumentBrief.mockReturnValue({
      brief: null, status: "error", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    expect(screen.getByText("Brief unavailable")).toBeInTheDocument();
  });

  it("renders bullets with BULL kind chip in ready state", () => {
    mockUseInstrumentBrief.mockReturnValue({
      brief: SAMPLE_BRIEF, status: "ready", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    // WHY check for BULL chip: the Δ28 contract says section.title containing
    // "BULL" → kind="bull" → chip renders "BULL" label. SAMPLE_BRIEF has 2 BULL
    // bullets so we use getAllByText to handle multiple matching elements.
    const bullChips = screen.getAllByText("BULL");
    expect(bullChips.length).toBeGreaterThanOrEqual(1);
    // First bullet text should be visible (from BULL CASE section).
    expect(screen.getByText("Record iPhone 15 demand driving Q4 upside.")).toBeInTheDocument();
  });

  it("renders BEAR chip for BEAR CASE section bullets", () => {
    mockUseInstrumentBrief.mockReturnValue({
      brief: SAMPLE_BRIEF, status: "ready", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    // WHY assert at most 3 bullets total: extractBullets caps at 3.
    expect(screen.getByText("BEAR")).toBeInTheDocument();
  });

  it("renders no more than 3 bullets even when brief has many sections", () => {
    const manyBullets: Partial<InstrumentBrief> = {
      entity_id: "test",
      narrative: "Narrative text.",
      sections: [
        {
          title: "BULL CASE",
          bullets: [
            { text: "Bullet 1." },
            { text: "Bullet 2." },
            { text: "Bullet 3." },
            { text: "Bullet 4 — should NOT appear." },
          ],
        },
      ],
      generated_at: "2026-05-19T00:00:00Z",
    };
    mockUseInstrumentBrief.mockReturnValue({
      brief: manyBullets, status: "ready", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    expect(screen.queryByText("Bullet 4 — should NOT appear.")).not.toBeInTheDocument();
  });

  it("renders 'Expand →' button and opens dialog with full brief on click", () => {
    mockUseInstrumentBrief.mockReturnValue({
      brief: SAMPLE_BRIEF, status: "ready", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    const expandBtn = screen.getByRole("button", { name: "Expand AI brief" });
    expect(expandBtn).toBeInTheDocument();
    // WHY click + check dialog: the Expand button opens a shadcn Dialog.
    // Verifying the dialog title appears confirms the Dialog renders its content.
    fireEvent.click(expandBtn);
    expect(screen.getByText("AI INSTRUMENT BRIEF")).toBeInTheDocument();
    // Full narrative should be visible in the dialog.
    expect(screen.getByText("Apple is a leading consumer electronics company with strong services revenue.")).toBeInTheDocument();
  });

  it("does not render 'Expand →' button when no brief is available", () => {
    mockUseInstrumentBrief.mockReturnValue({
      brief: null, status: "idle", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    expect(screen.queryByRole("button", { name: "Expand AI brief" })).not.toBeInTheDocument();
  });

  it("falls back to narrative bullet parsing when sections is empty", () => {
    const noSections: Partial<InstrumentBrief> = {
      entity_id: "test",
      narrative: "First sentence. Second sentence. Third sentence. Fourth sentence.",
      sections: [],
      generated_at: "2026-05-19T00:00:00Z",
    };
    mockUseInstrumentBrief.mockReturnValue({
      brief: noSections, status: "ready", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    // WHY check "First sentence": when sections is empty, extractBullets
    // splits narrative by ". " and takes first 3. "First sentence" is the
    // first token.
    expect(screen.getByText("First sentence")).toBeInTheDocument();
    // "Fourth sentence" must not appear (capped at 3).
    expect(screen.queryByText("Fourth sentence.")).not.toBeInTheDocument();
  });

  // ── Regression: S9 sends risk_summary = {} (QA Wave-3, 2026-06-11) ─────────
  //
  // WHY: the live gateway serialises an EMPTY OBJECT for risk_summary when no
  // risk data was computed (observed on GET /v1/briefings/instrument/{AAPL}).
  // `{}` is truthy, so the old `brief.risk_summary && …top_risk_signals.map()`
  // guard crashed with "Cannot read properties of undefined (reading 'map')"
  // and error-boundaried the ENTIRE Financials tab. These tests pin the
  // hasRiskSummary() field-level guard.
  it("does not crash when risk_summary is an empty object ({}) from S9", () => {
    const emptyRisk: Partial<InstrumentBrief> = {
      ...SAMPLE_BRIEF,
      // Cast: the declared type says "full object | null", but the live wire
      // shape includes {} — exactly the mismatch this regression test pins.
      risk_summary: {} as InstrumentBrief["risk_summary"],
    };
    mockUseInstrumentBrief.mockReturnValue({
      brief: emptyRisk, status: "ready", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    // Bullets still render (the panel survived) …
    expect(screen.getByText("Record iPhone 15 demand driving Q4 upside.")).toBeInTheDocument();
    // … and no risk chip appears for an empty summary.
    expect(screen.queryByText(/RISK$/)).not.toBeInTheDocument();
    // The Expand dialog (which also renders the risk block) must not crash either.
    fireEvent.click(screen.getByRole("button", { name: "Expand AI brief" }));
    expect(screen.getByText("AI INSTRUMENT BRIEF")).toBeInTheDocument();
  });

  it("still renders the risk chip when risk_summary is fully populated", () => {
    const withRisk: Partial<InstrumentBrief> = {
      ...SAMPLE_BRIEF,
      risk_summary: {
        concentration_score: 0.8,
        top_risk_signals: [{ signal_id: "sig-1", description: "Supplier concentration" }],
        sector_breakdown: {},
      },
    };
    mockUseInstrumentBrief.mockReturnValue({
      brief: withRisk, status: "ready", errorMessage: null, retry: vi.fn(),
    });
    render(<AIBriefPanel entityId="test-entity" />);
    expect(screen.getByText("HIGH RISK")).toBeInTheDocument();
    // Dialog path renders the signal list.
    fireEvent.click(screen.getByRole("button", { name: "Expand AI brief" }));
    expect(screen.getByText(/Supplier concentration/)).toBeInTheDocument();
  });
});
