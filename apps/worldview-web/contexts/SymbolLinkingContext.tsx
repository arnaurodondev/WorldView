/**
 * contexts/SymbolLinkingContext.tsx — Per-panel symbol linking by color group
 *
 * WHY THIS EXISTS: Institutional traders need multiple panels watching the same symbol
 * simultaneously — e.g., a chart, fundamentals panel, and news feed all locked to AAPL.
 * Symbol linking (inspired by Bloomberg's color-coded group links) solves this: panels
 * in the same color group automatically update when any panel in that group changes
 * symbol. Setting AAPL on a "blue" chart broadcasts AAPL to every "blue" panel.
 *
 * WHY SCOPED PER WORKSPACE PAGE (not layout.tsx): Each workspace has independent symbol
 * linking state. The provider lives inside workspace/page.tsx so switching workspaces
 * resets active symbols without polluting the global shell state.
 *
 * WHY PERSIST COLORS BUT NOT ACTIVE SYMBOLS: A user expects their panel groupings
 * (which panels share which color) to survive a reload — that is configuration. The
 * actively-displayed ticker is data, and a fresh-page-load is a fresh research session;
 * forcing the user to re-trigger symbol changes after reload is acceptable and avoids
 * stale "AAPL" sitting in a panel from yesterday's research session.
 *
 * HOW IT WORKS:
 *   1. User picks a color (red/green/blue/yellow/purple/none) on a panel via the dot
 *      button in the panel header (SymbolLinkColorPicker).
 *   2. setLinkColor(panelId, color) records the choice; persisted to localStorage.
 *   3. When any panel calls setActiveSymbol(panelId, "AAPL", "ins-aapl"), the context
 *      looks up that panel's color and broadcasts the symbol to every other panel
 *      sharing that color (so all "blue" panels now see AAPL).
 *   4. Panels read their current symbol via getSymbolForPanel(panelId), which is wired
 *      through the convenience hook useSymbolLink(panelId).
 *
 * WHY null-color (LinkColor === "none"): Panels not in any group render their own
 * symbol independently — broadcast does NOT touch them. This is the explicit way to
 * opt out of synchronisation while still showing the dot button.
 *
 * WHO USES IT:
 *   - WorkspacePanelContainer renders the SymbolLinkColorPicker that calls setLinkColor.
 *   - Symbol-aware widgets (chart, fundamentals, graph) call useSymbolLink(panelId)
 *     to read the current linked ticker — when isLinked === true they prefer the
 *     linked symbol over their prop-driven default.
 * DATA SOURCE: Internal state + localStorage (link colors only); no S9 calls.
 * DESIGN REFERENCE: PRD-0031 §5.3 Symbol linking; DESIGN_SYSTEM.md §6.13 Symbol
 *                   Linking dot pattern.
 */

"use client";
// WHY "use client": uses React state, useEffect (localStorage hydration), and context.
// Server components cannot access localStorage or React context.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// ── Types ──────────────────────────────────────────────────────────────────────

/**
 * LinkColor — the 5 panel link colors plus "none" (unlinked).
 * WHY string union (not enum): JSON-serialisable for localStorage persistence.
 * WHY 5 colors: matches Bloomberg Terminal's 5 group link colors — a standard
 * institutional traders recognise. "none" = panel does not participate in any group.
 */
export type LinkColor = "none" | "red" | "green" | "blue" | "purple" | "yellow";

/**
 * Per-panel link record. Stored by panelId.
 *
 * WHY active values are nullable: a panel can have a color (config) but no symbol
 * yet (the user has not picked a ticker since loading the page).
 */
export interface SymbolLink {
  /** Stable workspace panel ID (e.g. "p-1714000000-abcd") */
  panelId: string;
  /** User-picked group color (or "none" for unlinked) */
  color: LinkColor;
  /** Active ticker (e.g. "AAPL") — broadcast across the color group at runtime */
  activeSymbol: string | null;
  /** Active instrument ID (e.g. "ins-aapl") — used by widgets that fetch by id */
  activeInstrumentId: string | null;
}

/**
 * GROUP_COLOR_HEX — CSS hex values for the small color dot buttons.
 *
 * WHY explicit hex (not Tailwind arbitrary values): Tailwind's class-based purging
 * would strip dynamic `bg-[#EF5350]` values generated at runtime. Inline styles
 * with these hex values are always applied correctly regardless of build.
 *
 * WHY align with semantic tokens (red=#EF5350, green=#26A69A, yellow=#FFD60A):
 * the trader's eye reads these colors with the same semantics already established
 * in the rest of the UI (positive/negative/primary). Reusing them removes friction.
 */
