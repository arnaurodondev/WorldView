# CIKM Proposal — Ground-Truth Measurement & Reconciliation

> **Snapshot**: all live numbers as of **2026-06-24T06:00Z**, commit **`7d6e535fcb4e`** (branch `feat/frontend-enhancement-sprint`; working tree clean except `docs/cikm-proposal/` + presentation files — no code changes).
> **Instance caveat (carried into every number)**: the instance is **continuously deployed and not backfilled** after pipeline fixes, so the **stored graph accretes output from multiple extractor versions** (Qwen3-235B era + current gpt-oss-120b era). *Fresh-extractor* precision and *stored-graph* support are therefore different measurements and must never be conflated.
> Live DB: `intelligence_db` on `worldview-postgres-intelligence-1` (AGE graph `worldview_graph`).

---

## Step 4 — Evidence table (draft value vs computed value)

| # | Metric | Draft value | **Computed value (as-of above)** | Match? | Provenance |
|---|---|---|---|---|---|
| 1 | Canonical entities | ~17k | **28,794** | ❌ stale (~1.7× off) | `SELECT count(*) FROM canonical_entities` |
| 2 | Graph vertices | ~41k | **44,615** = entity **28,764** + TemporalEvent **15,851** (label `Entity`=0) | ⚠️ conflated entity+event; stale | AGE `worldview_graph.*` per-label counts; cypher `MATCH (n) RETURN count(n)` |
| 3 | Graph edges | ~14k | **15,448** AGE edges; materialized `relations` = **14,955** | ⚠️ close, stale | cypher `MATCH ()-[r]->() RETURN count(r)`; `SELECT count(*) FROM relations` |
| 4 | Entity mentions | ~99k | **248,047** | ❌ stale (2.5× off) | `nlp_db.entity_mentions` |
| 5 | Raw relation evidence | (n/a) | `relation_evidence_raw` = **100,020**; partitioned `relation_evidence` = **122,548** | — | counts |
| 6 | Ingest rate | ~2,400/day | **3,194 / last 24h**; **14,427 / last 7d** (≈2,060/day) | ⚠️ within range; state window | `content_store_db.documents.ingested_at` (total 59,259) |
| 7 | LLM cost | (none) | **$16.81 / 30d** (113,193 calls); $5.78 / 7d | ✅ new | `intelligence_db.llm_usage_log.estimated_cost_usd`. *Caveat:* `nlp_db` ledger logs $0 (self-hosted NER/embeddings) — metered API only |
| 8 | Stored-graph support | **27.6%** | **36.9% predicate-balanced** (95% CI 32.2–41.9%) / **48.8% volume-weighted**; n=382 | ❌ 27.6% superseded | `scripts/eval/remeasure_stored_relation_quality.py`, verdicts persisted; **judge = Qwen3-235B** (LLM, not human); 2026-06-20 |
| 9 | Dominant defect | **co-mention 45.7%** | **UNSUPPORTED 36.6% + WRONG_DIRECTION 14.7%**; CO_MENTION only **8.6%** (33/382); WRONG_PREDICATE 3.1% | ❌ wrong under current measurement | same audit; SUPPORTED 141 / UNSUP 140 / WRONG_DIR 56 / CO_MENT 33 / WRONG_PRED 12 |
| 10 | Fresh-extraction precision | 5.0/5 | **5.0/5** gpt-oss-120b@medium vs 4.4 Qwen; n=**17 articles / 32 relations**; ~29% api_error under load | ✅ (small-n caveat) | `scripts/eval/extraction_quality_eval.py` / `gate_residual_ab.py`; **judge DeepSeek-V4-Flash**, temp 0 |
| 11 | Deterministic gates | 442 removed; listed_on→86% | **442** invalid `listed_on` removed from graph; raw flagged **5,719 self-loops + 1,133 invalid listed_on** of 100,217; `listed_on`→**86%**; gate now **0/32 drops** on live model (regression guarantee) | ✅ | `relation_validation.py` (committed, 40 unit tests); audit 2026-06-18 |
| 12 | Grounding ablation | 1.83→0.17 | **1.83→~0.25** (Qwen+news) / **1.58→0.17** (gemini); n=**18 obscure persons**; **AUDIT-ONLY, NOT DEPLOYED** | ❌ misleading as system property; 0.17 is gemini | `results/desc_grounding_eval/eval.py` (staged news stand-ins); judge DeepSeek-V4-Flash; 2026-06-17 |
| 13 | Judge calibration (κ) | (implied validated) | **κ = 0.59 DRAFT** (agent-labelled, **not** human; below 0.7 bar); gold set n=**39** | ❌ not citable | `scripts/chat_quality_calibration.py`; gold set frozen, human labels pending |
| 14 | Judge failure examples | "85/100, 100/100" | **Real & logged** (pre-fix all-green run 2026-06-09): fabrication-flagged answer PASSed; raw-error string scored full marks; leaked tokens 90–100 | ✅ as illustrations | `tests/validation/chat_quality_benchmark/runs/`; v3 fixes: grounding floor 12, degenerate pre-checks, failure-first |
| 15 | Graph latency / speedup | 18.4s→240ms (76×) | **Live naive EXPLAIN ANALYZE: explicit 144,807 ms; VLE 5,429 ms → ≈27×.** 76× / 240ms **NOT reproduced this pass** (those need the production pruned+hop-capped engine path) | ❌ unverified as stated | live EXPLAIN ANALYZE on `worldview_graph` vertex 9288674231451649; audit numbers from `scripts/eval/measure_maxhops_pruned.py` (not re-run) |
| 16 | Benchmark stability | (none) | **NO ARTIFACT** — k-run churn never measured | n/a | — |
| 17 | Citation faithfulness | (none) | **NO ARTIFACT** — only a numeric-grounding validator exists, not a citation-faithfulness judge | n/a | `services/rag-chat/.../numeric_grounding.py` |

