/**
 * components/shell/GlobalHotkeyBindings.tsx — Register all app-wide chords.
 *
 * WHY THIS EXISTS: PLAN-0059 W1 closes F-LAYOUT-001 (StatusBar lying about
 * keyboard shortcuts). This component is mounted once inside the (app) layout
 * and registers every globally-available chord:
 *
 *   Navigation chords (g d/p/i/s/w/a/n/c/h/,):
 *     g d  →  /dashboard
 *     g p  →  /portfolio
 *     g i  →  /instruments  (redirects to /screener — but the chord is still useful as muscle memory)
 *     g s  →  /screener
 *     g w  →  /workspace
 *     g a  →  /alerts
 *     g n  →  /news (currently 307 → /alerts; will be promoted in Wave 6)
 *     g c  →  /chat
 *     g h  →  cheat-sheet (alias for `?` — delegates to shell.help.cheatsheet binding)
 *     g ,  →  /settings
 *
 *   View toggles:
 *     mod+b  →  toggle sidebar (callback prop — owned by layout state)
 *     mod+\ →  toggle StatusBar / full-width (placeholder — Wave 5)
 *
 *   Search / palette:
 *     mod+k  →  intentionally NOT registered here — cmdk's Dialog handles ⌘K via
 *               its own keydown listener. Registering it would call e.stopPropagation()
 *               (via useChordHotkeys on match) and silently break the command palette.
 *               The `?` overlay lists all real shortcuts; ⌘K is discoverable there.
 *     /      →  focus GlobalSearch input
 *
 *   Help:
 *     ?      →  toggle cheat-sheet (registered by HotkeyCheatSheet itself)
 *
 * WHY a component (not inline in layout.tsx): keeps the layout file focused on
 * shell layout concerns. All binding declarations live in one place — easier
 * to audit "what chords does the app have?" without grepping.
 *
 * WHY useChordHotkeys is mounted here: this component lives directly under
 * HotkeyProvider, so the listener has access to the scope context. Mounting
 * it any deeper would still work but we co-locate with the bindings for
 * clarity.
 */

"use client";
// WHY "use client": uses useRouter and registers chord handlers.

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import { useChordHotkeys } from "@/hooks/useChordHotkeys";
import type { HotkeyBinding } from "@/lib/hotkey-registry";

// ── Props ─────────────────────────────────────────────────────────────────────

interface GlobalHotkeyBindingsProps {
  /**
   * Toggle the sidebar — owned by layout.tsx state. Passed in so the chord
   * doesn't need to know about localStorage / sidebarExpanded plumbing.
   */
  readonly onToggleSidebar: () => void;
  /**
   * Open the command palette / focus search input. The existing GlobalSearch
   * component already handles ⌘K via cmdk; this prop exists so a future
   * standalone palette can be opened from a chord.
   *
   * For now it's optional — when not supplied the chord is not registered so
   * the cheat sheet won't list it, preserving the no-lying-StatusBar invariant.
   */
  readonly onFocusSearch?: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function GlobalHotkeyBindings({
  onToggleSidebar,
  onFocusSearch,
}: GlobalHotkeyBindingsProps) {
  const router = useRouter();
  const { registry } = useHotkeyScope();

  // Mount the document-level listener. Doing this here (vs in layout.tsx)
  // keeps the chord plumbing co-located with the bindings.
  useChordHotkeys();

  // Build the list of bindings. useMemo so the registration effect doesn't
  // re-fire on every render. `registry` is stable within a provider tree but
  // is listed in deps so React Compiler can track the captured closure.
  const bindings = useMemo<HotkeyBinding[]>(() => {
    const navTo = (path: string, id: string, label: string): HotkeyBinding => ({
      id,
      chord: "",
      scope: "global",
      group: "Navigation",
      label,
      handler: () => router.push(path),
    });

    const list: HotkeyBinding[] = [
      // ── Navigation chords (g + letter) ────────────────────────────────────
      { ...navTo("/dashboard", "nav.dashboard", "Go to Dashboard"), chord: "g d" },
      { ...navTo("/portfolio", "nav.portfolio", "Go to Portfolio"), chord: "g p" },
      { ...navTo("/instruments", "nav.instruments", "Go to Instruments"), chord: "g i" },
      { ...navTo("/screener", "nav.screener", "Go to Screener"), chord: "g s" },
      { ...navTo("/workspace", "nav.workspace", "Go to Workspace"), chord: "g w" },
      { ...navTo("/alerts", "nav.alerts", "Go to Alerts"), chord: "g a" },
      { ...navTo("/news", "nav.news", "Go to News"), chord: "g n" },
      { ...navTo("/chat", "nav.chat", "Go to Chat"), chord: "g c" },
      { ...navTo("/settings", "nav.settings", "Go to Settings"), chord: "g ," },

      // ── g h — alias for `?` (cheat-sheet toggle) ──────────────────────
      // WHY delegation (not direct state access): the open/close state lives
      // inside HotkeyCheatSheet which registers shell.help.cheatsheet with
      // its setOpen callback. We cannot import or prop-drill that setter here
      // without circular coupling. Delegating via the registry means the two
      // bindings always share the same toggle behaviour — if HotkeyCheatSheet
      // is refactored, g h stays correct automatically.
      {
        id: "nav.help.cheatsheet",
        chord: "g h",
        scope: "global",
        group: "Navigation",
        label: "Open keyboard shortcuts",
        handler: (e) => {
          const cs = registry.all().find((b) => b.id === "shell.help.cheatsheet");
          if (cs) void cs.handler(e);
        },
      },

      // ── View toggles ──────────────────────────────────────────────────
      {
        id: "view.toggle.sidebar",
        chord: "mod+b",
        scope: "global",
        group: "View",
        label: "Toggle sidebar",
        handler: onToggleSidebar,
      },
    ];

    // Search focus (optional — only register if a handler was supplied).
    if (onFocusSearch) {
      list.push({
        id: "shell.search.focus",
        chord: "/",
        scope: "global",
        group: "Symbol",
        label: "Focus global search",
        handler: () => onFocusSearch(),
      });
    }

    return list;
  }, [router, onToggleSidebar, onFocusSearch, registry]);

  // Register all bindings on mount; unregister on unmount.
  useEffect(() => {
    const unsubs = bindings.map((b) => registry.register(b));
    return () => {
      for (const u of unsubs) u();
    };
  }, [bindings, registry]);

  // No DOM output — purely registration side-effects.
  return null;
}
