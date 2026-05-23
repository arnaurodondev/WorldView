/**
 * components/instrument/intelligence/__tests__/ArticleImpactDrawer.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0091 C-2):
 * ArticleImpactDrawer has four distinct render states — loading, data, error,
 * and the trigger bar itself. Without tests, regressions in any of these states
 * (e.g. loading skeletons not rendering, error message wrong, window values
 * missing) are invisible until a browser QA session. These tests pin the four
 * states so CI catches regressions immediately.
 *
 * TEST STRATEGY:
 * Mock `useAuthedQuery` at the module level so we can control what state the
 * hook returns in each test. This avoids needing a real QueryClient, MSW,
 * ApiClientProvider, or network layer — ArticleImpactDrawer is pure presentation
 * above the hook boundary.
 *
 * WHY mock useAuthedQuery (not useQuery):
 * ArticleImpactDrawer calls useAuthedQuery from @/lib/api-client. Mocking the
 * specific hook it uses ensures we test the component's rendering logic, not
 * the hook's auth-gating logic (which has its own tests in api-client.test.tsx).
 *
 * WHY we need a QueryClientProvider even with a mocked query:
 * shadcn's Popover uses Radix portals which require a stable React tree. The
 * QueryClientProvider is technically not needed when the hook is mocked, but
 * the Popover's portal may try to access React context during testing.
 * We include it for a complete render tree.
 *
 * WHY fireEvent.click on the trigger (not userEvent.click):
 * Vitest's jsdom doesn't run Radix portal animations. userEvent.click is async
 * and more realistic but adds complexity when all we need is that the click
 * fires and the popover content appears. fireEvent.click is synchronous and
 * sufficient for these unit-level tests.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { ArticleImpactHistoryResponse } from "@/types/api";

// ── Mock useAuthedQuery before the component is imported ──────────────────────
// WHY: ArticleImpactDrawer calls useAuthedQuery inside its render. Vitest hoists
// vi.mock() calls before any imports, so the component will import the mocked
// version when it resolves @/lib/api-client.
vi.mock("@/lib/api-client", () => ({
  useAuthedQuery: vi.fn(),
}));

// Import AFTER the mocks are set up — Vitest hoists vi.mock so this gets the
// mocked version, not the real useAuthedQuery.
// eslint-disable-next-line import/first
import { ArticleImpactDrawer } from "@/components/instrument/intelligence/ArticleImpactDrawer";
// eslint-disable-next-line import/first
import { useAuthedQuery } from "@/lib/api-client";

// ── Typed mock reference ──────────────────────────────────────────────────────
// WHY cast: vi.mock replaces the export with a vi.fn(), but TypeScript still
// thinks it's the original function signature. The cast unlocks mockReturnValue.
const mockUseAuthedQuery = useAuthedQuery as ReturnType<typeof vi.fn>;

// ── Test utilities ────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/**
 * makeQueryResult — builds a minimal UseQueryResult-compatible mock.
 *
 * WHY a factory (not a plain object): UseQueryResult has many fields. The factory
 * provides safe defaults (false for all booleans, undefined for all data) and
 * accepts overrides so each test only specifies what it cares about.
 */
function makeQueryResult(
  overrides: Partial<UseQueryResult<ArticleImpactHistoryResponse | null>>,
): UseQueryResult<ArticleImpactHistoryResponse | null> {
  return {
    data: undefined,
    dataUpdatedAt: 0,
    error: null,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    fetchStatus: "idle",
    isError: false,
    isFetched: false,
    isFetchedAfterMount: false,
    isFetching: false,
    isLoading: false,
    isLoadingError: false,
    isPaused: false,
    isPending: false,
    isPlaceholderData: false,
    isRefetchError: false,
    isRefetching: false,
    isStale: false,
    isSuccess: false,
    isInitialLoading: false,
    refetch: vi.fn(),
    status: "pending",
    ...overrides,
  } as UseQueryResult<ArticleImpactHistoryResponse | null>;
}

// ── Fixtures ──────────────────────────────────────────────────────────────────

