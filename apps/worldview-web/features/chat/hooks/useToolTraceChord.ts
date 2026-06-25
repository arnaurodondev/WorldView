"use client";
// WHY "use client": registers a hotkey binding via React context + state — browser only.

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
 * ROUND 4 HARDENING — REGISTRY MIGRATION (DESIGN_SYSTEM.md §6.12):
 * This hook previously owned a RAW `document.addEventListener("keydown")`
 * listener. That worked, but it was invisible to the central hotkey registry
 * (`lib/hotkey-registry`) — and therefore invisible to the `?` cheat-sheet
 * overlay, breaking the platform's "no-lying invariant" (every live chord
 * must be discoverable from the registry; §6.12 explicitly flagged this hook
 * as the known gap). It also meant TWO keydown dispatch paths existed on the
 * chat page (the registry's `useChordHotkeys` listener + this one), with no
 * scope arbitration between them.
 *
 * The migration follows the CommandPalette pattern (`shell.command.palette`,
 * Round-3): register a `HotkeyBinding` through the contextual registry from
 * `useHotkeyScope()` and let the single `useChordHotkeys` document listener
 * (mounted by GlobalHotkeyBindings in the app layout) do the dispatching.
 * What the registry buys us over the raw listener:
 *
 *   1. The `?` cheat sheet lists "⌘D — Toggle tool trace (debug)" — but ONLY
 *      while ?debug=1 is active, because the binding is registered only while
 *      `enabled` is true (see the registration effect below). The Q-8 gate
 *      and the cheat-sheet honesty rule compose for free.
 *   2. Modifier-bearing chords (mod+d) pass through the listener's
 *      input-suspension rule, so ⌘D still works while the composer textarea
 *      has focus — same behaviour as the old raw listener, now centrally
 *      guaranteed (pinned in __tests__/use-chord-hotkeys.test.tsx).
 *   3. Scope arbitration: while a modal dialog is open (scope "modal"), the
 *      registry's modal short-circuit suspends this global binding — the old
 *      raw listener would have toggled the drawer underneath an open dialog.
 *   4. preventDefault on match is handled by the dispatcher, so Ctrl/⌘+D only
 *      loses its browser bookmark default when the binding is actually live
 *      (debug mode on) — identical to the old behaviour, one code path.
 *
 * GATING (unchanged): `enabled=false` (no ?debug=1) → NO binding registered,
 * the chord does nothing, the cheat sheet does not advertise it, and the
 * drawer force-closes if the flag is removed mid-session.
 */

import { useCallback, useEffect, useState } from "react";

// WHY useHotkeyScope (not the lib/hotkey-registry singleton directly): the
// provider may be given a custom registry instance (tests do this to avoid
// cross-test pollution). Registering on the contextual registry guarantees
// the binding lands in the SAME instance the chord dispatcher + cheat sheet
// read from. This is the exact pattern CommandPalette established in Round 3.
import { useHotkeyScope } from "@/contexts/HotkeyContext";

/**
 * Stable binding id — used for registry deduplication and cheat-sheet keying.
 * Exported so tests can assert the binding's presence/absence in the registry
 * without hardcoding the string twice.
 */
export const TOOL_TRACE_CHORD_ID = "chat.tooltrace.drawer";

export function useToolTraceChord(enabled: boolean): {
  /** Whether the drawer is currently open. Always false when disabled. */
  isOpen: boolean;
  /** Imperative close — used by the drawer's own close button. */
  close: () => void;
} {
  const [isOpen, setIsOpen] = useState(false);
  const { registry } = useHotkeyScope();

  // Force-close when debug mode is turned off mid-session (e.g. the user
  // edits the URL). Without this the drawer would stay mounted with no way
  // to reopen it after a re-toggle, and worse, would keep exposing trace
  // data after the gate was removed.
  useEffect(() => {
    if (!enabled) setIsOpen(false);
  }, [enabled]);

  // Register the chord ONLY while debug mode is enabled. register() returns
  // its own unregister function — returning it directly from the effect means
  // React unregisters on disable/unmount, so the binding's lifetime exactly
  // matches the ?debug=1 session (Q-8 gate) and never leaks across routes.
  useEffect(() => {
    if (!enabled) return;
    return registry.register({
      id: TOOL_TRACE_CHORD_ID,
      // "mod+d" canonicalises to ⌘D on macOS / Ctrl+D elsewhere — same
      // cross-platform convention the old raw listener implemented by hand
      // with (e.metaKey || e.ctrlKey).
      chord: "mod+d",
      // WHY scope "global" (not "page"): the binding's lifetime is already
      // scoped to the chat page (this hook only mounts there) — registering
      // and unregistering with the component is the page-scoping mechanism.
      // The "page" scope would additionally require a <HotkeyScope> push that
      // nothing on the chat page performs today.
      scope: "global",
      // "View" — the drawer is a panel toggle, same family as ⌘B sidebar /
      // ⌘. statusbar in the HotkeyGroup taxonomy.
      group: "View",
      label: "Toggle tool trace (debug)",
      // WHY a functional update (not closing over isOpen): keeps the handler
      // identity stable across open/close flips so we never need isOpen in
      // the effect deps — no churn of unregister/register on every toggle.
      handler: () => setIsOpen((prev) => !prev),
    });
  }, [enabled, registry]);

  const close = useCallback(() => setIsOpen(false), []);

  return { isOpen, close };
}
