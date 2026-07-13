# EMNLP 2026 System Demonstrations — 6-Page Paper Plan

> **Venue**: EMNLP 2026 System Demonstrations track, Budapest, 24–29 Oct 2026.
> **Deadline**: **Fri 10 Jul 2026, 11:59pm UTC-12 (AoE)** · notification 20 Aug · camera-ready 30 Aug.
> **Format**: 6 pages content max (desk-reject if over) + unlimited references/ethics + ≤2-page appendix. ACL/EMNLP LaTeX template. PDF via OpenReview.
> **Review**: single-blind (keep your name, self-cite freely), no rebuttal.
> **Hard gates**: (1) a **live demo URL or installable package is strictly required**; (2) **a paper with no evaluation may be desk-rejected**; (3) a ≤2.5-min screencast (review-only).
> **Sources**: this plan synthesizes `docs/cikm-proposal/cikm-2026-industry-day-v5.typ`, `docs/cikm-proposal/measurement-evidence.md`, `thesis/OUTLINE.md`, `thesis/chapters/05-evaluation.typ`, and a web research pass on the EMNLP demo track (accepted-paper patterns, chairs, trends).

---

## 1. Strategic framing (what wins in this track)

The demo track rewards, in priority order: **open-source / open-access** systems, **technologically innovative industrial systems**, and **evaluation / diagnostic tooling**. The two hottest 2024–25 clusters are **RAG-with-a-vertical-anchor** and **agentic / evaluation toolkits**. Finance demos are *rare* (Alpha-GPT was nearly the only one in EMNLP 2025), so the domain itself is a differentiator.

Worldview hits all of these at once. **The thesis-grade move is to lead with TWO contributions, exactly as CIKM v5 already reframed them:**