### The two flagged draft numbers, resolved
- **"41k vertices / 14k edges"**: partially supported but **stale and conflated**. Correct as-of figures: **44,615 vertices (28,764 entity + 15,851 temporal-event)**, **15,448 graph edges / 14,955 materialized relations**. Do not say "41k entities" — entity vertices are ~28.8k; the 41–45k total includes event vertices.
- **"76×"**: **not reproduced.** Live naive measurement gives **≈27×** (145 s vs 5.4 s), and absolute VLE latency is **seconds, not 240 ms**, for a naive query. The 76×/240 ms figures belong to the production engine's pruned/hop-capped path and must be re-measured with `measure_maxhops_pruned.py` before any use.

---

## Step 5 — Classification

### [VERIFIED, CITABLE] — safe for an archival abstract
- Scale: **28,794 canonical entities**; **44,615 graph vertices (28,764 entity + 15,851 temporal-event)**; **15,448 edges / 14,955 materialized relations**; **248,047 entity mentions**; **100,020 raw relation-evidence rows**.
- Throughput: **~2,000–3,200 articles/day** (24h = 3,194; 7d = 14,427).
- Operating cost: **≈ $17 / 30 days** metered LLM spend (self-hosted NER/embeddings excluded).
- **Stored-graph support: 48.8% volume-weighted / 36.9% predicate-balanced** (n=382, LLM-judge Qwen3-235B), with defect mix **UNSUPPORTED 36.6% / WRONG_DIRECTION 14.7% / CO_MENTION 8.6%**.
- **Fresh-extraction precision 5.0/5** (n=17 art./32 rel., DeepSeek judge) — *explicitly contrasted* with stored support; small-n.
- **Deterministic gates**: 442 graph rows removed; `listed_on`→86%; 0/32 live drops (regression guarantee).
- **Judge hardening** (grounding veto / degenerate pre-checks / failure-first) and the **real logged failure examples** that motivated it (qualitative, no κ).
- **Explicit-traversal pathology** (~145 s for one naive 1-hop) as the motivation for variable-length traversal — qualitative.

### [REAL BUT NOT YET REPRODUCIBLE THIS PASS] — talk only / "measurement underway", NOT the abstract
- **76× / 240 ms VLE / p50 103 ms / p95 248 ms (maxhops≤3)** — exist in the committed benchmark + 2026-06-12 audit but were **not re-run**; naive live repro disagrees. Re-run `measure_maxhops_pruned.py` to citably restore.
- **Grounding 1.83→0.17/0.25** — audit-only, n=18, **not deployed**. Frame as "validated offline; deployment underway," never as a live property.
- **Judge κ = 0.59** — draft, sub-threshold, human labels pending.

### [NOT COMPUTABLE] — do not claim
- Benchmark run-to-run stability (k-run churn): no artifact.
- Citation-faithfulness gauge: no artifact.

---

