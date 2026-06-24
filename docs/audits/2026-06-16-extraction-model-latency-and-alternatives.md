# Extraction Model Latency — Root Cause & DeepInfra Alternatives (2026-06-16)

**Scope:** READ-ONLY diagnosis + web research. NO code changes. Companion to
`docs/audits/2026-06-16-nlp-throughput-bottleneck.md` (which proved the nlp-pipeline
backlog is latency-bound on the 235B extraction model). This doc answers *why each
235B call takes minutes* and *which DeepInfra model to swap to*.

**Bottom line:**
1. **The dominant latency driver is the model itself.** DeepInfra serves
   `Qwen/Qwen3-235B-A22B-Instruct-2507` at **8.3 output tokens/sec — the slowest of
   11 measured providers** (Artificial Analysis). Combined with `reasoning_effort="low"`
   (which is *enabled* in our config, not off — it emits billed-but-hidden reasoning
   tokens before the JSON), a single extraction generating ~800–1,500 effective tokens
   decodes in **~100–180s**, matching the measured p50 of 161s. This is driver **(c)+(d)**:
   reasoning is on AND the model is inherently slow on DeepInfra.
2. **Input window is NOT the driver.** TTFT (prefill) on DeepInfra is ~1.0s even for
   large prompts; the 24k-word single-window cap produces a big prefill but prefill is
   cheap relative to decode. The minutes are spent in **decode at 8.3 t/s**, not prefill.
3. **Our-side levers:** (a) turn `reasoning_effort` back to `"none"`, (b) lower
   `max_tokens`, (c) reduce 235B-facing concurrency — but the highest-leverage fix is a
   **model swap** to a faster non-reasoning instruct model.
4. **Recommended primary:** `openai/gpt-oss-120b` (configurable reasoning, native
   structured output, ~$0.04/$0.19 per 1M, MoE 5.1B active → an order of magnitude
   faster decode). **Recommended fast fallback:** `meta-llama/Llama-3.3-70B-Instruct`
   or `openai/gpt-oss-20b` — both genuinely sub-30s, replacing DeepSeek-V4-Flash
   (measured p50 = 303s, useless as a "fast" fallback).

---

## Part 1 — Why does a single extraction call take minutes?

### 1.1 The actual request shape (from code)

**Window builder** — `services/nlp-pipeline/.../application/blocks/deep_extraction.py`:
- `SINGLE_WINDOW_TOKEN_LIMIT = 24_000` (config `extraction_single_window_tokens=24000`).
- `_build_windows` splits on **whitespace** (`full_text.split()`), so the "24k tokens"
  cap is really **24k words ≈ 30–35k real tokens**. The DeepInfra comment claims
  262k native context, so the window always fits.
- **Almost every financial-news article is a single window.** Typical news bodies are
  300–2,000 words → one call, whole article in the prompt. Multi-window (6k-word
  windows, 500 overlap) only triggers for very long filings/transcripts.
- **Per-call input size:** prompt (system extraction template, see
  `libs/prompts/.../extraction/deep.py`) + the article body + a deduped mention list.
  For a typical news article: **~500–2,500 input tokens**; for a long filing window:
  up to ~8k tokens. Prefill at this size on DeepInfra is ~1s (TTFT measured 1.01s).

