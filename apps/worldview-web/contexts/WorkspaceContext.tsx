/**
 * contexts/WorkspaceContext.tsx — Named workspace state management
 *
 * WHY THIS EXISTS: Traders need multiple named layout configurations (workspaces)
 * that persist between sessions. Day Trading, Research, and Portfolio Monitor
 * are fundamentally different information environments — this context lets users
 * switch between them without reconfiguring panels every time.
 *
 * WHY localStorage (not server state): Workspace layout preferences are purely
 * personal and session-local. They don't need server sync, tenant association,
 * or real-time collaboration. localStorage gives instant reads/writes with zero
 * network cost and survives page refreshes.
 *
 * WHO USES IT: app/(app)/layout.tsx (provider), WorkspaceTabs (switcher UI),
 *              workspace/page.tsx (reads activeWorkspace to render panel grid)
 * DATA SOURCE: localStorage only (no S9 calls)
 * DESIGN REFERENCE: PRD-0031 §5.2 Named workspaces, §5.5 Default presets
 */

"use client";
// WHY "use client": uses localStorage (browser-only), React state, and context.
// Server Components cannot access browser APIs or React context state.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

// ── Types ──────────────────────────────────────────────────────────────────────

/**
 * PanelType — 10 supported workspace panel content types.
 * WHY string union not enum: simpler to serialize/deserialize from localStorage JSON.
 * Each value maps to a dedicated widget component in the workspace grid.
 */
export type PanelType =
  | "chart"
  | "watchlist"
  | "screener"
  | "alerts"
  | "fundamentals"
  | "news"
  | "graph"
  | "portfolio"
  | "brief"
  | "chat";

/** A single panel within a workspace row */
export interface WorkspacePanel {
  /** Stable per-panel ID — React key + resize state key */
  id: string;
  type: PanelType;
}

/** A horizontal row of panels (split evenly by default) */
export interface WorkspaceRow {
  panels: WorkspacePanel[];
}

/** Full configuration for one named workspace */
export interface WorkspaceConfig {
  id: string;
  name: string;
  rows: WorkspaceRow[];
  /**
   * Persisted panel size ratios for react-resizable-panels.
   * WHY stored here (not separately): workspace config is the single source of
   * truth for everything a named workspace contains. Sizes and layout change
   * together — storing them together prevents stale-size bugs on workspace switch.
   *
   * Structure: rowSizes[rowIdx] = [size0, size1, ...] — proportional widths
   * for panels within that row. Outer array (not stored here) is row heights.
   */
  panelSizes?: number[][];
}

// ── Default presets (PRD §5.5) ────────────────────────────────────────────────

/**
 * DEFAULT_WORKSPACES — 4 preset configs every new user starts with.
 *
 * WHY 4 presets (not 1): covers the 4 primary institutional trader workflows:
 * - Day Trading → active intraday monitoring (chart + screener)
 * - Research → deep fundamental + news analysis before a trade
 * - Portfolio Monitor → risk/P&L overview + price context
 * - Morning Brief → Worldview's unique AI briefing workflow
 *
 * Designed so a Bloomberg PM opening the app for the first time sees a familiar
 * layout immediately, without any configuration required.
 */
const DEFAULT_WORKSPACES: WorkspaceConfig[] = [
  {
    id: "ws-day-trading",
    name: "Day Trading",
    rows: [
      { panels: [{ id: "dt-chart", type: "chart" }, { id: "dt-watchlist", type: "watchlist" }] },
      { panels: [{ id: "dt-screener", type: "screener" }, { id: "dt-alerts", type: "alerts" }] },
    ],
  },
  {
    id: "ws-research",
    name: "Research",
    rows: [
      { panels: [{ id: "rs-chart", type: "chart" }, { id: "rs-news", type: "news" }] },
      { panels: [{ id: "rs-fundamentals", type: "fundamentals" }, { id: "rs-graph", type: "graph" }] },
    ],
  },
  {
    id: "ws-portfolio-monitor",
    name: "Portfolio Monitor",
    rows: [
      { panels: [{ id: "pm-portfolio", type: "portfolio" }, { id: "pm-chart", type: "chart" }] },
      { panels: [{ id: "pm-watchlist", type: "watchlist" }, { id: "pm-news", type: "news" }] },
    ],
  },
  {
    id: "ws-morning-brief",
    name: "Morning Brief",
    rows: [
      { panels: [{ id: "mb-brief", type: "brief" }] },
      { panels: [{ id: "mb-screener", type: "screener" }, { id: "mb-alerts", type: "alerts" }] },
    ],
  },
];

