/**
 * components/portfolio/__tests__/BottomStripCluster.test.tsx
 * (PLAN-0108 W4-T404)
 *
 * WHY THIS EXISTS: BottomStripCluster is a layout wrapper that routes prop data
 * to three children. These tests verify:
 *   1. All three cells are rendered (structural integrity check).
 *   2. Contributors array is forwarded to Cell 1's ContributorsStrip.
 *   3. Detractors array is forwarded to Cell 2's ContributorsStrip.
 *
 * MOCKED: ContributorsStrip and RecentActivityStrip.
 *
 * WHY we mock the children (not render real ones):
 *   ContributorsStrip uses next/link (needs router context) and
 *   RecentActivityStrip calls useAuth + useQuery (needs QueryClientProvider and
 *   auth context). Mocking both keeps these tests as pure unit tests of
 *   BottomStripCluster's prop-routing logic — child rendering is tested in their
 *   own test files. Mocking also prevents the test from being coupled to child
 *   implementation details that could change independently.
 *
 * WHY no QueryClientProvider or router wrapper:
 *   With children mocked, BottomStripCluster has zero hooks or context
 *   dependencies of its own. The render is synchronous and needs no async helpers.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ── Child mocks ────────────────────────────────────────────────────────────────

/**
 * WHY capture-and-render approach: we need to verify which props were passed to
 * each ContributorsStrip instance. The mock renders a testid data attribute that
 * encodes the length of contributors/detractors arrays — this lets us assert
 * that the correct side of movers was forwarded without inspecting React
 * internals or using ref forwarding.
 *
 * WHY two separate ContributorsStrip instances share one mock: vi.mock hoists to
 * module scope and replaces the entire @/components/portfolio/ContributorsStrip
 * module. The single mock function captures every call in order — the first call
 * is Cell 1 (contributors), the second is Cell 2 (detractors).
 */
const mockContributorsStripCalls: Array<{
  contributorsCount: number;
  detractorsCount: number;
}> = [];

vi.mock("@/components/portfolio/ContributorsStrip", () => ({
  ContributorsStrip: vi.fn(
    ({
      contributors,
      detractors,
    }: {
      contributors: { ticker: string; pnlPct: number }[];
      detractors: { ticker: string; pnlPct: number }[];
    }) => {
      // Record call order so tests can assert which side came first.
      mockContributorsStripCalls.push({
        contributorsCount: contributors.length,
        detractorsCount: detractors.length,
      });
      return (
        <div
          data-testid="contributors-strip-mock"
          data-contributors={contributors.length}
          data-detractors={detractors.length}
        />
      );
    },
  ),
}));

/**
 * WHY simple stub for RecentActivityStrip: this test only needs to confirm that
 * Cell 3 renders (structural test). The portfolioId forwarding is verified by
 * checking the data-portfolio-id attribute. No async data is needed.
 */
vi.mock("@/components/portfolio/RecentActivityStrip", () => ({
  RecentActivityStrip: vi.fn(
    ({ portfolioId }: { portfolioId: string | null | undefined }) => (
      <div
        data-testid="recent-activity-strip-mock"
        data-portfolio-id={portfolioId ?? ""}
      />
    ),
  ),
}));

// ── Component under test ───────────────────────────────────────────────────────

// WHY import after vi.mock: vitest's mock hoisting means the mock is in place
// before the module resolves, but the import still needs to be below the mock
// declarations in source order to satisfy TypeScript module ordering expectations.
import { BottomStripCluster } from "@/components/portfolio/BottomStripCluster";
import type { MoverEntry } from "@/components/portfolio/BottomStripCluster";

// ── Fixtures ───────────────────────────────────────────────────────────────────

const CONTRIBUTORS: MoverEntry[] = [
  { ticker: "AAPL", name: "Apple Inc.", pnlPct: 5.2 },
  { ticker: "MSFT", name: "Microsoft Corp.", pnlPct: 3.1 },
];

const DETRACTORS: MoverEntry[] = [
  { ticker: "META", name: "Meta Platforms", pnlPct: -4.7 },
  { ticker: "NFLX", name: "Netflix Inc.", pnlPct: -2.3 },
];

const PORTFOLIO_ID = "portfolio-uuid-1234";

// ── Tests ──────────────────────────────────────────────────────────────────────

beforeEach(() => {
  // WHY clear between tests: mockContributorsStripCalls accumulates across
  // renders. Clearing before each test prevents call order from blending across
  // test cases and giving false positives.
  mockContributorsStripCalls.length = 0;
  vi.clearAllMocks();
});

