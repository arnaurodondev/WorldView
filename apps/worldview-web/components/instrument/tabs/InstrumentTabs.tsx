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

import { useMemo } from "react";
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

  return (
    <div className="flex h-8 items-end gap-6 border-b border-border px-3">
      {TABS.map((t) => {
        const isActive = activeTab === t.key;
        // WHY border-b-2 on both branches: keeps the baseline height
        // identical so switching tabs does NOT cause a 2px vertical jump.
        const cls = isActive
          ? "border-b-2 border-primary text-foreground"
          : "border-b-2 border-transparent text-muted-foreground hover:text-foreground/70";
        return (
          <button
            key={t.key}
            type="button"
            onClick={() => onTabChange(t.key)}
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
