// CIKM 2026 Industry Day — Talk Proposal (Typst draft v7)
// =======================================================
// v7 = author's full rewrite. Cleaner 4-level structure (answer / substantiation / trajectory / calibration)
//   + "served-graph" finding + talk takeaways. Removed: traversal prototype, typed-block-split detail,
//   before/after deltas. Reframed "deployed/production" -> "locally operated" (honest). Numbers verified vs
//   FINAL-67 run_20260627T032420Z (matcher 8137117dd): trajectory 88.9, substantiation 56/0/0 over 22/67,
//   κ 0.59->0.80, served-graph 82.6%->48.8%/36.9%. Format: 2-page ACM SigConf; bio+refs+GenAI uncounted.

#set document(title: "A Multi-Level Evaluation Framework for Grounded Agentic RAG in a Continuously Operated Financial Intelligence System")
#set page(paper: "us-letter", margin: (x: 1.9cm, y: 2.2cm))
#set text(font: "New Computer Modern", size: 9.5pt)
#set par(justify: true, leading: 0.5em)
#set heading(numbering: "1")
#show heading: set text(size: 10.5pt, weight: "bold")
#show heading: set block(above: 0.85em, below: 0.45em)

#let pbox(b) = box(stroke: 0.5pt, inset: (x: 3pt, y: 2.5pt), radius: 2pt, text(7pt, b))
#let ar = text(8pt)[ #sym.arrow.r ]

#align(center)[
  #text(15pt, weight: "bold")[A Multi-Level Evaluation Framework for Grounded Agentic\
  RAG in a Continuously Operated Financial Intelligence System]

  #v(0.3em)
  #text(11pt)[Arnau Rodon Comas]\
  #text(9pt)[Universitat Pompeu Fabra · MeshX #footnote[Independent thesis work; not affiliated with or endorsed by MeshX.]]\
  #text(9pt, style: "italic")[rodonarnau\@gmail.com]
]

#v(0.5em)

#block(inset: (x: 0.6cm))[
  #text(weight: "bold")[Abstract.]
  We present #emph[Worldview], a locally operated financial-intelligence system used as a testbed for
  evaluating grounded agentic retrieval-augmented generation (RAG) [7]. The system answers analyst-style
  questions over a changing retrieval substrate: evidence-linked knowledge-graph relations, dense entity and
  passage embeddings, BM25 lexical search [8], and structured market data. Its graph is not static: entity
  representations are refreshed from multiple semantic views, relation confidence accumulates with corroborating
  evidence, and edge scores decay by predicate-specific timescale. This makes evaluation harder than in a frozen
  RAG benchmark, because users query the served graph and current retrieval state, not the extractor in
  isolation. Our central contribution is a #emph[multi-level evaluation framework] for this setting. Beyond an
  LLM answer-quality judge, the framework adds deterministic hard-fail gates, a grounding veto, numeric
  tool-output substantiation, trajectory judging over the captured tool-call trace, and calibration against a
  human-labelled gold set. The framework was motivated by real failures: a fabricated answer scored 85/100 under
  an additive judge, raw error strings scored perfectly, and tool-routing defects were invisible at answer
  level. In the latest frozen evaluation run, the trajectory judge scored 88.9/100 over 67 questions, and the
  current gated judge reached Cohen's κ = 0.80 with zero false-passes on fabrication. We also report a negative
  finding: fresh-extractor support substantially overestimated served-graph support, showing that live KG-RAG
  systems must evaluate the state users actually query.
]

#v(0.3em)

#columns(2, gutter: 0.7cm)[

= Problem and context
A financial question rarely has one retrieval shape. Fundamentals and earnings questions require structured
queries over time series and financial tables. Entity-and-relation questions require graph traversal. Thematic
questions require dense retrieval. Tickers, filing identifiers, and exact financial terms require lexical
search. A grounded financial assistant must therefore choose among heterogeneous tools, combine their outputs — dense
and lexical results merged by reciprocal-rank fusion [2] — and produce an answer whose claims trace back to
retrieved evidence.

The under-reported difficulty is not only retrieval quality, but #emph[trust under continuous operation]. A
deployed or continuously operated KG-RAG system changes over time: new documents arrive, entity descriptions are
refreshed, graph edges gain or lose confidence, and the served retrieval substrate drifts away from any single
extractor snapshot. Standard answer-level evaluation is insufficient in this setting. A final answer may look
coherent while using the wrong tool, ignoring returned values, citing stale graph state, or passing an
uncalibrated LLM judge.

This talk contributes two linked artifacts: first, #emph[Worldview], a continuously operated local
financial-intelligence system that makes these failure modes observable; second, a #emph[multi-level evaluation
framework] that measures the system at the answer, evidence, trajectory, and judge-calibration levels.

= Worldview as the testbed
Worldview is a local, continuously operated financial-intelligence system built around a living KG-RAG
substrate. In the latest frozen run, the instance processed #strong[14,427] news articles over the previous
seven days, resolved approximately #strong[248k] entity mentions into approximately #strong[28.8k] canonical
entities, and maintained a graph of approximately #strong[44.6k] vertices, including entities and temporal
events, with approximately #strong[15k] materialised relations. The system runs under an explicit monthly
model-cost ceiling, enforced by a learned routing gate that decides which documents deserve expensive
extraction.

