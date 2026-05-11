/**
 * hooks/useChordHotkeys.ts — Global keyboard chord listener.
 *
 * WHY THIS EXISTS: PLAN-0059 W1 hotkey infrastructure. Mounts a single
 * document-level keydown listener that:
 *
 *   1. Builds up a chord buffer (e.g., "g" → "g d") with a 1.2s reset window.
 *   2. Suspends inside <input>, <textarea>, [contenteditable] (so typing
 *      doesn't accidentally trigger global navigation).
 *   3. Resolves each completed chord against the registry, respecting the
 *      active scope stack (modal > input > chart > table > page > global).
 *   4. Fires the matched binding's handler and resets the buffer.
 *
 * WHY a hook (not a class side-effect): the listener's lifecycle is tied to
 * the React tree — when the HotkeyProvider unmounts (route group exit, log out,
 * etc.) the listener must detach. useEffect cleanup is the right fit.
 *
 * WHY single global listener (not one per registered chord): registering
 * many keydown listeners would force browsers to dispatch each keypress to
 * every listener, eating CPU. One listener that consults a registry scales
 * to hundreds of bindings without measurable cost.
 *
 * USAGE: mounted exactly once inside the HotkeyProvider tree. Consumers do
 * not call this — they call HotkeyProvider + use registry.register() via
 * <HotkeyScope> or programmatic register().
 */

"use client";
// WHY "use client": uses document.addEventListener — browser-only.

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { canonicalChord } from "@/lib/hotkey-registry";
import { useHotkeyScope } from "@/contexts/HotkeyContext";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * 1200ms — chord reset window. Linear and Notion both use ~1s; Vim uses 1s
 * by default. We use 1.2s as a compromise: long enough that two-key chords
 * (`g d`) don't reset under network-induced jitter on slow machines, short
 * enough that a stray "g" doesn't linger if the user gets distracted.
 */
const CHORD_RESET_MS = 1200;

/**
 * Single-key bindings reserved as "ignore on first press" — these would
 * otherwise be aggressively swallowed before the user finishes typing in
 * a non-input control. Currently empty; placeholder for future expansion.
 */
const IGNORED_KEYS = new Set<string>([]);

// ── Activation predicates ─────────────────────────────────────────────────────

/**
 * isTextInputActive — true when document.activeElement is a text-entry control
 * (input, textarea, contenteditable). The listener ALWAYS suspends in this
 * case to preserve normal typing — single-letter chords like `g` would
 * otherwise eat keystrokes inside a search box.
 *
 * The "input" scope from HotkeyContext is meant for SCOPED bindings that
 * deliberately fire even inside inputs (e.g., ⌘Enter to submit a form). Pure
 * single-key chords are unconditionally suspended.
 *
 * Special-case: <input type="checkbox|radio|range|color"> are NOT text inputs;
 * keys like Space toggling them is desirable but doesn't conflict with our
 * letter-based chords. We exclude only the text-entry types.
 */
function isTextInputActive(): boolean {
  const el = typeof document !== "undefined" ? document.activeElement : null;
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "TEXTAREA") return true;
  if (tag === "INPUT") {
    const type = (el as HTMLInputElement).type?.toLowerCase() ?? "text";
    // Only text-entry types swallow keystrokes; checkboxes/radios/etc. don't.
    const TEXT_TYPES = new Set([
      "text", "search", "email", "url", "tel", "password",
      "number", "date", "datetime-local", "month", "week", "time",
    ]);
    return TEXT_TYPES.has(type);
  }
  if ((el as HTMLElement).isContentEditable) return true;
  return false;
}

/**
 * keyToChordSegment — turn a KeyboardEvent into a single chord segment
 * (e.g., "g", "mod+k", "shift+mod+e", "?", "↑").
 *
 * Modifiers are joined with "+" and ordered shift→mod→alt for deterministic
 * matching. The actual key is appended last in lowercase.
 *
 * Returns null when the event should be ignored entirely (modifier-only
 * keypress, IME composition in progress, etc.).
 */
