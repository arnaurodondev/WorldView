/**
 * components/shell/AskAiPanel.tsx — Floating mini-chat panel
 *
 * WHY THIS EXISTS: Traders often want a quick AI answer without navigating away
 * from their current view (e.g., "What's the macro context for this earnings beat?").
 * The floating panel lets them ask a one-off question, get a streamed answer,
 * and close the panel — all without leaving the Dashboard or Instrument Detail.
 *
 * WHY SSE streaming (not fetch + await):
 * Chat responses can be long (100–500 words). Streaming shows the answer as it
 * generates (like ChatGPT) rather than making the user wait for the full response.
 * Users can start reading immediately — better UX for a finance terminal where
 * every second counts.
 *
 * WHY native EventSource:
 * EventSource is the standard browser SSE API. It handles reconnection automatically.
 * No library needed (no socket.io, no custom fetch-based streaming).
 *
 * WHY fixed bottom-right (not modal):
 * A floating panel doesn't block the current page view. The user can read their
 * dashboard and the AI answer simultaneously, side-by-side.
 *
 * WHO USES IT: app/(app)/layout.tsx — rendered when TopBar's "Ask AI" button is clicked
 * DATA SOURCE: S9 POST /api/v1/chat/stream (SSE)
 * DESIGN REFERENCE: PRD-0028 §6.5 AskAiPanel
 */

"use client";
// WHY "use client": Uses useState, useEffect (SSE stream), EventSource (browser API),
// useRef (textarea focus, stream abort), and keyboard event handlers.

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { X, Send, ExternalLink, Bot } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
// HF-10: shared price formatter for locale-grouped output ("$4,892.11").
// Used in both the visible context hint and the LLM system-context builder.
import { formatPrice } from "@/lib/format";

// ── Citation helpers ──────────────────────────────────────────────────────────

/**
 * ParsedSource — a single extracted source entry from the "Sources:" block.
 * WHY only title (not URL): the AskAiPanel is a mini floating panel with very
 * limited vertical real estate. Showing a full URL would overflow the 320px
 * panel width and truncation makes URLs hard to read. The title alone is
 * sufficient for the analyst to understand what was cited — they can open the
 * full Chat page (/chat) to see clickable URLs via CitationList.
 */
interface ParsedSource {
  title: string;
}

/**
 * parseCitationResponse — split the raw streaming response into body + sources.
 *
 * WHY called post-stream (not mid-stream): parsing mid-stream produces partial
 * false positives — a half-streamed "Sources:" header could match prematurely
 * and truncate the visible body. Post-stream parsing waits until the full text
 * is available, so the split is always correct.
 *
 * WHY two delimiters: S8 sometimes emits "## Sources" (markdown header) and
 * sometimes "\n\nSources:" (plain text). We check both to stay resilient to
 * minor prompt-format variations between model versions.
 *
 * @returns { body, sources } — body is the prose to render; sources is the list
 *   of extracted entries (empty array if no Sources block was found).
 */
