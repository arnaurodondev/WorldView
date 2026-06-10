/**
 * features/chat/components/__tests__/ChatContextRail.test.tsx
 *
 * Unit tests for ChatContextRail.
 *
 * WHAT THESE GUARD:
 *   1. Citation deduplication — same article_id across two messages → 1 row.
 *   2. Top-4 cap — 6 unique citations → only 4 rendered.
 *   3. Relevance sort — highest-score citation renders first.
 *   4. Contradiction extraction — ⚠ prefix in message content → warning chip.
 *   5. Related tickers extraction — $AAPL in content → ticker chip rendered.
 *   6. onTickerClick callback — clicking a ticker chip fires the callback.
 *   7. onClose callback — clicking × fires onClose.
 *   8. Entity section visibility — rendered only when entityId is non-null.
 *
 * WHY mock useAuth and useQuery:
 * EntityCard fires a TanStack useQuery that needs a real QueryClientProvider.
 * Rather than mounting the full provider, we mock the hooks so the unit tests
 * are fast and deterministic. Integration tests covering the full query
 * lifecycle belong in the Playwright E2E suite.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ── Mock TanStack Query ───────────────────────────────────────────────────────
// WHY top-level mock: the EntityCard inside ChatContextRail calls useQuery.
// Without a provider or mock, the hook throws. We mock the module so useQuery
// returns an idle (no-data, not-loading) state for all calls in this suite.
vi.mock("@tanstack/react-query", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-query")>(
    "@tanstack/react-query",
  );
  return {
    ...actual,
    useQuery: vi.fn().mockReturnValue({ data: undefined, isLoading: false }),
  };
});

// ── Mock useAuth ──────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

// ── Mock gateway (not called in these tests but import side-effects require it)
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getCompanyOverview: vi.fn(),
  })),
}));

import { ChatContextRail } from "../ChatContextRail";
import type { Message } from "@/types/api";
// WHY import useQuery here: the module is mocked above; importing the mocked
// binding lets the Round-2 mini-card tests override its return value with
// resolved overview data (vi.mocked(useQuery).mockReturnValue(...)).
import { useQuery } from "@tanstack/react-query";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeMessage(
  overrides: Partial<Message> & { content: string },
): Message {
  return {
    message_id: crypto.randomUUID(),
    thread_id: "thread-1",
    role: "assistant",
    created_at: new Date().toISOString(),
    citations: [],
    ...overrides,
  };
}

const DEFAULT_PROPS = {
  entityId: null,
  messages: [],
  isCollapsed: false,
  onClose: vi.fn(),
  onTickerClick: vi.fn(),
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ChatContextRail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Render shell ──────────────────────────────────────────────────────────

  it("renders the header with CONTEXT label", () => {
    render(<ChatContextRail {...DEFAULT_PROPS} />);
    // WHY uppercase regex: the label is rendered uppercase via CSS class but
    // the DOM text node is lowercase. The regex covers both without depending
    // on a specific CSS transform behaviour in the test environment.
    expect(screen.getByText(/context/i)).toBeInTheDocument();
  });

  it("fires onClose when × is clicked", () => {
    const onClose = vi.fn();
    render(<ChatContextRail {...DEFAULT_PROPS} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText("Close context rail"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  // ── Entity section ────────────────────────────────────────────────────────

  it("does NOT render Entity section header when entityId is null", () => {
    render(<ChatContextRail {...DEFAULT_PROPS} entityId={null} />);
    // The "ENTITY" section header is only present when entityId is set.
    // WHY case-insensitive: CSS text-transform is applied via class, the DOM
    // may expose the raw string in either case depending on jsdom config.
    expect(screen.queryByText(/entity/i)).not.toBeInTheDocument();
  });

  it("renders Entity section header when entityId is provided", () => {
    render(
      <ChatContextRail
        {...DEFAULT_PROPS}
        entityId="2c8e3a7f-0001-0001-0001-000000000001"
      />,
    );
    expect(screen.getByText(/entity/i)).toBeInTheDocument();
  });

  // ── Citations ─────────────────────────────────────────────────────────────

  it("shows 'No sources cited yet.' when messages have no citations", () => {
    const messages = [
      makeMessage({ content: "Hello world", citations: [] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    expect(screen.getByText(/no sources cited yet/i)).toBeInTheDocument();
  });

  it("deduplicates citations with the same article_id", () => {
    // WHY two messages with the same citation: this simulates the assistant
    // referencing the same 10-Q in two different turns. The rail should show
    // it once, not twice.
    const sharedCitation = {
      article_id: "art-001",
      title: "AAPL 10-Q Q2 2026",
      url: "https://sec.gov/...",
      source: "sec",
      relevance_score: 0.95,
    };
    const messages = [
      makeMessage({ content: "First", citations: [sharedCitation] }),
      makeMessage({ content: "Second", citations: [sharedCitation] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // Only one instance of the title should appear.
    const titles = screen.getAllByText("AAPL 10-Q Q2 2026");
    expect(titles).toHaveLength(1);
  });

  it("caps citations at 4 even when more unique ones exist", () => {
    const messages = [
      makeMessage({
        content: "Source dump",
        citations: [1, 2, 3, 4, 5, 6].map((i) => ({
          article_id: `art-${i}`,
          title: `Article ${i}`,
          url: `https://example.com/${i}`,
          source: "news",
          relevance_score: i / 10,
        })),
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // Only 4 [N] index markers should appear (rendered as "[1]", "[2]", …).
    const indices = ["[1]", "[2]", "[3]", "[4]"];
    for (const idx of indices) {
      expect(screen.getByText(idx)).toBeInTheDocument();
    }
    // "[5]" and "[6]" must not exist.
    expect(screen.queryByText("[5]")).not.toBeInTheDocument();
    expect(screen.queryByText("[6]")).not.toBeInTheDocument();
  });

  it("sorts citations by relevance_score descending", () => {
    // WHY: highest-confidence source must appear at position [1].
    const messages = [
      makeMessage({
        content: "Multi-source",
        citations: [
          {
            article_id: "low",
            title: "Low confidence source",
            url: "",
            source: "news",
            relevance_score: 0.3,
          },
          {
            article_id: "high",
            title: "High confidence source",
            url: "",
            source: "sec",
            relevance_score: 0.95,
          },
        ],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    const items = screen.getAllByText(/\[(1|2)\]/);
    // "[1]" should be followed by "High confidence source".
    const firstIndex = items.find((el) => el.textContent === "[1]");
    // The "[1]" element is a sibling to the title within the same <a> ancestor.
    expect(firstIndex?.closest("a")?.textContent).toContain(
      "High confidence source",
    );
  });

  // ── Contradictions ────────────────────────────────────────────────────────

  it("does NOT render Contradictions section when no contradictions found", () => {
    const messages = [makeMessage({ content: "All looks consistent." })];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // Section header only appears when contradictions > 0.
    expect(screen.queryByText(/contradictions/i)).not.toBeInTheDocument();
  });

  it("renders Contradictions section when message content matches pattern", () => {
    const messages = [
      makeMessage({
        content:
          "⚠ FX impact reported as 60bp in Q1 vs 80-120bp range in Q2 guidance",
        citations: [],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    expect(screen.getByText(/contradictions/i)).toBeInTheDocument();
    // The extracted snippet should appear somewhere in the DOM.
    expect(
      screen.getByText(/FX impact reported as 60bp/i),
    ).toBeInTheDocument();
  });

  // ── Related tickers ───────────────────────────────────────────────────────

  it("does NOT render Related Tickers section when no $TICKER patterns found", () => {
    const messages = [
      makeMessage({ content: "No tickers here, just plain text." }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    expect(screen.queryByText(/related tickers/i)).not.toBeInTheDocument();
  });

  it("renders ticker chips for $TICKER mentions in messages", () => {
    const messages = [
      makeMessage({ content: "Comparing $AAPL and $NVDA performance.", citations: [] }),
      makeMessage({ role: "user", content: "What about $TSM?", citations: [] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    expect(screen.getByText(/related tickers/i)).toBeInTheDocument();
    // WHY getByText with $ prefix: the chip renders "$AAPL", not "AAPL".
    expect(screen.getByText("$AAPL")).toBeInTheDocument();
    expect(screen.getByText("$NVDA")).toBeInTheDocument();
    expect(screen.getByText("$TSM")).toBeInTheDocument();
  });

  it("deduplicates ticker mentions across multiple messages", () => {
    const messages = [
      makeMessage({ content: "$AAPL is up.", citations: [] }),
      makeMessage({ content: "$AAPL is also relevant here.", citations: [] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    const chips = screen.getAllByText("$AAPL");
    expect(chips).toHaveLength(1);
  });

  it("fires onTickerClick with the ticker when a chip is clicked", () => {
    const onTickerClick = vi.fn();
    const messages = [
      makeMessage({ content: "$NVDA GPU dominance continues.", citations: [] }),
    ];
    render(
      <ChatContextRail
        {...DEFAULT_PROPS}
        messages={messages}
        onTickerClick={onTickerClick}
      />,
    );
    fireEvent.click(screen.getByText("$NVDA"));
    // WHY "NVDA" (without $): the component calls onTickerClick with the raw
    // ticker extracted by the regex (captures the group after $). The page
    // wraps it with " $" before appending to the composer.
    expect(onTickerClick).toHaveBeenCalledWith("NVDA");
  });

  // ── Bold markdown ticker extraction ──────────────────────────────────────
  // These tests guard the second extraction path added for Issue 1: assistant
  // messages that use **BOLD** formatting for entity names without a $ prefix.

  it("extracts **BOLD** uppercase words from assistant messages as tickers", () => {
    // WHY role:"assistant": bold extraction only applies to assistant messages.
    const messages = [
      makeMessage({
        role: "assistant",
        content: "Comparing **NVDA** and **AMD** performance year-to-date.",
        citations: [],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // Both bold tokens should appear as chips.
    expect(screen.getByText("$NVDA")).toBeInTheDocument();
    expect(screen.getByText("$AMD")).toBeInTheDocument();
  });

  it("does NOT extract **BOLD** uppercase words from user messages", () => {
    // WHY: user-typed bold is not a reliable ticker signal — analysts sometimes
    // bold words for emphasis without meaning a stock symbol.
    const messages = [
      makeMessage({
        role: "user",
        content: "I am **VERY** interested in comparing them.",
        citations: [],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // "VERY" is bold and all-caps but in a user message — should not appear.
    expect(screen.queryByText("$VERY")).not.toBeInTheDocument();
  });

  it("filters out common non-ticker bold abbreviations (CEO, GDP, etc.)", () => {
    // WHY: the allowlist prevents common financial abbreviations from
    // appearing as spurious chips in the Related Tickers section.
    const messages = [
      makeMessage({
        role: "assistant",
        content:
          "The **CEO** commented on **GDP** trends and **EPS** beats. **NVDA** led gains.",
        citations: [],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // CEO / GDP / EPS are in the NON_TICKER_BOLD allowlist — must be filtered out.
    expect(screen.queryByText("$CEO")).not.toBeInTheDocument();
    expect(screen.queryByText("$GDP")).not.toBeInTheDocument();
    expect(screen.queryByText("$EPS")).not.toBeInTheDocument();
    // NVDA is a real ticker — must appear.
    expect(screen.getByText("$NVDA")).toBeInTheDocument();
  });

  it("deduplicates when same ticker appears as both $TICKER and **BOLD**", () => {
    // WHY: both extraction paths feed the same Set — double-counting must not
    // happen even when the same entity appears via both patterns in one thread.
    const messages = [
      makeMessage({
        role: "user",
        content: "What about $NVDA?",
        citations: [],
      }),
      makeMessage({
        role: "assistant",
        content: "**NVDA** has strong momentum in AI infrastructure.",
        citations: [],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // Only one "$NVDA" chip should exist.
    const chips = screen.getAllByText("$NVDA");
    expect(chips).toHaveLength(1);
  });

  // ── Round 2: bare-token detection via the shared extractor ───────────────

  it("detects bare (un-prefixed, un-bolded) tickers in plain prose", () => {
    // WHY this matters: analysts type "compare NVDA with AMD", not "$NVDA".
    // The pre-Round-2 inline regex only caught $-prefixed and **bold** tokens,
    // so this everyday phrasing produced zero detections.
    const messages = [
      makeMessage({
        role: "user",
        content: "compare NVDA with AMD on margins",
        citations: [],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    expect(screen.getByText("$NVDA")).toBeInTheDocument();
    expect(screen.getByText("$AMD")).toBeInTheDocument();
  });

  it("blocklists noisy bare tokens (CEO, GDP) while keeping $-forced ones", () => {
    const messages = [
      makeMessage({
        role: "user",
        // "GDP" bare → blocked; "$GDP" explicit → counts ($ bypasses the list).
        content: "the CEO talked GDP — but track $GDP futures",
        citations: [],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    expect(screen.queryByText("$CEO")).not.toBeInTheDocument();
    // Exactly one GDP chip — from the $-prefixed mention.
    expect(screen.getAllByText("$GDP")).toHaveLength(1);
  });
});

// ── Round 2: Entity Overview mini-cards (resolved overview data) ─────────────
//
// These tests override the module-level useQuery mock with RESOLVED overview
// data so the mini-cards actually render their ticker / name / price / %chg /
// P/E / market-cap cells. Overriding inside this block (which runs after the
// suites above) cannot retro-affect the earlier tests — vi.clearAllMocks()
// in beforeEach clears call history but each test here re-arms the value it
// needs explicitly.

const MOCK_OVERVIEW = {
  instrument: {
    instrument_id: "inst-1",
    ticker: "AAPL",
    name: "Apple Inc.",
  },
  quote: { price: 189.84, change_pct: 1.23, volume: 52_000_000 },
  fundamentals: { pe_ratio: 29.4, market_cap: 2_900_000_000_000 },
};

describe("ChatContextRail — Entity Overview mini-cards (Round 2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // All useQuery calls in this block resolve to the same overview — fine
    // for assertions on card STRUCTURE (count, fields, click) where per-card
    // identity is irrelevant.
    vi.mocked(useQuery).mockReturnValue({
      data: MOCK_OVERVIEW,
      isLoading: false,
    } as unknown as ReturnType<typeof useQuery>);
  });

  it("renders a mini-card with ticker, name, price, %chg and P/E from overview data", () => {
    const messages = [
      makeMessage({ content: "What's going on with $AAPL?", citations: [] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // Section header (count badge renders separately).
    expect(screen.getByText(/entity overview/i)).toBeInTheDocument();
    const card = screen.getByTestId("entity-mini-card");
    // Resolved fields — ticker, company name, P/E ratio label, price digits.
    expect(card.textContent).toContain("AAPL");
    expect(card.textContent).toContain("Apple Inc.");
    expect(card.textContent).toContain("P/E");
    expect(card.textContent).toContain("189.84");
    // Positive change renders with an explicit "+" sign (colour-coding is a
    // CSS class — we assert the class hook rather than computed colour).
    expect(card.querySelector(".text-positive")).not.toBeNull();
  });

  it("caps mini-cards at 8 most recent tickers and shows the overflow count", () => {
    // 10 distinct $-tickers in one message → 8 cards + "+2 more mentioned".
    const tickers = ["AAPL", "NVDA", "AMD", "TSM", "MSFT", "GOOG", "AMZN", "META", "TSLA", "INTC"];
    const messages = [
      makeMessage({
        content: tickers.map((t) => `$${t}`).join(" "),
        citations: [],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    expect(screen.getAllByTestId("entity-mini-card")).toHaveLength(8);
    expect(screen.getByText("+2 more mentioned")).toBeInTheDocument();
  });

  it("fires onCardClick with the RESOLVED ticker when a card is clicked", () => {
    const onCardClick = vi.fn();
    const messages = [
      // Detected token is "$NVDA" but the (mocked) resolver returns AAPL —
      // the callback must receive the RESOLVED symbol, because that is what
      // /instruments/[ticker] navigates with.
      makeMessage({ content: "Look at $NVDA", citations: [] }),
    ];
    render(
      <ChatContextRail
        {...DEFAULT_PROPS}
        messages={messages}
        onCardClick={onCardClick}
      />,
    );
    fireEvent.click(screen.getByTestId("entity-mini-card"));
    expect(onCardClick).toHaveBeenCalledWith("AAPL");
  });

  it("renders cards as disabled (non-interactive) when onCardClick is absent", () => {
    const messages = [
      makeMessage({ content: "Look at $NVDA", citations: [] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // WHY disabled: a focusable button with no handler is a lying affordance.
    expect(screen.getByTestId("entity-mini-card")).toBeDisabled();
  });

  it("does NOT render a card for tickers that fail to resolve", () => {
    // Simulate the search-miss path: queryFn resolved to null (no instrument).
    vi.mocked(useQuery).mockReturnValue({
      data: null,
      isLoading: false,
    } as unknown as ReturnType<typeof useQuery>);
    const messages = [
      makeMessage({ content: "Look at $ZZZZZ", citations: [] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // The chip still shows (detection happened) …
    expect(screen.getByText("$ZZZZZ")).toBeInTheDocument();
    // … but no card renders — validation against the search endpoint failed.
    expect(screen.queryByTestId("entity-mini-card")).not.toBeInTheDocument();
  });
});

// ── Round 3 Polish — skeleton presence ────────────────────────────────────────

describe("ChatContextRail — loading skeletons (Round 3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders a card-SHAPED skeleton for the primary entity card while the overview loads", () => {
    // Pin the loading state: every useQuery in the rail reports in-flight.
    vi.mocked(useQuery).mockReturnValue({
      data: undefined,
      isLoading: true,
    } as unknown as ReturnType<typeof useQuery>);

    render(<ChatContextRail {...DEFAULT_PROPS} entityId="entity-uuid-1" />);

    // The skeleton wears the SAME card chrome as the populated EntityCard
    // (border + bg-card) so data landing doesn't pop a border into view —
    // the testid pins that the card-shaped variant (not bare bars) renders.
    expect(screen.getByTestId("entity-card-skeleton")).toBeInTheDocument();
  });
});
