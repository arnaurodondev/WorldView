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
 * DESIGN: W1 §4.7 — wraps response body in AiContentRail (F1 primitive, --accent-ai
 * violet left rail) and uses InlineCitationAnchor (F1 primitive) for [N] markers
 * instead of a hand-rolled renderWithCitations function.
 *
 * WHO USES IT: app/(app)/layout.tsx — rendered when TopBar's "Ask AI" button is clicked
 * DATA SOURCE: S9 POST /api/v1/chat/stream (SSE)
 * DESIGN REFERENCE: PRD-0028 §6.5 AskAiPanel; PRD-0089 F1 §3.2
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
import { formatPrice } from "@/lib/format";
// F1 primitives — W1 §4.7
import { AiContentRail } from "@/components/primitives/AiContentRail";
import { InlineCitationAnchor } from "@/components/primitives/InlineCitationAnchor";

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
 * parseCitationResponse — split raw response into prose body + sources list.
 * Called post-stream (not mid-stream) to avoid false splits on partial delimiters.
 * Handles both "## Sources\n" (markdown) and "\n\nSources:\n" (plain-text) emitters.
 * WHY exported: used by AskAiPanel.test.tsx as unit tests for the parse logic.
 */
export function parseCitationResponse(raw: string): {
  body: string;
  sources: ParsedSource[];
} {
  const PLAIN_SEP = "\n\nSources:\n";
  const MD_SEP = "\n## Sources\n";

  let sepIdx = raw.indexOf(PLAIN_SEP);
  let sepLen = PLAIN_SEP.length;
  if (sepIdx === -1) {
    sepIdx = raw.indexOf(MD_SEP);
    sepLen = MD_SEP.length;
  }

  if (sepIdx === -1) {
    return { body: raw, sources: [] };
  }

  const body = raw.slice(0, sepIdx).trimEnd();
  const sourceBlock = raw.slice(sepIdx + sepLen);

  const sources: ParsedSource[] = sourceBlock
    .split("\n")
    .filter((line) => /^\d+\.\s/.test(line.trim()))
    .map((line) => {
      const withoutNum = line.trim().replace(/^\d+\.\s*/, "");
      const dashIdx = withoutNum.search(/ [—–] https?:\/\//);
      const title = dashIdx !== -1 ? withoutNum.slice(0, dashIdx).trim() : withoutNum.trim();
      return { title };
    })
    .filter((s) => s.title.length > 0);

  return { body, sources };
}

/**
 * renderWithCitations — replace `[N]` markers with InlineCitationAnchor chips.
 * Uses kind="NEWS" (RAG retrieval path). F1 primitive provides consistent color
 * + ARIA across chat, brief, and this panel (W1 §4.7 — no hand-rolled <sup>).
 * WHY exported: used by AskAiPanel.test.tsx unit tests.
 */
export function renderWithCitations(text: string): ReactNode {
  const CITATION_RE = /\[(\d+)\]/g;
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let hasMarkers = false;

  while ((match = CITATION_RE.exec(text)) !== null) {
    hasMarkers = true;
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const citNum = match[1];
    parts.push(
      <InlineCitationAnchor
        key={`cite-${match.index}`}
        kind="NEWS"
        id={citNum}
        label={`[${citNum}]`}
        density="terminal"
      />,
    );
    lastIndex = CITATION_RE.lastIndex;
  }

  if (!hasMarkers) return text;

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
  // below runs the full parse once and populates these two fields.
  const [parsedBody, setParsedBody] = useState<string>("");
  const [parsedSources, setParsedSources] = useState<ParsedSource[]>([]);

  const buildSystemContext = useCallback((): string | undefined => {
    if (!ticker) return undefined;
    const sign = priceChangePct != null && priceChangePct >= 0 ? "+" : "";
    const pricePart = price != null
      ? ` at ${formatPrice(price)}${priceChangePct != null ? ` (${sign}${priceChangePct.toFixed(2)}%)` : ""}`
      : "";
    const pePart = fundamentals?.pe != null ? ` P/E: ${fundamentals.pe.toFixed(1)}.` : "";
    return `User is viewing ${ticker}${pricePart}.${pePart} Answer in the context of this instrument.`;
  }, [ticker, price, priceChangePct, fundamentals]);

  const displayHint = contextHint ?? (ticker
    ? `Context: ${ticker}${price != null ? ` · ${formatPrice(price)}` : ""}${priceChangePct != null ? ` · ${priceChangePct >= 0 ? "+" : ""}${priceChangePct.toFixed(1)}%` : ""}${fundamentals?.pe != null ? ` · P/E ${fundamentals.pe.toFixed(1)}` : ""}`
    : undefined);

  // WHY useRef for EventSource: the SSE connection is imperative infrastructure.
  const eventSourceRef = useRef<EventSource | null>(null);
  // F-027: AbortController so the fetch SSE stream can be cancelled on unmount.
  const abortControllerRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, []);

  // ── P2B-1: parse citations once streaming completes ──────────────────────
  useEffect(() => {
    if (!response) {
      setParsedBody("");
      setParsedSources([]);
      return;
    }
    if (isStreaming) return;
    const { body, sources } = parseCitationResponse(response);
    setParsedBody(body);
    setParsedSources(sources);
  }, [response, isStreaming]);

  // handleSend — POST + SSE via fetch+ReadableStream (EventSource only supports GET)
  const handleSend = useCallback(async () => {
    if (!query.trim() || isStreaming || !accessToken) return;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
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
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${accessToken}`,
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
          // DS-007: process final partial line that was not terminated with \n.
          if (buffer.startsWith("data: ")) {
            const data = buffer.slice(6);
            if (data !== "[DONE]") {
              try {
                const parsed = JSON.parse(data) as { text?: string; token?: string };
                if (parsed.text ?? parsed.token) {
                  setResponse((prev) => prev + (parsed.text ?? parsed.token));
                }
              } catch { /* partial line — skip */ }
            }
          }
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
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
            } catch { /* non-JSON keep-alive line — skip */ }
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
    // WHY rounded-[2px]: terminal radius rule. F-QA-12: bottom-10 lifts above 24px StatusBar.
    <div
      className="fixed bottom-10 right-4 z-50 flex w-80 flex-col rounded-[2px] border border-border bg-background"
      role="complementary"
      aria-label="AI assistant"
    >
      {/* ── Header ─────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          {/* PLAN-0059 W0 F-VISUAL-022: --accent-ai violet */}
          <div className="flex h-5 w-5 items-center justify-center rounded-[2px] bg-[hsl(var(--accent-ai)/0.20)] ring-1 ring-[hsl(var(--accent-ai)/0.30)]">
            <Bot className="h-3 w-3 text-[hsl(var(--accent-ai))]" />
          </div>
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-foreground">Analyst</span>
        </div>
        <div className="flex items-center gap-1">
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

      {/* ── Context hint (instrument page floater) ──────────────────────────
          WHY always render when present (not gated on !response): the hint must
          stay visible across the full conversation lifecycle so the user knows the
          assistant still has page context after the first answer. */}
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
            /*
             * WHY AiContentRail (W1 §4.7): every AI-generated text surface must
             * carry the violet left rail so analysts can immediately distinguish
             * model output from source data (PRD-0089 F1 §3.2 + FU-DISCUSS-12).
             */
            <AiContentRail>
              {/*
               * WHY two render paths:
               * STREAMING: render `response` verbatim — parsing mid-stream could
               * split on a half-arrived "Sources:" delimiter and truncate the body.
               * SETTLED: render parsedBody through renderWithCitations() which
               * converts [N] tokens into InlineCitationAnchor chips.
               */}
              <p className="whitespace-pre-wrap text-[11px] text-foreground">
                {isStreaming
                  ? (
                    <>
                      {response}
                      {/* Static cursor while streaming — no animate-pulse (HIGH-015) */}
                      <span className="ml-0.5 inline-block h-4 w-0.5 bg-primary" />
                    </>
                  )
                  : renderWithCitations(parsedBody)}
              </p>

              {/* P2B-1: Sources list — only after streaming completes */}
              {!isStreaming && parsedSources.length > 0 && (
                <div className="mt-2 border-t border-border/40 pt-1.5">
                  <p className="mb-1 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                    Sources
                  </p>
                  <ol className="space-y-0.5">
                    {parsedSources.map((src, i) => (
                      <li key={i} className="flex items-baseline gap-1 text-[10px]">
                        <span className="shrink-0 font-mono text-[9px] text-muted-foreground">
                          {i + 1}.
                        </span>
                        <span className="text-foreground/70">{src.title}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </AiContentRail>
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
          // WHY rounded-[2px]: terminal radius rule. text-[11px]: terminal density.
          className="flex-1 resize-none rounded-[2px] border border-border bg-muted px-2 py-1 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]"
        />
        {/* PLAN-0059 W0 F-VISUAL-022: --accent-ai violet (was amber-500/90) */}
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
