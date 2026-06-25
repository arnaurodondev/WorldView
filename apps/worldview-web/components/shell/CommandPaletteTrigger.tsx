/**
 * components/shell/CommandPaletteTrigger.tsx — the VISIBLE, always-present
 * entry point that advertises the ⌘K command palette in the TopBar.
 *
 * WHY THIS EXISTS (UI competitive roadmap §3 / B4 "Make ⌘K discoverable"):
 * Worldview already ships a real command palette (CommandPalette.tsx) — a
 * genuine differentiator over Koyfin/TIKR. But the palette was previously only
 * reachable two ways:
 *   1. the ⌘K / Ctrl+K chord (invisible — undiscoverable to a new user), and
 *   2. a tiny bare "⌘K" glyph chip in the TopBar (present, but reads as
 *      decoration, not as a clickable search entry point).
 * Premium terminals (Superhuman, Linear, Bloomberg <GO>) make the command
 * entry point look like a SEARCH BOX with the shortcut inside it — a wide,
 * obviously-clickable "Search or jump to…  ⌘K" affordance. That single change
 * turns an invisible asset into a premium signal "for nearly free".
 *
 * WHAT IT DOES: renders a subtle, terminal-grade search-style button. Clicking
 * it (mouse users) OR pressing the chord (keyboard users) both open the SAME
 * palette — this component never duplicates the palette, it only opens it.
 *
 * HOW IT TRIGGERS THE PALETTE: it dispatches the `worldview:open-command-palette`
 * CustomEvent (exported as OPEN_COMMAND_PALETTE_EVENT from CommandPalette.tsx).
 * CommandPalette (mounted once in app/(app)/layout.tsx) listens for that event
 * and flips its own open state. This is the established shell decoupling pattern
 * (mirrors worldview:open-ai-panel / worldview:open-feedback) and means this
 * trigger needs NO opener prop drilled through the layout → TopBar chain.
 *
 * WHO USES IT: components/shell/TopBar.tsx (left cluster, after GlobalSearch).
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §6.15 Command Palette.
 */

"use client";
// WHY "use client": dispatches a browser CustomEvent on click and does runtime
// platform detection (mac vs non-mac) inside an effect — both are browser-only.

import { useEffect, useState } from "react";
import { Search } from "lucide-react";
// The palette owns the open-event contract; we import the constant so a typo'd
// event string can't silently no-op (the palette listener would never fire).
import { OPEN_COMMAND_PALETTE_EVENT } from "@/components/shell/CommandPalette";
// Platform-aware chord rendering. formatChordForDisplay("mod+k") returns "⌘K"
// on mac and "Ctrl+K" elsewhere — the SAME helper the cheat sheet uses, so the
// hint we show is guaranteed to match the registered chord (no-lying invariant).
import { formatChordForDisplay } from "@/lib/hotkey-registry";

/**
 * openCommandPalette — fire the decoupled open event.
 * Extracted so the click handler and any future programmatic opener share one
 * code path, and so the test can assert on the exact event name.
 */
export function openCommandPalette(): void {
  window.dispatchEvent(new CustomEvent(OPEN_COMMAND_PALETTE_EVENT));
}

export function CommandPaletteTrigger() {
  // ── Hydration-safe platform label ────────────────────────────────────────
  // WHY a mount gate (not a direct formatChordForDisplay call at render):
  // formatChordForDisplay does runtime platform detection via navigator, which
  // is unavailable during SSR. If we rendered the platform-specific label on
  // the server it would always assume non-mac ("Ctrl+K"), and a mac client
  // would then hydrate to "⌘K" — a React hydration text mismatch warning.
  //
  // Fix: render a STABLE placeholder ("⌘K") on the server and on the very
  // first client render (so the markup matches), then swap to the real
  // platform-aware label in an effect after mount. The default placeholder is
  // the mac glyph because it matches the pre-existing chip convention and the
  // DESIGN_SYSTEM copy; non-mac users see it correct themselves a frame later.
  const [chordLabel, setChordLabel] = useState("⌘K");
  useEffect(() => {
    // Runs only on the client, after the first paint — safe to detect platform.
    setChordLabel(formatChordForDisplay("mod+k"));
  }, []);

  return (
    // WHY a <button> styled like a search input (not a real <input>): this is a
    // TRIGGER, not a field — typing happens inside the palette's own input once
    // it opens. A button is the correct semantics for "activate this surface"
    // and keeps a single keyboard tab-stop. role/label make the intent explicit
    // to assistive tech ("Search or jump to anything — Cmd/Ctrl K").
    //
    // STYLING (Terminal Dark, DESIGN_SYSTEM.md §4):
    //   - h-5 to sit inside the 32px (h-8) TopBar without crowding it.
    //   - rounded-[2px] 2px-radius chrome rule (no pill/rounded-full on boxes).
    //   - bg-muted/20 + border-border/50 = the same subtle "inset field" look
    //     GlobalSearch and the portfolio rail use, so the bar reads as one set.
    //   - w-44 gives it real "search box" presence (vs the old bare glyph) while
    //     staying inside shrink-0 so it never collapses; min/visible at md+.
    //   - text-muted-foreground placeholder-grey signals "empty field / hint".
    <button
      type="button"
      onClick={openCommandPalette}
      // Full intent for screen readers — the visible text is terse by design.
      aria-label="Search or jump to anything (Cmd+K or Ctrl+K)"
      // Native tooltip teaches the chord on hover for mouse users.
      title="Search or jump to anything (⌘K / Ctrl+K)"
      // WHY data-testid: lets the unit test target the trigger without coupling
      // to the (intentionally terse / platform-variant) visible label text.
      data-testid="command-palette-trigger"
      className="group flex h-5 w-44 shrink-0 items-center gap-1.5 rounded-[2px] border border-border/50 bg-muted/20 px-1.5 text-left text-[11px] text-muted-foreground transition-colors hover:border-border hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      {/* Magnifier icon — the universal "this is search" signifier. 1.5px stroke
          matches terminal icon weight (heavier 2px reads as consumer web app). */}
      <Search className="h-3 w-3 shrink-0" strokeWidth={1.5} aria-hidden="true" />

      {/* Prompt copy — "Search or jump to…" is the Linear/Superhuman convention:
          it advertises BOTH capabilities of the palette (search instruments AND
          jump to pages/conversations). truncate keeps it tidy if the slot ever
          shrinks. min-w-0 lets it truncate inside the flex row. */}
      <span className="min-w-0 flex-1 truncate">Search or jump to…</span>

      {/* The shortcut chip, pushed to the trailing edge. font-mono + the muted
          chip background reads as a physical key — the passive "you can also
          press this" teaching device. Platform-aware via chordLabel. */}
      <kbd className="ml-auto shrink-0 rounded-[2px] border border-border/50 bg-muted/40 px-1 font-mono text-[10px] text-muted-foreground-dim group-hover:text-foreground">
        {chordLabel}
      </kbd>
    </button>
  );
}
