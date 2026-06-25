/**
 * __tests__/shell/CommandPalette.test.tsx — Round-1 global ⌘K palette contract.
 *
 * Pins:
 *   - opens on Cmd+K AND Ctrl+K, toggles closed on a second press
 *   - Round-3: ⌘K is dispatched through lib/hotkey-registry (id
 *     `shell.command.palette`) by the useChordHotkeys document listener —
 *     the test harness mounts HotkeyProvider + the listener exactly like the
 *     production (app) layout does (GlobalHotkeyBindings mounts the listener)
 *   - ⌘K still fires while focus is in a text input (modifier chords bypass
 *     the input-suspension rule)
 *   - the mod+k binding is visible in registry.all() → the `?` cheat sheet
 *     lists it automatically (single-source-of-truth contract)
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
  // usePathname is consumed by useChordHotkeys (page-scoped binding matching).
  usePathname: () => "/dashboard",
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
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";
import { useChordHotkeys } from "@/hooks/useChordHotkeys";

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * Round-3: the palette's ⌘K chord goes through the hotkey registry. In the
 * production layout the document-level chord listener is mounted by
 * GlobalHotkeyBindings; tests mount it via this minimal host so the keydown →
 * registry → handler dispatch path is exercised end-to-end (same pattern as
 * __tests__/hotkey-cheat-sheet.test.tsx).
 */
function ListenerHost() {
  useChordHotkeys();
  return null;
}

function renderPalette() {
  // retry:false → a failing queryFn surfaces immediately instead of retrying
  // for 3×timeout and flaking the suite. Fresh client per test isolates caches.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // Fresh registry per render — isolates chord registrations between tests
  // (the default singleton would leak `shell.command.palette` across cases).
  const registry = new HotkeyRegistry();
  return {
    registry,
    ...render(
      <QueryClientProvider client={client}>
        <HotkeyProvider registry={registry}>
          <ListenerHost />
          <CommandPalette />
        </HotkeyProvider>
      </QueryClientProvider>,
    ),
  };
}

/** Simulate the global chord. The chord listener is attached to `document`. */
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

  it("registers mod+k in the hotkey registry (cheat-sheet single-source contract)", () => {
    // The `?` overlay (HotkeyCheatSheet) renders registry.all() verbatim —
    // this binding existing IS what makes ⌘K appear there. If this assertion
    // fails, the cheat sheet stops listing the command palette.
    const { registry } = renderPalette();
    const binding = registry.all().find((b) => b.id === "shell.command.palette");
    expect(binding).toBeDefined();
    expect(binding?.chord).toBe("mod+k");
    expect(binding?.group).toBe("Symbol");
    expect(binding?.label).toBe("Open command palette");
  });

  it("⌘K still fires while focus is in a text input (modifier chords bypass suspension)", () => {
    // This pins the property that justified moving ⌘K into the registry:
    // useChordHotkeys only suspends modifier-LESS chords inside text inputs,
    // so ⌘K from the chat composer / search box still opens the palette.
    renderPalette();
    const input = document.createElement("input");
    input.type = "text";
    document.body.appendChild(input);
    input.focus();
    try {
      fireEvent.keyDown(input, { key: "k", metaKey: true });
      expect(screen.getByPlaceholderText(INPUT_PLACEHOLDER)).toBeInTheDocument();
    } finally {
      input.remove();
    }
  });

  it("unregisters mod+k on unmount (no stale chord after the layout tears down)", () => {
    const { registry, unmount } = renderPalette();
    expect(registry.all().some((b) => b.id === "shell.command.palette")).toBe(true);
    unmount();
    expect(registry.all().some((b) => b.id === "shell.command.palette")).toBe(false);
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
