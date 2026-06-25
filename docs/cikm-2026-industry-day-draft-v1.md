# CIKM 2026 Industry Day — Talk Proposal (DRAFT v1, Markdown for content review)

> Working draft for content/framing review **before** converting to ACM `sigconf` LaTeX.
> Target length when typeset: **2 pages** (bio + references do NOT count). Non-anonymous.
> Numbers sourced from `docs/cikm-2026-industry-day-analysis.md` metrics pack (verified against audits 2026-06).
> ⚠️ = needs Arnau to confirm/decide before submission.

---

## Title (candidates — pick one)
1. **Hybrid Retrieval for a Financial Knowledge Graph: Grounding News-Derived Facts with Graph Traversal, Dense Embeddings, and LLM-as-Judge** *(recommended)*
2. When the Benchmark Lies: Lessons from Grounding a Financial KG + RAG System in Production
3. Combining Graph and Vector Retrieval for Citation-Grounded Financial Question Answering

> Rec #1 leads with the *method* (hybrid retrieval) — CIKM's core identity — and names all three pillars (graph, vector, evaluation). #2 leads with the *lesson* (more memorable, slightly riskier).

---

## Abstract (~150 words)
Worldview is a market-intelligence platform that turns a continuous news stream into a queryable financial knowledge graph and answers analyst questions with citation-grounded, multi-agent RAG. We describe a **hybrid retrieval** design that fuses three signals over the same corpus: variable-length graph traversal on Apache AGE, dense vector search over entity- and definition-level embeddings in pgvector/HNSW, and full-text BM25 — combined by reciprocal-rank fusion and grounded back to source documents via per-relation citations. The talk's central lesson is a **measurement trap**: extraction benchmarks reported near-perfect precision, yet a stratified audit of the *stored* graph found only ~28% of relations were document-supported — the dominant defect being plausible co-mentions invisible to structural validation. We present the LLM-as-judge evaluation methodology that exposed this gap, the deterministic gates that fixed the structural fraction, and the production failures (silent extraction drops, CPU-throttled NER, an over-additive judge) we corrected along the way.

---

## 1. Problem & context (~0.4 col)
- Retail and prosumer investors lack a tool that reads the *entire* news flow, links it to entities, and answers questions with **traceable evidence** rather than ungrounded LLM prose.
- Worldview ingests ~**2,400 articles/day**, runs GLiNER NER + LLM relation extraction, and materializes a financial KG: **16,994 canonical entities**, **41,448 graph vertices / 14,109 edges** (Apache AGE), with **99,462 entity mentions** resolved to canonical IDs.
- Built as a deployed, end-to-end system (10 FastAPI microservices, Next.js 15, Kafka, Postgres + AGE + pgvector, MinIO, Valkey) — **a live demo, evaluated under realistic settings** (single-operator thesis deployment, not a multi-tenant production service). ⚠️ keep this honest framing.

## 2. Hybrid retrieval design & tradeoffs (~0.6 col) — THE SPINE
- **Three retrieval signals over one corpus, fused by RRF:**
  - **Graph traversal** (Apache AGE, Cypher VLE): entity-anchored multi-hop context. Design lesson: explicit per-edge-label `MATCH` cost **18.4 s/query**; native variable-length-edge traversal with GIN-indexed vertex lookup cost **240 ms** — a **76× speedup**. Pairwise endpoint queries 56–100 ms (800 ms on degree>100 hubs).
  - **Dense vector search** (pgvector + HNSW, cosine): BGE-large 1024-d embeddings over **three entity views** (definition, narrative, fundamentals) plus chunk/section embeddings — so retrieval matches on *meaning*, not just graph adjacency.
  - **Lexical** (BM25 / Postgres FTS) as a recall floor.
- **Why hybrid, not either alone:** graph gives precise entity relationships but misses paraphrase; vectors give semantic recall but no relational structure; fusion + KG citations gives **grounded** answers with `relation_id` provenance (1–7 citations/answer).
- Multi-agent RAG orchestration over the fused context; first-token target <5 s. ⚠️ confirm current chat model id for camera-ready (DeepSeek-R1 Distill family).

