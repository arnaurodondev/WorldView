// CIKM 2026 Industry Day — Talk Proposal (Typst draft v6)
// =======================================================
// v6 = v5 + REAL post-fix numbers (run_20260626T072542Z, gold _v3_regrade_kappa.json) + improvement loop.
// NEW: trajectory 84.6->87.7 (eval surfaced a routing sink -> fixed, unrecovered 36->24); judge κ=0.80
//   current-gated (vs 0.59 stored mixed-era); substantiation reframed as the honest 3-gap "measuring the
//   measurer" journey (19/19 substantiated on verifiable latest-period claims; whole-answer rate awaits
//   multi-row sampling). DO NOT print the 81%/72% substantiation artifacts; the 81.6->69.5 answer-judge dip
//   is a single-row contradiction-veto ARTIFACT (not a regression) and is NOT cited.
// v5 spine retained — the contribution is TWO parts:
//   (1) THE LIVING SYSTEM — a deployed grounded agentic RAG with hybrid retrieval
//       (AGE + pgvector/HNSW + BM25 + structured market data), typed-block split
//       fusion, multi-view entity embeddings, a cost-controlled learned routing
//       gate, and a continuously-updated "living graph" (weekly tri-embedding
//       refresh, edge temporal decay on six timescales, contradiction-demotes-confidence).
//   (2) THE MULTI-LEVEL EVALUATION FRAMEWORK — answer-level (4 LLM dims + 7
//       deterministic hard-fail gates + grounding veto), tool-output substantiation,
//       trajectory / tool-chain judge, judge calibration (Cohen's kappa vs human
//       gold), and an emerging reasoning-validity layer (honestly caveated).
// v4's "honest measurement of a non-backfilled KG" is DEMOTED to a FINDING, not the headline.
//
// ONLY [verified, citable] numbers in the body; every figure traces to
//   docs/cikm-proposal/measurement-evidence.md, docs/audits/2026-06-24-age-traversal-latency-optimization.md,
//   docs/plans/0115-multi-level-eval-framework-plan.md, or gold/_calibration_report.md.
// All finding-run numbers are now filled with real measured values.
// Format: 2-page ACM SigConf; bio + references + "GenAI Usage Disclosure" do NOT count.
//
// PUNCTUATION RULE (carried from v4): never place a period/semicolon flush against a
//   closing ] of #strong[...]/#emph[...]; bold tokens stay mid-sentence, followed by plain text.
//
// ⚠️ BEFORE SUBMISSION (author only): confirm deadline; fill email/supervisor-spelling/GenAI; trim to 2pp;
//   CAMERA-READY: port to LaTeX(acmart) — TAPS rejects Typst. (Finding-run numbers now filled.)

#set document(title: "A Multi-Level Evaluation Framework for Grounded Agentic RAG, Built and Operated in Production")
#set page(paper: "us-letter", margin: (x: 1.9cm, y: 2.2cm))
#set text(font: "New Computer Modern", size: 9.5pt)
#set par(justify: true, leading: 0.5em)
#set heading(numbering: "1")
#show heading: set text(size: 10.5pt, weight: "bold")
#show heading: set block(above: 0.85em, below: 0.45em)

#let pbox(b) = box(stroke: 0.5pt, inset: (x: 3pt, y: 2.5pt), radius: 2pt, text(7pt, b))
#let ar = text(8pt)[ #sym.arrow.r ]

// ----------------------------- TITLE BLOCK -----------------------------
#align(center)[
  #text(16pt, weight: "bold")[A Multi-Level Evaluation Framework for Grounded\
  Agentic RAG, Built and Operated in Production]

  #v(0.3em)
  #text(11pt)[Arnau Rodon Comas]\
  #text(9pt)[Universitat Pompeu Fabra · MeshX #footnote[Independent thesis work; not affiliated with or endorsed by MeshX.]]\
  #text(9pt, style: "italic")[rodonarnau\@gmail.com] // ⚠️ confirm email to list
]

#v(0.5em)

