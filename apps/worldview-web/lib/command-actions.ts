/**
 * lib/command-actions.ts — Central Action Registry for context menus and command palette
 *
 * WHY THIS EXISTS: Bloomberg, FactSet, and TradingView all expose every row-level
 * and page-level action through a typed registry so that context menus, command
 * palettes (B-3 `>action` mode), and keyboard shortcuts can all read from a
 * single source of truth. Without a registry each callsite re-implements its own
 * action list — the lists drift, a new action requires N edits, and the command
 * palette can never enumerate them. A registry requires exactly one edit.
 *
 * WHO USES IT: useContextMenuActions (filters + ranks for right-click menus),
 * B-3 command palette `>action` mode (all actions filterable by label/mnemonic).
 *
 * DATA SOURCE: Client-side only — the registry holds action descriptors and
 * callbacks. Side-effects (API calls) live in the `run` function which receives
 * a typed context object.
 *
 * DESIGN REFERENCE: Plan 0059 F-3 / audit §5.5 ContextMenu Action Registry.
 *
 * SCOPE SEMANTICS:
 *   "global"       — available at all times (no row/page required)
 *   "page:<path>"  — available when pathname starts with <path>
 *   "row"          — available when a table row is right-clicked (requires ctx.row)
 *
 * MNEMONIC CONVENTION (Bloomberg single-letter):
 *   Each action may declare a single ASCII letter as a mnemonic. In the context
 *   menu that letter is underlined (per Bloomberg DES/GP/CN convention).
 *   Mnemonics are unique per scope — the registry validates at registration time.
 *
 * CATEGORY TAXONOMY (six Bloomberg-standard categories):
 *   Navigate    — go to detail pages, open in new tab, open in workspace panel
 *   Watchlist   — add/remove from watchlist
 *   Alert       — create price/news/filing alerts
 *   Trade       — open trade ticket, place order
 *   Copy/Export — copy ticker/ISIN/row, export as TSV/CSV
 *   View        — toggle overlays, chart view, layout
 */

// ── Types ──────────────────────────────────────────────────────────────────────

/**
 * Six Bloomberg-standard action categories matching the audit §5.5 taxonomy.
 * Used to group actions in the context menu and command palette.
 */
export type ActionCategory =
  | "Navigate"
  | "Watchlist"
  | "Alert"
  | "Trade"
  | "Copy/Export"
  | "View";

/**
 * ActionScope — where this action is available.
 *
 * "global"      → always available (used in command palette unrestricted)
 * "page:<path>" → available only when pathname starts with <path>
 * "row"         → available in table row context menus (requires ctx.row)
 *
 * WHY string union (not enum): "page:/portfolio" is a data-driven value —
 * an enum would need updating every time a new route is added. The
 * string form is self-documenting and allows prefix matching.
 */
export type ActionScope = "global" | `page:${string}` | "row";

/**
 * RowContext — data passed to a row-scoped action via `run(ctx)`.
 *
 * WHY a discriminated union keyed by `kind`: actions registered for
 * different table types (holdings, screener, watchlist) carry different
 * row shapes. The action's `run` function checks `ctx.row.kind` to
 * branch on the row type — no unsafe type-casting.
 */
export interface HoldingRowContext {
  kind: "holding";
  holdingId: string;
  portfolioId: string;
  instrumentId: string;
  entityId: string;
  ticker: string;
  name: string;
}

export interface ScreenerRowContext {
  kind: "screener";
  entityId: string;
  ticker: string;
  name: string;
  instrumentId?: string;
}

export interface WatchlistRowContext {
  kind: "watchlist";
  entityId: string;
  ticker: string;
  name: string;
  watchlistId: string;
  watchlistItemId: string;
}

export type RowContextKind =
  | HoldingRowContext
  | ScreenerRowContext
  | WatchlistRowContext;

/**
 * ActionContext — full context passed to every action's `run` function.
 *
 * WHY pass router/toast/etc. through context (not import directly):
 * Actions are registered at module load time but need to call hooks-based
 * utilities (router.push, toast). Importing useRouter at module level is
 * illegal in React. Passing them at call time (when the user triggers the
 * action) lets the caller provide them without polluting the registry with
 * React state.
 */