The agent answers questions through a typed tool catalog rather than a fixed retrieval pipeline. Its tools
include graph traversal over evidence-linked relations, dense retrieval over pgvector/HNSW entity and passage
embeddings [3], BM25 lexical search [8], and structured market-data queries over prices, fundamentals, and
prediction-market snapshots. Each tool call, argument, status, latency, and result count is recorded as a
trace, which later becomes an evaluation object.

The graph is designed to model financial knowledge as a #emph[changing object]. Each canonical entity can be
represented through multiple refreshed views: a definitional view, an evidence-built narrative view, and, for
instruments, a market/fundamental view. This allows the same entity to be retrieved through different semantic
routes depending on the query. Relations carry confidence that increases with corroborating evidence and decays
over time according to the predicate class: a supplier relation, a board-membership relation, and an
intraday-sentiment relation should not remain equally fresh for the same duration. Contradictory evidence
demotes confidence rather than deleting the edge. Unlike summarisation-oriented graph RAG [5], every edge
points back to the passage that asserted it — which is what makes the evidence-level evaluation below possible.

#figure(
  block(breakable: false, inset: 7pt, stroke: 0.4pt, radius: 3pt, width: 100%)[
    #set align(center)
    #let sbox(b, w: auto, dash: false, fg: white) = box(
      stroke: (thickness: 0.5pt, dash: if dash { "dashed" } else { "solid" }),
      inset: (x: 5pt, y: 3.5pt), radius: 2.5pt, width: w, fill: fg,
    )[#align(center)[#text(8pt, b)]]
    #let dn = text(9.5pt)[#sym.arrow.b]
    #sbox[News / filings] \
    #dn \
    #sbox(w: 100%)[Ingestion: NER [1] · entity resolution · relation extraction · validation gates] \
    #dn \
    #sbox(w: 100%)[Living knowledge graph: Postgres + AGE + pgvector\ evidence-linked relations · multi-view embeddings · decaying confidence] \
    #dn \
    #sbox(w: 100%)[Agent: graph · dense (HNSW) · BM25 · market-data tools] \
    #dn \
    #sbox[Cited answer] \
    #text(7.5pt, fill: luma(110))[tool-call trace] #h(3pt) #dn \
    #sbox(w: 100%, dash: true, fg: luma(244))[#strong[Multi-level evaluation:] answer validity · substantiation · trajectory · judge calibration]
  ],
  caption: [Worldview ingestion-to-answer loop. News and filings pass through NER, entity resolution, relation
  extraction, and validation gates into a living knowledge graph; at query time an agent retrieves over graph,
  dense, lexical, and structured-market tools and returns a cited answer. The same tool-call trace is then
  consumed by the multi-level evaluation framework (dashed) — the contribution of this paper.],
)

This design is what motivates the evaluation framework. The system is not evaluated only as an extractor, nor
only as a chatbot. It is evaluated as a live retrieval-and-reasoning stack whose served state is the object
users actually query.

= Multi-level evaluation framework
The framework evaluates four levels, each catching failures that the previous level cannot see.

#strong[Level 1: answer validity.] The answer judge scores grounding, framing, tool use, and coherence, but
only after deterministic hard-fail gates and a grounding veto. These gates were added because of logged failures
that additive LLM scoring [4] did not reliably catch: an answer flagged as mostly fabricated still scored
#strong[85/100], a raw error string scored #strong[100/100], and leaked control tokens scored in the 90–100
range. The lesson is simple: LLM judges are useful, but some defects should be vetoed deterministically.

#strong[Level 2: tool-output substantiation.] A generated answer can pass answer-level checks while ignoring or
misusing the data returned by tools. The substantiation layer cross-checks numeric claims against actual tool
outputs. In the latest frozen benchmark, #strong[22 of 67] questions carried verifiable value-tool samples;
across those, every numeric claim the harness could check was grounded: #strong[56] substantiated, #strong[0]
contradicted, and #strong[0] unsupported. The check is deliberately precision-oriented: if the captured sample
does not contain the relevant period or metric, the claim is left #emph[unmatched] rather than falsely
contradicted. It is thus a high-precision corroborating floor; a figure simply #emph[absent] from the tool
payload is caught by the Level-1 grounding veto, not this numeric check.

#strong[Level 3: trajectory quality.] Agentic RAG must also be evaluated #emph[before] the final answer. The
trajectory judge reads the captured tool-call trace and scores routing, ordering, recovery, and efficiency,
supported by deterministic signals such as repeated identical empty calls or failed calls without a substitute.
This level drove a concrete system improvement: it surfaced that the agent overused free-text document search
and looped on empty results instead of selecting the matching structured tool. After sharpening tool
descriptions and adding a no-repeat-empty-query guardrail, the trajectory judge scored #strong[88.9/100] over
the full 67-question benchmark.