#block(inset: (x: 0.6cm))[
  #text(weight: "bold")[Abstract.]
  We present #emph[Worldview], a deployed market-intelligence system, and a #emph[multi-level evaluation
  framework] for grounded agentic retrieval-augmented generation (RAG) built around it. The system is a
  living one: a research agent answers analyst questions over a #emph[hybrid retrieval] substrate spanning
  Apache AGE graph traversal, pgvector/HNSW dense vectors, lexical BM25, and structured market data (prices,
  fundamentals, prediction markets), fused by reciprocal-rank fusion with a #emph[typed-block split] that
  routes structured outputs around the reranker. A learned, cost-controlled routing gate holds operating
  cost under a fixed monthly ceiling, and a #emph[continuously-updated] knowledge graph refreshes each
  entity's tri-view embeddings weekly, decays edges on six timescales, and lets contradicting evidence demote
  confidence without deletion. Our second and central contribution is how we #emph[evaluate] such a system:
  beyond a hardened answer-quality judge (four LLM dimensions plus seven deterministic hard-fail gates and a
  grounding veto), we add a #emph[tool-output substantiation] check (does the answer actually use the
  retrieved data?), a #emph[trajectory] judge over the captured tool-call trace, and #emph[judge calibration]
  against a human-labelled gold set, with an honestly-caveated emerging #emph[reasoning-validity] layer. Real
  production failures — an answer flagged "most claims fabricated" that scored 85/100 — motivate the
  deterministic gates; the framework also proved active rather than passive — it surfaced a tool-routing
  defect we then fixed, with the trajectory judge scoring 88.9/100 over the full 67-question benchmark, while a current-judge calibration of κ = 0.80
  (zero false-passes on fabrication) cleared our acceptance bar. We also report a sobering finding: under one
  frozen judge, fresh-extraction support (82.6%) roughly halves to served-graph support, because the number
  that matters is the graph users query, not the extractor's precision. The talk is a field report on building and measuring grounded agentic
  RAG honestly, in production, at single-operator scale.
]

#v(0.3em)

#columns(2, gutter: 0.7cm)[

= Problem and context
A financial question rarely has one retrieval shape. Fundamentals and earnings need structured queries over
time series; entity-and-relation questions (“which suppliers does NVIDIA share with AMD?”) need graph
traversal; thematic questions need dense retrieval; tickers and filing codes need exact-token match — and
every answer must trace back to the text or datum that supports it. No single retriever covers this. The
harder, and under-reported, problem is #emph[trusting] such a system once it runs continuously: standard
benchmarks score a frozen snapshot, but a deployed grounded RAG is a moving target whose answers, tool
choices, and graph all drift. This talk contributes (i) #emph[the living system] — an integrated, deployed
grounded agentic RAG — and (ii) #emph[a multi-level evaluation framework] that measures it at the answer,
tool-output, trajectory, and judge-calibration levels.

Worldview is built end-to-end as a #emph[deployed, live system] — ten event-driven microservices (FastAPI,
Kafka, PostgreSQL/TimescaleDB, pgvector, Apache AGE) with a Next.js front end — evaluated under realistic
single-operator settings. As of June 2026 the running instance ingests #strong[~2,000–3,200 news
articles/day] (14,427 over the last 7 days), resolves #strong[~248k] entity mentions into #strong[~28.8k]
canonical entities, and maintains a graph of #strong[~44.6k vertices] (28.8k entities + 15.9k temporal
events) holding #strong[~15k] materialised relations, all under a fixed #strong[~\$200/month] budget ceiling
enforced by the learned routing gate below — a real system run within a hard cost bound, not an idealised one.

= Part 1: the living system
A research agent answers each query through a planning loop with an explicit tool budget: it selects tools
from a typed catalog, executes them concurrently, and synthesises a streamed, cited answer; every step (tool
call, latency, result count) is surfaced as a live research trace — the same trace the trajectory judge later
consumes.