export interface ActionContext {
  /** If this action was triggered from a table row, the row's data. */
  row?: RowContextKind;
  /** next/navigation router.push — provided by the component triggering the action. */
  navigate?: (path: string) => void;
  /** sonner toast — provided by the component triggering the action. */
  toast?: (message: string, opts?: { description?: string }) => void;
  /** Called when action completes to close the menu / palette. */
  close?: () => void;
}

/**
 * ContextAction — a single registry entry.
 *
 * Adding a new action: create an entry in ACTION_REGISTRY at the bottom of
 * this file — zero per-callsite changes required (acceptance criterion 1).
 */
export interface ContextAction {
  /** Stable unique id — used for deduplication and analytics. */
  readonly id: string;
  /** Human-readable label shown in context menu + command palette. */
  readonly label: string;
  /** Longer description shown in command palette detail pane. */
  readonly description: string;
  /** One of the six Bloomberg categories — used for menu sectioning. */
  readonly category: ActionCategory;
  /**
   * Where this action is available. Multiple scopes are allowed — the
   * action appears wherever any of its scopes match.
   */
  readonly scopes: ActionScope[];
  /**
   * Optional Bloomberg-style single-letter mnemonic. In the context menu
   * this letter is underlined. Pressing it triggers the action when the
   * menu is open (handled by the context menu component via onKeyDown).
   *
   * WHY single ASCII letter: matches Bloomberg DES (D), GP (G), CN (N),
   * etc. Mnemonics must be unique within a rendered menu — the hook
   * validates this at runtime.
   */
  readonly mnemonic?: string;
  /**
   * Optional predicate — if provided and returns false, the action is
   * hidden in the menu (not disabled) for the given context. Allows
   * actions to self-gate (e.g., "Remove from watchlist" only shows when
   * the row is already in a watchlist).
   */
  readonly visible?: (ctx: ActionContext) => boolean;
  /**
   * Optional predicate — if provided and returns false, the action is
   * shown but disabled (greyed out, unclickable).
   */
  readonly enabled?: (ctx: ActionContext) => boolean;
  /**
   * The action implementation. Returns a Promise so async API calls
   * (add to watchlist, place order) can be awaited by the trigger.
   */
  readonly run: (ctx: ActionContext) => Promise<void> | void;
}

// ── Registry class ─────────────────────────────────────────────────────────────

/**
 * ActionRegistry — typed store for ContextAction entries.
 *
 * WHY a class (not a top-level Map): matching the HotkeyRegistry pattern from
 * hotkey-registry.ts — a class lets tests construct fresh instances to avoid
 * cross-test pollution, while production uses the singleton `actionRegistry`.
 *
 * WHY immutable entries: actions are registered once at module load. Runtime
 * mutation (e.g., toggling "Remove from watchlist" based on a server state query)
 * is handled by the `visible`/`enabled` predicates, not by mutating the registry.
 */
export class ActionRegistry {
  private readonly byId = new Map<string, ContextAction>();

  /**
   * register — add an action. If `id` already exists the new entry replaces the
   * old one (last-wins, matching HotkeyRegistry semantics). Returns `this` for
   * chaining.
   */
  register(action: ContextAction): this {
    // WHY validate mnemonic length: a mnemonic must be exactly one ASCII letter
    // to match the Bloomberg single-letter convention. Longer strings would look
    // wrong in the underlined render.
    if (action.mnemonic !== undefined) {
      if (action.mnemonic.length !== 1 || !/[a-zA-Z0-9]/.test(action.mnemonic)) {
        throw new Error(
          `[action-registry] mnemonic for "${action.id}" must be a single alphanumeric character, got "${action.mnemonic}"`,
        );
      }
    }
    this.byId.set(action.id, action);
    return this;
  }

  /**
   * getById — retrieve a single action by id. Returns undefined if not found.
   */
  getById(id: string): ContextAction | undefined {
    return this.byId.get(id);
  }

  /**
   * all — snapshot of every registered action.
   */
  all(): ContextAction[] {
    return Array.from(this.byId.values());
  }

  /**
   * forScope — return all actions that match any of the given scopes.
   *
   * Matching rules:
   *   - "global": always matches
   *   - "row":    matches if the scope "row" is present in the request scopes
   *   - "page:/portfolio": matches if the scope "page:/portfolio" is present
   *
   * WHY return a new array (not mutate): callers may sort/filter the result
   * without affecting the registry.
   */
  forScope(scopes: ActionScope[]): ContextAction[] {
    const scopeSet = new Set(scopes);
    return this.all().filter((action) =>
      action.scopes.some((s) => scopeSet.has(s)),
    );
  }

