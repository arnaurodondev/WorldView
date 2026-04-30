# Investigation: Platform Stability Follow-ups (PLAN-0055 iter-4 unfixed findings)

**Date**: 2026-04-30
**Investigator**: `/investigate` skill (delegated to two parallel root-cause agents)
**Severity**: 1 CRITICAL + 2 MAJOR + 1 MINOR
**Status**: All four root causes identified; fixes scoped (not yet applied)

## Scope

The PLAN-0055 iter-4 runtime QA pass surfaced four unfixed runtime issues that are **not caused by PLAN-0055** but are causing platform instability. This investigation produces deep root-cause analyses and fix recommendations for each.

| ID | Severity | Service | One-liner |
|----|----------|---------|-----------|
| F-101 | CRITICAL | nlp-pipeline-price-impact-worker | Every market-data OHLCV call → 401 Unauthorized; AIW writes 0 rows |
| F-102 | MAJOR | nlp-pipeline-watchlist-consumer | Every Avro message dead-letters with utf-32-be codec error |
| F-103 | MAJOR | nlp-pipeline-unresolved-resolution-worker | 100% failure rate (43/43); silent JSON parse swallows raw response |
| F-104 | MINOR | content-ingestion-worker | Finnhub transcripts 100% retry-exhaustion (HTTP 403 — premium endpoint) |

The acknowledged PLAN-0055 deferrals (C2 replay-worker stub, C3/C4 news read path on legacy column, M1 unemitted metrics, M3 docs gap, C5 partial test coverage) are scope choices and are **not** investigated here — they have explicit owners in the iter-3/iter-4 reports.

---

## F-101 — Price-impact worker → market-data 401 Unauthorized

### Root cause: missing internal-JWT injection in `MarketDataClient`

**What**: `MarketDataClient` issues `GET http://market-data:8003/api/v1/market-data/ohlcv/{symbol}` with no `headers=` kwarg. `services/nlp-pipeline/src/nlp_pipeline/infrastructure/http/market_data_client.py:66-67` constructs the request with a vanilla `httpx.AsyncClient` (built at `services/nlp-pipeline/src/nlp_pipeline/workers/price_impact_labelling_worker.py:64-65`).

**Why**: Receiver `services/market-data/src/market_data/infrastructure/middleware/internal_jwt.py:160-166` (PRD-0025) rejects every non-health request that lacks `X-Internal-JWT`. The path `/api/v1/market-data/ohlcv/...` is not in `_SKIP_PATHS`/`_SKIP_PREFIXES`. There is currently **no shared library** for backend-to-backend internal-JWT signing — only `services/api-gateway/src/api_gateway/jwt_utils.py` knows how to mint these tokens, and only the gateway has the private key mounted.

**When**: Always — every cycle, every symbol. PRD-0025 introduced `InternalJWTMiddleware` repo-wide; the price-impact worker was added later and silently became unauthorised on every call.

**Why 401 is silent**: `MarketDataClient.get_ohlcv` does NOT call `raise_for_status()` — non-200/non-404 status codes are downgraded to a `warning` log + `None` return. The labelling worker continues, computes 0 windows, exits the cycle "successfully". Classic "all-green / zero-output" pattern (BP-114 lineage).

### Impact
- **Immediate**: `article_impact_windows` stays empty → market_impact term in `display_relevance_score` is always 0 → news ranking is dominated by routing + LLM signals only.
- **Blast radius**: Every other worker that needs to call S2 internal endpoints will hit the same wall the moment it's added (KG scheduler, future batch jobs).
- **Data risk**: None — no corruption, just silent under-population.

### Fix Options

#### Option A — Route worker calls through S9 api-gateway as a proxy
Add public OHLCV routes to api-gateway and have the worker call those. The gateway mints the internal JWT itself.
- **Benefits**: One signer; no private-key sprawl; auditable via gateway access logs.
- **Drawbacks**: Extra network hop for batch traffic; gateway becomes bottleneck; need a public OHLCV route policy.
- **Effort**: Medium / **Risk**: Low–Medium

#### Option B — Shared `libs/common/auth/internal_jwt.py` signer + private-key mount in workers ★
Lift `issue_system_jwt` from `services/api-gateway/src/api_gateway/jwt_utils.py` into a shared lib. Mount the same RS256 private key (`INTERNAL_JWT_SIGNING_KEY` + `INTERNAL_JWT_KID`) into worker containers via a SOPS-encrypted secret. Pass an `httpx.Auth` callable into `MarketDataClient` that signs once and refreshes every ~50 s.
- **Benefits**: Zero extra hops; reusable for every future worker→service call; aligns with existing JWKS verifier; restores PRD-0025 invariant.
- **Drawbacks**: Spreads the gateway's private key into more containers (broader blast radius if compromised); requires secret-rotation discipline; CLAUDE.md note "key is S9 only" must be relaxed.
- **Effort**: Medium / **Risk**: Medium (key management)

