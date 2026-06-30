// CIKM 2026 Industry Day — Talk Proposal (Typst draft)
// =====================================================
// FORMAT NOTES (verified 2026-06-22 against official CIKM pages):
//   • Limit: 2 pages. Speaker bio + references + the "GenAI Usage Disclosure"
//     section do NOT count toward the 2 pages.
//   • Required template: ACM SigConf (two-column). This Typst file APPROXIMATES
//     that layout for the SUBMISSION PDF only.
//   • Non-anonymous: a final speaker-details section is mandatory.
//   • "GenAI Usage Disclosure" section is MANDATORY, titled exactly that,
//     placed immediately before the references.
//   • EasyChair track "CIKM 2026 Industry Day"; deadline 29 Jun 2026 23:59 AoE.
//
//   ⚠️ CAMERA-READY RISK: ACM TAPS accepts only LaTeX (acmart) + Word, NOT Typst.
//   If accepted, port these ~2 pages to \documentclass[sigconf]{acmart}.
//
// ⚠️ markers below = decisions/values for Arnau to confirm before submission.

#set document(title: "Hybrid Retrieval for a Financial Knowledge Graph")
#set page(paper: "us-letter", margin: (x: 1.9cm, y: 2.2cm))
#set text(font: "New Computer Modern", size: 9.5pt)  // ACM uses Libertine; NCM is a safe Typst-native stand-in.
#set par(justify: true, leading: 0.5em)
#set heading(numbering: "1")
#show heading: set text(size: 10.5pt, weight: "bold")
#show heading: set block(above: 0.9em, below: 0.5em)

// ----------------------------- TITLE BLOCK (full width) -----------------------------
#align(center)[
  #text(17pt, weight: "bold")[Hybrid Retrieval for a Financial Knowledge Graph:\
  Grounding News-Derived Facts with Graph Traversal, Dense Embeddings, and LLM-as-Judge]

  #v(0.4em)
  #text(11pt)[Arnau Rodon Comas]\
  #text(9pt)[Universitat Pompeu Fabra · MeshX #footnote[Independent thesis work; not affiliated with or endorsed by MeshX.]]\
  #text(9pt, style: "italic")[rodonarnau\@gmail.com] // ⚠️ confirm which email to list
]

#v(0.6em)

// ----------------------------- ABSTRACT (full width) -----------------------------
#block(inset: (x: 0.6cm))[
  #text(weight: "bold")[Abstract.]
  // Decision (Q: "describe" vs "design/implement"?): Industry Day rewards DEPLOYED
  // systems and builder framing — use active "we present the design, deployment, and
  // evaluation of…". Decision (Q: mention structured ingestion?): YES — OHLCV /
  // fundamentals / prediction-market signals are genuinely in the retrieval path
  // (tool-call parity with documents + KG), which differentiates this from news-only RAG.
  We present the design, deployment, and evaluation of #emph[Worldview], a market-intelligence
  system that turns a continuous news stream into a queryable financial knowledge graph and
  answers analyst questions as an agentic, citation-grounded assistant. A research agent plans
  and calls tools over a #emph[hybrid retrieval] substrate that fuses four signals over the same
  corpus — variable-length graph traversal (Apache AGE), dense vector search over entity- and
  document-level embeddings (pgvector/HNSW), lexical BM25, and structured market data (prices,
  fundamentals, prediction markets) — combined by reciprocal-rank fusion and grounded back to
  sources via per-claim citations. Our central, transferable lesson concerns #emph[honest
  measurement of grounded systems]: extraction benchmarks reported near-perfect precision, yet a
  stratified audit of the #emph[stored] graph found only ~28% of relations were document-supported,
  the dominant defect being plausible co-mentions invisible to structural validation. We show why
  deterministic validation gates are necessary but insufficient, and how an LLM-as-judge evaluation
  layer — once hardened against its own failure modes — closes the gap. We share the production
  failures (silent extraction drops, resource-starved NER) corrected along the way.
]

#v(0.4em)

// ----------------------------- TWO-COLUMN BODY -----------------------------
#columns(2, gutter: 0.7cm)[

