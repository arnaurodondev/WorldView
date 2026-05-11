# Evaluation Layer — Design Investigation

**Date**: 2026-04-30
**Investigator**: Claude (investigation skill, 5 parallel research streams)
**Type**: Design proposal (not a bug investigation)
**Scope**: How the worldview evaluation layer should be designed for a thesis-grade financial RAG + Knowledge Graph system
**Sources**: Academic (29 papers), industry (16 vendors), cross-domain (10 fields), worldview-internal code, production ops practices
**Successor to**: `2026-04-30-retrieval-graph-architecture-revised.md` §3.3 (M-3 eval framework recommendation)
**Feeds**: `docs/plans/0058-retrieval-and-kg-strategic-uplift-plan.md` Wave C — supersedes the current 5-task spec there.

---

## 0. Executive Verdict

The current PLAN-0058 Wave C eval spec ("50-query golden set, NDCG@10 + MRR + P@5") is **directionally correct but narrow**. It treats evaluation as a single-leaderboard exercise. The right evaluation layer is **eight-dimensional** and **five-layered**, drawing from communities that have spent 30+ years on problems structurally identical to ours (TREC IR, recommender systems, medical diagnostics, quantitative finance backtesting, educational testing).

**Three guiding principles**:

1. **Evaluation is plural**, not a single number. A retriever can be best-in-class on factoid lookup and worst-in-class on relationship reasoning. A single average always lies.
2. **Statistical discipline first, then volume.** ARES + Prediction-Powered Inference (Saad-Falcon et al., NAACL 2024 + Angelopoulos & Bates, *Science* 2023) gives us valid 95% confidence intervals from 200–500 labels. This is more defensible for a thesis than 5,000 unverified silver labels.
3. **Borrow from outside NLP.** The most undervalued techniques (metamorphic testing, point-in-time walk-forward, ECE calibration, item-response theory, skill scores over naive baselines) come from software testing, quantitative finance, medical diagnostics, educational testing, and weather forecasting. Adopting them is the single biggest differentiator vs. a generic "RAGAS in CI" eval.

**The eight-dimension framework** (each row gets primary metrics + measurement method):

| # | Dimension | Question it answers | Primary metric(s) | Source community |
|---|---|---|---|---|
| 1 | **Retrieval relevance** | Did we retrieve the right candidates? | NDCG@10, MRR, Recall@30 (per intent) | TREC / IR canon |
| 2 | **Generation faithfulness** | Is the answer grounded in retrieved context? | RAGAS faithfulness, ALCE citation F1 | RAG academic |
| 3 | **Citation correctness** | Do citations support the specific claims they're attached to? | Per-claim citation precision/recall, with **negative points for fabricated citations** | Harvey BigLaw Bench |
| 4 | **KG structural quality** | Is the graph self-consistent and well-typed? | Constraint-violation count, type/symmetry/inverse violations | Wikidata constraints |
| 5 | **KG semantic coverage** | Does the graph contain the entities/relations users ask about? | Per-class coverage ratio, metapath density | Hetionet (biomedical KG) |
| 6 | **Calibration** | When the system is confident, is it right? | ECE (binned + adaptive), Brier score, abstention–accuracy curve | Medical diagnostics, autonomous driving |
| 7 | **Robustness** | Does quality survive paraphrase, time-shift, adversarial input? | Metamorphic-relation pass rate, prompt-mutation sensitivity | Software testing, RGB benchmark |
| 8 | **Efficiency** | What's the quality–latency–cost Pareto? | NDCG@10 vs. p95 latency vs. $/query | Database optimizer benchmarking |

The current `NDCG@10 + MRR + P@5` plan covers only Dimension 1. Dimensions 2 and 6 are essential for a finance product. Dimensions 3, 4, 5, 7, 8 are what move the thesis from "passing" to "publishable."

---

## 1. State of the Art Synthesis

### 1.1 Academic frame (what the field measures)

