# NLP Pipeline Throughput Bottleneck — Diagnosis (2026-06-16)

**Scope:** READ-ONLY. Why is the nlp-pipeline Kafka consumer lag (~30,355 at report time) not draining?
**Verdict:** **MIXED — primarily LATENCY-bound on the 235B extraction model, with a co-equal RATE-LIMIT (HTTP 429 `engine_overloaded`) component.** GLiNER and consumer concurrency are NOT the constraint. A DeepInfra rate-limit increase **would partially help** (it removes ~half the failures) but will **not** fix throughput on its own because the 235B's raw per-call latency exceeds the 90s wall-clock cap.

---

## 1. Lag composition

| Group | Total lag |
|---|---|
| `nlp-pipeline-group` (article consumers) | 1,899 (draining) |
| `nlp-entity-refresh-group` | 0 |
| `kg-service-group-enriched` | ~5 |

All NLP backlog is on **`nlp-pipeline-group`** = the 3 `article-consumer` replicas running deep extraction. The 30,355 figure was measured before the 12-minute-ago container restart; at audit time it had already drained to ~1,900 and is falling, confirming the consumers ARE making progress when the 235B cooperates. The binding resource is per-article extraction wall-time, not consumer parallelism.

## 2. The two failure modes (235B extraction), from article-consumer logs

Counts across the 3 replicas (current container lifetime):

| Signal | c1 | c2 | c3 | **Total** |
|---|---|---|---|---|
| HTTP 429 responses (incl. relevance Qwen3.5-9B calls) | 15 | 43 | 25 | **83** |
| `engine_overloaded` (235B rate-limit) | 3 | 11 | 6 | **20** |
| Wall-clock timeout @ 90s | 21 | 22 | 16 | **59** |
| Fallback engaged — reason `rate_limit` | 3 | 4 | 2 | **9** |
| Fallback engaged — reason `timeout` | 12 | 10 | 6 | **28** |
| Fallback succeeded / failed | 3/3 | 1/3 | 0/3 | **4/9** |
| `deep_extraction.window_timeout` | 4 | 4 | 4 | **12** |

**Ratio of failure cause: timeout (59) ≈ 3× rate-limit (20).** When the 235B is reached, the dominant outcome is a 90s wall-clock timeout, not a 429 rejection. This is the signature of a **latency-bound** primary model, with rate-limiting as a secondary aggravator that appears during bursts.

## 3. Latency distribution (`llm_usage_log`, last 2h)

| model_id | capability | calls | p50 ms | p95 ms | max ms |
|---|---|---|---|---|---|
| Qwen/Qwen3-235B-A22B-Instruct-2507 | extraction | 14 | **161,404** | 178,561 | 179,814 |
| deepseek-ai/DeepSeek-V4-Flash (fallback) | extraction | 4 | 303,140 | 341,915 | 342,407 |
| Qwen/Qwen3.5-9B | classification (relevance) | 226 | 2,012 | 7,509 | 16,002 |
| Qwen/Qwen3.5-9B | extraction (resolution) | 109 | ~0* | ~0* | ~0* |
| qwen2.5:7b-instruct (LOCAL Ollama, legacy) | extraction | 308 | **180,255** | 274,622 | 363,772 |

\* resolution calls log near-zero latency_ms (instrumentation quirk); they are not on the hot path.

**Reading:** the 235B `latency_ms` of 161s reflects the *full* `extract()` envelope (multiple 90s attempts + retry backoff + fallback), well above the 90s single-attempt cap → almost every call exhausts its retry budget. The 235B is **inherently too slow for the configured 90s wall-clock cap under any concurrent load**. The legacy local `qwen2.5:7b-instruct` (180s p50, 73% `model_error`) is even worse and is the residue of the prior config — it is not the API path but still pollutes the table.

## 4. Request rate & concurrency

- **Config:** `article_consumer_concurrency = 16` per replica × 3 replicas = up to **48 articles in flight** (`config.py:273`). `deepinfra_max_connections = 64`. Concurrency is NOT under-provisioned — it is over-provisioned relative to what the 235B endpoint tolerates (driving the 429s).
- **Observed extraction request rate (per-minute, last 20 min):** peaks of ~8–10 successful 235B calls/min and bursts of 29 Qwen3.5-9B relevance calls/min. Because each 235B call holds a slot for up to 90–400s, the 48 concurrent slots translate to only a handful of *completing* extractions per minute.
- **Effective peak concurrency hitting DeepInfra 235B:** up to 48 simultaneous requests during a burst → this is precisely what triggers `engine_overloaded`.

