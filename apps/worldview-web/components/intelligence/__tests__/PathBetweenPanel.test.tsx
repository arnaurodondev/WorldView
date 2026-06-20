/**
 * components/intelligence/__tests__/PathBetweenPanel.test.tsx (PLAN-0112 T-5-03)
 *
 * Pins the pairwise panel's load-bearing states:
 *  1. Initial prompt before two entities are chosen.
 *  2. After choosing source + target (via the picker), a CONNECTED response
 *     renders the verdict + ranked path + sub-scores.
 *  3. A DISCONNECTED response renders the clean "no meaningful connection" state.
 *
 * STRATEGY: we mock useApiClient().searchFundamentals so the picker returns a
 * single deterministic candidate, and mock usePathBetween so the result body is
 * driven by the test (not a real network call). We drive the picker by typing
 * and clicking the candidate; the 300ms debounce elapses under REAL timers.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const searchFundamentals = vi.fn();

vi.mock("@/lib/api-client", () => ({
  useApiClient: () => ({ searchFundamentals }),
  useAccessToken: () => "test-token",
}));

vi.mock("@/lib/api/intelligence", () => ({
  usePathBetween: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

// WHY mock AlertWizard (PLAN-0113 W5): once both endpoints are chosen the panel
// mounts the wizard, which pulls the authed mutation hooks (require
// <ApiClientProvider>, absent here). The wizard has its own tests; this panel test
// only needs to confirm the wizard is invoked with the right KG_CONNECTION prefill.
const alertWizardSpy = vi.fn();
vi.mock("@/components/alerts/AlertWizard", () => ({
  AlertWizard: (props: Record<string, unknown>) => {
    alertWizardSpy(props);
    return <div data-testid="kg-alert-wizard" data-open={String(props.open)} />;
  },
}));

import { usePathBetween } from "@/lib/api/intelligence";
import { PathBetweenPanel } from "@/components/intelligence/PathBetweenPanel";

const mockUsePathBetween = vi.mocked(usePathBetween);

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Type into a picker input and click the returned candidate.
 *  WHY real timers (no fake timers): React Testing Library's async findBy/waitFor
 *  poll on real timers; faking timers freezes that polling and deadlocks. The
 *  picker's 300ms debounce is short enough that findByText's 1s default covers it. */
async function chooseEntity(label: string, ticker: string, queryText = "ap") {
  const input = screen.getByLabelText(`${label} entity search`);
  fireEvent.change(input, { target: { value: queryText } });
  // The candidate button shows the ticker (e.g. "AAPL"). WHY target the ticker
  // (not the name): the entity NAME also appears in already-selected chips and in
  // rendered path pills, which would collide; the ticker only appears in the live
  // dropdown candidate. Allow a generous window for the 300ms debounce.
  const candidate = await screen.findByText(ticker, undefined, { timeout: 2000 });
  fireEvent.click(candidate);
}

beforeEach(() => {
  searchFundamentals.mockReset();
  alertWizardSpy.mockReset();
  mockUsePathBetween.mockReset();
  // Default: idle (pending) until both endpoints are chosen.
  mockUsePathBetween.mockReturnValue({
    data: undefined,
    isFetching: false,
    isError: false,
  } as never);
  // Picker returns one candidate per source/target. The text differs so the two
  // pickers' results are distinguishable in the DOM.
  searchFundamentals.mockImplementation(async () => ({
    results: [
      {
        instrument_id: "i1",
        entity_id: "ent-src",
        ticker: "AAPL",
        name: "Apple Inc.",
        exchange: "NASDAQ",
        type: "equity",
      },
    ],
    query: "ap",
  }));
});

