/**
 * components/instrument/tabs/InstrumentTabs.tsx — three-tab bar (Quote / Financials / Intel)
 *
 * WHY THIS EXISTS: PRD-0088 §6.6 collapses 4 tabs into 3 with underline
 * markers and Q/F/I keyboard mnemonics so power users never touch the mouse.
 * WHO USES IT: components/instrument/InstrumentPageClient.tsx (T-A-05).
 *
 * W5-T-26: adds Quote-tab-scoped hotkeys via HotkeyScope (scope="page"):
 *   B → dispatch "wv:brief-toggle" event (AiBriefBanner listens)
 *   D → dispatch "wv:desc-toggle" event (CompanyAboutCard listens)
 *   Shift+R is wired directly in QuoteTab.tsx (needs qc access).
 *
 * WHY custom DOM events (not global store): the banner and card are mounted
 * deep in the tree; passing callbacks as props would require drilling through
 * InstrumentPageClient → QuoteTab → CompanyAboutCard. Events are cleaner for
 * "fire-and-forget" toggle actions between decoupled siblings.
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
  // registration stable across parent re-renders.
  const bindings = useMemo(
    () => [
      // Tab-switch chords (always active on the instrument page).
      ...TABS.map((t) => ({
        id: `ins.tab.${t.key}`,
        chord: t.chord,
        group: "Symbol" as const,
        label: `${t.label} tab`,
        handler: () => onTabChange(t.key),
      })),
      // Quote-tab-scoped chords: B (brief), D (description).
      // WHY custom events: decoupled fire-and-forget; banner/card listen via useEffect.
      {
        id: "ins.quote.brief",
        chord: "b",
        group: "Symbol" as const,
        label: "Toggle brief expand",
        handler: () => window.dispatchEvent(new CustomEvent("wv:brief-toggle")),
      },
      {
        id: "ins.quote.desc",
        chord: "d",
        group: "Symbol" as const,
        label: "Toggle description expand",
        handler: () => window.dispatchEvent(new CustomEvent("wv:desc-toggle")),
      },
      // Financials-tab-scoped chord: P (period toggle annual/quarterly).
      // WHY scope guard (activeTab === "financials"): p is a common key that
      // could fire accidentally while on Quote/Intelligence. The guard keeps
      // the binding harmless outside the Financials tab.
      // WHY custom event (not direct setState): FinancialsTab owns the period
      // state; InstrumentTabs is unaware of it. Dispatching an event avoids
      // prop-drilling a setPeriodType callback through InstrumentPageClient.
      // Alt+1..5 section scroll: not bound as hotkeys — analysts use standard
      // browser scroll (arrow keys / Page Down) since the left column has
      // natural focus. Reserved for a future scroll-to-section feature.
      {
        id: "ins.financials.period",
        chord: "p",
        group: "Symbol" as const,
        label: "Toggle annual/quarterly period (Financials tab)",
        handler: () => {
          if (activeTab === "financials") {
            window.dispatchEvent(new CustomEvent("wv:financials-period-toggle"));
          }
        },
      },
    ],
    [onTabChange, activeTab],
  );

  return (
    <div className="flex h-8 items-end gap-4 border-b border-border px-3">
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
            className={`pb-1.5 text-[11px] font-medium uppercase tracking-wide transition-colors ${cls}`}
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
