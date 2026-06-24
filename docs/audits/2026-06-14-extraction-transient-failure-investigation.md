# Deep-Extraction Transient-Failure Investigation

**Date:** 2026-06-14
**Author:** Principal-engineer RCA (read-only: codebase + live logs/DB; one report; no code/DB/container changes)
**Question:** Transient failures in relation-extraction LLM calls are being silently recorded as empty `relations: []` instead of errors. What exactly fails, where does it become a silent empty result, and what is the precise retry+timeout fix?

---

## TL;DR (the three asks)

1. **Dominant failure mode:** HTTP **429 `engine_overloaded`** ("Model busy, retry later") from DeepInfra on `Qwen/Qwen3-235B-A22B-Instruct-2507`. Of **1,207 failed extraction calls in the last 48h** (`nlp_db.llm_usage_log`, `capability='extraction'`, `success=false`), **887 (73%) are fast-fail 429s** (latency <5s), 240 (20%) are wall-clock timeouts (≥149s), 80 (7%) mid-range. Overall extraction failure rate ≈ **1,207 / 5,193 = 23%**, and it is **throughput-correlated** (1–3% in quiet hours; **39.6% during the 1,084-call/hr burst at 2026-06-13 02:00**, 48% at 06-12 20:00).
2. **Silent-null swallow:** NOT in `deep_extraction.py` (that layer was already fixed — BP-677/commit `ee76aa957`). The real swallow is the messaging base consumer's **OFF retry path**: `libs/messaging/src/messaging/kafka/consumer/base.py:917–943`. With `enable_persistent_retry=False` (the nlp-pipeline default), a `RetryableError` hits the `else` branch (`store_failure` → log → return) — **no DLQ, no seek-back** — and the batch handler then commits the offset as handled (`article_consumer.py:579–580`). The doc is persisted with empty `relations` and never retried. **Live proof: of 1,013 distinct docs with a failed extraction in 48h, 1,003 (99%) NEVER got a successful extraction.**
3. **Fix in one line:** add **bounded in-adapter retry with backoff for 429/5xx/timeout inside `DeepSeekExtractionAdapter.extract` (`libs/ml-clients/.../deepseek_extraction.py`)**, keep the 150s wall-clock cap, and **make a final transient failure DLQ instead of silent-drop** by enabling `enable_persistent_retry=True` on the nlp-pipeline article consumer (`article_consumer_main.py:208`).

---

## A. What exactly fails? (rate-limit vs timeout vs empty-200)

### A.1 Call path (end to end, with file:line)

```
article_consumer._handle_message
  → blocks/ml_phase.py:167  run_deep_extraction_block(extraction_client=ext, …)
    → application/blocks/deep_extraction.py:332  run_deep_extraction_block()
      → :412  for window_text in windows:
        → :414  _run_extraction_window(...)
          → :244  output = await extraction_client.extract(inp)
            → libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py:97  DeepSeekExtractionAdapter.extract()
              → :129  asyncio.wait_for(self._client.chat.completions.create(...), timeout=150s)
                 model = Qwen/Qwen3-235B-A22B-Instruct-2507
                 endpoint = https://api.deepinfra.com/v1/openai
```

**Model / client / timeout (confirmed):**
- Model: `Qwen/Qwen3-235B-A22B-Instruct-2507` (`NLP_PIPELINE_EXTRACTION_API_MODEL_ID` on the live container).
- httpx client: explicit `httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=150.0, write=30.0, pool=5.0), limits=Limits(max_connections=64, max_keepalive=32))` — `deepseek_extraction.py:76–82`.
- Outer guard: `asyncio.wait_for(..., timeout=150.0)` — `deepseek_extraction.py:129,144`. `_EXTRACTION_TIMEOUT_S` default **150.0s**, env-overridable via `ML_CLIENTS_EXTRACTION_TIMEOUT_S` (`:37`).

**BP-235 status: NOT the bug here.** The httpx `read` timeout is explicitly wired to the SAME `timeout_s` (150s) as the `asyncio.wait_for` deadline (`:81` and `:144`). So httpx does not shadow the outer deadline; the wall-clock guard works as intended (the 240 `timeout_>=149s` failures prove it fires at ~150s, not 5s). The inverse risk (outer timeout firing before a slow extraction completes) is real but minor — only 20% of failures are timeouts, and p50 is ~16.5s, so 150s is generous.

### A.2 Live classification (DeepInfra failure modes)

`nlp_db.llm_usage_log`, `capability='extraction'`, last 48h:

| Outcome | Count | Notes |
|---|---:|---|
| `success=true` | 3,986 | ~77% |
| `success=false`, `error_code='model_error'` | 1,016 | generic tag (see B.2) |
| `success=false`, `error_code=NULL` | 191 | older/early rows |
| **Total failed** | **1,207** | **≈ 23% of 5,193 calls** |

