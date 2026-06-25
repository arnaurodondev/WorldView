# Chat-model eval (task #12) — Qwen3-235B vs gpt-oss-120b

Date: 2026-06-17 (key blocker); **RESOLVED 2026-06-18** via a synthesis-level A/B **and a full
`chat_quality_benchmark` head-to-head**. Live chat model = `Qwen/Qwen3-235B-A22B-Instruct-2507`.

## VERDICT v2 (2026-06-18) — FULL benchmark: quality TIED incl. tool-selection; keep 235B (or swap for cost)

The **full `chat_quality_benchmark`** was run for both arms (12 questions × 3 runs × full RAG pipeline +
DeepSeek-V4-Flash judge). For gpt-oss, `reasoning_effort=medium` was wired into both the tool-planning and
synthesis turns (clean-worktree image `worldview-rag-chat:gptoss-eval`; it returns EMPTY without it).
Baseline ran at calm load (8-13); the gpt-oss arm ran at load ~33 with the upstream timeout raised to 30s
so entity-resolve wouldn't time out (the load-induced empties are model-agnostic — both arms hit them; see
RC-2 in `2026-06-18-internal-tool-latency-investigation.md`). Raw:
`results/chat_model_eval/FULL_qwen235b/` and `FULL_gptoss120b_v2/`.

| Judge dimension (/25) | Qwen3-235B | gpt-oss-120b@medium |
|---|---|---|
| **overall score (/100)** | 82.94 | **83.19** (tie, +0.25) |
| tool_use | 22.92 | **22.92 (identical)** |
| grounding | **19.75** | 18.75 |
| framing | 20.83 | 20.69 |
| refusal_judgment | 19.44 | **20.83** |
| buckets (P/W/F) | 29 / 4 / 3 | 24 / 9 / 3 |
| judge verdicts (P/W/F) | 26 / 1 / 9 | 26 / 3 / 7 |

**The deeper benchmark confirms the synthesis A/B and adds tool-selection (which synthesis couldn't test):**
- **Quality is statistically tied** (82.94 vs 83.19). **Tool-selection is identical** (22.92 both) — gpt-oss
  plans/selects tools as well as 235B through the real agent loop.
- gpt-oss trades **slightly weaker grounding** (−1.0) for **better refusal judgment** (+1.4); more borderline
  WARNs (9 vs 4) but fewer hard judge-FAILs (7 vs 9). Both block the prompt-injection (adversarial FAIL =
  the input-safety guard firing; judge PASS).
- **Latency across the two arms is NOT comparable** (baseline load 8-13 / 10s timeout vs gpt-oss load 33 /
  30s timeout). The per-call latency truth is the calm synthesis A/B (gpt-oss slightly *faster*, 2.6 vs
  3.8s p50). And per the latency investigation, a turn fires 4-6 sequential completions, so a faster +
  ~10× cheaper per-call model would help proportionally if swapped.

**Recommendation (unchanged, now deeper-confirmed): keep Qwen3-235B** on quality grounds (tied, with a
marginal grounding edge). gpt-oss-120b@medium is a **fully viable, ~10× cheaper, no-worse-quality**
alternative — **swap only if cost becomes the driver** (tool-selection + overall quality are confirmed
safe). The real chat-latency win is NOT the model — it's the orchestration (offload the grounding rewrites
to the 8B model, fix the entity-resolution Seq Scan, isolate the read path — see the latency audit).

---

## VERDICT v1 (2026-06-18) — synthesis-level A/B (superseded by the full benchmark above, consistent with it)
gpt-oss-120b@medium is a viable chat model; quality-equivalent, comparable latency.

The full-pipeline benchmark proved **too platform-fragile** to run cleanly (rag-chat crash-loops on the
`APP_ENV` bug — now fixed `dfb91c8` — plus entity-resolve/tool ReadTimeouts under host load; 4 distinct
contamination modes). So the model comparison was done as a **synthesis-level A/B** (pure DeepInfra, real
production `SYNTHESIS_SYSTEM_PROMPT`, 6 representative tasks × both models, DeepSeek-V4-Flash judge,
identical (question, tool-context) inputs; Qwen3 `thinking=True`, gpt-oss `reasoning_effort=medium`, both
`<think>`-stripped). Raw: `results/chat_model_eval/synth_ab_results.json`.

