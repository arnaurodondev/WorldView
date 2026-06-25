/**
 * lib/api/useAlertRules.ts — TanStack Query hooks for standing alert rules
 * (PLAN-0113 Wave 4, T-4-01).
 *
 * WHY A SEPARATE HOOKS FILE (not folded into `alertRules.ts`):
 * `alertRules.ts` is a PURE gateway factory (`createAlertRulesApi`) that gets
 * spread into `lib/gateway.ts`. If we imported React / TanStack hooks there, the
 * gateway shim would pull React into every non-React import site. Keeping the
 * hooks here (like the rest of the React-aware data layer) preserves that split:
 *   - `alertRules.ts`  → types + raw fetch methods (gateway-spread, React-free)
 *   - `useAlertRules.ts` → the `use*` hooks components actually call
 *
 * All hooks lean on `useAuthedQuery` / `useAuthedMutation` (lib/api-client.tsx)
 * which inject the memoised gateway and gate queries on auth — so we never fire
 * a rules request during the signed-out window (the classic 401 stampede).
 *
 * CACHE INVALIDATION: every mutation invalidates the `["alerts","rules"]` prefix
 * (`qk.alerts.rules()`), which cascades to the filtered list + per-rule detail
 * keys (TanStack partial-match), so the manager list refreshes after any write.
 */

"use client";
// WHY "use client": these are React hooks (TanStack Query) — browser-only.

import { useQueryClient } from "@tanstack/react-query";
import { useAuthedMutation, useAuthedQuery } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { DEFAULT_STALE } from "./_client";
import type {
  AlertRule,
  AlertRuleListResponse,
  CreateAlertRuleInput,
  ListAlertRulesParams,
  UpdateAlertRuleInput,
} from "./alertRules";

// ── Read hooks ──────────────────────────────────────────────────────────────

/**
 * useAlertRules — list the caller's standing rules (optionally filtered).
 *
 * WHY DEFAULT_STALE.alerts (15s): rule definitions change rarely, but the
 * `enabled` flag + `last_state.last_fired_at` shift when a rule fires or is
 * paused, so a short-ish window keeps the manager list reasonably fresh without
 * hammering S9. Manual mutations invalidate immediately regardless.
 */
export function useAlertRules(params: ListAlertRulesParams = {}) {
  return useAuthedQuery<AlertRuleListResponse>({
    // Filters are part of the cache identity so different filter combos don't
    // clobber each other (TanStack treats the params object as part of the key).
    queryKey: qk.alerts.rulesList(params as Readonly<Record<string, unknown>>),
    queryFn: (gw) => gw.listAlertRules(params),
    staleTime: DEFAULT_STALE.alerts,
  });
}

/**
 * useAlertRule — fetch a single rule by id.
 *
 * `enabled` is gated on a non-empty id so we never call `/alert-rules/` with a
 * blank segment (the gateway's malformed-path guard would reject it anyway, but
 * gating avoids the wasted render + error state).
 */
export function useAlertRule(ruleId: string | null) {
  return useAuthedQuery<AlertRule>({
    queryKey: qk.alerts.rule(ruleId ?? ""),
    queryFn: (gw) => gw.getAlertRule(ruleId as string),
    enabled: Boolean(ruleId),
    staleTime: DEFAULT_STALE.alerts,
  });
}

// ── Write hooks ─────────────────────────────────────────────────────────────

/**
 * useCreateAlertRule — POST a new standing rule, then refresh the rules cache.
 *
 * WHY invalidate the whole rules prefix (not just the unfiltered list): the new
 * rule may match several filtered views (e.g. `?enabled=true`, `?rule_type=…`).
 * Invalidating `qk.alerts.rules()` re-fetches every rules query at once.
 */
export function useCreateAlertRule() {
  const qc = useQueryClient();
  return useAuthedMutation<AlertRule, Error, CreateAlertRuleInput>({
    mutationFn: (gw, input) => gw.createAlertRule(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.alerts.rules() });
    },
  });
}

/**
 * useUpdateAlertRule — PATCH an existing rule (partial). Used for edit, pause /
 * unpause (enabled toggle), and condition re-arm. Invalidates both the rules
 * list prefix and the specific rule's detail key.
 */
export function useUpdateAlertRule() {
  const qc = useQueryClient();
  return useAuthedMutation<
    AlertRule,
    Error,
    { ruleId: string; patch: UpdateAlertRuleInput }
  >({
    mutationFn: (gw, { ruleId, patch }) => gw.updateAlertRule(ruleId, patch),
    onSuccess: (_data, { ruleId }) => {
      void qc.invalidateQueries({ queryKey: qk.alerts.rules() });
      void qc.invalidateQueries({ queryKey: qk.alerts.rule(ruleId) });
    },
  });
}

/**
 * useDeleteAlertRule — DELETE a rule (204). Invalidates the rules cache so the
 * removed row disappears from every filtered list.
 */
export function useDeleteAlertRule() {
  const qc = useQueryClient();
  return useAuthedMutation<void, Error, string>({
    mutationFn: (gw, ruleId) => gw.deleteAlertRule(ruleId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.alerts.rules() });
    },
  });
}
