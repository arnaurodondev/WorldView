/**
 * contexts/WorkspaceContext.tsx — Named workspace state management
 *
 * WHY THIS EXISTS: Traders need multiple named layout configurations (workspaces)
 * that persist between sessions. Day Trading, Research, and Portfolio Monitor are
 * fundamentally different information environments — this context lets users switch
 * between them without reconfiguring panels every time.
 *
 * WHY localStorage (not server state): Workspace layout preferences are purely
 * personal and session-local. They don't need server sync, tenant association, or
 * real-time collaboration. localStorage gives instant reads/writes with zero network
 * cost and survives page refreshes.
 *
 * WHY V2 STORAGE KEY (PLAN-0051 T-C-3-01): Earlier builds wrote to
 * `worldview-workspaces` (v1) without explicit versioning. The Wave C activation
 * adds a debounced layout-resize writer + an explicit migration path; bumping to
 * `worldview:workspaces:v2` lets us read v1 once, translate, and from then on write
 * v2 only. If we ever change the WorkspaceConfig shape again, v3 follows the same
 * pattern.
 *
 * WHY DEBOUNCED LAYOUT WRITES: react-resizable-panels fires onLayoutChanged on
 * pointer release — already debounced relative to onLayoutChange — but a user can
 * still drop the handle, immediately drag again, etc. Wrapping persistence in a
 * 300ms debounce coalesces bursty edits into one localStorage write so we never
 * thrash the disk with intermediate states.
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
  useRef,
  useState,
  type ReactNode,
} from "react";

// ── Types ──────────────────────────────────────────────────────────────────────

/**
 * PanelType — supported workspace panel content types.
 *
 * WHY string union (not enum): simpler to JSON-serialise to localStorage.
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

/**
 * SUPPORTED_PANEL_TYPES — runtime mirror of the PanelType union.
 *
 * QA-iter1 MIN-2 introduced this set so ``migrateV1`` can drop panels whose
 * type was removed from the catalogue — without it, legacy v1 configs with
 * a stale type rendered as empty placeholders (``default:`` branch in
 * WorkspacePanelContainer).
 *
 * QA-iter2 N-NIT-1: the set is now derived from ``Record<PanelType, true>``
 * so adding a new ``PanelType`` member without listing it here becomes a
 * TypeScript error at compile time (the record is exhaustive on the union).
 * The previous hand-maintained list was a silent-drift hazard.
 */
const PANEL_TYPE_REGISTRY: Record<PanelType, true> = {
  chart: true,
  watchlist: true,
  screener: true,
  alerts: true,
  fundamentals: true,
  news: true,
  graph: true,
  portfolio: true,
  brief: true,
  chat: true,
};
const SUPPORTED_PANEL_TYPES: ReadonlySet<PanelType> = new Set(
  Object.keys(PANEL_TYPE_REGISTRY) as PanelType[],
);

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
   *
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
 * DEFAULT_WORKSPACES — preset configs every new user starts with.
 *
 * WHY 4 presets: covers the 4 primary institutional trader workflows:
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

// ── Storage keys ──────────────────────────────────────────────────────────────

/** Current versioned key. Bumped from v1 to mark a known-good shape going forward. */
const STORAGE_KEY = "worldview:workspaces:v2";
/** Legacy key — read once at boot, then discarded after migration. */
const LEGACY_STORAGE_KEY = "worldview-workspaces";
/** Active-workspace selector key (no shape change between v1 and v2 — keep stable). */
const ACTIVE_KEY = "worldview-active-workspace";

/**
 * DEBOUNCE_MS — how long to wait after the most recent state change before writing
 * to localStorage. 300ms is the standard institutional-UI debounce: short enough
 * to feel instant for the next reload, long enough to coalesce a flurry of edits
 * (rapid resizes, panel adds + immediate moves) into a single write.
 */
const DEBOUNCE_MS = 300;

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
  /** Add a new panel of the given type to the active workspace */
  addPanelToWorkspace: (workspaceId: string, type: PanelType) => void;
  /** Remove a specific panel from the active workspace by panel ID */
  removePanelFromWorkspace: (workspaceId: string, panelId: string) => void;
  /** Persist the panel size ratios after a resize drag event */
  updatePanelSizes: (workspaceId: string, panelSizes: number[][]) => void;
  /**
   * Update the layout for one panel after a resize/move. Wired to
   * onLayoutChanged from WorkspaceGrid's PanelGroup. Currently this delegates
   * to updatePanelSizes since rows are positioned by index — kept as an explicit
   * entry point so future drag-to-reorder code has an obvious hook to attach to.
   */
  updateWorkspaceLayout: (workspaceId: string, panelSizes: number[][]) => void;
}

// ── Context ───────────────────────────────────────────────────────────────────

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

// ── localStorage helpers ──────────────────────────────────────────────────────

/**
 * migrateV1 — translate the legacy v1 shape (key `worldview-workspaces`, plain
 * WorkspaceConfig[]) to the v2 shape.
 *
 * WHY a dedicated migrator (not "just read both keys"): even though the shape is
 * presently identical, having an explicit migrator means future v2→v3 work edits
 * one function. It also gives us a single place to log/observe migration if we
 * ever need to debug user reports of "I had 8 workspaces and now I have 4".
 *
 * @returns parsed v2-shaped config array, or null when the legacy key is absent
 *          or unreadable.
 */