#### Option C — Exempt `/internal/v1/...` from JWT middleware on receiver side
Duplicate OHLCV under `/internal/v1/market-data/ohlcv/{symbol}` and add `/internal/v1/` to `_SKIP_PREFIXES`; secure with network-policy / mTLS.
- **Benefits**: Simplest, no JWT plumbing in workers.
- **Drawbacks**: Silently breaks PRD-0025 invariant; two namespaces with divergent auth; bypasses tenant isolation; future operators may misuse the exemption.
- **Effort**: Low / **Risk**: HIGH (architecture regression)

### Recommendation: **Option B**
Restores PRD-0025; reusable across every worker that hits this wall (also unblocks F-103 next time it needs S2/S3); key sprawl is mitigable with rotation discipline. Not Option A because gateway-as-proxy adds latency on the hottest analytics path; not Option C because skipping middleware is the wrong direction long-term.

### Verification
```bash
docker logs worldview-nlp-pipeline-price-impact-worker-1 2>&1 | grep -c "HTTP/1.1 401"  # expect 0
docker exec worldview-postgres-1 psql -U postgres -d nlp_db -c \
  "SELECT count(*) FROM article_impact_windows WHERE created_at > now() - interval '30 minutes';"
# expect > 0
```

---

## F-102 — Watchlist consumer dead-letters every Avro message

### Root cause: BP-122 fix never reached this consumer

**What**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/watchlist_consumer.py:146-155` does:
```python
def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise  # Let the base class handle Avro path  ← LIE: base class has no Avro path
def get_schema_path(self, topic: str) -> str | None:
    return None
