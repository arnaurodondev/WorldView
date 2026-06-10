/**
 * __tests__/shell/CommandPalette.test.tsx — Round-1 global ⌘K palette contract.
 *
 * Pins:
 *   - opens on Cmd+K AND Ctrl+K, toggles closed on a second press
 *   - closes on Escape (Radix Dialog dismissal path resets the query)
 *   - opens on the `worldview:open-command-palette` CustomEvent (TopBar chip)
 *   - Navigate group enumerates routes with registry chord hints
 *   - typing filters nav items; selecting one router.push()es and closes
 *   - instrument search is debounced (4 keystrokes → exactly ONE S9 call)
 *   - exact-ticker ranking is reflected in DOM order; selecting navigates
 *     to /instruments/<entity_id>
 *   - recent conversations render newest-first and navigate to /chat?thread=
 *   - recent instruments (localStorage) render when the query is empty
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks ──────────────────────────────────────────────────────────────────────

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token", isAuthenticated: true, isLoading: false }),
}));

// Gateway: only the two methods the palette consumes. vi.hoisted so the
// factory variables exist before the hoisted vi.mock call runs.
const { mockSearchInstruments, mockGetThreads } = vi.hoisted(() => ({
  mockSearchInstruments: vi.fn(),
  mockGetThreads: vi.fn(),
}));
vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    searchInstruments: mockSearchInstruments,
    getThreads: mockGetThreads,
  }),
}));

import { CommandPalette, OPEN_COMMAND_PALETTE_EVENT } from "@/components/shell/CommandPalette";

// ── Helpers ────────────────────────────────────────────────────────────────────

function renderPalette() {
  // retry:false → a failing queryFn surfaces immediately instead of retrying
  // for 3×timeout and flaking the suite. Fresh client per test isolates caches.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CommandPalette />
    </QueryClientProvider>,
  );
}

/** Simulate the global chord. The palette listens on `document`. */
function pressCmdK(opts: { ctrl?: boolean } = {}) {
  fireEvent.keyDown(document, {
    key: "k",
    metaKey: !opts.ctrl,
    ctrlKey: !!opts.ctrl,
  });
}

const INPUT_PLACEHOLDER = "Type a page, ticker or conversation…";

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  // Default: no search results / no threads. Individual tests override.
  mockSearchInstruments.mockResolvedValue({ results: [], query: "" });
  mockGetThreads.mockResolvedValue([]);
});

// ── Open / close behaviour ─────────────────────────────────────────────────────

describe("CommandPalette open/close", () => {
  it("is closed by default and opens on Cmd+K", () => {
    renderPalette();
    expect(screen.queryByPlaceholderText(INPUT_PLACEHOLDER)).not.toBeInTheDocument();

    pressCmdK();
    expect(screen.getByPlaceholderText(INPUT_PLACEHOLDER)).toBeInTheDocument();
  });

  it("opens on Ctrl+K (non-mac) and toggles closed on a second press", () => {
    renderPalette();
    pressCmdK({ ctrl: true });
    expect(screen.getByPlaceholderText(INPUT_PLACEHOLDER)).toBeInTheDocument();

    pressCmdK({ ctrl: true });
    expect(screen.queryByPlaceholderText(INPUT_PLACEHOLDER)).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    renderPalette();
    pressCmdK();
    const input = screen.getByPlaceholderText(INPUT_PLACEHOLDER);

    // Radix DismissableLayer listens for Escape on the document; firing on the
    // focused input bubbles there.
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByPlaceholderText(INPUT_PLACEHOLDER)).not.toBeInTheDocument();
    });
  });

  it("opens when the TopBar hint dispatches the CustomEvent", () => {
    renderPalette();
    fireEvent(window, new CustomEvent(OPEN_COMMAND_PALETTE_EVENT));
    expect(screen.getByPlaceholderText(INPUT_PLACEHOLDER)).toBeInTheDocument();
  });

  it("resets the query when reopened (no stale filter)", async () => {
    renderPalette();
    pressCmdK();
    fireEvent.change(screen.getByPlaceholderText(INPUT_PLACEHOLDER), {
      target: { value: "portfolio" },
    });
    // Close via Escape, reopen — the input must be empty again.
    fireEvent.keyDown(screen.getByPlaceholderText(INPUT_PLACEHOLDER), { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByPlaceholderText(INPUT_PLACEHOLDER)).not.toBeInTheDocument();
    });
    pressCmdK();
    expect(screen.getByPlaceholderText(INPUT_PLACEHOLDER)).toHaveValue("");
  });
});

// ── Navigate group ─────────────────────────────────────────────────────────────

