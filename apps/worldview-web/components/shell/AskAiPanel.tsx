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
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AskAiPanel({ onClose }: AskAiPanelProps) {
  const router = useRouter();
  const { accessToken } = useAuth();

  const [query, setQuery] = useState("");
  const [response, setResponse] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // WHY useRef for EventSource: the SSE connection is imperative infrastructure,
  // not UI state. Storing it in a ref avoids unnecessary re-renders on connect/disconnect.
  const eventSourceRef = useRef<EventSource | null>(null);
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

  // Cleanup SSE stream on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
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

    setIsStreaming(true);
    setResponse("");
    setError(null);

    try {
      const res = await fetch("/api/v1/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // WHY Authorization header: S9 requires Bearer token for all authenticated endpoints
          "Authorization": `Bearer ${accessToken}`,
        },
        body: JSON.stringify({
          message: query.trim(),
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
        if (done) break;

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
              const parsed = JSON.parse(data) as { token?: string };
              if (parsed.token) {
                // Append each token as it streams in — creates the "typing" effect
                setResponse((prev) => prev + parsed.token);
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
  }, [query, isStreaming, accessToken]);

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
      className="fixed bottom-4 right-4 z-50 flex w-80 flex-col rounded-lg border border-border bg-background shadow-2xl"
      role="complementary"
      aria-label="AI assistant"
    >
      {/* ── Header ─────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium text-foreground">Ask AI</span>
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
          className="flex-1 resize-none rounded-md border border-border bg-muted px-2 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
        />
        <Button
          size="sm"
          onClick={() => void handleSend()}
          disabled={!query.trim() || isStreaming}
          className="h-8 w-8 shrink-0 p-0"
          aria-label="Send message"
        >
          <Send className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}