const STORAGE_KEY = "worldview-workspaces";
const ACTIVE_KEY = "worldview-active-workspace";

// ── Context shape ─────────────────────────────────────────────────────────────

interface WorkspaceContextValue {
  workspaces: WorkspaceConfig[];
  activeWorkspaceId: string;
  /** Convenience: the full WorkspaceConfig for the currently active workspace */
  activeWorkspace: WorkspaceConfig | undefined;
  setActiveWorkspace: (id: string) => void;
  addWorkspace: () => void;
  removeWorkspace: (id: string) => void;
  renameWorkspace: (id: string, name: string) => void;
  /** Add a new panel of the given type to the active workspace (appended to last row or new row) */
  addPanelToWorkspace: (workspaceId: string, type: PanelType) => void;
  /** Remove a specific panel from the active workspace by panel ID */
  removePanelFromWorkspace: (workspaceId: string, panelId: string) => void;
  /** Persist the panel size ratios after a resize drag event */
  updatePanelSizes: (workspaceId: string, panelSizes: number[][]) => void;
}

// ── Context ───────────────────────────────────────────────────────────────────

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

// ── localStorage helpers ──────────────────────────────────────────────────────

/** Safe read from localStorage — returns DEFAULT_WORKSPACES if missing or corrupt */
function loadWorkspaces(): WorkspaceConfig[] {
  // WHY typeof window guard: this function runs in the lazy useState initializer
  // which can be called during SSR pre-rendering (no window available)
  if (typeof window === "undefined") return DEFAULT_WORKSPACES;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_WORKSPACES;
    const parsed = JSON.parse(raw) as WorkspaceConfig[];
    // WHY length guard: if user somehow saved an empty array, recover gracefully
    return Array.isArray(parsed) && parsed.length > 0 ? parsed : DEFAULT_WORKSPACES;
  } catch {
    // WHY catch: JSON.parse throws on corrupt localStorage data
    return DEFAULT_WORKSPACES;
  }
}