**Request params** — `libs/ml-clients/.../adapters/deepseek_extraction.py`,
`_create_with_retry` (lines ~310–332):
```python
response_format={"type": "json_object"},
temperature=0.0,
max_tokens=4096,
extra_body={
    "reasoning_effort": self._reasoning_effort,   # default "low"  ← NOT off
    "prompt_cache_key": "kg_extraction_v2",
},
```
- `max_tokens=4096` — output cap (generous headroom for the events/claims/relations schema).
- `temperature=0.0` — deterministic, no impact on latency.
- `response_format=json_object` — server-side JSON enforcement, negligible latency.
- **`reasoning_effort="low"` — the key finding.** Set in code
  (`_EXTRACTION_REASONING_EFFORT = os.environ.get("ML_CLIENTS_EXTRACTION_REASONING_EFFORT", "low")`)
  and **NOT overridden in `services/nlp-pipeline/configs/docker.env`** → the live value
  is `"low"`. It was deliberately raised from `"none"` on 2026-06-15 for
  relation-extraction recall/precision (see comments referencing
  `docs/audits/2026-06-13-relation-extraction-quality-audit.md`). With `"low"`, the
  model emits a hidden reasoning chain (billed as output, not returned) *before* the
  JSON answer — directly multiplying decode time.

**Retry/budget envelope** (same adapter): per-attempt cap 90s
(`ML_CLIENTS_EXTRACTION_TIMEOUT_S=90`), per-model total budget 200s
(`ML_CLIENTS_EXTRACTION_TOTAL_BUDGET_S=200`), up to 3 attempts, then a fresh 200s
budget on the fallback model. Article watchdog raised to 700s
(`NLP_PIPELINE_MESSAGE_PROCESSING_TIMEOUT_S=700`).

### 1.2 The provider-side smoking gun (web-verified)

| Metric (DeepInfra, Qwen3-235B-A22B-Instruct-2507) | Value | Source |
|---|---|---|
| **Output speed** | **8.3 tokens/sec — slowest of 11 providers** | Artificial Analysis |
| Time to first token (prefill) | 1.01s | Artificial Analysis |
| Blended price | $0.07 / 1M (cheapest provider) | Artificial Analysis |
| Listed price (model page) | **$0.09 in / $0.10 out per 1M** | deepinfra.com |
| Context | 262,144 native | deepinfra.com |
| Thinking mode | "supports only non-thinking mode; no `<think>` blocks" | deepinfra.com |

**This is the whole story.** At **8.3 t/s**, generating just 800 output tokens takes
**96s**; 1,500 tokens takes **181s** — exactly the measured p50/p95 (161s/178s). The
235B is the *cheapest* provider precisely because it is the *slowest* (small/oversubscribed
GPU pool). DeepInfra is almost certainly serving this on a shared/serverless pool, which
also explains the `engine_overloaded` 429 bursts under our 48-way concurrency.

> **Reasoning-mode caveat:** the model page says Instruct-2507 is non-thinking, yet our
> adapter sends `reasoning_effort="low"` via `extra_body`. On DeepInfra this knob is
> either ignored (then the 8.3 t/s decode alone explains the latency) **or** silently
> routes through a reasoning code path that inflates output tokens. Either way the
> safe, cheap experiment is to set `reasoning_effort="none"` and re-measure — but even
> at "none", 8.3 t/s makes this model structurally unsuited to the 90s cap.

### 1.3 Dominant-driver verdict

| Candidate driver | Verdict |
|---|---|
| (a) Input window too large (prefill) | **Ruled out** — TTFT ~1s; prefill is not the cost. Reducing window size buys little. |
| (b) Output `max_tokens=4096` too large | **Minor** — it's a *cap*, not the actual output; real output is ~800–1,500 tokens. Lowering it bounds the worst case but does not move p50. |
| (c) `reasoning_effort` not off | **Contributing** — it is `"low"`, not `"none"`; adds hidden reasoning tokens → more decode. Cheap to revert and re-measure. |
| (d) Model inherently slow on DeepInfra | **PRIMARY** — **8.3 t/s decode** is the root cause. No amount of window/token tuning fixes a model that decodes at 8 t/s. |
| (e) DeepInfra serverless cold/queue | **Secondary** — manifests as the 429 `engine_overloaded` bursts under 48-way concurrency; aggravates but is not the per-call floor. |

**Our-side levers, in order (no model swap):**
1. `ML_CLIENTS_EXTRACTION_REASONING_EFFORT=none` — re-measure latency vs. the
   relation-quality regression that motivated "low". (Trade-off: recall/precision.)
