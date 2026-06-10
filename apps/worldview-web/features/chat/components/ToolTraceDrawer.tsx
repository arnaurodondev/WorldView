"use client";
// WHY "use client": interactive (close button, native <details> toggles) and
// rendered conditionally from client-side chord/debug state.

/**
 * features/chat/components/ToolTraceDrawer.tsx — debug drawer showing the
 * tool-call trace for the last chat turn (PRD-0089 Q-8, Round 1 Foundation).
 *
 * WHY THIS EXISTS:
 * When a RAG answer looks wrong, the first question is "what did the tools
 * actually return?". The user-facing ToolCallIndicator shows only friendly
 * labels and pass/fail icons; this drawer shows the engineer's view — raw
 * tool name, the JSON arguments the LLM passed, the raw result metadata,
 * and per-call latency — without opening the network tab.
 *
 * ACCESS CONTROL (Q-8): rendered ONLY when `?debug=1` is in the URL (the
 * page gates on `useDebugFlag()`), toggled via ⌘D/Ctrl+D (`useToolTraceChord`).
 * No persistence — closing the tab forgets everything.
 *
 * WHY native <details>/<summary> (not a shadcn Accordion):
 * The drawer is a developer-only surface; <details> gives collapse/expand for
 * free with zero JS state, works with keyboard out of the box, and avoids
 * pulling Radix Accordion into the chat bundle for a debug tool that 99% of
 * sessions never open. (shadcn/ui-only rule applies to product UI components;
 * native disclosure elements are not a component-library bypass.)
 *
 * WHY position:fixed right panel (not a bottom sheet): the trace is read
 * side-by-side with the conversation it explains — covering the messages
 * with a bottom sheet would force the user to toggle back and forth.
 *
 * DATA SOURCE: `useChatStream().toolTrace` — captured from `tool_call` /
 * `tool_result` SSE events; survives stream completion (cleared on next send
 * or thread switch).
 */

import { X } from "lucide-react";

import type { ToolTraceEntry } from "@/features/chat/lib/types";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ToolTraceDrawerProps {
  /** Trace entries for the last turn — empty array shows the named empty state. */
  trace: ToolTraceEntry[];
  /** Close handler (X button). The ⌘D chord also toggles from the page. */
  onClose: () => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatJson — pretty-print with a hard size cap.
 *
 * WHY the cap: a pathological tool result (e.g. a 200-row screener payload)
 * would otherwise render megabytes of <pre> text and freeze the tab. 4 KB is
 * plenty to diagnose argument/shape issues; the full payload remains visible
 * in the network tab if truly needed.
 */
function formatJson(value: unknown): string {
  let text: string;
  try {
    text = JSON.stringify(value, null, 2) ?? "null";
  } catch {
    // Circular structures can't occur from JSON.parse'd SSE data, but be
    // defensive — a debug tool must never crash the page it is debugging.
    text = String(value);
  }
  const MAX = 4096;
  return text.length > MAX ? `${text.slice(0, MAX)}\n… (truncated)` : text;
}

/** Status → token-based colour class (never hardcoded hex — Terminal Dark rule). */
function statusClass(status: ToolTraceEntry["status"]): string {
  switch (status) {
    case "ok":
      return "text-positive";
    case "error":
      return "text-negative";
    case "empty":
      return "text-muted-foreground";
    default:
      return "text-primary"; // running
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ToolTraceDrawer({ trace, onClose }: ToolTraceDrawerProps) {
  return (
    <div
      // data-testid is the contract with e2e/chat-polish.spec.ts ("?debug=1
      // reveals the ToolTraceDrawer via ⌘D") — do not rename.
      data-testid="tool-trace-drawer"
      role="dialog"
      aria-label="Tool call trace"
      // WHY fixed + z-40: floats above the chat columns but below modal
      // dialogs (Radix portals default to z-50). top-12 clears the TopBar.
      className="fixed bottom-0 right-0 top-12 z-40 flex w-[380px] flex-col border-l border-border bg-card shadow-lg"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-foreground">
          Tool Trace
          {/* WHY the DEBUG tag: makes screenshots self-explanatory — anyone
              seeing this panel knows it is not a product surface. */}
          <span className="ml-2 rounded-[2px] border border-warning/40 px-1 py-0.5 text-[9px] text-warning">
            DEBUG
          </span>
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close tool trace"
          className="rounded-[2px] p-0.5 text-muted-foreground hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" strokeWidth={1.5} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-2">
        {trace.length === 0 ? (
          // Named empty state — the drawer opening with nothing in it must
          // explain itself ("did the trace break?" → no, no tools ran yet).
          <p className="px-2 py-3 text-[11px] text-muted-foreground">
            No tool calls in the last turn. Send a question that needs data
            (e.g. &ldquo;What moved NVDA today?&rdquo;) and reopen with ⌘D.
          </p>
        ) : (
          <div className="space-y-1">
            {trace.map((entry) => (
              // WHY <details> open by default for errors only: a failing tool
              // is what the engineer came to inspect — auto-expand it; healthy
              // calls stay collapsed so a 6-tool turn fits on screen.
              <details
                key={entry.tool}
                open={entry.status === "error"}
                className="rounded-[2px] border border-border bg-background"
                data-testid="tool-trace-entry"
              >
                <summary className="flex cursor-pointer items-center gap-2 px-2 py-1.5 text-[11px]">
                  {/* Raw tool name in mono — the precise identifier. */}
                  <span className="font-mono text-foreground">{entry.tool}</span>
                  <span className={`font-mono text-[10px] uppercase ${statusClass(entry.status)}`}>
                    {entry.status}
                  </span>
                  {/* Latency — numeric, therefore font-mono (ADR-F-15).
                      "—" while running / when the result never arrived. */}
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                    {entry.latencyMs !== null ? `${entry.latencyMs} ms` : "—"}
                  </span>
                </summary>
                <div className="space-y-1.5 border-t border-border/60 px-2 py-1.5">
                  <p className="text-[10px] text-muted-foreground">{entry.label}</p>
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground">
                      Arguments
                    </p>
                    {/* WHY overflow-x-auto + whitespace-pre: long arg strings
                        (queries, entity ids) must not blow out the 380px panel. */}
                    <pre className="mt-0.5 overflow-x-auto whitespace-pre rounded-[2px] bg-muted p-1.5 font-mono text-[10px] leading-relaxed text-foreground">
                      {formatJson(entry.args)}
                    </pre>
                  </div>
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground">
                      Result
                    </p>
                    <pre className="mt-0.5 overflow-x-auto whitespace-pre rounded-[2px] bg-muted p-1.5 font-mono text-[10px] leading-relaxed text-foreground">
                      {entry.result !== null ? formatJson(entry.result) : "(running…)"}
                    </pre>
                  </div>
                </div>
              </details>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
