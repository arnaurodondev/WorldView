/**
 * features/chat/components/__tests__/ChatContextRail.test.tsx
 *
 * Unit tests for ChatContextRail.
 *
 * WHAT THESE GUARD (Wave-2 rework — sections renamed/upgraded, assertions
 * PORTED from the pre-rework suite, never dropped):
 *   1. Source deduplication — same source doc across two messages → 1 row
 *      with a ×N reference count (was: citation dedup by article_id).
 *   2. Row cap — sources beyond DEFAULT_SOURCE_CAP collapse into a
 *      "+N more sources" line (was: hard top-4 cap).
 *   3. Ordering — count desc then relevance desc (was: relevance only).
 *   4. Contradiction extraction — ⚠ prefix in message content → warning chip.
 *   5. Related tickers extraction — $AAPL in content → ticker chip rendered.
 *   6. onTickerClick callback — clicking a ticker chip fires the callback.
 *   7. onClose callback — clicking × fires onClose.
 *   8. Entity section visibility — rendered only when entityId is non-null.
 *   9. (Wave 2) Cold state, Tools Used summary, source rows as external
 *      links, one-request by-ticker mini-card fetch, 5-day sparkline.
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

// ── Mock gateway (mostly not called — useQuery is mocked — but the Wave-2
// fetch-path test invokes a captured queryFn against these spies).
const mockGetCompanyOverviewByTicker = vi.fn();
const mockSearchInstruments = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getCompanyOverview: vi.fn(),
    getCompanyOverviewByTicker: mockGetCompanyOverviewByTicker,
    searchInstruments: mockSearchInstruments,
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
    // WHY exact string (Wave-2 port): the cold-state title ("Context appears
    // as you chat") also matches a /context/i regex; the exact node text
    // pins the PANEL HEADER specifically (CSS uppercases it visually).
    expect(screen.getByText("Context")).toBeInTheDocument();
  });

  // ── Wave 2: cold state ────────────────────────────────────────────────────

  it("shows the 'Context appears as you chat' cold state for an empty conversation", () => {
    render(<ChatContextRail {...DEFAULT_PROPS} messages={[]} entityId={null} />);
    expect(screen.getByTestId("rail-cold-state")).toBeInTheDocument();
    expect(
      screen.getByText("Context appears as you chat"),
    ).toBeInTheDocument();
    // The empty section scaffolding must NOT render alongside the cold state.
    expect(screen.queryByText("Conversation Sources")).not.toBeInTheDocument();
  });

  it("does NOT show the cold state once the conversation has messages", () => {
    render(
      <ChatContextRail
        {...DEFAULT_PROPS}
        messages={[makeMessage({ content: "hello" })]}
      />,
    );
    expect(screen.queryByTestId("rail-cold-state")).not.toBeInTheDocument();
    expect(screen.getByText("Conversation Sources")).toBeInTheDocument();
  });

  it("fires onClose when × is clicked", () => {
    const onClose = vi.fn();
    render(<ChatContextRail {...DEFAULT_PROPS} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText("Close context rail"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  // ── Entity section ────────────────────────────────────────────────────────

  it("does NOT render Entity section header when entityId is null", () => {
    render(
      <ChatContextRail
        {...DEFAULT_PROPS}
        entityId={null}
        // A message keeps the rail OUT of the cold state so this pins the
        // section's absence specifically (Wave-2 port: the cold-state body
        // mentions "Entity cards", which a loose /entity/i would match).
        messages={[makeMessage({ content: "plain text" })]}
      />,
    );
    expect(screen.queryByText("Entity")).not.toBeInTheDocument();
  });

  it("renders Entity section header when entityId is provided", () => {
    render(
      <ChatContextRail
        {...DEFAULT_PROPS}
        entityId="2c8e3a7f-0001-0001-0001-000000000001"
      />,
    );
    expect(screen.getByText("Entity")).toBeInTheDocument();
  });

  // ── Citations ─────────────────────────────────────────────────────────────

  it("shows 'No sources cited yet.' when messages have no citations", () => {
    const messages = [
      makeMessage({ content: "Hello world", citations: [] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    expect(screen.getByText(/no sources cited yet/i)).toBeInTheDocument();
  });

  it("deduplicates citations of the same source doc and shows the reference count", () => {
    // WHY two messages with the same citation (ported): the assistant
    // references the same 10-Q in two different turns. The rail shows ONE
    // row — now (Wave 2) with a ×2 reference count instead of losing the
    // second occurrence silently.
    const sharedCitation = {
      article_id: "art-001",
      title: "AAPL 10-Q Q2 2026",
      url: "https://sec.gov/Archives/aapl-10q",
      source: "sec",
      relevance_score: 0.95,
    };
    const messages = [
      makeMessage({ content: "First", citations: [sharedCitation] }),
      makeMessage({ content: "Second", citations: [sharedCitation] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // Only one instance of the title should appear…
    const titles = screen.getAllByText("AAPL 10-Q Q2 2026");
    expect(titles).toHaveLength(1);
    // …carrying the aggregated reference count.
    expect(screen.getByText("×2 references")).toBeInTheDocument();
  });

  it("source rows with a URL open in a new tab; URL-less (KG) rows are not links", () => {
    const messages = [
      makeMessage({
        content: "Mixed sources",
        citations: [
          {
            article_id: "ext-1",
            title: "External article",
            url: "https://news.example.com/a",
            source: "news",
            relevance_score: 0.8,
          },
          {
            article_id: "kg-1",
            title: "Knowledge graph claim",
            url: "", // normalizer writes "" for KG citations — must not link
            source: "kg",
            relevance_score: 0.7,
          },
        ],
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);

    const rows = screen.getAllByTestId("conversation-source-row");
    expect(rows).toHaveLength(2);

    const link = screen.getByText("External article").closest("a");
    expect(link).not.toBeNull();
    expect(link).toHaveAttribute("href", "https://news.example.com/a");
    // New tab + reverse-tabnabbing protection — research gesture must never
    // navigate the chat away.
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");

    // KG row renders as a plain div — a dead <a href="#"> would be a lie.
    expect(screen.getByText("Knowledge graph claim").closest("a")).toBeNull();
  });

  it("caps rendered sources at 6 and shows the '+N more sources' overflow", () => {
    // Ported from the old top-4 cap test: the cap is now DEFAULT_SOURCE_CAP
    // (6) with an explicit overflow line instead of silent truncation.
    const messages = [
      makeMessage({
        content: "Source dump",
        citations: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => ({
          article_id: `art-${i}`,
          title: `Article ${i}`,
          url: `https://example.com/${i}`,
          source: "news",
          relevance_score: i / 10,
        })),
      }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    // Six [N] rank markers render…
    for (const idx of ["[1]", "[2]", "[3]", "[4]", "[5]", "[6]"]) {
      expect(screen.getByText(idx)).toBeInTheDocument();
    }
    // …[7]/[8] do not — they collapse into the overflow line.
    expect(screen.queryByText("[7]")).not.toBeInTheDocument();
    expect(screen.queryByText("[8]")).not.toBeInTheDocument();
    expect(screen.getByText("+2 more sources")).toBeInTheDocument();
    // The section count badge still reports ALL distinct sources.
    expect(screen.getByText("8")).toBeInTheDocument();
  });

  it("sorts equally-referenced sources by relevance_score descending", () => {
    // Ported: highest-confidence source must appear at position [1] when
    // reference counts tie (count is the primary key — Wave 2).
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
    const firstIndex = items.find((el) => el.textContent === "[1]");
    // The "[1]" marker shares a row container with its title (url-less rows
    // render as divs, so we anchor on the row testid, not <a>).
    expect(
      firstIndex?.closest('[data-testid="conversation-source-row"]')
        ?.textContent,
    ).toContain("High confidence source");
  });

  it("a source referenced MORE OFTEN outranks a higher-relevance one-off", () => {
    const repeat = {
      article_id: "rep",
      title: "Repeated source",
      url: "https://example.com/rep",
      source: "news",
      relevance_score: 0.2,
    };
    const messages = [
      makeMessage({
        content: "a",
        citations: [
          repeat,
          {
            article_id: "one",
            title: "One-off high confidence",
            url: "https://example.com/one",
            source: "sec",
            relevance_score: 0.99,
          },
        ],
      }),
      makeMessage({ content: "b", citations: [repeat] }),
    ];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    const first = screen.getByText("[1]");
    expect(
      first.closest('[data-testid="conversation-source-row"]')?.textContent,
    ).toContain("Repeated source");
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

// ── Round 4 Hardening — entity-card lookups are FAIL-SILENT (1d) ─────────────
//
// The rail's cards are ambient background context, not user-requested data.
// When their lookups fail (S9 down, search 500, overview 404) the card must
// simply be ABSENT — no error banner, no destructive chrome, nothing that
// makes a background fetch failure look like a conversation problem.

describe("ChatContextRail — failed card lookups stay silent (Round 4)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("a failed primary entity-card query renders NO card and NO error UI", () => {
    // TanStack error state: data undefined, isError true. The rail reads only
    // data/isLoading — the error must not leak into the DOM.
    vi.mocked(useQuery).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("overview fetch failed"),
    } as unknown as ReturnType<typeof useQuery>);

    render(<ChatContextRail {...DEFAULT_PROPS} entityId="entity-uuid-1" />);

    // Card absent…
    expect(screen.queryByTestId("entity-card-skeleton")).not.toBeInTheDocument();
    // …and no error copy / alert role anywhere in the rail.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/error|failed|retry/i)).not.toBeInTheDocument();
    // The rest of the rail keeps rendering normally (section labels intact —
    // Wave 2: "Recent Citations" became "Conversation Sources").
    expect(screen.getByText("Conversation Sources")).toBeInTheDocument();
  });

  it("a failed mini-card lookup renders NO card and NO error UI (chip survives)", () => {
    vi.mocked(useQuery).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("search 500"),
    } as unknown as ReturnType<typeof useQuery>);

    const messages = [makeMessage({ content: "Look at $NVDA", citations: [] })];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);

    // Detection still surfaces the quick-action chip…
    expect(screen.getByText("$NVDA")).toBeInTheDocument();
    // …but the failed lookup contributes no card and no error chrome.
    expect(screen.queryByTestId("entity-mini-card")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/error|failed|retry/i)).not.toBeInTheDocument();
  });
});

// ── Wave 2 — one-request by-ticker fetch + 5-day sparkline ───────────────────

describe("ChatContextRail — by-ticker mini-card fetch (Wave 2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("mini-card queryFn resolves via getCompanyOverviewByTicker in ONE call (no search step)", async () => {
    // useQuery is module-mocked, so the queryFn never runs in render — we
    // CAPTURE the options the mini-card passes and invoke the queryFn
    // directly against the gateway spies. This pins the Wave-2 contract:
    // one by-ticker request, zero searchInstruments round-trips.
    vi.mocked(useQuery).mockReturnValue({
      data: undefined,
      isLoading: true,
    } as unknown as ReturnType<typeof useQuery>);

    const messages = [makeMessage({ content: "Look at $NVDA", citations: [] })];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);

    // Find the mini-card's query options by its cache key shape
    // (["chat", "ticker-mini", "NVDA"] — qk.chat.tickerMini).
    const call = vi
      .mocked(useQuery)
      .mock.calls.map((c) => c[0] as { queryKey?: unknown; queryFn?: () => unknown })
      .find(
        (opts) =>
          Array.isArray(opts.queryKey) && opts.queryKey[1] === "ticker-mini",
      );
    expect(call).toBeDefined();
    expect(Array.isArray(call!.queryKey) && (call!.queryKey as string[])[2]).toBe(
      "NVDA",
    );

    mockGetCompanyOverviewByTicker.mockResolvedValue(MOCK_OVERVIEW);
    await call!.queryFn!();

    expect(mockGetCompanyOverviewByTicker).toHaveBeenCalledWith("NVDA");
    // The old two-step dance is GONE — no instrument search round-trip.
    expect(mockSearchInstruments).not.toHaveBeenCalled();
  });

  it("renders a 5-day sparkline from the ohlcv bars the overview already carries", () => {
    vi.mocked(useQuery).mockReturnValue({
      data: {
        ...MOCK_OVERVIEW,
        ohlcv: {
          bars: [248.1, 250.4, 249.9, 252.8, 254.2, 255.0, 256.3].map(
            (close, i) => ({
              timestamp: `2026-06-0${i + 1}T00:00:00Z`,
              open: close,
              high: close,
              low: close,
              close,
              volume: 1000,
            }),
          ),
        },
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useQuery>);

    const messages = [makeMessage({ content: "Look at $AAPL", citations: [] })];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);

    // The sparkline wrapper renders inside the card — zero extra requests
    // (the closes come from the overview payload itself).
    expect(screen.getByTestId("mini-card-sparkline")).toBeInTheDocument();
  });

  it("renders NO sparkline when the overview has fewer than 2 bars", () => {
    vi.mocked(useQuery).mockReturnValue({
      data: { ...MOCK_OVERVIEW, ohlcv: { bars: [] } },
      isLoading: false,
    } as unknown as ReturnType<typeof useQuery>);

    const messages = [makeMessage({ content: "Look at $AAPL", citations: [] })];
    render(<ChatContextRail {...DEFAULT_PROPS} messages={messages} />);
    expect(screen.getByTestId("entity-mini-card")).toBeInTheDocument();
    expect(screen.queryByTestId("mini-card-sparkline")).not.toBeInTheDocument();
  });
});

// ── Wave 2 — Tools Used section ───────────────────────────────────────────────

describe("ChatContextRail — Tools Used (Wave 2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useQuery).mockReturnValue({
      data: undefined,
      isLoading: false,
    } as unknown as ReturnType<typeof useQuery>);
  });

  const SAMPLES = [
    { tool: "get_price_history", latencyMs: 100 },
    { tool: "get_price_history", latencyMs: 200 },
    { tool: "search_documents", latencyMs: 950 },
  ];

  it("renders one row per tool with count and average latency", () => {
    const messages = [makeMessage({ content: "tool-using answer" })];
    render(
      <ChatContextRail
        {...DEFAULT_PROPS}
        messages={messages}
        toolUsage={SAMPLES}
      />,
    );

    expect(screen.getByText("Tools Used")).toBeInTheDocument();
    const rows = screen.getAllByTestId("tool-usage-row");
    expect(rows).toHaveLength(2);
    // Count-desc ordering: price_history (×2) above search_documents (×1).
    expect(rows[0].textContent).toContain("get_price_history");
    expect(rows[0].textContent).toContain("×2");
    expect(rows[0].textContent).toContain("150 ms"); // (100+200)/2
    expect(rows[1].textContent).toContain("search_documents");
    expect(rows[1].textContent).toContain("×1");
    expect(rows[1].textContent).toContain("950 ms");
  });

  it("omits the section entirely when no tools have completed", () => {
    const messages = [makeMessage({ content: "pure LLM answer" })];
    render(
      <ChatContextRail {...DEFAULT_PROPS} messages={messages} toolUsage={[]} />,
    );
    expect(screen.queryByText("Tools Used")).not.toBeInTheDocument();
  });

  it("links to ?debug=1 when debug is off, and shows the ⌘D hint when on", () => {
    const messages = [makeMessage({ content: "tool-using answer" })];
    const { rerender } = render(
      <ChatContextRail
        {...DEFAULT_PROPS}
        messages={messages}
        toolUsage={SAMPLES}
        isDebug={false}
        debugHref="/chat?thread=t-1&debug=1"
      />,
    );
    const link = screen.getByTestId("tools-debug-link");
    expect(link).toHaveAttribute("href", "/chat?thread=t-1&debug=1");

    rerender(
      <ChatContextRail
        {...DEFAULT_PROPS}
        messages={messages}
        toolUsage={SAMPLES}
        isDebug
        debugHref="/chat?thread=t-1&debug=1"
      />,
    );
    expect(screen.queryByTestId("tools-debug-link")).not.toBeInTheDocument();
    expect(screen.getByText(/⌘D opens the per-call trace/)).toBeInTheDocument();
  });
});
