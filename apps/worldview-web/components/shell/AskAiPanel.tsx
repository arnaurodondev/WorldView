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
import { useRouter } from "next/navigation";
import { X, Send, ExternalLink, Bot } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";

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

  // PLAN-0071 P2A-3: build system_context from structured props when on an instrument page.
  // Returns undefined (not included in body) when no ticker is available.
  const buildSystemContext = useCallback((): string | undefined => {
    if (!ticker) return undefined;
    const sign = priceChangePct != null && priceChangePct >= 0 ? "+" : "";
    const pricePart = price != null
      ? ` at $${price.toFixed(2)}${priceChangePct != null ? ` (${sign}${priceChangePct.toFixed(2)}%)` : ""}`
      : "";
    const pePart = fundamentals?.pe != null ? ` P/E: ${fundamentals.pe.toFixed(1)}.` : "";
    return `User is viewing ${ticker}${pricePart}.${pePart} Answer in the context of this instrument.`;
  }, [ticker, price, priceChangePct, fundamentals]);

  // Derive the display hint: prefer explicit contextHint, fall back to structured props.
  const displayHint = contextHint ?? (ticker
    ? `Context: ${ticker}${price != null ? ` · $${price.toFixed(2)}` : ""}${priceChangePct != null ? ` · ${priceChangePct >= 0 ? "+" : ""}${priceChangePct.toFixed(1)}%` : ""}${fundamentals?.pe != null ? ` · P/E ${fundamentals.pe.toFixed(1)}` : ""}`
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
            <p className="whitespace-pre-wrap text-sm text-foreground">
              {response}
              {/* Blinking cursor while streaming */}
              {isStreaming && (
                <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-primary" />
              )}
            </p>
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
          className="flex-1 resize-none rounded-[2px] border border-border bg-muted px-2 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]"
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
