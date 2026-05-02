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
 */

import { useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Thread } from "@/types/api";
import { PLACEHOLDER_THREAD_TITLE } from "../lib/starters";

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
  const [draft, setDraft] = useState(thread.title ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  // Re-sync the draft when the underlying thread title changes (e.g. after
  // a successful PATCH the parent's optimistic update flows down).
  useEffect(() => {
    setDraft(thread.title ?? "");
  }, [thread.title]);

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
      className="group relative flex cursor-pointer items-start gap-2 rounded-[2px] px-3 py-2.5 transition-colors hover:bg-muted"
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
              "px-1.5 py-0.5 text-sm text-foreground",
              "focus:outline-none focus:ring-1 focus:ring-primary",
            )}
            aria-label="Edit thread title"
            maxLength={200}
          />
        ) : (
          <p
            className={`truncate text-sm ${
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
            {thread.title ?? PLACEHOLDER_THREAD_TITLE}
          </p>
        )}
        <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
          {new Date(thread.updated_at).toLocaleDateString([], {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </p>
      </div>

      <button
        className="hidden shrink-0 rounded-[2px] p-0.5 text-muted-foreground hover:text-destructive group-hover:flex"
        onClick={(e) => onDelete(thread.thread_id, e)}
        aria-label={`Delete thread: ${thread.title ?? PLACEHOLDER_THREAD_TITLE}`}
        tabIndex={-1}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