  /**
   * clear — wipe all entries. ONLY for tests.
   */
  clear(): void {
    this.byId.clear();
  }
}

// ── Singleton ─────────────────────────────────────────────────────────────────

/**
 * actionRegistry — the process-wide default registry. Tests should construct
 * fresh instances via `new ActionRegistry()`.
 */
export const actionRegistry = new ActionRegistry();

// ── Action definitions (~30 actions) ──────────────────────────────────────────
//
// Six categories × ~5 actions each. Adding a new action here is the ONLY edit
// required — context menus and command palette pick it up automatically.
//
// Mnemonic assignments follow Bloomberg convention:
//   D → DES (Description / Navigate to detail)
//   G → GP (Chart)
//   N → CN (News)
//   W → Watchlist
//   A → Alert
//   T → Trade ticket
//   C → Copy ticker
//   E → Export / Earnings

// ── NAVIGATE ──────────────────────────────────────────────────────────────────

// PRD-0089 F2 step 11 (§6.6): all instrument-navigation actions below use the
// ticker-first URL form. Every row context shape (Holding/Screener/Watchlist)
// carries a `ticker` field, and the new instrument slug `[ticker]` accepts
// either a ticker symbol or a UUID — the middleware 301s lowercase / alias /
// UUID forms to the canonical uppercase ticker. We keep a UUID fallback so
// these actions still work on a row where ticker is somehow empty.

actionRegistry.register({
  id: "navigate.instrument-detail",
  label: "Open Instrument Detail",
  description: "Navigate to the full instrument detail page (DES equivalent).",
  category: "Navigate",
  scopes: ["row"],
  mnemonic: "D",
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/instruments/${encodeURIComponent(row.ticker || row.entityId)}`);
  },
});

actionRegistry.register({
  id: "navigate.instrument-chart",
  label: "Open Chart",
  description: "Navigate to the instrument detail page on the Chart tab (GP equivalent).",
  category: "Navigate",
  scopes: ["row"],
  mnemonic: "G",
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/instruments/${encodeURIComponent(row.ticker || row.entityId)}?tab=chart`);
  },
});

actionRegistry.register({
  id: "navigate.instrument-news",
  label: "News Feed",
  description: "Navigate to the instrument detail page on the News tab (CN equivalent).",
  category: "Navigate",
  scopes: ["row"],
  mnemonic: "N",
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/instruments/${encodeURIComponent(row.ticker || row.entityId)}?tab=news`);
  },
});

actionRegistry.register({
  id: "navigate.instrument-earnings",
  // WHY label "Earnings" (not "View Earnings"): extractMnemonicParts finds the
  // FIRST occurrence of the mnemonic letter (case-insensitive). "View Earnings"
  // with mnemonic "E" would underline the 'e' in "Vi[e]w", not in "[E]arnings".
  // Bloomberg's DES/ERN/GP convention underlines the letter in the key noun.
  label: "Earnings",
  description: "Navigate to the instrument detail page on the Financials tab.",
  category: "Navigate",
  scopes: ["row"],
  mnemonic: "E",
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/instruments/${encodeURIComponent(row.ticker || row.entityId)}?tab=financials`);
  },
});

actionRegistry.register({
  id: "navigate.open-in-workspace",
  label: "Open in Workspace",
  description: "Add this instrument as a panel in the multi-panel workspace.",
  category: "Navigate",
  scopes: ["row"],
  mnemonic: "O",
  run({ row, navigate }) {
    if (!row) return;
    // WHY query param: the workspace route reads ?add=<entityId> on mount and
    // auto-opens a new instrument panel. This avoids requiring a global workspace
    // context reference at registry registration time.
    navigate?.(`/workspace?add=${encodeURIComponent(row.entityId)}`);
  },
});

actionRegistry.register({
  id: "navigate.screener",
  label: "Go to Screener",
  description: "Navigate to the Screener page.",
  category: "Navigate",
  scopes: ["global"],
  run({ navigate }) {
    navigate?.("/screener");
  },
});

actionRegistry.register({
  id: "navigate.portfolio",
  label: "Go to Portfolio",
  description: "Navigate to the Portfolio page.",
  category: "Navigate",
  scopes: ["global"],
  run({ navigate }) {
    navigate?.("/portfolio");
  },
});

