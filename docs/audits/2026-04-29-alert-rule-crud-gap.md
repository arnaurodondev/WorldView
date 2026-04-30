# Backend Gap — Alert Rule CRUD endpoints (PLAN-0051 Wave D)

**Date**: 2026-04-29
**Author**: PLAN-0051 Wave D frontend implementation
**Status**: open — frontend ships with localStorage-only fallback

## Summary

The frontend Rule Manager dialog (`components/alerts/RuleManagerDialog.tsx`) and
`lib/alerts/rules.ts` helpers were built in PLAN-0051 Wave D to provide full CRUD
(list / create / update / delete / toggle-enabled) over user-defined alert rules.
There is **no S10 backend endpoint** for alert rules at the time of writing —
the helpers therefore persist exclusively to `localStorage` under the
`worldview-alert-rules` key. Every rule returned from the helpers is tagged with
`_localOnly: true` so the UI can render a small "(local only)" pill making it
obvious to the user that the rule will not sync across devices.

## What's missing

| Endpoint | Purpose | Caller |
|---|---|---|
| `GET    /v1/alerts/rules`           | list all rules for the authenticated user | `listAlertRules()` |
| `POST   /v1/alerts/rules`           | create a new rule                          | `createAlertRule(input)` |
| `PATCH  /v1/alerts/rules/{rule_id}` | update an existing rule                    | `updateAlertRule(id, patch)` |
| `DELETE /v1/alerts/rules/{rule_id}` | delete a rule                              | `deleteAlertRule(id)` |

Backend persistence model (suggested):

```sql
CREATE TABLE alert_rules (
    rule_id            UUID PRIMARY KEY,
    user_id            UUID NOT NULL,
    tenant_id          UUID NOT NULL,
    name               TEXT NOT NULL,
    rule_type          TEXT NOT NULL,  -- price_threshold | volume_spike | news_signal | portfolio_risk
    entity_search      TEXT,
    condition_expr     TEXT NOT NULL,
    enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    notify_in_app      BOOLEAN NOT NULL DEFAULT TRUE,
    notify_email       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_alert_rules_user ON alert_rules (user_id);
```

The condition expression is currently free-text on the client — backend should
either keep it free-text (analyst-style) or define a structured
`{field, op, value}` payload and transform it before fanout.

## What ships in the meantime

- `lib/alerts/rules.ts` exposes async helpers that match the eventual remote
  contract. Swapping to a real fetch is a one-file edit.
- Every rule is tagged `_localOnly: true`. UI displays a small badge.
- `components/alerts/AlertRuleBuilder.tsx` (legacy quick-add form) continues
  to write through the same storage key, so existing rules carry over.
- The `RuleManagerDialog` `prefillEntity` prop pre-fills the entity field
  when launched from "Set alert rule" on the AlertDetailSheet — keeping the
  contract uniform across the eventual backend cut-over.

## Migration plan when the endpoint ships

1. Replace `lib/alerts/rules.ts` body to call `gateway.listAlertRules()` etc.
2. Drop the `_localOnly` tag (or keep it tied to `IF rule.id starts with rule-`,
   indicating an unmigrated row).
3. Add a one-shot migration: on first authenticated load, POST every
   `_localOnly` rule to the backend and clear localStorage on success.
4. Update `docs/apps/worldview-web.md` Alerts section.