| Metric | Qwen3-235B | gpt-oss-120b@medium |
|---|---|---|
| grounding / accuracy / helpfulness (1-5) | 5 / 5 / 5 | 5 / 5 / 5 |
| fabricated claims (total, 6 tasks) | 0 | 0 |
| appropriate refusals (price-pred + unknown-ticker) | 2/2 | 2/2 |
| latency p50 / max | 3.8s / 6.9s | **2.6s** / 6.9s |
| output tokens (mean) | 61 | **187 (≈3×)** |

**Findings:**
1. **Quality is equivalent** — both score a clean sweep (5/5/5, 0 fabrication, 2/2 refusals) on grounded
   synthesis. The reasoning-model **latency fear did NOT materialize**: gpt-oss@medium is *slightly faster*
   at p50 (2.6 vs 3.8s) — it's fast on DeepInfra, not a slow thinker here.
2. **gpt-oss is ~3× more verbose** (187 vs 61 output tokens). Quality judged equal, so the extra length is
   not extra value — a verbosity/cost consideration (though gpt-oss-120b is ~10× cheaper per-token than
   235B per the extraction analysis, so 3× tokens still nets cheaper).
3. **The real chat latency bottleneck is the platform tools, not the model.** Full-pipeline runs were
   35-85s while the model synthesis itself is 2-7s — dominated by slow entity-resolve/tool calls under
   load. **Swapping the chat model will not fix chat latency.**

**Limitations / not tested:** the 6 synthesis tasks maxed out both models (all 5s) → not strongly
discriminating; and **tool-SELECTION accuracy** (does each model pick the right tools?) needs the full
pipeline, which remains load-blocked. For a definitive production swap, run the full benchmark on a calm
platform after wiring gpt-oss `reasoning_effort` into the rag-chat adapter (it returns empty without it).

**Recommendation:** gpt-oss-120b@medium is a **safe, quality-neutral, cheaper, no-slower** alternative for
chat synthesis — but since quality is equivalent and the latency win is marginal (and tool-selection is
unverified), there's **no compelling reason to swap the chat model right now**. Keep Qwen3-235B; revisit
only if cost becomes a driver (then validate tool-selection on the full pipeline first).

---

## Original block (2026-06-17) — now resolved
Status: **was BLOCKED — external credential failure** (revoked DeepInfra key, since rotated).

## TL;DR

The single DeepInfra API key used by the entire platform —
`xVi3…GivI` (32 chars) — is **revoked / unauthorized**. Every model call
returns:

```
HTTP 401  {"error":{"message":"User is not authorized to access this resource",
           "type":"invalid_request_error","code":"invalid_api_key"}}
```

…for **all** models tested: `deepseek-ai/DeepSeek-V4-Flash`,
`Qwen/Qwen3-235B-A22B-Instruct-2507`, `openai/gpt-oss-120b`,
`openai/gpt-oss-20b`. The benchmark cannot run because **every arm** (baseline
chat completion + the LLM judge) routes through this one key. This is a
credential problem, not an orchestration problem — no model swap, adapter
change, or container recreate can work around a dead key.

**Action required from the user: provide a valid DeepInfra key** (or whichever
provider account is current), inject it into the live rag-chat container's
`RAG_CHAT_DEEPINFRA_API_KEY` (and `DEEPINFRA_API_KEY` for the judge), then
re-run. Everything else for the eval is staged and ready (see "Ready to run").

## What was verified this session

1. **Live platform is up & untouched.** 80 containers running.
   `worldview-rag-chat-1` is `Up ~1h (unhealthy)`. I made **zero** docker
   mutations (no `down`, no recreate, no rebuild, no `make test`) and **zero**
   code changes — the dead-key finding made all of that moot.

2. **Baseline chat model confirmed (resolves the prior config-drift note).**
   The LIVE `worldview-rag-chat-1` container has
   `RAG_CHAT_COMPLETION_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507`,
   `RAG_CHAT_COMPLETION_PROVIDER=deepinfra`. This comes from the gitops-copied
   `services/rag-chat/configs/docker.env` (modified 2026-06-17), which compose
   reads via `env_file`. So the **real production baseline = Qwen3-235B**, NOT
   DeepSeek-V4-Flash (the `config.py` default and the pre-gitops docker.env
   comment are both stale). The container does NOT set `APP_ENV`; it stays up
   because it sets `RAG_CHAT_INTERNAL_JWT_SKIP_VERIFICATION=true` instead. Full
   env snapshot: `results/chat_model_eval/_live_ragchat_env.txt`.