/** Safe read of the last-active workspace ID from localStorage */
function loadActiveId(workspaces: WorkspaceConfig[]): string {
  if (typeof window === "undefined") return workspaces[0]?.id ?? "";
  const stored = localStorage.getItem(ACTIVE_KEY);
  // WHY validate: stored ID may be stale if user deleted that workspace
  const valid = workspaces.find((w) => w.id === stored);
  return valid?.id ?? workspaces[0]?.id ?? "";
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  // WHY lazy initializers: avoids reading localStorage on every render.
  // Each initializer runs once at mount, returning the persisted state
  // or defaults if nothing is stored.
  const [workspaces, setWorkspaces] = useState<WorkspaceConfig[]>(loadWorkspaces);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string>(() =>
    loadActiveId(loadWorkspaces()),
  );

  // Persist workspaces whenever they change
  useEffect(() => {
    // WHY window guard in effect: effects run on client only in Next.js App Router,
    // but the guard makes this explicitly clear and safe for future SSR changes.
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(workspaces));
    }
  }, [workspaces]);

  // Persist active workspace ID whenever it changes
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem(ACTIVE_KEY, activeWorkspaceId);
    }
  }, [activeWorkspaceId]);

  const setActiveWorkspace = useCallback((id: string) => {
    setActiveWorkspaceId(id);
  }, []);

  const addWorkspace = useCallback(() => {
    // WHY Date.now() suffix: guarantees uniqueness without a UUID library
    const ts = Date.now();
    const newWs: WorkspaceConfig = {
      id: `ws-custom-${ts}`,
      name: `Workspace ${String(ts).slice(-4)}`,
      rows: [
        {
          panels: [
            { id: `p-${ts}-0`, type: "chart" },
            { id: `p-${ts}-1`, type: "screener" },
          ],
        },
      ],
    };
    setWorkspaces((prev) => [...prev, newWs]);
    // WHY switch to new workspace: user intent is to edit the new one immediately
    setActiveWorkspaceId(newWs.id);
  }, []);

  const removeWorkspace = useCallback(
    (id: string) => {
      setWorkspaces((prev) => {
        const next = prev.filter((w) => w.id !== id);
        // WHY fallback to defaults: UI cannot function with 0 workspaces —
        // the tab strip would be empty and there would be no active workspace
        return next.length > 0 ? next : DEFAULT_WORKSPACES;
      });
      // If we removed the active workspace, switch to the first available
      setActiveWorkspaceId((prev) => {
        if (prev !== id) return prev;
        const remaining = workspaces.filter((w) => w.id !== id);
        return remaining[0]?.id ?? DEFAULT_WORKSPACES[0].id;
      });
    },
    [workspaces],
  );

  const renameWorkspace = useCallback((id: string, name: string) => {
    setWorkspaces((prev) =>
      prev.map((w) =>
        // WHY trim + fallback to w.name: prevent empty-string workspace names
        w.id === id ? { ...w, name: name.trim() || w.name } : w,
      ),
    );
  }, []);

  const addPanelToWorkspace = useCallback((workspaceId: string, type: PanelType) => {
    setWorkspaces((prev) =>
      prev.map((w) => {
        if (w.id !== workspaceId) return w;
        // WHY try last row first: users expect new panels to appear near the bottom.
        // If the last row has only 1 panel, add a second panel in that row (side by side).
        // If the last row already has 2 panels, start a new row below.
        const lastRow = w.rows[w.rows.length - 1];
        const newPanel: WorkspacePanel = {
          id: `p-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          type,
        };
        if (lastRow && lastRow.panels.length < 2) {
          // Add to existing last row
          const updatedRows = [...w.rows];
          updatedRows[updatedRows.length - 1] = {
            panels: [...lastRow.panels, newPanel],
          };
          return { ...w, rows: updatedRows };
        }
        // Start a new row
        return { ...w, rows: [...w.rows, { panels: [newPanel] }] };
      }),
    );
  }, []);

  const removePanelFromWorkspace = useCallback((workspaceId: string, panelId: string) => {
    setWorkspaces((prev) =>
      prev.map((w) => {
        if (w.id !== workspaceId) return w;
        // WHY filter then clean: remove the specific panel, then remove any rows
        // that end up empty (a row with 0 panels is an invalid workspace state).
        const updatedRows = w.rows
          .map((row) => ({ panels: row.panels.filter((p) => p.id !== panelId) }))
          .filter((row) => row.panels.length > 0);
        // WHY fallback to a single chart: if all panels are removed, restore a minimal
        // default so the workspace is never completely blank.
        const safeRows =
          updatedRows.length > 0
            ? updatedRows
            : [{ panels: [{ id: `p-default-${Date.now()}`, type: "chart" as PanelType }] }];
        return { ...w, rows: safeRows };
      }),
    );
  }, []);

  const updatePanelSizes = useCallback((workspaceId: string, panelSizes: number[][]) => {
    setWorkspaces((prev) =>
      prev.map((w) =>
        // WHY shallow merge (not deep): panelSizes is a plain number[][] that fully
        // replaces the previous value — no need to merge individual cells.
        w.id === workspaceId ? { ...w, panelSizes } : w,
      ),
    );
  }, []);

  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId);

  return (
    <WorkspaceContext.Provider
      value={{
        workspaces,
        activeWorkspaceId,
        activeWorkspace,
        setActiveWorkspace,
        addWorkspace,
        removeWorkspace,
        renameWorkspace,
        addPanelToWorkspace,
        removePanelFromWorkspace,
        updatePanelSizes,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useWorkspace — access workspace state from any client component.
 * WHY throw on missing provider: fails fast with a clear message instead of
 * silently returning undefined and causing a cryptic downstream error.
 */
export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  }
  return ctx;
}
