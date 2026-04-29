/**
 * lib/workspace-templates.ts — Predefined workspace layouts (PLAN-0051 T-C-3-06)
 *
 * WHY THIS EXISTS: First-time users (and even seasoned ones starting a new
 * analytical session) shouldn't have to manually wire up panels. Templates
 * give a one-click path from "blank workspace" to a sensibly-laid-out set of
 * panels appropriate for a specific trading workflow.
 *
 * WHY 5 TEMPLATES (not 1, not 20):
 *   - 1 template = no choice = useless personalization
 *   - 20 templates = decision paralysis
 *   - 5 covers the canonical institutional workflows: day trade, swing,
 *     research, news-driven, long-term. Anything beyond is just rearranging
 *     the same panel set, which the user can do post-creation.
 *
 * WHY this file is .ts (not .tsx): pure data + types, no JSX. Keeping it
 * non-React makes it usable from any module (server actions, tests, etc.)
 * without pulling in React as a dependency.
 *
 * IMPORTANT: Each template's `config.panels` references panel_type strings that
 * MUST exist in PANEL_CATALOGUE in WorkspaceContext.tsx. If a panel_type is
 * removed from PANEL_CATALOGUE, the template that references it would create
 * an unrenderable workspace. The companion test
 * (__tests__/workspace-templates.test.tsx) asserts every template references
 * only valid panel types — that test guards against this drift.
 *
 * WHO USES IT:
 *   - NewFromTemplateDialog.tsx — renders 5 cards
 *   - tests in __tests__/workspace-templates.test.tsx
 * DESIGN REFERENCE: PLAN-0051 §T-C-3-06 (5 templates), DESIGN_SYSTEM.md
 */

import type {
  PanelType,
  WorkspaceConfig,
  WorkspacePanel,
  WorkspaceRow,
} from "@/contexts/WorkspaceContext";

// ── Helper: build a panel with a unique id ────────────────────────────────────

/**
 * makePanel — creates a panel with a deterministic-but-unique id.
 *
 * WHY include the template id in the panel id: when the user instantiates a
 * template, we copy the `panels` array verbatim. Without unique ids, two panels
 * of the same type (e.g., two charts in "Day Trader") would share the same
 * React key and trigger the "Encountered two children with the same key"
 * warning. Embedding the template id gives stable, debuggable ids.
 *
 * WHY `${templateId}-${type}-${index}` (not crypto.randomUUID): tests need
 * deterministic panel ids to assert on. UUIDs would force tests to use
 * approximate matchers everywhere. The template id + index combo is unique
 * within a template and easy to read in DOM inspector.
 */
function makePanel(templateId: string, type: PanelType, index: number): WorkspacePanel {
  return { id: `${templateId}-${type}-${index}`, type };
}

/** makeRow — convenience constructor that wraps panels in a row. */
function makeRow(panels: WorkspacePanel[]): WorkspaceRow {
  return { panels };
}

// ── Template type ─────────────────────────────────────────────────────────────

/**
 * WorkspaceTemplate — a reusable workspace blueprint.
 *
 * WHY config.id is omitted: the template itself has no workspace id. When the
 * user instantiates the template, the WorkspaceContext.addWorkspaceFromConfig
 * caller assigns a fresh `ws-custom-<timestamp>` id. Storing a fixed id on the
 * template would mean "instantiating the same template twice" overwrites the
 * first instance — clearly wrong.
 */
export interface WorkspaceTemplate {
  /** Stable template id — used as cache key for the dialog list */
  id: string;
  /** Short user-facing name (≤16 chars to fit in dialog cards) */
  name: string;
  /** One-sentence description shown beneath the name */
  description: string;
  /**
   * The workspace shape this template instantiates. The caller assigns a
   * fresh `id` after copying these fields.
   */
  config: Omit<WorkspaceConfig, "id">;
}

// ── Templates ────────────────────────────────────────────────────────────────

// WHY arrays inside makeRow inside config.rows: matches WorkspaceConfig's
// nested shape exactly (rows: [{panels: [...]}, {panels: [...]}]). This makes
// the template structure 1:1 with the runtime layout — visually scannable.

/**
 * DAY_TRADER — fast-paced intraday monitoring layout.
 *
 * WHY this layout: a day trader needs the chart front-and-center (large), with
 * the live watchlist immediately beside it for quick symbol switches. The
 * second row exposes flash news and active alerts — both are reactive surfaces.
 */
const DAY_TRADER: WorkspaceTemplate = {
  id: "day-trader",
  name: "Day Trader",
  description: "Real-time chart, watchlist, news feed, and alerts for fast-paced intraday work.",
  config: {
    name: "Day Trader",
    rows: [
      makeRow([
        makePanel("day-trader", "chart", 0),
        makePanel("day-trader", "watchlist", 1),
      ]),
      makeRow([
        makePanel("day-trader", "news", 2),
        makePanel("day-trader", "alerts", 3),
      ]),
    ],
  },
};

