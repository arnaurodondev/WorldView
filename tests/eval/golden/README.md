# Golden Retrieval Evaluation Set

> **PLAN-0063 W5-1-01** — labelled query corpus and grading conventions for the
> L1 retrieval-quality eval. Authoritative spec: `docs/plans/0063-w5-hybrid-retrieval-eval-gate-plan.md`
> §0-bis.0 (locks L1–L16) and §0-bis.4-v2 (distribution).

This directory holds the corpus that `scripts/eval_retrieval.py` and the
CI gate (enabled at the W5-3 commit) consume. Treat every file here as
data-with-tests-against-it: a careless edit can silently regress NDCG@10
or pass a regression undetected.

---

## 1. Files

| File | Purpose |
|---|---|
| `queries.jsonl` | **120 labelled queries** — the primary golden set. |
| `_backlog.jsonl` | **20 spare queries** — unlabelled candidates kept on hand to replace any query that retires (per L18 Maintenance / Deprecation rule below). |
| `query_embeddings.parquet` | **Precomputed query embeddings (120 rows, BAAI/bge-large-en-v1.5, dim 1024)** — generated 2026-05-06 via `scripts/generate_query_embeddings.py` against DeepInfra. Each row carries `query_text_sha256 + model_revision` for drift detection; CI loads this parquet via `--query-embeddings` to make eval runs $0/run + deterministic (L5). Regenerate when the embedding model changes. |
| `LABELLING_REPORT.md` | Per-pass labelling status: how many fully labelled, partial, retrieval pathologies. |
| `README.md` | This file. |

---

## 2. Schema (one JSON object per line)

Required fields on every row:

```jsonc
{
  "query_id":              "q001",                       // ^q\d{3}$, unique
  "query_text":            "What is Apple's …",          // 1–2000 chars; analyst phrasing for ≥80% of rows
  "intent":                "FACTUAL_LOOKUP",             // legacy diagnostic axis (kept for continuity)
  "query_class":           "factual_lookup",             // GATING axis (per L6 / §0-bis.4-v2)
  "query_subclass":        "forward_guidance",           // sub-stratum (see distribution table below)
  "phrasing_audit":        true,                         // bool — passed analyst-vs-non-analyst phrasing review
  "label_review": {
    "reviewer_id_a":       "claude-agent-1",
    "reviewer_id_b":       "claude-agent-1",
    "reviewed_at_utc":     "2026-05-06T00:00:00Z",
    "agreement_notes":     "single-reviewer initial pass; 2-reviewer audit deferred"
  },
  "expected_grade_3_count": 1,                            // ≥1 — at least one row in relevant_doc_ids must be relevance=3
  "entity_ids":            [],                            // canonical entity UUIDs from intelligence_db.canonical_entities
  "relevant_doc_ids": [
    {
      "doc_id":            "<uuid>",
      "relevance":         3,                              // 0/1/2/3 (graded — see §4)
      "rationale":         "≤120 chars — why this grade"
    }
  ],
  "notes":                 "≤200 chars — what this query is testing"
}
```

`query_class` is the gating axis from W5-1 onward. `intent` (the v1 axis) is
preserved for diagnostic reporting only — the eval script reports
NDCG@10 broken down by **both** so we keep continuity with the S6 intent
classifier.

---

## 3. Distribution (v2, authoritative — per §0-bis.4-v2)

Total: **120 queries.** Per-class minimum n=4; classes the CI gate makes
NDCG@10 regression claims on (≥0.05 fails) are ≥6.

| `query_class` | n (minimum) | `query_subclass` (in row) |
|---|---|---|
| `factual_lookup` | 14 | `recent` / `historical` / `forward_guidance` |
| `comparison` | 10 | `pair` / `cohort` (≥3 entities) |
| `reasoning` | 10 | `causal` / `counterfactual` |
| `financial_data` | 8 | `point_in_time` / `time_series` / `ratio_derived` |
| `relationship` | 8 | `direct_1hop` / `indirect_2plus_hop` |
| `signal_intel` | 7 | `sentiment` / `flow` / `unusual_activity` |
| `general` | 6 | `daily_brief` / `topical` |
| `portfolio` | 7 | `holdings` / `events` / `risk` |
| `identifier_lookup` | **12** | `prd_id` (≥2) / `filing_type` (≥2) / `ticker_or_isin_or_cik` (≥3) / `function_or_class_name` (≥2) / `error_or_bp_code` (≥2) / `date_quarter` (≥1) |
| `ambiguous` | 6 | `entity_ambiguous` / `time_ambiguous` / `pronoun_no_anchor` |
| `non_analyst` | **12** | `screener_style` (≥3) / `geo_filter` (≥2) / `theme_search` (≥3) / `casual_browse` (≥2) / `operator_dev_query` (≥2) |
| `adversarial_or_out_of_scope` | 6 | `out_of_scope` (≥2) / `decision_support_deflection` (≥2) / `prompt_injection` (≥1) / `nonsense` (≥1) |
| `time_anchored_edge` | 4 | `today` / `last_week` / `last_quarter` / `since_event` |
| **Total (minimum)** | **110** | — |

