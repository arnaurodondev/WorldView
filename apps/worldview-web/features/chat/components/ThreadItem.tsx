"use client";

/**
 * features/chat/components/ThreadItem.tsx — Sidebar row for a single thread.
 *
 * WHY EXTRACTED (PLAN-0059 E-3 partial): the rename UX (double-click → input
 * → Enter / Esc) added enough state that inlining inside the page render was
 * cluttering the orchestrator. Pulling it out keeps the sidebar list code
 * trivial and the rename state self-contained.
 *
 * PLAN-0051 T-E-5-06: optimistic title update with rollback on PATCH error.
 *
 * DENSITY BUNDLE 2026-05-09 — title + date robustness fixes
 * --------------------------------------------------------
 * Two visible bugs reported by the user:
 *
 *   1. **"Invalid Date"** — appeared when ``thread.updated_at`` was null /
 *      undefined / non-ISO. ``new Date(undefined)`` returns an Invalid Date
 *      whose ``toLocaleDateString()`` is the string ``"Invalid Date"``.
 *      Fix: ``safeFormatDate(updated_at, created_at)`` falls back through
 *      ``updated_at -> created_at -> "—"``.
 *
 *   2. **"New Conversation"** placeholder shown forever — title was null for
 *      threads where the post-stream PATCH that names the thread either
 *      hadn't fired yet or failed. Fix: ``deriveTitle(thread)`` falls back to
 *      a snippet of the first user message (truncated, single-line) before
 *      reverting to the static placeholder. This matches what ChatGPT/Claude
 *      do — the user always sees something they can identify.
 */

import { useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Thread } from "@/types/api";
import { PLACEHOLDER_THREAD_TITLE } from "../lib/starters";

/**
 * safeFormatDate — render a thread timestamp without ever returning
 * "Invalid Date".
 *
 * WHY THIS EXISTS: ``thread.updated_at`` can be null, undefined, "" or a
 * non-ISO format depending on which S9 endpoint produced the row (legacy
 * cached threads pre-PRD-0028 had no ``updated_at``). ``new Date(falsy)``
 * yields an Invalid Date whose locale-formatted output is the literal string
 * "Invalid Date" — visible to the user.
 *
 * Strategy: try ``updated_at`` first (the canonical "last activity" stamp),
 * fall through to ``created_at`` if that fails, finally render a single
 * em-dash so the row still has consistent height/layout.
 */
function safeFormatDate(
  updatedAt: string | null | undefined,
  createdAt: string | null | undefined,
): string {
  for (const candidate of [updatedAt, createdAt]) {
    if (!candidate) continue;
    const d = new Date(candidate);
    // ``isNaN(d.getTime())`` is the canonical "is this date Invalid?" check.
    if (Number.isNaN(d.getTime())) continue;
    return d.toLocaleDateString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return "—";
}

/**
 * deriveTitle — pick the best human label for a thread row.
 *
 * Resolution order:
 *   1. ``thread.title`` — set by S8 after the first stream completes (the LLM
 *      proposes a 4-6 word title which the post-stream PATCH applies).
 *   2. First user message snippet — if title isn't set yet, slice the first
 *      user message to 50 chars + ellipsis. This is the same pattern ChatGPT
 *      uses while the title is still being generated.
 *   3. ``PLACEHOLDER_THREAD_TITLE`` — last resort for empty threads where the
 *      user hasn't sent anything yet.
 *
 * WHY 50 chars: long enough to be uniquely identifiable, short enough to
 * fit on one row at 11px in the 224px sidebar without truncating with "...".
 */
function deriveTitle(thread: Thread): string {
  const trimmed = (thread.title ?? "").trim();
  if (trimmed) return trimmed;

  // Look for the first user message in the thread payload (S9 may include
  // the first few messages on the list response — see chat page query).
  const firstUserMsg = thread.messages?.find((m) => m.role === "user")?.content;
  if (firstUserMsg && firstUserMsg.trim()) {
    // Strip newlines so multi-line questions collapse to one row.
    const oneLine = firstUserMsg.replace(/\s+/g, " ").trim();
    if (oneLine.length <= 50) return oneLine;
    return oneLine.slice(0, 47).trimEnd() + "…";
  }

  return PLACEHOLDER_THREAD_TITLE;
}

export interface ThreadItemProps {
  thread: Thread;
  isActive: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string, e: React.MouseEvent) => void;
  onRename: (id: string, newTitle: string) => Promise<void>;
}