/**
 * RESEARCH — deep due-diligence layout for one symbol.
 *
 * WHY this layout: a research analyst evaluating a single ticker wants chart,
 * fundamentals, news, and AI brief side-by-side. The chart provides price
 * context, fundamentals show valuation/quality, news surfaces catalysts, and
 * the brief synthesizes everything via LLM.
 */
const RESEARCH: WorkspaceTemplate = {
  id: "research",
  name: "Research",
  description: "Chart, fundamentals, news, and AI brief side-by-side for deep due diligence.",
  config: {
    name: "Research",
    rows: [
      makeRow([
        makePanel("research", "chart", 0),
        makePanel("research", "fundamentals", 1),
      ]),
      makeRow([
        makePanel("research", "news", 2),
        makePanel("research", "brief", 3),
      ]),
    ],
  },
};

/**
 * SWING_TRADER — multi-day to multi-week position monitoring.
 *
 * WHY this layout: swing traders care about daily/weekly chart patterns,
 * scanning the screener for new setups, monitoring their watchlist, and
 * checking key fundamentals for risk before entering. No alerts panel by
 * default — swing traders react over hours/days, not seconds.
 */
const SWING_TRADER: WorkspaceTemplate = {
  id: "swing-trader",
  name: "Swing Trader",
  description: "Daily/weekly chart, screener, watchlist, and key fundamentals for swing setups.",
  config: {
    name: "Swing Trader",
    rows: [
      makeRow([
        makePanel("swing-trader", "chart", 0),
        makePanel("swing-trader", "screener", 1),
      ]),
      makeRow([
        makePanel("swing-trader", "watchlist", 2),
        makePanel("swing-trader", "fundamentals", 3),
      ]),
    ],
  },
};

/**
 * NEWS_JUNKIE — news-flow-driven monitoring.
 *
 * WHY this layout: traders who trade primarily on news and sentiment want
 * morning brief at the top (highest-context surface), then news + alerts
 * below for the live stream. No chart by default — news junkies pull up
 * charts on demand when a story breaks.
 */
const NEWS_JUNKIE: WorkspaceTemplate = {
  id: "news-junkie",
  name: "News Junkie",
  description: "Morning brief, live news, and alerts for headline-driven trading.",
  config: {
    name: "News Junkie",
    rows: [
      makeRow([makePanel("news-junkie", "brief", 0)]),
      makeRow([
        makePanel("news-junkie", "news", 1),
        makePanel("news-junkie", "alerts", 2),
      ]),
    ],
  },
};

/**
 * INVESTOR — long-term portfolio monitoring layout.
 *
 * WHY this layout: long-term investors check their portfolio, drill into
 * fundamentals of holdings, monitor a chart for context, and read AI briefs
 * for thesis updates. They DO NOT use screeners or alerts daily — those
 * surfaces are for active traders.
 */
const INVESTOR: WorkspaceTemplate = {
  id: "investor",
  name: "Investor",
  description: "Portfolio holdings, fundamentals, chart, and AI brief for long-term holdings.",
  config: {
    name: "Investor",
    rows: [
      makeRow([
        makePanel("investor", "portfolio", 0),
        makePanel("investor", "fundamentals", 1),
      ]),
      makeRow([
        makePanel("investor", "chart", 2),
        makePanel("investor", "brief", 3),
      ]),
    ],
  },
};

// ── Public exports ────────────────────────────────────────────────────────────

/**
 * WORKSPACE_TEMPLATES — the 5 canonical templates shown in NewFromTemplateDialog.
 *
 * WHY exported as a const array (not a function): templates are static; making
 * them a function would invite the temptation to inject runtime data, breaking
 * the "templates are fixed" mental model. Const array also enables TS to infer
 * the tuple type, giving exhaustive switch checks at call sites.
 */
export const WORKSPACE_TEMPLATES: WorkspaceTemplate[] = [
  DAY_TRADER,
  RESEARCH,
  SWING_TRADER,
  NEWS_JUNKIE,
  INVESTOR,
];

/**
 * findTemplate — look up a template by id. Returns undefined when missing.
 *
 * WHY a helper (not Array.find inline at call sites): documents the intent and
 * allows future caching (e.g., if WORKSPACE_TEMPLATES grows we could swap to a
 * Map) without touching call sites. Tests also call this directly for clarity.
 */
export function findTemplate(id: string): WorkspaceTemplate | undefined {
  return WORKSPACE_TEMPLATES.find((t) => t.id === id);
}