3. **The key is dead everywhere, not just my probe.** I enumerated every
   DeepInfra key in: all `services/*/configs/*.env`, the `worldview-gitops`
   repo (`env/`, `secrets/`), and the runtime env of every running
   `rag-chat` / `nlp-pipeline` / `knowledge-graph` container. There is exactly
   **one** distinct DeepInfra key platform-wide (`xVi3…GivI`), and it returns
   401 from every source. (`NLP_PIPELINE_EXTRACTION_API_KEY`,
   `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY`, `*_EMBEDDING_API_KEY`, and
   `RAG_CHAT_DEEPINFRA_API_KEY` are all the SAME value.) Implication: the live
   platform's chat, extraction, and embedding paths are ALL currently
   non-functional at the model layer — worth flagging beyond this eval.

4. **Judge is budget-correct** (unchanged from prior note):
   `scripts/chat_quality_judge.py` `_DEFAULT_JUDGE_MODEL =
   "deepseek-ai/DeepSeek-V4-Flash"`; reads `DEEPINFRA_API_KEY` from env;
   base `https://api.deepinfra.com/v1/openai`. Also blocked by the dead key.

## gpt-oss adapter caveat — analysis (not yet applied; no point until key works)

`DeepInfraCompletionAdapter`
(`services/rag-chat/src/rag_chat/infrastructure/llm/deepinfra_adapter.py`)
sends the Qwen-style `chat_template_kwargs={"thinking": True}` **only in
`stream()`** (the bare-prompt path). The actual chat flow uses
`chat_with_tools()` (tool planning) + `stream_chat()` / `_stream_chat_one_model()`
(synthesis) — and **none of those send any reasoning hint**; they emit plain
OpenAI payloads. So for gpt-oss the minimal eval-only change is to inject
`reasoning_effort` (e.g. `"medium"`) into the payload dicts in those three
methods, gated on `self._model.startswith("openai/gpt-oss")`.

Second gotcha (caught here): the adapter defaults
`stream_chat_fallback_model="deepseek-ai/DeepSeek-V4-Flash"`. For a gpt-oss arm
that silent fallback would **contaminate the arm** (a gpt-oss zero-chunk would
be answered by DeepSeek and scored as gpt-oss). The gpt-oss arms must set the
fallback to the same gpt-oss model (or empty) via
`RAG_CHAT_DEEPINFRA_STREAM_FALLBACK_MODEL`. The staged runner already does this.

## Ready to run (once a valid key exists)

`results/chat_model_eval/run_model.sh <model> <reasoning_effort|none> <label>`
performs the per-arm `--no-deps --force-recreate rag-chat` swap and runs the
12-Q subset at `--max-runs-per-q 3` with `--judge`. **Caveat before re-use:**
that script targets the `eval` compose profile and a `docker-compose.eval.yml`;
the LIVE stack uses `docker-compose.yml` + `docker-compose.dev.yml`. Per the
hard constraint, the correct per-arm swap against the LIVE stack is:

```
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml \
  --profile infra up -d --force-recreate --no-deps \
  -e RAG_CHAT_COMPLETION_MODEL=<arm> ... rag-chat
```
…with `RAG_CHAT_INTERNAL_JWT_SKIP_VERIFICATION=true` (and/or `APP_ENV=development`)
preserved so it does not crash-loop, and the model restored to
`Qwen/Qwen3-235B-A22B-Instruct-2507` afterward.

12-Q subset (tool-routing / chains / grounding / safety):
`tc_movers_today_gainers, tc_batch_fundamentals_mag5,
tc_entity_graph_tesla_neighbors, chain_portfolio_upcoming_earnings,
chain_nvda_competitor_growth_rank, chain_top_mover_fundamentals,
da_apple_revenue_fy2024q4_precision, ru_nvda_amd_compare_qtr,
safety_future_price_prediction, safety_unknown_ticker,
safety_prompt_injection_system_prompt, safety_impossible_fiscal_quarter`.

Arms: (1) `Qwen/Qwen3-235B-A22B-Instruct-2507` (baseline, no recreate),
(2) `openai/gpt-oss-120b` reasoning_effort=medium,
(3) `openai/gpt-oss-20b` reasoning_effort=medium.

## Restore state

- rag-chat model: **untouched** — still `Qwen/Qwen3-235B-A22B-Instruct-2507`
  (no recreate was performed).
- Adapter code: **untouched** — no `reasoning_effort` edit was applied this
  session (would have been wasted against a dead key).
- Leftover `infra/compose/docker-compose.modeloverride.yml`: removed this
  session (was inert).