describe("CommandPalette Navigate group", () => {
  it("renders main routes with chord hints from the registry convention", () => {
    renderPalette();
    pressCmdK();

    // WHY selector scope: "Navigate" also appears in the footer hint strip
    // ("↑↓ Navigate") — scope to the cmdk group heading element.
    expect(screen.getByText("Navigate", { selector: "[cmdk-group-heading]" })).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Screener")).toBeInTheDocument();
    expect(screen.getByText("Portfolio › Transactions")).toBeInTheDocument();
    expect(screen.getByText("Watchlists")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    // Chord hint: jsdom is non-mac → formatChordForDisplay("g d") === "G D".
    expect(screen.getByText("G D")).toBeInTheDocument();
  });

  it("filters nav items as the user types (label + keyword match)", () => {
    renderPalette();
    pressCmdK();
    fireEvent.change(screen.getByPlaceholderText(INPUT_PLACEHOLDER), {
      target: { value: "trades" }, // keyword of Portfolio › Transactions
    });

    expect(screen.getByText("Portfolio › Transactions")).toBeInTheDocument();
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
  });

  it("navigates and closes when a nav item is selected", () => {
    renderPalette();
    pressCmdK();
    fireEvent.click(screen.getByText("Dashboard"));

    expect(mockPush).toHaveBeenCalledWith("/dashboard");
    expect(screen.queryByPlaceholderText(INPUT_PLACEHOLDER)).not.toBeInTheDocument();
  });
});

// ── Instrument search ──────────────────────────────────────────────────────────

describe("CommandPalette instrument search", () => {
  it("debounces keystrokes into a single S9 call with the final query", async () => {
    renderPalette();
    pressCmdK();
    const input = screen.getByPlaceholderText(INPUT_PLACEHOLDER);

    // Four rapid keystrokes — the 250ms debounce must collapse them.
    for (const v of ["A", "AA", "AAP", "AAPL"]) {
      fireEvent.change(input, { target: { value: v } });
    }

    await waitFor(() => expect(mockSearchInstruments).toHaveBeenCalled());
    expect(mockSearchInstruments).toHaveBeenCalledTimes(1);
    expect(mockSearchInstruments).toHaveBeenCalledWith("AAPL", 10);
  });

  it("renders results ranked (exact ticker first) and navigates on select", async () => {
    // Server order: AAPL before A — ranking must flip them for query "A".
    mockSearchInstruments.mockResolvedValue({
      results: [
        { instrument_id: "i-aapl", entity_id: "e-aapl", ticker: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", type: "equity" },
        { instrument_id: "i-a", entity_id: "e-a", ticker: "A", name: "Agilent", exchange: "NYSE", type: "equity" },
      ],
      query: "A",
    });

    renderPalette();
    pressCmdK();
    fireEvent.change(screen.getByPlaceholderText(INPUT_PLACEHOLDER), { target: { value: "A" } });

    const agilent = await screen.findByText("Agilent");
    const apple = screen.getByText("Apple Inc.");
    // Exact match "A" (Agilent) must precede prefix match AAPL in DOM order.
    expect(
      agilent.compareDocumentPosition(apple) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    fireEvent.click(agilent);
    expect(mockPush).toHaveBeenCalledWith("/instruments/e-a");
    // Selecting an instrument persists it to the shared recents stack.
    expect(window.localStorage.getItem("worldview-recent-instruments")).toContain("e-a");
  });

  it("shows localStorage recent instruments while the query is empty", () => {
    window.localStorage.setItem(
      "worldview-recent-instruments",
      JSON.stringify([{ entityId: "e-nvda", ticker: "NVDA", name: "NVIDIA Corp." }]),
    );
    renderPalette();
    pressCmdK();

    expect(screen.getByText("Recent Instruments")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    // No query typed → no S9 search must fire (gated on length >= 1).
    expect(mockSearchInstruments).not.toHaveBeenCalled();
  });
});

// ── Recent conversations ───────────────────────────────────────────────────────

describe("CommandPalette recent conversations", () => {
  it("renders the newest threads and navigates with ?thread=", async () => {
    mockGetThreads.mockResolvedValue([
      { thread_id: "t-old", title: "NVDA earnings deep dive", owner_id: "u1", messages: [], created_at: "2026-06-01T00:00:00Z", updated_at: "2026-06-01T00:00:00Z" },
      { thread_id: "t-new", title: "AAPL guidance question", owner_id: "u1", messages: [], created_at: "2026-06-09T00:00:00Z", updated_at: "2026-06-09T00:00:00Z" },
    ]);

    renderPalette();
    pressCmdK();

    const newest = await screen.findByText("AAPL guidance question");
    const oldest = screen.getByText("NVDA earnings deep dive");
    // Newest-first ordering in the DOM.
    expect(
      newest.compareDocumentPosition(oldest) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    fireEvent.click(newest);
    expect(mockPush).toHaveBeenCalledWith("/chat?thread=t-new");
  });

  it("falls back to the untitled label for title=null threads", async () => {
    mockGetThreads.mockResolvedValue([
      { thread_id: "t-x", title: null, owner_id: "u1", messages: [], created_at: "2026-06-09T00:00:00Z", updated_at: "2026-06-09T00:00:00Z" },
    ]);
    renderPalette();
    pressCmdK();

    expect(await screen.findByText("Untitled conversation")).toBeInTheDocument();
  });
});