= Problem and context
Retail and prosumer investors lack a tool that reads the entire news flow, links it to the right
entities, and answers questions with #emph[traceable evidence] rather than ungrounded LLM prose.
Worldview is built end-to-end as a #emph[deployed, live system] — ten event-driven microservices
(FastAPI, Kafka/Avro, PostgreSQL/TimescaleDB, pgvector, Apache AGE, MinIO, Valkey) with a Next.js
front end — and is evaluated under #emph[realistic, thesis-scale settings] (a single-operator
deployment, not a multi-tenant production service).
// Decision (Q: include KG-size numbers?): YES, but framed as evidence of a REAL running
// pipeline, not a scale brag — the numbers are modest and we say so.
Concretely, the running pipeline ingests on the order of #strong[~2,400 news articles/day], resolves
#strong[~99k] entity mentions to #strong[~17k] canonical entities, and materializes a graph of
#strong[~41k vertices / ~14k edges] — modest by web scale, but a genuine operating system whose
quality we can audit honestly.

= System: agentic hybrid retrieval
// Decision (Q: do they want agentic framing? we have the research agent): YES — "Agentic AI
// for knowledge tasks" is a new CIKM 2026 top-level theme AND it is real here. We frame the
// agent as the VEHICLE and grounding/evaluation as the CONTRIBUTION.
A research agent answers each query through a planning loop with an explicit tool budget: it selects
tools from a typed catalog, executes them concurrently, and synthesises a streamed, cited answer;
every step (tool call, latency, result count) is surfaced to the user as a live research trace.

// Decision (Q: only retrieval, or also KG creation?): include a COMPACT construction summary,
// because the quality lesson below depends on understanding extraction.
#strong[Knowledge-graph construction.] Each article passes through NER (GLiNER, 11 entity classes),
a four-stage entity-resolution cascade, and LLM relation extraction; candidate relations are
canonicalised and promoted into the materialised graph, with a shadow Cypher graph in Apache AGE.

#strong[Hybrid retrieval.] The agent composes four retrievers over one corpus, fused by
reciprocal-rank fusion (RRF):
- #emph[Graph traversal] (AGE variable-length edges) for entity-anchored multi-hop context. Replacing
  per-edge-label `MATCH` with native variable-length traversal over a GIN-indexed vertex store cut a
  representative query from #strong[18.4 s to 240 ms (76×)].
- #emph[Dense vectors] (pgvector + HNSW, cosine) over chunk, section, and three entity-profile views,
  so retrieval matches on meaning, not only graph adjacency.
- #emph[Lexical BM25] as a recall floor, with canonical-ticker boosting.
- #emph[Structured market data] — OHLCV, fundamentals, and prediction-market snapshots — retrieved as
  first-class tools, giving the agent numeric grounding alongside text and graph.

Retriever choice is #emph[intent-aware]: the agent routes relationship questions toward the graph and
quantitative questions toward structured tools, rather than running a fixed pipeline. Answers carry
1–7 citations resolved back to a `relation_id`, article snippet, or `(period, metric)` tuple.

= The lesson: measuring a grounded system honestly
// Decision (Q: is the eval problem too targeted? is measurement == eval framework?):
// The two are DISTINCT efforts (a one-time extraction-quality audit vs a continuous chat-quality
// judge), but they share ONE transferable thesis — present them as two evidences for it, not as
// two separate lessons. This is the distinctive, Meij/King-relevant contribution.
The system's most transferable contribution is not the retrieval stack but #emph[how we learned to
trust it]. Two findings, at two different layers, point to one lesson.

#strong[1. Benchmarks measure the wrong moment.] Fresh extraction scored #strong[5.0/5 precision]
on a held-out article set; yet a stratified audit of #strong[382] stored relations found only
#strong[27.6%] were document-supported (95% CI 22–33%). The dominant defect — #strong[45.7%] — was
#emph[co-mention]: a real co-occurrence that is not a real relation. Per-call precision says little
about corpus-level quality once aggregation, canonicalisation, and promotion intervene.

#strong[2. Structural gates are necessary but not sufficient.] Deterministic gates (self-loop, out-of-
vocabulary predicate, invalid `listed_on`, common-noun endpoint) removed #strong[442] user-visible bad
relations and raised `listed_on` support to #strong[86%] — but are blind to the semantic co-mention
majority. Closing that gap needs a model-based judge.

