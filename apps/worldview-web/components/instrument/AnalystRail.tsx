/**
 * components/instrument/AnalystRail.tsx — Docked analyst AI rail for the instrument page
 *
 * PLAN-0071 Phase 4 (P5 in plan doc).
 *
 * WHY THIS EXISTS: The floating AskAiPanel (bottom-right fixed) is disconnected from
 * the instrument page layout — it overlaps content and has no persistent context strip.
 * The AnalystRail replaces it on instrument pages with a docked, resizable right panel
 * that stays visible alongside the chart and tabs, mirrors the Bloomberg MOSB pane design.
 *
 * WHY docked (not floating): floating panels conflict with tables, charts, and other
 * positioned elements. A docked rail is predictable — it shifts the main content left
 * and the user always knows where it is.
 *
 * WHY stateful message history (unlike AskAiPanel): the rail is persistent while the
 * user is on the instrument page. They should be able to scroll back and see prior
 * answers without re-asking. Messages reset when the rail is closed.
 *
 * WHY SSE streaming (not fetch + await): same reason as AskAiPanel — responses can
 * be long and streaming shows tokens progressively.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { X, Send, Bot } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Message {
  role: "user" | "assistant";
  content: string;
  /** True while the assistant is still streaming this message */
  streaming?: boolean;
}

