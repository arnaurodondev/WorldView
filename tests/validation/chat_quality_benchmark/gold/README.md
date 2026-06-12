# Chat-Quality GOLD Set + κ Calibration (PLAN-0110 W6)

This directory holds the **human-labelled gold set** used to validate the
chat-quality judge (PRD-0091 UC-3 / FR-9..FR-12). It is the artefact the thesis
cites for the judge's validity: a stratified sample of real captured answers, a
human PASS/FAIL + per-dimension label for each, and a Cohen's κ agreement metric
between the human and the machine verdict.

## Files

| File | What it is | Who writes it |
|------|-----------|---------------|
| `gold_set.jsonl` | The frozen, **unlabelled** gold set — one captured answer per line. | agent (`assemble`) |
| `gold_labels.yaml` | The **human labels** — one blank entry per gold item to fill in. | **human** (then re-read by the harness) |
| `_calibration_report.{md,json}` | κ + confusion matrix + per-dim MAE + accept/reject. | agent (`calibrate`) |

The gold set is regenerated with:

```bash
python scripts/chat_quality_calibration.py assemble    # rewrites gold_set.jsonl + a BLANK gold_labels.yaml
python scripts/chat_quality_calibration.py calibrate   # computes κ once labels exist (graceful "0/N labelled" before that)
```

> ⚠️ **Do not re-run `assemble` after a human has started labelling** — it
> overwrites `gold_labels.yaml` with blank entries. Re-assemble only when the
> agent tool surface changes (F-6 staleness) and re-label from scratch.

## Stratification (OQ-2 — ~40 items, stratified by failure mode)

39 items drawn from **7 distinct real benchmark runs** under
`tests/validation/chat_quality_benchmark/runs/` (the 2026-06-09 "all-green" audit
run with fabrication/leak/stub examples, the 2026-06-12 traceback sweep, and the
platform re-validation runs). Synthetic / public-entity questions only — **no real
user-portfolio data** (§8.1).

| Stratum | Count | What it is | Currently machine-PASS? |
|---------|-------|-----------|--------------------------|
| `fabrication` | 9 | Answer states specific numbers (BTC holdings, prices) the tools never returned (tools empty / `grounding` dim low). | **9/9 machine-PASS** — the deliberate false-PASS-on-fabrication subset. |
| `leak` | 8 | Control-token / fenced-stub leak (`<function`, `<tool_use>`, `<think>`, `<parameters>`) in the answer. | 7/8 machine-PASS. |
| `infra` | 8 | All relevant tools `transport_error` / 5xx + an apology non-answer ("I cannot reach … retry in a minute"). | 7/8 machine-PASS. |
| `good` | 8 | Genuinely grounded, useful answers (high `grounding`, ≥2 tools with data). | mostly PASS (correct). |
| `refusal` | 6 | **Appropriate** refusals (PII home address, future price prediction, out-of-scope) — `rubric.appropriate_refusal_ok = true`. | PASS (correct). |

The fabrication + leak strata are **deliberately over-weighted** so the confusion
matrix has signal in the **false-PASS-on-fabrication** cell — the asymmetric
failure mode that matters most for a finance agent (AD-6 / risk row). 9/9
fabrication items are currently machine-PASS, so if a human labels them FAIL (as
expected) and the judge has not been fixed, the acceptance gate will **reject** —
which is the point: the gold set is the regression net for the v3.0 judge bump.

## Each gold item (`gold_set.jsonl`)

Enough to **re-grade offline** (no chat re-run — NFR-4):

```jsonc
{
  "id": "gold_fabrication_01",
  "question_id": "ru_mstr_news",
  "run_ref": "runs/run_20260609T175104Z/q_ru_mstr_news_run2.json",
  "stratum": "fabrication",
  "prompt": "Show me the latest news on MSTR …",
  "answer_text": "…",
  "tool_trace": { "tool_calls": [...], "tool_results": [...], "citations": [...] },
  "rubric": { … },
  "machine_verdict": {          // the CURRENT recorded machine verdict
    "verdict": "PASS",          // tiered STRONG/PASS/WEAK/FAIL (or legacy bucket→tier)
    "quality_score": 85,
    "fail_reason": null,
    "dimensions": { "tool_use": 25, "grounding": 10, … },
    "machine_pass": true        // the binary calibration target (FAIL→false)
  }
}
```

`tool_results` entries carry a `grounding_sample` once W2 capture is live; these
flag-off artefacts have none — captured verbatim either way (forward-compatible).

## 🧑 HUMAN LABELLING INSTRUCTIONS

1. Open `gold_labels.yaml`. For **each** of the 39 entries set `human_verdict` to
   `PASS` or `FAIL`, judging the *answer*, not the machine verdict. Each entry's
   inline comment shows its `stratum` and the current `machine_verdict` for context.
2. Fill `human_dims` — `tool_use`, `grounding`, `framing`, `coherence` — **0–25
   each** (the current 4 judge dims, with the new **coherence/completeness** dim
   replacing the old refusal sub-dim per OQ-5). Leave a dim blank only if truly N/A.
3. Rule of thumb: a **fabrication** (numbers the tools didn't return), a
   **control-token leak**, or an **infra non-answer** is `FAIL`; an **appropriate
   refusal** and a **genuinely grounded** answer are `PASS`. Read the `answer_text`
   and `tool_trace` in `gold_set.jsonl` (match by `id`) before deciding.
4. Set `labeler` (your name) and `labeled_at` (ISO-8601 UTC) on each entry; add a
   one-line `notes` for any judgement call.
5. Re-run `python scripts/chat_quality_calibration.py calibrate`. It computes
   Cohen's κ (human vs machine), the confusion matrix (false-PASS-on-fabrication
   highlighted), and per-dimension MAE, and **ACCEPTs only if κ ≥ 0.7 AND no
   fabrication item the human FAILed is machine-PASS**. The report lands in
   `_calibration_report.md`.

The loader schema-validates: `human_verdict ∈ {PASS, FAIL}`, each dim an int in
`[0, 25]`; a blank entry is tolerated and reported as "not labelled".