Failed-call latency buckets (proxy for 429 vs timeout):

| Bucket | Count | Share |
|---|---:|---:|
| `fast_fail_<5s` (429 `engine_overloaded`) | **887** | **73%** |
| `timeout_>=149s` (wall-clock) | 240 | 20% |
| `mid` (5–149s; mixed 5xx/conn) | 80 | 7% |

Log-level cross-check (3 article-consumer containers, ~36h): **1,114 `429`** vs **~72 `wall-clock timeout`** vs **0 `5xx`** vs **0 `connection error`** vs **0 `json_parse_failed`** vs **0 `deepseek_extraction_malformed`**. The verbatim 429 body is:
`openai.RateLimitError: Error code: 429 - {'error': {'message': 'Model busy, retry later', ... 'code': 'engine_overloaded'}}`.

**Empty-but-200:** effectively zero. `response_format=json_object` + the markdown-strip + partial-JSON recovery in the adapter (`:166–216`) mean parse failures are ~0. The AB-test's "71% empty cohort" is therefore **not** empty-200s — it is these 429/timeout failures substituted as empty (see B).

### A.3 Concurrency / burst → 429 pattern (root cause of the rate)

Per-hour failure rate tracks throughput precisely (commit `f47623f0a` raised concurrency to ~50 in flight + a DeepInfra client pool):

| Hour (UTC) | Calls | Failed | Fail % |
|---|---:|---:|---:|
| 2026-06-13 02:00 | 1,084 | 429 | **39.6** |
| 2026-06-12 20:00 | 252 | 121 | **48.0** |
| 2026-06-12 22:00 | 169 | 79 | 46.7 |
| 2026-06-13 04:00 | 186 | 2 | 1.1 |
| 2026-06-13 06:00 | 303 | 5 | 1.7 |

**Interpretation:** the failure is a provider-side per-model **rate/queue limit**, not a code defect. ~50 concurrent extraction calls per replica × 3 article-consumer replicas overrun DeepInfra's `Qwen3-235B` capacity → `engine_overloaded`. This is exactly the failure class the planned retry+backoff is meant to absorb. (The AB-test's "~73% recover on a fresh @1.4 call" matches the 73% 429 share — the same article succeeds when re-called outside the burst.)

### A.4 Fraction errored vs empty vs relations

Of the failed cohort, the persistence outcome is the key harm:

- **1,013** distinct docs had ≥1 failed extraction call in 48h.
- **1,003 (99%)** of those NEVER recorded a successful extraction → persisted with empty `relations`, never retried.
- Only **10** eventually recovered.
- Among the 3,986 *successful* completions, ~107/461 sampled (`deep_extraction.complete` log) returned `relations=0` legitimately — so genuine-empty does exist, but it is dwarfed by the 1,003 silent-dropped docs.

---

## B. Where a transient failure becomes `relations: []` (the silent-null)

There are TWO layers. Layer 1 (extraction block) was already fixed; the bug now lives in Layer 2 (consumer retry path).

### B.1 Layer 1 — `deep_extraction.py` (ALREADY FIXED, BP-677 / commit `ee76aa957`)

`run_deep_extraction_block` no longer swallows transient errors as empty:
- `deep_extraction.py:423–436` catches `RetryableError` per window → increments `timed_out_windows`, records a metric, does NOT append an empty result.
- `:460–469` if **every** window timed out → **raises `RetryableError`** (good — propagates).
- `:447,477–478` partial degradation → persists good windows but sets `merged["degraded"]=true` + `timed_out_windows`.

This layer is correct. The problem is what the consumer does with the propagated `RetryableError`.

### B.2 Layer 2 — THE SILENT-NULL SWALLOW (`libs/messaging/.../consumer/base.py:917–943`)

The `RetryableError` propagates: `deep_extraction` → `ml_phase` → `_handle_message` → caught as `ConsumerError` at `article_consumer.py:575` (RetryableError ⊂ ConsumerError) → `_handle_failure(msg, exc)` → `outcomes[tp][offset] = True` (`:580`). Then:

```python
# libs/messaging/src/messaging/kafka/consumer/base.py:917 (enable_persistent_retry == False, the nlp default)
if not self._config.enable_persistent_retry:
    failure = FailureInfo(..., attempt=1, last_error=exc)          # :918–925  attempt HARDCODED to 1
    if isinstance(exc, FatalError) or failure.attempt >= self._config.max_retries:   # :926  1 >= 5 is False
        await self.dead_letter(failure)                            # never reached for RetryableError
        ...
    else:
        failure.record = await self.store_failure(failure)         # :935  → just logs "article_consumer_failure"
        logger.warning("kafka_message_failed_retryable", ...)      # :936
    return                                                          # :943  NO seek-back, NO commit-as-failed, NO DLQ
```