#figure(
  block(breakable: false)[
    #set align(center)
    #pbox[News] #ar #pbox[GLiNER NER] #ar #pbox[Entity resolution] #ar #pbox[LLM extraction]
    #v(3pt)
    #pbox[Validation gates] #ar #pbox[KG: Postgres + AGE + pgvector]
    #v(3pt)
    #pbox[Hybrid retrieval] #ar #pbox[Agent] #ar #pbox[Cited answer]
  ],
  caption: [Pipeline: news articles are tagged (GLiNER NER [1], 11 classes), entity-resolved, and turned into
  relations by an LLM; deterministic gates filter structural defects before promotion into a continuously-updated
  Postgres+AGE+pgvector knowledge graph; a tool-using agent retrieves over graph, dense vectors, BM25, and
  structured market data and returns a cited answer. (Alt text: a left-to-right data-flow diagram of the
  Worldview ingestion-to-answer pipeline, news on the left through to a cited answer on the right.)],
)

#strong[Cost-controlled learned routing.] Deep extraction is the expensive step, so a relevance gate runs
first: cheap signals — entity density, source authority, recency, document type, and an extraction-yield
proxy — route each article into one of four processing tiers #emph[before] any embedding or LLM call. We
replaced the hand-weighted gate with a learned one that embeds the title/subtitle and predicts extraction
yield, escalating only ambiguous articles to an LLM tiebreak. It is what keeps the system inside its fixed
monthly budget ceiling without starving extraction on the articles that matter.

#strong[Hybrid retrieval with typed-block split fusion.] An agent composes four retrievers over one corpus
through typed tool calls — not a fixed pipeline: AGE #emph[graph traversal] for entity-anchored multi-hop
context; #emph[dense vectors] (pgvector + HNSW [4], cosine); #emph[BM25] as a recall floor; and
#emph[structured market data] (OHLCV, fundamentals, prediction markets) as first-class tools. Fusion is
deliberately split: inside hybrid document search, vector and BM25 results merge by reciprocal-rank fusion
[2], but structured outputs (graph edges, financial rows, claims) bypass the reranker and reach the model as
#emph[typed blocks] (`<graph_facts>`, `<structured_data>`) rather than stringified prose — a cross-encoder
adds nothing on tuple-shaped artifacts, and preserving structure preserves the numbers the model must reason
over. Each canonical entity also carries up to three #emph[embedding views] — a definition, an
evidence-built narrative, and (for instruments) a fundamentals+OHLCV view — each under its own partial HNSW
index, so definitional, contextual, and numerical questions reach the same node by different routes. Unlike
summarisation-oriented graph RAG [6], the graph here is a #emph[typed, evidence-linked] store in which every
edge points back to the passage that asserted it — which is precisely what makes the evaluation below
possible.

#strong[The living graph.] The graph is not a frozen snapshot. Each entity's three embedding views are
#emph[re-textualised and re-embedded weekly] (definition / fundamentals+OHLCV / news), so the dense substrate
tracks fresh fundamentals and recent news rather than ossifying at ingest time. Edges #emph[decay] on one of
six timescales by predicate, and contradicting evidence #emph[demotes] an edge's confidence without deleting
it. A continuously-deployed grounded RAG must therefore be evaluated as a #emph[living object], not a one-shot
benchmark — the motivation for the framework in Part 2.

#strong[Graph traversal is the binding constraint.] Graph retrieval is live in the query path, but it is
expensive and worsens as the graph grows. AGE's variable-length traversal is single-threaded path
enumeration: on the live graph its pairwise latency is #strong[p95 ≈ 0.9 s] idle but rises to #strong[~17 s]
under single-operator contention, and depth-4 discovery #emph[times out]. A reproducible relational
#emph[prototype] — an indexed edge projection plus a settled-set (`UNION`) recursive CTE — answers the same
connectivity question in #strong[≈4 ms p50 / 53 ms p95] (~20× faster, two hops deeper), same host [3]. We
label it a #emph[prototype measuring connectivity], not yet a shipped path-enumeration replacement, and
report the candid lesson: a graph extension's traversal engine lost to plain indexed SQL on a 15k-edge graph.

= Part 2: the multi-level evaluation framework
The central contribution is measuring the system above at four levels, each catching failures the level below
cannot see.

