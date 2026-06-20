/**
 * lib/api/alertRules.ts — Real CRUD client + TanStack hooks for STANDING alert rules
 * (PLAN-0113 Wave 4, T-4-01).
 *
 * WHY THIS FILE EXISTS:
 * Until PLAN-0113 the only "rule" surface was `lib/alerts/rules.ts`, which stored
 * rules in localStorage and never reached the backend — a rule a user created
 * never actually fired. Wave 1 shipped a REAL backend resource:
 *
 *   POST   /v1/alert-rules            → create a standing rule
 *   GET    /v1/alert-rules            → list the caller's rules (+ filters)
 *   GET    /v1/alert-rules/{id}       → fetch one rule
 *   PATCH  /v1/alert-rules/{id}       → partial update (re-arms on condition change)
 *   DELETE /v1/alert-rules/{id}       → remove a rule (204)
 *
 * This module is the typed frontend mirror of that contract. The discriminated
 * `condition` union is keyed by `rule_type`, exactly as the backend Pydantic
 * models in `services/alert/src/alert/domain/rule_conditions.py` define it.
 *
 * ARCHITECTURE (R14 — Frontend → S9 only):
 * Every call goes through `apiFetch` (which prefixes `/api` → S9 gateway). The
 * frontend NEVER talks to S10 directly; S9 proxies `/v1/alert-rules` and injects
 * the internal JWT. `tenant_id` / `user_id` come from the JWT, never the body.
 *
 * WHY a dedicated factory (not folded into `alerts.ts`):
 * `alerts.ts` owns FIRED alerts (pending / history / ack / snooze). RULES are a
 * separate resource (standing vs fired). Keeping them in separate files mirrors
 * the backend's `/alerts` vs `/alert-rules` split and keeps each module < 350 LOC
 * (the CI size gate). This factory is spread into the gateway in `lib/gateway.ts`.
 */

import { apiFetch } from "./_client";

// ── Rule-type enum + literal union ─────────────────────────────────────────────

/**
 * RULE_TYPES — the 5 user-creatable rule types, in display order.
 *
 * WHY a runtime array (not just a TS type): the AlertWizard renders one "type
 * card" per entry and iterates this list, and tests assert the card count. A
 * bare `type` would not survive to runtime. `as const` makes each entry a
 * string-literal so `RuleType` below is the exact union, not `string`.
 *
 * These MUST stay in lock-step with the backend `RuleType` StrEnum
 * (services/alert/src/alert/domain/enums.py) — they are the discriminator.
 */
export const RULE_TYPES = [
  "PRICE_CROSS",
  "NEWS_COUNT",
  "NEWS_MOMENTUM",
  "KG_CONNECTION",
  "FUNDAMENTAL_CROSS",
] as const;

/** RuleType — discriminator union derived from the runtime list above. */
export type RuleType = (typeof RULE_TYPES)[number];

/**
 * Severity — fired-alert severity chosen per rule.
 *
 * WHY lowercase on the wire: the backend `AlertRuleCreateRequest.severity`
 * validates against `low|medium|high|critical` (lowercase). The rest of the UI
 * uses uppercase `AlertSeverity` for display; we keep this module aligned with
 * the backend wire shape and uppercase only at render time.
 */
export type RuleSeverity = "low" | "medium" | "high" | "critical";

/** Cross operator shared by price + fundamental rules. */
export type CrossOperator = "above" | "below";

/**
 * News-count windows (v1 source coverage) — mirrors backend `NEWS_COUNT_WINDOWS`.
 * `7d` is the S6 rollup window; `1h|6h|24h` map to the trending endpoint.
 */
export const NEWS_COUNT_WINDOWS = ["1h", "6h", "24h", "7d"] as const;
export type NewsCountWindow = (typeof NEWS_COUNT_WINDOWS)[number];

/**
 * News-momentum windows — mirrors backend `NEWS_MOMENTUM_WINDOW_HOURS`. These
 * are the only windows the S6 trending endpoint supports, so the picker is a
 * closed set (a free-text number would 422 at the boundary).
 */
export const NEWS_MOMENTUM_WINDOW_HOURS = [24, 72, 168] as const;
export type NewsMomentumWindowHours = (typeof NEWS_MOMENTUM_WINDOW_HOURS)[number];

// ── Condition value objects (discriminated by rule_type at the rule level) ──────
//
// NOTE: unlike the rule itself, the condition object does NOT carry `rule_type`
// inside it — the discriminator lives on the rule row (`AlertRule.rule_type`).
// We therefore model each condition as its own interface and a `RuleCondition`
// union; the editor components produce the matching shape for the chosen type.

/** PRICE_CROSS condition — `{instrument_id, operator, value>0}`. */
export interface PriceCrossCondition {
  instrument_id: string;
  operator: CrossOperator;
  value: number; // > 0 (enforced backend-side)
}

/** NEWS_COUNT condition — `{entity_id, window, threshold>=1, keyword?}`. */
export interface NewsCountCondition {
  entity_id: string;
  window: NewsCountWindow;
  threshold: number; // >= 1
  keyword?: string;
}

/** NEWS_MOMENTUM condition — `{entity_id, window_hours, delta_pct, min_count>=1}`. */
export interface NewsMomentumCondition {
  entity_id: string;
  window_hours: NewsMomentumWindowHours;
  delta_pct: number;
  min_count: number; // >= 1, default 2
}

/**
 * KG_CONNECTION condition — `{source_entity_id, target_entity_id, max_hops 1..3, relation_type?}`.
 * `source_entity_id` must differ from `target_entity_id` (the editor enforces this
 * before allowing Save; the backend re-checks).
 */