function migrateV1(): WorkspaceConfig[] | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    // QA-iter1 MIN-2: prune panels whose type was removed from the catalogue.
    // Without this, legacy v1 configs with a stale panel type render as an
    // empty cell (``default:`` branch in WorkspacePanelContainer). We log a
    // single warning to console so users diagnosing "where did my panel go"
    // have a breadcrumb.
    let droppedCount = 0;
    const cleaned = (parsed as WorkspaceConfig[]).map((ws) => ({
      ...ws,
      rows: ws.rows.map((row) => ({
        ...row,
        panels: row.panels.filter((p) => {
          if (SUPPORTED_PANEL_TYPES.has(p.type)) return true;
          droppedCount += 1;
          return false;
        }),
      })),
    }));
    if (droppedCount > 0 && typeof console !== "undefined") {
      // eslint-disable-next-line no-console
      console.warn(
        `[workspace.migrateV1] dropped ${droppedCount} panel(s) with unsupported types`,
      );
    }
    return cleaned;
  } catch {
    return null;
  }
}

/**
 * Safe read from localStorage — returns DEFAULT_WORKSPACES if missing or corrupt.
 *
 * Migration path:
 *   1. If v2 key exists → use v2 directly.
 *   2. Else if legacy v1 key exists → migrate, write v2, return migrated array.
 *   3. Else → DEFAULT_WORKSPACES.
 *
 * WHY do the v2 write inline during migration: leaves the user's storage in a
 * clean v2-only state on the very next read; eliminates running both code paths
 * forever. The legacy key is intentionally left in place so that if v2 is later
 * cleared (e.g. by a debug tool), we still have a recovery path.
 */
function loadWorkspaces(): WorkspaceConfig[] {
  // WHY typeof window guard: this function runs in the lazy useState initialiser
  // which can be called during SSR pre-rendering (no window available)
  if (typeof window === "undefined") return DEFAULT_WORKSPACES;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as WorkspaceConfig[];
      // WHY length guard: if user somehow saved an empty array, recover gracefully
      return Array.isArray(parsed) && parsed.length > 0 ? parsed : DEFAULT_WORKSPACES;
    }

    // No v2 — try v1 migration.
    const migrated = migrateV1();
    if (migrated && migrated.length > 0) {
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated));
      } catch {
        // WHY swallow: writing the migrated copy is best-effort. If localStorage is
        // full or disabled, we still return the migrated value in memory.
      }
      return migrated;
    }
    return DEFAULT_WORKSPACES;
  } catch {
    // WHY catch: JSON.parse throws on corrupt localStorage data
    return DEFAULT_WORKSPACES;
  }
}

/** Safe read of the last-active workspace ID from localStorage */
function loadActiveId(workspaces: WorkspaceConfig[]): string {
  if (typeof window === "undefined") return workspaces[0]?.id ?? "";
  const stored = window.localStorage.getItem(ACTIVE_KEY);
  // WHY validate: stored ID may be stale if user deleted that workspace
  const valid = workspaces.find((w) => w.id === stored);
  return valid?.id ?? workspaces[0]?.id ?? "";
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  // WHY lazy initialisers: avoid reading localStorage on every render.
  // Each initialiser runs once at mount, returning the persisted state
  // or defaults if nothing is stored.
  const [workspaces, setWorkspaces] = useState<WorkspaceConfig[]>(loadWorkspaces);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string>(() =>
    loadActiveId(loadWorkspaces()),
  );

  // ── Debounced persistence of `workspaces` ─────────────────────────────────
  /**
   * WHY ref'd timer: useEffect with a setTimeout is the standard React debounce
   * pattern. Storing the timer in a ref (not state) means clearing/replacing it
   * does not trigger a re-render. The cleanup function clears any pending write
   * when the component unmounts or the effect re-runs.
   */
  const writeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (writeTimerRef.current) clearTimeout(writeTimerRef.current);
    writeTimerRef.current = setTimeout(() => {
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(workspaces));
      } catch {
        // WHY swallow: QuotaExceededError or storage-disabled mode shouldn't crash
        // the workspace UI. Worst case, the user's edits don't survive a reload.
      }
      writeTimerRef.current = null;
    }, DEBOUNCE_MS);
    return () => {
      if (writeTimerRef.current) clearTimeout(writeTimerRef.current);
    };
  }, [workspaces]);

  // Persist active workspace ID whenever it changes (no debounce — single-key write)
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(ACTIVE_KEY, activeWorkspaceId);
    } catch {
      // see above — best-effort write
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

  /**
   * updateWorkspaceLayout — public hook the grid invokes after a layout change.
   *
   * WHY a separate name from updatePanelSizes: WorkspaceGrid uses this to capture
   * future layout-related state (panel reorders, drag-to-other-row) without churn
   * to the persistence path. Today it's a thin alias; tomorrow it's the entry
   * point for richer layout semantics.
   */
  const updateWorkspaceLayout = useCallback(
    (workspaceId: string, panelSizes: number[][]) => {
      updatePanelSizes(workspaceId, panelSizes);
    },
    [updatePanelSizes],
  );

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
        updateWorkspaceLayout,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useWorkspace — access workspace state from any client component.
 *
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
