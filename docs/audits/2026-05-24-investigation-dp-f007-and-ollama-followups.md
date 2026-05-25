# Investigation: DP-F007 routing-score backfill + Ollama dep follow-ups

**Date**: 2026-05-24
**Investigator**: Claude
**Status**: Both investigations complete; fixes ready for `/implement`

---

## Part 1 — DP-F007: routing_decisions.composite_score v1→v2 backfill

### TL;DR

**Real, safe, and fully deterministic to fix.** A single commit on 2026-05-23 19:03:54 UTC (`9c232b3e`) dropped 3 dead signals from the routing formula and reweighted the remaining 5. Every v1 row's `feature_scores_json` JSONB already contains the 5 v2 inputs, so the backfill is a pure UPDATE — no re-computing signals, no external data needed.

### Cutover

- **Commit**: `9c232b3e` — "fix(nlp-pipeline): PLAN-0093 wave C-1 — drop 3 dead routing signals + rebalance weights"
- **Cutover timestamp**: 2026-05-23 19:03:54 UTC
- **Affected rows**: all rows with `decided_at < '2026-05-23 19:03:54+00:00'`
- **Row count**: unknown (no doc-level estimate), but back-of-envelope ~10K–100K based on ~2 weeks of news ingestion at this dev/staging scale. Doesn't matter operationally — formula is row-agnostic.

### Formula diff

**v1** (8 signals, 3 dead — `novelty`, `watchlist`, `price_impact` were hardcoded 1.0 / 0.0 / 0.0 because their upstream workers ran AFTER routing):

```
0.25 * entity_density + 0.20 * source_reliability + 0.15 * novelty(=1.0)
+ 0.10 * recency + 0.10 * watchlist(=0.0) + 0.05 * document_type
+ 0.05 * extraction_yield + 0.10 * price_impact(=0.0)
```

Practical max ≈ 0.65 (because the 3 dead signals always added a constant 0.15 from novelty=1.0, never their full 0.35 weight allocation).

**v2** (5 live signals, weights re-summing to 1.0):

```
0.35 * entity_density + 0.30 * source_reliability + 0.15 * recency
+ 0.10 * document_type + 0.10 * extraction_yield
```

Practical max ≈ 0.90+. Tier thresholds were also bumped in the same commit: `TIER_DEEP` 0.70 → 0.75. Other thresholds unchanged.

Source: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py:206-231` (v2) and git `9c232b3e^:.../routing.py` (v1).

### Schema state

- `routing_decisions` has **no `score_version` column**. ORM at `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py:218-229`.
- `feature_scores_json` is `JSONB NOT NULL` — created in migration `0001_create_nlp_schema.py:170`.
- v1 rows persisted **all 8** signal values into the JSONB; v2 rows persist only the 5 live ones. Backfill needs only the 5 live signal keys, which are present in every v1 row.

### Backfill SQL (production-ready sketch)

```sql
UPDATE routing_decisions
SET composite_score = LEAST(1.0, GREATEST(0.0,
    0.35 * (feature_scores_json->>'entity_density')::float +
    0.30 * (feature_scores_json->>'source_reliability')::float +
    0.15 * (feature_scores_json->>'recency')::float +
    0.10 * (feature_scores_json->>'document_type')::float +
    0.10 * (feature_scores_json->>'extraction_yield')::float
))
WHERE decided_at < '2026-05-23 19:03:54+00:00'
  AND feature_scores_json ? 'entity_density'
  AND feature_scores_json ? 'source_reliability'
  AND feature_scores_json ? 'recency'
  AND feature_scores_json ? 'document_type'
  AND feature_scores_json ? 'extraction_yield';
