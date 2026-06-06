/**
 * features/chat/components/ChatLayout.tsx — 3-column shell for /chat.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block B, T-04):
 *   Bloomberg-grade research chat needs three persistent rails visible at
 *   once: (1) the THREAD RAIL on the left so an analyst can pivot between
 *   research threads without losing context, (2) the MESSAGE COLUMN in the
 *   middle which is the high-density reading surface, and (3) the CONTEXT
 *   RAIL on the right which aggregates entity health, cumulative citations,
 *   detected contradictions and related tickers. The legacy `page.tsx` had
 *   only two columns — the right rail did not exist — which forced the
 *   analyst to scroll mid-message to verify sources. T-04 introduces the
 *   shell that hosts all three.
 *
 * WHY OWN THE COLLAPSE STATE HERE (not in page.tsx):
 *   The right-rail collapse toggle is purely a layout concern; the page
 *   should not have to know about column widths or chord listeners. We
 *   keep that knowledge inside the shell so callers compose the children
 *   without thinking about responsive behaviour.
 *
 * KEYBOARD CHORD — Cmd+\\ (or Ctrl+\\ on Windows/Linux):
 *   Pre-flight grep across `apps/worldview-web/` found ZERO existing
 *   listeners for `Meta+\\` / `Cmd+\\` / `'\\'`. The chord is therefore
 *   FREE in the global shell registry — no fallback to `Cmd+Shift+\\` is
 *   needed. The chord is scoped to this layout's lifetime (mounted while
 *   on /chat); navigating away unmounts the layout and removes the
 *   listener automatically.
 *
 * RESPONSIVE BREAKPOINTS (matches plan §6 T-04):
 *   - lg (>=1024px): 3-col `[224px | 1fr | 320px]`
 *   - md (768..1023px): 2-col `[224px | 1fr]` — rail auto-collapsed
 *   - sm (<768px): 1-col `[1fr]` — both rails hidden; v1.1 will add a
 *     slide-over for the context rail on small screens.
 *
 *   We use a single grid with Tailwind responsive variants instead of
 *   re-mounting subtrees so the message column scroll position is
 *   preserved when the viewport crosses a breakpoint.
 *
 * DATA SOURCE: pure presentational; reads no API.
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §3 (3-column shell) +
 *   §6.4 (column widths).
 */

"use client";
// WHY "use client": this component owns a DOM-level keydown listener and
// React state for the collapsed flag. Both require the browser runtime —
// a Server Component cannot register `window.addEventListener` or call
// `useState`.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface ChatLayoutProps {
  /**
   * Left thread rail. Caller passes `<ThreadRail .../>` (T-05). Width is
   * fixed at 224px by the parent grid, so the rail does not need to
   * declare its own width.
   */
  readonly threadRail: ReactNode;
  /**
   * Centre message column. Caller passes `<ChatMessageList/>` + composer +
   * any header chrome (T-06 + T-17). Min-width 0 on the grid cell prevents
   * long unbreakable tokens from forcing the rail columns to shrink.
   */
  readonly messageColumn: ReactNode;
  /**
   * Right context rail. Caller passes `<ChatContextRail/>` (T-16). Hidden
   * via the responsive grid when collapsed or on md/sm breakpoints.
   */
  readonly contextRail: ReactNode;
}

/**
 * ChatLayout — see file header.
 *
 * WHY named-slot props (not `children`):
 *   The plan spec called for `{ children }` but the page-level composition
 *   (Block G T-20) is dramatically clearer with three explicit slots —
 *   the caller cannot accidentally pass the message column where the
 *   thread rail belongs. The slots also let us key off render state
 *   (e.g. `contextRail === null` would force collapse) without using
 *   `React.Children.toArray` introspection, which is the React anti-pattern.
 *   Documented as a judgment call in the agent report.
 */