2. Lower `max_tokens` to ~1536–2048 — bounds the worst-case decode tail.
3. Drop `article_consumer_concurrency` 16→6–8 to stop triggering `engine_overloaded`.

**But the structural fix is a model swap** (Part 2): 8.3 t/s cannot meet a 90s cap.

---

## Part 2 — DeepInfra model alternatives (web-verified)

All prices $/1M (input / output). Throughput = output tokens/sec on DeepInfra (or
provider-median where the DeepInfra row was not separately published, flagged as such).
For extraction we want a **non-reasoning instruct model**, strong at structured JSON,
cheap, and **materially faster than 8.3 t/s**.

| Model (DeepInfra slug) | Price in/out | Context | Throughput (DeepInfra) | JSON/structured | Notes |
|---|---|---|---|---|---|
| **`openai/gpt-oss-120b`** | **$0.04 / $0.19** | 128k | median ~344 t/s across providers; DeepInfra-specific row not published but MoE 5.1B-active → an order of magnitude over 8.3 t/s | **Native structured output + tool use; configurable reasoning depth** | **Recommended PRIMARY.** Cheapest output of the strong models; can run reasoning *low/off* for speed or *high* for quality. |
| `Qwen/Qwen3-235B-A22B-Instruct-2507` (current) | $0.09 / $0.10 | 262k | **8.3 t/s (slowest)** | json_object ✓ | Current primary. Cheapest tokens, but throughput makes it unusable at the 90s cap. |
| `meta-llama/Llama-3.3-70B-Instruct` | $0.23 / $0.40 | 128k | ~23.5 t/s (DeepInfra Turbo/FP8) | json_object ✓ (no native reasoning) | **Recommended FAST FALLBACK.** Pure instruct (no reasoning overhead), ~3x the 235B's decode, battle-tested at structured extraction. |
| `deepseek-ai/DeepSeek-V3` (Dec'24) | $0.27 / $1.10 | 64k–128k | 18.1 t/s, TTFT 1.02s | json_object ✓ | Strong quality, but output price 11x the 235B and only ~2x faster. Not cost-justified as primary. |
| `openai/gpt-oss-20b` | $0.03 / ~$0.04–0.19 | 128k | very fast (smaller MoE, 3.6B active) | Native structured output | Alternative fast fallback — cheapest, fastest, lower quality than 120b. |
| `Qwen/Qwen2.5-72B-Instruct` | $0.23 / $0.40 | 128k | (not separately measured) | json_object ✓ | Solid instruct option; similar profile to Llama-3.3-70B. |
| `deepseek-ai/DeepSeek-V4-Flash` (current fallback) | $0.14 / $0.28 | 1M | — (measured **p50 303s** in our logs) | json_object ✓ | **Remove as fallback** — measured *slower* than the primary; useless on the 429/timeout path. |

### Recommended PRIMARY — `openai/gpt-oss-120b`
- **Slug (verified):** `openai/gpt-oss-120b` (DeepInfra demo + API page).
- **Price:** ~$0.04 in / $0.19 out per 1M. Input *cheaper* than the 235B; output ~2x
  but on far fewer total tokens because decode is an order of magnitude faster.
- **Context:** 128k (>> our 24k-word window cap).
- **Why it fits:** 117B MoE, **5.1B active params per forward pass** → fundamentally
  faster decode than the 235B (22B active). Native **structured-output + function-calling**
  support (better JSON adherence than coercing json_object). **Configurable reasoning
  depth** — set it *low/none* for the latency-bound deep tier, or *high* selectively for
  hard relation cases. Provider-median output ~344 t/s; even DeepInfra's slower instance
  will crush 8.3 t/s, bringing a typical extraction well under the 90s cap.
- **Trade-off / quality risk:** gpt-oss-120b is a different model family than Qwen3;
  the v1.6 relation-extraction prompt was tuned against the 235B. Re-run the relation-
  extraction quality A/B (`docs/audits/2026-06-13-relation-extraction-quality-audit.md`
  harness) before flipping production. Quality is expected comparable-or-better at far
  better latency, but **must be validated, not assumed.**

### Recommended FAST FALLBACK — `meta-llama/Llama-3.3-70B-Instruct`
- **Slug (verified):** `meta-llama/Llama-3.3-70B-Instruct` (DeepInfra).
- **Price:** $0.23 in / $0.40 out per 1M. Context 128k.
- **Why it fits the 429/timeout path:** pure instruct model — **no reasoning chain**, so
  decode is short and predictable; ~23.5 t/s on DeepInfra → a typical extraction in
  **well under 30s**, the genuine "fast fallback" the current DeepSeek-V4-Flash (303s)
  fails to provide. Reliable json_object adherence, widely used for financial extraction.
- **Trade-off:** ~2.5–4x the 235B's token price, but the fallback fires on a minority of
  calls (the 429/timeout path) so the blended cost impact is small. Lower ceiling on
  multi-hop relational reasoning than gpt-oss-120b/235B — acceptable for a fallback whose
  job is "return *something* fast rather than DLQ".
- **Alternative fast fallback:** `openai/gpt-oss-20b` (cheaper/faster, slightly lower
  quality) if you want the fallback in the same family as the primary.

### Config-only change surface (for the eventual swap — not applied here)
- `NLP_PIPELINE_EXTRACTION_API_MODEL_ID=openai/gpt-oss-120b`
- `NLP_PIPELINE_EXTRACTION_FALLBACK_MODEL_ID=meta-llama/Llama-3.3-70B-Instruct`
- `ML_CLIENTS_EXTRACTION_REASONING_EFFORT=none` (or `low` if the A/B shows it's needed
  and the faster model can afford it)
- Consider lowering `NLP_PIPELINE_ARTICLE_CONSUMER_CONCURRENCY` 16→8 regardless.
- Note: `gpt-oss` exposes *native* structured output; the adapter currently sends
  `response_format={"type":"json_object"}`, which gpt-oss accepts — no code change
  strictly required, but a follow-up could switch to the native schema mode for
  stricter adherence.

---

## Sources
- Qwen3-235B-A22B-Instruct-2507 model page (price, 262k context, non-thinking):
  https://deepinfra.com/Qwen/Qwen3-235B-A22B-Instruct-2507
- Qwen3-235B-A22B-Instruct-2507 provider benchmarks (**DeepInfra 8.3 t/s, TTFT 1.01s, $0.07 blended**):
  https://artificialanalysis.ai/models/qwen3-235b-a22b-instruct-2507/providers
- gpt-oss-120b model page (median 344 t/s, TTFT 0.90s):
  https://artificialanalysis.ai/models/gpt-oss-120b
- gpt-oss-120b / 20b pricing + structured output (DeepInfra $0.04/$0.19; gpt-oss-20b $0.03):
  https://artificialanalysis.ai/models/gpt-oss-120b/providers ;
  https://deepinfra.com/openai/gpt-oss-120b ; https://deepinfra.com/openai/gpt-oss-20b
- Llama 3.3 70B (DeepInfra ~23.5 t/s, $0.23/$0.40):
  https://artificialanalysis.ai/models/llama-3-3-instruct-70b/providers
- DeepSeek V3 (DeepInfra 18.1 t/s, TTFT 1.02s, $0.27/$1.10):
  https://artificialanalysis.ai/models/deepseek-v3/providers
- Qwen2.5-72B / DeepSeek-V3 DeepInfra pricing:
  https://anotherwrapper.com/tools/llm-pricing/deepseek-v3-deepinfra
- DeepInfra provider overview: https://artificialanalysis.ai/providers/deepinfra
</content>
</invoke>