export interface KgConnectionCondition {
  source_entity_id: string;
  target_entity_id: string;
  max_hops: number; // 1..3, default 3
  relation_type?: string;
}

/** FUNDAMENTAL_CROSS condition — `{instrument_id, metric_key, operator, value}`. */
export interface FundamentalCrossCondition {
  instrument_id: string;
  metric_key: string;
  operator: CrossOperator;
  value: number;
}

/** Union of all condition shapes — the wizard narrows by the chosen `rule_type`. */
export type RuleCondition =
  | PriceCrossCondition
  | NewsCountCondition
  | NewsMomentumCondition
  | KgConnectionCondition
  | FundamentalCrossCondition;

// ── Request / response shapes (mirror services/alert/.../api/schemas.py) ────────

/**
 * AlertRule — full stored representation returned by the backend
 * (`AlertRuleResponse`). `condition` is typed loosely here as `RuleCondition`;
 * callers narrow on `rule_type` before reading fields.
 */
export interface AlertRule {
  rule_id: string;
  tenant_id: string;
  user_id: string;
  rule_type: RuleType;
  name: string;
  /** instrument_id (price/fundamental) or entity_id (news/momentum); null for KG. */
  entity_id: string | null;
  node_a_entity_id: string | null;
  node_b_entity_id: string | null;
  condition: RuleCondition;
  severity: RuleSeverity;
  enabled: boolean;
  cooldown_seconds: number;
  notify_in_app: boolean;
  notify_email: boolean;
  /** Edge memory (was_above / last_count / connected / last_fired_at …) or null. */
  last_state: Record<string, unknown> | null;
  created_at: string; // ISO-8601 UTC
  updated_at: string; // ISO-8601 UTC
}

/** Body for POST /v1/alert-rules. `tenant_id`/`user_id` come from the JWT. */
export interface CreateAlertRuleInput {
  rule_type: RuleType;
  name?: string;
  condition: RuleCondition;
  severity?: RuleSeverity; // default "medium"
  enabled?: boolean; // default true
  cooldown_seconds?: number; // per-type default if omitted
  notify_in_app?: boolean; // default true
  notify_email?: boolean; // default false
}

/**
 * Body for PATCH /v1/alert-rules/{id}. All fields optional; `rule_type` is
 * immutable so it is intentionally absent. Changing `condition` re-arms the rule
 * (backend resets `last_state`).
 */
export interface UpdateAlertRuleInput {
  name?: string;
  condition?: RuleCondition;
  severity?: RuleSeverity;
  enabled?: boolean;
  cooldown_seconds?: number;
  notify_in_app?: boolean;
  notify_email?: boolean;
}

/** Query filters for GET /v1/alert-rules (list). */
export interface ListAlertRulesParams {
  enabled?: boolean;
  rule_type?: RuleType;
  limit?: number;
  offset?: number;
}

/** Paginated list response (`AlertRuleListResponse`). */
export interface AlertRuleListResponse {
  items: AlertRule[];
  total: number;
}

// ── Gateway factory (spread into createGateway in lib/gateway.ts) ───────────────

/**
 * createAlertRulesApi — returns the alert-rules CRUD methods bound to a token.
 *
 * Mirrors the other `createXApi(t)` factories so it can be spread into the
 * gateway shim. Each method is a thin `apiFetch` wrapper — no transformation,
 * because the backend response already matches our `AlertRule` shape 1:1.
 */
export function createAlertRulesApi(t: string | undefined) {
  return {
    /** List the caller's standing rules (filtered + paginated server-side). */
    listAlertRules(params: ListAlertRulesParams = {}): Promise<AlertRuleListResponse> {
      // Build the query string from only the set filters (omit undefined so an
      // unset filter is truly "any" rather than `?enabled=undefined`).
      const qs = new URLSearchParams();
      if (params.enabled !== undefined) qs.set("enabled", String(params.enabled));
      if (params.rule_type) qs.set("rule_type", params.rule_type);
      if (params.limit !== undefined) qs.set("limit", String(params.limit));
      if (params.offset !== undefined) qs.set("offset", String(params.offset));
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return apiFetch<AlertRuleListResponse>(`/v1/alert-rules${suffix}`, { token: t });
    },

    /** Fetch a single rule by id (404 → GatewayError if not owned by caller). */
    getAlertRule(ruleId: string): Promise<AlertRule> {
      return apiFetch<AlertRule>(`/v1/alert-rules/${encodeURIComponent(ruleId)}`, {
        token: t,
      });
    },

    /** Create a standing rule → returns the persisted row (201). */
    createAlertRule(input: CreateAlertRuleInput): Promise<AlertRule> {
      return apiFetch<AlertRule>(`/v1/alert-rules`, {
        method: "POST",
        body: input,
        token: t,
      });
    },

    /** Partial-update a rule → returns the updated row (200). */
    updateAlertRule(ruleId: string, patch: UpdateAlertRuleInput): Promise<AlertRule> {
      return apiFetch<AlertRule>(`/v1/alert-rules/${encodeURIComponent(ruleId)}`, {
        method: "PATCH",
        body: patch,
        token: t,
      });
    },

    /** Delete a rule (204 No Content → resolves undefined via apiFetch). */
    deleteAlertRule(ruleId: string): Promise<void> {
      return apiFetch<void>(`/v1/alert-rules/${encodeURIComponent(ruleId)}`, {
        method: "DELETE",
        token: t,
      });
    },
  };
}