export interface AnalystRailProps {
  onClose: () => void;
  ticker: string;
  price?: number | null;
  priceChangePct?: number | null;
  pe?: number | null;
  week52High?: number | null;
  week52Low?: number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildSystemContext({
  ticker,
  price,
  priceChangePct,
  pe,
}: Pick<AnalystRailProps, "ticker" | "price" | "priceChangePct" | "pe">): string {
  const sign = priceChangePct != null && priceChangePct >= 0 ? "+" : "";
  const pricePart = price != null
    ? ` at $${price.toFixed(2)}${priceChangePct != null ? ` (${sign}${priceChangePct.toFixed(2)}%)` : ""}`
    : "";
  const pePart = pe != null ? ` P/E: ${pe.toFixed(1)}.` : "";
  return `User is viewing ${ticker}${pricePart}.${pePart} Answer in the context of this instrument.`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalystRail({
  onClose,
  ticker,
  price,
  priceChangePct,
  pe,
  week52High,
  week52Low,
}: AnalystRailProps) {
  const { accessToken } = useAuth();

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Focus input on mount
  useEffect(() => { inputRef.current?.focus(); }, []);

  // Scroll to bottom when messages update
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Abort in-flight stream on unmount
  useEffect(() => {
    return () => { abortControllerRef.current?.abort(); };
  }, []);

  const handleSend = useCallback(async () => {
    if (!input.trim() || isStreaming || !accessToken) return;

    const userMessage = input.trim();
    setInput("");
    setError(null);

    // Add user turn immediately
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);

    // Add empty assistant turn (will be filled by streaming)
    setMessages((prev) => [...prev, { role: "assistant", content: "", streaming: true }]);

    // Abort previous request
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsStreaming(true);

    try {
      const res = await fetch("/api/v1/chat/stream", {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${accessToken}`,
        },
        body: JSON.stringify({
          message: userMessage,
          system_context: buildSystemContext({ ticker, price, priceChangePct, pe }),
        }),
      });

      if (!res.ok) throw new Error(`Chat error: ${res.status}`);

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buf = "";

      // eslint-disable-next-line no-await-in-loop
      while (true) {
        // eslint-disable-next-line no-await-in-loop
        const { done, value } = await reader.read();
        if (done) {
          // Flush remaining buffer (DS-007: final token without trailing newline)
          if (buf.startsWith("data: ")) {
            const data = buf.slice(6);
            if (data !== "[DONE]") {
              try {
                const parsed = JSON.parse(data) as { text?: string; token?: string };
                const chunk = parsed.text ?? parsed.token;
                if (chunk) {
                  setMessages((prev) => {
                    const next = [...prev];
                    const last = next[next.length - 1];
                    if (last?.role === "assistant") {
                      next[next.length - 1] = { ...last, content: last.content + chunk };
                    }
                    return next;
                  });
                }
              } catch { /* ignore malformed */ }
            }
          }
          break;
        }

        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6);
          if (data === "[DONE]") {
            setIsStreaming(false);
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last?.role === "assistant" && last.streaming) {
                next[next.length - 1] = { ...last, streaming: false };
              }
              return next;
            });
            return;
          }
          try {
            const parsed = JSON.parse(data) as { text?: string; token?: string };
            const chunk = parsed.text ?? parsed.token;
            if (chunk) {
              setMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last?.role === "assistant") {
                  next[next.length - 1] = { ...last, content: last.content + chunk };
                }
                return next;
              });
            }
          } catch { /* ignore keep-alive lines */ }
        }
      }

      // Mark last message as done if [DONE] was not received
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "assistant" && last.streaming) {
          next[next.length - 1] = { ...last, streaming: false };
        }
        return next;
      });
      setIsStreaming(false);
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setError(err instanceof Error ? err.message : "Chat failed. Please try again.");
      // Remove the empty streaming message on error
      setMessages((prev) => prev.filter((m) => !(m.role === "assistant" && m.streaming)));
      setIsStreaming(false);
    }
  }, [input, isStreaming, accessToken, ticker, price, priceChangePct, pe]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  const sign = priceChangePct != null && priceChangePct >= 0 ? "+" : "";
  const changeColor = priceChangePct != null && priceChangePct < 0 ? "text-negative" : "text-positive";

  return (
    <div
      className="flex h-full flex-col border-l border-border bg-background"
      role="complementary"
      aria-label={`Analyst panel for ${ticker}`}
    >
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex shrink-0 items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="flex h-5 w-5 items-center justify-center rounded-[2px] bg-[hsl(var(--accent-ai)/0.20)] ring-1 ring-[hsl(var(--accent-ai)/0.30)]">
            <Bot className="h-3 w-3 text-[hsl(var(--accent-ai))]" />
          </div>
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-foreground">
            Analyst
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-1 text-muted-foreground hover:text-foreground"
          aria-label="Close analyst panel"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* ── Context strip ──────────────────────────────────────────────── */}
      {/* WHY always visible (not just on first message): the strip anchors the rail
          to this instrument. The user can see at a glance that the assistant is
          context-aware without having to re-read the main page header. */}
      <div className="shrink-0 border-b border-border bg-muted/20 px-3 py-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <span className="font-mono text-[11px] font-semibold text-foreground">{ticker}</span>
          {price != null && (
            <span className="font-mono text-[11px] tabular-nums text-foreground">
              ${price.toFixed(2)}
            </span>
          )}
          {priceChangePct != null && (
            <span className={cn("font-mono text-[10px] tabular-nums", changeColor)}>
              {sign}{priceChangePct.toFixed(2)}%
            </span>
          )}
          {pe != null && (
            <span className="text-[10px] text-muted-foreground">
              P/E <span className="tabular-nums text-foreground">{pe.toFixed(1)}</span>
            </span>
          )}
          {week52High != null && week52Low != null && (
            <span className="text-[10px] text-muted-foreground">
              52W{" "}
              <span className="tabular-nums text-foreground">
                {week52Low.toFixed(2)}–{week52High.toFixed(2)}
              </span>
            </span>
          )}
        </div>
      </div>

      {/* ── Message list ───────────────────────────────────────────────── */}
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto px-3 py-3"
      >
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <Bot className="h-6 w-6 text-muted-foreground/40" />
            <p className="text-[11px] text-muted-foreground">
              Ask about {ticker} — price drivers, fundamentals, risks
            </p>
          </div>
        )}

        <div className="flex flex-col gap-3">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={cn(
                "flex flex-col gap-0.5",
                msg.role === "user" ? "items-end" : "items-start",
              )}
            >
              <span className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground/60">
                {msg.role === "user" ? "You" : "Analyst"}
              </span>
              <div
                className={cn(
                  "max-w-[90%] rounded-[2px] px-2.5 py-1.5 text-[11px] leading-relaxed",
                  msg.role === "user"
                    ? "bg-primary/10 text-foreground"
                    : "bg-muted/50 text-foreground",
                )}
              >
                <span className="whitespace-pre-wrap">{msg.content}</span>
                {msg.streaming && (
                  <span className="ml-0.5 inline-block h-3 w-0.5 animate-pulse bg-primary align-middle" />
                )}
              </div>
            </div>
          ))}
        </div>

        {error && (
          <p className="mt-2 text-[11px] text-destructive">{error}</p>
        )}
      </div>

      {/* ── Input area ─────────────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Ask about ${ticker}…`}
            rows={2}
            disabled={isStreaming}
            className="flex-1 resize-none rounded-[2px] border border-border bg-muted px-2 py-1.5 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]"
          />
          <Button
            size="sm"
            onClick={() => void handleSend()}
            disabled={!input.trim() || isStreaming}
            className="h-8 shrink-0 gap-1.5 border-0 bg-[hsl(var(--accent-ai)/0.90)] px-3 text-xs font-semibold text-white hover:bg-[hsl(var(--accent-ai))] disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))]"
            aria-label="Send message"
          >
            <Send className="h-3 w-3" />
          </Button>
        </div>
        <p className="mt-1 text-[9px] text-muted-foreground/50">
          Enter to send · Shift+Enter for newline
        </p>
      </div>
    </div>
  );
}