export function ThreadItem({
  thread,
  isActive,
  onSelect,
  onDelete,
  onRename,
}: ThreadItemProps) {
  // WHY local edit state: the row owns its own draft title while the input
  // is shown, then propagates to the parent via onRename on commit.
  const [isEditing, setIsEditing] = useState(false);
  // Density bundle 2026-05-09: seed the draft with the *derived* title so
  // a user editing a not-yet-named thread sees the message-snippet title in
  // the input rather than an empty box. Saving without changes is still a
  // no-op (commit() compares against thread.title before PATCHing).
  const displayTitle = deriveTitle(thread);
  const [draft, setDraft] = useState(displayTitle);
  const inputRef = useRef<HTMLInputElement>(null);

  // Re-sync the draft when the underlying thread title changes (e.g. after
  // a successful PATCH the parent's optimistic update flows down).
  useEffect(() => {
    setDraft(displayTitle);
  }, [displayTitle]);

  // Auto-focus the input when entering edit mode.
  useEffect(() => {
    if (isEditing) inputRef.current?.focus();
  }, [isEditing]);

  /**
   * commit — try to PATCH the new title; revert local state on error.
   */
  async function commit() {
    const trimmed = draft.trim();
    setIsEditing(false);
    // Empty titles are rejected; revert to current value.
    if (!trimmed || trimmed === (thread.title ?? "")) {
      setDraft(thread.title ?? "");
      return;
    }
    try {
      await onRename(thread.thread_id, trimmed);
    } catch {
      // Rollback the draft on error so the user can retry.
      setDraft(thread.title ?? "");
    }
  }

  function cancel() {
    setDraft(thread.title ?? "");
    setIsEditing(false);
  }

  return (
    <div
      // Density bundle 2026-05-09: px-3 py-2.5 → px-2 py-1.5 (Bloomberg
      // sidebar row density). Each thread row drops from ~46px to ~36px,
      // letting one more thread fit in a 12-thread sidebar without scrolling.
      className="group relative flex cursor-pointer items-start gap-2 rounded-[2px] px-2 py-1.5 transition-colors hover:bg-muted"
      style={isActive ? { backgroundColor: "rgba(232,163,23,0.08)" } : undefined}
      onClick={() => !isEditing && onSelect(thread.thread_id)}
      role="button"
      aria-pressed={isActive}
      tabIndex={0}
      onKeyDown={(e) => {
        if (isEditing) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(thread.thread_id);
        }
      }}
    >
      <div className="min-w-0 flex-1">
        {isEditing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            onBlur={() => void commit()}
            onKeyDown={(e) => {
              // WHY stopPropagation: prevent the parent's onKeyDown from
              // re-selecting the thread on Enter while we're editing.
              e.stopPropagation();
              if (e.key === "Enter") {
                e.preventDefault();
                void commit();
              } else if (e.key === "Escape") {
                e.preventDefault();
                cancel();
              }
            }}
            className={cn(
              "w-full rounded-[2px] border border-primary/40 bg-card",
              // WHY text-[11px]: sidebar thread items are data rows — must use the
              // 11px terminal data density, not the 14px consumer-app text-[14px].
              "px-1.5 py-0.5 text-[11px] text-foreground",
              "focus:outline-none focus:ring-1 focus:ring-primary",
            )}
            aria-label="Edit thread title"
            maxLength={200}
          />
        ) : (
          // WHY text-[11px]: thread titles are data rows in the sidebar — terminal
          // density rule mandates 11px for all data text. text-[14px] (14px) is a
          // consumer chatbot convention that breaks Bloomberg-grade density.
          <p
            className={`truncate text-[11px] ${
              isActive ? "font-medium text-primary" : "text-foreground"
            }`}
            // WHY double-click to rename: matches Slack/Notion convention.
            // Keeps single-click for "select thread", double-click for edit.
            onDoubleClick={(e) => {
              e.stopPropagation();
              setIsEditing(true);
            }}
            title="Double-click to rename"
          >
            {/* Density bundle 2026-05-09: deriveTitle prefers the LLM-generated
                title, falls back to the first-user-message snippet, and only
                shows "New conversation" when there is genuinely no content. */}
            {displayTitle}
          </p>
        )}
        {/* Density bundle 2026-05-09: safeFormatDate guarantees we never render
            "Invalid Date" — falls through updated_at -> created_at -> "—". */}
        <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
          {safeFormatDate(thread.updated_at, thread.created_at)}
        </p>
      </div>

      <button
        className="hidden shrink-0 rounded-[2px] p-0.5 text-muted-foreground hover:text-destructive group-hover:flex"
        onClick={(e) => onDelete(thread.thread_id, e)}
        aria-label={`Delete thread: ${displayTitle}`}
        tabIndex={-1}
      >
        {/* WHY strokeWidth={1.5}: hairline icon weight for terminal chrome buttons. */}
        <Trash2 className="h-3.5 w-3.5" strokeWidth={1.5} />
      </button>
    </div>
  );
}