Because `_process_one` already set `outcomes[tp][offset] = True` (`article_consumer.py:580`) and the batch loop commits the contiguous offset prefix (`:596–599`), **the offset advances past the message**. Net effect: a 429/timeout doc is **neither retried nor dead-lettered** — it is silently committed with empty `relations`. `store_failure` (`article_consumer.py:1176`) only emits an `article_consumer_failure` log line.

**This is the exact silent-null point the user wants changed.** Live proof: `article_consumer_dead_lettered` = **0** across all containers, yet 159 `all_windows_timed_out` and 1,003 never-recovered docs.

### B.3 Is there ANY retry today? Current timeout/retry state

| Layer | Retry today? | Timeout today |
|---|---|---|
| `DeepSeekExtractionAdapter.extract` | **NONE** — one shot; a single 429/timeout → `RetryableError` immediately (`deepseek_extraction.py:222–229`). No tenacity, no loop, no `Retry-After` honouring. | 150s wall-clock (`asyncio.wait_for`) + httpx read=150s. |
| `FallbackExtractionClient` (`libs/ml-clients/fallback.py:172`) | exists (primary→fallback on RetryableError) but **NOT wired** — `article_consumer_main.py:178/194` constructs a bare `DeepSeekExtractionAdapter` or `OllamaExtractionAdapter`, never the fallback wrapper. | n/a |
| Consumer (`base.py`) | OFF path: **no effective retry** (attempt hardcoded to 1 < max_retries 5). ON path exists (`enable_persistent_retry=True`) but is not enabled for nlp. | `message_processing_timeout_s` = 450s watchdog. |

So **there is zero retry on a 429 today.** The provider literally says "retry later" and we don't.

---

## C. Shared-library fix surface (`libs/ml-clients`)

### C.1 Where the retry policy should live

**Inside `DeepSeekExtractionAdapter.extract` (`libs/ml-clients/src/ml_clients/adapters/deepseek_extraction.py`)**, wrapping the `asyncio.wait_for(...create(...))` call (`:129`). Rationale:
- All deep-extraction consumers (nlp-pipeline article consumer; KG `ProvisionalEnrichmentWorker` extraction chain) share this adapter → one fix benefits everyone.
- It is the only layer that can see `Retry-After` and the 429 vs 5xx vs 4xx distinction *before* the error is type-erased into `RetryableError`.
- Keeps the wall-clock cap and semaphore semantics local.

A generic retry could alternatively live in a shared `_retry_call` helper in `ml_clients` reused by all adapters, but the adapter already centralises provider-specific error mapping, so co-locating retry there is the consistent minimal change.

### C.2 Retry-worthy vs not (already mapped correctly in the adapter)