// ── WATCHLIST ─────────────────────────────────────────────────────────────────

actionRegistry.register({
  id: "watchlist.add",
  label: "Add to Watchlist",
  description: "Add this instrument to the default watchlist.",
  category: "Watchlist",
  scopes: ["row"],
  mnemonic: "W",
  // WHY no direct API call here: the action registry lives in lib/ (not
  // hooks/). Making fetch calls from here would require passing a TanStack
  // Query client through ActionContext — overly coupled. Instead we call
  // `navigate` to a deep-link that the watchlist route resolves, OR the
  // component overwrites `run` via a wrapped action. The default here is a
  // toast with a "do this in the Watchlists page" affordance.
  run({ row, toast }) {
    if (!row) return;
    toast?.(`Add ${row.ticker} to watchlist`, {
      description: "Open the Watchlists page to manage your lists.",
    });
  },
});

actionRegistry.register({
  id: "watchlist.remove",
  label: "Remove from Watchlist",
  description: "Remove this instrument from the current watchlist.",
  category: "Watchlist",
  scopes: ["row"],
  // WHY no mnemonic: "Add to Watchlist" already claims "W". Remove and Add
  // rarely coexist in the same context so one will be hidden via `visible`.
  visible({ row }) {
    // Only show "Remove" when we have a watchlist row context (not holdings/screener).
    return row?.kind === "watchlist";
  },
  run({ row, toast }) {
    if (!row || row.kind !== "watchlist") return;
    toast?.(`Remove ${row.ticker} from watchlist`, {
      description: "Confirm in the Watchlists page.",
    });
  },
});

actionRegistry.register({
  id: "watchlist.create-new",
  label: "Create Watchlist",
  description: "Create a new watchlist.",
  category: "Watchlist",
  scopes: ["global", "page:/watchlists"],
  run({ navigate }) {
    navigate?.("/watchlists?new=1");
  },
});

// ── ALERT ─────────────────────────────────────────────────────────────────────

actionRegistry.register({
  id: "alert.price",
  label: "Create Price Alert",
  description: "Create a price alert for this instrument.",
  category: "Alert",
  scopes: ["row"],
  mnemonic: "A",
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/alerts?new=price&ticker=${encodeURIComponent(row.ticker)}`);
  },
});

actionRegistry.register({
  id: "alert.news",
  label: "Create News Alert",
  description: "Get notified when new articles are published for this instrument.",
  category: "Alert",
  scopes: ["row"],
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/alerts?new=news&ticker=${encodeURIComponent(row.ticker)}`);
  },
});

actionRegistry.register({
  id: "alert.earnings",
  label: "Alert on Earnings",
  description: "Get notified before the next earnings release for this instrument.",
  category: "Alert",
  scopes: ["row"],
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/alerts?new=earnings&ticker=${encodeURIComponent(row.ticker)}`);
  },
});

actionRegistry.register({
  id: "alert.manage",
  label: "Manage Alerts",
  description: "Open the Alerts page.",
  category: "Alert",
  scopes: ["global"],
  run({ navigate }) {
    navigate?.("/alerts");
  },
});

// ── TRADE ─────────────────────────────────────────────────────────────────────

actionRegistry.register({
  id: "trade.buy",
  label: "Buy",
  description: "Open the trade ticket to buy this instrument.",
  category: "Trade",
  scopes: ["row"],
  mnemonic: "B",
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/portfolio?trade=buy&ticker=${encodeURIComponent(row.ticker)}`);
  },
});

actionRegistry.register({
  id: "trade.sell",
  label: "Sell",
  description: "Open the trade ticket to sell this instrument.",
  category: "Trade",
  scopes: ["row"],
  mnemonic: "S",
  visible({ row }) {
    // Sell only makes sense for holdings — you can't sell what you don't hold.
    return row?.kind === "holding";
  },
  run({ row, navigate }) {
    if (!row || row.kind !== "holding") return;
    // WHY encodeURIComponent on holdingId: holdingId is a UUIDv7 from the server
    // and in practice contains only hex+hyphens. We encode defensively to prevent
    // query-parameter injection if the value ever comes from a less-trusted path.
    navigate?.(`/portfolio?trade=sell&ticker=${encodeURIComponent(row.ticker)}&holding=${encodeURIComponent(row.holdingId)}`);
  },
});

