/**
 * hooks/useConsoleCapture.ts — opt-in browser console buffer.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-02):
 * Bug reports are useless without context. By optionally attaching the
 * last N console.{log,warn,error} entries we give support engineers the
 * same view the user saw before submitting. Approved decision: capture is
 * OPT-IN — the FeedbackModal renders a checkbox and only mounts the hook
 * with `enabled: true` after the user agrees.
 *
 * SECURITY:
 *   - We never auto-attach the buffer to outgoing requests; the consumer
 *     decides when to read `logs` and include them in the payload
 *   - Backend redacts secrets server-side; we only do best-effort scrubbing
 *     (regex-strip Bearer tokens) before storing in the ring buffer
 *   - Buffer is in-memory only; nothing persists across page reloads
 *
 * IMPLEMENTATION NOTES:
 *   - Wraps window.console.{log,warn,error} via monkey-patching
 *   - Restores the originals on unmount
 *   - Ring buffer of MAX_ENTRIES so a runaway log loop can't OOM the page
 */

"use client";
// WHY "use client": touches `window.console` — browser-only.

import { useCallback, useEffect, useRef, useState } from "react";

// ── Constants ──────────────────────────────────────────────────────────────

const MAX_ENTRIES = 50; // matches the spec "last 50 console entries"

/** Console levels we capture — others (debug/trace/info) are intentionally skipped. */
const CAPTURED_LEVELS = ["log", "warn", "error"] as const;
type Level = (typeof CAPTURED_LEVELS)[number];

// ── Types ──────────────────────────────────────────────────────────────────

export interface ConsoleEntry {
  /** ms since epoch for relative ordering. */
  timestamp: number;
  level: Level;
  /**
   * String-formatted args. We do NOT keep object references — JSON.stringify
   * with try/catch handles circular refs and lets the buffer be sent over
   * the network later without serialisation surprises.
   */
  message: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * formatArgs — turn console.* args into a single string.
 * Uses JSON.stringify for objects; falls back to String() for circular
 * refs, functions, and primitive types.
 */
function formatArgs(args: unknown[]): string {
  return args
    .map((a) => {
      if (a === null) return "null";
      if (typeof a === "string") return scrubSecrets(a);
      if (typeof a === "number" || typeof a === "boolean") return String(a);
      try {
        return scrubSecrets(JSON.stringify(a));
      } catch {
        return String(a);
      }
    })
    .join(" ");
}

/**
 * scrubSecrets — best-effort regex strip of obvious tokens.
 *
 * NOT a security boundary — the backend redactor in S1 is the canonical
 * one. This is a UX-friendly extra layer so support engineers don't see
 * raw bearer tokens in their triage view.
 */
function scrubSecrets(s: string): string {
  return s
    .replace(/Bearer\s+[A-Za-z0-9._\-+/=]+/g, "Bearer [REDACTED]")
    .replace(/("password"\s*:\s*)"[^"]*"/gi, '$1"[REDACTED]"')
    .replace(/("access_token"\s*:\s*)"[^"]*"/gi, '$1"[REDACTED]"');
}

// ── Hook ───────────────────────────────────────────────────────────────────

export interface UseConsoleCaptureResult {
  /** The current ring-buffer snapshot (newest last). */
  logs: ConsoleEntry[];
  /** Empty the buffer — useful when retrying a flow. */
  clear: () => void;
}

/**
 * useConsoleCapture — capture console.{log,warn,error} entries while mounted.
 *
 * @param enabled when false the hook is inert (no patching) — opt-in flag
 *
 * Usage:
 *   const [optIn, setOptIn] = useState(false);
 *   const { logs, clear } = useConsoleCapture(optIn);
 *   // attach `logs` to feedback payload only after explicit user consent
 */
export function useConsoleCapture(enabled: boolean): UseConsoleCaptureResult {
  // WHY both ref + state: React state drives re-renders for the UI preview;
  // ref holds the latest array so the patched console functions can push
  // synchronously without depending on stale-closure state.
  const bufferRef = useRef<ConsoleEntry[]>([]);
  const [logs, setLogs] = useState<ConsoleEntry[]>([]);

  // Throttle setState calls — bursty logs would re-render every line.
  // Schedule one flush per microtask using a flag; the next flush picks
  // up everything pushed since.
  const dirtyRef = useRef(false);

  const scheduleFlush = useCallback(() => {
    if (dirtyRef.current) return;
    dirtyRef.current = true;
    queueMicrotask(() => {
      dirtyRef.current = false;
      // copy the ref so React detects the new identity
      setLogs([...bufferRef.current]);
    });
  }, []);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;

    const originals: Partial<Record<Level, typeof console.log>> = {};

    for (const level of CAPTURED_LEVELS) {
      originals[level] = window.console[level].bind(window.console);
      // WHY assign through window.console (not local var): some libraries
      // grab `console.error` on import — we want them to see our wrapper.
      window.console[level] = (...args: unknown[]) => {
        const entry: ConsoleEntry = {
          timestamp: Date.now(),
          level,
          message: formatArgs(args),
        };
        bufferRef.current.push(entry);
        // Ring-buffer trim (keep only newest MAX_ENTRIES).
        if (bufferRef.current.length > MAX_ENTRIES) {
          bufferRef.current.splice(0, bufferRef.current.length - MAX_ENTRIES);
        }
        scheduleFlush();
        // Always forward to the original so the devtools panel still works.
        originals[level]?.(...args);
      };
    }

    return () => {
      // Restore originals on unmount or when `enabled` flips false.
      for (const level of CAPTURED_LEVELS) {
        const orig = originals[level];
        if (orig) window.console[level] = orig;
      }
    };
  }, [enabled, scheduleFlush]);

  const clear = useCallback(() => {
    bufferRef.current = [];
    setLogs([]);
  }, []);

  return { logs, clear };
}