#strong[Answer level: gates before judgement.] The answer judge scores four LLM dimensions (grounding,
framing, tool-use, coherence) but only #emph[after] seven deterministic hard-fail gates and a grounding veto.
Those gates exist because of real, logged failures: in a pre-fix run an answer flagged “most claims
fabricated” still scored #strong[85/100], a raw error string scored #strong[100/100], and leaked control
tokens scored #strong[90–100]. No additive LLM rubric catches these reliably; deterministic veto does — but
gates are necessary, not sufficient, so three further levels follow.

#strong[Tool-output substantiation — measuring the measurer.] An answer can pass every answer-level check and
still #emph[ignore] the data it retrieved, asserting numbers the tools never returned. We built a
deterministic check that cross-references each numeric claim against the actual values the tools returned.
Standing it up was itself an exercise in failure-first measurement: it took #emph[three] successive,
individually-invisible fixes before it produced a trustworthy signal — the retrieval layer first sampled
entity #emph[identifiers], not values; once values flowed, the judge's input path silently #emph[dropped]
them; once consumed, the matcher over-extracted #emph[structural] numbers (years, row indices) and our
single-row samples falsely #emph[contradicted] multi-period answers. Each gap was invisible until we read the
per-claim outputs. Hardened, the check runs over the full #strong[67]-question benchmark: #strong[22] questions
carry verifiable value-tool samples, and across them every numeric claim the harness can check is grounded —
#strong[56] substantiated, #strong[0] contradicted, #strong[0] unsupported. The remaining numeric claims
reference metrics or periods the captured sample does not hold, so the check leaves them #emph[unmatched]
rather than false-flag them — a deliberate precision-over-recall stance under which a #emph[reported]
contradiction is trustworthy (a time-series sample can substantiate a claim it contains but cannot disprove an
unsampled period). It is therefore a high-precision corroborating floor, not the whole grounding story: a
figure simply #emph[absent] from what the tools returned is caught by the answer-level grounding veto, not
this numeric check — we lean on both. The meta-point is the talk's thesis turned on ourselves: a measurement harness that
#emph[reports] a number is not the same as one that is #emph[correct].

#strong[Trajectory / tool-chain quality — the eval driving improvement.] The captured trace — ordered tool
names, arguments, status, and result counts — is itself judged: a trajectory judge scores routing, ordering,
failure-recovery, and efficiency, corroborated by deterministic signals (repeated identical calls; failed
calls with no successful substitute). The two weakest dimensions, efficiency and routing, traced to a
#emph[single] behavior the eval surfaced: the agent defaulted to free-text document search (32% of all tool
calls), looping on empty results instead of the matching structured tool. This is exactly the loop the
framework exists to close — we sharpened tool routing and added an enforced no-repeat-empty-query guardrail.
Over the full #strong[67]-question benchmark the trajectory judge now scores #strong[88.9/100] (ordering 24.6,
recovery 22.3, routing 22.4, efficiency 19.6 out of 25 each), with the deterministic signals corroborating. A
respectable final answer can ride a wasteful path, a class only trajectory-level evaluation exposes.

#strong[Judge calibration.] An LLM judge must itself be measured against humans. Against a #strong[39]-item,
failure-mode-stratified, human-labelled gold set, the judge scored on its #emph[stored] verdicts gives Cohen's
#strong[κ = 0.59] — below a 0.7 bar — but that set deliberately mixes #emph[pre-gate] outputs the current
judge no longer produces. Re-scored with the #emph[current] gated judge, agreement rises to #strong[κ = 0.80]
(raw agreement 90%, #strong[zero] false-passes on fabrication), above bar, with the safety-critical
false-pass-on-fabrication cell — the asymmetry we hold to zero — empty. A single κ would have hidden that the
deterministic gates are exactly what moved it.

#strong[Emerging: reasoning validity.] Finally, a minimal reasoning-validity layer labels whether each
evidence→claim inference is supported, unsupported, or contradicted by the cited evidence. We ship it as an
#emph[emerging] signal only, with an explicit caveat: this judge is itself an LLM — the very component the
talk warns about — so we report only its agreement with the #emph[deterministic] substantiation check, never
a standalone validated benchmark.

= A finding, not the headline: served quality is what counts
Because the instance is continuously deployed and #emph[not backfilled], its stored graph is a sediment of
several extractor generations — so the extractor's #emph[fresh] precision badly overstates what users
retrieve. Under one #emph[single frozen open-weight judge] and an identical binary "document-supported"
rubric, fresh extraction reaches #strong[82.6%] support (38/46; 95% CI 69–92%), while the relations actually
served from the stored graph are only #strong[48.8%] supported (volume-weighted; #strong[36.9%]
predicate-balanced; n=382) — stored quality roughly #emph[halves], dominated by mundane #emph[unsupported]
and #emph[wrong-direction] relations [7], not exotic ones. Deterministic gates (self-loop, out-of-vocabulary
predicate, invalid `listed_on`, common-noun endpoint) removed #strong[442] bad relations and lifted
`listed_on` support to #strong[86%] overall; on the current extractor the same gates now drop #strong[0/32] candidates, having
shifted from filter to #emph[regression guard]. The lesson generalises: the number to trust is #emph[served-graph]
support under one frozen judge, and only #emph[layer-aware, failure-first] measurement — answer, tool-output,
trajectory, and calibrated judge together — tells a system that #emph[reports] success apart from one that
#emph[is] correct. Code and evaluation scripts are public.

] // end two-column body