export const GROUP_COLOR_HEX: Record<Exclude<LinkColor, "none">, string> = {
  red: "#EF5350", // matches --negative
  green: "#26A69A", // matches --positive
  blue: "#3B82F6", // standard blue (distinct from primary yellow)
  yellow: "#FFD60A", // matches --primary
  purple: "#A855F7", // violet accent
};

/** Ordered list used by the color picker UI (popovers iterate this) */
export const LINK_COLOR_ORDER: LinkColor[] = [
  "none",
  "red",
  "green",
  "blue",
  "yellow",
  "purple",
];

// ── localStorage keys ─────────────────────────────────────────────────────────

/**
 * STORAGE_KEY_COLORS — persists the panelId→color map.
 *
 * WHY versioned (v1): a future migration may need to bump the schema (e.g. to add
 * per-panel default symbols). Versioning the key lets us detect old shapes and
 * either migrate or discard them without crashing on parse errors.
 */
const STORAGE_KEY_COLORS = "worldview:symbolLinks:v1";

// ── Context shape ─────────────────────────────────────────────────────────────

interface SymbolLinkingContextValue {
  /** All current per-panel link records, keyed by panelId */
  links: Record<string, SymbolLink>;
  /** Update a panel's color group (also persists to localStorage) */
  setLinkColor: (panelId: string, color: LinkColor) => void;
  /**
   * Set the active symbol on a panel. If the panel has a color !== "none",
   * the symbol is broadcast to every other panel sharing that color.
   */
  setActiveSymbol: (panelId: string, symbol: string, instrumentId: string) => void;
  /** Convenience getter — returns the current symbol/instrumentId for a panel */
  getSymbolForPanel: (panelId: string) => {
    symbol: string | null;
    instrumentId: string | null;
  };
}

// ── Context ───────────────────────────────────────────────────────────────────

const SymbolLinkingContext = createContext<SymbolLinkingContextValue | null>(null);

// ── localStorage helpers ──────────────────────────────────────────────────────

/**
 * Load only the COLOR portion of the link map from localStorage. Active symbols
 * are never persisted (see file-level WHY).
 *
 * WHY try/catch: localStorage.getItem can throw in private-mode browsers; JSON.parse
 * throws on corrupt data. Defensive parsing returns {} so the app keeps booting
 * even if the user's storage is wedged.
 */
function loadColorMap(): Record<string, LinkColor> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY_COLORS);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    // WHY filter to known LinkColor values: localStorage may contain stale shapes
    // from older builds — silently drop unknown entries instead of crashing the app.
    const result: Record<string, LinkColor> = {};
    for (const [panelId, color] of Object.entries(parsed)) {
      if (
        typeof color === "string" &&
        (LINK_COLOR_ORDER as string[]).includes(color)
      ) {
        result[panelId] = color as LinkColor;
      }
    }
    return result;
  } catch {
    return {};
  }
}

/** Save the color map to localStorage. Wrapped in try/catch for QuotaExceeded edge cases. */
function persistColorMap(map: Record<string, LinkColor>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY_COLORS, JSON.stringify(map));
  } catch {
    // WHY swallow: QuotaExceededError or storage-disabled mode shouldn't crash
    // the workspace; the worst case is the user's color picks don't survive reload.
  }
}

// ── Provider ──────────────────────────────────────────────────────────────────

/**
 * SymbolLinkingProvider — manages per-panel link state for one workspace.
 *
 * WHY `links` is a flat Record<string, SymbolLink> (not Map): records are easier
 * to spread/clone for React state immutability and serialise cleanly to JSON.
 */