## Step 7 — Numbers to gather/commit BEFORE submission (couldn't verify this pass)
1. **Re-run `scripts/eval/measure_maxhops_pruned.py`** on the current `worldview_graph` to get citable production p50/p95 pairwise latency and the *real* current speedup — then either restore a (smaller, honest) speedup figure or keep latency qualitative.
2. **Human-label the 39-item gold set** and re-run `chat_quality_calibration.py` to get a citable κ (target ≥0.7). Until then, no κ in print.
3. **Decide grounding-ablation framing**: either deploy news-grounding to `DefinitionRefreshWorker` and re-measure on the live corpus (makes 1.83→0.25 a real system result), or keep it strictly as "offline-validated, deployment underway."
4. **Confirm fresh-extraction precision on a larger n** (current n=17 is underpowered); a 50–100 article run would harden the 5.0/5 vs 36.9% contrast.
5. **Pick the stored-support headline**: volume-weighted (48.8%, user-experienced) vs predicate-balanced (36.9%, harsher) — state both, lead with one, and label the judge as LLM (Qwen3-235B), not human.

---

# ADDENDUM — Four-gap resolution (measured 2026-06-24T07:30Z, SHA 7d6e535f)

## Task 1 — Apples-to-apples headline (PRIORITY FINDING: gap shrinks but survives)
Re-judged the FRESH gpt-oss-120b sample (46 relations, model_switch_ab/model_runs.json) with the IDENTICAL Qwen3-235B binary "document-supported" rubric used for the 382 stored relations.
- **Fresh: 38/46 = 82.6% supported** (Clopper–Pearson 95% CI 68.6–92.2%; one-sided lower 70.8%). Breakdown: SUPPORTED 38, CO_MENTION 3, UNSUPPORTED 3, WRONG_DIRECTION 2.
- **Stored: 36.9%** predicate-balanced (same judge/rubric).
- **Finding**: the original "5.0/5 vs 37%" overstated the gap — that was DeepSeek 1–5 mean vs Qwen binary. Same-judge/same-rubric truth = **82.6% fresh → 36.9% stored ≈ quality halves**. Gap is real and large but ~2×, not "perfect→37%". Script: scratchpad t1/rejudge_fresh.py + remeasure_stored_relation_quality.py judge.

## Task 2 — Audit-judge spot-validation (artifact built; κ pending)
Stratified fresh draw (≤2/predicate, n=64), evidence-fetched, judged by same Qwen3-235B.
- **Independent corroboration**: 23/64 = **35.9% supported** ≈ the 36.9% headline. Breakdown UNSUP 23 / SUP 23 / WRONG_DIR 9 / CO_MENT 7 / NO_EVID 2.
- **Labeling sheet**: `docs/cikm-proposal/task2_judge_validation_sheet.md` — ready for author to label; κ (agree% + Cohen's κ) computed once labels filled. NOTE: fresh draw (original 382 verdict file not persisted), validates same judge on same population, not identical rows.

## Task 3 — Latency (CLAIM KILLED)
Naive 1-hop (confirmed 1-hop, vertex 9288674231451649): explicit **144,807 ms** vs VLE **5,429 ms ≈ 27×**.
Production pruned/hop-capped benchmark (measure_maxhops_pruned.py, runs=3, maxhops=3, live graph):
- pairwise **p50 1,473 ms / p95 17,360 ms**; anchor **p50 11,020 ms / p95 28,274 ms** — FAILS the script's own interactive bar (pairwise p95<1000ms); one query hit statement timeout.
- **Finding**: the 2026-06-12 audit's 60–800ms no longer holds (graph grew 33.3k/10k → 44.6k/15.4k; pruning/ANALYZE stale). Graph traversal is currently a PERFORMANCE WEAKNESS, not a feature. Drop "interactive budget"; frame as open scaling problem.

## Task 4 — Cost scope (SOFTEN)
- intelligence_db ledger 30d: extraction(DeepInfra) **$16.78** / 80,453 calls; embedding(Ollama) **$0** (self-hosted).
- nlp_db ledger 30d: **67,549 calls all logged $0.00** — including real DeepInfra models (gpt-oss-120b, Qwen3-235B, DeepSeek-V4-Flash, Llama-3.1-8B). Cost field unpopulated → **true metered spend > $17, not cleanly computable this pass**. Self-hosted GLiNER/embeddings genuinely ~$0 marginal. → cost claim softened to "≈$17/30d metered, some calls not cost-attributed."

## Classification (this pass)
- **[verified, citable]**: fresh 82.6% (CP CI), stored 36.9%/48.8%, defect mix, the 35.9% corroboration, naive 27× (145s vs 5.4s), pruned pairwise p50/p95 (1.5s/17.4s), intelligence-ledger $16.78/30d.
- **[real but not reproducible/clean]**: true total metered cost (ledger gap); audit-judge κ (needs human labels).
- **[not computable]**: benchmark stability, citation faithfulness (no artifact, unchanged).
