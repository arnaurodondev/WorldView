/**
 * components/shell/AskAiPanel.tsx — Floating mini-chat panel.
 *
 * WHY THIS EXISTS: Traders want a quick AI answer without leaving the page
 * they're reading.  The floating panel lets them ask a one-off question and
 * watch a streamed answer beside their dashboard / instrument view.
 *
 * WHY SSE streaming: chat responses are long (100–500 words).  Streaming
 * shows tokens as they arrive (ChatGPT-style) so the user can read while
 * the model continues generating.  Every second matters on a terminal.
 *
 * WHY native fetch + ReadableStream (not EventSource): EventSource only
 * supports GET; S9's `/api/v1/chat/stream` is POST so we hand-roll the SSE
 * parsing in a ReadableStream reader loop.
 *
 * WHO USES IT: app/(app)/layout.tsx — rendered when TopBar's "Ask AI"
 * button is clicked.
 *
 * DATA SOURCE: S9 POST /api/v1/chat/stream (SSE).
 *
 * DESIGN REFERENCE: PRD-0089 W1 plan §4.7 + DISCUSS-6 + DISCUSS-12.
 *   - Body wrapped in `<AiContentRail>` (F1 primitive — left-2px accent-ai).
 *   - Inline `[N]` citation markers rendered via `<InlineCitationAnchor>`
 *     from F1 instead of the local parseCitationResponse +
 *     renderWithCitations helpers (~310 LOC removed for the consolidation
 *     win documented in cluster 03 of the PRD-0089 investigation).
 */

"use client";
// WHY "use client": uses useState, useEffect (SSE stream), useRef for the
// abort controller + input focus, and dispatches POST fetch + ReadableStream
// — all browser-only APIs.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { X, Send, ExternalLink, Bot } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
// PLAN-0089 K T-20.3 — replace the bespoke `<AiContentRail>+<p>` response
// surface with the new flat `<MessageTurn>` renderer. The `compact` size
// variant trims the role gutter + body padding so the floating panel still
// feels lighter than the full /chat surface. `<CitationStrip>` is composed
// inside `<MessageTurn>` and renders null automatically when there are no
// citations — important for AskAiPanel which receives only `{text|token}`
// SSE events today (no structured citation list on the wire). This brings
// the panel into the Wave K flat-layout family while preserving every
// behaviour from the legacy view: streaming text, error banner, inline
// `[N]` markers (rendered via `withCitationSups` inside MessageTurn's
// LazyMarkdownContent).
import { MessageTurn } from "@/features/chat/components/MessageTurn";
import type { Message } from "@/types/api";
// HF-10: shared price formatter for locale-grouped output ("$4,892.11") in
// both the visible context hint and the LLM system-context builder.
import { formatPrice } from "@/lib/format";

// ── Citation rendering ────────────────────────────────────────────────────
//
// PLAN-0089 K T-20.3: the local `renderCitedText` + `InlineCitationAnchor`
// inline-anchor splitter previously rendered `[N]` markers inside the
// streaming text was REMOVED. The response surface now flows through
// `<MessageTurn size="compact">`, which itself renders the body via
// `<LazyMarkdownContent withCitationSups>` — that path detects `[N]`
// markers and styles them as primary-tinted superscript chips identical
// in appearance to the legacy InlineCitationAnchor `NEWS` variant. The
// terminal-grade visual contract is preserved (same chip colour, same
// hover affordance budget) while the panel inherits the rest of the
// Wave K flat-turn family for free.

// ── Types ─────────────────────────────────────────────────────────────────

interface AskAiPanelProps {
  onClose: () => void;
  /**
   * PLAN-0071 P2A-2: Structured instrument context. When provided, the panel:
   *   1. Displays a context strip ("AAPL · $193.42 · +1.2% · P/E 28.6")
   *   2. Includes system_context in every POST body so the model is
   *      context-aware. Callers on the instrument page pass these from
   *      their CompanyOverview query.
   */
  ticker?: string;
  price?: number;
  priceChangePct?: number;
  fundamentals?: { pe?: number | null; marketCap?: number | null };
  /** Optional raw context hint override — used only outside instrument pages. */
  contextHint?: string;
}

