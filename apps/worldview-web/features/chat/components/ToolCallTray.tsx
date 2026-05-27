/**
 * features/chat/components/ToolCallTray.tsx — Collapsible tool-call tray.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block B, T-08):
 *   The legacy `StreamingBubble` rendered tool-call rows inline above the
 *   streaming text, expanded at all times. Once tools completed they
 *   stayed visible forever, wasting vertical real estate and pulling the
 *   eye away from the answer the analyst was reading. Bloomberg / Refinitiv
 *   convention: while a tool is RUNNING, the tray is auto-expanded so the
 *   analyst sees the activity ("Searching documents…" / "Querying KG…");
 *   ~1.5s after the LAST tool finishes, the tray auto-collapses to a
 *   one-line summary `tool calls — N/N done` that the analyst can click
 *   to re-expand on demand.
 *
 *   This component owns the per-turn collapse state in React state (NOT
 *   the URL — per Wave K decision: per-turn UI affordances must not leak
 *   into the URL, so they don't survive thread switching). Each
 *   `<MessageTurn>` renders its own tray, so each turn's tray remembers
 *   its own collapse history within the page lifetime.
 *
 *   Each row reuses `<ToolCallIndicator>` verbatim — the visual contract
 *   for an individual tool spinner / ok / error icon stays in one place.
 *
 * FALLBACK INDICATOR (acceptance gate #13):
 *   When a row carries `is_fallback === true`, we render `↻ Retrying with
 *   X (Y returned empty)` instead of a fresh spinner. The original tool
 *   id is read from `fallback_of`. The prefix is a visual signal that
 *   the answer the LLM produced is from a degraded path — the analyst
 *   should weight it accordingly.
 *
 * ROW HEIGHT: 16px per design §6.4 (the densest of the three row heights
 *   in Wave K — meta strip rows are 9px text but the row itself is
 *   16px; citation rows are 18px; thread rows 24px).
 *
 * DATA SOURCE: pure prop forwarding from `useChatStream.activeTools` (or
 *   from a persisted `tool_calls` field once Q-11 lands).
 *
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §5 (tool-call tray) +
 *   §6.4 (16px row height).
 */

"use client";
// WHY "use client": owns the collapse-state useState, the auto-collapse
// useEffect with setTimeout, and the click handler. None can run in a
// Server Component.

import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight, Loader2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ToolCallState } from "@/features/chat/components/ToolCallIndicator";

interface ToolCallTrayProps {
  readonly tools: ToolCallState[];
  /**
   * Initial collapsed state. Defaults to `false` because a tray that
   * appears at first should always be expanded — the analyst wants to
   * see what's running. We auto-collapse on its own when the last tool
   * finishes.
   */
  readonly defaultCollapsed?: boolean;
}

// Auto-collapse delay (ms) after the LAST tool completes. 1.5s is the
// design-doc value (§5). Long enough for the analyst's eye to register
// the green checks; short enough that the tray doesn't loiter once the
// answer text starts arriving.
const AUTO_COLLAPSE_DELAY_MS = 1500;

/**
 * ToolCallTray — see file header.
 *
 * COLLAPSE BEHAVIOUR:
 *   - When any tool is `running`: tray is forced expanded (we still allow
 *     the user to override by clicking the header, but the moment a new
 *     tool starts running we re-expand).
 *   - When ALL tools are done: a 1.5s timer fires; on expiry we collapse.
 *   - Click on header: manually toggle (no timer interference).
 */