```

**Why**: Producer `services/portfolio/src/portfolio/infrastructure/messaging/serialization.py` correctly emits Confluent Avro framing (5-byte header `0x00` magic + 4-byte schema_id + Avro binary record). Hex dump confirms:
```
00 00 00 00 14  48 30 31 39 64 ...
```
Python's `json.loads` does RFC-4627 encoding sniffing: first 4 bytes `\x00\x00\x00\x00` → it picks **UTF-32-BE**. Bytes 4-7 contain `0x4830...` = 1,211,408,185 — out of `range(0x110000)` → exact error string in logs:
```
'utf-32-be' codec can't decode bytes in position 4-7: code point not in range(0x110000)
```
The `except: raise` looks like a fallback but is not — `BaseKafkaConsumer._handle_message` (`libs/messaging/src/messaging/kafka/consumer/base.py:303-316`) routes every deserialise exception straight to DLQ.

**Where else**: `services/alert/src/alert/infrastructure/messaging/consumers/watchlist_consumer.py:170-174` has the same latent bug (S10 just hasn't seen traffic yet).

Compare to the working sibling `article_consumer.py:710-722` which detects `\x00` magic and calls `deserialize_confluent_avro(schema_path, raw)` — canonical BP-122 fix.

### Impact
- **Immediate**: All watchlist updates fail to propagate to the NLP pipeline's `watched_entities` Valkey set → relevance scoring loses the personalisation boost for every user-added entity.
- **Blast radius**: Same code shape in S10 alert service — will fail identically on first traffic.

### Fix Options

#### Option A — Mirror the article_consumer fix on both watchlist consumers ★
Override `deserialize_value()` to detect `\x00` and delegate to `deserialize_confluent_avro(schema_path, raw)`; populate `get_schema_path()` to return `infra/kafka/schemas/portfolio.watchlist.updated.v1.avsc`.
- **Files**: `services/nlp-pipeline/.../watchlist_consumer.py`, `services/alert/.../watchlist_consumer.py`.
- **Effort**: 30 min / **Risk**: Very low — proven pattern; preserves JSON fallback for unit tests.

#### Option B — Lift BP-122 logic into `BaseKafkaConsumer`
Provide a default `deserialize_value` in the base class so subclasses opt in by implementing only `get_schema_path()`.
- **Files**: `libs/messaging/.../consumer/base.py` + audit of 9+ existing consumers.
- **Effort**: 2 h + regression tests / **Risk**: Medium — touches a hot path.

#### Option C — Switch portfolio watchlist topic to plain JSON
Stop using AvroSerializer for these two event types.
- **Drawbacks**: Breaks Schema Registry contract; precedent for partial-Avro topics; not recommended.

### Recommendation: **Option A now + Option B in next platform-hardening sprint**
A fastest path to green for both consumers; B is the durable cure (would prevent a third recurrence).

### Verification
```bash
# Add an item via S9: POST /v1/users/{id}/watchlists/{wid}/items
docker logs worldview-nlp-pipeline-watchlist-consumer-1 2>&1 | grep "watchlist_entity_added"  # expect ≥ 1
docker exec valkey redis-cli SISMEMBER nlp:v1:watched_entities <entity_id>  # expect 1
```

---

## F-103 — UnresolvedResolutionWorker 100% failure rate

### Root cause: silent JSON parse + brittle prompt template

**What**: DeepInfra returns HTTP 200 OK on every call (auth + network healthy). Failure is downstream at `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py:399-403`:
```python
raw = response.json()["choices"][0]["message"]["content"]
parsed = json.loads(raw)
```
The except block catches but does **not log `raw`** — only `mention_id`. So 43 identical "json_parse_failure" warnings, zero diagnostic evidence.

**Why**: Prompt template at line 58 inlines an invalid-JSON literal:
```
Respond with JSON: {"is_entity": true/false, "reason": "..."}.
```
`true/false` is **not** valid JSON. Meta-Llama-3.1-8B-Instruct often imitates the prompt closely and emits content like `"is_entity": true/false` (invalid) or wraps the JSON in prose / code fences. Even with `response_format: {"type": "json_object"}` the prompt's bad example dominates.

This is the same anti-pattern documented in user-memory entry `feedback_prompt_input_mismatch.md` (broke ~80% of S6 extraction output earlier).

### Impact
- **Immediate**: Provisional mentions never get resolved to canonicals → KG fan-out is starved → relations/edges remain sparse.
- **Blast radius**: Same `except Exception → return sentinel` shape in the Ollama path at lines 318-322.

### Fix Options

#### Option A — Tighten prompt + log raw response on parse failure ★
1. Replace `true/false` with `{"is_entity": true, "reason": "..."}`.
2. Add explicit "Output ONLY JSON, no prose, no code fences" instruction.
3. In the except block: log `raw[:500]` plus `exc_info=True`.
- **Effort**: Low / **Risk**: Low. **High probability of immediate fix.**

#### Option B — Switch to OpenAI tool-call / structured output
Use `tools=[{"type":"function","function":{"name":"classify_mention","parameters":{...}}}]` + `tool_choice={"type":"function","name":"classify_mention"}`; parse `tool_calls[0].function.arguments`.
- **Benefits**: Schema-validated; model can't return invalid types; reusable.
- **Drawbacks**: DeepInfra tool-call coverage per model is uneven; needs verification.
- **Effort**: Medium / **Risk**: Medium

#### Option C — Tolerant JSON extractor + single retry
Helper that strips ```json fences```, finds first balanced `{...}`, falls back to regex; on parse failure retry once with a stricter prompt.
- **Effort**: Medium / **Risk**: Low

### Recommendation: **Option A first, then A+C if A alone doesn't drop failure rate to <5%**
A is a 10-line change that closes the diagnostic blindspot and likely fixes the immediate symptom. C is the durable reusable fix worth doing once we have observability data. B is overkill for one classifier.

### Verification
```bash
docker logs worldview-nlp-pipeline-unresolved-resolution-worker-1 2>&1 | grep "unresolved_resolution_cycle_done"
# expect: errors << processed; entity_created + noise > 0
```

---

## F-104 — Finnhub transcripts 100% retry-exhaustion

### Root cause: HTTP 403 from a paid endpoint, retried as if transient

**What**: Live evidence shows every call returns HTTP 403 Forbidden:
```
adapter_retry attempt=1 context=finnhub:transcripts:AAPL error='Finnhub API error: HTTP 403'
…attempt=2…attempt=3 → finnhub_transcripts_unavailable error='All 3 retries exhausted'
```

**Why**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/client.py:88-105` calls `GET /stock/transcripts/list`, a **paid (Premium API)** endpoint on Finnhub. The deployed account is on the free tier, so the API token is rejected with 403. The same key works fine for `/company-news` (lots of `finnhub_dedup_skip` lines confirm).

Two compounding code-quality issues:
1. **403 is non-recoverable but treated as retryable.** `_check_response` raises generic `AdapterError` for any 4xx ≠ 429. `_retry_request` (`adapters/base.py:88-104`) retries on every `Exception` → 3 retries × (1+2+4)s × 8 symbols ≈ 56s wasted per cycle, 100% doomed.
2. **Comment vs behaviour drift.** `adapter.py:132` says "premium feature — gracefully skip if account lacks access" but the retry loop hammers anyway.

### Impact
- **Immediate**: 56s wasted per ingestion cycle; misleading `warning`-level retry log noise.
- **Functional**: Earnings transcripts are not ingested — affects nothing else (nothing downstream depends on them yet).

### Fix Options

