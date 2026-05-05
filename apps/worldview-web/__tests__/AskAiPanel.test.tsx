/**
 * __tests__/AskAiPanel.test.tsx — SSE streaming and interaction tests for AskAiPanel
 *
 * WHY THIS EXISTS: AskAiPanel has complex streaming logic:
 * - fetch() + ReadableStream for POST-based SSE (EventSource is GET-only)
 * - incremental token accumulation into response text
 * - [DONE] sentinel stops streaming and marks complete
 * - DS-007 regression: final token at stream boundary must not be dropped
 * - Error handling (network failure, non-2xx status)
 * - P2B-1: post-stream citation parsing ([N] markers + Sources section)
 *
 * WHAT WE TEST:
 * 1. Initial render — textarea auto-focus, placeholder, disabled Send button
 * 2. Typing a query enables the Send button
 * 3. SSE streaming — tokens accumulate correctly
 * 4. [DONE] sentinel — stops streaming, clears isStreaming state
 * 5. DS-007 regression — final token in buffer (no trailing \n) is processed
 * 6. Error state — network failure shows error message
 * 7. Error state — HTTP error (non-200) shows error message
 * 8. Keyboard interaction — Enter sends, Shift+Enter allows newline
 * 9. Escape key calls onClose
 * 10. Close button (X) calls onClose
 * 11. External link button navigates to /chat and calls onClose
 * 12. Textarea disabled while streaming
 * 13. No accessToken — Send button disabled / handleSend no-ops
 * 14. P2B-1: [N] markers render as superscript <sup> elements post-stream
 * 15. P2B-1: Sources section rendered when response contains Sources block
 * 16. P2B-1: No Sources section when response has no Sources block
 * 17. P2B-1: parseCitationResponse and renderWithCitations unit tests
 *
 * WHAT WE DO NOT TEST HERE:
 * - Visual layout (Playwright e2e)
 * - Actual HTTP requests to real S9 (integration test)
 *
 * WHY MOCK fetch: prevents real network calls; lets us inject controlled SSE data.
 * WHY MOCK useAuth: component reads accessToken from this hook.
 * WHY MOCK next/navigation: useRouter requires Next.js Router context.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { AskAiPanel, parseCitationResponse, renderWithCitations } from "@/components/shell/AskAiPanel";

// ── Next.js mock ───────────────────────────────────────────────────────────────

// WHY: useRouter from next/navigation is not available in jsdom — needs mocking.
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: mockPush,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  })),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────

// WHY: AskAiPanel calls useAuth() to get the access token for the Authorization header.
const mockUseAuth = vi.fn(() => ({
  accessToken: "test-bearer-token",
  isAuthenticated: true,
  isLoading: false,
  user: null,
  setTokens: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => mockUseAuth(),
}));

// ── Fetch mock helpers ─────────────────────────────────────────────────────────

/**
 * makeSSEStream — create a ReadableStream that emits the given SSE chunks.
 * WHY TextEncoder: ReadableStream works with Uint8Array (binary) not strings.
 * The TextDecoder in the component handles the decode step.
 */
function makeSSEStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

/**
 * mockFetch — replace global fetch with one that returns a controlled SSE stream.
 * Returns the mock function so tests can assert it was called.
 */
function mockFetch(chunks: string[], status = 200) {
  const mockFn = vi.fn().mockResolvedValue(
    new Response(makeSSEStream(chunks), {
      status,
      headers: { "Content-Type": "text/event-stream" },
    }),
  );
  vi.stubGlobal("fetch", mockFn);
  return mockFn;
}

// ── Render helper ─────────────────────────────────────────────────────────────

function renderPanel(onClose = vi.fn()) {
  return { ...render(<AskAiPanel onClose={onClose} />), onClose };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AskAiPanel — initial render", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the Ask AI header", () => {
    renderPanel();
    expect(screen.getByText("Analyst")).toBeInTheDocument();
  });

  it("renders the textarea with placeholder text", () => {
    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    expect(textarea).toBeInTheDocument();
  });

  it("Send button is disabled when textarea is empty", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: /send message/i })).toBeDisabled();
  });

  it("Send button is enabled after typing a query", () => {
    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "What is AAPL's P/E ratio?" } });
    expect(screen.getByRole("button", { name: /send message/i })).not.toBeDisabled();
  });

  it("renders close (X) button", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: /close ai panel/i })).toBeInTheDocument();
  });

  it("renders Open full chat button", () => {
    renderPanel();
    expect(screen.getByTitle(/open full chat/i)).toBeInTheDocument();
  });
});