1. **The living system** — a deployed, grounded, agentic RAG over a *hybrid retrieval* substrate (AGE graph traversal + pgvector/HNSW + BM25 + structured market data), with typed-block split fusion, multi-view entity embeddings, a cost-controlled learned routing gate, and a continuously-updated ("living") knowledge graph (weekly tri-embedding refresh, six-timescale edge decay, contradiction-demotes-confidence).
2. **The multi-level evaluation framework** — answer-level judge with 7 deterministic hard-fail gates + grounding veto, tool-output substantiation, trajectory/tool-chain judge, judge calibration (Cohen's κ vs. human gold), emerging reasoning-validity layer.

**Why this dual framing for *this* venue:** the demo track's single biggest desk-reject trigger is "no evaluation," and the track loves evaluation tooling. A demo paper whose *second contribution is the eval framework itself* is both desk-reject-proof and squarely in a hot cluster. The "honest benchmark-vs-stored grounding gap" becomes our credibility hook, not a weakness.

### Naming
Accepted demos almost universally use a **brandable Name: descriptive-subtitle** title. We already have the brand: **Worldview**.

- **Proposed title**: *Worldview: A Deployed Grounded Agentic RAG over a Living Financial Knowledge Graph, with a Multi-Level Evaluation Framework*
- Alt (eval-forward): *Worldview: Measuring a Continuously-Deployed Financial KG-RAG Honestly* — but lead-with-system reads better for a *demo* track than for the CIKM talk.

---

## 2. Page-by-page budget (6 pages)

| § | Section | Pages | Primary source material |
|---|---------|-------|-------------------------|
| 1 | Introduction + contributions list + **live-URL/open-source statement** | 0.75 | CIKM v5 §"Problem and context"; thesis Ch.1 (O-1..6, C-1..4) |
| 2 | System overview + **Figure 1 (architecture)** + target audience/use cases | 1.0 | thesis OUTLINE Ch.3/4; CIKM v5 pipeline figure |
| 3 | Architecture & novelty: hybrid retrieval + typed-block fusion + living graph + agent/SSE trace | 1.5 | CIKM v5 "Part 1: the living system"; thesis §4.5 |
| 4 | Implementation: stack, models, deployment, **licensing** | 0.5 | thesis Ch.3 (10 services, Postgres-consolidation, Docker); abstract |
| 5 | **Evaluation** (DO NOT SKIP) — the multi-level framework + headline numbers | 1.25 | CIKM v5 "Part 2"; thesis Ch.5; measurement-evidence.md |
| 6 | Demo walkthrough + **screenshots** (mirror the screencast) | 0.5 | landing/chat showcases; thesis Appendix G journeys |
| 7 | Related work / comparison vs. existing systems | 0.5 | thesis Ch.2 SoTA; demo-track analogues (below) |
| — | Conclusion + Ethics/Broader Impact (ethics is *outside* the 6pp budget) | — | thesis Ch.6; CIKM v5 GenAI disclosure |

Figures count toward the 6 pages — budget ~1.5 pages of the above for Figure 1 (architecture) + Figure 2 (eval-framework levels or living-graph edge) + 1–2 screenshots.

---

## 3. Section-by-section content spec

### §1 Introduction (~0.75pg)
- Open on the **integration-gap + multi-retrieval-shape** problem (CIKM v5 opening: "A financial question rarely has one retrieval shape"). Fundamentals→structured; entity-relations→graph; thematic→dense; tickers→exact-match; every answer must cite.
- The harder, under-reported problem: **trusting** a continuously-deployed grounded RAG whose answers, tool choices, and graph all drift — standard benchmarks score a frozen snapshot.
- **Explicit bulleted contributions** (reviewers scan for this): C1 living system; C2 multi-level eval framework; C3 the honest served-vs-fresh finding.
- **State availability up front**: "Worldview is open-source; a live instance is reachable at <URL>." Reviewers look for this immediately.

### §2 System overview (~1.0pg) — **Figure 1 mandatory**
- One sentence of what the user does (analyst asks a question → streamed, cited answer with a live research trace).
- **Figure 1**: end-to-end pipeline (reuse + upgrade the CIKM v5 pbox diagram): News → GLiNER NER (11 classes) → entity resolution → LLM extraction → validation gates → KG (Postgres+AGE+pgvector) → hybrid retrieval → agent → cited answer. Include alt-text (accessibility expected).
- Scale paragraph (the "real deployed system" credibility shot): ~2,000–3,200 articles/day, ~248k mentions → ~28.8k canonical entities, ~44.6k vertices (28.8k entity + 15.9k temporal-event), ~15k relations, under a ~$200/month ceiling. **Use the verified figures from measurement-evidence.md, not the thesis's older seeded counts.**
- Target audience: analysts / researchers / retail-prosumer investors (contrast Bloomberg $24k/seat from thesis Ch.2).

### §3 Architecture & novelty (~1.5pg) — the technical centerpiece
Pull directly from CIKM v5 "Part 1", expanded:
- **Cost-controlled learned routing gate**: cheap signals (entity density, source authority, recency, doc type, extraction-yield proxy) route into 4 tiers *before* any embedding/LLM call; learned embedding gate (ROC-AUC 0.828 vs 0.779 baseline — thesis §5) escalates only ambiguous articles to an LLM tiebreak. This is what holds the budget ceiling.
- **Hybrid retrieval with typed-block split fusion**: 4 retrievers as typed tool calls (AGE graph traversal, pgvector+HNSW dense, BM25 recall floor, structured market data). RRF fuses vector+BM25 *inside* document search; structured outputs (graph edges, financial rows, claims) **bypass the reranker** and reach the model as typed blocks (`<graph_facts>`, `<structured_data>`) — preserving the numbers the model must reason over. **This is the strongest single novelty claim — make it prominent.**
- **Multi-view entity embeddings**: each canonical entity carries up to 3 embedding views (definition / evidence-narrative / fundamentals+OHLCV), each under its own partial HNSW index.
- **The living graph**: weekly re-textualize+re-embed all 3 views; edges decay on 6 timescales by predicate; contradicting evidence demotes confidence without deletion. → motivates "evaluate as a living object, not a one-shot benchmark."
- **Agent + live research trace**: planning loop with explicit tool budget, concurrent execution, streamed cited answer; every step (tool, latency, result count) surfaced as the trace the trajectory judge later consumes. (Ties §3 to §5 — nice.)

### §4 Implementation (~0.5pg)
- 10 event-driven microservices (FastAPI, Kafka, PostgreSQL/TimescaleDB, pgvector, Apache AGE), Next.js 15 frontend; transactional outbox; one consolidated Postgres replacing 3 specialized stores (thesis abstract C-1).
- Models: GLiNER (local NER), DeepInfra-hosted LLMs for extraction/synthesis (name the live models honestly — gpt-oss-120b era), BGE embeddings (self-hosted).
- **Licensing** (CFP explicitly requires it): state the repo license. Confirm before submission.
- Reproducibility: `make dev` boots the full stack on a single host.

### §5 Evaluation (~1.25pg) — **non-negotiable, this is the desk-reject gate AND a contribution**
Structure as the four levels (CIKM v5 Part 2), each catching what the level below cannot:
1. **Answer level — gates before judgement**: 4 LLM dims (grounding/framing/tool-use/coherence) *after* 7 deterministic hard-fail gates + grounding veto. Motivate with the **real logged failures**: "most claims fabricated" scored 85/100; raw error string scored 100/100; leaked control tokens 90–100. (These are verified/citable.)
2. **Tool-output substantiation**: cross-reference each numeric claim against values the called tools actually returned → substantiated / unsupported / contradicted; coverage honestly bounded to the 10 grounding-exposing tools. → `[PENDING FINDING-RUN: % unsubstantiated]`.
3. **Trajectory / tool-chain judge**: scores routing, ordering, failure-recovery, efficiency over the captured trace. → `[PENDING FINDING-RUN: mean trajectory quality; redundancy/unrecovered count]`.
4. **Judge calibration**: Cohen's κ vs. human-labelled gold (39 items, failure-mode-stratified) against a 0.7 bar. **Resolve the κ inconsistency** (see Gap G3) before quoting a number.
- **Emerging reasoning-validity layer**: ship as emerging-only, caveated (it's itself an LLM); report only its agreement with the deterministic substantiation check.
- **The headline finding** (credibility hook): under one frozen judge + identical binary "document-supported" rubric, **fresh extraction = 82.6% support (38/46; 95% CI 69–92%)** vs **served-graph = 48.8% volume-weighted / 36.9% predicate-balanced (n=382)** — stored quality roughly *halves*, dominated by mundane UNSUPPORTED (36.6%) + WRONG_DIRECTION (14.7%), not exotic defects. Deterministic gates removed 442 bad relations, lifted `listed_on` to 86%, now 0/32 drops (regression guard). **The lesson: trust served-graph support under one frozen judge, not extractor precision.**
- Optionally fold in the latency table (thesis §5.3): chart p95 32ms, hybrid search p95 134ms, depth-2 graph p95 305ms, cached chat first-token p95 924ms. **Caveat the graph-traversal latency honestly** (measurement-evidence Task 3: variable-length traversal is a current scaling weakness; the relational-CTE prototype hits ≈4ms p50/53ms p95 but is a connectivity prototype, not a shipped replacement).

### §6 Demo walkthrough (~0.5pg)
- One concrete scenario end-to-end with screenshots, mirroring the screencast: e.g., "Which suppliers does NVIDIA share with AMD?" → show the live research trace (tool calls + latencies), the typed graph-facts block, and the streamed cited answer.
- 1–2 UI screenshots (landing KG/weird-connections showcase + grounded-chat with citations). Source: existing frontend showcases / thesis Appendix G.

### §7 Related work / comparison (~0.5pg) — CFP explicitly asks for this
- vs. **summarization-oriented Graph RAG** (Edge et al. 2024): Worldview's graph is a *typed, evidence-linked* store — every edge points back to the asserting passage (what makes the eval possible).
- vs. demo-track analogues: **SpiritRAG** (domain-anchored RAG Q&A — closest structural sibling), **KMatrix-2** (knowledge-enhancement toolkit), **Alpha-GPT** (the rare finance demo), **AgentDiagnose / TruthTorchLM** (trajectory/truthfulness eval — position our eval framework against these).
- vs. institutional terminals (Bloomberg/Refinitiv): open, inspectable, grounded-with-citations.

### Ethics / Broader Impact (outside 6pp budget — use generously)
- Adapt CIKM v5 GenAI disclosure. Financial-advice caveats; hallucination risk mitigated-not-eliminated by grounding; data-source licensing/ToS.

---

## 4. Figures to produce

| Fig | Content | Source / status |
|-----|---------|-----------------|
| 1 | End-to-end architecture (news → KG → hybrid retrieval → cited answer) | Upgrade CIKM v5 pbox diagram; **needs a clean vector figure** |
| 2 | Either the 4-level eval framework (answer→tool→trajectory→calibration) OR a living-graph edge (text/relation/decay/confidence) | New — recommend the eval-levels figure (it's the novelty) |
| 3 | Demo screenshot: live research trace + cited answer | Capture from live instance |

---

## 5. Gaps to close BEFORE 10 Jul (ordered by risk)

- **G1 — LIVE DEMO URL (highest risk, longest lead time).** The CFP *strictly enforces* a reachable live demo or installable package. The instance currently runs locally on a single host. **Decision needed**: expose a public, stable, rate-limited demo deployment, OR package a one-command Docker bundle reviewers can run. This is the single biggest non-writing task — start immediately. (See also memory: live-QA found MinIO OOM + stale images — harden before exposing.)
- **G2 — PENDING FINDING-RUN numbers.** Fill the three `[PENDING FINDING-RUN]` tokens (W1 % unsubstantiated; W2 mean trajectory quality + redundancy/unrecovered count; W3 current gated-judge κ). Per memory, PLAN-0115 finding-run is partly done (gated-v3-judge κ=0.7953 DONE; substantiation%+trajectory finding-run in progress). **Pull the completed numbers into the paper.**
- **G3 — κ inconsistency to resolve.** CIKM v5 says κ=0.594 (below 0.7 bar); thesis Ch.5 says author-labelled κ≈0.95; memory says gated-v3-judge κ=0.7953. These measure different judge versions/label sets. **Pick one defensible, human-labelled number with its exact provenance** and use it consistently. Do NOT quote a sub-bar κ as a result without framing.
- **G4 — Licensing statement.** Confirm the repo's license and state it in §4 (CFP requires it).
- **G5 — Reproducibility of the headline.** The 82.6%-vs-36.9% finding is verified (measurement-evidence Addendum Task 1). Keep the same-judge/same-rubric framing; do NOT revert to the old "5.0/5 vs 37%" which overstated the gap.
- **G6 — Screencast (≤2.5 min, audio narration).** Record after the live demo is stable; mirror the §6 walkthrough.
- **G7 — LaTeX port.** Draft can start in Typst for speed, but submission is the EMNLP/ACL `acl` LaTeX template — port before submission (TAPS/ACL reject Typst).
- **G8 — >25% overlap rule.** If the CIKM Industry Day talk (or its v5 write-up) is published/archival anywhere, ensure <25% verbatim overlap. CIKM Industry Day is talk-only/non-archival per the dossier, so likely fine — but the *eval-framework* content also feeds REALM (17 Jul) and FinNLP; sequence so the demo paper and those are not simultaneously under review with >25% shared text.

---

## 6. Suggested writing order & timeline (14 days)

1. **Days 1–3**: Stand up the public/packaged live demo (G1) — longest lead time, gates everything. In parallel, draft §3 (architecture) and §5 (eval) from CIKM v5 — the content is ~80% written.
2. **Days 3–5**: Run/pull the finding-run numbers (G2), resolve κ (G3), confirm license (G4). Lock all citable numbers.
3. **Days 5–8**: Draft §1, §2, §4, §7; produce Figure 1 + Figure 2.
4. **Days 8–10**: Demo walkthrough §6 + screenshots; record screencast (G6).
5. **Days 10–12**: Port to ACL LaTeX (G7); tighten to 6 pages; write ethics/impact.
6. **Days 12–14**: Internal review pass, overlap check (G8), proofread, submit on OpenReview (link posts ≥2 weeks before deadline).

---

## 7. One-line bottom line
Lead **open + live + working**; brandable name (**Worldview**); anchor hard in the **finance vertical** (rare here); make **hybrid AGE+pgvector+BM25 typed-block fusion** the novelty centerpiece; and let the **multi-level evaluation framework + honest served-vs-fresh grounding gap** be the second contribution that makes the paper both desk-reject-proof and memorable.
