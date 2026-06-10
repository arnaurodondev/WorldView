"use client";
// WHY "use client": registers a document-level keydown listener — browser only.

/**
 * useToolTraceChord — ⌘D / Ctrl+D toggle for the debug ToolTraceDrawer.
 *
 * WHY THIS EXISTS (PRD-0089 Q-8, completed in Round 1 Foundation):
 * The ToolTraceDrawer exposes internal retrieval/tool-call trace data. Q-8
 * mandates it is reachable ONLY behind the `?debug=1` URL flag (see
 * `useDebugFlag`) — no cookie, no localStorage. The chord is the toggle
 * mechanism on top of that gate: with debug enabled, ⌘D (macOS) or Ctrl+D
 * (Windows/Linux) flips the drawer; without it the chord is inert and the
 * browser's default bookmark shortcut behaviour is left untouched.
 *
 * WHY preventDefault ONLY when enabled: Ctrl/⌘+D is the browser's
 * "bookmark this page" shortcut. Hijacking it for every user would be
 * hostile; we only intercept when the analyst explicitly opted into debug
 * mode via the URL.
 *
 * WHY a document-level listener (not an element handler): the chord must
 * work regardless of which element holds focus (textarea, thread list,
 * body). Cleanup on unmount/disable prevents listener accumulation across
 * hot reloads and navigations.
 */

import { useCallback, useEffect, useState } from "react";

export function useToolTraceChord(enabled: boolean): {
  /** Whether the drawer is currently open. Always false when disabled. */
  isOpen: boolean;
  /** Imperative close — used by the drawer's own close button. */
  close: () => void;
} {
  const [isOpen, setIsOpen] = useState(false);

  // Force-close when debug mode is turned off mid-session (e.g. the user
  // edits the URL). Without this the drawer would stay mounted with no way
  // to reopen it after a re-toggle, and worse, would keep exposing trace
  // data after the gate was removed.
  useEffect(() => {
    if (!enabled) setIsOpen(false);
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    function handleChord(e: KeyboardEvent) {
      // metaKey on macOS, ctrlKey elsewhere — same convention as the
      // chat page's Cmd+\ context-rail toggle.
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "d") {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", handleChord);
    return () => document.removeEventListener("keydown", handleChord);
  }, [enabled]);

  const close = useCallback(() => setIsOpen(false), []);

  return { isOpen, close };
}
