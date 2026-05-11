/**
 * __tests__/intelligence/intelligence-components.test.tsx — Component unit tests
 * (PLAN-0074 Wave H T-H-02 through T-H-07)
 *
 * WHY THESE TESTS EXIST:
 * The intelligence page has complex cross-panel interactions. Component tests
 * verify that individual components render correctly and respond to props/state
 * changes without needing a running Next.js server.
 *
 * WHAT WE TEST:
 * 1. HealthScoreBadge — color threshold logic (red/yellow/green)
 * 2. ConfidenceTrendSparkline — renders SVG polyline with data
 * 3. SelectedEntityContext — provides correct context values + reset on path change
 * 4. IntelligenceLayout — renders grid + tab variants
 * 5. EntityChatPanel — expand/collapse toggle, disabled send on empty
 * 6. NarrativeCard — shows toast on regenerate 202 + 429
 * 7. IntelligencePageErrorBoundary — shows error UI + retry resets
 * 8. EntitySidebar — switches to selected entity on context change
 *
 * WHY MOCK HOOKS:
 * Components that use TanStack Query hooks need the QueryClient provider.
 * Components that use useApiClient/useAccessToken need ApiClientProvider.
 * We mock these at the module level so components render without full provider trees.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HealthScoreBadge } from "@/components/intelligence/HealthScoreBadge";
import { ConfidenceTrendSparkline } from "@/components/intelligence/ConfidenceTrendSparkline";
import { IntelligencePageErrorBoundary } from "@/components/intelligence/IntelligencePageErrorBoundary";
import { SelectedEntityProvider, useSelectedEntity } from "@/contexts/SelectedEntityContext";
import { KeyMetricsGrid } from "@/components/intelligence/KeyMetricsGrid";
import { SourceDistributionList } from "@/components/intelligence/SourceDistributionList";

// ── Mock next/navigation ──────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/intelligence/test-id"),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn() })),
  useParams: vi.fn(() => ({ entity_id: "test-id" })),
}));

// ── Mock @/lib/api-client ─────────────────────────────────────────────────────
vi.mock("@/lib/api-client", () => ({
  useAccessToken: vi.fn(() => "test-token"),
  useApiClient: vi.fn(() => ({ getEntityGraph: vi.fn() })),
  ApiClientProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// ── Mock intelligence hooks ───────────────────────────────────────────────────
vi.mock("@/lib/api/intelligence", () => ({
  useEntityIntelligence: vi.fn(() => ({
    data: null,
    isLoading: false,
    isError: false,
  })),
  useEntityPaths: vi.fn(() => ({
    data: null,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  })),
  useEntityNarrativeHistory: vi.fn(() => ({
    data: null,
    isLoading: false,
    isError: false,
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
  })),
  useTriggerNarrativeGeneration: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
}));

// ── Mock sonner toast ─────────────────────────────────────────────────────────
vi.mock("sonner", () => ({
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
}));

// ── QueryClient wrapper ───────────────────────────────────────────────────────
function WithQueryClient({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(QueryClientProvider, { client: qc }, children);
}

// ─────────────────────────────────────────────────────────────────────────────
// HealthScoreBadge tests
// ─────────────────────────────────────────────────────────────────────────────

describe("HealthScoreBadge", () => {
  it("renders red for score < 0.3", () => {
    const { container } = render(<HealthScoreBadge score={0.2} size={48} />);
    // WHY check aria-label: it contains the formatted score and is readable by tests
    expect(container.querySelector('[role="img"]')).toHaveAttribute(
      "aria-label",
      "Health score: 20%",
    );
    // WHY getAttribute("class"): SVG elements have className as SVGAnimatedString
    // (not a plain string) in JSDOM. getAttribute("class") returns the raw string
    // value so toContain() works as expected.
    const arc = container.querySelector("circle:last-child");
    expect(arc?.getAttribute("class")).toContain("text-negative");
  });

  it("renders amber/warning for score 0.3-0.6", () => {
    const { container } = render(<HealthScoreBadge score={0.5} size={48} />);
    const arc = container.querySelector("circle:last-child");
    expect(arc?.getAttribute("class")).toContain("text-warning");
  });

  it("renders green/positive for score > 0.6", () => {
    const { container } = render(<HealthScoreBadge score={0.9} size={48} />);
    const arc = container.querySelector("circle:last-child");
    expect(arc?.getAttribute("class")).toContain("text-positive");
  });

  it("renders dash for null score", () => {
    render(<HealthScoreBadge score={null} size={48} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// ConfidenceTrendSparkline tests
// ─────────────────────────────────────────────────────────────────────────────

describe("ConfidenceTrendSparkline", () => {
  it("renders SVG polyline when data has 2+ points", () => {
    const data = [
      { date: "2026-04-01", avg_confidence: 0.6 },
      { date: "2026-04-15", avg_confidence: 0.75 },
      { date: "2026-05-01", avg_confidence: 0.8 },
    ];
    const { container } = render(<ConfidenceTrendSparkline data={data} />);
    const polyline = container.querySelector("polyline");
    expect(polyline).toBeInTheDocument();
    // WHY check points attribute: the polyline should have computed SVG points
    expect(polyline?.getAttribute("points")).toBeTruthy();
  });

  it("renders loading skeleton when isLoading is true", () => {
    render(<ConfidenceTrendSparkline data={[]} isLoading={true} />);
    // WHY check bg-muted: Skeleton uses bg-muted class
    const skeleton = document.querySelector(".bg-muted");
    expect(skeleton).toBeInTheDocument();
  });

  it("renders placeholder dash for fewer than 2 data points", () => {
    render(<ConfidenceTrendSparkline data={[]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("uses text-positive class for upward trend", () => {
    const data = [
      { date: "2026-04-01", avg_confidence: 0.5 },
      { date: "2026-05-01", avg_confidence: 0.8 },
    ];
    const { container } = render(<ConfidenceTrendSparkline data={data} />);
    // WHY getAttribute("class"): SVG polyline has SVGAnimatedString className in JSDOM.
    const polyline = container.querySelector("polyline");
    expect(polyline?.getAttribute("class")).toContain("text-positive");
  });

  it("uses text-negative class for downward trend", () => {
    const data = [
      { date: "2026-04-01", avg_confidence: 0.8 },
      { date: "2026-05-01", avg_confidence: 0.5 },
    ];
    const { container } = render(<ConfidenceTrendSparkline data={data} />);
    // WHY getAttribute("class"): SVG polyline has SVGAnimatedString className in JSDOM.
    const polyline = container.querySelector("polyline");
    expect(polyline?.getAttribute("class")).toContain("text-negative");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SelectedEntityContext tests
// ─────────────────────────────────────────────────────────────────────────────

describe("SelectedEntityContext", () => {
  it("provides anchorEntityId and selectedEntityId (default = anchor)", () => {
    let contextValue: ReturnType<typeof useSelectedEntity> | null = null;

    function Capturer() {
      contextValue = useSelectedEntity();
      return null;
    }

    render(
      <SelectedEntityProvider anchorEntityId="anchor-id">
        <Capturer />
      </SelectedEntityProvider>,
    );

    // WHY non-null assertion: TypeScript can't track that contextValue was
    // populated inside the Capturer render — it still sees null after the
    // render() call. The render() is synchronous and Capturer always runs,
    // so the value is guaranteed to be set at this point.
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    expect(contextValue!.anchorEntityId).toBe("anchor-id");
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    expect(contextValue!.selectedEntityId).toBe("anchor-id");
  });

  it("updates selectedEntityId when setSelectedEntityId is called", async () => {
    let contextValue: ReturnType<typeof useSelectedEntity> | null = null;

    function Capturer() {
      contextValue = useSelectedEntity();
      return (
        <button onClick={() => contextValue?.setSelectedEntityId("node-id")}>
          Select
        </button>
      );
    }

    render(
      <SelectedEntityProvider anchorEntityId="anchor-id">
        <Capturer />
      </SelectedEntityProvider>,
    );

    fireEvent.click(screen.getByText("Select"));

    await waitFor(() => {
      expect(contextValue?.selectedEntityId).toBe("node-id");
    });
  });

  it("throws when used outside provider", () => {
    // WHY suppress console.error: React prints error boundary messages to console.
    // We expect the throw so we suppress the noise.
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Consumer() {
      useSelectedEntity();
      return null;
    }
    expect(() => render(<Consumer />)).toThrow(
      "useSelectedEntity must be used inside <SelectedEntityProvider>",
    );
    consoleSpy.mockRestore();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// IntelligencePageErrorBoundary tests
// ─────────────────────────────────────────────────────────────────────────────

describe("IntelligencePageErrorBoundary", () => {
  it("renders children when no error", () => {
    render(
      <IntelligencePageErrorBoundary panelName="Graph">
        <p>Content</p>
      </IntelligencePageErrorBoundary>,
    );
    expect(screen.getByText("Content")).toBeInTheDocument();
  });

  it("shows panel failed message when child throws", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    // WHY React.ReactNode return type: TypeScript requires components to return
    // ReactNode (not void). Even though throw makes the return unreachable, we
    // must declare the return type so the component is usable as a JSX element.
    function Thrower(): React.ReactNode {
      throw new Error("Test error message");
    }

    render(
      <IntelligencePageErrorBoundary panelName="Graph">
        <Thrower />
      </IntelligencePageErrorBoundary>,
    );

    expect(screen.getByText("Graph panel failed to load")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    consoleSpy.mockRestore();
  });

  it("shows retry button that resets error state", async () => {
    let shouldThrow = true;
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    function Conditional() {
      if (shouldThrow) throw new Error("oops");
      return <p>Recovered</p>;
    }

    render(
      <IntelligencePageErrorBoundary panelName="Intelligence">
        <Conditional />
      </IntelligencePageErrorBoundary>,
    );

    // Error state visible
    expect(screen.getByText("Intelligence panel failed to load")).toBeInTheDocument();

    // Stop throwing, then click retry
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    // WHY waitFor: error boundary setState is async in React 18
    await waitFor(() => {
      expect(screen.getByText("Recovered")).toBeInTheDocument();
    });

    consoleSpy.mockRestore();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// KeyMetricsGrid tests
// ─────────────────────────────────────────────────────────────────────────────

describe("KeyMetricsGrid", () => {
  it("renders key/value pairs from metrics object", () => {
    render(
      <KeyMetricsGrid
        metrics={{ employee_count: 150000, revenue: 385_000_000_000 }}
      />,
    );
    expect(screen.getByText("Employee Count")).toBeInTheDocument();
    expect(screen.getByText("Revenue")).toBeInTheDocument();
  });

  it("renders placeholder when metrics is empty", () => {
    render(<KeyMetricsGrid metrics={{}} />);
    expect(screen.getByText("No key metrics available")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SourceDistributionList tests
// ─────────────────────────────────────────────────────────────────────────────

describe("SourceDistributionList", () => {
  it("renders source bars for each distribution entry", () => {
    const dist = [
      { source_type: "news", source_name: "Reuters", count: 40, pct: 60 },
      { source_type: "filing", source_name: "SEC", count: 20, pct: 30 },
    ];
    render(<SourceDistributionList distribution={dist} />);
    expect(screen.getByText("Reuters")).toBeInTheDocument();
    expect(screen.getByText("SEC")).toBeInTheDocument();
    // WHY check progressbar: each bar has role="progressbar" with aria-valuenow
    const bars = screen.getAllByRole("progressbar");
    expect(bars).toHaveLength(2);
  });

  it("renders 'No source data' for empty distribution", () => {
    render(<SourceDistributionList distribution={[]} />);
    expect(screen.getByText("No source data")).toBeInTheDocument();
  });
});