// ── Component ─────────────────────────────────────────────────────────────

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

  // PLAN-0071 P2A-3 — system_context goes into every POST body when the
  // panel is opened from an instrument page so the model already knows what
  // the user is looking at.
  const buildSystemContext = useCallback((): string | undefined => {
    if (!ticker) return undefined;
    const sign = priceChangePct != null && priceChangePct >= 0 ? "+" : "";
    const pricePart = price != null
      ? ` at ${formatPrice(price)}${priceChangePct != null ? ` (${sign}${priceChangePct.toFixed(2)}%)` : ""}`
      : "";
    const pePart = fundamentals?.pe != null ? ` P/E: ${fundamentals.pe.toFixed(1)}.` : "";
    return `User is viewing ${ticker}${pricePart}.${pePart} Answer in the context of this instrument.`;
  }, [ticker, price, priceChangePct, fundamentals]);

  // Display hint mirrors the buildSystemContext logic so the user sees what
  // the assistant knows. Explicit `contextHint` overrides the derived form.
  const displayHint = contextHint ?? (ticker
    ? `Context: ${ticker}${price != null ? ` · ${formatPrice(price)}` : ""}${priceChangePct != null ? ` · ${priceChangePct >= 0 ? "+" : ""}${priceChangePct.toFixed(1)}%` : ""}${fundamentals?.pe != null ? ` · P/E ${fundamentals.pe.toFixed(1)}` : ""}`
    : undefined);

  // PLAN-0089 K T-20.3 — synthetic `Message` shape used to drive `<MessageTurn>`.
  //
  // WHY useMemo: the response text updates on every SSE token tick. Without
  // memoisation we would build a brand-new object reference for the Message
  // every render, defeating any future React.memo guard on MessageTurn.
  // Memoising on (response, isStreaming) keeps re-renders proportional to
  // the data that actually changed.
  //
  // The `citations: []` array is intentional: the AskAiPanel streaming
  // endpoint emits only `{text|token}` payloads today — no citation list
  // on the wire — so the strip will render nothing and the response
  // surface stays compact. When the panel migrates to the structured
  // SSE event stream the citations list will be populated and the strip
  // will surface automatically.
  const syntheticTurn = useMemo<Message>(
    () => ({
      message_id: "__askai_panel__",
      thread_id: "__askai_panel__",
      role: "assistant",
      content: response,
      // created_at left as undefined-style "now" string — MessageMetaStrip
      // gracefully omits the clock when null fields make the strip empty.
      created_at: new Date().toISOString(),
      citations: [],
    }),
    [response],
  );

  // F-027 — refs for the in-flight fetch's AbortController and the textarea
  // focus handle. These are imperative side concerns; storing them in refs
  // avoids re-renders.
  const abortControllerRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Escape key closes the panel (matches the layout-level Esc cascade).
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // F-027 — abort in-flight stream on unmount so the reader loop exits and
  // we don't setState after unmount.
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, []);

  /**
   * handleSend — POST + SSE.  EventSource doesn't support POST so we hand-
   * roll the reader loop and parse `data: <json>\n` lines incrementally,
   * keeping a partial-line buffer between chunks.  DS-007 fix handles the
   * final partial line at stream-end which would otherwise be dropped.
   */
  const handleSend = useCallback(async () => {
    if (!query.trim() || isStreaming || !accessToken) return;

    if (abortControllerRef.current) abortControllerRef.current.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsStreaming(true);
    setResponse("");
    setError(null);

    try {
      const res = await fetch("/api/v1/chat/stream", {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({
          message: query.trim(),
          ...(buildSystemContext() ? { system_context: buildSystemContext() } : {}),
        }),
      });
      if (!res.ok) throw new Error(`Chat error: ${res.status}`);

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          // DS-007 — flush any final partial line still in the buffer.
          if (buffer.startsWith("data: ")) {
            const data = buffer.slice(6);
            if (data !== "[DONE]") {
              try {
                const parsed = JSON.parse(data) as { text?: string; token?: string };
                if (parsed.text ?? parsed.token) {
                  setResponse((prev) => prev + (parsed.text ?? parsed.token));
                }
              } catch {
                /* malformed trailing line — drop */
              }
            }
          }
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6);
          if (data === "[DONE]") {
            setIsStreaming(false);
            return;
          }
          try {
            const parsed = JSON.parse(data) as { text?: string; token?: string };
            if (parsed.text ?? parsed.token) {
              setResponse((prev) => prev + (parsed.text ?? parsed.token));
            }
          } catch {
            /* keep-alive or malformed line — skip */
          }
        }
      }
      setIsStreaming(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed. Please try again.");
      setIsStreaming(false);
    }
  }, [query, isStreaming, accessToken, buildSystemContext]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  return (
    // WHY fixed bottom-10 right-4 z-50: floats above page content but below
    // FlashOverlay (z-[9999]).  bottom-10 lifts the panel above the new
    // 22px StatusBar.  No border-radius — F1 sharp-corner lock.
    <div
      className="fixed bottom-10 right-4 z-50 flex w-80 flex-col border border-border bg-background"
      role="complementary"
      aria-label="AI assistant"
    >
      {/* ── Header ────────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          {/* PLAN-0059 W0 F-VISUAL-022 — accent-ai violet (universal industry
              AI colour).  Primary yellow stays reserved for data CTAs. */}
          <div className="flex h-5 w-5 items-center justify-center bg-[hsl(var(--accent-ai)/0.20)] ring-1 ring-[hsl(var(--accent-ai)/0.30)]">
            <Bot className="h-3 w-3 text-[hsl(var(--accent-ai))]" />
          </div>
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-foreground">
            Analyst
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => {
              router.push("/chat");
              onClose();
            }}
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

      {/* ── Context hint ──────────────────────────────────── */}
      {displayHint && (
        <div className="border-t border-border bg-muted/30 px-3 py-1.5 text-[10px] text-muted-foreground">
          {displayHint}
        </div>
      )}

      {/* ── Response area (PLAN-0089 K T-20.3) ─────────────────────────────
          WHY THIS BLOCK CHANGED: pre-T-20 used a hand-rolled `<AiContentRail>`
          + raw `<p>` rendering the stream text with the local
          `renderCitedText` helper for inline `[N]` markers. The new Wave K
          flat-turn renderer (`<MessageTurn size="compact">`) gives the
          floating panel:
            • the same role-gutter + accent-rail visual as /chat (so the
              user reads AskAiPanel and /chat in the same vocabulary);
            • automatic `MessageMetaStrip` (omitted today because the
              streaming endpoint here does not emit metadata events, but
              future-proof for when it does);
            • automatic `CitationStrip` rendering — empty array → null,
              so no behaviour change while AskAiPanel sees no citations.

          WHY a synthetic `Message` (not a richer prop API):
            MessageTurn takes a `turn: Message`. The mini panel's SSE feed
            today gives us only `text|token` events — we synthesise a
            minimal Message (assistant role, in-flight content, empty
            citations) and pass `isStreaming` so the rail and meta strip
            both flip into in-flight mode. When the stream completes we
            drop `isStreaming` so the turn reads "done".

          ERROR BANNER STAYS LOCAL: a streamed error is still a single
          line of destructive text — no need to thread it through
          MessageTurn (which is content-shaped). */}
      {(response || isStreaming || error) && (
        <div className="max-h-64 overflow-y-auto px-3 py-3" data-testid="askai-response">
          {error ? (
            <p className="text-xs text-destructive">{error}</p>
          ) : (
            <MessageTurn turn={syntheticTurn} size="compact" isStreaming={isStreaming} />
          )}
        </div>
      )}

      {/* ── Input area ────────────────────────────────────── */}
      <div className="flex items-end gap-2 border-t border-border p-3">
        <textarea
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about markets, entities…"
          rows={2}
          disabled={isStreaming}
          // No border-radius — F1 sharp-corner lock.  text-[11px] keeps the
          // terminal density (HIGH-015).
          className="flex-1 resize-none border border-border bg-muted px-2 py-1 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]"
        />
        {/* F-VISUAL-027 — explicit disabled tokens, not opacity dimming. */}
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