const MOCK_IMPACT_DATA: ArticleImpactHistoryResponse = {
  article_id: "art-001",
  impact_windows: {
    day_t0: 0.012,   // +1.20%
    day_t1: -0.008,  // -0.80%
    day_t2: 0.003,   // +0.30%
    day_t5: null,    // not yet computed
  },
};

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockUseAuthedQuery.mockReset();
});

describe("ArticleImpactDrawer", () => {
  it("renders the 4-segment impact bar as the trigger", () => {
    // WHY idle state (not loading): we want to test the trigger bar itself,
    // which is always visible regardless of query state. We use idle so the
    // popover content doesn't distract from the trigger assertion.
    mockUseAuthedQuery.mockReturnValue(
      makeQueryResult({ isLoading: false, isError: false }),
    );

    render(
      <Wrapper>
        <ArticleImpactDrawer articleId="art-001" />
      </Wrapper>,
    );

    // The trigger button wraps an aria-labeled "price impact bar".
    // WHY getByLabelText: the impact bar has aria-label="price impact bar" so
    // screen readers announce it correctly. This assertion pins that contract.
    const bar = screen.getByLabelText("price impact bar");
    expect(bar).toBeDefined();

    // The bar must have exactly 4 child segments (one per window).
    // WHY children.length: Popover renders the trigger in a Portal; the bar's
    // 4 child divs are the stable DOM contract we care about here.
    expect(bar.children.length).toBe(4);
  });

  it("opens popover and shows 4 window rows when data is available", () => {
    mockUseAuthedQuery.mockReturnValue(
      makeQueryResult({
        isLoading: false,
        isError: false,
        isSuccess: true,
        data: MOCK_IMPACT_DATA,
      }),
    );

    render(
      <Wrapper>
        <ArticleImpactDrawer articleId="art-001" />
      </Wrapper>,
    );

    // Click the trigger button to open the popover.
    const triggerBtn = screen.getByRole("button", { name: /price impact/i });
    fireEvent.click(triggerBtn);

    // All four window labels must be visible in the open popover.
    expect(screen.getByText("SAME DAY")).toBeDefined();
    expect(screen.getByText("+1 DAY")).toBeDefined();
    expect(screen.getByText("+2 DAYS")).toBeDefined();
    expect(screen.getByText("+5 DAYS")).toBeDefined();

    // The header label must be visible.
    expect(screen.getByText("PRICE IMPACT")).toBeDefined();
  });

  it("shows skeleton rows when loading", () => {
    mockUseAuthedQuery.mockReturnValue(
      makeQueryResult({ isLoading: true, isPending: true }),
    );

    render(
      <Wrapper>
        <ArticleImpactDrawer articleId="art-001" />
      </Wrapper>,
    );

    // Open the popover to see its content.
    const triggerBtn = screen.getByRole("button", { name: /price impact/i });
    fireEvent.click(triggerBtn);

    // WHY query [aria-busy="true"]: the loading state sets aria-busy on the
    // container div, which is both a semantic signal and a stable test handle.
    const loadingContainer = document.querySelector('[aria-busy="true"]');
    expect(loadingContainer).toBeDefined();

    // The loading container must have 4 skeleton children (one per window).
    expect(loadingContainer?.children.length).toBe(4);
  });

  it('shows "Impact data unavailable" on error', () => {
    mockUseAuthedQuery.mockReturnValue(
      makeQueryResult({
        isError: true,
        error: new Error("network error"),
        status: "error",
      }),
    );

    render(
      <Wrapper>
        <ArticleImpactDrawer articleId="art-001" />
      </Wrapper>,
    );

    // Open the popover to see the error state.
    const triggerBtn = screen.getByRole("button", { name: /price impact/i });
    fireEvent.click(triggerBtn);

    // WHY exact text: the spec mandates this exact copy. If the message changes,
    // the test fails, prompting a deliberate decision to update it.
    expect(screen.getByText("Impact data unavailable")).toBeDefined();
  });
});