describe("BottomStripCluster renders three cells", () => {
  it("renders the outer wrapper with three child cells", () => {
    render(
      <BottomStripCluster
        portfolioId={PORTFOLIO_ID}
        contributors={CONTRIBUTORS}
        detractors={DETRACTORS}
      />,
    );

    // WHY getByTestId for the wrapper: the outer div has a fixed testid; testing
    // its existence confirms the component mounted without throwing.
    const cluster = screen.getByTestId("bottom-strip-cluster");
    expect(cluster).toBeDefined();

    // WHY three cell testids: confirms all three layout slots are present.
    // If any child mock throws or the JSX tree is restructured, this fails fast.
    expect(screen.getByTestId("cell-contributors")).toBeDefined();
    expect(screen.getByTestId("cell-detractors")).toBeDefined();
    expect(screen.getByTestId("cell-recent-activity")).toBeDefined();

    // WHY two ContributorsStrip mocks: Cell 1 and Cell 2 both use ContributorsStrip.
    const strips = screen.getAllByTestId("contributors-strip-mock");
    expect(strips).toHaveLength(2);

    // WHY one RecentActivityStrip mock: Cell 3 uses RecentActivityStrip exclusively.
    const activityStrip = screen.getByTestId("recent-activity-strip-mock");
    expect(activityStrip).toBeDefined();
  });
});

describe("BottomStripCluster passes contributors to first ContributorsStrip", () => {
  it("Cell 1 receives the full contributors array and empty detractors", () => {
    render(
      <BottomStripCluster
        portfolioId={PORTFOLIO_ID}
        contributors={CONTRIBUTORS}
        detractors={DETRACTORS}
      />,
    );

    // WHY check first call: React renders JSX children in document order (top→down).
    // Cell 1 (contributors) is always the first ContributorsStrip call.
    const firstCall = mockContributorsStripCalls[0];
    expect(firstCall).toBeDefined();

    // WHY check contributorsCount === CONTRIBUTORS.length: verifies the full
    // array was forwarded, not a slice or an empty array.
    expect(firstCall.contributorsCount).toBe(CONTRIBUTORS.length);

    // WHY check detractorsCount === 0: Cell 1 must pass detractors=[] to
    // ContributorsStrip so the detractors section renders only dash rows
    // (keeping the column as a contributors-only panel).
    expect(firstCall.detractorsCount).toBe(0);

    // WHY also check the DOM attribute: confirms the mock received the value
    // and serialised it correctly — a two-layer assertion that catches both
    // call-site forwarding AND mock rendering.
    const strips = screen.getAllByTestId("contributors-strip-mock");
    expect(strips[0].getAttribute("data-contributors")).toBe(
      String(CONTRIBUTORS.length),
    );
    expect(strips[0].getAttribute("data-detractors")).toBe("0");
  });
});

describe("BottomStripCluster passes detractors to second ContributorsStrip", () => {
  it("Cell 2 receives the full detractors array and empty contributors", () => {
    render(
      <BottomStripCluster
        portfolioId={PORTFOLIO_ID}
        contributors={CONTRIBUTORS}
        detractors={DETRACTORS}
      />,
    );

    // WHY check second call: Cell 2 (detractors) is the second ContributorsStrip
    // rendered in JSX order — index 1 in the call log.
    const secondCall = mockContributorsStripCalls[1];
    expect(secondCall).toBeDefined();

    // WHY check detractorsCount === DETRACTORS.length: verifies the full array
    // was forwarded to Cell 2, not an empty array or the contributors array.
    expect(secondCall.detractorsCount).toBe(DETRACTORS.length);

    // WHY check contributorsCount === 0: Cell 2 must pass contributors=[] so
    // the contributors section renders only dash rows.
    expect(secondCall.contributorsCount).toBe(0);

    // DOM attribute cross-check.
    const strips = screen.getAllByTestId("contributors-strip-mock");
    expect(strips[1].getAttribute("data-detractors")).toBe(
      String(DETRACTORS.length),
    );
    expect(strips[1].getAttribute("data-contributors")).toBe("0");
  });

  it("forwards portfolioId to RecentActivityStrip", () => {
    render(
      <BottomStripCluster
        portfolioId={PORTFOLIO_ID}
        contributors={CONTRIBUTORS}
        detractors={DETRACTORS}
      />,
    );

    // WHY check the portfolioId attribute: RecentActivityStrip uses portfolioId
    // to fire its TanStack Query. If the prop is dropped, the strip shows "No
    // recent activity" permanently — a silent data regression.
    const activityStrip = screen.getByTestId("recent-activity-strip-mock");
    expect(activityStrip.getAttribute("data-portfolio-id")).toBe(PORTFOLIO_ID);
  });
});

describe("BottomStripCluster handles empty mover arrays", () => {
  it("renders without throwing when contributors and detractors are both empty", () => {
    // WHY this edge case: a new portfolio with no holdings produces empty arrays
    // from useTopMovers. BottomStripCluster must not throw or render differently
    // — ContributorsStrip handles the empty-array dash-row rendering internally.
    render(
      <BottomStripCluster
        portfolioId={PORTFOLIO_ID}
        contributors={[]}
        detractors={[]}
      />,
    );

    const cluster = screen.getByTestId("bottom-strip-cluster");
    expect(cluster).toBeDefined();

    const firstCall = mockContributorsStripCalls[0];
    const secondCall = mockContributorsStripCalls[1];
    expect(firstCall.contributorsCount).toBe(0);
    expect(secondCall.detractorsCount).toBe(0);
  });
});