describe("PathBetweenPanel", () => {
  it("shows the initial prompt before two entities are chosen", () => {
    render(
      <Wrapper>
        <PathBetweenPanel />
      </Wrapper>,
    );
    expect(
      screen.getByText("Pick two entities to see how they are connected"),
    ).toBeDefined();
  });

  it("renders the connected verdict + ranked path after choosing both", async () => {
    mockUsePathBetween.mockReturnValue({
      data: {
        source_entity_id: "ent-src",
        target_entity_id: "ent-src",
        connected: true,
        shortest_hops: 2,
        paths: [
          {
            path_nodes: [
              { entity_id: "ent-src", name: "Apple Inc.", entity_type: "company" },
              { entity_id: "mid", name: "TSMC", entity_type: "company" },
            ],
            path_edges: [{ relation_type: "SUPPLIER_OF", confidence: 0.7 }],
            hop_count: 2,
            reliability: 0.6,
            unexpectedness: 0.8,
            semantic_distance: 0.5,
            novelty: 0.1,
            weirdness: 0.55,
          },
        ],
        computed_at: "2026-06-12T00:00:00Z",
      },
      isFetching: false,
      isError: false,
    } as never);

    render(
      <Wrapper>
        <PathBetweenPanel />
      </Wrapper>,
    );

    await chooseEntity("Source", "AAPL");
    await chooseEntity("Target", "AAPL");

    await waitFor(() => expect(screen.getByText(/Connected/)).toBeDefined());
    // Headline weirdness % (0.55 → 55%) and the sub-score labels render.
    expect(screen.getByText("55%")).toBeDefined();
    expect(screen.getByText("REL")).toBeDefined();
  });

  it("exposes a ＋ Alert entry point pre-scoped to KG_CONNECTION once both chosen", async () => {
    // Distinct candidates keyed off the typed query so source_entity_id ≠
    // target_entity_id regardless of how many times each picker refetches.
    searchFundamentals.mockImplementation(async (q: string) =>
      q === "an"
        ? {
            results: [
              { instrument_id: "i2", entity_id: "ent-tgt", ticker: "ANTH", name: "Anthropic", exchange: "PRIV", type: "equity" },
            ],
            query: q,
          }
        : {
            results: [
              { instrument_id: "i1", entity_id: "ent-src", ticker: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", type: "equity" },
            ],
            query: q,
          },
    );

    render(
      <Wrapper>
        <PathBetweenPanel />
      </Wrapper>,
    );

    // No button before both endpoints exist.
    expect(screen.queryByTestId("kg-connection-alert-button")).toBeNull();

    await chooseEntity("Source", "AAPL", "ap");
    await chooseEntity("Target", "ANTH", "an");

    // Button appears, click it → wizard opens pre-scoped + both entities seeded.
    const btn = await screen.findByTestId("kg-connection-alert-button");
    fireEvent.click(btn);

    await waitFor(() => {
      const lastCall = alertWizardSpy.mock.calls.at(-1)?.[0];
      expect(lastCall?.open).toBe(true);
      expect(lastCall?.initialRuleType).toBe("KG_CONNECTION");
      expect(lastCall?.prefillCondition).toMatchObject({
        source_entity_id: "ent-src",
        target_entity_id: "ent-tgt",
      });
      expect(lastCall?.prefillNames).toMatchObject({
        "ent-src": "Apple Inc.",
        "ent-tgt": "Anthropic",
      });
    });
  });

  it("renders the no-connection empty state when connected=false", async () => {
    mockUsePathBetween.mockReturnValue({
      data: {
        source_entity_id: "ent-src",
        target_entity_id: "ent-src",
        connected: false,
        shortest_hops: null,
        paths: [],
        computed_at: "2026-06-12T00:00:00Z",
      },
      isFetching: false,
      isError: false,
    } as never);

    render(
      <Wrapper>
        <PathBetweenPanel />
      </Wrapper>,
    );

    await chooseEntity("Source", "AAPL");
    await chooseEntity("Target", "AAPL");

    await waitFor(() =>
      expect(screen.getByText("No meaningful connection found")).toBeDefined(),
    );
  });
});