#strong[3. The judge needs guarding too.] Our LLM-as-judge answer-quality harness initially used an
additive rubric that let broken output pass: a reply flagged "most claims fabricated" still scored
85/100, a raw error string scored 100/100, and leaked control tokens scored 90–100. The fix was
architectural — a #emph[grounding veto], #emph[degenerate-answer pre-checks], and #emph[failure-first
reporting] (worst cases before averages). Measured honestly, grounding works: grounding entity
descriptions in retrieved news cut fabricated claims on obscure entities from #strong[1.83 to ~0.17
per description] versus ungrounded recall.

#strong[What broke in production.] A prompt/lookup source mismatch once silently discarded ~80% of
extracted relations during canonicalisation; and NER spawned 14 compute threads under a 4-core quota,
thrashing until articles timed out and were dropped. Both were invisible to green dashboards — the
same theme as the measurement lesson: #emph[a system that reports success is not the same as a system
that is correct].

= Relevance to CIKM 2026 themes and topics
This talk maps directly onto CIKM 2026 areas: #emph[Information Access and Retrieval] (hybrid RAG;
generating a knowledge graph from unstructured text); #emph[Agentic AI for Information and Knowledge
Tasks] (tool-using research agent); #emph[Trustworthy and Responsible AI] (grounding, attribution,
hallucination mitigation); #emph[Evaluation] (LLM-as-judge, the benchmark-vs-deployment gap,
failure-first reporting); and #emph[Applications: business]. It fits the Industry Day themes of
deployed-system design, production metrics and measurement, and data-quality challenges, and is
offered as an #emph[academia↔industry crossover] talk from a practitioner who built the system.

] // end two-column body

// ----------------------------- SPEAKER DETAILS (does NOT count toward 2 pages) -----------------------------
#v(0.6em)
#line(length: 100%, stroke: 0.4pt)
#set heading(numbering: none)
= Speaker details
// Non-anonymous section is MANDATORY. Bio sourced from Arnau's resume — positions him as a
// genuine industry practitioner (strongest framing for Industry Day) + final-year BSc author.
*Arnau Rodon Comas* is a forward-deployed Machine Learning Engineer at *MeshX*, where he builds
production AI systems for a major international airport group — owning data modelling, ML pipelines,
deployment, and evaluation. He is completing a *BSc in Mathematical Engineering in Data Science* at
*Universitat Pompeu Fabra* (Barcelona), where *Worldview* is his thesis #footnote[Thesis supervised by Víctor Casamayor (⚠️ confirm supervisor name/spelling).]. His work centres on
retrieval grounding, knowledge-graph extraction quality, and LLM-as-judge evaluation for finance NLP;
he has also published empirical asset-pricing research (SSRN; World Finance & Banking Symposium 2025)
and was a solo Top-5 finalist in the Southeastern Hedge Fund Competition 2026. He would present this
talk in person in Rome.

// ----------------------------- GENAI DISCLOSURE (MANDATORY, exact title, before refs, not counted) -----------------------------
= GenAI Usage Disclosure
// CIKM 2026 requires full disclosure of ALL GenAI use across research (code, data) and writing.
// ⚠️ Arnau: edit this to be truthful and complete for YOUR actual usage before submitting.
Generative AI tools were used during this work as follows. (i) #emph[System under study]: Worldview
itself uses LLMs as components — relation extraction, entity-description generation, and an
LLM-as-judge evaluation layer — as described above; these are the object of study, and all reported
metrics were computed over the system's own logs. (ii) #emph[Engineering]: AI coding assistants were
used to help implement and debug parts of the platform's codebase. (iii) #emph[Writing]: an AI
assistant was used to help draft and edit this proposal. All technical claims, numbers, system
descriptions, and conclusions were verified by the author against the system's evaluation artifacts
and are the author's own.

// ----------------------------- REFERENCES (do NOT count toward 2 pages) -----------------------------
= References
// ⚠️ Minimal placeholder set — expand/curate. Use ACM Reference Format at camera-ready.
#set text(size: 8.5pt)
#enum(
  numbering: "[1]",
  [Zaratiana, U. et al. GLiNER: Generalist Model for Named Entity Recognition using Bidirectional Transformer. NAACL 2024.],
  [Cormack, G., Clarke, C., Büttcher, S. Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods. SIGIR 2009.],
  [Apache AGE: A Graph Extension for PostgreSQL. Apache Software Foundation.],
  [Malkov, Y., Yashunin, D. Efficient and robust approximate nearest neighbor search using HNSW graphs. IEEE TPAMI 2020.],
  [Lewis, P. et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS 2020.],
)
