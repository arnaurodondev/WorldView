# Embedding Backlog Diagnosis — `nlp_db.embedding_pending`

**Date:** 2026-06-16
**Type:** READ-ONLY diagnosis (task #3). No code or data changes.
**Provider:** DeepInfra (`BAAI/bge-large-en-v1.5`, confirmed via worker env + logs).

## TL;DR

The backlog is **not** a downtime artifact and **not** a rate-limit / provider-health
problem. It is a **systemic truncation bug**: the embedding adapter truncates input to
**1500 characters**, but `BAAI/bge-large-en-v1.5` has a hard **512-token** context limit.
For dense financial/JSON text, 1500 chars exceeds 512 tokens, so DeepInfra rejects the
request with **HTTP 400 `invalid_request_error`** (a *fatal* 4xx, not retryable). Every
affected chunk/section burns all 5 retries and is then **abandoned** (`retry_count=5`),
where `claim_batch` permanently skips it. The retry worker is healthy and running — it
simply cannot drain rows that are mathematically un-embeddable at the current char limit.

## 1. Composition & Trend

| Metric | Value |
|---|---|
| Total rows | **1625** |
| `retry_count` distribution | **100% at 5** (the `_MAX_RETRIES` ceiling) |
| Still actively retrying (`<5`) | **0** |
| `created_at` range | 2026-06-02 → 2026-06-16 (today) |
| Rows created **today** (2026-06-16) | **121** |
| Composition | 952 chunk (`error_detail='chunk embedding failed'`) + 673 section |
| `embedding_text` length | min 370, avg 2088, max 47011 chars |
| Rows ≤ 2000 chars | 1079 (so length alone is *not* the discriminator — see below) |

**Trend: GROWING, not draining.** Count was a steady 1625 across repeated measurements
(the worker keeps re-attempting the 4 not-yet-maxed rows and re-abandoning them), and
**121 new rows landed today** — confirming the inline path is *still* enqueuing failures
on every fresh ingestion. The 06-02 / 06-03 spike (472 + 316) is the initial mass; the
daily drip since (10–260/day) is the ongoing systemic leak.

## 2. Root Cause (reproduced)

Pulled a failing row's `embedding_text`, rebuilt the exact request the adapter sends
(instruction prefix + `[:1500]` truncation), and POSTed to DeepInfra:

```
STATUS 400
{"error":{"message":"You passed 513 input tokens and requested 0 output tokens.
However, the model's context length is only 512 tokens... (parameter=input_tokens,
value=513)","type":"invalid_request_error"}}
```

Re-running the **same text truncated to 1100 chars → 200 OK**. A trivial `"hello world"`
input → 200 OK. So:

- **Model + API key are healthy** (not deprecated, not rate-limited, no 429, no timeout).
- The 400 is **content-specific**: dense text packs >512 tokens into ≤1500 chars.
- `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py` line 47:
  `_MAX_CHARS = 1500` with the comment *"1500 chars ~= 500 tokens... safe under 512"*.
  This assumes ~3 chars/token (2.0–2.2 tok/word). Financial/JSON-envelope text is far
  denser, so 1500 chars routinely → 513+ tokens. The heuristic is simply wrong for this
  corpus.

### Why it accumulates and never drains

1. **Inline path** (`run_embeddings_block` → `persist.py:149-156`) uses the same
   `DeepInfraEmbeddingAdapter`. Dense chunks 400 inline → enqueued into `embedding_pending`.
2. **Retry worker** (`embedding_retry_worker.py`) re-sends the *identical* truncated text →
   identical 400. The adapter maps 4xx to `FatalError`, but the worker's `_process_job`
   treats *any* exception as a retry (bumps `retry_count`, backs off), so it grinds through
   all 5 attempts.
3. At `retry_count==5` the row is logged `embedding_retry_abandoned` and left in place.
   `claim_batch(... max_retries=5)` filters `retry_count < 5`, so these 1625 rows are
   **permanently invisible** to the worker. Startup log confirms:
   `embedding_retry_abandoned_at_startup count=1621 ... "rows with retry_count>=5 are
   skipped by claim_batch and need manual triage"`.

The same `_MAX_CHARS = 1500` flaw also lives in the inline query path
`services/nlp-pipeline/src/nlp_pipeline/api/routes/embed.py:38` — query-side embeddings of
long inputs will 400 identically.

## 3. Provider Health

Healthy. No 429s anywhere in the worker logs; every failure is a deterministic 400. The
shared DeepInfra account is **not** the bottleneck — this is independent of extraction
rate limits.

## 4. Recommendation

This is a **fix-the-truncation** problem, not a "let the worker drain it" or "raise limits"
problem. Draining is impossible without a code change because the abandoned rows will
re-400 forever.

**Primary fix (low risk, single line):** lower `_MAX_CHARS` to a value that is provably
≤512 tokens for the worst-case corpus. 1100 chars reproduced as safe here; **~1000 chars**
is a conservative target. Apply in all three locations that must stay in the *same
semantic space*:
- `libs/ml-clients/.../adapters/deepinfra_embedding.py:47`
- `services/nlp-pipeline/.../api/routes/embed.py:38`
- `libs/ml-clients/.../adapters/ollama_embedding.py` (Ollama silently coped via BP-121
  truncation, but keep parity so ingest vs query embeddings match).

  *Better long-term:* truncate by **actual token count** (tokenizer-based) rather than a
  char heuristic, since char-density varies by source_type.

**Backlog remediation (after the fix ships):** the 1625 abandoned rows need a one-time
reset of `retry_count`/`next_retry_at` (or a targeted backfill worker) so the retry worker
re-claims them with the corrected truncation. The existing
`backfill_light_chunk_embeddings.py` worker is a precedent for this pattern. Without the
truncation fix first, resetting `retry_count` only restarts the same 400 loop.

**Do NOT** raise embedding limits or add capacity — the provider is fine; the request is
malformed.

## Evidence pointers

- `libs/ml-clients/src/ml_clients/adapters/deepinfra_embedding.py` (`_MAX_CHARS=1500`, 4xx→FatalError)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/embedding_retry_worker.py` (abandon-at-5, claim filter)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/persist.py:149-156` (inline enqueue)
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/embed.py:38` (query-path same flaw)
- Worker logs: repeated `HTTP/1.1 400 Bad Request` + `embedding_retry_abandoned`
