// CIKM 2026 Industry Day — Talk Proposal (Typst draft v3)
// =======================================================
// v3 after ground-truth measurement (see measurement-evidence.md).
// ONLY [verified, citable] numbers appear in the body. Snapshot: 2026-06-24T07:30Z,
// commit 7d6e535f, live instance intelligence_db / worldview_graph.
// Format: 2-page ACM SigConf; bio + references + "GenAI Usage Disclosure" do NOT count.
//
// CHANGES FROM v2:
//  - Headline leads with 48.8% volume-weighted (user-experienced); 36.9% balanced footnoted.
//  - Title now leads with the measurement contribution, not "Hybrid Retrieval".
//  - Problem opener de-pitched: technical framing, not market-gap rhetoric.
//  - Latency reframed as an HONEST OPEN PROBLEM that worsens with graph size;
//    stable 145s-naive anchor kept, contaminated p50/p95 dropped (single-operator contention).
//  - Graph retrieval confirmed live + un-timed-out, so four-modality fusion claim stands present-tense.
//  - "regression guarantee" reworded; positioning citations added (GraphRAG, LLM-judge, distant supervision).
//
// ⚠️ BEFORE SUBMISSION (only the author can close these):
//   1. CONFIRM DEADLINE in writing with chairs (official pages disagreed: 22 vs 26 Jun; file said 29).
//   2. Label the 64-item audit-judge sheet -> real Cohen's kappa (currently "in progress").
//   3. Fill admin placeholders: email, supervisor spelling, truthful GenAI disclosure.
//   4. (optional, hardens headline) larger-n fresh sample (n=46 -> 50-100 articles).
// ⚠️ CAMERA-READY: ACM TAPS accepts only LaTeX(acmart)+Word; port if accepted.

#set document(title: "Measuring a Continuously-Deployed Financial Knowledge Graph Honestly")
#set page(paper: "us-letter", margin: (x: 1.9cm, y: 2.2cm))
#set text(font: "New Computer Modern", size: 9.5pt)
#set par(justify: true, leading: 0.5em)
#set heading(numbering: "1")
#show heading: set text(size: 10.5pt, weight: "bold")
#show heading: set block(above: 0.9em, below: 0.5em)

#let pbox(b) = box(stroke: 0.5pt, inset: (x: 3pt, y: 2.5pt), radius: 2pt, text(7pt, b))
#let ar = text(8pt)[ #sym.arrow.r ]

// ----------------------------- TITLE BLOCK -----------------------------
#align(center)[
  #text(16pt, weight: "bold")[Measuring a Continuously-Deployed Financial Knowledge\
  Graph Honestly: A Field Report on Grounded Hybrid Retrieval]

  #v(0.3em)
  #text(11pt)[Arnau Rodon Comas]\
  #text(9pt)[Universitat Pompeu Fabra · MeshX #footnote[Independent thesis work; not affiliated with or endorsed by MeshX.]]\
  #text(9pt, style: "italic")[rodonarnau\@gmail.com] // ⚠️ confirm email to list
]

#v(0.5em)

#block(inset: (x: 0.6cm))[
  #text(weight: "bold")[Abstract.]
  We present the design and evaluation of #emph[Worldview], a deployed market-intelligence system that
  turns a continuous news stream into a financial knowledge graph (KG) and answers analyst questions as
  an agentic, citation-grounded assistant. A research agent plans and calls tools over a #emph[hybrid
  retrieval] substrate fusing graph traversal (Apache AGE), dense vectors (pgvector/HNSW), lexical BM25,
  and structured market data (prices, fundamentals, prediction markets). Our contribution is not the
  stack but a candid account of #emph[measuring such a system honestly] once it is continuously deployed
  and #emph[never backfilled], so the stored graph accretes output from several extractor versions. The
  headline tension, measured under #emph[one identical judge and rubric] (Qwen3-235B, binary
  "document-supported"): fresh extraction is #strong[82.6%] supported (38/46; 95% CI 69–92%), yet the
  relations a user actually retrieves from the #emph[stored] graph are only #strong[48.8%] supported
  (volume-weighted; #strong[36.9%] predicate-balanced; n=382) — quality roughly #emph[halves] between
  extraction and storage, driven by unsupported and wrong-direction relations, not exotic ones. We show
  that deterministic validation gates are necessary but insufficient, that an LLM-as-judge layer must
  itself be hardened against failure modes we observed in production, and that fresh-extractor precision
  is the wrong number to trust. The talk is an honest field report on operating and measuring a grounded
  financial KG at single-operator scale.
]

#v(0.3em)

#columns(2, gutter: 0.7cm)[

