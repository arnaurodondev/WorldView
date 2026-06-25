/**
 * components/instrument/tabs/InstrumentTabs.tsx — three-tab bar (Quote / Financials / Intel)
 *
 * WHY THIS EXISTS: PRD-0088 §6.6 collapses 4 tabs into 3 with underline
 * markers and Q/F/I keyboard mnemonics so power users never touch the mouse.
 * WHO USES IT: components/instrument/InstrumentPageClient.tsx (T-A-05).
 * DATA SOURCE: presentational — activeTab + onTabChange come from parent.
 * DESIGN REFERENCE: docs/specs/0088-…-redesign.md §6.6.
 * TARGET READER: junior Next.js dev — HotkeyScope is the in-house pattern
 * for page-scoped chords; it auto-suspends inside text inputs.
 */

"use client";
// WHY "use client": this component owns a HotkeyScope which subscribes to
// the HotkeyContext via useEffect at mount — requires the client runtime.

import { useMemo, useRef, type KeyboardEvent } from "react";
import { HotkeyScope } from "@/components/shell/HotkeyScope";

// WHY exported union: InstrumentPageClient + tab content components all
// reference the same value set — keeps everything in lockstep.
export type InstrumentTabKey = "quote" | "financials" | "intelligence";

interface InstrumentTabsProps {
  readonly activeTab: InstrumentTabKey;
  readonly onTabChange: (tab: InstrumentTabKey) => void;
}

// WHY const tuple: visual order and hotkey-binding order stay in sync.
const TABS: ReadonlyArray<{ key: InstrumentTabKey; label: string; chord: string }> = [
  { key: "quote", label: "QUOTE", chord: "q" },
  { key: "financials", label: "FINANCIALS", chord: "f" },
  { key: "intelligence", label: "INTELLIGENCE", chord: "i" },
];

export function InstrumentTabs({ activeTab, onTabChange }: InstrumentTabsProps) {
  // WHY useMemo for bindings: HotkeyScope re-registers whenever the
  // `bindings` reference changes. Memoising against onTabChange keeps the
  // registration stable across parent re-renders (only churns when the
  // callback identity changes — usually never for a stable setState ref).
  const bindings = useMemo(
    () =>
      TABS.map((t) => ({
        id: `ins.tab.${t.key}`,
        chord: t.chord,
        group: "Symbol" as const,
        label: `${t.label} tab`,
        handler: () => onTabChange(t.key),
      })),
    [onTabChange],
  );

  // ── Roving tabindex (Round-4 hardening, item 2) ────────────────────────────
  // WHY refs to the three buttons: arrow-key navigation must MOVE FOCUS (not
  // just selection) so the focus ring follows the active tab — the roving-
  // tabindex pattern from the WAI-ARIA Authoring Practices tabs widget.
  // WHY we deliberately KEEP role="button" + aria-current (and do NOT switch
  // to role="tab"/"tablist"): the tab PANELS in InstrumentPageClient are
  // conditionally rendered (unmounted when inactive), so there is no stable
  // tabpanel node to point aria-controls at — half-implemented tab semantics
  // (tabs without panels) are worse for screen readers than honest buttons
  // with aria-current="page". The existing test suite also pins the button
  // role + aria-current contract (R19: never weaken tests).
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  /** Move selection AND focus by arrow keys; Home/End jump to the edges. */
  const handleKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number | null = null;
    // WHY wrap-around (modulo): ArrowRight on the last tab lands on the first
    // — the WAI-ARIA recommended behaviour for horizontal tab strips.
    if (e.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = TABS.length - 1;
    if (next === null) return;
    // preventDefault: Home/End would otherwise scroll the page.
    e.preventDefault();
    onTabChange(TABS[next].key);
    tabRefs.current[next]?.focus();
  };

  return (
    <div className="flex h-8 items-end gap-6 border-b border-border px-3">
      {TABS.map((t, index) => {
        const isActive = activeTab === t.key;
        // WHY border-b-2 on both branches: keeps the baseline height
        // identical so switching tabs does NOT cause a 2px vertical jump.
        const cls = isActive
          ? "border-b-2 border-primary text-foreground"
          : "border-b-2 border-transparent text-muted-foreground hover:text-foreground/70";
        return (
          <button
            key={t.key}
            ref={(el) => { tabRefs.current[index] = el; }}
            type="button"
            onClick={() => onTabChange(t.key)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            // Roving tabindex: only the ACTIVE tab participates in the page's
            // Tab order (tabIndex 0); the strip is then navigated internally
            // with arrows. This keeps the tab strip ONE Tab-stop instead of
            // three — the canonical composite-widget keyboard contract.
            tabIndex={isActive ? 0 : -1}
            // Round-3 item 5: focus-visible ring so keyboard users can see
            // which tab button holds focus (the Q/F/I chords cover power
            // users, but plain Tab navigation must work too).
            className={`pb-1.5 text-[11px] font-medium uppercase tracking-wide transition-colors rounded-[2px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${cls}`}
            aria-current={isActive ? "page" : undefined}
          >
            {t.label}
          </button>
        );
      })}
      {/* WHY HotkeyScope scoped page=/instruments/: bindings only fire on
          this route, so pressing Q on the dashboard does nothing. The
          registry also auto-suspends while a text input is focused. */}
      <HotkeyScope scope="page" page="/instruments/" bindings={bindings} />
    </div>
  );
}