export function parseCitationResponse(raw: string): {
  body: string;
  sources: ParsedSource[];
} {
  // Try both delimiter styles. Priority: plain-text "\n\nSources:\n" > "## Sources".
  const PLAIN_SEP = "\n\nSources:\n";
  const MD_SEP = "\n## Sources\n";

  let sepIdx = raw.indexOf(PLAIN_SEP);
  let sepLen = PLAIN_SEP.length;
  if (sepIdx === -1) {
    sepIdx = raw.indexOf(MD_SEP);
    sepLen = MD_SEP.length;
  }

  if (sepIdx === -1) {
    // No sources section — return full response as body.
    return { body: raw, sources: [] };
  }

  const body = raw.slice(0, sepIdx).trimEnd();
  const sourceBlock = raw.slice(sepIdx + sepLen);

  // Parse each numbered line: "1. Title — URL" or just "1. Title"
  // WHY loose regex (not strict): source lines may not have URLs, may use
  // en-dash "–" instead of em-dash "—", or may omit the dash altogether.
  // We extract everything after the "N. " prefix as the title display string.
  const sources: ParsedSource[] = sourceBlock
    .split("\n")
    .filter((line) => /^\d+\.\s/.test(line.trim()))
    .map((line) => {
      // Strip leading "N. " and, if present, cut the URL suffix after " — " or " – ".
      const withoutNum = line.trim().replace(/^\d+\.\s*/, "");
      const dashIdx = withoutNum.search(/ [—–] https?:\/\//);
      const title = dashIdx !== -1 ? withoutNum.slice(0, dashIdx).trim() : withoutNum.trim();
      return { title };
    })
    .filter((s) => s.title.length > 0);

  return { body, sources };
}

/**
 * renderWithCitations — convert raw response text into JSX, replacing
 * "[N]" citation markers with styled <sup> elements.
 *
 * WHY citation rendering: AskAiPanel accumulates SSE tokens. S8 injects [N]
 * markers from retrieved chunks. Parsing post-stream (not mid-stream) prevents
 * partial-parse flicker — the full response is available before any rendering.
 *
 * WHY <sup> with bg-primary/10: the terminal design system uses primary/10 chip
 * backgrounds for inline reference markers (same treatment as the CitationList
 * pill style in the full Chat page — consistent visual vocabulary across surfaces).
 */
export function renderWithCitations(text: string): ReactNode {
  // Split on [N] markers (one or more digits). The capture group (\d+) keeps
  // the number in the resulting array so we know the citation index.
  const CITATION_RE = /\[(\d+)\]/g;
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let hasMarkers = false;

  while ((match = CITATION_RE.exec(text)) !== null) {
    hasMarkers = true;
    // Push the plain text segment before this citation marker.
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    // Push the styled superscript citation marker.
    const citNum = match[1];
    parts.push(
      <sup
        key={`cite-${match.index}`}
        // WHY these classes: rounded-[2px] = terminal 2px radius rule;
        // bg-primary/10 + text-primary = same chip treatment as CitationList pills;
        // font-mono text-[8px] = minimum legible size for inline index numbers.
        className="cursor-default rounded-[2px] bg-primary/10 px-0.5 text-[8px] font-mono text-primary"
        title={`Citation ${citNum}`}
      >
        [{citNum}]
      </sup>,
    );
    lastIndex = CITATION_RE.lastIndex;
  }

  // WHY early return when no markers: if no [N] patterns were found, skip the
  // array construction and return the original string directly. This makes the
  // return type consistent for callers that test `typeof result === "string"`,
  // and avoids an unnecessary single-element array allocation.
  if (!hasMarkers) return text;

  // Push any remaining text after the last citation marker.
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface AskAiPanelProps {
  onClose: () => void;
  /**
   * PLAN-0071 P2A-2: Structured instrument context. When provided, the panel:
   *   1. Displays a context strip ("AAPL · $193.42 · +1.2% · P/E 28.6")
   *   2. Includes system_context in every POST body so the model is context-aware
   * Callers on the instrument page pass these from their CompanyOverview query.
   */
  ticker?: string;
  price?: number;
  priceChangePct?: number;
  fundamentals?: { pe?: number | null; marketCap?: number | null };
  /**
   * Optional raw context hint override. When `ticker` is present, a hint is
   * derived automatically — this prop only needed for non-instrument contexts.
   */
  contextHint?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AskAiPanel({
  onClose,
  ticker,
  price,
  priceChangePct,
  fundamentals,
  contextHint,
}: AskAiPanelProps) {
  const router = useRouter();
  const { accessToken } = useAuth();

  const [query, setQuery] = useState("");
  const [response, setResponse] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── P2B-1: parsed citation state ──────────────────────────────────────────
  // WHY separate state for parsedBody + parsedSources:
  // During streaming we display `response` directly (no parsing — partial text
  // would produce false splits). Once isStreaming flips to false the useEffect
  // below runs the full parse once and populates these two fields. Components
  // below then render parsedBody (with renderWithCitations) and the Sources list.
  const [parsedBody, setParsedBody] = useState<string>("");
  const [parsedSources, setParsedSources] = useState<ParsedSource[]>([]);

  // PLAN-0071 P2A-3: build system_context from structured props when on an instrument page.
  // Returns undefined (not included in body) when no ticker is available.
  const buildSystemContext = useCallback((): string | undefined => {
    if (!ticker) return undefined;
    const sign = priceChangePct != null && priceChangePct >= 0 ? "+" : "";
    // HF-10: formatPrice gives the LLM a locale-grouped, null-safe price.
    const pricePart = price != null
      ? ` at ${formatPrice(price)}${priceChangePct != null ? ` (${sign}${priceChangePct.toFixed(2)}%)` : ""}`
      : "";
    const pePart = fundamentals?.pe != null ? ` P/E: ${fundamentals.pe.toFixed(1)}.` : "";
    return `User is viewing ${ticker}${pricePart}.${pePart} Answer in the context of this instrument.`;
  }, [ticker, price, priceChangePct, fundamentals]);

  // Derive the display hint: prefer explicit contextHint, fall back to structured props.
  const displayHint = contextHint ?? (ticker
    ? `Context: ${ticker}${price != null ? ` · ${formatPrice(price)}` : ""}${priceChangePct != null ? ` · ${priceChangePct >= 0 ? "+" : ""}${priceChangePct.toFixed(1)}%` : ""}${fundamentals?.pe != null ? ` · P/E ${fundamentals.pe.toFixed(1)}` : ""}`
    : undefined);

  // WHY useRef for EventSource: the SSE connection is imperative infrastructure,
  // not UI state. Storing it in a ref avoids unnecessary re-renders on connect/disconnect.
  const eventSourceRef = useRef<EventSource | null>(null);
  // F-027: AbortController ref so the fetch SSE stream can be cancelled when the
  // panel unmounts or a new request starts. Without this, an in-flight stream would
  // continue consuming memory and calling setState on an unmounted component.
  const abortControllerRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Focus input when panel opens
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Escape key closes panel
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // F-027: Cleanup SSE stream on unmount — abort the fetch so the reader loop exits.
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      // Abort any in-flight fetch stream to prevent setState-after-unmount.
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, []);

  // ── P2B-1: parse citations once streaming completes ──────────────────────
  // WHY post-stream (not during streaming): parsing mid-stream on every token
  // append could produce false "Sources:" splits when the delimiter is still
  // arriving. Waiting for isStreaming=false guarantees the full response is
  // available before we attempt to find the Sources section.
  // WHY reset on new `response = ""`: setResponse("") fires at the start of
  // every new send (see handleSend). That clears parsedBody + parsedSources so
  // the previous answer's sources don't linger while the new stream runs.
  useEffect(() => {
    if (!response) {
      // New query started (or panel opened with no prior answer) — clear parsed state.
      setParsedBody("");
      setParsedSources([]);
      return;
    }
    if (isStreaming) {
      // Still streaming — render raw `response` (see JSX below). Skip parse.
      return;
    }
    // Stream complete and we have a non-empty response — parse once.
    const { body, sources } = parseCitationResponse(response);
    setParsedBody(body);
    setParsedSources(sources);
  }, [response, isStreaming]);

  /**
   * handleSend — start streaming a chat response
   *
   * WHY POST + SSE (not GET + SSE):
   * The query text can be long. POST body is not logged or size-limited like query params.
   * The S9 endpoint accepts POST and returns SSE (Content-Type: text/event-stream).
   *
   * WHY manual fetch + ReadableStream (not EventSource):
   * EventSource only supports GET requests. For POST + SSE, we use fetch with
   * response.body.getReader() to manually parse the SSE stream.
   */
  const handleSend = useCallback(async () => {
    if (!query.trim() || isStreaming || !accessToken) return;

    // Close any existing stream
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    // F-027: abort any in-flight fetch stream before starting a new one.
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsStreaming(true);
    setResponse("");
    setError(null);

    try {
      const res = await fetch("/api/v1/chat/stream", {
        method: "POST",
        // F-027: pass the abort signal so the fetch is cancelled on unmount.
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          // WHY Authorization header: S9 requires Bearer token for all authenticated endpoints
          "Authorization": `Bearer ${accessToken}`,
        },
        body: JSON.stringify({
          message: query.trim(),
          // PLAN-0071 P2A-3: include system_context when on an instrument page
          // so the model answers in context without the user re-stating the ticker.
          ...(buildSystemContext() ? { system_context: buildSystemContext() } : {}),
          // WHY no thread_id: mini-panel is stateless (no conversation history).
          // Full conversation threads are in the Chat page (/chat).
        }),
      });

      if (!res.ok) {
        throw new Error(`Chat error: ${res.status}`);
      }

      // Read the SSE stream incrementally
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      // Parse SSE format: "data: <token>\n\n"
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          // DS-007 fix: after the stream ends, the buffer may still contain a final
          // partial line (e.g., "data: {\"token\":\"last\"}" without a trailing \n).
          // Without this block, the final token would be silently discarded because
          // lines.pop() always moves the last (potentially incomplete) line back into
          // the buffer, and the outer loop exits before we process it.
          if (buffer.startsWith("data: ")) {
            const data = buffer.slice(6);
            if (data !== "[DONE]") {
              try {
                const parsed = JSON.parse(data) as { text?: string; token?: string };
                if (parsed.text ?? parsed.token) {
                  setResponse((prev) => prev + (parsed.text ?? parsed.token));
                }
              } catch {
                // Partial/malformed line at stream boundary — skip
              }
            }
          }
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        // Process complete SSE lines
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? ""; // keep incomplete last line for next chunk

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (data === "[DONE]") {
              // WHY [DONE] sentinel: S9 sends this to signal stream completion
              setIsStreaming(false);
              return;
            }
            try {
              const parsed = JSON.parse(data) as { text?: string; token?: string };
              if (parsed.text ?? parsed.token) {
                // Append each token as it streams in — creates the "typing" effect
                // WHY text ?? token: S8 SSE emitter sends {"text": ...} (AI-006 fix)
                setResponse((prev) => prev + (parsed.text ?? parsed.token));
              }
            } catch {
              // Some lines may not be JSON (e.g., empty keep-alive lines) — skip
            }
          }
        }
      }

      setIsStreaming(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed. Please try again.");
      setIsStreaming(false);
    }
  }, [query, isStreaming, accessToken, buildSystemContext]);

  // Send on Enter (Shift+Enter = newline)
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  return (
    // WHY fixed bottom-4 right-4: floats in the corner over all page content.
    // WHY z-50: below FlashOverlay (z-[9999]) but above page content (z-0).
    <div
      // WHY rounded-[2px] (was rounded-lg): terminal 2px radius rule applies to panels.
      // F-QA-12: bottom-10 lifts the panel above the 24px StatusBar so its
      // bottom border doesn't visually merge with the bar.
      className="fixed bottom-10 right-4 z-50 flex w-80 flex-col rounded-[2px] border border-border bg-background"
      role="complementary"
      aria-label="AI assistant"
    >
      {/* ── Header ─────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          {/* PLAN-0059 W0 F-VISUAL-022: --accent-ai violet (was amber-500/400).
              WHY violet: universal industry AI color (Anthropic, OpenAI, Copilot, Notion AI).
              Amber was bypassing the token system (Tailwind default) and conflicted with
              --warning amber. Primary yellow (#FFD60A) remains reserved for data CTAs. */}
          <div className="flex h-5 w-5 items-center justify-center rounded-[2px] bg-[hsl(var(--accent-ai)/0.20)] ring-1 ring-[hsl(var(--accent-ai)/0.30)]">
            <Bot className="h-3 w-3 text-[hsl(var(--accent-ai))]" />
          </div>
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-foreground">Analyst</span>
        </div>
        <div className="flex items-center gap-1">
          {/* Link to full chat page */}
          <button
            onClick={() => { router.push("/chat"); onClose(); }}
            className="p-1 text-muted-foreground hover:text-foreground"
            title="Open full chat"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onClose}
            className="p-1 text-muted-foreground hover:text-foreground"
            aria-label="Close AI panel"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* ── Context hint (optional, instrument-page floater) ─────────────
          Surfaces a quiet one-liner so the user knows the assistant is
          aware of the current page context.
          F-QA-10 fix: always render the hint when supplied — the prior
          `&& !response && !isStreaming && !error` made the hint vanish
          after the first answer streamed, so the user re-typed without
          any indication that the assistant still had page context.
          The hint sits ABOVE the response area, above the input slot,
          so it stays visible across the full conversation lifecycle.
          We do NOT auto-prepend it to the user's typed message — that
          would be magical and could leak page state into transcripts the
          user might not want shared. */}
      {displayHint && (
        <div className="border-t border-border bg-muted/30 px-3 py-1.5 text-[10px] text-muted-foreground">
          {displayHint}
        </div>
      )}

      {/* ── Response area ────────────────────────────── */}
      {(response || isStreaming || error) && (
        <div className="max-h-64 overflow-y-auto px-3 py-3">
          {error ? (
            <p className="text-xs text-destructive">{error}</p>
          ) : (
            <>
              {/*
               * WHY two render paths (streaming vs settled):
               *
               * STREAMING: render `response` verbatim (no citation parse).
               * Parsing mid-stream could split on a half-arrived "Sources:"
               * delimiter and truncate the visible body. The blinking cursor
               * signals to the user that the answer is still generating.
               *
               * SETTLED (isStreaming=false): render `parsedBody` through
               * renderWithCitations() which converts [N] tokens to styled <sup>
               * elements, then append the Sources section if sources were found.
               * WHY post-hoc sources: S8 appends a plain-text Sources block at
               * the end of the response. Extracting it into a distinct UI region
               * (bordered list) separates "answer" from "references" — the same
               * visual convention used in the full Chat page's CitationList.
               */}
              {/* HIGH-015: animate-pulse removed from cursor — Bloomberg terminal mandate.
                  text-sm → text-[11px] for terminal density alignment. */}
              <p className="whitespace-pre-wrap text-[11px] text-foreground">
                {isStreaming
                  ? (
                    <>
                      {response}
                      {/* Static cursor while streaming — no animate-pulse per HIGH-015 */}
                      <span className="ml-0.5 inline-block h-4 w-0.5 bg-primary" />
                    </>
                  )
                  : renderWithCitations(parsedBody)}
              </p>

              {/* P2B-1: Sources section — only rendered after streaming completes
                  and only when the response contained a Sources block.
                  WHY bordered top + "Sources" label: visually separates the
                  answer body from the reference list, matching the CitationList
                  pill style in the full Chat thread (consistent vocabulary). */}
              {!isStreaming && parsedSources.length > 0 && (
                <div className="mt-2 border-t border-border/40 pt-1.5">
                  <p className="mb-1 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                    Sources
                  </p>
                  <ol className="space-y-0.5">
                    {parsedSources.map((src, i) => (
                      <li key={i} className="flex items-baseline gap-1 text-[10px]">
                        {/* WHY font-mono number: matches the [N] sup style — monospace
                            indices pair well with monospace citation markers in the body. */}
                        <span className="shrink-0 font-mono text-[9px] text-muted-foreground">
                          {i + 1}.
                        </span>
                        <span className="text-foreground/70">{src.title}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── Input area ───────────────────────────────── */}
      <div className="flex items-end gap-2 border-t border-border p-3">
        <textarea
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about markets, entities…"
          rows={2}
          disabled={isStreaming}
          // WHY rounded-[2px] (was rounded-md): terminal 2px radius rule
          // text-sm → text-[11px]: terminal density alignment (HIGH-015)
          className="flex-1 resize-none rounded-[2px] border border-border bg-muted px-2 py-1 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]"
        />
        {/* PLAN-0059 W0 F-VISUAL-022: --accent-ai violet bg (was amber-500/90).
            WHY text-white: --accent-ai (#A855F7) has medium luminance — white reaches
            ~5:1 contrast (AA) whereas black on violet is harder to read at 14px+ weight.
            WHY explicit disabled tokens (was disabled:opacity-40): F-VISUAL-027 fix —
            opacity dimming yields sub-AA contrast. Explicit tokens desaturate, not vanish. */}
        <Button
          size="sm"
          onClick={() => void handleSend()}
          disabled={!query.trim() || isStreaming}
          className="h-8 shrink-0 gap-1.5 border-0 bg-[hsl(var(--accent-ai)/0.90)] px-3 text-xs font-semibold text-white hover:bg-[hsl(var(--accent-ai))] disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))]"
          aria-label="Send message"
        >
          <Send className="h-3 w-3" />
          Send
        </Button>
      </div>
    </div>
  );
}
