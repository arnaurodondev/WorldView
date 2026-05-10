# Cash / Buying Power truthful state — missing integration (PLAN-0088 P0-11)

**Date:** 2026-05-10
**Plan:** PLAN-0088 demo stabilization, P0-11
**Component:** `apps/worldview-web/components/portfolio/CashRow.tsx`
**Backend:** `services/portfolio/src/portfolio/application/use_cases/get_exposure.py`

## Symptom

The portfolio Holdings tab Cash row showed `$0.00` for Cash, with em-dash
placeholders for Buying Power and Sweep Rate. The Cash value implied
"we checked your broker — you have zero dollars in cash". This is
misleading: no broker balance was ever queried.

## Root cause

`GetExposureUseCase.execute()` hard-codes `cash = Decimal(0)` in v1. The
SnapTrade integration imports transactions and resolves holdings, but it
**does not** fetch broker cash balances or buying power. The DB has no
`balances` table; no balance topic flows through Kafka.

The frontend `CashRow` component then took `data?.cash ?? 0` and
ran it through `formatPrice(...)` → `"$0.00"`.

## Fix landed in this commit (frontend-only)

`CashRow.tsx` now treats `cash === 0` as "unknown / not yet wired" and
renders an em-dash with a hover tooltip:

> "Cash and buying power are not synced yet. Connect a brokerage in
> Settings to enable live balances."

This is the truthful state — the platform openly admits it does not
know the cash balance, instead of fabricating $0.00.

The fix uses no backend contract change. The moment the backend starts
returning a non-zero `cash`, the live value lights up automatically.

## What is missing for full truthful balances

To replace the em-dash with real numbers, the following pieces are
required (NOT in scope for the demo):

1. **SnapTrade balance polling adapter.** A new worker similar to
   `BrokerageTransactionSyncWorker` that calls the SnapTrade
   `/accounts/{id}/balances` endpoint and publishes a
   `brokerage.balance.snapshot.v1` event.
2. **Topic + Avro schema:** `infra/kafka/schemas/brokerage_balance_snapshot.avsc`
   with fields `(account_id, cash, buying_power, currency, as_of)`.
3. **`portfolio_balances` table** (DDL migration) keyed by
   `(portfolio_id, currency, as_of)`.
4. **`GetExposureUseCase` change** to read the latest balance row per
   currency and surface `cash` (and a new `buying_power` field) in the
   response.
5. **Optional `balance_status` envelope** (`unavailable_no_broker_sync`
   / `stale` / `live`) so the UI can differentiate "no broker connected"
   from "broker connected but balances stale > 24h".

## Why we did not implement (1)–(5) in this session

* The PLAN-0088 P0-11 constraint: "If real SnapTrade balances cannot be
  safely retrieved in this session, implement a truthful unavailable /
  sync-pending state and document the exact missing integration." The
  fix above honours that constraint.
* The full integration crosses a Kafka topic, a DB migration, and a use
  case — a normal `/plan`-sized wave, not a demo P0.

## Validation

* Frontend unit: `cashKnown` flag flips correctly for `cash=0`,
  `cash=null`, `cash=12345.67`.
* Manual: visit `/portfolio` with the demo seed (cash always 0 in v1)
  and verify the Cash cell shows "—" with the tooltip on hover.
