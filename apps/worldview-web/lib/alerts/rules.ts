/**
 * lib/alerts/rules.ts — alert rule CRUD helpers (PLAN-0051 Wave D T-D-4-06).
 *
 * WHY THIS EXISTS: AlertRuleBuilder (legacy) wrote rules straight into a
 * localStorage blob. The Rule Manager dialog needs full CRUD (list/edit/delete)
 * and we'd like the same code path to gracefully upgrade to a backend
 * endpoint when one ships. Splitting the storage layer out of the builder
 * keeps both the builder and the manager single-source-of-truth for the
 * shape of an `AlertRule` and the storage key.
 *
 * BACKEND CONTRACT (planned, not yet shipped):
 *   GET    /v1/alerts/rules
 *   POST   /v1/alerts/rules
 *   PATCH  /v1/alerts/rules/{id}
 *   DELETE /v1/alerts/rules/{id}
 *
 * Until the parallel backend agent ships those endpoints, every helper here
 * returns rules tagged `_localOnly: true`. The audit doc
 * `docs/audits/2026-04-29-alert-rule-crud-gap.md` documents this gap so the
 * S10 team has a single place to track the work.
 */

// ── Types ──────────────────────────────────────────────────────────────────

/**
 * AlertRule — a user-defined alert trigger.
 *
 * WHY explicit `enabled` flag: traders prefer "pause" over "delete" for rules
 * they want to bring back later (e.g. earnings-window rules that only matter
 * during the season). Soft-disable beats hard-delete for that workflow.
 *
 * WHY name: lets the manager render a recognisable label even before any
 * rule has fired. Falls back to `${type}: ${condition}` when blank.
 */
export interface AlertRule {
  id: string;
  /** Human label — defaults to `${type}: ${condition}` when blank. */
  name: string;
  type: "price_threshold" | "volume_spike" | "news_signal" | "portfolio_risk";
  /** Free-text entity hint (ticker, name) — backend will resolve to entity_id. */
  entitySearch: string;
  /** The condition expression (e.g. "price > 150"). Free-text for now. */
  condition: string;
  /** Whether the rule is currently active. */
  enabled: boolean;
  notifyInApp: boolean;
  notifyEmail: boolean;
  createdAt: string; // ISO 8601 UTC
  /** True when persisted only in localStorage (backend endpoint missing). */
  _localOnly?: boolean;
}

/** Patch payload for editing — every field optional. */
export type AlertRulePatch = Partial<Omit<AlertRule, "id" | "createdAt">>;

// ── Constants ──────────────────────────────────────────────────────────────

/**
 * STORAGE_KEY — the legacy AlertRuleBuilder uses `worldview-alert-rules`.
 * We re-use it so existing rules are visible in the new manager without a
 * migration. New fields (`name`, `enabled`) gain defaults via the loader.
 */
const STORAGE_KEY = "worldview-alert-rules";

// ── Storage helpers ────────────────────────────────────────────────────────

/**
 * normaliseRule — back-fill defaults onto a row read from localStorage.
 *
 * WHY: pre-Wave D rows omit `name` and `enabled`. Without normalisation a
 * legacy rule would render as a blank cell + no enabled toggle.
 */
function normaliseRule(raw: Partial<AlertRule>): AlertRule {
  const id = typeof raw.id === "string" ? raw.id : `rule-${Date.now()}`;
  const type = (raw.type as AlertRule["type"]) ?? "price_threshold";
  const condition = typeof raw.condition === "string" ? raw.condition : "";
  const entitySearch = typeof raw.entitySearch === "string" ? raw.entitySearch : "";
  return {
    id,
    name: typeof raw.name === "string" && raw.name.length > 0 ? raw.name : defaultRuleName(type, entitySearch, condition),
    type,
    entitySearch,
    condition,
    enabled: raw.enabled ?? true,
    notifyInApp: raw.notifyInApp ?? true,
    notifyEmail: raw.notifyEmail ?? false,
    createdAt: typeof raw.createdAt === "string" ? raw.createdAt : new Date().toISOString(),
    _localOnly: true,
  };
}

/**
 * defaultRuleName — produce a recognisable label from the rule's contents
 * when no explicit name was supplied. Used by the manager + the builder.
 */
export function defaultRuleName(type: AlertRule["type"], entity: string, condition: string): string {
  const subject = entity.trim() || "Any entity";
  const labelMap: Record<AlertRule["type"], string> = {
    price_threshold: "Price",
    volume_spike: "Volume",
    news_signal: "News",
    portfolio_risk: "Portfolio risk",
  };
  return `${labelMap[type]} • ${subject}${condition ? ` • ${condition}` : ""}`;
}

/** Read the current rules array from localStorage, normalised. */
function readRules(): AlertRule[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.map((row) => normaliseRule(row as Partial<AlertRule>));
  } catch {
    return [];
  }
}

/** Persist the rules array to localStorage. */
function writeRules(rules: AlertRule[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(rules));
  } catch {
    // ignore — quota / private-mode
  }
}

// ── Public CRUD API (localStorage-only for the MVP) ───────────────────────

/**
 * listAlertRules — return all rules from localStorage.
 *
 * WHY async: when the backend endpoint ships we want to swap this
 * implementation without touching the call sites. Promises today, real fetch
 * tomorrow — same signature.
 */
export async function listAlertRules(): Promise<AlertRule[]> {
  return readRules();
}

/**
 * createAlertRule — insert a new rule. Returns the persisted row.
 */
export async function createAlertRule(input: Omit<AlertRule, "id" | "createdAt" | "_localOnly">): Promise<AlertRule> {
  const next: AlertRule = {
    ...input,
    id: typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `rule-${Date.now()}`,
    createdAt: new Date().toISOString(),
    _localOnly: true,
  };
  const all = readRules();
  writeRules([...all, next]);
  return next;
}

/**
 * updateAlertRule — apply a partial patch to a rule by id.
 */
export async function updateAlertRule(id: string, patch: AlertRulePatch): Promise<AlertRule | null> {
  const all = readRules();
  const idx = all.findIndex((r) => r.id === id);
  if (idx === -1) return null;
  // WHY spread in this order: existing values first, patch second so
  // explicit `undefined` in the patch does NOT clobber unrelated fields.
  // (Object spread keeps the latter-wins semantics so callers should pass
  // only the fields they intend to change.)
  const merged: AlertRule = { ...all[idx], ...patch, _localOnly: true };
  const next = [...all];
  next[idx] = merged;
  writeRules(next);
  return merged;
}

/**
 * deleteAlertRule — remove a rule by id. Returns true when removed.
 */
export async function deleteAlertRule(id: string): Promise<boolean> {
  const all = readRules();
  const next = all.filter((r) => r.id !== id);
  if (next.length === all.length) return false;
  writeRules(next);
  return true;
}

/**
 * countAlertRules — synchronous helper for badge counters.
 *
 * WHY sync: the page header reads this on every render to show "(N)" beside
 * the manage-rules button — async would force a useEffect/useState dance.
 */
export function countAlertRules(): number {
  return readRules().length;
}
