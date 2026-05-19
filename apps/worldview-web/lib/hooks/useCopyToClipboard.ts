/**
 * lib/hooks/useCopyToClipboard.ts — Unified clipboard copy with transient feedback.
 *
 * WHY THIS EXISTS (DS-009, FR-10.7):
 * Three components (AliasPill, MarkdownContent, DataTable) each implemented
 * their own clipboard logic, each with slightly different fallback behaviour
 * and timeout durations. Centralising into one hook:
 *   1. Single fallback path for environments without Clipboard API (old WebKit,
 *      some in-app browsers, HTTPS-required contexts).
 *   2. Consistent 2000ms feedback window (long enough to read, short enough
 *      not to block the next interaction).
 *   3. One place to add future enhancements (toast notifications, Sentry logging).
 *
 * USAGE:
 *   const { copy, copied } = useCopyToClipboard();
 *   <button onClick={() => copy(text)}>{copied ? "Copied!" : "Copy"}</button>
 *
 * RETURN:
 *   copy(text)  — async; resolves when clipboard write succeeds or falls back.
 *   copied      — true for 2000ms after a successful copy, then resets to false.
 *                 Use to swap button label or show a checkmark.
 */

"use client";
// WHY "use client": uses useState, setTimeout (imperative timer), and browser APIs.

import { useCallback, useRef, useState } from "react";

export interface UseCopyToClipboardResult {
  /** Copy `text` to the clipboard. Returns a promise that resolves on success. */
  copy: (text: string) => Promise<void>;
  /**
   * True for 2000ms after a successful copy.
   * WHY 2000ms: long enough to be legible, short enough to not interrupt flow.
   * Bloomberg Terminal copy feedback is typically 1.5-2s.
   */
  copied: boolean;
}

/** Duration (ms) that `copied` stays true after a successful write. */
const RESET_DELAY = 2_000;

export function useCopyToClipboard(): UseCopyToClipboardResult {
  const [copied, setCopied] = useState(false);
  // Store the timeout id in a ref so we can cancel it if the user copies
  // again before the previous timeout fires — avoids double-reset flicker.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const copy = useCallback(async (text: string): Promise<void> => {
    try {
      // Prefer the modern Clipboard API: async, no flash, no selection mess.
      // Requires a secure context (https:// or localhost) AND user gesture.
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        // Fallback: create a temporary textarea, select it, execCommand("copy").
        // Deprecated but still works in most environments that lack Clipboard API
        // (iOS in-app browsers, older Chromium, some CI headless browsers).
        const textarea = document.createElement("textarea");
        textarea.value = text;
        // WHY these styles: keep the element off-screen and invisible so it
        // doesn't cause layout shift or visual flash during the copy.
        textarea.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        // eslint-disable-next-line @typescript-eslint/no-deprecated
        document.execCommand("copy");
        document.body.removeChild(textarea);
      }

      // Cancel any pending reset so the button doesn't flicker if the user
      // copies quickly back-to-back.
      if (timerRef.current) clearTimeout(timerRef.current);
      setCopied(true);
      timerRef.current = setTimeout(() => {
        setCopied(false);
        timerRef.current = null;
      }, RESET_DELAY);
    } catch {
      // Clipboard write failed (e.g. permission denied, insecure context).
      // We swallow silently — the button should not turn red; the user simply
      // didn't get feedback. Future: could integrate with toast here.
      setCopied(false);
    }
  }, []);

  return { copy, copied };
}