= Problem and context
A financial question rarely has one retrieval shape. Fundamentals and earnings need structured queries
over time series; entity-and-relation questions (“which suppliers does NVIDIA share with AMD?”) need
graph traversal; thematic questions need dense retrieval; tickers and filing codes need exact-token
match — and every answer must trace back to the text or datum that supports it. No single retriever
covers this, so Worldview fuses four over one corpus and grounds each claim with a citation. Just as
hard as building it is #emph[trusting] it: once the system runs continuously, the number that says it
works and the graph a user actually queries drift apart.

Worldview is built end-to-end as a #emph[deployed, live system] — ten event-driven microservices
(FastAPI, Kafka, PostgreSQL/TimescaleDB, pgvector, Apache AGE, MinIO, Valkey) with a Next.js front end
— and is evaluated under realistic, single-operator thesis-scale settings. As of June 2026 the running
instance ingests #strong[~2,000–3,200 news articles/day] (14,427 over the last 7 days), resolves
#strong[~248k] entity mentions to #strong[~28.8k] canonical entities, and maintains a graph of
#strong[~44.6k vertices] (28.8k entities + 15.9k temporal events) with #strong[~14.9k materialised
relations], at low operating cost (the metered-extraction ledger records ≈#strong[\$17/30 days]; some
self-hosted calls are not cost-attributed, so true spend is modestly higher). It is a small but genuine
operating system whose quality we can audit honestly — and the honest answer is uncomfortable.

= System: agentic hybrid retrieval over a financial KG
A research agent answers each query through a planning loop with an explicit tool budget: it selects
tools from a typed catalog, executes them concurrently, and synthesises a streamed, cited answer; every
step (tool call, latency, result count) is surfaced as a live research trace.

#figure(
  block(breakable: false)[
    #set align(center)
    #pbox[News] #ar #pbox[GLiNER NER] #ar #pbox[Entity resolution] #ar #pbox[LLM extraction]
    #v(3pt)
    #pbox[Validation gates] #ar #pbox[KG: Postgres + AGE + pgvector]
    #v(3pt)
    #pbox[Hybrid retrieval] #ar #pbox[Agent] #ar #pbox[Cited answer]
  ],
  caption: [Pipeline: news articles are tagged (GLiNER NER, 11 classes), entity-resolved, and turned
  into relations by an LLM; deterministic gates filter structural defects before promotion into a
  Postgres+AGE+pgvector knowledge graph; a tool-using agent retrieves over graph, dense vectors, BM25,
  and structured market data and returns a cited answer. (Alt text: a left-to-right data-flow diagram of
  the Worldview ingestion-to-answer pipeline, news on the left through to a cited answer on the right.)],
)

#strong[Hybrid retrieval.] The agent composes four retrievers over one corpus, fused by reciprocal-rank
fusion [2]: AGE #emph[graph traversal] for entity-anchored multi-hop context; #emph[dense vectors]
(pgvector + HNSW [4], cosine) over chunk, section, and entity-profile embeddings; #emph[BM25] as a
recall floor; and #emph[structured market data] — OHLCV, fundamentals, and prediction-market snapshots
— retrieved as first-class tools. Retriever choice is intent-aware, and answers carry citations
resolved back to a relation, an article snippet, or a `(period, metric)` tuple. Unlike
summarisation-oriented graph RAG [6], the graph here is a #emph[typed, evidence-linked] store in which
every edge points back to the passage that asserted it — which is precisely what makes the quality
audit below possible.

#strong[Graph traversal is the binding constraint — an open problem.] Graph retrieval is live in the
query path (not gated behind a timeout), but it is expensive and #emph[grows worse as the graph grows].
A naive explicit-edge expansion sequential-scans every edge-label table and is pathologically slow
(≈#strong[145 s] for a single hop under `EXPLAIN ANALYZE` on the live graph); variable-length traversal
with a hop cap makes it usable, but bringing graph retrieval to interactive latency as edge count rises
is a scaling problem we have #emph[not] fully solved. We report this as an open problem rather than hide
it behind a benchmark run on an idle machine: under single-operator resource contention, traversal
latency is variable and environment-bound, so we deliberately omit a headline p95 we could not reproduce
across load conditions.

= Honest measurement of a non-backfilled grounded KG
This is the heart of the talk. Because the instance is #emph[continuously deployed and not backfilled]
after pipeline fixes, the stored graph is a sediment of several extractor generations — which makes the
usual benchmark numbers actively misleading. Three findings, at three layers, make one point.

#strong[1. Fresh-extractor "precision" is the wrong number.] Under one identical rubric (Qwen3-235B,
binary "document-supported"), fresh extraction is #strong[82.6%] supported (38/46; 95% CI 69–92%),
while the #strong[382]-relation #emph[stored] audit — same judge, same rubric, stratified across all
predicates and both extractor eras — shows that the relations a user actually retrieves are only
#strong[48.8%] supported (volume-weighted)#footnote[Predicate-balanced support is harsher still, 36.9%;
we lead with the volume-weighted figure because it reflects what the system actually serves at query
time.]. Stored quality is roughly #emph[half] of fresh. An earlier soft 1–5 rubric flattered fresh
extraction to ≈5/5 — which is exactly why we report #emph[support rates], not “precision,” and never
compare across judges.

