# Extraction-quality LLM-as-judge A/B harness

**Date:** 2026-06-12
**Artefact:** `scripts/eval/extraction_quality_eval.py` (+ README + tests)
**Status:** Harness built + validated via 3-article mocked dry-run. Full 100-article
run NOT yet executed (deferred pending sign-off — it costs tokens).

## Why

We need to decide whether a faster/cheaper DeepInfra extraction model
(`deepseek-ai/DeepSeek-V4-Flash`, `Qwen/Qwen3.6-35B-A3B`) matches the production
`Qwen/Qwen3-235B-A22B-Instruct-2507` on **extraction quality** before swapping it.
Extraction drives the KG (events/claims/relations); a wrong swap silently degrades
the graph. Chosen approach: **LLM-as-judge as the primary screen** (no engineer-time
labelling), human spot-check optional/secondary.

## What was built

A standalone 4-stage harness (does **not** touch the live pipeline / adapter /
`config.py` / model env):

1. **assemble** — pulls DEEP-tier docs from nlp_db and freezes the EXACT extraction
   inputs (`{entities}` allow-list from `entity_mentions`, `{text}` from
   `chunks.chunk_text` joined by `chunk_index`), mirroring `deep_extraction.py`.
   Balanced across earnings / M&A / management / macro / thin span buckets.
2. **run** — runs each candidate through the same decode params as the production
   adapter (`temperature=0`, `json_object`, `reasoning_effort=none`,
   `max_tokens=4096`), capturing raw JSON + latency + tokens. Per-article error
   capture (no run-aborting crashes).
3. **judge** — an **independent** strong judge scores precision / recall / adherence
   (1–5) + counts + justification. Judge = Claude Opus 4.8 (`claude-opus-4-8`) when
   `ANTHROPIC_API_KEY` is set (different family ⇒ independent of all DeepInfra
   candidates); else the 235B on DeepInfra with a hard self-grading guard.
4. **report** — comparison table (means, fabrication rate, JSON-fail rate, counts,
   p50/p95 latency) + ranked verdict (`-0.10` overall match tolerance) +
   `human_spotcheck.md`.

The prompt is rendered from the real `prompts.extraction.deep.DEEP_EXTRACTION` v1.4
template (no copy) so it can't drift from production.

## Judge-bias mitigations (the measurement instrument)

- **Self-preference**: judge is never the candidate; default is a different family
  (Claude); code guard refuses self-grading.
- **Verbosity bias**: explicit NEUTRALITY RULES in the prompt — short-but-correct
  beats long-but-padded; recall judged against what the article supports, not a
  quota; thin-article empty output is the correct 5/5/5.
- **Reproducibility**: both extraction and judge at `temperature=0`; strict JSON;
  deterministic floor for unparseable outputs.

## Dry-run validation (3 articles, mocked LLMs)

Ran the real CLI command functions end-to-end with mocked DeepInfra + Anthropic
calls. Sanity checks all held:

- Faithful baseline extraction → **5/5/5**.
- Candidate with an off-allow-list `object_ref` → adherence **2**, `allowlist
  violation` flagged → overall 3.667, ranked **"BELOW baseline — do NOT swap"**.
- Thin article, correct empty output → **5/5/5** (not penalised as a miss).

All 13 offline unit tests pass (`scripts/eval/test_extraction_quality_eval.py`).

## Cost estimate

100 articles × 3 models, ~700 words/article, worst-case 4096-token outputs:

- Extraction ≈ **$0.18**; DeepInfra judge ≈ **$0.07** → **total ≈ $0.25**.
- With Claude Opus 4.8 as judge instead: judge leg ≈ **$5–6**.

## Next step (not done here)

Run the full `assemble → run → judge → report` against the live DBs +
`DEEPINFRA_API_KEY` (+ `ANTHROPIC_API_KEY` for the Claude judge) once approved. Then
read the verdict + latency columns to make the swap call.
