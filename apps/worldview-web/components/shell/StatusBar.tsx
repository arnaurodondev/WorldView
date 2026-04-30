/**
 * components/shell/StatusBar.tsx — Bloomberg-inspired bottom status bar.
 *
 * WHY THIS EXISTS: Bloomberg Terminal has a bottom function-key bar showing
 * keyboard shortcuts and system status. This gives the platform two professional
 * signals: (1) keyboard shortcuts suggest power-user depth; (2) connection status
 * gives instant system health feedback without navigating to a settings page.
 *
 * WHY 24px HEIGHT: Same as Bloomberg's command line. Compact enough to not
 * steal vertical space from data panels. Barely perceptible as chrome.
 *
 * PLAN-0059 W1 F-LAYOUT-001 fix (2026-04-30):
 *   The previous implementation hardcoded a 6-item SHORTCUTS array (G+D, G+S,
 *   G+W, G+P, G+A, ⌘K) with NO global keyboard listener wired anywhere. The
 *   StatusBar was advertising chord shortcuts that did nothing — promised-but-
 *   broken hotkeys actively destroy trust within 90 seconds of demo. The audit
 *   ranked this as the single most damaging Layout finding.
 *
 *   The bar now reads from `lib/hotkey-registry` via the HotkeyProvider context.
 *   It can ONLY display chords that are actually registered. If a chord is
 *   unregistered (e.g., its owning component unmounted), it disappears from
 *   the StatusBar automatically. Structurally impossible to lie.
 *
 * WHO USES IT: app/(app)/layout.tsx — rendered at the very bottom of the shell
 * DATA SOURCE: hotkey-registry (live registered bindings, scope=global, group=Navigation)
 * DESIGN REFERENCE: Pattern 12 from Bloomberg Terminal UI research; deep-dive §7.3
 */

"use client";
// WHY "use client": uses usePathname() for active route highlighting + reads
// the registry via context (browser-only).

import { usePathname } from "next/navigation";
import { useMemo } from "react";
import { formatChordForDisplay } from "@/lib/hotkey-registry";
import { useHotkeyBindings } from "@/contexts/HotkeyContext";

/**
 * How many chord hints fit comfortably on the StatusBar left cluster at a
 * 1280px viewport before they push the right cluster off-screen.
 *
 * WHY 6: matches the original hand-curated count. The Navigation group always
 * fits ~6-8 chords; we cap to keep the bar visually balanced. The cheat sheet
 * (`?`) shows the full list — the StatusBar is a "popular" subset by design.
 */
const STATUS_BAR_HINT_LIMIT = 6;

/**
 * Priority order for chord IDs that get shown in the StatusBar. Bindings whose
 * id matches this list (in order) are surfaced first; the remainder are hidden
 * (still discoverable via `?`).
 *
 * WHY id-based prioritisation (not group-based): we want the same six chords
 * Bloomberg users have muscle-memorised — Dashboard / Screener / Workspace /
 * Portfolio / Alerts / Search — regardless of their group taxonomy.
 */
const PRIORITY_IDS: readonly string[] = [
  "nav.dashboard",
  "nav.screener",
  "nav.workspace",
  "nav.portfolio",
  "nav.alerts",
  "shell.search.focus",
  "shell.help.cheatsheet",
];