export function ChatLayout({ threadRail, messageColumn, contextRail }: ChatLayoutProps) {
  // ── Collapse state for the right-hand context rail ─────────────────────────
  // WHY default-open on lg: research analysts spend most of their time on
  // 1440x900+ external monitors where the rail fits comfortably. The
  // collapse is a deliberate gesture (Cmd+\\) rather than the default.
  const [contextRailCollapsed, setContextRailCollapsed] = useState(false);

  // ── Cmd+\\ chord handler ───────────────────────────────────────────────────
  // WHY a stable callback (useCallback): the effect below depends on this
  // and a fresh function identity every render would tear down + re-add
  // the listener on every keystroke elsewhere in the tree.
  const toggleContextRail = useCallback(() => {
    setContextRailCollapsed((prev) => !prev);
  }, []);

  useEffect(() => {
    // WHY listening on `window` (not `document`): some Radix portals attach
    // to body and stop document-level propagation; window-level always sees
    // the keydown regardless of focus target.
    function onKeyDown(event: KeyboardEvent) {
      // The chord: Meta (Cmd on macOS) or Ctrl (Win/Linux) + literal `\\`.
      // `event.key` reports the printable character; we match on `\\`
      // directly which is robust across keyboard layouts that physically
      // place backslash on a different key (e.g. ISO vs ANSI).
      const isModifier = event.metaKey || event.ctrlKey;
      if (!isModifier) return;
      if (event.key !== "\\") return;
      // Prevent the browser from interpreting Cmd+\\ as a shortcut (some
      // browsers map it to "toggle reader mode" or similar accessibility
      // chords). preventDefault() keeps the chord ours.
      event.preventDefault();
      toggleContextRail();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleContextRail]);

  return (
    <div
      // WHY data-testid: T-23 Playwright tests will locate this shell to
      // assert column widths at 1440x900. Stable attribute beats class name.
      data-testid="chat-layout"
      className={cn(
        // Base: 1-col on small screens (rails hidden).
        "grid h-full w-full overflow-hidden",
        "grid-cols-[minmax(0,1fr)]",
        // md (>=768px): 2-col — thread rail + message column. Context rail
        // is auto-collapsed at this breakpoint regardless of state.
        "md:grid-cols-[224px_minmax(0,1fr)]",
        // lg (>=1024px): 3-col when expanded, 2-col when collapsed.
        // grid-template-columns is the only declarative way to "remove"
        // a column without unmounting its content (which would lose
        // ChatContextRail's internal scroll position + cached selectors).
        contextRailCollapsed
          ? "lg:grid-cols-[224px_minmax(0,1fr)]"
          : "lg:grid-cols-[224px_minmax(0,1fr)_320px]",
      )}
    >
      {/*
        Thread rail — hidden on small screens (md:block reveals at >=768px).
        WHY `aside` + `aria-label`: matches the existing landmark on the
        legacy page.tsx so screen-reader users find the same nav region.
      */}
      <aside
        className="hidden md:flex h-full min-w-0 flex-col border-r border-border bg-background"
        aria-label="Chat thread list"
      >
        {threadRail}
      </aside>

      {/*
        Message column — always visible. min-w-0 + overflow-hidden so long
        unbreakable tokens (e.g. base64 fingerprints in a code block) wrap
        instead of expanding the column past the grid track.
      */}
      <main className="flex h-full min-w-0 flex-col overflow-hidden bg-background">
        {messageColumn}
      </main>

      {/*
        Context rail — only mounted on lg. We use a CSS-driven `hidden`
        helper (md:hidden + lg:flex) instead of removing the JSX so the
        keyboard chord still toggles the layout without re-mounting the
        rail's internal state. When collapsed at lg, the grid-template
        above drops the column entirely so the rail's width vanishes.
        We additionally hide the element with `hidden` so it does not
        steal tab focus while invisible.
      */}
      <aside
        className={cn(
          "hidden h-full min-w-0 flex-col border-l border-border bg-background",
          // Only show at lg AND when not collapsed. md never shows the rail.
          contextRailCollapsed ? "lg:hidden" : "lg:flex",
        )}
        aria-label="Chat context rail"
        data-collapsed={contextRailCollapsed ? "true" : "false"}
      >
        {contextRail}
      </aside>
    </div>
  );
}