export function SymbolLinkingProvider({ children }: { children: ReactNode }) {
  // WHY initial state empty: hydration happens in a useEffect to avoid SSR mismatch.
  // If we read localStorage in the lazy initialiser, the first server render would
  // have {} and the first client render would have populated colors → React warns.
  const [links, setLinks] = useState<Record<string, SymbolLink>>({});

  // ── Hydrate color picks from localStorage on mount (client-only) ────────────
  // WHY a useEffect (not lazy initialiser): runs after first render so SSR HTML
  // and client HTML match. The first render is empty links; immediately after,
  // we hydrate colors.
  useEffect(() => {
    const colorMap = loadColorMap();
    if (Object.keys(colorMap).length === 0) return;
    setLinks((prev) => {
      const next = { ...prev };
      for (const [panelId, color] of Object.entries(colorMap)) {
        next[panelId] = {
          panelId,
          color,
          activeSymbol: null,
          activeInstrumentId: null,
        };
      }
      return next;
    });
  }, []);

  // ── setLinkColor — updates color and persists ───────────────────────────────
  const setLinkColor = useCallback((panelId: string, color: LinkColor) => {
    setLinks((prev) => {
      const existing = prev[panelId];
      const next: Record<string, SymbolLink> = {
        ...prev,
        [panelId]: {
          panelId,
          color,
          // WHY preserve active values: changing color shouldn't clear the symbol
          // currently displayed. The user may have a chart on AAPL and just want
          // to add it to the blue group — they don't want AAPL to disappear.
          activeSymbol: existing?.activeSymbol ?? null,
          activeInstrumentId: existing?.activeInstrumentId ?? null,
        },
      };
      // Persist only the color portion. Build the map fresh from the new state.
      const colorMap: Record<string, LinkColor> = {};
      for (const link of Object.values(next)) {
        colorMap[link.panelId] = link.color;
      }
      persistColorMap(colorMap);
      return next;
    });
  }, []);

  // ── setActiveSymbol — broadcast across same-color panels ────────────────────
  const setActiveSymbol = useCallback(
    (panelId: string, symbol: string, instrumentId: string) => {
      setLinks((prev) => {
        const source = prev[panelId];
        const sourceColor = source?.color ?? "none";
        const next: Record<string, SymbolLink> = { ...prev };

        // Always update the source panel itself so its state is consistent.
        next[panelId] = {
          panelId,
          color: sourceColor,
          activeSymbol: symbol,
          activeInstrumentId: instrumentId,
        };

        // WHY broadcast only when color !== "none": "none" means the panel is
        // intentionally not in any group — symbol changes stay local to that panel.
        if (sourceColor !== "none") {
          for (const link of Object.values(prev)) {
            if (link.panelId === panelId) continue;
            if (link.color === sourceColor) {
              next[link.panelId] = {
                ...link,
                activeSymbol: symbol,
                activeInstrumentId: instrumentId,
              };
            }
          }
        }
        return next;
      });
    },
    [],
  );

  // ── getSymbolForPanel — convenience getter ──────────────────────────────────
  const getSymbolForPanel = useCallback(
    (panelId: string): { symbol: string | null; instrumentId: string | null } => {
      const link = links[panelId];
      if (!link) return { symbol: null, instrumentId: null };
      return {
        symbol: link.activeSymbol,
        instrumentId: link.activeInstrumentId,
      };
    },
    [links],
  );

  // WHY useMemo on the context value: prevents every consumer from re-rendering on
  // unrelated state changes (e.g. a sibling component re-render that doesn't touch
  // links). The value object identity stays stable as long as the dependencies do.
  const value = useMemo<SymbolLinkingContextValue>(
    () => ({ links, setLinkColor, setActiveSymbol, getSymbolForPanel }),
    [links, setLinkColor, setActiveSymbol, getSymbolForPanel],
  );

  return (
    <SymbolLinkingContext.Provider value={value}>
      {children}
    </SymbolLinkingContext.Provider>
  );
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

/**
 * useSymbolLinking — low-level access to the full linking API.
 *
 * WHY throw on missing provider: fails fast with a clear message instead of
 * silently returning undefined and causing a cryptic downstream null dereference.
 */
export function useSymbolLinking(): SymbolLinkingContextValue {
  const ctx = useContext(SymbolLinkingContext);
  if (!ctx) {
    throw new Error("useSymbolLinking must be used inside <SymbolLinkingProvider>");
  }
  return ctx;
}

/**
 * useSymbolLink — convenience hook for a single panel widget.
 *
 * WHY a per-panel hook: widgets only care about their own symbol; the full links
 * map is not needed. This narrow hook makes call sites read like data: a widget
 * asks "what symbol am I supposed to display?" and gets a clean answer.
 *
 * @param panelId — the workspace panel ID this widget is rendered for
 * @returns symbol + instrumentId for the panel, plus isLinked flag (color !== "none")
 */
export function useSymbolLink(panelId: string): {
  symbol: string | null;
  instrumentId: string | null;
  /** True if the panel participates in a color group (and thus may receive broadcasts) */
  isLinked: boolean;
} {
  const { links, getSymbolForPanel } = useSymbolLinking();
  const link = links[panelId];
  const { symbol, instrumentId } = getSymbolForPanel(panelId);
  return {
    symbol,
    instrumentId,
    isLinked: !!link && link.color !== "none",
  };
}