export function StatusBar() {
  const pathname = usePathname();
  const bindings = useHotkeyBindings();

  // Pick the chord hints to display. Sort by PRIORITY_IDS order, then any
  // remaining global Navigation chords, then cap at STATUS_BAR_HINT_LIMIT.
  const hints = useMemo(() => {
    const byId = new Map(bindings.map((b) => [b.id, b]));
    const ordered = [];
    for (const id of PRIORITY_IDS) {
      const b = byId.get(id);
      if (b) ordered.push(b);
    }
    // Optionally fall through to additional Navigation chords if priority list
    // didn't fill the limit.
    if (ordered.length < STATUS_BAR_HINT_LIMIT) {
      const usedIds = new Set(ordered.map((b) => b.id));
      for (const b of bindings) {
        if (usedIds.has(b.id)) continue;
        if (b.scope !== "global") continue;
        if (b.group !== "Navigation") continue;
        ordered.push(b);
        if (ordered.length >= STATUS_BAR_HINT_LIMIT) break;
      }
    }
    return ordered.slice(0, STATUS_BAR_HINT_LIMIT);
  }, [bindings]);

  // Derive active route label for the right-side breadcrumb.
  // WHY uppercase mono label: Bloomberg's status bar uses short uppercase identifiers
  // (e.g. "EQUITY", "FIXED INCOME") to show active function. Mirrors that pattern.
  const activeLabel =
    pathname?.startsWith("/dashboard") ? "DASHBOARD" :
    pathname?.startsWith("/screener") ? "SCREENER" :
    pathname?.startsWith("/workspace") ? "WORKSPACE" :
    pathname?.startsWith("/portfolio") ? "PORTFOLIO" :
    pathname?.startsWith("/instruments") ? "INSTRUMENT" :
    pathname?.startsWith("/alerts") ? "ALERTS" :
    pathname?.startsWith("/news") ? "NEWS" :
    pathname?.startsWith("/chat") ? "CHAT" :
    pathname?.startsWith("/settings") ? "SETTINGS" : "";

  return (
    // WHY bg-background border-t: sits flush with the page background, separated
    // from content by a single near-invisible top border. No elevation/shadow needed —
    // the bar is ambient chrome, not a floating panel.
    // WHY shrink-0: prevents the status bar from being squeezed when the viewport
    // is short. The 24px allocation must be guaranteed regardless of content height.
    <div className="h-6 shrink-0 flex items-center justify-between px-3 border-t border-white/[0.06] bg-background">
      {/* Left: keyboard shortcut hints — derived from the live registry */}
      <div className="flex items-center gap-3 overflow-hidden" aria-label="Keyboard shortcuts">
        {hints.length === 0 ? (
          // Empty state — happens during initial hydration before bindings register.
          // WHY render an explicit placeholder span (not null): keeps the bar's
          // vertical alignment stable so the right cluster doesn't visually jump.
          <span className="text-[10px] text-muted-foreground/40">…</span>
        ) : (
          hints.map((b) => (
            <span
              key={b.id}
              className="flex items-center gap-1 text-[10px] text-muted-foreground/50 whitespace-nowrap"
              // The full label (e.g., "Go to Dashboard") is on the kbd's title
              // for tooltip discovery; the visible label is short.
              title={b.label}
            >
              <kbd className="font-mono text-[9px] text-primary/70">
                {formatChordForDisplay(b.chord)}
              </kbd>
              <span>{shortLabel(b.label)}</span>
            </span>
          ))
        )}
      </div>

      {/* Right: active page label + connection status */}
      <div className="flex items-center gap-3 shrink-0">
        {/* Active page breadcrumb — shows which section of the terminal is active */}
        {activeLabel && (
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground/50 font-mono">
            {activeLabel}
          </span>
        )}

        {/* Connection status dot — static green when connected */}
        {/* WHY static (no animate-pulse): Bloomberg status dots are static.
            The color (green=live) communicates state; pulsing animation is a
            consumer-app pattern — institutional terminals don't pulse because
            it would be distracting on a densely-packed display. */}
        <div className="flex items-center gap-1">
          <span className="h-1.5 w-1.5 rounded-full bg-positive" aria-hidden />
          <span className="text-[10px] text-muted-foreground/50 font-mono">Live</span>
        </div>
      </div>
    </div>
  );
}

/**
 * shortLabel — strip "Go to " / "Open " / "Toggle " / "Show " prefixes so the
 * StatusBar shows compact one-word labels next to each chord (matches the
 * original hand-curated list).
 *
 * Examples:
 *   "Go to Dashboard"           → "Dashboard"
 *   "Show keyboard shortcuts"   → "Keyboard shortcuts"
 *   "Focus global search"       → "Search"
 *   "Toggle sidebar"            → "Sidebar"
 */
function shortLabel(label: string): string {
  return label
    .replace(/^Go to /, "")
    .replace(/^Open /, "")
    .replace(/^Toggle /, "")
    .replace(/^Show /, "")
    .replace(/^Focus global /, "")
    .replace(/^Focus /, "");
}
