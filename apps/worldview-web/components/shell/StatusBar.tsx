/**
 * components/shell/StatusBar.tsx — Bloomberg-inspired bottom status bar
 *
 * WHY THIS EXISTS: Bloomberg Terminal has a bottom function-key bar showing
 * keyboard shortcuts and system status. This gives the platform two professional
 * signals: (1) keyboard shortcuts suggest power-user depth; (2) connection status
 * gives instant system health feedback without navigating to a settings page.
 *
 * WHY 24px HEIGHT: Same as Bloomberg's command line. Compact enough to not
 * steal vertical space from data panels. Barely perceptible as chrome.
 *
 * WHO USES IT: app/(app)/layout.tsx — rendered at the very bottom of the shell
 * DATA SOURCE: none — keyboard hints are static; connection status is static green
 *              (live market data WebSocket connection is assumed healthy; a future
 *              iteration can wire this to actual WebSocket state)
 * DESIGN REFERENCE: Pattern 12 from Bloomberg Terminal UI research
 */

"use client";
// WHY "use client": uses usePathname() for active route highlighting

import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

// Keyboard shortcut definitions — mirrors useHotkeys bindings in layout
// WHY show these here (not in a help modal): Bloomberg puts shortcuts in the
// status bar so power users see them constantly and build muscle memory faster.
// Constant-visibility reinforcement is more effective than a discoverable modal.
const SHORTCUTS = [
  { keys: "G+D", label: "Dashboard" },
  { keys: "G+S", label: "Screener" },
  { keys: "G+W", label: "Workspace" },
  { keys: "G+P", label: "Portfolio" },
  { keys: "G+A", label: "Alerts" },
  { keys: "⌘K", label: "Search" },
] as const;

export function StatusBar() {
  const pathname = usePathname();

  // Derive active route label for the right-side breadcrumb.
  // WHY uppercase mono label: Bloomberg's status bar uses short uppercase identifiers
  // (e.g. "EQUITY", "FIXED INCOME") to show active function. Mirrors that pattern.
  const activeLabel =
    pathname.startsWith("/dashboard") ? "DASHBOARD" :
    pathname.startsWith("/screener") ? "SCREENER" :
    pathname.startsWith("/workspace") ? "WORKSPACE" :
    pathname.startsWith("/portfolio") ? "PORTFOLIO" :
    pathname.startsWith("/instruments") ? "INSTRUMENT" :
    pathname.startsWith("/alerts") ? "ALERTS" :
    pathname.startsWith("/chat") ? "CHAT" :
    pathname.startsWith("/settings") ? "SETTINGS" : "";

  return (
    // WHY bg-background border-t: sits flush with the page background, separated
    // from content by a single near-invisible top border. No elevation/shadow needed —
    // the bar is ambient chrome, not a floating panel.
    // WHY shrink-0: prevents the status bar from being squeezed when the viewport
    // is short. The 24px allocation must be guaranteed regardless of content height.
    <div className="h-6 shrink-0 flex items-center justify-between px-3 border-t border-white/[0.06] bg-background">
      {/* Left: keyboard shortcut hints */}
      <div className="flex items-center gap-3 overflow-hidden">
        {SHORTCUTS.map((s) => (
          <span key={s.keys} className="flex items-center gap-1 text-[10px] text-muted-foreground/50 whitespace-nowrap">
            {/* WHY opacity-50 on text (muted-foreground/50): shortcuts are ambient
                information — should not compete with main content. Fading them to
                50% makes them recede visually until the user needs them. */}
            <kbd className="font-mono text-[9px] text-primary/70">{s.keys}</kbd>
            <span>{s.label}</span>
          </span>
        ))}
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