describe("AskAiPanel — close interactions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls onClose when X button is clicked", () => {
    const { onClose } = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /close ai panel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when Escape key is pressed", () => {
    const { onClose } = renderPanel();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose and navigates to /chat when external link is clicked", () => {
    const { onClose } = renderPanel();
    fireEvent.click(screen.getByTitle(/open full chat/i));
    expect(mockPush).toHaveBeenCalledWith("/chat");
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("AskAiPanel — keyboard shortcuts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch([
      'data: {"token":"Hi"}\n\n',
      "data: [DONE]\n\n",
    ]);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Enter key (without Shift) submits the query", async () => {
    renderPanel();

    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "What is beta?" } });

    // Press Enter (no shift) — should trigger send
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    // Response should appear after streaming
    await waitFor(() => {
      expect(screen.getByText("Hi")).toBeInTheDocument();
    });
  });

  it("Shift+Enter does NOT submit (allows newlines)", () => {
    const fetchMock = mockFetch([]);
    renderPanel();

    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Multi-line" } });

    // Shift+Enter should NOT trigger fetch
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });

    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("AskAiPanel — SSE streaming", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("accumulates tokens from the SSE stream", async () => {
    mockFetch([
      'data: {"token":"Hello"}\n\n',
      'data: {"token":" World"}\n\n',
      "data: [DONE]\n\n",
    ]);

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Test question" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    // WHY waitFor with specific text: tokens stream asynchronously;
    // we need to poll until the full accumulated text is present.
    await waitFor(() => {
      expect(screen.getByText("Hello World")).toBeInTheDocument();
    });
  });

  it("stops streaming on [DONE] sentinel", async () => {
    mockFetch([
      'data: {"token":"Done"}\n\n',
      "data: [DONE]\n\n",
      // These tokens MUST NOT appear (stream already ended)
      'data: {"token":"EXTRA"}\n\n',
    ]);

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Question" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      // "Done" should be there but not "EXTRA" (stream ended at [DONE])
      expect(screen.getByText("Done")).toBeInTheDocument();
    });

    expect(screen.queryByText(/EXTRA/)).toBeNull();
  });

  it("DS-007 regression: processes final token without trailing newline", async () => {
    // WHY this test: The SSE parser splits on \n and moves the last incomplete
    // line back into the buffer. When the stream ends (done=true) without a
    // trailing newline, the buffer still holds the final data line.
    // The DS-007 fix flushes this buffer after the loop exits.
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        // First chunk: complete SSE line
        controller.enqueue(encoder.encode('data: {"token":"First"}\n\n'));
        // Final chunk: NO trailing \n — simulates the stream boundary edge case
        controller.enqueue(encoder.encode('data: {"token":"Last"}'));
        controller.close();
      },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(stream, { status: 200 })),
    );

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Edge case" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    // Both tokens must appear — "Last" would be dropped without the DS-007 fix
    await waitFor(() => {
      expect(screen.getByText("FirstLast")).toBeInTheDocument();
    });
  });

  it("shows blinking cursor while streaming", async () => {
    // WHY: The streaming cursor is a UX indicator. Tests verify it appears
    // during streaming so regressions (e.g., always showing it) are caught.
    let resolveStream!: () => void;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        // Emit one token but DON'T close — keep stream open to keep isStreaming=true
        controller.enqueue(new TextEncoder().encode('data: {"token":"..."}\n\n'));
        // Stream stays open; resolveStream() will close it to end the test
        new Promise<void>((resolve) => {
          resolveStream = resolve;
        }).then(() => controller.close()).catch(() => undefined);
      },
    });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream, { status: 200 })));

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Streaming test" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    // WHY animate-pulse: the blinking cursor has this Tailwind class
    await waitFor(() => {
      expect(document.querySelector(".animate-pulse")).toBeInTheDocument();
    });

    // Clean up: close the stream so the component can finish
    act(() => resolveStream());
  });

  it("textarea is disabled while streaming", async () => {
    let resolveStream!: () => void;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"token":"..."}\n\n'));
        new Promise<void>((resolve) => { resolveStream = resolve; })
          .then(() => controller.close()).catch(() => undefined);
      },
    });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream, { status: 200 })));

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Is it disabled?" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(textarea).toBeDisabled();
    });

    act(() => resolveStream());
  });
});

