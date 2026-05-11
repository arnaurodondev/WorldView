# Fix-Bug Report: Platform Stability Follow-ups

**Date**: 2026-04-30
**Skill**: fix-bug
**Scope**: F-101, F-102, F-103, F-104 from `docs/audits/2026-04-30-investigation-platform-stability-followups.md`
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: **SHIP** — all 4 fixes verified at runtime against live containers

---

## Summary

| ID | Severity | Service | Fix | Live verification |
|----|----------|---------|-----|-------------------|
| F-101 | CRITICAL | nlp-pipeline-price-impact-worker | `MarketDataClient` mints internal JWT via S9 `/v1/auth/dev-login` and injects `X-Internal-JWT` header | Zero 401s in 90s window (was 100%) |
| F-102 | MAJOR | nlp-pipeline + alert watchlist consumers | Confluent magic-byte detection + Schema Registry id lookup (per-event-type schemas) | 14 `watchlist_entity_added` events processed; zero new DLQs |
| F-103 | MAJOR | nlp-pipeline-unresolved-resolution-worker | Tolerant `_extract_json_object` helper + raw-response logging in parse-failure branches | error rate 1.4% (2/138, was 100% — 43/43) |
| F-104 | MINOR | content-ingestion-worker | New `PremiumEndpointError` raised on 403 + `_is_retryable` predicate that short-circuits the retry loop | Single `info` log per symbol with `reason=premium_endpoint`; zero `adapter_retry` warnings |

Total tests passing: **content-ingestion 587, nlp-pipeline 589, alert 431** (1,607 unit tests). Ruff clean across all 3 services.

---

## Per-fix detail

### F-101 — Internal JWT signing for nlp-pipeline → market-data calls

**Files changed**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/http/market_data_client.py` — added token bootstrap via `POST /v1/auth/dev-login`, in-process cache with 240s TTL (S9 mints 5-minute tokens), `X-Internal-JWT` header injection per request
- `services/nlp-pipeline/src/nlp_pipeline/workers/price_impact_labelling_worker.py` — pass `api_gateway_url=settings.api_gateway_url` to `MarketDataClient`

**Why dev-login over private-key signer**: dev-login produces a real RS256 JWT signed by the gateway with the registered `kid` — receivers verify it via JWKS just as for any user request. No new secret distribution needed; works in dev today. For prod the same pattern with a system-scoped `/internal/auth/system-token` endpoint is the natural follow-up.

**Verification (live)**:
```
docker logs --since 60s worldview-nlp-pipeline-price-impact-worker-1 | grep -c "401 Unauthorized" → 0
docker logs --since 90s ... | grep "HTTP/1.1 (200|404)" → many
```

### F-102 — BP-122 watchlist consumer fix (S6 + S10) with Schema Registry lookup

**Files changed**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/watchlist_consumer.py`
- `services/alert/src/alert/infrastructure/messaging/consumers/watchlist_consumer.py`

**Initial fix (mirror article_consumer)** dead-lettered with a NEW error: `Expected -60 bytes, read 232`. Investigation showed the producer publishes **per-event-type schemas** (`WatchlistItemAdded` / `WatchlistItemDeleted` — schema_ids 19/20 in dev), not the unified `WatchlistUpdatedEnvelope` (schema_id 17). A single hardcoded `.avsc` therefore can't decode both event types.

**Final fix**: parse the 4-byte `schema_id` from the wire-format header, look up the schema from Schema Registry (`GET /schemas/ids/{id}`), cache it in-process, then `deserialize_avro` against the resolved schema. This is robust to producer schema evolution and per-event-type schemas.

**Verification (live)**:
```
docker logs --since 90s worldview-nlp-pipeline-watchlist-consumer-1 | grep -c "watchlist_entity_added" → 14
docker logs --since 90s ... | grep -c "dead_letter" → 0
```

### F-103 — UnresolvedResolutionWorker JSON resilience

**Files changed**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py`

**Changes**:
1. New `_extract_json_object(raw)` helper at module level — tries `json.loads`, then strips ```json fences```, then extracts the first balanced `{...}` substring. Tolerant to the most common LLM-noise patterns.
2. Both Ollama and DeepInfra parse-failure except blocks now log `raw=raw[:500]` and the underlying exception message, so silent failures become diagnosable.
3. Replaced bare `json.loads(raw)` with `_extract_json_object(raw)` at both call sites.

**Verification (live)**: a cycle ran shortly after restart with `processed=138, entity_created=49, noise=87, errors=2`. **error rate went from 100% (43/43) to 1.4% (2/138)** and the remaining errors will now show their raw response in logs the next time they fire.

### F-104 — Finnhub 403 short-circuit + non-retryable error allowlist

**Files changed**:
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/client.py` — new `class PremiumEndpointError(AdapterError)`; `_check_response` raises it on 403
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/adapter.py` — catches `PremiumEndpointError` separately and logs once at info level
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/base.py` — new module-level `_is_retryable(exc)` predicate; the retry loop re-raises immediately when it returns False

**Verification (live)**:
```
docker logs --since 5m worldview-content-ingestion-worker-1 | grep "finnhub_transcripts_unavailable"
→ 8 lines info "premium_endpoint" — one per symbol
docker logs --since 5m ... | grep "adapter_retry.*finnhub"
→ 0 (was 8 retries × 3 attempts × 7s/cycle = 56s wasted)
```

---

## Acknowledged out-of-scope findings

The price-impact worker now successfully authenticates against market-data; however, the OHLCV calls return **HTTP 404** for the requested dates because S3's OHLCV table is sparse. This is an **ingestion-data availability** issue, not a PLAN-0055 or fix-bug concern. Until S3 is backfilled with the relevant date ranges, `article_impact_windows` will remain empty.

---

## Cross-cutting observations carried into compounding updates

1. **Per-role docker images need explicit rebuild.** Each Compose worker (price-impact, watchlist-consumer, etc.) has its own image. `docker compose build <api-only>` skips them. The implementation team learned this twice during this fix cycle. Worth adding to `docs/workflows/local-dev.md`.
2. **Producer per-event-type schemas vs. consumer single-schema assumption** is a class of bug; Schema Registry id lookup is the durable fix.
3. **Retry-on-permanent-error** generalises to a `RetryConfig.retryable_status` allowlist (308, 408, 429, 500, 502, 503, 504); current fix is class-name-based but functional.
4. **Worker logs were write-only diagnostic graveyards** — F-103 surfaced 100% failure rate but discarded the only piece of evidence (the raw LLM response). The fix turned the worker from "always green / always wrong" into a self-diagnosable one.

---

## Verdict

**SHIP**. All 4 BLOCKING/CRITICAL/MAJOR/MINOR findings closed at the source code level AND verified live against running containers. Unit suites green across 3 services. Ruff clean. Acknowledged out-of-scope: market-data backfill (separate ingestion concern, not platform-stability).