#strong[2. The defects are mundane, not exotic.] The stored-graph shortfall is dominated by
#strong[unsupported (36.6%)] and #strong[wrong-direction (14.7%)] relations — the classic false
positives of distant-supervision-style extraction [7]; true "co-mention" errors are only #strong[8.6%].
The lesson for practitioners: chase the boring failure mass, not the interesting one.

#strong[3. Gates help but cannot close it; the judge needs guarding too.] Deterministic gates
(self-loop, out-of-vocabulary predicate, invalid `listed_on`, common-noun endpoint) removed
#strong[442] bad relations and raised `listed_on` support to #strong[86%]; on the current extractor the
gates now drop #strong[0/32] candidates — they have shifted from active filter to a #emph[regression
guard] against future drift, but they are blind to the semantic mass above. Closing that gap needs a
model judge — which has its own failure modes. Our first answer-quality judge used an additive rubric
that let broken output pass: in a real logged run, an answer flagged "most claims fabricated" still
scored 85/100, a raw error string scored 100/100, and leaked control tokens scored 90–100. The fix was
architectural — a grounding veto, degenerate-answer pre-checks, and failure-first reporting [5]. We hold
the #emph[stored-graph] audit judge to the same skepticism: an independent stratified re-draw reproduces
it (35.9% supported, n=64) and human verification of its verdicts is in progress. The same theme recurs
in operations — a silent prompt/lookup mismatch once discarded roughly four-fifths of extracted
relations, and resource-starved NER timed out and dropped articles, both invisible to green dashboards.
#emph[A system that reports success is not the same as a system that is correct]; for grounded KGs, only
layer-aware, failure-first measurement tells them apart. Code and evaluation scripts are public.

] // end two-column body

// ----------------------------- BACK MATTER (uncounted) -----------------------------
#v(0.5em)
#line(length: 100%, stroke: 0.4pt)
#set heading(numbering: none)
= Speaker details
*Arnau Rodon Comas* is a forward-deployed Machine Learning Engineer at *MeshX*, building production AI
systems for a major international airport group (data modelling, ML pipelines, deployment, evaluation).
He is completing a *BSc in Mathematical Engineering in Data Science* at *Universitat Pompeu Fabra*
(Barcelona), where *Worldview* is his thesis #footnote[Thesis supervised by Víctor Casamayor (⚠️ confirm name/spelling).]. His work
centres on retrieval grounding, knowledge-graph extraction quality, and LLM-as-judge evaluation for
finance NLP; he has published empirical asset-pricing research (SSRN; World Finance & Banking Symposium
2025) and was a solo Top-5 finalist in the Southeastern Hedge Fund Competition 2026. He would present in
person in Rome.

= GenAI Usage Disclosure
// ⚠️ Edit to reflect actual usage truthfully and completely before submitting.
Generative AI was used as follows. (i) #emph[System under study]: Worldview itself uses LLMs as
components — relation extraction, entity-description generation, and an LLM-as-judge evaluation layer;
these are the object of study, and all reported metrics were computed over the system's own
logs/databases. (ii) #emph[Engineering]: AI coding assistants helped implement and debug parts of the
platform. (iii) #emph[Measurement]: an AI agent assisted in running the read-only database queries and
evaluation scripts whose outputs are reported here; every number was traced to a committed script or a
direct query and verified by the author. (iv) #emph[Writing]: an AI assistant helped draft and edit this
proposal. All technical claims, numbers, and conclusions were verified by the author against the
system's evaluation artifacts and are the author's own.

= References
#set text(size: 8.5pt)
#enum(
  numbering: "[1]",
  [Zaratiana, U., Tomeh, N., Holat, P., Charnois, T. GLiNER: Generalist Model for NER using a Bidirectional Transformer. NAACL 2024.],
  [Cormack, G. V., Clarke, C. L. A., Büttcher, S. Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods. SIGIR 2009.],
  [Apache AGE: A Graph Extension for PostgreSQL. Apache Software Foundation.],
  [Malkov, Y. A., Yashunin, D. A. Efficient and Robust Approximate Nearest Neighbor Search Using HNSW Graphs. IEEE TPAMI 2020.],
  [Zheng, L., et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. NeurIPS 2023.],
  [Edge, D., et al. From Local to Global: A Graph RAG Approach to Query-Focused Summarization. arXiv:2404.16130, 2024.],
  [Mintz, M., Bills, S., Snow, R., Jurafsky, D. Distant Supervision for Relation Extraction without Labeled Data. ACL-IJCNLP 2009.],
)
