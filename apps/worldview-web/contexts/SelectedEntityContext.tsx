/**
 * contexts/SelectedEntityContext.tsx — Cross-panel entity selection sync
 * (PLAN-0074 Wave H T-H-02)
 *
 * WHY THIS EXISTS:
 * The intelligence page has three panels that need to stay in sync:
 *   1. Graph panel — user clicks a node to explore a relation
 *   2. Intelligence panel (Relations/Evidence/Paths tabs) — filters to the selected entity
 *   3. Sidebar — switches to show intelligence for the selected entity
 *
 * Without a shared context, each panel would need to pass state up to the page
 * and then back down through props (prop-drilling). With context, any panel can
 * call `setSelectedEntityId(id)` and every other panel re-renders with the new
 * selection automatically — no prop chains.
 *
 * TWO IDs — WHY:
 *   - `anchorEntityId`: The entity in the URL — `/intelligence/[entity_id]`. This
 *     is always the "home" entity. It never changes while on the page.
 *   - `selectedEntityId`: The entity the user last clicked in the graph or selected
 *     in a table row. Starts equal to anchor. Changes as the user explores.
 *
 * RESET ON ROUTE CHANGE — WHY:
 * If the user navigates from /intelligence/AAPL to /intelligence/TSLA, the route
 * param changes but the context persists (React keeps the subtree mounted if the
 * layout is the same). Without the useEffect reset, selectedEntityId would still
 * point to the last node the user clicked on AAPL, confusing the TSLA panels.
 *
 * WHO USES IT:
 * - IntelligenceLayout (provides the context)
 * - GraphPanel (calls setSelectedEntityId on node click)
 * - IntelligencePanel / tabs (reads selectedEntityId for filtering)
 * - EntitySidebar (switches to show selected entity intelligence)
 * - EntityChatPanel (reads anchorEntityId only — chat always stays on anchor)
 */

"use client";
// WHY "use client": createContext + useContext + useState require browser-side
// React. Context cannot live in Server Components.

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SelectedEntityContextType {
  /**
   * The entity the user last clicked in the graph (or the anchor if no
   * node has been clicked yet). Used to filter Relations/Evidence/Paths tabs
   * and to switch the sidebar to show a different entity's intelligence.
   */
  selectedEntityId: string;
  /** Update the selected entity — called by graph node click handler */
  setSelectedEntityId: (id: string) => void;
  /**
   * The entity from the URL param — the "home" entity for this page.
   * Never changes while on the same page. Panels that should always
   * refer to the anchor (e.g. the chat panel) read this, not selectedEntityId.
   */
  anchorEntityId: string;
}

// ── Context ───────────────────────────────────────────────────────────────────

// WHY null default: forces a clear error if a component tries to use the context
// without being wrapped in <SelectedEntityProvider>. Silent undefined would
// produce cryptic "cannot read property 'selectedEntityId' of undefined" later.
const SelectedEntityContext = createContext<SelectedEntityContextType | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────────

interface SelectedEntityProviderProps {
  /** The entity UUIDv7 from the URL param (route segment [entity_id]) */
  anchorEntityId: string;
  children: ReactNode;
}

export function SelectedEntityProvider({
  anchorEntityId,
  children,
}: SelectedEntityProviderProps) {
  // Default: selected = anchor (no graph node clicked yet)
  const [selectedEntityId, setSelectedEntityId] = useState(anchorEntityId);

  // Get the current pathname so we can detect navigation
  const pathname = usePathname();

  // WHY reset on pathname change:
  // When the user navigates to a different entity's intelligence page, the
  // IntelligenceLayout component stays mounted (same route group, same layout).
  // Without this reset, selectedEntityId would still be the last-clicked node
  // from the PREVIOUS entity's graph — confusing the new page's panels.
  // We depend on `pathname` (not `anchorEntityId`) so navigation-triggered
  // resets fire even if anchorEntityId has the same value for different paths.
  useEffect(() => {
    setSelectedEntityId(anchorEntityId);
  }, [pathname, anchorEntityId]);

  return (
    <SelectedEntityContext.Provider
      value={{ selectedEntityId, setSelectedEntityId, anchorEntityId }}
    >
      {children}
    </SelectedEntityContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useSelectedEntity — access the cross-panel entity selection state.
 *
 * WHY a named hook (not direct useContext):
 * Encapsulating the null check here means every call site gets a clear error
 * message ("useSelectedEntity must be inside SelectedEntityProvider") rather
 * than a cryptic "cannot read property" crash from destructuring null.
 */
export function useSelectedEntity(): SelectedEntityContextType {
  const ctx = useContext(SelectedEntityContext);
  if (!ctx) {
    throw new Error(
      "useSelectedEntity must be used inside <SelectedEntityProvider>. " +
        "Mount it in IntelligenceLayout, which wraps all three columns. " +
        "PLAN-0074 Wave H T-H-02.",
    );
  }
  return ctx;
}