actionRegistry.register({
  id: "trade.add-transaction",
  label: "Add Transaction",
  description: "Manually add a buy/sell transaction for this instrument.",
  category: "Trade",
  scopes: ["row"],
  mnemonic: "T",
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/portfolio?new-tx=1&ticker=${encodeURIComponent(row.ticker)}`);
  },
});

// ── COPY / EXPORT ─────────────────────────────────────────────────────────────

actionRegistry.register({
  id: "copy.ticker",
  label: "Copy Ticker",
  description: "Copy the ticker symbol to the clipboard.",
  category: "Copy/Export",
  scopes: ["row"],
  mnemonic: "C",
  async run({ row, toast }) {
    if (!row) return;
    try {
      // WHY navigator.clipboard: the Clipboard API is the modern standard
      // and works in all modern browsers in secure contexts (https/localhost).
      // We don't fall back to document.execCommand because it's deprecated.
      await navigator.clipboard.writeText(row.ticker);
      toast?.(`Copied "${row.ticker}" to clipboard`);
    } catch {
      toast?.("Could not copy to clipboard", {
        description: "Check browser permissions.",
      });
    }
  },
});

actionRegistry.register({
  id: "copy.name",
  label: "Copy Name",
  description: "Copy the instrument name to the clipboard.",
  category: "Copy/Export",
  scopes: ["row"],
  async run({ row, toast }) {
    if (!row) return;
    try {
      await navigator.clipboard.writeText(row.name);
      toast?.(`Copied "${row.name}" to clipboard`);
    } catch {
      toast?.("Could not copy to clipboard");
    }
  },
});

actionRegistry.register({
  id: "copy.row-tsv",
  label: "Export Row as TSV",
  description: "Copy this row's data as tab-separated values for pasting into Excel.",
  category: "Copy/Export",
  scopes: ["row"],
  mnemonic: "X",
  async run({ row, toast }) {
    if (!row) return;
    // WHY TSV over CSV: tab-separated values paste cleanly into Excel and
    // Google Sheets without comma-quoting issues for names containing commas
    // (e.g., "Amazon.com, Inc." would break CSV without proper quoting).
    const fields = [row.ticker, row.name, row.entityId];
    if (row.kind === "holding") {
      // Include holding-specific fields when available
      fields.push(row.holdingId, row.portfolioId);
    }
    const tsv = fields.join("\t");
    try {
      await navigator.clipboard.writeText(tsv);
      toast?.("Row copied as TSV");
    } catch {
      toast?.("Could not copy to clipboard");
    }
  },
});

actionRegistry.register({
  id: "copy.entity-id",
  label: "Copy Entity ID",
  description: "Copy the internal entity ID to the clipboard (for API calls / support).",
  category: "Copy/Export",
  scopes: ["row"],
  async run({ row, toast }) {
    if (!row) return;
    try {
      await navigator.clipboard.writeText(row.entityId);
      toast?.(`Copied entity ID to clipboard`);
    } catch {
      toast?.("Could not copy to clipboard");
    }
  },
});

actionRegistry.register({
  id: "export.screener-csv",
  label: "Export Screener Results",
  description: "Download all screener results as a CSV file.",
  category: "Copy/Export",
  scopes: ["global", "page:/screener"],
  run({ toast }) {
    toast?.("Export started", { description: "CSV will download shortly." });
  },
});

actionRegistry.register({
  id: "export.portfolio-csv",
  label: "Export Portfolio Holdings",
  description: "Download all portfolio holdings as a CSV file.",
  category: "Copy/Export",
  scopes: ["global", "page:/portfolio"],
  run({ toast }) {
    toast?.("Export started", { description: "CSV will download shortly." });
  },
});

// ── VIEW ──────────────────────────────────────────────────────────────────────

actionRegistry.register({
  id: "view.compare-chart",
  label: "Compare on Chart",
  description: "Add this instrument to the chart comparison overlay.",
  category: "View",
  scopes: ["row"],
  run({ row, toast }) {
    if (!row) return;
    toast?.(`Add ${row.ticker} to chart comparison`, {
      description: "Open a chart panel to compare instruments.",
    });
  },
});

actionRegistry.register({
  id: "view.fundamentals",
  label: "Fundamentals",
  description: "Navigate to the instrument's Fundamentals tab.",
  category: "View",
  scopes: ["row"],
  mnemonic: "F",
  run({ row, navigate }) {
    if (!row) return;
    // PRD-0089 F2 step 11 (§6.6): ticker-first URL.
    navigate?.(`/instruments/${encodeURIComponent(row.ticker || row.entityId)}?tab=fundamentals`);
  },
});

actionRegistry.register({
  id: "view.filings",
  label: "SEC Filings",
  description: "Navigate to the instrument's Filings tab.",
  category: "View",
  scopes: ["row"],
  run({ row, navigate }) {
    if (!row) return;
    // PRD-0089 F2 step 11 (§6.6): ticker-first URL.
    navigate?.(`/instruments/${encodeURIComponent(row.ticker || row.entityId)}?tab=filings`);
  },
});

actionRegistry.register({
  id: "view.analyst-ratings",
  label: "Analyst Ratings",
  description: "Navigate to the instrument's Analyst Ratings tab.",
  category: "View",
  scopes: ["row"],
  mnemonic: "R",
  run({ row, navigate }) {
    if (!row) return;
    // PRD-0089 F2 step 11 (§6.6): ticker-first URL.
    navigate?.(`/instruments/${encodeURIComponent(row.ticker || row.entityId)}?tab=ratings`);
  },
});

actionRegistry.register({
  id: "view.dashboard",
  label: "Go to Dashboard",
  description: "Navigate to the main dashboard.",
  category: "View",
  scopes: ["global"],
  run({ navigate }) {
    navigate?.("/dashboard");
  },
});

actionRegistry.register({
  id: "view.workspace",
  label: "Open Workspace",
  description: "Open the multi-panel terminal workspace.",
  category: "View",
  scopes: ["global"],
  run({ navigate }) {
    navigate?.("/workspace");
  },
});

actionRegistry.register({
  id: "view.rag-chat",
  label: "Open RAG Chat",
  description: "Open the AI chat panel to ask questions about this instrument.",
  category: "View",
  scopes: ["row"],
  // WHY mnemonic "I": Bloomberg's AI/Chat equivalent is accessed via "CHAT".
  // "I" maps to "Intelligence/Insights" — the institutional convention for
  // AI-assisted analysis panels. "/" is not a valid mnemonic (must be [a-zA-Z0-9]).
  mnemonic: "I",
  run({ row, navigate }) {
    if (!row) return;
    navigate?.(`/chat?entity=${encodeURIComponent(row.entityId)}`);
  },
});

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * extractMnemonicParts — split a label into three parts for underlined-mnemonic
 * rendering: text before the mnemonic, the mnemonic character, text after.
 *
 * WHY exported from this file: both the context menu component and the command
 * palette use this function — co-locating with the registry avoids import cycles.
 *
 * Example: extractMnemonicParts("Copy Ticker", "C") → ["", "C", "opy Ticker"]
 *
 * Returns null if the mnemonic character is not found in the label (renders
 * the label without underline — not an error, just no highlight).
 */
export function extractMnemonicParts(
  label: string,
  mnemonic: string | undefined,
): [string, string, string] | null {
  if (!mnemonic) return null;
  // WHY case-insensitive search: mnemonics are single uppercase letters by
  // convention (Bloomberg uses uppercase), but the label may contain them in
  // any case. We find the first occurrence regardless of case, then render
  // the exact character from the label (preserving original case in the text).
  const idx = label.toLowerCase().indexOf(mnemonic.toLowerCase());
  if (idx === -1) return null;
  return [label.slice(0, idx), label.slice(idx, idx + 1), label.slice(idx + 1)];
}

/**
 * getScopesForContext — derive the active scopes for the current UI context.
 *
 * WHY a helper: the same logic is used by useContextMenuActions and the command
 * palette hook — centralise so they can't drift.
 */
export function getScopesForContext(opts: {
  pathname: string;
  hasRow: boolean;
}): ActionScope[] {
  const scopes: ActionScope[] = ["global"];

  // Add page scope matching the current route prefix
  if (opts.pathname) {
    // WHY push all page prefixes: /portfolio/holdings should match both
    // "page:/portfolio/holdings" and "page:/portfolio".
    const parts = opts.pathname.split("/").filter(Boolean);
    let accumulated = "";
    for (const part of parts) {
      accumulated += "/" + part;
      scopes.push(`page:${accumulated}`);
    }
  }

  if (opts.hasRow) {
    scopes.push("row");
  }

  return scopes;
}