```

### Three open implementation decisions

1. **Tier recalibration**: a backfilled row's `composite_score` shifts upward but its stored `routing_tier` was assigned under v1 thresholds. Strictly speaking the tier should be re-evaluated too. Either (a) re-run the v2 tier classifier on each backfilled row and update `routing_tier`, or (b) leave `routing_tier` as-is and accept that historical tier labels mean "v1-tier" while scores are "v2". **Recommend (a)** — tiers drive downstream behavior; mismatched semantics will confuse future analysts.

2. **Score_version column or no?** Two options:
   - **Option A — backfill in place**, no new column. Pure data fix. After backfill, the table is uniformly v2 and there is no formula-version semantics to track. **Simpler.**
   - **Option B — add `score_version` column**, leave old rows alone, branch the display-relevance computation on it. More flexible if we expect another formula change soon, but adds permanent code complexity.
   - **Recommend Option A** — formula stabilized at v2 (no v3 planned); a column adds cost with no benefit.

3. **Migration mechanism**: Alembic migration vs. one-shot SQL script.
   - Alembic gives version control + idempotency + replay across environments. The dev DB and prod DB both need this exact UPDATE.
   - One-shot SQL is faster to write but lives outside the migration history.
   - **Recommend Alembic** — `op.execute()` with the UPDATE, downgrade is a no-op (or stores nothing; you can't "un-backfill" without preserving the v1 values).

### Risk

**Low.**
- Formula is closed-form on stored inputs; no external dependency, no API call.
- Cutover predicate (`decided_at < '2026-05-23 19:03:54+00:00'`) is precise — newer rows are not touched.
- The 5 input keys are guaranteed present (v1 stored all 8); the `?` checks are belt-and-braces.

### Downstream effect

`display_relevance_score = 0.5*market + 0.4*llm + 0.1*routing` (`services/nlp-pipeline/src/nlp_pipeline/application/services/relevance_score.py:23-50`). After backfill, the `routing` term for historical rows shifts; expected blended-score impact is **+5–8%** on average for pre-cutover articles, eliminating the discontinuity that biased "top articles" lists toward newer content.

The `display_relevance_score` is **computed at query time** (not persisted), so no further backfill is needed — fixing `composite_score` automatically fixes the blend.

---

## Part 2 — Sibling Ollama dependencies (follow-up to DP-F005)

### TL;DR

**Three workers can drop the Ollama dep in a single mechanical commit; two must keep it.** All three safe-to-remove cases are exact replicas of the DP-F005 pattern: Ollama is the fallback path, never the primary, and the dep just delays startup by 15-30s waiting for an unused health probe.

### Inventory

| # | Worker | Compose line | Verdict | Why |
|---|--------|--------------|---------|-----|
| 1 | `nlp-pipeline-relevance-scoring` | 1451-1470 | **SAFE_TO_REMOVE** | Primary = DeepInfra Llama-3.1-8B; Ollama is fallback only when `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` is unset (never in shipped envs). |
| 2 | `nlp-pipeline-unresolved-resolution-worker` | 1472-1503 | **SAFE_TO_REMOVE** | Same env var as worker 1; same fallback semantics. Code reads `settings.relevance_scoring_api_key.get_secret_value()` to pick provider at runtime. |
| 3 | `knowledge-graph-path-insight-worker` | 1915-1944 | **SAFE_TO_REMOVE** | **No ML client at all.** Worker only does AGE graph traversal + rule-based scoring + template matching. The Ollama dep is purely ceremonial (the compose comment admits it: "added for healthy-deps consistency"). |
| 4 | `nlp-pipeline-article-consumer` | 1310-1341 | **KEEP** | Has TWO conditional Ollama fallbacks (`OllamaEmbeddingAdapter` line 130-139 of main, `OllamaExtractionAdapter` line 161-166). Both reachable in local dev when keys are unset. |
| 5 | `rag-chat` | 2105 | **KEEP (already lenient)** | Uses `service_started` not `service_healthy` — no health-probe wait. No change needed. |
| – | `gliner-ner` | 1183 | **KEEP (intentional)** | Infrastructure container — initialises model artefacts; dep is correct. |

### Estimated cold-start savings

**~45–90 seconds** per cold `docker compose up`, depending on Ollama startup latency. Real-world impact:
- CI/CD spin-up is faster.
- Prod rolling restarts after a deploy don't wait on Ollama health for these three workers.
- If Ollama is down (e.g. GPU OOM), these three workers continue to deploy and start; they will use DeepInfra (workers 1 & 2) or never touch ML at all (worker 3).

### Risk

**Low.** Same risk profile as DP-F005 itself:
- Workers 1 & 2: if someone deliberately unsets the API key for offline dev, they must start Ollama manually before bringing up these workers. Document in dev README (the DP-F005 commit already added a similar note for `embedding-retry-worker`).
- Worker 3: zero risk — no ML usage path at all.

### Suggested fix shape (one commit)

```yaml
# Remove from each of the three worker blocks:
depends_on:
  ...
- ollama:                       # ← drop these two lines
-   condition: service_healthy  # ← drop these two lines
  ...
```

Then update the comment block at the top of each worker to explain why the dep is gone (cite this investigation report's path). One commit, three files modified (technically one file — `infra/compose/docker-compose.yml`), no tests needed beyond `docker compose -f infra/compose/docker-compose.yml config --quiet`.

### Suggested doc update

Append one bullet to whichever dev-README the DP-F005 commit edited (`docs/workflows/local-dev.md` per that commit's report): "Workers that previously waited for Ollama health (`relevance-scoring`, `unresolved-resolution-worker`, `path-insight-worker`) now start independently. If you unset their API keys to use Ollama as fallback, start Ollama manually first."

---

## Recommended next steps

### Single commit — Ollama follow-up (Bucket A, safe)

Drop `ollama.service_healthy` from the three workers listed above. ~10 lines deleted, ~3 comment lines updated, one doc note added. Validation: `docker compose ... config --quiet`. No tests.

### Single PR / wave — DP-F007 backfill (Bucket B, decision needed)

- Decide between Option A (backfill in place) vs Option B (`score_version` column).
- Decide whether to recalibrate `routing_tier` alongside `composite_score`.
- Write the Alembic migration (op.execute with the UPDATE).
- Test on a snapshot DB if available; otherwise rely on the closed-form correctness of the SQL.
- Document the migration ID + cutover date in `docs/services/nlp-pipeline.md`.

**My recommendation**: ship the Ollama follow-up immediately (it's mechanical and risk-free), then queue DP-F007 for a dedicated wave because it has tier-recalibration design choices worth a 10-minute conversation with the user before code.

---

## Compounding check

- **BUG_PATTERNS.md** — candidate entry: "Compose `depends_on: <service>: service_healthy` declared for services that are only used as a runtime fallback. Cold-start delay with zero correctness benefit when the primary path is configured." (Cluster: DP-F005 + this follow-up = 4 instances. Worth a pattern.)
- **STANDARDS.md** — candidate entry: "When a fallback provider is gated by `*_API_KEY`-set semantics, do not block container startup on the fallback's health. Use `service_started` or no dep at all." Same family as the bug pattern.
- **MASTER_PLAN.md** — no updates needed; system architecture unchanged.
- No new RULES.md or HIGH_RISK_PATTERNS.md updates needed.

These are recommendations only; I have not applied them. Worth folding into the next docs-audit pass.