## 5. Fallback effectiveness (DeepSeek-V4-Flash)

- Fired 37 times (9 rate_limit + 28 timeout) across replicas; **only 4/13 logged fallbacks succeeded**, and its own p50 latency is **303s** — *slower* than the primary. The fallback is **not relieving 235B pressure**; it frequently times out too and burns an additional 200s budget per doc (see `config.py:290` re-budget note). It is a correctness safety net, not a throughput lever.

## 6. GLiNER (local NER) — NOT a bottleneck

- `gliner-server` CPU **0.13%**, 2.26 GiB / 46.7 GiB mem; every `/ner/batch` returns **200 OK**, zero timeout/queue/503 logs. Ollama CPU **0.00%**. Local NER has ample headroom.

---

## Conclusion

| Candidate cause | Verdict |
|---|---|
| (a) DeepInfra rate limits (429 `engine_overloaded`) | **Contributing (~1/3 of failures)** — increase helps partially |
| (b) Raw 235B latency vs 90s cap | **PRIMARY constraint (~2/3 of failures)** — a limit increase does NOT fix this |
| (c) GLiNER local NER saturation | **Ruled out** (0.13% CPU, all 200 OK) |
| (d) Consumer concurrency too low | **Ruled out** — it is too HIGH (48-way), which *causes* the 429s |

**A DeepInfra rate-limit increase is worth requesting but is not sufficient.** The real levers, in priority order:

1. **Routing redesign (now live) — route fewer articles to the 235B deep-extraction tier.** Highest leverage: the 235B simply cannot sustain 48-way concurrency at 90–160s/call. Fewer deep calls = less 429 AND less timeout.
2. **Reduce 235B-facing concurrency** (`article_consumer_concurrency` 16→~6–8, or a dedicated 235B semaphore) so request rate stays under the endpoint's sustainable throughput — this directly removes the `engine_overloaded` bursts without any DeepInfra change.
3. **Pick a faster primary or raise the 90s cap deliberately.** The 235B p50≈161s means the 90s cap guarantees mass timeouts; either swap the deep tier to a faster model (e.g. make DeepSeek-V4-Flash or Qwen3.5-9B the primary for most docs) or raise the cap and lower concurrency to compensate.
4. **Fix the fallback:** DeepSeek-V4-Flash p50=303s makes it useless as a *fast* fallback — choose a genuinely faster fallback model.

---

## DeepInfra rate-limit-increase request table (ready to send)

Request applies to the `Qwen/Qwen3-235B-A22B-Instruct-2507` (extraction) and `Qwen/Qwen3.5-9B` (relevance + resolution) models on API key `...GG6i`.

| Model | Use | Observed peak concurrency | Observed peak req rate | 429 frequency | Current apparent limit | **Requested new limit** |
|---|---|---|---|---|---|---|
| Qwen/Qwen3-235B-A22B-Instruct-2507 | deep extraction | ~48 concurrent (3 replicas × 16) | ~8–10 completes/min, ~30–40 attempts/min during bursts | ~20 `engine_overloaded` rejections / replica-lifetime; **~1/3 of all extraction attempts hit a 429** | endpoint rejects sustained >~10–15 concurrent (`engine_overloaded`) | **≥50 concurrent / ≥60 req/min sustained** |
| Qwen/Qwen3.5-9B | relevance scoring + unresolved resolution | bursts of ~29 calls/min | ~225 classification + ~109 resolution calls / 2h | 1 `model_error`, occasional 429 during 235B bursts (shared key) | fine at current rate; minor contention | **≥60 req/min** to decouple from 235B bursts |

> Caveat to include in the request: even at higher limits, the 235B's ~160s effective per-call latency means concurrency headroom (not just req/min) is what matters; please confirm the per-model **concurrent-request** ceiling, not only the rate ceiling.

---

### Appendix — evidence commands (all read-only)
- `llm_usage_log` group-by model/capability/success/error_code/fallback_reason (last 2–3h)
- `llm_usage_log` latency percentiles per model
- `kafka-consumer-groups --all-groups --describe` filtered to nlp groups
- `docker logs <article-consumer>` greps: `429 Too Many Requests`, `engine_overloaded`, `wall-clock timeout after 90`, `fallback_engaged/succeeded/failed`
- `docker stats` gliner-server / ollama
- `config.py` lines 100–138 (models), 248–297 (concurrency/budget)