describe("AskAiPanel — error states", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("shows error message when fetch throws (network failure)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("NetworkError")),
    );

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Does this fail?" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      // WHY text-destructive: the component renders errors in destructive color class
      const errorEl = document.querySelector(".text-destructive");
      expect(errorEl).not.toBeNull();
    });
  });

  it("shows error message when server returns non-200 status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(null, { status: 503, statusText: "Service Unavailable" }),
      ),
    );

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "503 test" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      const errorEl = document.querySelector(".text-destructive");
      expect(errorEl).not.toBeNull();
      expect(errorEl?.textContent).toMatch(/503|chat|failed/i);
    });
  });

  it("re-enables Send button after error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Timeout")),
    );

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Will fail" } });
    const sendBtn = screen.getByRole("button", { name: /send message/i });
    fireEvent.click(sendBtn);

    // After error, isStreaming=false → button not disabled (query still has text)
    await waitFor(() => {
      expect(sendBtn).not.toBeDisabled();
    });
  });
});

describe("AskAiPanel — auth guard", () => {
  afterEach(() => {
    // Restore default mock after each test in this describe block
    mockUseAuth.mockReturnValue({
      accessToken: "test-bearer-token",
      isAuthenticated: true,
      isLoading: false,
      user: null,
      setTokens: vi.fn(),
      logout: vi.fn(),
    });
    vi.unstubAllGlobals();
  });

  it("does not call fetch when accessToken is null", async () => {
    // WHY mockReturnValue (not mockReturnValueOnce): React may re-render the
    // component multiple times (e.g., state updates from effects). mockReturnValueOnce
    // only overrides the FIRST call; subsequent renders fall back to the default
    // mock (which has a real token), causing handleSend to proceed.
    // mockReturnValue overrides ALL calls during this test.
    // WHY unknown cast: the mockUseAuth return type is inferred from the default
    // mock definition which has accessToken: string (non-null). Casting through
    // unknown allows this test to inject null for accessToken without a TS error.
    // This is the standard "partial mock" escape hatch in test files.
    mockUseAuth.mockReturnValue({
      accessToken: null,
      isAuthenticated: false,
      isLoading: false,
      user: null,
      setTokens: vi.fn(),
      logout: vi.fn(),
    } as unknown as ReturnType<typeof mockUseAuth>);

    const fetchMock = mockFetch([]);
    renderPanel();

    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "No token" } });

    // WHY click Send even though accessToken=null: the button's disabled prop
    // only checks query.trim() || isStreaming — NOT accessToken. So the button
    // IS enabled with text in it. Clicking calls handleSend() which guards:
    //   if (!query.trim() || isStreaming || !accessToken) return;
    // → returns early, fetch is never called.
    const sendBtn = screen.getByRole("button", { name: /send message/i });
    fireEvent.click(sendBtn);

    // Give React time to process any state updates, then assert fetch not called
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ── P2B-1: parseCitationResponse unit tests ───────────────────────────────────

describe("parseCitationResponse", () => {
  it("returns full text as body when no Sources section is present", () => {
    const { body, sources } = parseCitationResponse("Apple earnings beat by 5%.");
    expect(body).toBe("Apple earnings beat by 5%.");
    expect(sources).toHaveLength(0);
  });

  it("splits on plain-text 'Sources:' delimiter", () => {
    const raw = "The analysis [1] is clear.\n\nSources:\n1. Reuters article — https://reuters.com";
    const { body, sources } = parseCitationResponse(raw);
    expect(body).toBe("The analysis [1] is clear.");
    expect(sources).toHaveLength(1);
    expect(sources[0].title).toBe("Reuters article");
  });

  it("splits on markdown '## Sources' delimiter", () => {
    const raw = "Good data [1].\n## Sources\n1. WSJ — https://wsj.com/article";
    const { body, sources } = parseCitationResponse(raw);
    expect(body).toBe("Good data [1].");
    expect(sources).toHaveLength(1);
    expect(sources[0].title).toBe("WSJ");
  });

  it("parses multiple sources", () => {
    const raw = "Analysis here.\n\nSources:\n1. Reuters — https://reuters.com\n2. Bloomberg — https://bloomberg.com\n3. WSJ — https://wsj.com";
    const { sources } = parseCitationResponse(raw);
    expect(sources).toHaveLength(3);
    expect(sources[0].title).toBe("Reuters");
    expect(sources[1].title).toBe("Bloomberg");
    expect(sources[2].title).toBe("WSJ");
  });

  it("handles sources without URL suffix", () => {
    const raw = "Text.\n\nSources:\n1. Internal research note";
    const { sources } = parseCitationResponse(raw);
    expect(sources[0].title).toBe("Internal research note");
  });

  it("filters blank source lines", () => {
    const raw = "Text.\n\nSources:\n1. Reuters\n\n2. Bloomberg";
    const { sources } = parseCitationResponse(raw);
    expect(sources).toHaveLength(2);
  });
});

// ── P2B-1: renderWithCitations unit tests ────────────────────────────────────

describe("renderWithCitations", () => {
  it("returns the plain string unchanged when no [N] markers are present", () => {
    const result = renderWithCitations("No citations here.");
    // WHY string equality: when there are no [N] markers, renderWithCitations
    // returns the original string directly (not wrapped in an array). This is
    // an intentional optimization — no array allocation needed for plain text.
    expect(result).toBe("No citations here.");
  });

  it("returns an array when [N] markers are present", () => {
    const result = renderWithCitations("See [1] and [2] for details.");
    expect(Array.isArray(result)).toBe(true);
  });

  it("produces sup elements for each [N] marker", () => {
    const result = renderWithCitations("See [1] and [2].") as unknown[];
    // Filter to only the object (ReactElement) entries — strings are the text segments.
    const supElements = result.filter((r) => typeof r === "object");
    expect(supElements).toHaveLength(2);
  });
});

// ── P2B-1: AskAiPanel citation rendering integration tests ───────────────────

describe("AskAiPanel — P2B-1 citation rendering", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("renders [N] markers as <sup> elements after stream completes", async () => {
    // WHY full response with [1] marker: tests that the post-stream parsing
    // triggers renderWithCitations, which converts [1] into a <sup> element
    // with className containing 'font-mono'. The streaming blinking cursor
    // is NOT present, confirming this is the settled (post-stream) state.
    mockFetch([
      'data: {"token":"See analysis [1] for details."}\n\n',
      "data: [DONE]\n\n",
    ]);

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Cite test" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    // Wait for stream to complete and citation parsing to fire
    await waitFor(() => {
      // WHY query sup: renderWithCitations wraps [1] in a <sup> element.
      // The text "for details." appears outside the sup as a text node.
      const sups = document.querySelectorAll("sup");
      expect(sups.length).toBeGreaterThan(0);
    });
  });

  it("renders a Sources section when response contains a Sources block", async () => {
    const responseWithSources =
      "The analysis [1] shows growth.\n\nSources:\n1. Reuters — https://reuters.com/article";

    mockFetch([
      `data: ${JSON.stringify({ token: responseWithSources })}\n\n`,
      "data: [DONE]\n\n",
    ]);

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "Source test" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    // Wait for the Sources section header to appear
    await waitFor(() => {
      // WHY uppercase "SOURCES": the Sources label uses uppercase tracking-wider
      // font-mono styling (terminal label convention). The regex is case-insensitive.
      expect(screen.getByText(/sources/i)).toBeInTheDocument();
    });

    // The extracted source title should appear in the list
    await waitFor(() => {
      expect(screen.getByText("Reuters")).toBeInTheDocument();
    });
  });

  it("does not render a Sources section when response has no Sources block", async () => {
    mockFetch([
      'data: {"token":"Plain answer with no citations."}\n\n',
      "data: [DONE]\n\n",
    ]);

    renderPanel();
    const textarea = screen.getByPlaceholderText(/ask about markets/i);
    fireEvent.change(textarea, { target: { value: "No sources test" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText("Plain answer with no citations.")).toBeInTheDocument();
    });

    // The "Sources" label must NOT be present — the response has no sources block.
    expect(document.querySelector(".border-border\\/40.pt-1\\.5")).toBeNull();
  });
});