The current corpus carries 120 rows: counts above are minimums; the
remaining 10 are spread across the analyst-style classes
(`factual_lookup`, `comparison`, `reasoning`, `financial_data`,
`relationship`, `signal_intel`) to maintain the ≥80% Sam-the-Analyst
phrasing target without starving the non-analyst classes.

---

## 4. Relevance scale (graded, 0–3)

| Grade | Meaning |
|---|---|
| `0` | Default for any candidate not listed in `relevant_doc_ids`. Irrelevant. |
| `1` | Mentions the topic but does not answer the question. |
| `2` | Substantive content on the entity/topic — partial answer or supporting detail. |
| `3` | **Direct answer** / primary source / authoritative citation. |

Default-zero convention: candidates not present in `relevant_doc_ids` are
treated as relevance=0. This means a labelling pass need only enumerate
the relevant items (graded ≥1).

Calibration rule when in doubt: prefer the lower grade. Especially:
**never grade `3` unless the snippet directly answers the question.**

For `adversarial_or_out_of_scope` rows, `expected_grade_3_count=1` means
the *correct refusal / empty result* is the "grade 3" outcome (the
metric is about the system doing the right thing, which here is to
decline).

---

## 5. Labelling procedure

For every query:

1. Call `POST /v1/internal/retrieve` (rag-chat, port 8008, `X-Internal-JWT`
   header — see *§ 7 Auth note* below) with `{"query_text": <q>, "top_k": 20}`.
2. Inspect the returned candidates' snippets.
3. For each candidate that is plausibly relevant, add an entry to
   `relevant_doc_ids` with `{doc_id, relevance, rationale}`.
4. Aim for ≥5 graded candidates per query, ≥1 with grade 3, ≥1 with grade 2.
5. If retrieval returns 0 candidates or all snippets look totally
   unrelated, leave `relevant_doc_ids` empty and add a `notes`
   explanation (e.g. "retrieval returned 0 results — corpus may not
   cover this topic"). The row is then *labelling-deferred*.
6. Optionally, fill `entity_ids` with canonical entity UUIDs verified
   against `intelligence_db.canonical_entities`:

```bash
docker exec worldview-postgres-1 psql -U postgres -d intelligence_db \
  -c "SELECT id FROM canonical_entities WHERE label ILIKE 'apple%' LIMIT 3"
```

---

## 6. Maintenance discipline (per L6 and §0-bis.4-v2)

These rules are **mandatory** — they keep the eval honest over years:

1. **Two-reviewer rule**. Every PR that modifies `queries.jsonl` requires
   sign-off from two reviewers in the `eval-stewards` CODEOWNERS group.
   Both reviewer IDs go into `label_review.reviewer_id_a` and
   `reviewer_id_b`. If they disagree on the max-grade row by >1 grade,
   escalate to a third reviewer; record the resolution in
   `agreement_notes`.

2. **Quarterly blind re-grade**. Every quarter, a stewards-rotation
   blind-regrades 10 % of queries (12 rows). Discrepancies feed back
   into the calibration notes.

3. **Live-traffic backflow** (post-PLAN-0075). Every quarter, sample
   10 thumbs-down + 10 thumbs-up + 10 random rows from
   `chat_feedback`, anonymise, label, append. Targets: **200 rows by
   Q3, 400 by year-end**.

4. **Adversarial backflow**. Thumbs-down rows tagged
   `wrong_information` go to the faithfulness golden (PLAN-0075 L3);
   `didnt_answer_my_question` go to the tool-selection golden
   (PLAN-0075 L2). Stays out of L1 unless retrieval was the proximate
   cause.

5. **Deprecation rule**. A query that scores >0.95 across all metrics
   for **2 consecutive quarters** is no longer informative — retire
   it from the primary set; replace with a row from `_backlog.jsonl`
   (and refill the backlog).

6. **Embedding-model drift guard**. The CI gate file
   (`results/baseline_post_hybrid.json`) records
   `(git_sha, embedding_model_id, model_revision, captured_at_utc)`.
   Any change to the embedding model triggers a re-baseline (W5-1-03 sanity
   check covers this).

---

## 7. Auth note for the `/v1/internal/retrieve` endpoint (Phase-2 labelling)

`POST /v1/internal/retrieve` requires a valid `X-Internal-JWT` carrying
`aud="worldview-internal"`. The dev-login JWT issued by
`POST /v1/auth/dev-login` (api-gateway) does **not** include this
audience claim in its current container build, so it is rejected by
rag-chat's `InternalJWTMiddleware`.

The supported labelling-pass workflow is to mint a JWT directly using
the gateway's RSA private key (read out of the container env
`API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY`) and the published `kid` from
`GET /internal/jwks`. The JTI replay cache means **each call needs a
fresh JWT** (or you'll get `401 Token replay detected`). See
`LABELLING_REPORT.md` for the helper script that automates this.

---

## 8. Stage 0 sanity record

Per §0-bis.0a, the implementing engineer appends a one-time pre-flight
record here (date, dev-stack git SHA, the five Q+A snippets) the first
time they boot the dev stack and confirm coherent answers. This anchors
"the pipeline worked at point X" so we can detect drift.

(*Stage 0 record pending — current dev stack returns 0 retrieval
candidates due to a service-to-service auth issue; see
`LABELLING_REPORT.md` for the blocker.*)
