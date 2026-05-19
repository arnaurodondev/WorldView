/**
 * lib/hooks/useKeyboardShortcuts.ts — Declarative keyboard shortcut registration.
 *
 * WHY THIS EXISTS (DS-010, FR-10.7):
 * Three call sites (GlobalSearch, QuickEditPopover, FlashOverlay) each wired
 * their own `keydown` listener with slightly different Ctrl/Meta handling,
 * resulting in inconsistent cross-platform behaviour and duplicated teardown
 * logic. Centralising:
 *   1. Normalises Ctrl (Windows/Linux) ↔ Cmd/Meta (macOS) mapping.
 *   2. Prevents accidental listener leaks (attach/detach in a single effect).
 *   3. Makes shortcut maps declaratively visible in the call site (easier audit).
 *
 * USAGE:
 *   useKeyboardShortcuts({
 *     "ctrl+k": () => openSearch(),
 *     "cmd+k":  () => openSearch(),   // same action — both handled
 *     "/":      () => focusInput(),
 *     "escape": () => closeModal(),
 *   });
 *
 * KEY FORMAT:
 *   - Modifier prefix: "ctrl+", "cmd+", "shift+", "alt+" (or combinations)
 *   - Key name: lowercase key value (e.g. "k", "escape", "/", "arrowdown")
 *   - Cmd and Ctrl are normalised separately — declare both if you want
 *     cross-platform (ctrl+k AND cmd+k) for a single action.
 *
 * WHY NOT react-hotkeys-hook for this hook:
 *   react-hotkeys-hook is used at the root layout for global navigation
 *   (g+d, g+w, g+c). This hook is lighter-weight for modal/overlay shortcuts
 *   that need to be registered and de-registered on component mount/unmount
 *   without touching the global hotkey registry.
 *
 * IMPORTANT:
 *   - Does NOT prevent default browser behaviour (e.g. / for Firefox QuickFind).
 *     Call `event.preventDefault()` inside your handler if needed.
 *   - Does NOT handle sequence chords (g then d) — use react-hotkeys-hook for that.
 */

"use client";
// WHY "use client": attaches event listeners — server-side rendering has no DOM.

import { useEffect, useRef } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * ShortcutMap — keys are shortcut strings in the format described above.
 * Values are handler functions called when the shortcut fires.
 *
 * WHY Record<string, () => void> (not a stricter union type):
 * A strict union of every possible shortcut string would be enormous and
 * inflexible. The runtime parsing provides the validation; callers use
 * literal strings so typos surface as "never fires" rather than type errors.
 */
type ShortcutMap = Record<string, () => void>;

// ── Normalise key string ──────────────────────────────────────────────────────

/**
 * buildKeyString — convert a KeyboardEvent into the canonical shortcut string.
 *
 * Examples:
 *   Ctrl+K on Windows  → "ctrl+k"
 *   Cmd+K on macOS     → "cmd+k"
 *   Escape             → "escape"
 *   /                  → "/"
 *
 * WHY lowercase: shortcut map keys are always lowercase; normalising here
 * prevents case-sensitive mismatches for letter keys.
 */
function buildKeyString(event: KeyboardEvent): string {
  const parts: string[] = [];
  // Order: ctrl → cmd → shift → alt → key.
  // WHY separate ctrl and metaKey: consumers may want to match only one
  // (e.g. Ctrl+K on Windows but NOT Cmd+K on Mac, or vice versa).
  if (event.ctrlKey) parts.push("ctrl");
  if (event.metaKey) parts.push("cmd");
  if (event.shiftKey) parts.push("shift");
  if (event.altKey) parts.push("alt");
  // Use event.key (not event.code) so virtual keyboards and non-QWERTY layouts
  // produce the correct character, not the physical key position.
  parts.push(event.key.toLowerCase());
  return parts.join("+");
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useKeyboardShortcuts — register a shortcut map for the component's lifetime.
 *
 * Attaches a single `keydown` listener to `window` on mount; detaches on
 * unmount. The map reference is stored in a ref so updating the map object
 * between renders does NOT re-register the listener (stable listener identity
 * avoids focus/capture order churn in deeply-nested overlays).
 */
export function useKeyboardShortcuts(shortcuts: ShortcutMap): void {
  // WHY a ref for the map: shortcut handlers often close over component state.
  // If we naively passed the map into the effect deps, every render that creates
  // a new object literal would re-attach the listener. Using a ref means the
  // listener always reads the latest handlers without re-registering.
  const shortcutsRef = useRef<ShortcutMap>(shortcuts);
  // Keep the ref in sync on every render (no deps needed in effect).
  shortcutsRef.current = shortcuts;

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Skip shortcut handling when the user is typing in an input/textarea/
      // select or a contenteditable element — shortcuts should not fire while
      // the user is composing text.
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }

      const key = buildKeyString(event);
      const handler = shortcutsRef.current[key];
      if (handler) {
        // WHY not calling event.preventDefault() here:
        // Some shortcuts (e.g. "/" for search focus) need it; others (Escape)
        // have no default to prevent. We leave that to the handler so callers
        // have control without fighting a blanket preventDefault.
        handler();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
    // No deps: listener registration is only tied to mount/unmount.
    // shortcutsRef.current is always current via the ref pattern above.
  }, []);
}