#### Option A — Treat HTTP 403 as a non-retryable `PremiumEndpointError` ★
Introduce `class PremiumEndpointError(AdapterError)` in `client.py`; raise it from `_check_response` when status == 403. Add a per-call `is_retryable: Callable[[Exception], bool]` to the retry loop (or a class-level allowlist). `adapter.py` catches the new exception and logs once at info.
- **Files**: `finnhub/client.py`, `finnhub/adapter.py`, `adapters/base.py`.
- **Effort**: 1 h / **Risk**: Very low. Pattern reusable for 401/402/404.

#### Option B — Config flag `finnhub_transcripts_enabled: bool = False`
- **Drawback**: Silently hides the integration; on tier upgrade, operator must remember to flip.

#### Option C — Negotiate-and-cache: probe at startup, set `_transcripts_unavailable=True` for worker lifetime
- **Drawback**: Caches transient failures.

### Recommendation: **Option A**
Right behaviour for any non-retryable client error; doesn't add config surface; the new exception class makes the cause grep-able. Generalises into a `RetryConfig.retryable_status: set[int] = {408, 429, 500, 502, 503, 504}` allowlist that kills the pattern at the framework level (cross-cutting, see below).

### Verification
```bash
docker logs worldview-content-ingestion-worker-1 2>&1 | grep -A1 "transcripts_unavailable" | head -20
# expect: 8 lines info "premium endpoint requires Finnhub paid tier"; zero preceding adapter_retry warnings
```

---

## Cross-cutting Observations

1. **`except Exception → log warning → return sentinel` is endemic.** F-101, F-102 (BP-122 lineage), F-103 all share this anti-pattern: the warning records the *event* but discards the *evidence* (raw bytes, raw text, exc_info). Recommend a repo-wide grep for `except Exception` followed by `logger.warning(` without `exc_info=True` and a checklist entry to require evidence logging.

2. **Retry-on-permanent-error is a cross-cutting class of bug.** F-104 and any other 4xx-returning integration share it. A `RetryConfig.retryable_status: set[int] = {408, 429, 500, 502, 503, 504}` allowlist in `libs/common/retries.py` would kill the pattern at the framework level.

3. **No shared internal-auth client.** Every backend-to-backend HTTP path will hit F-101 the moment it tries to reach an InternalJWTMiddleware-guarded service. A `libs/common/auth/internal_jwt.py` module with `InternalJWTSigner` + `httpx`-friendly `auth=` callable would be the durable fix and unblocks future workers.

4. **BP-122 has slipped review at least twice** (S6 + S10 watchlist consumers). The "`# Let the base class handle Avro path`" comment on line 153 is a comment-vs-code lie. Recommend a `/docs-audit` rule that flags `json.loads(raw)` in any consumer's `deserialize_value` without a `\x00` magic-byte branch.

5. **Worker logs are write-only diagnostic graveyards.** Per-cycle aggregate counters but no per-call evidence. A `WORKER_DEBUG_RAW=1` env switch to flip on full evidence logging for one cycle without redeploying would be a 30-min investment that pays back the next time a parser fails silently.

---

## Recommended Fix Sequence

| Order | Fix | Effort | Why first |
|-------|-----|--------|-----------|
| 1 | F-103 Option A (prompt + raw logging) | Low | Single file, immediate signal-to-noise win, unblocks diagnosis on any future LLM regressions |
| 2 | F-102 Option A (BP-122 fix on both watchlist consumers) | Low | Fixes two services with one pattern |
| 3 | F-104 Option A (PremiumEndpointError + retry-allowlist) | Low | Saves 56s/cycle; reusable framework cleanup |
| 4 | F-101 Option B (shared internal-JWT signer) | Medium | Largest restoration of platform invariant; unblocks future workers |
| 5 | Cross-cutting #1 + #4 (review checklists, BUG_PATTERNS) | Low | Compounding step — prevents recurrence |

## Compounding Updates Recommended

| Document | Update |
|----------|--------|
| `docs/BUG_PATTERNS.md` | New entry: "Internal-JWT-guarded endpoint receives unsigned worker calls → 401 silent under-population" |
| `docs/BUG_PATTERNS.md` | New entry: "Retry loop on non-retryable status (4xx ≠ 408/429) → wasted cycle time + log noise" |
| `.claude/review/checklists/REVIEW_CHECKLIST.md` | New check: any `deserialize_value` doing `json.loads(raw)` MUST include `\x00` magic-byte branch + schema_path |
| `.claude/review/checklists/REVIEW_CHECKLIST.md` | New check: any `except Exception → log.warning` MUST include `exc_info=True` and the raw input/output evidence |
| `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` | New HR entry: "Worker HTTP client → internal endpoint without `X-Internal-JWT` header" |

---

## Suggested Next Step

`/fix-bug` invocations in the order above (1→4) — each is a self-contained fix with clear verification steps and low blast radius. The cross-cutting framework cleanups (#2, #3 in cross-cutting list) warrant a small follow-up plan once the four point fixes have shipped.
