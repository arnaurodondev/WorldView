# W5-1 — Baseline-Capture Procedure (for W5-3 use)

**Date**: 2026-05-06
**Plan**: PLAN-0063 W5-1 / W5-3
**Status**: procedure documented; capture itself happens in W5-3

## Why this lives in W5-1

Per §0-bis.0 v2 lock **L3** of `docs/plans/0063-w5-hybrid-retrieval-eval-gate-plan.md`,
the baseline NDCG@10 is captured against the **post-hybrid** pipeline, not against the
current ANN-only pipeline. W5-1 ships the eval substrate (endpoint + script + CI
scaffolding + 120-query labelled set + precomputed embeddings) but **not** the captured
baseline. The captured baseline file lives at `results/baseline_pre_hybrid.json` and is
created in W5-3 after T-W5-3-01..03 land in dev.

This document is the runbook for that capture. It exists in W5-1 so the procedure is
reviewable now and so W5-3 doesn't have to re-derive it.

## Pre-conditions before running capture

1. The dev stack is up via `make dev`; **all** of the following containers are healthy:
   - `worldview-rag-chat-1` (running the W5-2/W5-3 image with hybrid path)
   - `worldview-nlp-pipeline-*` (chunk search returning > 0 results on a smoke query)
   - `worldview-api-gateway-1` (issues `aud="worldview-internal"` JWT — pre-existing
     stale containers had to be rebuilt; verified 2026-05-06)
   - Postgres `intelligence-postgres` and `nlp-postgres`
   - Valkey
2. W1+W2 data has been flowing for ≥24h. Confirm with:
   ```bash
   docker exec worldview-nlp-postgres-1 psql -U postgres -d nlp_db \
     -c "SELECT count(*) FROM chunks"
   ```
   Expected: ≥10K rows. If lower, halt and ask why before capturing.
3. `tests/eval/golden/queries.jsonl` is fully labelled (or at least 60+ queries with
   ≥5 graded candidates each + ≥1 relevance=3 row each). The labelling subagent
   produces a `LABELLING_REPORT.md` next to the queries — read it before capture.
4. `tests/eval/golden/query_embeddings.parquet` exists with one row per query
   (drift-checked via `query_text_sha256`). Regenerate if missing or stale:
   ```bash
   DEEPINFRA_API_KEY=<key> python scripts/generate_query_embeddings.py \
     --golden tests/eval/golden/queries.jsonl \
     --output tests/eval/golden/query_embeddings.parquet
   ```

## Capture procedure

```bash
# 1. Get a dev internal JWT
JWT=$(curl -sf -X POST http://localhost:8000/v1/auth/dev-login \
  -H 'Content-Type: application/json' -d '{}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

# 2. Run the eval against the post-hybrid path (W5-3 commit)
EVAL_INTERNAL_JWT="$JWT" \
  python scripts/eval_retrieval.py \
    --rag-url http://localhost:8008 \
    --golden tests/eval/golden/queries.jsonl \
    --query-embeddings tests/eval/golden/query_embeddings.parquet \
    --output-dir results/

# 3. Rename the latest output to the canonical baseline filename
LATEST=$(ls -t results/eval_*.json | head -1)
cp "$LATEST" results/baseline_pre_hybrid.json
git add results/baseline_pre_hybrid.json

# 4. Sanity-check the value
python -c "
import json
d = json.load(open('results/baseline_pre_hybrid.json'))
v = d['summary']['ndcg_at_10']['mean']
print(f'NDCG@10 = {v:.4f}')
assert 0.20 <= v <= 0.85, f'baseline outside expected range — review per OQ-W5-4'
print('OK: in expected range')
"
```

If the sanity check fails (NDCG outside `[0.20, 0.85]`), stop. Per OQ-W5-4 in the
plan, document the rationale and propose a re-validated `+lift` target before
proceeding to W5-3 commit.

## What the file looks like

`results/baseline_pre_hybrid.json` is the same shape as any `results/eval_<ts>.json`
but is the canonical reference for the W5-3 gate. Required keys checked by the CI
workflow's pre-flight step:

- `summary.ndcg_at_10.mean` — finite float > 0
- `git_sha` — set
- `embedding_model` — recorded for drift audits
- `n_queries_evaluated` — sanity (should be ≥60)

## Enabling the CI gate (W5-3 commit)

When W5-3 lands, edit `.github/workflows/retrieval-eval.yml`:

1. Remove `continue-on-error: true` from the `full-eval-disabled-gate` job step.
2. Add `--baseline results/baseline_pre_hybrid.json --fail-on-regression -0.05` to
   the eval-script invocation (negative threshold = required improvement floor; see
   T-W5-3-04 spec).
3. Rename the job from `full-eval-disabled-gate` to `full-eval-gate`.

## References

- PLAN-0063 §0-bis.0 v2 (L3) — anchor decision
- PLAN-0063 §0-bis.0a — Stage 0 pre-flight (must run BEFORE W5-1 commit)
- BP-235 — explicit httpx timeouts on the script (already wired)
- DEF-002 — JWT audience (=`worldview-internal`); api-gateway must issue it