export function ToolCallTray({
  tools,
  defaultCollapsed = false,
}: ToolCallTrayProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  // Track whether the user manually toggled — if so we respect their
  // choice and stop the auto-collapse timer from re-asserting itself.
  const [userOverride, setUserOverride] = useState(false);

  // Counts for the header summary line.
  const total = tools.length;
  const running = tools.filter((t) => t.status === "running").length;
  const done = total - running;
  const allDone = running === 0 && total > 0;

  // ── Auto-collapse timer ────────────────────────────────────────────────────
  // WHY a useEffect (not a one-off setTimeout in an event handler): the
  // "all done" condition can be reached either by a tool_result event
  // (status flips to ok/error) OR by a fresh render with already-done
  // tools (history reload). An effect catches both.
  useEffect(() => {
    if (!allDone) return; // still running — no timer
    if (userOverride) return; // user pinned it; don't fight them
    if (collapsed) return; // already collapsed
    const handle = setTimeout(() => {
      setCollapsed(true);
    }, AUTO_COLLAPSE_DELAY_MS);
    return () => clearTimeout(handle);
  }, [allDone, userOverride, collapsed]);

  // ── Re-expand when new tools start ─────────────────────────────────────────
  // If a new tool appears in `running` state after we had auto-collapsed,
  // re-expand. This handles the streaming case where S8 fires
  // tool_call -> tool_result -> tool_call (a second tool) in sequence.
  useEffect(() => {
    if (running > 0 && collapsed && !userOverride) {
      setCollapsed(false);
    }
  }, [running, collapsed, userOverride]);

  if (total === 0) return null;

  return (
    <div
      // WHY data-tool-call-tray: T-22 unit tests target this stable
      // attribute to assert the auto-collapse timing without relying on
      // a fragile class-name selector.
      data-tool-call-tray
      data-collapsed={collapsed ? "true" : "false"}
      // WHY no rounded corners: the tray is INSIDE the message turn's
      // body column; rounding would visually detach it. Border-l on the
      // root + matching border-color subtle "inset block" effect.
      className="mt-1 border border-border bg-card"
      role="region"
      aria-label="Tool calls"
    >
      {/* ── Header (clickable to toggle) ─────────────────────────────── */}
      <button
        type="button"
        data-cell
        onClick={() => {
          setCollapsed((c) => !c);
          setUserOverride(true);
        }}
        // WHY h-[16px]: design row height for tool-call rows. The header
        // matches the row body so the tray looks like a stack of equal
        // rows, the topmost one being the header.
        className={cn(
          "flex h-[16px] w-full items-center gap-1 px-2 text-left",
          "text-[9px] font-mono uppercase tracking-wide",
          "bg-muted/40 text-muted-foreground",
          "hover:bg-muted/60 transition-color-only duration-75",
        )}
        aria-expanded={!collapsed}
      >
        {collapsed ? (
          <ChevronRight className="h-2.5 w-2.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-2.5 w-2.5" aria-hidden="true" />
        )}
        <span>tool calls</span>
        <span className="tabular-nums">
          — {done}/{total} done
        </span>
      </button>

      {/* ── Body (rows) ──────────────────────────────────────────────── */}
      {/* WHY max-height transition + overflow-hidden: per spec ("100ms
          max-height transition only"), we animate height-driven collapse
          without animating opacity / transform. The max-h-0 → max-h-96
          range covers ~12 rows which is enough for any single response. */}
      <div
        className={cn(
          "overflow-hidden transition-[max-height] duration-100 ease-linear",
          collapsed ? "max-h-0" : "max-h-96",
        )}
      >
        {tools.map((tool) => (
          <ToolRow key={`${tool.name}-${tool.fallback_of ?? ""}`} tool={tool} />
        ))}
      </div>
    </div>
  );
}

/**
 * ToolRow — one 16px row inside the tray. Pulled out to keep the parent's
 * render small and so the unit test (T-22 case 2) can target the row
 * directly without diving into the parent.
 *
 * WHY NOT reuse ToolCallIndicator: ToolCallIndicator manages its OWN
 * running/done grouping and renders without a row container that fits
 * the tray's 16px row spec. Re-using it as a single-tool renderer would
 * pull in the wrong layout. We instead replicate its icon+label logic
 * inline at the row level so each row controls its own height + padding.
 */
function ToolRow({ tool }: { tool: ToolCallState }) {
  const isRunning = tool.status === "running";
  const isOk = tool.status === "ok";
  // Fallback indicator: if S8 flagged this tool_call as a fallback, the
  // visible label is "↻ Retrying with X (Y returned empty)" where X is
  // the current tool name and Y is the fallback_of name. We omit the
  // suffix if fallback_of is missing.
  const isFallback = tool.is_fallback === true;
  const label = isFallback
    ? `↻ Retrying with ${tool.name}${
        tool.fallback_of ? ` (${tool.fallback_of} returned empty)` : ""
      }`
    : tool.label;

  return (
    <div
      data-cell
      data-tool-row={tool.name}
      data-tool-status={tool.status}
      className="flex h-[16px] items-center gap-1.5 border-t border-border px-2 text-[9px] font-mono first:border-t-0"
    >
      {/* Icon column. Running → Loader2 (static; the no-animate-spin rule
          from Bloomberg-terminal mandate is preserved). Done ok → green
          check. Done error/empty → muted X. Fallback overrides icon to
          the retry glyph used in the label so the row reads coherently
          even at a glance. */}
      {isFallback ? null : isRunning ? (
        <Loader2 className="h-2.5 w-2.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      ) : isOk ? (
        <Check className="h-2.5 w-2.5 shrink-0 text-positive" aria-hidden="true" />
      ) : (
        <X className="h-2.5 w-2.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      )}
      <span
        className={cn(
          "truncate",
          isFallback
            ? "text-warning"
            : isRunning
              ? "text-foreground"
              : "text-muted-foreground line-through opacity-70",
        )}
      >
        {label}
      </span>
    </div>
  );
}