## 3. The measurement trap (~0.5 col) — THE LESSON
- **Fresh-extraction benchmark**: gpt-oss-120b scored **5.0/5 precision, 0.0 fabrications/article** on a 20-article set.
- **Stored-graph reality** (stratified 382-row audit): only **27.6% of relations document-supported** (95% CI 22–33%). Breakdown: **45.7% CO_MENTION** (the dominant defect — real co-occurrence, not a real relation), 11.5% unsupported, 7.8% wrong-direction, 7.4% wrong-predicate.
- **Lesson 1 — benchmarks measure the wrong moment.** Per-call precision ≠ corpus-level stored quality once aggregation, canonicalization, and promotion intervene. The gap was **~18×**.
- **Lesson 2 — structural gates only catch structural defects.** Deterministic gates (self-loop, OOV predicate, invalid `listed_on`, common-noun endpoint) removed **442 user-visible bad relations** and raised `listed_on` support to **86%** — but are blind to the semantic CO_MENTION majority. That needs a model-based judge.

## 4. Evaluating grounding with an LLM-as-judge (~0.4 col)
- **CHAT_QUALITY_JUDGE v2** (DeepSeek-V4-Flash, temp 0, strict JSON) scores grounding/framing/tool-use/refusal.
- **Anti-pattern we found and fixed (BP-676):** an additive rubric let broken answers pass — a reply flagged "most claims fabricated" still scored 85/100 PASS; a raw "500 error" string scored 100/100; leaked control tokens scored 90–100. Fixes: **dimensional veto** (grounding floor), **degenerate-answer pre-checks**, and **failure-first reporting** (worst-N before averages).
- **Grounding works when measured honestly:** news-grounded entity descriptions cut fabrications on obscure entities from **1.83 → ~0.17 per description** vs ungrounded recall — but only with a model that actually emits output (a candidate replacement produced 100% empty results at the threshold, which naïve metrics would have rewarded).

## 5. What broke in production (~0.3 col) — pick 1–2 to keep
- **Silent extraction drop:** a prompt/lookup source mismatch silently discarded ~**80%** of extracted relations during canonicalization; fixed by unifying the entity-list source.
- **CPU-throttled NER:** GLiNER spawned 14 OMP threads under a 4-core cgroup quota → thread-thrash, ~12% useful CPU, articles timing out at 240 s and dropping to DLQ; fixed by pinning threads + raising memory cap.
- **O(n²) KG promoter:** a per-relation correlated density subquery cost 1.13M units every 5 min; a CTE precompute cut it **32×**.

## 6. Relevance to CIKM 2026 themes & topics (~0.2 col) — EXPLICIT, required signal
- *Information Access and Retrieval* — hybrid RAG + generation of knowledge graphs from unstructured data.
- *Agentic AI for Information and Knowledge Tasks* — multi-agent orchestration over fused retrieval.
- *Trustworthy and Responsible AI* — factuality, grounding, attribution, hallucination mitigation.
- *Evaluation* — LLM-as-judge, benchmark-vs-deployment gap, reproducibility.
- *Mining Multi-Modal Content / Applications: business* — financial KG from news.
- *Industry Day themes*: deployed system design & scalability, production metrics, data/quality challenges, and **academia↔industry crossover** (a student-built deployed platform).

## Takeaway for the audience (one sentence to end on)
> Hybrid graph+vector retrieval makes financial QA *grounded*; but the harder, transferable lesson is that **extraction benchmarks systematically overstate stored-graph quality**, and only judge-based, failure-first evaluation closes the gap.

---

## Speaker details & bio (does NOT count toward 2 pages; non-anonymous)
- **Speaker**: Arnau Rodon Comas — MSc candidate (MECD), Universitat Pompeu Fabra; thesis supervised by Víctor Casamayor.
- **Bio** ⚠️ draft: *Arnau Rodon Comas is a master's student at Universitat Pompeu Fabra building Worldview, a financial market-intelligence platform combining knowledge graphs, hybrid retrieval, and grounded RAG. His work focuses on extraction quality, retrieval grounding, and LLM-as-judge evaluation for finance NLP.* (Add 1 line of relevant prior experience if desired.)

## GenAI Usage Disclosure (required by general submission policy; not counted)
⚠️ Draft: *Generative AI tools were used to assist drafting and editing of this proposal; all technical claims, metrics, and system descriptions are the author's own and verified against the system's evaluation logs.*

---

## Open decisions before LaTeX conversion
1. **Title**: #1 (method-led, recommended) vs #2 (lesson-led)?
2. **"What broke" section**: which 1–2 of the three stories to keep (space-limited)?
3. **Honesty calibration**: how prominently to feature the 27.6% stored-quality number. Recommendation: feature it — it's the differentiator and reads as rigor, not weakness, at this venue. ⚠️ but confirm you're comfortable putting it in print under your name.
4. Confirm current **chat model id** and any number you want re-verified at camera-ready (live figures drift).
