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

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { X, Send, ExternalLink, Bot } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { AiContentRail } from "@/components/primitives/AiContentRail";
import { InlineCitationAnchor } from "@/components/primitives/InlineCitationAnchor";
// HF-10: shared price formatter for locale-grouped output ("$4,892.11") in
// both the visible context hint and the LLM system-context builder.
import { formatPrice } from "@/lib/format";

// ── Citation rendering (single primitive — DISCUSS-6) ─────────────────────

/**
 * renderCitedText — split a chat response on `[N]` markers and substitute
 * the F1 `<InlineCitationAnchor>` primitive for each one. This is the
 * trivial replacement for the old parseCitationResponse +
 * renderWithCitations pair: the primitive owns the visual treatment (colour,
 * underline, hover preview slot), so all we do here is the regex split.
 *
 * The primitive accepts `kind` per citation; AskAiPanel does not receive
 * structured kind information from the streaming endpoint so we tag every
 * marker as `NEWS` — neutral foreground colour, matches the muted look the
 * old `<sup>` chip carried.  The /chat page (linked via the ExternalLink
 * button in the header) shows the structured kind-aware citation list when
 * the user wants the full reference set.
 */
// Sec F-002 (QA 2026-05-21): cap citation-id length at 6 digits.
// `\d+` matches arbitrarily long digit runs; a degenerate SSE stream
// returning `[999999999999...]` would otherwise produce a huge DOM
// string in the aria-label + label slots. Six digits covers every
// realistic citation count (a chat response with >1M chunks doesn't
// exist) and bounds the worst case to ~50 chars per anchor.
const MAX_CITATION_ID_LEN = 6;

function renderCitedText(text: string) {
  const CITATION_RE = /\[(\d+)\]/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CITATION_RE.exec(text)) !== null) {
    const n = match[1];
    // Sec F-002: skip pathological markers — keep their literal text in
    // the body rather than rendering as a citation anchor.
    if (n.length > MAX_CITATION_ID_LEN) continue;
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    parts.push(
      <InlineCitationAnchor
        key={`cite-${match.index}`}
        kind="NEWS"
        id={n}
        label={`[${n}]`}
        density="compact"
      />,
    );
    lastIndex = CITATION_RE.lastIndex;
  }
  if (lastIndex === 0) return text;
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

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

      {/* ── Response area ─────────────────────────────────── */}
      {(response || isStreaming || error) && (
        <div className="max-h-64 overflow-y-auto px-3 py-3" data-testid="askai-response">
          {error ? (
            <p className="text-xs text-destructive">{error}</p>
          ) : (
            // F1 AiContentRail — 2px accent-ai left rail signals "this is
            // model-generated narrative" consistently with the brief, chat
            // bubbles, and Quote tab AI banner (DISCUSS-12 / C-07).
            <AiContentRail>
              {/* HIGH-015 — static cursor while streaming, no animate-pulse. */}
              <p className="whitespace-pre-wrap text-[11px] text-foreground">
                {isStreaming ? (
                  <>
                    {response}
                    <span className="ml-0.5 inline-block h-4 w-0.5 bg-primary" />
                  </>
                ) : (
                  // F1 InlineCitationAnchor replaces the local
                  // renderWithCitations helper — single primitive owns the
                  // [N] visual treatment across chat, brief, Quote footer.
                  renderCitedText(response)
                )}
              </p>
            </AiContentRail>
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