The dominant reference-free RAG framework is **RAGAS** (Es et al., EACL 2024, [arXiv:2309.15217](https://arxiv.org/abs/2309.15217)) — four sentence-level metrics: faithfulness, answer relevancy, context precision, context recall. WikiEval inter-annotator agreement: ~95% on faithfulness, ~90% on answer relevancy. Limitation: brittle on numeric/tabular text — important for finance. **ARES** (Saad-Falcon et al., NAACL 2024, [arXiv:2311.09476](https://arxiv.org/abs/2311.09476)) is the methodological upgrade: fine-tunes a small LM judge on synthetic triples, then uses **Prediction-Powered Inference** (Angelopoulos & Bates, *Science* 2023) to convert noisy judge predictions into provably valid CIs from a few hundred human labels. **This is the right shape for a thesis with a small labeling budget.**

For multi-hop and KG-augmented RAG, **MSR GraphRAG / BenchmarkQED** (Edge et al., 2024, [arXiv:2404.16130](https://arxiv.org/html/2404.16130v1)) introduces a four-dimension rubric tailored to graph synthesis: **Comprehensiveness, Diversity, Empowerment, Relevance**. GraphRAG wins ~70-80% of pairwise comparisons over naive RAG on global queries (synthesis questions); on factoid queries the win rate evaporates. Implication: **separate eval suites for factoid vs synthesis intents** — pooling them hides the real signal.

For citation-grounded answers, **ALCE** (Gao et al., EMNLP 2023, [arXiv:2305.14627](https://arxiv.org/abs/2305.14627)) is the de facto benchmark; best models miss citation support 50%+ of the time on ELI5. For finance, where every claim needs a source link, this is non-negotiable.

For KG quality specifically, **Paulheim's survey** (*Semantic Web* 2017) distinguishes completion (recall) from error detection (precision); **Färber et al.** (*Semantic Web* 2018) provides the standard human-review protocol; **Hetionet** (Himmelstein et al., *eLife* 2017) provides the metapath-density methodology — directly transferable to financial KGs (e.g., Company → executive → Company; Holding → Fund → Holding).

For retrieval calibration, the radiology / medical-AI tradition wins. **ECE** (Naeini et al., AAAI 2015; Guo et al., ICML 2017) measures whether stated confidence matches empirical accuracy; **adaptive ECE / class-wise ECE** (Nixon et al., CVPRW 2019) handle binning artefacts. For a system that says "high confidence" on a dollar figure, ECE is the metric that catches overconfident hallucination.

The single most important bias paper on LLM-as-judge: **Zheng et al.** (NeurIPS 2023, [arXiv:2306.05685](https://arxiv.org/abs/2306.05685)) catalogs four biases — position, verbosity, self-enhancement, limited reasoning — and shows mitigations (pairwise swap, multi-judge aggregation, calibrated reference answers) that close most of the gap to humans. **Huang et al.** ([arXiv:2403.02839](https://arxiv.org/html/2403.02839v2)) is the warning: fine-tuned judges (JudgeLM, Auto-J, Prometheus) close most of the gap **in-domain** but degrade on OOD prompts. For thesis defense: budget GPT-4-class judging on a 200–500-item gold set, distilled-judge for daily regression, ARES/PPI to bound bias.

### 1.2 Industry frame (what shipping companies do)

- **OpenAI evals** ([github.com/openai/evals](https://github.com/openai/evals)): registry-based YAML+jsonl per task; `modelgraded/closedqa.yaml` rubric ("Is the submission grounded?") is directly portable.
- **Anthropic** ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) + [statistical approach](https://www.anthropic.com/research/statistical-approach-to-model-evals)): "20–50 simple tasks drawn from real-world failures because early changes have large effect sizes; combine multiple grader types; **always read the transcripts**; report **clustered standard errors when tasks share themes**." Bloom (agent-as-evaluator) lets a synthetic user simulate multi-turn conversations and grade end-state.
- **Google Vertex AI** ([adaptive rubrics docs](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/rubric-metric-details)): per-prompt **adaptive rubrics** — autorater first reads the prompt and generates a custom pass/fail checklist, then scores. Single highest-leverage idea for finance Q&A. **E-E-A-T** (Google Search Quality Rater Guidelines, 182-page playbook) maps to financial source quality.
- **Microsoft / GraphRAG**: Comprehensiveness, Diversity, Empowerment, Relevance with **counterbalanced pairwise comparison** (swap order to control position bias).
- **Cohere / Pinecone / Vespa / Elastic / Weaviate**: standardized on the IR canon (NDCG@10, Recall@30, MRR). Vespa's pipeline is exemplary: **LLM-as-a-judge → labeled qrels → GBDT learning-to-rank → `trec_eval` validation**. Elastic's `_rank_eval` REST endpoint is a production-ready primitive.
- **LlamaIndex / LangSmith / Haystack**: converge on retrieval-vs-generation eval split + labeled-vs-label-free split. LangSmith versioned datasets + `client.evaluate(...)` with pairwise-compare is the right ergonomics target.
- **Bloomberg GPT** ([arXiv:2303.17564](https://arxiv.org/abs/2303.17564)): public financial benchmarks (FPB, FiQA SA, Headline, Fin-NER, ConvFinQA) + internal benchmarks mirroring terminal usage + standard LLM benchmarks (BIG-Bench Hard, MMLU). Layered evaluation, not a single number.
- **Harvey BigLaw Bench** ([blog](https://www.harvey.ai/blog/introducing-biglaw-bench)): convert real expert work into eval tasks; rubric = Answer Quality + Source Reliability with **negative points for fabricated citations**. **This is the single most adoptable industry pattern for our case** — finance and law share the "wrong with confidence is worse than uncertain" property.
- **Glean** ([blog](https://www.glean.com/blog/glean-ai-evaluator)): no good public benchmarks for enterprise search; built proprietary AI Evaluator validated against humans at **74% agreement** — useful threshold for our LLM-as-judge.
- **Search-engine ranker eval** (Microsoft Research / Airbnb / Cornell): four eval modes — offline TREC, online A/B, online interleaved (~100× more sensitive than A/B), counterfactual / off-policy from logs (IPS, SNIPS, doubly robust). For thesis (no traffic), modes 1 and 4 apply.

### 1.3 Cross-domain frame (what the field is *not* using yet)

The eight most-undervalued techniques (full justifications in §3 below):

| # | Technique | Source field | Why undervalued in RAG eval |
|---|---|---|---|
| 1 | **Metamorphic testing** of retrieval invariants | Software testing | Oracle-free; thousands of checks without a golden set. RAG community fixated on golden sets. |
| 2 | **Walk-forward eval with point-in-time correctness** | Quantitative finance | Look-ahead bias silently inflates every temporal RAG benchmark in the literature. Mandatory for finance. |
| 3 | **Calibration metrics (ECE, Brier, reliability diagrams)** | Medical diagnostics | RAG papers report accuracy but not calibration; users get burned by overconfident hallucinations. |
| 4 | **Item Response Theory** (query difficulty + retriever ability) | Educational testing | Decomposes mean-score confounds; **zero RAG papers use it** — strong thesis-novelty contribution. |
| 5 | **Counterfactual / off-policy eval** (IPS, SNIPS) | Recommender systems | Cuts iteration cost dramatically; ignored because RAG community lacks RecSys background. |
| 6 | **Abstention–accuracy frontier** | Autonomous driving | Honest curve, not single accuracy point. Track "I don't know" rate vs. accuracy on answered. |
| 7 | **Mutation testing applied to prompts and rubrics** | Software testing | Validates the *eval itself* — almost no one tests their evaluator's robustness. |
| 8 | **Skill score over naive baselines** (climatology + persistence) | Weather forecasting | Strips "looks impressive but a trivial baseline does 90% of it" — chronic RAG-paper weakness. |

### 1.4 Worldview-internal frame (what we already have)

The platform exposes 8 evaluable surfaces (verified in code, audit-04-30):

- **S6 NLP pipeline** — 11 blocks: NER (GLiNER 11 classes), 4-stage entity resolution, embeddings (BGE 1024-dim), deep extraction (Llama-3.1-8B), routing (8 signals)
- **S7 Knowledge Graph** — 8 endpoints: cypher neighborhood, cypher path, search relations, similar entities, claims, temporal events, contradictions, entity graph
- **S8 RAG-Chat** — 9 retrieval sources (chunks ANN, relations, egocentric graph, claims, events, contradictions, financial, portfolio, Cypher), 8 query intents (`FACTUAL_LOOKUP`, `GENERAL`, `COMPARISON`, `FINANCIAL_DATA`, `PORTFOLIO`, `REASONING`, `RELATIONSHIP`, `SIGNAL_INTEL`), Cohere/BGE reranker, DeepSeek-R1 32B generation
- **2,443 test files** already in place (unit + integration + architecture + e2e + contract)
- **Prometheus metrics** in 8 services, ready to extend
- **Data assets**: 3,233 articles, 2,839 sections, 18,695 mentions, 83 canonicals, 38 aliases, 6 claims, 7 events, 18 seeded relations (all per audit-04-30 row counts)

The lesson: **the eval framework can ride on existing infra (tests, Prometheus, Postgres, Kafka)** — no new infrastructure needed in Phase 1.

---

## 2. The Five-Layer Evaluation Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 5: User feedback (citation relevance, intent correction)    │   Online, sparse, gold-standard
├──────────────────────────────────────────────────────────────────┤
│ Layer 4: Streaming live metrics (Prometheus)                      │   Online, dense, sampled
├──────────────────────────────────────────────────────────────────┤
│ Layer 3: Golden-set evaluation + LLM-as-judge + ARES/PPI         │   Offline batch, weekly/nightly
├──────────────────────────────────────────────────────────────────┤
│ Layer 2: Property-based + metamorphic + KG constraint tests       │   CI, every PR, oracle-free
├──────────────────────────────────────────────────────────────────┤
│ Layer 1: Existing unit + integration + architecture tests         │   CI, every commit, deterministic
└──────────────────────────────────────────────────────────────────┘
```

Each layer answers a different question and runs at a different cadence. **Skipping layers is what produces fragile evaluation; running every layer on every commit is what produces broke teams.**

### Layer 1 — Existing tests (already shipped)

2,443 test files. Already runs on every commit. Not modified by this proposal.

### Layer 2 — Property-based + Metamorphic + KG-Constraint Tests

**Cadence**: Every PR. **Cost**: free (no LLM calls). **Coverage**: oracle-free invariants.

**Sub-layer 2a — Metamorphic relations** (the highest-leverage cross-domain technique):

```python
# tests/eval/metamorphic/test_retrieval_invariants.py
@metamorphic
def test_paraphrase_overlap(retriever):
    """Paraphrasing a query should preserve ≥70% of top-10 results."""
    for q, q_paraphrase in PARAPHRASE_PAIRS:  # 100 hand-curated or LLM-generated pairs
        a = set(d.id for d in retriever.search(q, k=10))
        b = set(d.id for d in retriever.search(q_paraphrase, k=10))
        assert len(a & b) / len(a) >= 0.70, f"low overlap: {q} vs {q_paraphrase}"

@metamorphic
def test_ticker_alias_consistency(retriever):
    """retrieve('AAPL ...') and retrieve('Apple ...') should overlap ≥80%."""
    for ticker, name in [("AAPL", "Apple"), ("TSLA", "Tesla"), ...]:
        ...

@metamorphic
def test_temporal_monotonicity(retriever):
    """For stable facts (e.g., 'Apple founded'), retrieve(Q, t) ⊇ retrieve(Q, t-1h)."""
    ...

@metamorphic
def test_no_lookahead(retriever):
    """No retrieved chunk should have published_at > query.as_of."""
    for q in TEMPORAL_QUERIES:
        for d in retriever.search(q.text, as_of=q.as_of):
            assert d.published_at <= q.as_of, "look-ahead bias detected"
```

These are **oracle-free** — they don't need a golden answer. They catch the bugs RAG benchmarks miss: the audit's F-CRIT-07 silent-drop pattern (BP-292/293), look-ahead bias, alias-graph asymmetry. ~50 metamorphic relations cover the system in one afternoon of work.

**Sub-layer 2b — KG constraint queries** (Wikidata-style):

```sql
-- evals/kg_constraints/c001_company_country.sql
-- Constraint: every Company canonical_entity must have a country property OR an alias of a known parent
SELECT entity_id, canonical_name
FROM canonical_entities
WHERE entity_type = 'organization'
  AND metadata->>'country' IS NULL
  AND entity_id NOT IN (
    SELECT subject_entity_id FROM relations WHERE canonical_type IN ('subsidiary_of', 'subsidiary')
  );
-- expected: 0 rows
```

10–15 constraints, scheduled hourly via cron, results to a `kg_quality_violations` table. Pinterest's "≥99% of pins map to ≥1 node" pattern: track `% of articles with ≥1 entity resolved` (currently 34% per 04-29 audit — already a constraint violation) and `% of canonicals with ≥1 outgoing edge` as headline KG-quality KPIs.

**Sub-layer 2c — Property-based tests** (Hypothesis library):

```python
@given(query=text(min_size=3), as_of=datetimes())
def test_retriever_never_crashes(retriever, query, as_of):
    result = retriever.search(query, as_of=as_of)
    assert all(isinstance(d.score, float) for d in result)
    assert all(0 <= d.score <= 1 for d in result)  # score normalization invariant
```

### Layer 3 — Golden-set evaluation (the heart of the framework)

**Cadence**: nightly (cheap eval) + weekly (full eval). **Cost**: $20–$200/week LLM-judge.

**Composition** (8 dimensions, each with own gold set):

| Dimension | Gold-set size | Source | Annotator |
|---|---|---|---|
| 1. Retrieval relevance | 100 queries × 4-grade relevance on top-30 | Hand-curated (50) + production logs (50) | Author + 1 finance student |
| 2. Generation faithfulness | Same 100 queries × answers | LLM-judge (RAGAS faithfulness) + 30-query human sample for ARES/PPI calibration | Llama-3.1-8B + 1 human |
| 3. Citation correctness | 50 finance-analyst questions × Harvey rubric | Hand-curated, modeled on real buy-side analyst questions | Author |
| 4. KG structural quality | Hourly cron over constraint catalog | Auto | None |
| 5. KG semantic coverage | Per-class coverage, metapath density on 200 known relations | Wikipedia infoboxes + SEC 10-K cross-reference | Auto + 4h author review |
| 6. Calibration | 100 retrieval results × confidence | Same as Dim 1 | Auto from Dim 1 labels |
| 7. Robustness | RGB-style 4-axis (noise/negation/integration/counterfactual) × 50 ea = 200 | LLM-generated, 20% spot-check | Llama-3.1-8B + 4h author review |
| 8. Efficiency | Latency/cost histogram on Dim 1 queries | Auto | None |

Total **300 hand-labeled items + ~600 auto/silver labels**. Realistic for a thesis (~25 hours of labeling).

**Methodology — the four non-negotiables**:

1. **ARES + Prediction-Powered Inference** for Dimensions 2 and 6. Train a small judge (Llama-3.1-8B, distilled from GPT-4 if budget allows). Use PPI to convert noisy judge labels into 95% CIs from ~300 human labels. Report intervals, not point estimates. This is what makes the thesis defensible against "your eval is biased by the judge."

2. **Per-intent stratification.** Never report a single average across the 8 query intents. Always break out by intent (and by `source_type` for retrieval). GraphRAG wins on synthesis intents and loses on factoid; pooling them lies.

3. **Pairwise comparison with counterbalanced order.** Whenever comparing two retrievers/rerankers/prompts, swap order between trials. Position bias is GPT-4's biggest tell (Zheng et al. 2023). LMSYS shows pairwise needs ~10× fewer judgments than absolute scoring for same statistical power.

4. **Skill score over naive baselines.** Every metric reported as `(actual − naive) / (oracle − naive)`. Naive baselines: BM25-only, random-relevant-sample, "always answer with last-news-headline." If a sophisticated retriever doesn't beat the naive by ≥0.05, the complexity is unjustified.

**LLM-as-judge cost engineering**:
- Cache by `(prompt_template_hash, input_hash, model_id)` — exact-match cache hits ~10%, semantic-cache (cosine 0.97) ~50%
- Confidence-routed escalation: cheap judge first, escalate to GPT-4-class only when log-prob of chosen label < 0.7 OR multi-pass disagreement
- Hard daily $ cap with Slack alert at 80% (a runaway re-judge loop will eat $500 in an afternoon)
- Multi-judge ensemble (3 judges majority) only on the weekly thesis report, single judge for nightly

### Layer 4 — Streaming live metrics

**Cadence**: continuous. **Cost**: trivial. **Output**: Prometheus + Grafana panels.

Hooks already exist (`services/*/src/*/infrastructure/metrics/prometheus.py`); we add seven gauges/histograms to make eval observable in production:

- `eval_retrieval_ndcg_p50{source_type, intent}` (recomputed nightly from Layer 3)
- `eval_kg_extraction_yield{stage}` (already in PLAN-0057 Wave A scope)
- `eval_kg_coverage_ratio{entity_class}` (already in PLAN-0057 Wave A scope)
- `eval_kg_constraint_violations_total{constraint_id}` (Layer 2b)
- `eval_calibration_ece` (rolling 7-day windowed ECE)
- `eval_abstention_rate` (% of queries where LLM said "insufficient context")
- `eval_judge_disagreement_rate` (multi-judge variance signal)

Grafana panels with **annotations** for every prompt/model/golden-set change. When NDCG drops on May 12, the annotations show: "prompt v3.1 → v3.2 deployed" — that's the lineage you need.

### Layer 5 — User feedback

**Cadence**: as users use the product. **Cost**: frontend dev time + storage.

Two thin instrumentations on `apps/worldview-web/components/chat/`:

1. **Per-citation thumbs up/down** next to `CitationBar.tsx`. Persists to new table `chat_citation_feedback (citation_id, user_id, thread_id, feedback enum, created_at)`. Aggregated nightly into Layer 4.
2. **Intent confirmation** chip after classification: "Detected intent: FINANCIAL_DATA — was this what you wanted?" Y/N. Persists to `chat_intent_feedback`.

For a thesis with limited live traffic, Layer 5 is a "future-proofing" investment — schema and APIs in place, scoring kicks in once there's signal. The **implicit signal** that matters now: log every query reformulation (user asks Q, then asks Q' within 60s of receiving answer); reformulation = retrieval probably failed. This is free and has been the bedrock of search-engine eval for 20 years.

---

## 3. Top 10 Adoptable Techniques (Ranked, Opinionated)

Compiled from across the five research streams. Each rated for thesis-grade impact and effort.

| Rank | Technique | Source | Adopt | Effort | Value | Why |
|---|---|---|---|---|---|---|
| **1** | **Metamorphic testing of retrieval invariants** (paraphrase overlap, ticker/name consistency, temporal monotonicity, no-lookahead) | Software testing | **Now** | Low | Very high | Oracle-free; 50 invariants in one afternoon catch F-CRIT-07-class bugs that golden sets miss |
| **2** | **Walk-forward eval with point-in-time correctness** (every chunk has `valid_from`, query carries `as_of`, retriever filters) | Quantitative finance | **Now** | Medium (schema change) | Very high | Without this, every temporal RAG benchmark in finance is silently overstating quality. Non-negotiable for thesis defense |
| **3** | **Harvey BigLaw Bench rubric**: real analyst questions + Answer Quality + Source Reliability + **negative points for fabricated citations** | Legal AI industry | **Now** | Medium (50 hand-curated questions) | Very high | Single highest-leverage industry pattern for finance; aligns eval with real product value |
| **4** | **ARES + Prediction-Powered Inference** for confidence intervals on judge-based metrics | Academic | **Now** | Medium (small judge fine-tune) | Very high | Defensible 95% CIs from 300 human labels; survives "your judge is biased" defense question |
| **5** | **Calibration: ECE + reliability diagrams + abstention–accuracy frontier** | Medical diagnostics + autonomous driving | **Now** | Low | Very high | Most undersold technique in production RAG; catches overconfident hallucination directly |
| **6** | **Per-intent stratified reporting** with **GraphRAG four-dim rubric** (Comprehensiveness, Diversity, Empowerment, Relevance) for synthesis intents | Microsoft Research | **Now** | Low | High | Single-average reporting hides 80% of signal; this is how GraphRAG wins decisively only on global queries |
| **7** | **Counterbalanced pairwise LLM-as-judge** with position-swap and reference answer + **multi-judge disagreement as signal** | Academic + LMSYS | **Now** | Low | High | Pairwise needs ~10× fewer judgments; position-swap is the cheapest bias mitigation |
| **8** | **Hetionet-style metapath evaluation** on the KG (Company–Person–Company, Holding–Fund–Holding, Article–Entity–Event) with curated 200-relation gold | Biomedical KG | **Now** | Medium | High | Closest published methodology to ours; turns a vague "is the KG good?" into concrete numbers |
| **9** | **Item Response Theory** for query difficulty + retriever ability decomposition | Educational testing | **Next quarter** | High | Very high | Genuinely novel for RAG (zero papers use it); strong thesis-contribution potential — distinguishes "ranker is good at easy queries" from "ranker is robust on hard ones" |
| **10** | **Counterfactual off-policy evaluation** (SNIPS) over logged retrieval traces | Recommender systems | **Next quarter** | Medium | High | Lets us A/B retrievers offline against demo-session logs without re-running queries; cuts iteration cost ~10× |

**Bonus (ranks 11–15, also worth adopting once Phase 1 ships)**:

11. **Mutation testing for prompts and eval rubrics** (validates the eval itself — software testing) — defer until Layer 3 is stable, then high value
12. **Skill score over naive baselines** (climatology + persistence — weather forecasting) — trivial wrapping of every metric, chronic RAG-paper-quality weakness
13. **Vespa LLM-judge → GBDT learning-to-rank loop** — when a reranker swap is on the table
14. **TPC-H-style query class taxonomy** with regression-test pinning ("must never regress" set of 50 queries; CI fails if any individual query drops >10%)
15. **CUPED variance reduction** for A/B retriever comparisons (halves required label budget)

### What to skip / deprioritize for a thesis

- **Promptfoo** — red-team focused, weak RAG-specific metrics
- **Single-judge G-Eval** — verbosity bias too strong (Liu et al. 2023 explicit warning)
- **Differential privacy on logs** — overkill unless publishing dataset
- **Snorkel weak-supervision pipelines** — heavy infra for marginal gain at thesis scale
- **CRUD-RAG benchmark** — Chinese-specific, low transfer
- **Online interleaving / true A/B** — requires production traffic we don't have
- **Multi-rater Krippendorff infrastructure with adjudication queue** — overhead exceeds benefit at 300-label scale
- **Custom embedding models / fine-tuned retrievers (L-2 in 04-23 audit)** — measure first via this framework, swap only if NDCG plateau

---

## 4. Where the Evaluation Layer Lives in the Repo

**Recommendation**: new top-level directory **`evals/`** (sibling to `services/` and `apps/`), not a new service.

**Rationale**:
1. Cross-service scope (S6, S7, S8 jointly) — not owned by any single service
2. Independent release cycle from services
3. No FastAPI surface needed; async workers + batch scripts + CI integration suffice
4. Reusable artifacts (golden sets, scorers, dashboards) shared across stakeholders

**Structure**:

```
evals/
├── pyproject.toml              # Hatch package, depends on libs/common, libs/observability, libs/contracts
├── README.md
├── src/evals/
│   ├── golden_sets/
│   │   ├── retrieval_v0_1_0.jsonl       # 100 queries × top-30 graded relevance (TREC qrels format)
│   │   ├── faithfulness_v0_1_0.jsonl    # 100 (query, answer, context) triples
│   │   ├── citations_v0_1_0.jsonl       # 50 Harvey-style analyst questions + reference citations
│   │   ├── kg_metapaths_v0_1_0.json     # 200 known relations (subject, object, predicate, sources)
│   │   ├── robustness_v0_1_0.jsonl      # 200 RGB-axis adversarial queries
│   │   └── manifests/                    # SHA-256 manifest per version, in-repo for CI gate
│   ├── scorers/
│   │   ├── ranking.py                    # NDCG, MRR, Recall@k (TREC-compatible)
│   │   ├── faithfulness.py               # RAGAS-style + ARES/PPI wrapper
│   │   ├── citation.py                   # Harvey rubric scorer (negative-point semantics)
│   │   ├── kg_constraints.py             # SQL constraint runner
│   │   ├── kg_metapath.py                # Hetionet DWPC-style scorer
│   │   ├── calibration.py                # ECE, Brier, reliability diagram, abstention-accuracy frontier
│   │   ├── robustness.py                 # Metamorphic + RGB scorers
│   │   └── skill_score.py                # Naive-baseline wrapper over any metric
│   ├── judges/
│   │   ├── deepinfra_llama_judge.py      # cheap tier (Llama-3.1-8B)
│   │   ├── gpt4_judge.py                 # escalation tier
│   │   ├── confidence_router.py          # cheap → expensive on low-confidence/disagreement
│   │   └── pairwise.py                   # counterbalanced pairwise comparison
│   ├── runners/
│   │   ├── pr_gate.py                    # Tier-1 CI: ≤5 min, deterministic only, no LLM judge
│   │   ├── nightly.py                    # Tier-2 CI: ≤30 min, LLM judge, single-judge
│   │   └── weekly.py                     # Tier-3 CI: full sweep, multi-judge ensemble, MLflow log
│   ├── lineage/
│   │   ├── manifest.py                   # produces eval_run manifest YAML
│   │   └── mlflow_sink.py                # logs to local MLflow server in docker-compose
│   ├── feedback/
│   │   ├── consumer.py                   # Kafka consumer for chat-citation-feedback events
│   │   └── implicit.py                   # query-reformulation detector
│   └── metrics/
│       ├── prometheus.py                 # exporter: turns eval results into 7 gauges
│       └── kg_constraints_cron.py        # hourly KG constraint runner → violations table
├── tests/
│   ├── unit/                             # scorer unit tests
│   ├── integration/                      # golden-set round-trip tests
│   └── metamorphic/                      # the metamorphic-relations test suite (Layer 2a)
└── docker/
    └── Dockerfile                        # for the cron + consumer workers
```

**Reuse from existing infrastructure** — 100% of:
- `tests/e2e/conftest.py` fixtures (service clients, JWT, db sessions)
- `libs/observability` for structlog / metrics
- `libs/contracts` for Avro/event schemas
- `services/intelligence-migrations/seeds/` for repeatable test data
- Postgres (new schema `eval_db`) + Valkey (judge cache) + Kafka (feedback events)
- Existing Prometheus stack (just add 7 gauges)

**New components**:
- One MLflow server (Docker container, ~200 MB)
- One Argilla server (Docker container, ~500 MB) — for human labeling workflow
- New Postgres schema `eval_db` with tables: `eval_runs`, `eval_results`, `golden_versions`, `kg_quality_violations`, `chat_citation_feedback`, `chat_intent_feedback`, `judge_cache`

---

## 5. Day-1 / Day-30 / Day-90 / Day-365 Rollout

Follows Anthropic's "20–50 simple tasks first" pattern; matches PLAN-0058 Wave C in shape but extends scope.

### Day 1 (~1 day of work, this week)
- 30 hand-written golden queries in `evals/src/evals/golden_sets/retrieval_v0_1_0.jsonl` (5 per intent × 6 intents — `FACTUAL_LOOKUP`, `COMPARISON`, `REASONING`, `RELATIONSHIP`, `FINANCIAL_DATA`, `SIGNAL_INTEL`); 4-grade relevance labels on top-30 retrieval candidates
- One pytest at `evals/tests/integration/test_pr_gate.py` that runs the retriever on the gold set, asserts `Recall@10 >= baseline - 0.02`
- GitHub Action that runs it on every PR
- Pinned baseline JSON in `evals/src/evals/golden_sets/manifests/baselines_v0_1_0.json`
- 10 metamorphic relations (paraphrase overlap, ticker/name consistency, temporal monotonicity, no-lookahead) — already useful with current corpus
- **No LLM-judge yet** (avoids cost while pipeline is unstable from PLAN-0057 Phase 1)

### Day 30
- Grow golden set to 100 queries, time-aware split (train cut: 2026-01-01 → 2026-03-31, eval: 2026-04-01+), intent-stratified buckets
- Add LLM-as-judge (DeepInfra Llama-3.1-8B) for `faithfulness` and `answer_relevance` on a 50-query subset, nightly only (~$5/run)
- 30-query human-labeled subset for ARES/PPI calibration → defensible CIs
- MLflow tracking server in Docker Compose; every nightly run logs metrics + reproducibility manifest
- Argilla container running; start labeling 10 production queries/week as new goldens
- 10 KG constraint queries scheduled hourly, violations to `eval_db.kg_quality_violations`
- Per-citation thumbs feedback shipped on chat UI
- 7 Prometheus eval gauges live + Grafana dashboard with annotations

### Day 90
- 50 Harvey-style analyst questions hand-curated (real buy-side question patterns); citation rubric with negative-point scoring shipped
- 200-relation Hetionet-style KG gold set + metapath density scorer
- ECE / abstention-accuracy frontier shipped with `eval_calibration_ece` gauge
- RGB four-axis robustness probe (50 examples per axis, LLM-generated + 20% spot-check)
- Confidence-routed judge (cheap → expensive on low-confidence/disagreement) with $ circuit breaker
- Replay harness: re-run last 7 days of demo-session queries against any retriever version with one command
- Shadow-deploy next reranker version against shadow traffic; promote on quality SLO
- Skill scores reported alongside every metric

### Day 365 (thesis defense)
- Distilled in-house judge fine-tuned on ~10k labeled judgments (Llama-3.1-8B → matches GPT-4 in-domain)
- Item Response Theory analysis: query-difficulty parameters + retriever-ability parameters jointly estimated → reported in thesis
- Counterfactual off-policy eval (SNIPS) over demo-session logs for retriever comparison
- Mutation testing of eval rubrics → demonstrates eval robustness
- Public golden set released with thesis (with held-out contamination probe)
- Full eval lineage: every reported number reproducible from a `run_id`
- Documented rater workflow with κ tracking + adjudication procedure (thesis appendix)
- KG quality framework (constraint catalog) as a thesis contribution in its own right

---

## 6. Integration with PLAN-0058 Wave C — Concrete Task List

The current Wave C in PLAN-0058 has 5 tasks. **This proposal expands and reorders them** into a Day-1/Day-30/Day-90 phased delivery. The critical insight: **Wave C should ship the metamorphic + constraint layer (Layer 2) BEFORE the golden-set layer (Layer 3)** — because Layer 2 is oracle-free and runs immediately, while Layer 3 requires PLAN-0057 Phase 1 to be complete (otherwise we measure the broken state).

**Revised Wave C task list**:

| ID | Task | Dependencies | Effort |
|---|---|---|---|
| **C-0** | Bootstrap: create `evals/` package, MLflow + Argilla docker-compose entries, `eval_db` schema (3 tables: eval_runs, eval_results, golden_versions). | none | 1 day |
| **C-1** | Layer 2a: 50 metamorphic relations + pytest harness + CI integration. **No labeling required.** Catches F-CRIT-07-class bugs immediately. | C-0 | 2 days |
| **C-2** | Layer 2b: 15 KG constraint SQL queries + hourly cron + `eval_db.kg_quality_violations` table + Prometheus gauge + Grafana panel. | C-0, PLAN-0057 Wave A-3 (canonical seeds — so constraints can pass) | 2 days |
| **C-3** | Layer 3 retrieval gold set: 100 queries × top-30 graded relevance, intent-stratified, time-aware split. Hand-curated 50 + production-log 50. Stored TREC-qrels format. Pinned baselines JSON. | PLAN-0057 Phase 1 complete | 3 days |
| **C-4** | Layer 3 scorers: NDCG, MRR, Recall@k (TREC-compat); RAGAS faithfulness via Llama-3.1-8B; Harvey-rubric citation scorer (with negative-point semantics for fabricated citations); ECE + reliability diagram; skill-score wrapper over naive baselines. | C-3 | 3 days |
| **C-5** | Layer 3 runners: PR gate (Tier-1, deterministic only), nightly (Tier-2, LLM judge), weekly (Tier-3, multi-judge). MLflow logging with reproducibility manifest. Per-intent stratified reporting. | C-3, C-4 | 2 days |
| **C-6** | ARES + Prediction-Powered Inference wrapper: 30-query human-labeled subset → 95% CI on judge-based metrics. Distill Llama-3.1-8B judge from GPT-4 labels (off-thesis-budget fallback: stop at single-judge). | C-4 | 2 days |
| **C-7** | Layer 4 streaming metrics: 7 Prometheus gauges (`eval_retrieval_ndcg_p50`, `eval_kg_extraction_yield`, `eval_kg_coverage_ratio`, `eval_kg_constraint_violations_total`, `eval_calibration_ece`, `eval_abstention_rate`, `eval_judge_disagreement_rate`) + Grafana dashboard with prompt/model/golden-set change annotations. | C-2, C-5 | 1 day |
| **C-8** | Layer 5 user feedback: per-citation thumbs UI + `chat_citation_feedback` table + Kafka consumer + nightly aggregator. Implicit-reformulation detector. | C-0 | 2 days |
| **C-9** | CI gate: PR fails on `Recall@10` regression > 0.02 OR `kg_extraction_yield` regression > 0.05; Tier-2/3 post Slack-only. | C-5 | 1 day |

**Wave-C exit gate (revised)**:
- Layer 2 (metamorphic + KG constraints) running on every PR; ≥45 of 50 metamorphic relations passing
- Layer 3 producing weekly NDCG@10/MRR/Recall@30/RAGAS-faithfulness/citation-F1/ECE numbers with 95% CIs from PPI
- All metrics reported per-intent; skill scores reported alongside raw values
- 7 Prometheus gauges live; Grafana dashboard with annotations
- One reproducible eval lineage manifest per nightly run, queryable via MLflow

**Effort estimate**: ~19 person-days (vs current 5-task spec at ~10 days). The extra ~9 days buys: metamorphic layer, KG constraints, calibration metrics, Harvey rubric, ARES/PPI, streaming metrics, user feedback. **All four highest-rated cross-domain techniques (#1, #2, #3, #5 in §3) included.**

---

## 7. Open Questions for User

Before turning this into an implementation plan revision (PLAN-0058 Wave C update + tracking change):

1. **Labeling budget**: comfortable with ~25 hours of personal labeling effort for the 300-item gold set, or should I scope down to 150 items (then use ARES/PPI even more aggressively)?
2. **MLflow + Argilla**: ok to add two new Docker containers (~700 MB total) to the dev stack? Alternative is a pure-git-based lineage system, which is simpler but loses the comparison UX.
3. **Public release**: are we planning to release the financial gold set with the thesis? If yes, factor in 2 extra weeks for legal review of EODHD/Finnhub-derived snippets.
4. **GPT-4 budget for distillation**: ~$200–$400 to label 5–10k judgments for the distilled judge. Worth it, or stop at single-judge Llama-3.1-8B?
5. **Day-1 vs Day-30 split**: comfortable with Layer 2 (metamorphic + constraints) shipping in Wave C, and Layer 3 (golden-set evaluation) gated on PLAN-0057 Phase 1? Or push Layer 3 ahead with the broken-pipeline state as the baseline (deliberately measuring the floor)?

Once we align on the above, I'll produce a revised `docs/plans/0058-retrieval-and-kg-strategic-uplift-plan.md` Wave C section and update TRACKING.md.

---

## 8. Compounding updates

- **`docs/plans/0058-retrieval-and-kg-strategic-uplift-plan.md`** — Wave C will be expanded from 5 to 9 tasks per §6 above (pending user approval of this design)
- **`docs/plans/TRACKING.md`** — PLAN-0058 row will be updated `0/6` → `0/9` once Wave C is revised
- **`docs/MASTER_PLAN.md`** — new section "Evaluation" added once Wave C ships
- **`evals/.claude-context.md`** (new file when the package is created) — pitfalls discovered during implementation
- **`docs/BUG_PATTERNS.md`** — proposed: BP-295 *"Single-leaderboard evaluation hides per-intent regressions"* and BP-296 *"LLM-as-judge without position-swap exhibits ~10% position bias"* — to be added when first concrete instances appear in our codebase
- **`RULES.md`** — proposed R29: *"Every retrieval/ranker change must include skill-score-vs-baseline reporting; PR cannot be merged without per-intent NDCG@10 numbers"* (defer to user approval)

**Compounding check applied: PLAN-0058 Wave C revision pending user approval; new docs to be created on approval; bug-pattern entries deferred until first concrete instance.**

---

## 9. Next Step

`/plan` — Once user approves the design (§7 questions resolved), revise `0058-retrieval-and-kg-strategic-uplift-plan.md` Wave C and produce a detailed task breakdown with file-level scope, acceptance criteria, and integration with PLAN-0057 Phase 1 dependencies.

If user prefers a separate plan for the eval layer (rather than expanding PLAN-0058 Wave C): create `0059-evaluation-layer-plan.md` and reference both PLAN-0057 (Phase 1 dep) and PLAN-0058 Wave D (hybrid retrieval, the first thing to *be evaluated*).
