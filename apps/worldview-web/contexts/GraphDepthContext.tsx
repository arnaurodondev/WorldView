/**
 * contexts/GraphDepthContext.tsx — Shared graph depth state between GraphPanel and EntitySidebar
 * (W4-INTELLIGENCE FR-3.3)
 *
 * WHY THIS EXISTS:
 * GraphPanel has a user-controlled depth slider (1–5). EntitySidebar fetches the
 * graph data for the selected entity using the same query key, but previously
 * hardcoded depth=2. When the analyst moves the slider to depth=3, the sidebar
 * should reflect the same depth so its relations list matches the graph.
 *
 * Without this context, EntitySidebar's queryKey ["intelligence-graph", id, 2, ...]
 * would never hit the cache primed by GraphPanel at depth=3 — causing an extra
 * network fetch and showing different data than the graph.
 *
 * DESIGN DECISION — why context (not prop drilling):
 * GraphPanel and EntitySidebar are siblings inside IntelligenceLayout. Lifting
 * depth state up to IntelligenceLayout and threading it down as props would
 * require changes to the layout's prop surface and to GraphPanel's external interface.
 * A context is simpler: GraphPanel writes to it, EntitySidebar reads from it,
 * neither needs to know about the layout's internal structure.
 *
 * WHY default=2:
 * GraphPanel initialises its slider at depth=2. The default context value must
 * match so consumers (EntitySidebar) get the correct depth even before GraphPanel
 * mounts and sets the value.
 *
 * WHO PROVIDES IT: IntelligenceLayout (wraps GraphPanel + EntitySidebar)
 * WHO READS IT: EntitySidebar (graph query key), GraphPanel (writes depth on slider change)
 */

"use client";
// WHY "use client": createContext + useContext require browser-side React.

import {
  createContext,
  useContext,
  useState,
  type ReactNode,
  type Dispatch,
  type SetStateAction,
} from "react";

// ── Context type ──────────────────────────────────────────────────────────────

interface GraphDepthContextType {
  /** The graph depth currently selected by the analyst (1–5). Default: 2. */
  depth: number;
  /** Update the graph depth — called by GraphPanel's slider onChange handler. */
  setDepth: Dispatch<SetStateAction<number>>;
}

// ── Context ───────────────────────────────────────────────────────────────────

// WHY null default: forces a clear error if a component reads depth outside
// the provider. Silent undefined would produce cryptic NaN in query keys.
const GraphDepthContext = createContext<GraphDepthContextType | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────────

interface GraphDepthProviderProps {
  children: ReactNode;
}

export function GraphDepthProvider({ children }: GraphDepthProviderProps) {
  // WHY default=2: matches GraphPanel's initial slider value.
  // Consumers get the correct depth even if GraphPanel hasn't rendered yet.
  const [depth, setDepth] = useState(2);

  return (
    <GraphDepthContext.Provider value={{ depth, setDepth }}>
      {children}
    </GraphDepthContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useGraphDepth — access the shared graph depth state.
 *
 * WHY a named hook (not direct useContext):
 * Encapsulating the null check here means every call site gets a clear error
 * ("useGraphDepth must be inside GraphDepthProvider") rather than a cryptic
 * "cannot read property 'depth' of null" crash.
 */
export function useGraphDepth(): GraphDepthContextType {
  const ctx = useContext(GraphDepthContext);
  if (!ctx) {
    throw new Error(
      "useGraphDepth must be used inside <GraphDepthProvider>. " +
        "Mount it in IntelligenceLayout, which wraps GraphPanel and EntitySidebar.",
    );
  }
  return ctx;
}