function keyToChordSegment(e: KeyboardEvent): string | null {
  // Ignore IME composition (typing CJK/accented characters) — the final
  // composed character fires its own key event.
  if (e.isComposing) return null;

  // Ignore pure modifier keypresses (Shift alone, Cmd alone) — they aren't
  // a chord, they're prefix arming.
  if (
    e.key === "Shift" ||
    e.key === "Control" ||
    e.key === "Meta" ||
    e.key === "Alt"
  ) {
    return null;
  }

  const parts: string[] = [];

  let key = e.key.toLowerCase();
  // Normalise space to "space" so chord strings remain space-separable.
  if (key === " ") key = "space";

  // WHY conditional shift: for letter keys (a-z) Shift produces uppercase but
  // the chord is letter-case-insensitive (we lowercase). For single-character
  // punctuation/symbols (?, /, :, etc.) the character ITSELF is what the
  // user typed — adding "shift" to the chord would force every binding author
  // to know whether their symbol requires Shift on the user's keyboard layout.
  // Linear/Notion follow the same rule. We only add "shift" for NAMED keys
  // (Enter, Tab, arrows, function keys) where Shift is a meaningful modifier.
  const isNamedKey = key.length > 1; // "enter", "escape", "arrowup", "f1", etc.
  if (e.shiftKey && isNamedKey) parts.push("shift");
  // Cmd on macOS, Ctrl elsewhere — both canonicalise to "mod"
  if (e.metaKey || e.ctrlKey) parts.push("mod");
  if (e.altKey) parts.push("alt");

  parts.push(key);

  return parts.join("+");
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useChordHotkeys — install the global listener.
 *
 * Mount exactly once near the top of the React tree (inside HotkeyProvider).
 * The listener attaches to document.keydown in capture phase so it sees the
 * event before route handlers / form submit shortcuts.
 */
export function useChordHotkeys(): void {
  const { activeScopes, registry } = useHotkeyScope();
  const pathname = usePathname() ?? "";

  // Buffer state lives in refs because the listener closure must always read
  // the latest values without re-attaching the listener (which would lose the
  // chord buffer between re-renders).
  const bufferRef = useRef<string>("");
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Mirror the latest scope/pathname into refs so the document-level listener
  // (attached once) always sees current values without the closure-stale-deps
  // anti-pattern.
  const activeScopesRef = useRef(activeScopes);
  const pathnameRef = useRef(pathname);
  useEffect(() => {
    activeScopesRef.current = activeScopes;
  }, [activeScopes]);
  useEffect(() => {
    pathnameRef.current = pathname;
  }, [pathname]);

  useEffect(() => {
    function clearBuffer(): void {
      bufferRef.current = "";
      if (resetTimerRef.current !== null) {
        clearTimeout(resetTimerRef.current);
        resetTimerRef.current = null;
      }
    }

    function scheduleReset(): void {
      if (resetTimerRef.current !== null) {
        clearTimeout(resetTimerRef.current);
      }
      resetTimerRef.current = setTimeout(() => {
        bufferRef.current = "";
        resetTimerRef.current = null;
      }, CHORD_RESET_MS);
    }

    function onKeyDown(e: KeyboardEvent): void {
      // Always honour Escape: clears any pending chord and emits a "modal"-scoped
      // binding if registered (e.g., "Close topmost overlay").
      if (e.key === "Escape") {
        clearBuffer();
        // Fall through to normal lookup so an Esc binding still fires.
      }

      // Suspend inside text-entry controls — we never want chord matching to
      // swallow regular typing. The exception is modifier-bearing chords
      // (mod+k, mod+enter) which the user cannot type as content; those
      // pass through.
      const segment = keyToChordSegment(e);
      if (segment === null) return;

      const hasModifier =
        segment.includes("mod+") || segment.includes("alt+") || segment.includes("shift+");

      if (isTextInputActive() && !hasModifier) {
        // Reset any in-progress chord — the user is now typing.
        clearBuffer();
        return;
      }

      if (IGNORED_KEYS.has(segment)) return;

      // Build the candidate chord from the buffer + this segment.
      const buffer = bufferRef.current;
      const candidate = canonicalChord(buffer === "" ? segment : `${buffer} ${segment}`);

      // Try exact match first.
      const match = registry.lookup(candidate, activeScopesRef.current, pathnameRef.current);
      if (match) {
        e.preventDefault();
        e.stopPropagation();
        clearBuffer();
        try {
          const result = match.handler(e);
          // Fire-and-forget Promises — we don't block the listener on them.
          if (result && typeof (result as Promise<unknown>).then === "function") {
            (result as Promise<unknown>).catch((err) => {
              // eslint-disable-next-line no-console
              console.error(`[hotkeys] handler for ${match.id} rejected:`, err);
            });
          }
        } catch (err) {
          // eslint-disable-next-line no-console
          console.error(`[hotkeys] handler for ${match.id} threw:`, err);
        }
        return;
      }

      // No exact match — is the candidate a prefix of a known chord?
      // If so, hold the buffer for the next key. Otherwise reset.
      if (registry.isPrefix(candidate)) {
        bufferRef.current = candidate;
        scheduleReset();
        // Don't preventDefault — the user might be typing in a non-chord context
        // and we should not block the keystroke from reaching the focused element.
        return;
      }

      // Buffer was held but this key doesn't continue or complete any chord —
      // try the segment alone (in case the prior buffer was a stale prefix
      // and this key is a fresh single-key chord).
      if (buffer !== "") {
        const fallback = registry.lookup(segment, activeScopesRef.current, pathnameRef.current);
        if (fallback) {
          e.preventDefault();
          e.stopPropagation();
          clearBuffer();
          try {
            void fallback.handler(e);
          } catch (err) {
            // eslint-disable-next-line no-console
            console.error(`[hotkeys] handler for ${fallback.id} threw:`, err);
          }
          return;
        }
      }

      // No match at all — reset the buffer.
      clearBuffer();
    }

    // Capture phase ensures we see the event before form-submit shortcuts on
    // children. We do NOT swallow events that don't match a binding.
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      clearBuffer();
    };
    // Listener is attached ONCE — ref mirrors above keep it current.
  }, [registry]);
}