// ----------------------------- BACK MATTER (uncounted) -----------------------------
#v(0.5em)
#line(length: 100%, stroke: 0.4pt)
#set heading(numbering: none)
= Speaker details
*Arnau Rodon Comas* is a forward-deployed Machine Learning Engineer at *MeshX*, building production AI
systems for a major international airport group (data modelling, ML pipelines, deployment, evaluation). He is
completing a *BSc in Mathematical Engineering in Data Science* at *Universitat Pompeu Fabra* (Barcelona),
where *Worldview* is his thesis #footnote[Thesis supervised by Víctor Casamayor (⚠️ confirm name/spelling).]. His work centres on
retrieval grounding, knowledge-graph extraction quality, and LLM-as-judge evaluation for finance NLP; he has
published empirical asset-pricing research (SSRN; World Finance & Banking Symposium 2025) and was a solo
Top-5 finalist in the Southeastern Hedge Fund Competition 2026. He would present in person in Rome.

= GenAI Usage Disclosure
// ⚠️ Edit to reflect actual usage truthfully and completely before submitting.
Generative AI was used as follows. (i) #emph[System under study]: Worldview itself uses LLMs as components —
relation extraction, entity-description generation, and a multi-level LLM-as-judge evaluation framework; these
are the object of study, and all reported metrics were computed over the system's own logs/databases. (ii)
#emph[Engineering]: AI coding assistants helped implement and debug parts of the platform and the evaluation
harness. (iii) #emph[Measurement]: an AI agent assisted in running the read-only database queries and
evaluation scripts whose outputs are reported here; every number was traced to a committed script or a direct
query and verified by the author, and pending finding-run values are explicitly marked. (iv) #emph[Writing]:
an AI assistant helped draft and edit this proposal. All technical claims, numbers, and conclusions were
verified by the author against the system's evaluation artifacts and are the author's own.

= References
#set text(size: 8.5pt)
#enum(
  numbering: "[1]",
  [Zaratiana, U., Tomeh, N., Holat, P., Charnois, T. GLiNER: Generalist Model for NER using a Bidirectional Transformer. NAACL 2024.],
  [Cormack, G. V., Clarke, C. L. A., Büttcher, S. Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods. SIGIR 2009.],
  [Apache AGE: A Graph Extension for PostgreSQL. Apache Software Foundation. (Variable-length traversal vs. recursive-CTE settled-set connectivity; PostgreSQL §7.8 recursive WITH.)],
  [Malkov, Y. A., Yashunin, D. A. Efficient and Robust Approximate Nearest Neighbor Search Using HNSW Graphs. IEEE TPAMI 2020.],
  [Zheng, L., et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. NeurIPS 2023.],
  [Edge, D., et al. From Local to Global: A Graph RAG Approach to Query-Focused Summarization. arXiv:2404.16130, 2024.],
  [Mintz, M., Bills, S., Snow, R., Jurafsky, D. Distant Supervision for Relation Extraction without Labeled Data. ACL-IJCNLP 2009.],
)