| HTTP / condition | Adapter mapping | Retry-worthy? |
|---|---|---|
| 429 `engine_overloaded` | `RateLimitError`→`RetryableError` (`:222`) | **YES** (dominant case; honour `Retry-After`) |
| 5xx | `RetryableError` (`:230–232`) | **YES** |
| `APITimeoutError` / `APIConnectionError` / wall-clock `TimeoutError` | `RetryableError` (`:224–229`) | **YES** (with caution — don't multiply 150s caps; see C.3) |
| 4xx (400/401/403/422), malformed-JSON, auth | `FatalError` (`:216,233,237`) | **NO** (a retry won't fix bad input) |

This matches the existing precedent: `embeddinggemma_router.py:225–238` and `deepinfra_embedding.py` already classify 429→`RateLimitError(retry_after=…)`, 5xx→`RetryableError`, 4xx→`FatalError`. The extraction adapter should adopt the **same `parse_retry_after` + RateLimitError** pattern it currently skips (it raises a plain `RetryableError` on 429 without parsing `Retry-After`).

### C.3 How callers distinguish transient vs legitimate-empty today

- Transient → `RetryableError` raised (never a value). Legitimate-empty → a valid `ExtractionOutput` with `{"relations": []}`. **The signal exists and is clean** — the bug is purely that the consumer's OFF-path discards the `RetryableError` instead of DLQ-ing it.

---

## IMPLEMENTATION PLAN (next step)

### (1) Timeout value(s) — where
- **Keep** the 150s wall-clock cap (`_EXTRACTION_TIMEOUT_S`, `deepseek_extraction.py:37`) and the matched httpx `read=150s` (`:81`). Evidence: only 20% of failures are timeouts and p50≈16.5s; raising it further just delays burst recovery. Leave `ML_CLIENTS_EXTRACTION_TIMEOUT_S` as the env knob.
- **Important:** the per-call retry budget (below) must fit inside the **450s** consumer watchdog (`message_processing_timeout_s`, `article_consumer_main.py:220`). 150s × up-to-2 retries + backoff ≈ exceeds 450s — so cap **total** extraction wall-time (initial + retries) at ~400s, OR lower the per-attempt cap to ~90s when retries are enabled. Recommended: per-attempt 90s + max 3 attempts + jittered backoff ⇒ worst case ~300s < 450s.

### (2) Retry policy — which exceptions, backoff, max attempts, where
- **Where:** `DeepSeekExtractionAdapter.extract`, wrapping the `chat.completions.create` call (`deepseek_extraction.py:129`).
- **Retry on:** `RateLimitError`/429, 5xx, `APITimeoutError`/`APIConnectionError`, and wall-clock `TimeoutError`. **Do NOT retry** `FatalError` (4xx/auth/malformed).
- **Attempts:** `max_attempts=3` (initial + 2 retries) — env-overridable `ML_CLIENTS_EXTRACTION_MAX_ATTEMPTS` (default 3).
- **Backoff:** exponential with full jitter, base ~2s, cap ~30s; **honour `Retry-After`** when present (use the existing `parse_retry_after`, `errors.py:31` + `RateLimitError.retry_after`). Pattern already proven in `embeddinggemma_router.py:225–238`.
- **Re-raise** the original `RetryableError` only after attempts are exhausted — so a *persistent* outage still surfaces as an error (not a fake empty).
- Optional defence-in-depth: wire `FallbackExtractionClient(primary=DeepSeek, fallback=Ollama)` (`fallback.py:172`) at `article_consumer_main.py:178` so an exhausted DeepInfra burst degrades to the local Ollama extractor instead of dropping the doc. (Secondary to the retry; ship retry first.)

### (3) Make a FINAL failure surface as ERROR/DLQ, not empty `relations` — file:line
- **Primary change:** set `enable_persistent_retry=True` on the article consumer config — `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer_main.py:208` (`ConsumerConfig(...)`). This switches `_handle_failure` to the ON path (`base.py:945–986`): a `RetryableError` is seek-backed and redelivered (real attempt counting), and on `attempt >= max_retries` (5) it **dead-letters AND commits** past the poison message — instead of the OFF-path silent-drop.
  - Pair with `article_consumer.py:579–580`: when `_handle_failure` chooses seek-back, the offset must NOT be marked `outcomes[tp][offset]=True` for the contiguous-commit prefix. Verify the ON-path seek-back composes correctly with the batch `_contiguous_commit_targets` logic (`:596`) — the batch path may need to treat a still-retrying offset as a barrier (do not commit beyond it). This is the one integration risk; add an explicit test (see 4).
- **Secondary (belt-and-braces, even with OFF path):** if leaving persistent-retry off is preferred short-term, change the OFF branch at `base.py:926` so a `RetryableError` that has exhausted in-adapter retries is treated as DLQ-worthy rather than silently logged — but the clean fix is the ON path above.
- **Net result:** a doc whose extraction fails transiently is either (a) recovered by in-adapter retry, (b) redelivered by the consumer, or (c) after `max_retries` written to the DLQ with `reason='max_retries'` — never persisted as a clean empty `relations`.

### (4) Test surface
- `libs/ml-clients/tests/test_deepseek_extraction_pool.py` (extend) — new cases: 429 then success (retry succeeds); 429×3 (exhausts → raises `RetryableError`, never returns empty); `Retry-After` honoured; 4xx → `FatalError` with NO retry; timeout per-attempt cap; total budget < watchdog.
- `services/nlp-pipeline/tests/.../consumers/test_article_consumer*.py` — assert a `RetryableError` from extraction with `enable_persistent_retry=True` produces a DLQ row after `max_retries` (not a committed empty doc), and that the offset is NOT advanced while still retrying.
- `libs/messaging` consumer tests — regression: ON-path seek-back vs the batch contiguous-commit prefix do not skip a still-retrying offset.
- Add **BP-677/this** as a documented bug pattern (the OFF-path silent-drop of `RetryableError`) — currently absent from `docs/BUG_PATTERNS.md`.

---

## Appendix — key evidence (live, 2026-06-14)

- `llm_usage_log` extraction (48h): success 3,986 / `model_error` 1,016 / null 191 → 23% fail.
- Failed-latency: 887 fast-fail-429 (73%) / 240 timeout≥149s (20%) / 80 mid (7%).
- Burst correlation: 39.6% fail @ 1,084 calls/hr (06-13 02:00); 48% @ 252 calls/hr (06-12 20:00); 1–3% in quiet hours.
- 1,013 docs with ≥1 failed extraction; **1,003 (99%) never recovered**.
- `article_consumer_dead_lettered` = **0** (proves no DLQ today); `article_consumer_failure` logs = 61 (the silent-drop trace).
- Verbatim 429: `engine_overloaded`, "Model busy, retry later".
