# Internal-JWT `aud`-claim gap — fix + verification-enable rollout

**Date:** 2026-07-01
**Type:** Security / platform hardening (DEF-002)
**Status:** Claims fix landed (ADDITIVE). Verification-enable is the NEXT step (NOT done here).

---

## The gap (confirmed)

Internal service-to-service calls use an RS256 "internal JWT" (S9 signs, backends
verify via `/internal/jwks`) sent as header `X-Internal-JWT`. The shared
`InternalJWTMiddleware` (`libs/observability/src/observability/internal_jwt.py`)
**requires** the `aud` claim and validates it:

```python
options={"require": ["sub", "tenant_id", "role", "exp", "iss", "aud"]}
issuer="worldview-gateway"
audience="worldview-internal"
```

Only `services/api-gateway/.../jwt_utils.py` minted tokens WITH `aud`. **11 other
minters omitted `aud`** (and most omitted `jti`). They "worked" only because their
target services run `skip_verification=True`. The moment real verification is
enabled on any target, every one of those minters would produce 401s.

## The fix (this change — ADDITIVE, low-risk)

A single shared minter now guarantees correct claims:

- `observability.internal_jwt.build_internal_jwt_claims(...)` — builds the
  canonical payload: `iss=worldview-gateway`, `aud=worldview-internal`, `sub`,
  `tenant_id`, `role`, `jti` (UUIDv7 via `common.ids.new_uuid7`), UTC `iat`/`exp`
  (via `common.time.utc_now`), plus optional `user_id`/`service_name`/`scope`.
- `observability.internal_jwt.mint_internal_jwt(...)` — builds the claims and
  signs (RS256 when a private-key PEM is supplied, else HS256 dev fallback).

All 11 minters now delegate to this helper, so every internal JWT is
**correct-by-construction**. Signing keys / dev secrets remain per-service
(unchanged) — this PR fixes CLAIMS, not key management.

**No `skip_verification` flag was changed and no middleware verification was
enabled anywhere.** A round-trip unit test proves a minted token PASSES full
`InternalJWTMiddleware` verification, so the future enable is safe.

### Minters updated

| # | Service | File | Function | sub |
|---|---------|------|----------|-----|
| 1 | market-data | `infrastructure/clients/intelligence_clients.py` | `_make_internal_jwt` | `system:intelligence-rollup-worker` |
| 2 | market-ingestion | `infrastructure/workers/fundamentals_refresh_worker.py` | `_sign_internal_jwt` | `system:fundamentals-refresh-worker` |
| 3 | market-ingestion | `infrastructure/workers/insider_universe_loader.py` | `_sign_internal_jwt` | `system:insider-universe-loader` |
| 4 | market-ingestion | `infrastructure/workers/instrument_policy_sync_worker.py` | `_sign_internal_jwt` | `system:instrument-policy-sync-worker` |
| 5 | content-ingestion | `infrastructure/workers/ticker_news_sync_worker.py` | `_sign_internal_jwt` | `system:ticker-news-sync-worker` |
| 6 | knowledge-graph | `infrastructure/scheduler/scheduler.py` | `build_market_data_signer._sign` | `system:kg-structured-enrichment` |
| 7 | knowledge-graph | `infrastructure/workers/fundamentals_refresh.py` | `_system_jwt_headers` | `system:kg-fundamentals-refresh` |
| 8 | portfolio | `workers/portfolio_snapshot_worker.py` | `_system_jwt_headers` | `system:portfolio-snapshot` |
| 9 | portfolio | `workers/brokerage_sync_worker.py` | `_system_jwt_headers` | `system:brokerage-sync` |
| 10 | portfolio | `infrastructure/market_data/current_price_client.py` | `_system_jwt_headers` | `system:portfolio-current-price-client` |
| 11 | portfolio | `infrastructure/market_data/recent_prices_client.py` | `_system_jwt_headers` | `system:portfolio-recent-prices-client` |

---

## NEXT STEP — service-by-service verification-enable rollout (NOT in this PR)

Now that every minter emits `aud` + `jti`, `skip_verification` can be turned OFF
one target service at a time. Do this deliberately and observably:

**Pre-flight (once):**
1. Confirm S9 `/internal/jwks` is reachable from every backend and the current
   signing `kid` is present (backends resolve keys by `kid`).
2. Ensure Valkey is reachable per target (JTI replay check fails-open if not, so
   this is not strictly blocking, but you want the replay defense active).

**Per target service (repeat, one at a time):**
1. Pick a low-traffic target first. Recommended order (fewest inbound internal
   callers → most): **content-store (S6) → knowledge-graph (S7) → alert (S10) →
   rag-chat (S8) → market-data (S3)**. Market-data last: it is the busiest
   internal callee (fundamentals/insider/policy/price clients + KG signer all
   call it).
2. Set that service's `*_INTERNAL_JWT_SKIP_VERIFICATION=false` (leave every
   OTHER service on `true`).
3. Redeploy the single service. Watch for:
   - `internal_jwt_public_key_loaded` at startup (JWKS fetch OK).
   - Any spike in 401s / `internal_jwt_invalid` / `internal_jwt_unknown_kid` /
     `jti_replay_detected` logs, and any downstream worker error logs
     (`*_jwt_sign_failed`, endpoint 401s).
4. Exercise the real callers (trigger the relevant workers / nightly rollups /
   price fetches) and confirm 200s.
5. If clean for a full traffic cycle (≥ the slowest caller's interval, e.g. the
   fundamentals worker's 2–6 h loop), keep it. If 401s appear, flip back to
   `true`, capture the offending `sub`/`kid`, fix, and retry.
6. Only then move to the next service.

**Rollback:** each step is a single env-var flip back to
`skip_verification=true` + redeploy of that one service. No code change needed.

**Done when:** all internal callees run `skip_verification=false` and no
`internal_jwt_*` rejection logs are observed across a full traffic cycle.