#strong[Level 4: judge calibration.] The judge is itself part of the system and must be measured. Against a
#strong[39]-item failure-mode-stratified human-labelled gold set, stored pre-gate verdicts achieved Cohen's
#strong[κ = 0.59], below the target bar. Re-scoring with the current gated judge raised agreement to
#strong[κ = 0.80], with raw agreement around 90% and #strong[zero] false-passes on fabrication. The important
result is not only the κ value, but the asymmetry: fabrication false-passes are treated as the safety-critical
cell and held to zero.

We also maintain an emerging #emph[reasoning-validity] layer that labels whether evidence-to-claim inferences
are supported, unsupported, or contradicted. We do not present it as a validated standalone benchmark yet,
because it remains LLM-judged. It is reported only as a diagnostic signal alongside deterministic
substantiation.

= Finding: served graph quality is the number that matters
The most important empirical lesson is that extractor quality can overstate user-facing quality. In one frozen
evaluation, fresh extraction reached #strong[82.6%] document support, while relations actually served from the
stored graph reached only #strong[48.8%] support volume-weighted, or #strong[36.9%] predicate-balanced [6]. The
gap appears because the live graph is a sediment of extractor versions, historical documents, validation rules,
and previous promotion decisions. Users do not query the fresh extractor; they query the served graph.

This finding changes what should be measured. A KG-RAG system can report strong extraction precision and still
serve stale, unsupported, or directionally wrong relations if the graph state is not evaluated directly.
Deterministic validation gates removed #strong[442] bad relations in the latest graph-quality pass, including
self-loops, out-of-vocabulary predicates, invalid `listed_on` relations, and common-noun endpoints. On the
current extractor, the same gates increasingly act as regression guards rather than active filters.

The general lesson is that live grounded RAG should be evaluated layer by layer: answer quality, evidence use,
tool trajectory, judge reliability, and served retrieval state. A system that #emph[reports] success is not
necessarily a system that #emph[is] correct.

= Talk takeaways
The talk is a technical field report on evaluating grounded agentic RAG under continuous operation. Attendees
will take away three practical lessons. #strong[First], answer-level LLM judging is necessary but insufficient:
deterministic vetoes and calibration are required for high-risk defects such as fabrication, raw errors, and
control-token leakage. #strong[Second], agentic systems must be evaluated at the tool level: the answer can be
acceptable while the trajectory is wasteful, brittle, or routed through the wrong retrieval surface.
#strong[Third], KG-RAG systems must evaluate the state actually served to users, not only the latest extractor.
In changing domains such as finance, the retrieval substrate is a living object, and evaluation must be designed
accordingly.

] // end two-column body

#v(0.5em)
#line(length: 100%, stroke: 0.4pt)
#set heading(numbering: none)
#set text(size: 9pt)
= Speaker details
*Arnau Rodon Comas* is a forward-deployed Machine Learning Engineer at *MeshX*, building production AI systems
for a major international airport group, with work spanning data modelling, ML pipelines, deployment, and
evaluation. He is completing a *BSc in Mathematical Engineering in Data Science* at *Universitat Pompeu Fabra*,
where Worldview is his final thesis project. His work focuses on retrieval grounding, knowledge-graph extraction
quality, and LLM-as-judge evaluation for financial NLP. He has published empirical asset-pricing research on
SSRN, presented at the World Finance & Banking Symposium 2025, and was a solo Top-5 finalist in the
Southeastern Hedge Fund Competition 2026. He would present in person in Rome.

= GenAI Usage Disclosure
Generative AI was used as follows. #strong[First], Worldview itself uses LLMs as system components: relation
extraction, entity-description generation, agentic retrieval, answer generation, and LLM-as-judge evaluation.
These components are the object of study. #strong[Second], AI coding assistants helped implement and debug parts
of the platform and evaluation harness. #strong[Third], an AI assistant helped run and inspect read-only
database queries and evaluation scripts; every reported metric was traced to a committed script or direct query
and verified by the author. #strong[Fourth], an AI assistant helped draft and edit this proposal. All technical
claims, measurements, and conclusions were verified by the author against the system's evaluation artifacts and
remain the author's own.

= References
#set text(size: 8.5pt)
#enum(
  numbering: "[1]",
  [Zaratiana, U., Tomeh, N., Holat, P., Charnois, T. GLiNER: Generalist Model for NER using a Bidirectional Transformer. NAACL 2024.],
  [Cormack, G. V., Clarke, C. L. A., Büttcher, S. Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods. SIGIR 2009.],
  [Malkov, Y. A., Yashunin, D. A. Efficient and Robust Approximate Nearest Neighbor Search Using HNSW Graphs. IEEE TPAMI 2020.],
  [Zheng, L., et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. NeurIPS 2023.],
  [Edge, D., et al. From Local to Global: A Graph RAG Approach to Query-Focused Summarization. arXiv:2404.16130, 2024.],
  [Mintz, M., Bills, S., Snow, R., Jurafsky, D. Distant Supervision for Relation Extraction without Labeled Data. ACL-IJCNLP 2009.],
  [Lewis, P., et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS 2020.],
  [Robertson, S., Zaragoza, H. The Probabilistic Relevance Framework: BM25 and Beyond. FnTIR 2009.],
)
