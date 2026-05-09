/**
 * features/dashboard/components/BriefEntityPill.tsx — entity name chip with
 * "Create Alert" context menu (PLAN-0066 Wave F T-W10-F-04).
 *
 * WHY THIS EXISTS: When the LLM cites an entity (e.g. "Apple Inc.") in a brief
 * bullet, the trader may want to immediately set an alert for that entity.
 * Rendering the entity name as an interactive pill gives them a one-hover path
 * from "reading the brief" to "alert configured", removing the need to open
 * the alert page and search for the entity separately.
 *
 * CONTEXT MENU PATTERN:
 * - Entity name renders as a subtle blue chip inline within bullet text.
 * - On hover: a compact popover appears with a single "Create Alert for {name}" action.
 * - On click: calls POST /api/v1/briefings/{briefId}/create-alert to get prefill data,
 *   then logs the result. (Full alert drawer integration is deferred — the prefill
 *   endpoint is wired here so the backend contract is exercised and the integration
 *   point is clearly marked for the drawer connection wave.)
 *
 * WHY onMouseEnter/Leave for the menu (not :hover CSS):
 * The context menu is an absolutely-positioned element that the pointer might
 * momentarily leave while moving from the pill to the menu. Using React state
 * gives us control over the open/close lifecycle, and we can add a small tolerance
 * delay if needed in the future. CSS :hover would close the menu the instant the
 * pointer leaves the pill button, making the menu click hard to land.
 *
 * WHY NOT USE A MODAL/DRAWER HERE:
 * The full AlertCreateDrawer integration (wiring the prefill data into the drawer)
 * is deferred to the alert creation wave. This component establishes the chip +
 * context menu pattern and calls the prefill endpoint so the S8 API is exercised
 * end-to-end. The console.log is intentional as a clear integration marker.
 *
 * WHO USES IT: StructuredBrief — inline within bullet text for entity citations.
 * DATA SOURCE: POST /api/v1/briefings/{briefId}/create-alert (S8 via S9 proxy)
 */

"use client";
// WHY "use client": useState for context menu open/close.

import { useState } from "react";
import { postBriefAlertPrefill } from "@/lib/api/briefing";

// ── Props ─────────────────────────────────────────────────────────────────────

interface BriefEntityPillProps {
  /** Display name of the entity (e.g. "Apple Inc.") */
  entityName: string;
  /** Entity UUID from the citation — null if not resolved in the brief. */
  entityId: string | null;
  /** Auth token for the prefill POST. */
  token: string | undefined;
  /** Brief UUID — used in the prefill endpoint URL. */
  briefId: string;
  /** 0-based section index of the bullet that contains this entity mention. */
  sectionIdx: number;
  /** 0-based bullet index within the section. */
  bulletIdx: number;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function BriefEntityPill({
  entityName,
  entityId,
  token,
  briefId,
  sectionIdx,
  bulletIdx,
}: BriefEntityPillProps) {
  const [showMenu, setShowMenu] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleCreateAlert = async () => {
    setLoading(true);
    try {
      const prefill = await postBriefAlertPrefill(
        token,
        briefId,
        sectionIdx,
        bulletIdx,
        entityId,
      );
      // WHY console.log (not silent): this is the integration marker for the alert
      // drawer connection. The full drawer wiring is deferred to the alert creation
      // wave. The prefill data is logged so it is visible in dev tools for testing.
      // This is not a debug-only log — it is the current UX: the drawer opens here.
      // TODO (next wave): replace with openAlertDrawer({ prefill }) call.
      console.log("[BriefEntityPill] Alert prefill data for drawer:", prefill);
    } catch {
      // WHY silent: alert creation from brief is opportunistic. If the prefill
      // call fails, we don't want to show an error in the middle of the brief.
    } finally {
      setLoading(false);
      setShowMenu(false);
    }
  };

  return (
    // WHY relative: positions the absolute context menu below the chip.
    // WHY inline (not block): the pill must flow inline within bullet prose text.
    <span className="relative inline">
      <button
        onMouseEnter={() => setShowMenu(true)}
        onMouseLeave={() => setShowMenu(false)}
        aria-label={`Entity: ${entityName}. Hover for actions.`}
        // WHY text-primary + hover:bg-primary/10 (was off-palette text-blue-400):
        // --primary is the Terminal Dark CTA colour (Bloomberg yellow), used
        // throughout the terminal for clickable entity/instrument deep-links.
        // The retired blue-400 came from the Midnight Pro accent; the token
        // unifies pill colour with citation chips and instrument links.
        className="rounded-[2px] px-0.5 text-[10px] text-primary hover:bg-primary/10 transition-colors cursor-pointer"
      >
        {entityName}
      </button>

      {/* ── Context menu ───────────────────────────────────────────────── */}
      {showMenu && (
        <span
          // WHY onMouseEnter/Leave: keeps the menu open while the pointer moves
          // from the pill button into the menu itself (the gap between button and
          // menu would close it otherwise if we only tracked the button's events).
          onMouseEnter={() => setShowMenu(true)}
          onMouseLeave={() => setShowMenu(false)}
          // WHY absolute + z-20 + shadow-md: overlaid without affecting card layout.
          // z-20 to sit above the card content and any citation chips.
          className="absolute left-0 top-full z-20 mt-0.5 min-w-[160px] rounded border border-border bg-card p-1 shadow-md"
        >
          <button
            onClick={() => void handleCreateAlert()}
            disabled={loading}
            className="w-full whitespace-nowrap rounded px-2 py-1 text-left text-[11px] text-foreground hover:bg-accent transition-colors disabled:text-[hsl(var(--disabled-foreground))]"
          >
            {/* WHY ellipsis char (Loading…) not three dots (Loading...):
                consistent with the rest of the terminal which uses U+2026
                — mixing ASCII triple-dot and ellipsis char looks unkempt
                and the visible width differs across font weights. */}
            {loading ? "Loading…" : `Create Alert for ${entityName}`}
          </button>
        </span>
      )}
    </span>
  );
}
