# ADR 0007 — `portfolio.holding.changed.v1` emission gated behind feature flag

- **Status**: Accepted (2026-06-10)
- **Plan**: PLAN-0109 Sub-Plan G
- **Owner**: portfolio service

## Context

The portfolio service has emitted `portfolio.holding.changed.v1` outbox events from
`UpsertHoldingsFromSnapshotUseCase` since PLAN-0046 (BP-264). The 2026-06-09 platform
audit (`docs/plans/0109-platform-remediation-plan.md`) found that:

- No service subscribes to the topic. Downstream consumers (alert, intelligence,
  rag-chat) all read the `holdings` table directly or via S9 — that table is
  the canonical source of truth for holding state.
- 14 events sat in the portfolio outbox `dead_letter` table for weeks with zero
  downstream impact (no replay ever reduced the count, no alert ever fired).
- Removing the event entirely would require deleting the domain event class,
  Avro schema, serializer registration, and topic constant — a non-trivial
  contract change that we want to keep available for the planned alert
  position-closure rule.

## Decision

Gate emission behind a default-`false` settings flag
`PORTFOLIO_EMIT_HOLDING_CHANGED` (Pydantic field `emit_holding_changed_events`).

- The use case still computes the upsert/delete diff and mutates the `holdings`
  table when the flag is off — only the outbox-row write is skipped.
- The domain event class, Avro schema, `EVENT_TOPIC_MAP` entry, and serializer
  registration are intentionally retained. Flipping the flag re-enables
  emission with zero code change.

## Consequences

- Zero downstream consumers wait on the topic today; the 14 dead-letter rows
  are dropped (replay would be pointless work — the holdings table is
  authoritative).
- When the alert service's position-closure rule lands we flip
  `PORTFOLIO_EMIT_HOLDING_CHANGED=true` in the production env and the rule
  starts receiving events on its first sync cycle. No portfolio redeploy
  required beyond the env-var change.
- The `holding.changed` topic continues to be reserved in `EVENT_TOPIC_MAP`
  and the Avro schema registry, so external integrations cannot accidentally
  reuse the name.
- Unit tests cover both states (flag off → no event, flag on → one event per
  closed position).

## Related

- `docs/plans/0109-platform-remediation-plan.md` Sub-Plan G
- `docs/services/portfolio.md` — "holding.changed emission (gated)" section
- BP-264 (the bug the original emission helped diagnose)
