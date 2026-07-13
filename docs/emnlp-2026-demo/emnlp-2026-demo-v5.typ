// EMNLP 2026 System Demonstrations — draft v5
// =====================================================================
// Changes vs v4 (post 5-agent audit; see docs/emnlp-2026-demo/v4-review.md):
//  - INTEGRITY fixes verified against committed artifacts:
//      * judge agreement kappa 0.95 -> 0.7953 (raw agr 0.8974, confusion
//        17/1/3/18, 0 false-passes on fabrication) [gold/_v3_regrade_kappa.json]
//      * routing baseline relabelled: deployed heuristic is the static-rule
//        router (AUC 0.639 / Brier 0.249), not the 0.779 GBM; learned gate
//        0.828 / 0.151 [2026-06-12-routing-classifier-ablation.md, row D vs C]
//  - NUMBER POLICY (author directive): keep only claim-bearing, defensible
//    numbers; drop transient/unbacked ones (latency p50/p95, spend point
//    estimate, corpus article count, citation-faithfulness 0.57) -> stated
//    qualitatively.
//  - FACT fixes: prediction ingestion is FIVE Polymarket endpoints (not four);
//    only 3 of 5 prediction tables are hypertables; filings floored at >=MEDIUM;
//    learned-router fallback triggers on headline-less docs.
//  - abstract rewritten to problem -> what/how/achieves -> continuous eval.
//  - de-duplicated (NVIDIA-TSMC example, evidence-contract, caveats stated once).
//  - paper size us-letter -> A4 (ACL requirement).
// Venue: 6pp body / 2pp appendix / two-column MANDATORY / single-blind /
// mandatory 2.5-min screencast / live demo or installable package.
//
// Canonical snapshots (never mixed):
//   graph scale           = thesis evaluation snapshot (June 2026)
//   answer benchmark      = 3 runs x 97 questions, 2026-07-08/09
//   routing ablation      = offline 5-fold CV, 15,006 articles
//   prediction-market e2e = live QA traces (June-July 2026), code-audited

#set document(title: "Worldview: Continuous Financial Knowledge-Graph Construction and Grounded Multimodal Question Answering")
#set page(paper: "a4", margin: (x: 1.9cm, y: 2.2cm), numbering: "1")
#set text(font: "New Computer Modern", size: 10pt)
#set par(justify: true, leading: 0.52em, first-line-indent: 1.2em, spacing: 0.52em)
#set heading(numbering: "1.1")
#show heading: set text(size: 10.5pt, weight: "bold")
#show heading.where(level: 1): set text(size: 11.5pt)
#show heading: set block(above: 0.9em, below: 0.5em)
#show heading: set par(first-line-indent: 0em)
#show figure.caption: set text(size: 9pt)
#show figure: set block(above: 0.9em, below: 0.9em)

#let c(..keys) = text(fill: rgb("#123a7a"))[[#keys.pos().map(str).join(", ")]]
#let todo(b) = text(fill: rgb("#aa0000"), weight: "bold", b)

#let sbox(b, w: auto, fg: white) = box(
  stroke: 0.5pt, inset: (x: 4pt, y: 3pt), radius: 2.5pt, width: w, fill: fg,
)[#align(center)[#text(7.6pt, b)]]
#let lbox(b, w: auto, fg: white) = box(
  stroke: 0.5pt, inset: (x: 4pt, y: 3pt), radius: 2.5pt, width: w, fill: fg,
)[#text(7.4pt, b)]
#let dn = text(9pt)[#sym.arrow.b]
#let ar = text(8pt)[#sym.arrow]

// ---------------------------------------------------------------------------
// Title block + abstract
// ---------------------------------------------------------------------------
#place(top, float: true, scope: "parent", clearance: 1.2em)[
  #align(center)[
    #text(16.5pt, weight: "bold")[
      Worldview: Continuous Financial Knowledge-Graph\ Construction and Grounded Multimodal Question Answering
    ]
    #v(0.5em)
    #text(11pt)[Arnau Rodon Comas]\
    #text(10pt)[Universitat Pompeu Fabra, Barcelona]\
    #text(10pt, style: "italic")[arnau.rodon\@upf.edu]
    #v(0.7em)
    #block(width: 88%)[
      #align(center)[#text(11pt, weight: "bold")[Abstract]]
      #v(0.2em)
      #set par(first-line-indent: 0em, justify: true, leading: 0.5em)
      #set align(left)
      #text(9.5pt)[
        Financial analysis draws on four semantically different kinds of evidence — observed market state, reported assertions in news and filings, collective expectations priced by prediction markets, and the user's own exposure — that live in separate systems. We present *Worldview*, a system that keeps these four forms in distinct native representations, linked by canonical entities and time, and enables joint, auditable question answering across them. It continuously converts news, filings, and prediction-market propositions into provenance-linked relational state, and queries that state jointly with structured market data and portfolio holdings through an inspectable, tool-mediated interface with passage-level citations. Construction is kept cost-bounded by a learned relevance gate that retains #sym.approx 94% of realised extraction yield at 75% deep-processing load. On a 97-question benchmark scored by deterministic grounding gates and an LLM judge, 91 of 97 answers pass under three-run majority vote (82 strong); we additionally report a document-only-RAG ablation and are explicit about the evaluation's limits. Worldview is self-hostable from a public repository in a seeded, no-credential demonstration mode.
      ]
    ]
  ]
]

#columns(2, gutter: 0.7cm)[

= Introduction

Assessing what a headline means for a portfolio is a language-technology problem before it is a finance problem. The evidence arrives as text — news, regulatory filings, prediction-market propositions — and becomes useful only after a full NLP lifecycle has run:

#block(inset: (left: 0.6em, y: 2pt))[
#set par(first-line-indent: 0em, leading: 0.5em)
#text(9pt)[
text acquisition #sym.arrow normalisation and deduplication #sym.arrow named-entity recognition #sym.arrow entity linking #sym.arrow relation / claim / event extraction #sym.arrow provenance-linked knowledge updating #sym.arrow multimodal evidence retrieval #sym.arrow grounded response generation
]
]

Each stage is load-bearing: without deduplication, syndicated reprints masquerade as corroboration; without entity resolution, "NVIDIA", "Nvidia Corp", and "NVDA" fragment the evidence for one company; without extraction into persistent relational state, every question re-reads the corpus from scratch; without provenance, no answer can be audited. Existing systems cover fragments of this lifecycle. Commercial terminals integrate structured and unstructured data but are closed and non-inspectable. Open retrieval-augmented generation (RAG) frameworks #c(1) supply retrieval and orchestration components but generally assume a prepared, static corpus. GraphRAG-style systems #c(7) build LLM-derived graphs by batch indexing over static document collections, rather than maintaining a continuously updated graph with per-edge provenance and valid-time; HybridRAG #c(12) fuses graph and vector retrieval for financial text but not over a continuously updated graph coupled to market and user state. Financial language models #c(10, 11) hold knowledge parametrically, without continuously updated, evidence-linked state; financial QA benchmarks #c(8, 9) evaluate models rather than deployed systems; and demonstration systems such as CHATREPORT #c(13) and RAGAS #c(14) analyse static disclosures or evaluate RAG pipelines rather than constructing intelligence. Unlike the surveyed open systems, Worldview integrates the full construction-to-access lifecycle in one inspectable deployment.

*Worldview* is an implemented system that runs this lifecycle continuously and end to end. Its defining contribution is not a new model but a *representation*: it keeps four semantically distinct evidence forms — observations, attributed assertions, probabilistic expectations, and user exposure (§2.2) — in native representations, linked by canonical entities and time, and enables joint, auditable question answering across them. Its intended users are NLP researchers studying streaming information extraction, retrieval, and knowledge updating; developers building domain-specific intelligence systems on open components; and analysts who need auditable cross-source synthesis. Concretely we contribute:

+ *A four-form evidence model* realised as a continuously updated, provenance-preserving knowledge base — observations, assertions, expectations, and exposure kept in native representations under one event-driven architecture and linked for joint query (§2.1–§2.2).
+ *A cost-aware construction pipeline with a learned relevance gate* — canonicalisation, deduplication, zero-shot financial NER, cascade entity resolution, and constrained extraction — whose routing gate is our primary quantitative result, retaining #sym.approx 94% of extraction yield at 75% deep-processing load (§2.3, §4.2).
+ *An evidence-linked, inspectable access layer*: tool-mediated retrieval across all four forms with an explicit evidence contract separating numbered passage citations from typed structured provenance, and fully inspectable tool traces (§2.5).

*Demonstration.* The demonstration lets attendees observe an incoming financial document as it is deduplicated and enriched; inspect the resulting graph relation, its temporal metadata, and the exact source passage that produced it; browse a prediction market's probability history and the entities its proposition mentions; and ask a portfolio-aware question — _"What is my exposure to TSMC?"_ — whose detected intent, selected tools, holdings, graph paths, retrieved passages, structured values, and citations are all exposed in the interface (§3).

= System Architecture

== Topology

#figure(
  block(breakable: false, inset: 5pt, stroke: 0.4pt, radius: 3pt, width: 100%)[
    #set align(center)
    #set par(first-line-indent: 0em, leading: 0.45em)
    #sbox(w: 100%)[*External sources* — market-data providers · news feeds · SEC EDGAR · Polymarket · brokerage sync · hosted LLM provider]
    #dn
    #grid(columns: (1fr, 1fr), gutter: 3pt,
      sbox(w: 100%)[*Structured path*\ market ingestion #sym.arrow time-series,\ quotes, fundamentals, prediction stores],
      sbox(w: 100%)[*Content path (NLP)*\ content ingestion #sym.arrow clean + dedup #sym.arrow\ route #sym.arrow NER #sym.arrow resolve #sym.arrow extract #sym.arrow graph],
    )
    #v(2pt)
    #sbox(w: 100%, fg: luma(240))[*Event backbone* — schema-governed Kafka events · transactional outbox · idempotent consumers]
    #v(2pt)
    #sbox(w: 100%, fg: luma(240))[*Shared intelligence state* (PostgreSQL) — relational + time-series (TimescaleDB) + vectors (pgvector HNSW) + property graph (Apache AGE) · evidence rows · object store for raw/canonical text]
    #v(2pt)
    #grid(columns: (1fr, 1.2fr, 1fr), gutter: 3pt,
      sbox(w: 100%)[portfolio &\ user state],
      sbox(w: 100%)[tool-mediated chat\ (typed retrieval tools)],
      sbox(w: 100%)[alerts &\ notification],
    )
    #dn
    #sbox(w: 72%)[API gateway #sym.arrow.l.r web frontend (inspectable tool traces)]
  ],
  caption: [Architecture. A continuous NLP construction path and structured-data paths feed shared intelligence state, which a tool-mediated access layer queries jointly with user portfolio state.],
) <fig:arch>

Worldview comprises ten backend services and a web frontend across a data layer, an intelligence layer, and two horizontal services (gateway, alerts); the figure shows the decomposition. What matters here is one property: construction and access are decoupled, so enrichment latency never blocks interactive queries and a failing provider never stalls the pipeline. Services communicate through schema-governed events (Avro contracts validated by a registry); every event is written to a *transactional outbox* in the same transaction as the domain change, and consumers are *idempotent* under at-least-once delivery. Storage is consolidated on one PostgreSQL instance whose extensions host the retrieval modalities side by side — relational and time-series tables, HNSW vector indexes #c(4), and an openCypher property graph — so graph traversals join relational evidence tables in one transaction. Raw and canonical text lives in an object store (events carry pointers, not payloads); the platform runs as a single-host containerised deployment.

== Information model: four forms of evidence <sec:info>

The system's central design decision is that financial evidence is not one corpus but four semantically different sources, which must stay in native representations while being linked for joint querying:

- *Observed state* — prices, fundamentals, calendars: measurements with a timestamp and a provider. Stored as time-series and relational tables; queried exactly; never paraphrased into text.
- *Reported assertions* — news and regulatory filings: claims made by a source with a reliability profile. Stored as canonical documents, embedded chunks, and extracted relations/claims/events, each linked to its supporting passage (§2.3).
- *Collective expectations* — prediction-market propositions and their probability histories: not reports of what happened, but *timestamped, tradeable beliefs about uncertain future outcomes*, revised continuously and eventually resolved (§2.4).
- *User-specific exposure* — portfolio holdings and watchlists: private state that determines which of the above matters to this user.

These forms carry different truth conditions — an observation is correct or not; an assertion is attributed and possibly contradicted; an expectation is a probability that resolves later; exposure is authoritative but private — so the system never collapses them into a single index. They are linked instead by three shared keys: *canonical entities* (assertion text and prediction propositions pass through the same NER and entity-resolution cascade), *topics/categories*, and *time* (bar timestamps, document publication times, relation valid-time intervals, snapshot times, market close dates). This linkage enables questions no single modality can answer — joining a user's exposure to the assertions and observations about a holding, or a market's collective expectation to the entities the other forms already key by (worked end to end in §3).

== Continuous knowledge construction (assertions) <sec:construct>

The content path converts each incoming document into persistent relational state.

*Canonicalisation and deduplication.* Raw articles are cleaned and passed through a three-stage cascade of ascending cost: exact byte hash, normalised URL+text hash, and MinHash–LSH #c(16) near-duplicate detection. Cross-source near-duplicates are retained and recorded as *corroboration* links on the surviving canonical document — a syndicated wire story contributes evidence once, not once per outlet.

*Relevance routing.* Before any embedding or LLM call, each document is scored and assigned one of four processing tiers. During the measured evaluation window the *deployed* router was a five-signal weighted heuristic (entity density, source reliability, recency, document type, a cheap yield prior). We additionally trained a learned gate — a calibrated classifier over a title-and-lede embedding and three cheap structured signals — predicting whether deep extraction will yield at least one relation, claim, or event (mechanics and ablation in §4.2). Evaluated offline, it has since been deployed with guards (regulatory filings floored at the medium tier or above; fallback to the heuristic for documents without a headline); routing statistics in §4 reflect the heuristic router live during the window.

*NER and entity resolution.* GLiNER #c(5) performs zero-shot NER over eleven natural-language-defined financial entity classes. Mentions are resolved by a staged cascade — exact alias, ticker symbol, class-aware canonical match, fuzzy similarity, embedding nearest-neighbour — and unresolved mentions are *preserved* as provisional entities rather than dropped, then promoted when later passes resolve them.

*Constrained extraction and graph materialisation.* Admitted documents are chunked and embedded with `bge-large-en-v1.5` #c(17); a hosted LLM then extracts events, claims, and relations against a *closed* predicate vocabulary, with subject and object references constrained to the detected-entity list. Each triple is canonicalised against a predicate registry and stored with every supporting passage linked to the resulting edge; claims and events carry their own evidence rows. Relations carry temporal metadata — six predicate-specific decay classes and valid-time intervals — with background workers that re-weight evidence over time and record contradicting evidence against an edge rather than deleting it. Confidence values are inspection metadata, not calibrated probabilities (§5).

== Collective expectations: prediction markets <sec:predictions>

Prediction markets are a distinct modality whose *text reuses the assertion pipeline*. A market's proposition gets no bespoke NLP path: on first sight and on resolution it is wrapped as a *synthetic document* and routed through the standard rails of §2.3, so the same NER and entity-resolution cascade links it to canonical entities with zero new extraction machinery. What differs is the *series* semantics of the numeric data. The provider is Polymarket, polled over five public endpoints — market snapshots, group events, per-outcome probability histories (hourly/daily/weekly), trades, and daily open interest. A market is keyed by its Polymarket condition identifier, and snapshots deduplicate on (market, minute-rounded fetch time) — a mutable series, not an immutable document; historical snapshots, price history (14-day backfill), and trades live in time-series hypertables, latest state and open interest in relational tables, so *probability trajectories over time, not just current odds, are queryable*.

The synthetic-document route yields one `PREDICTION` temporal event per market plus one exposure row per resolved entity, each carrying an LLM-classified *polarity* — whether a YES resolution would be bullish, bearish, or neutral *for that entity* (e.g., _"Will X miss Q3 earnings?"_ #sym.arrow bearish for X), with a confidence score and a neutral fallback on classifier failure. A background detector watches open markets and, when the affirmative outcome's probability moves by #sym.gt.eq 0.15 within 24 hours on a sufficiently liquid market, emits a signal joined to the linked entities' polarity, feeding watchlist-gated user alerts. At query time, a structured tool searches propositions by keyword and returns per-outcome implied probabilities, resolution date, 24-hour volume, and the market URL; the probabilities and volume are also attached as machine-readable grounding fields that the evaluation harness checks answers against. Chat retrieval over propositions is keyword-based, a boundary we return to in §5.

== Access layer and evidence contract <sec:contract>

A planner LLM answers questions through a tool-use loop #c(20) over a typed tool manifest (Appendix A) spanning the four evidence forms: hybrid document search (dense ANN + BM25 #c(2), merged by Reciprocal Rank Fusion #c(3), with HyDE expansion #c(6) for relationship-type intents), knowledge-graph traversal and relation/claim/event search, structured market and fundamentals queries, calendars and prediction markets, and the authenticated user's portfolio. Tools execute concurrently; every call, its arguments, and its results are exposed in the interface.

The *evidence contract* is explicit, because different evidence forms need different provenance. News, filings, and transcripts become embedded chunks that enter the prompt as a numbered, citable sources block, re-scored by recency- and source-trust weighting and optionally cross-encoder-reranked. Prediction-market results join this numbered block as a deliberate special case: each retrieved market is a citable item whose `[N]` marker resolves to its Polymarket URL, and it *also* carries typed grounding fields (implied probabilities, volume) for numeric checking. Graph edges, claims, events, financial rows, and holdings instead reach the model as *typed blocks* that preserve structure and carry their own provenance — a graph edge arrives with its temporal metadata and back-links to supporting passages; claims and events reference their evidence rows; structured values identify their tool and provider of origin — and are not numbered. Every `[N]` marker resolves to a stored source by construction: a serving-path scrubber deletes any marker whose target is missing, and a numeric-grounding check re-prompts once when a stated figure mismatches its cited value. Statements derived from graph or structured evidence are supported instead by the deterministic grounding gates of the evaluation harness (§4.3), which compare answer numerics — including uncited ones — against captured tool output. We do not claim every statement is cited; we claim every citation resolves, and that citation *faithfulness* is measured separately and is currently moderate (§4.3).

#place(top, float: true, scope: "parent", clearance: 0.8em)[
#figure(
  block(breakable: false, inset: 5pt, stroke: 0.4pt, radius: 3pt, width: 100%)[
    #set align(left)
    #set par(first-line-indent: 0em, leading: 0.45em)
    #grid(columns: (auto, 1fr), gutter: 4pt,
      align(horizon)[#rotate(-90deg, reflow: true)[#text(7.2pt, weight: "bold")[ASSERTIONS]]],
      [
        #lbox(w: 100%)[news / filing #ar clean + 3-stage dedup #ar canonical doc #ar relevance route (tier) #ar GLiNER NER #ar entity resolution #ar constrained LLM extraction]
        #v(1pt)
        #lbox(w: 100%, fg: luma(244))[*artifacts:* chunk embeddings · evidence row {subj, pred, obj, passage, source, confidence} #ar graph edge {decay class, valid-time, passage links} · claim rows · event rows]
      ],
    )
    #v(2pt)
    #grid(columns: (auto, 1fr), gutter: 4pt,
      align(horizon)[#rotate(-90deg, reflow: true)[#text(7.2pt, weight: "bold")[EXPECTATIONS]]],
      [
        #lbox(w: 100%)[Polymarket poll #ar snapshot + probability-history hypertables {outcome prices, volume, liquidity, close, resolution} · proposition text #ar synthetic doc #ar same NER + resolution rails]
        #v(1pt)
        #lbox(w: 100%, fg: luma(244))[*artifacts:* `PREDICTION` temporal event · per-entity exposure {polarity, confidence} · move signal (|#sym.Delta p| #sym.gt.eq 0.15, liquidity-gated) #ar watchlist alerts]
      ],
    )
    #v(2pt)
    #grid(columns: (auto, 1fr), gutter: 4pt,
      align(horizon)[#rotate(-90deg, reflow: true)[#text(7.2pt, weight: "bold")[OBS. / EXP.]]],
      [
        #lbox(w: 100%)[market ingestion #ar OHLCV bars · quotes · fundamentals · calendars (observed state) #h(8pt) | #h(8pt) brokerage sync #ar holdings · watchlists (user exposure)]
      ],
    )
    #v(3pt)
    #align(center)[#text(8pt)[#sym.arrow.b.double #h(4pt) *shared keys: canonical entities · topics · time* #h(4pt) #sym.arrow.b.double]]
    #v(3pt)
    #grid(columns: (auto, 1fr), gutter: 4pt,
      align(horizon)[#rotate(-90deg, reflow: true)[#text(7.2pt, weight: "bold")[ACCESS]]],
      [
        #lbox(w: 100%)[question #ar intent #ar tool loop (concurrent typed tools) #ar *evidence bundle:* `[N]`-cited passages (RRF-fused, trust-weighted) · typed graph edges #sym.arrow.l passages · claims/events #sym.arrow.l evidence rows · structured values (tool + provider) · market probabilities (grounding fields) · holdings #ar streamed answer + inspectable trace]
      ],
    )
  ],
  caption: [Typed dataflow. Each evidence form is constructed on its own path into native representations (top three lanes), linked by canonical entities, topics, and time; the access path (bottom) assembles a mixed evidence bundle in which passages carry numbered citations and all other artifacts carry typed provenance.],
) <fig:dataflow>
]

= Worked Examples

One example runs through the paper. An article reports: _"NVIDIA reports record third-quarter earnings, citing surging demand for its data-centre chips, which are manufactured by TSMC."_

*Document to intelligence.* A content adapter lands the article minutes after publication; cleaning and the deduplication cascade confirm it is new (a syndicated copy would instead attach as corroboration). The router admits it at the deepest tier — reputable source, fresh, entity-dense. GLiNER tags *NVIDIA* and *TSMC*; both resolve at the first cascade stage; the extraction LLM emits an event (`EARNINGS_RELEASE`), a claim (`REVENUE_GROWTH`, positive), and a relation whose stored evidence row has the shape:

#block(width: 100%, inset: (y: 2pt))[
  #set text(size: 8pt)
  #block(fill: luma(246), stroke: 0.4pt, radius: 2.5pt, inset: 5pt, width: 100%)[
    #set par(first-line-indent: 0em, leading: 0.5em)
    #raw("subject:    TSMC
predicate:  supplier_of
object:     NVIDIA Corporation
source:     nlp_extraction · <source document id>
evidence:   \"NVIDIA reports record earnings,
             ... manufactured by TSMC.\"
extraction_confidence: 0.91
decay_class: DURABLE · valid_from: <ingest date>")
  ]
]

The schema is real; the passage and values are illustrative, not a verbatim database row. The graph service canonicalises the predicate and links the passage to the edge; end-to-end, a published article becomes a queryable relation within minutes, dominated by provider polling and LLM extraction.

*Question to grounded answer.* A user holding NVIDIA later asks _"What is my exposure to TSMC?"_ — a question that joins three evidence forms. The planner fans out concurrently: the *portfolio* tool returns the NVDA position (exposure); *graph traversal* finds the `supplier_of` path from the holding to TSMC — the edge constructed above — with its passage back-links (assertions); *hybrid document search* surfaces recent TSMC coverage (assertions); *structured* tools fetch TSMC quotes and fundamentals (observations). The synthesis streams with `[N]` markers on passage-backed statements, while the holding, the graph path, and the market figures appear as typed evidence in the answer's inspection panel — closing the loop from answer back to source text.

*Expectations example (verified).* The prediction modality answers a different kind of question. In a live trace, the query _"Which prediction markets track Nikki Haley?"_ retrieved ten open markets by keyword search over propositions; each was returned with its per-outcome implied probability, resolution date, 24-hour volume, and a citation resolving to the market's Polymarket URL (e.g., the 2028 Republican-nomination market). Because these propositions are entity-linked upstream (§2.4), the same markets also surface as `PREDICTION` events on their linked entities' pages.

= Evaluation

We ask three questions. *RQ1*: does the implemented system support the complete demonstrated workflows? *RQ2*: is selective NLP processing effective and operationally practical? *RQ3*: how reliable are generated answers and their evidence?

*Setup.* Graph-scale figures come from the thesis evaluation snapshot (June 2026) of the single-host deployment: a news-and-filings corpus processed into 16,817 resolved entities and 4,750 canonical, provenance-linked relations. The routing ablation is an offline five-fold stratified cross-validation over 15,006 historical articles (positive rate 0.625). The answer benchmark is a 97-question catalogue spanning twelve strata (Appendix B), executed as three full runs against the live system on 8–9 July 2026 and aggregated by per-question majority vote.

#figure(
  placement: auto,
  {
    set text(size: 8pt)
    table(
      columns: (1.35fr, 1fr),
      inset: (x: 3.5pt, y: 2.4pt),
      align: (left, left),
      stroke: 0.4pt,
      table.header([*Measure*], [*Value*]),
      table.cell(colspan: 2, fill: luma(240))[*Workflow completion (RQ1)*],
      [Construction path (article #sym.arrow graph)], [operational; minutes end-to-end],
      [Retrieval modalities exercised], [document, graph, structured, portfolio (12 tools)],
      table.cell(colspan: 2, fill: luma(240))[*Selective processing (RQ2)*],
      [Tier split (heuristic router)], [deep 32% · medium 57% · light 11%],
      [Learned gate vs. deployed heuristic (5-fold CV)], [ROC-AUC 0.639 #sym.arrow 0.828; Brier 0.249 #sym.arrow 0.151],
      [Learned gate operating point], [75% of docs to deep extraction; #sym.approx 94% of realised yield retained],
      [Hosted-model spend], [within the \$50/month design ceiling],
      table.cell(colspan: 2, fill: luma(240))[*Answer reliability (RQ3), 97 questions #sym.times 3 runs*],
      [Majority-vote verdicts], [82 STRONG · 9 PASS · 0 WEAK · 6 FAIL],
      [Run-to-run variation], [40/97 questions changed verdict in #sym.gt.eq 1 run],
      [Judge–author agreement (39 items)], [$kappa approx 0.80$; 0 false-passes on fabrication (single annotator)],
    )
  },
  caption: [Main results; §4.2–§4.3 give conditions and caveats.],
) <tab:results>

== RQ1: Workflow completion

Both demonstrated paths execute end to end on the deployed system. The construction path converts live feeds into graph state continuously; the access path answered the full benchmark against that state, exercising the document, graph, structured, and portfolio modalities. Cross-component evidence resolution — answer citation to stored chunk, graph edge to source passage, claim to evidence row — is navigable in the interface, and both worked paths of §3 execute on the snapshot corpus with their supporting edges, passages, and portfolio context inspectable. The prediction-market path (ingestion #sym.arrow entity linking #sym.arrow retrieval with resolving citations) is verified by live traces (§3) rather than by a benchmark stratum.

== RQ2: Selective processing

*Routing.* The prediction target is concrete: will deep extraction of this document yield at least one relation, claim, or event? The learned gate is a gradient-boosted classifier over an EmbeddingGemma #c(18) title-and-lede embedding and three cheap structured signals, calibrated by isotonic regression #c(19); labels are retroactive extraction yield, de-biased with a counterfactual sample of light-tier documents. Under five-fold cross-validation it improves ROC-AUC over the deployed static-rule router from 0.639 to 0.828 and calibration (Brier) from 0.249 to 0.151; at the chosen operating threshold it routes 75% of documents to deep extraction while retaining #sym.approx 94% of realised yield — a quarter of LLM extraction work avoided at a #sym.approx 6% yield cost. Because historical negatives include documents whose extraction silently timed out, absolute scores are conservative lower bounds. The live tier distribution under the heuristic router sends roughly a third of documents to deep extraction (Table 1); the learned gate was deployed after this window.

*Cost and latency.* Hosted-model inference for a month of single-node operation stayed within the \$50/month design ceiling (inference only; data-provider subscriptions excluded). Interactive reads are fast enough for live demonstration; chat first-token, by contrast, is dominated by hosted-LLM planning latency and runs to several seconds on the cold path — an operational limitation we mitigate with streaming but do not hide.

== RQ3: Answer reliability

*Benchmark design.* Each answer is judged by a gate-then-band pipeline: seven deterministic invariant gates fire first — scaffolding leaks, truncation, empty-after-tools, tool-failure non-answers, numeric claims contradicting captured tool output, *phantom citations* naming a tool never called, and a grounding floor (full definitions in Appendix B) — and any fired gate fails the answer outright before a four-dimension rubric bands it STRONG/PASS/WEAK/FAIL. A fabricated answer cannot be rescued by fluent prose, the failure mode a naive LLM judge rewards.

*Results.* Under three-run majority vote: *82 STRONG, 9 PASS, 0 WEAK, 6 FAIL* (per-run counts and the six-failure breakdown in Appendix B; the failures are dominated by multi-step derived arithmetic). Verdicts vary across runs — 40 of 97 questions changed verdict in at least one run — because the planner runs unseeded at non-zero temperature; we therefore report majority votes with per-run counts rather than a single-run pass rate, keeping the planner unseeded so runs reflect production behaviour.

*Citations.* The three-property split is defined in §2.5. Marker resolution holds by construction. Semantic faithfulness, scored by an online judge on a 0–3 rubric over a small production sample, is only *moderate* — a preliminary result we report rather than hide. Numeric correctness against tool output, including uncited structured and prediction-market claims, is what the deterministic gates enforce. The judge agrees with 39 author-labelled answers at Cohen's $kappa approx 0.80$ #c(15) (raw agreement 0.90) and passed none of the gold set's nine fabrication cases; this is *author–judge* agreement by a single annotator who designed the rubric and iteratively repaired the judge, so it supports the methodology rather than constituting broad human validation (Appendix B).

= Limitations

The deployment is single-host; horizontal scaling is designed for but unexercised. A hosted inference provider sits on the critical path for extraction and chat; the local fallback degrades latency materially, and cold-path first-token latency is a real interaction cost. There has been no independent user study. The knowledge graph carries residual NER and entity-resolution noise, and relation extraction is conservative, so graph coverage is partial. Graph-confidence values are inspection metadata, *not calibrated*: at the June 2026 snapshot essentially all 4,750 relations sat in the $[0.9, 1.0]$ bin (mean 0.996), because the upstream extractor emits near-constant high scores; a redesigned aggregation posterior postdates the evaluation (Appendix B), and calibration remains future work. Citation faithfulness is preliminary and only moderate. Answer-benchmark verdicts vary across runs, and judge validation rests on a single author-annotator with evaluator-overfitting risk. Prediction-market retrieval in chat is keyword-based rather than entity-linked (an entity-to-markets API exists but is not yet wired into the chat tool), and the prediction path is verified by live traces rather than a benchmark stratum. Source coverage is representative — news, EDGAR filings, one prediction-market provider, several market-data providers — not exhaustive, and live ingestion requires third-party data subscriptions.

= Conclusion and Availability

Worldview implements the full lifecycle of financial intelligence in one inspectable deployment: text becomes provenance-linked relational state under an explicit cost gate, prediction-market expectations are entity-linked and tracked over time, and the result is queried jointly with market data and portfolio holdings — inspectable from answer to citation to graph edge to source passage. Its strongest validated results are the answer benchmark (91 of 97 questions pass-or-better across three runs) and the routing ablation (#sym.approx 94% of yield retained at 75% deep-processing load); its main open limitations are that graph-confidence calibration and citation faithfulness remain preliminary.

The implementation is public at #link("https://github.com/arnaurodondev/WorldView")[github.com/arnaurodondev/WorldView], licensed under the Business Source License 1.1 (source-available; free for non-production use; converts to Apache-2.0 on 2030-05-17). A hosted instance runs at #link("https://app.worldview-labs.com")[app.worldview-labs.com] #todo[(TODO-VERIFY: reviewer access mode / demo credentials)], and the repository provides a documented Docker-based single-node installation with a *seeded, no-credential demonstration mode*: a built-in dev login exposes entity browsing, graph and evidence inspection, and prediction-market views on sample data without any paid account; live ingestion and LLM extraction/chat additionally require market-data and hosted-LLM keys (a local model fallback covers chat at degraded latency). #todo[TODO-BLOCKING: 2.5-minute screencast link.]

] // end body columns

// Ethics statement — unlimited optional space per the call; kept outside the
// six-page body.
#pagebreak()
#set par(first-line-indent: 0em)
#heading(numbering: none)[Ethics and GenAI Disclosure]
LLMs are components of the system under study (extraction, polarity classification, entity descriptions, tool-mediated retrieval, synthesis, and LLM-as-judge evaluation). AI coding assistants aided implementation and drafting; all reported metrics trace to committed evaluation artifacts and were verified by the author. The system ingests only public or licensed data and stores no personal data beyond account email and user-entered portfolio state. Worldview is a research system, not investment advice; prediction-market probabilities are displayed as market prices, not endorsements of trading; grounding machinery reduces but does not eliminate fabrication risk, and answers must not be relied on for financial decisions.

// ---------------------------------------------------------------------------
#v(1.2em)
#set heading(numbering: none)
#set par(first-line-indent: 0em)
= References
#set text(size: 9pt)
#set enum(numbering: "[1]")
#columns(2, gutter: 0.7cm)[
#enum(
  [Lewis, P., Perez, E., Piktus, A., et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS 2020.],
  [Robertson, S., Zaragoza, H. The Probabilistic Relevance Framework: BM25 and Beyond. Foundations and Trends in Information Retrieval, 3(4), 2009.],
  [Cormack, G. V., Clarke, C. L. A., Büttcher, S. Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods. SIGIR 2009.],
  [Malkov, Y. A., Yashunin, D. A. Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs. IEEE TPAMI, 42(4), 2020.],
  [Zaratiana, U., Tomeh, N., Holat, P., Charnois, T. GLiNER: Generalist Model for Named Entity Recognition using Bidirectional Transformer. NAACL 2024.],
  [Gao, L., Ma, X., Lin, J., Callan, J. Precise Zero-Shot Dense Retrieval without Relevance Labels. ACL 2023.],
  [Edge, D., Trinh, H., Cheng, N., et al. From Local to Global: A Graph RAG Approach to Query-Focused Summarization. arXiv:2404.16130, 2024.],
  [Chen, Z., Chen, W., Smiley, C., et al. FinQA: A Dataset of Numerical Reasoning over Financial Data. EMNLP 2021.],
  [Islam, P., Kannappan, A., Kiela, D., et al. FinanceBench: A New Benchmark for Financial Question Answering. arXiv:2311.11944, 2023.],
  [Araci, D. FinBERT: Financial Sentiment Analysis with Pre-trained Language Models. arXiv:1908.10063, 2019.],
  [Wu, S., Irsoy, O., Lu, S., et al. BloombergGPT: A Large Language Model for Finance. arXiv:2303.17564, 2023.],
  [Sarmah, B., Mehta, D., Hall, B., et al. HybridRAG: Integrating Knowledge Graphs and Vector Retrieval Augmented Generation for Efficient Information Extraction. ICAIF 2024.],
  [Ni, J., Bingler, J., Colesanti-Senni, C., et al. CHATREPORT: Democratizing Sustainability Disclosure Analysis through LLM-based Tools. EMNLP 2023 (System Demonstrations).],
  [Es, S., James, J., Espinosa-Anke, L., Schockaert, S. RAGAS: Automated Evaluation of Retrieval Augmented Generation. EACL 2024 (System Demonstrations).],
  [Cohen, J. A Coefficient of Agreement for Nominal Scales. Educational and Psychological Measurement, 20(1), 1960.],
  [Broder, A. Z. On the Resemblance and Containment of Documents. Proc. Compression and Complexity of Sequences, 1997.],
  [Xiao, S., Liu, Z., Zhang, P., Muennighoff, N. C-Pack: Packaged Resources to Advance General Chinese Embedding. SIGIR 2024.],
  [Vera, H., Schechter Vera, S., et al. EmbeddingGemma: Powerful and Lightweight Text Representations. arXiv:2509.20354, 2025.],
  [Zadrozny, B., Elkan, C. Transforming Classifier Scores into Accurate Multiclass Probability Estimates. KDD 2002.],
  [Schick, T., Dwivedi-Yu, J., Dessì, R., et al. Toolformer: Language Models Can Teach Themselves to Use Tools. NeurIPS 2023.],
)
]
// Body numbering map (verified): 1 RAG · 2 BM25 · 3 RRF · 4 HNSW · 5 GLiNER ·
// 6 HyDE · 7 GraphRAG · 8 FinQA · 9 FinanceBench · 10 FinBERT ·
// 11 BloombergGPT · 12 HybridRAG · 13 CHATREPORT · 14 RAGAS · 15 Cohen ·
// 16 Broder · 17 BGE · 18 EmbeddingGemma · 19 isotonic · 20 Toolformer.

// ---------------------------------------------------------------------------
#pagebreak()
#set text(size: 10pt)
#set heading(numbering: "A.1", outlined: false)
#counter(heading).update(0)

= Tool and Modality Inventory

The access layer exposes 29 typed tools (capability manifest v8; manifest–registry parity is enforced by an architecture test). *Provenance* states what evidence accompanies each result; *Citable* marks tools whose outputs can carry numbered `[N]` citations (document chunks) versus typed structured provenance.

#set text(size: 7.6pt)
#table(
  columns: (auto, 1fr, auto, auto),
  inset: (x: 3.5pt, y: 2.3pt),
  align: (left, left, left, center),
  stroke: 0.4pt,
  table.header([*Tool*], [*Input #sym.arrow output*], [*Provenance*], [*Citable*]),
  table.cell(colspan: 4, fill: luma(240))[*Structured market data (7) — market-data service*],
  [`get_price_history`], [ticker, window #sym.arrow OHLCV bars], [tool + provider], [—],
  [`get_fundamentals_history`], [ticker, periods #sym.arrow metric series], [tool + provider], [—],
  [`get_fundamentals_history_batch`], [tickers #sym.arrow metric series per ticker], [tool + provider], [—],
  [`query_fundamentals`], [ticker, metrics #sym.arrow values], [tool + provider], [—],
  [`compare_entities`], [2–4 entities #sym.arrow side-by-side table], [tool + provider], [—],
  [`screen_universe`], [filter predicates #sym.arrow instruments], [tool + provider], [—],
  [`get_market_movers`], [period #sym.arrow gainers/losers], [tool + provider], [—],
  table.cell(colspan: 4, fill: luma(240))[*Calendars (2) — market-data service*],
  [`get_economic_calendar`], [window #sym.arrow macro events (actual/forecast)], [tool + provider], [—],
  [`get_earnings_calendar`], [window #sym.arrow earnings dates, EPS], [tool + provider], [—],
  table.cell(colspan: 4, fill: luma(240))[*Document search (3) — NLP service; dense + lexical*],
  [`search_documents`], [query #sym.arrow RRF-fused chunks], [chunk #sym.arrow source doc], [yes],
  [`get_entity_news`], [entity, window #sym.arrow news chunks], [chunk #sym.arrow source doc], [yes],
  [`get_filings`], [query, form #sym.arrow filing chunks + links], [chunk #sym.arrow SEC source], [yes],
  table.cell(colspan: 4, fill: luma(240))[*Knowledge graph (6) — graph service*],
  [`get_entity_graph`], [entity #sym.arrow 1–2-hop neighbourhood], [edge #sym.arrow evidence passages], [yes],
  [`traverse_graph`], [pattern #sym.arrow multi-hop paths], [edge #sym.arrow evidence passages], [yes],
  [`search_entity_relations`], [entity #sym.arrow ranked triples], [edge #sym.arrow evidence passages], [yes],
  [`search_claims`], [entity/topic #sym.arrow extracted claims], [claim evidence row], [yes],
  [`search_events`], [filters #sym.arrow corporate events], [event evidence row], [yes],
  [`get_contradictions`], [entity #sym.arrow conflicting claim pairs], [both evidence rows], [yes],
  table.cell(colspan: 4, fill: luma(240))[*Entity intelligence (5) — graph service via gateway*],
  [`get_entity_narrative`], [entity #sym.arrow generated narrative], [narrative sources], [—],
  [`get_entity_paths`], [entity #sym.arrow top pre-computed paths], [edge #sym.arrow evidence passages], [yes],
  [`get_path_between`], [two entities #sym.arrow bounded live path], [edge #sym.arrow evidence passages], [yes],
  [`get_entity_health`], [entity #sym.arrow coverage/confidence summary], [aggregate metadata], [—],
  [`get_entity_intelligence`], [entity #sym.arrow bundled view], [mixed, as above], [yes],
  table.cell(colspan: 4, fill: luma(240))[*Portfolio and personal (2) — portfolio / chat services*],
  [`get_portfolio_context`], [auth user #sym.arrow holdings, watchlist], [typed tool output], [—],
  [`get_morning_brief`], [auth user #sym.arrow archived brief], [typed tool output], [—],
  table.cell(colspan: 4, fill: luma(240))[*Prediction markets (1) — market-data service; keyword search over propositions*],
  [`get_prediction_markets`], [topic/keyword #sym.arrow markets: per-outcome implied odds, resolution date, 24h volume, URL], [market URL + grounding fields (probabilities, volume, market id)], [yes],
  table.cell(colspan: 4, fill: luma(240))[*Curated reference (1) — static dataset*],
  [`get_market_sizing`], [segment #sym.arrow dated TAM estimates], [dated static source], [—],
  table.cell(colspan: 4, fill: luma(240))[*Alerts (2) — alert service; `create_alert` is the only write tool (confirmation-gated)*],
  [`get_alerts`], [auth user #sym.arrow active alerts], [typed tool output], [—],
  [`create_alert`], [rule #sym.arrow created alert], [typed tool output], [—],
)
#set text(size: 10pt)

= Evaluation Protocol and Additional Analysis

*Benchmark strata (97 questions).* Tool coverage 21; hypothetical scenario reasoning 16; robustness lookups 11; multi-tool chains 8; robustness iterations 7; comparisons 6; adversarial safety 6; date-anchored 6; aggregation/graph 5; multi-hop ripple 5; deep-dive 3; portfolio 3.

*Deterministic invariant gates (fired before any rubric score; any hit = FAIL).* (1) control-token leak — tool-call scaffolding in the user-facing answer; (2) truncation — answer terminates mid-structure; (3) empty-after-tools — no substantive answer after tools returned data; (4) tool-failure non-answer — infrastructure apology on an answerable question; (5) grounding-contradicted — a numeric claim contradicts a value a tool returned; (6) phantom-citation — a citation names a tool absent from the call trace; (7) grounding-floor — the judge's grounding dimension falls below the floor. A substantiation cross-check additionally verifies that asserted numerics (including prediction-market probabilities via the tool's grounding fields) match values the sampled tools actually returned.

*Verdict model and judge.* Gate-then-band (verdict model v1.1): if no gate fires, four rubric dimensions — tool routing, grounding, framing, coherence, 0–25 each — scored by the judge LLM (`DeepSeek-V4-Flash`, fixed rubric prompt, temperature 0) band the answer into STRONG / PASS / WEAK / FAIL.

*Runs and aggregation.* Three full runs against the live deployment (2026-07-08 21:18 UTC; 2026-07-09 01:35; 2026-07-09 06:49), identical 97-question catalogue, planner unseeded. Per-run verdicts (STRONG/PASS/WEAK/FAIL): 76/8/0/13, 75/8/2/12, 78/6/5/8. Aggregation: per-question majority vote (median band when all three differ), giving 82/9/0/6.

*Failure breakdown (majority FAIL, 6).* Three hypothetical scenario projections requiring multi-step derived arithmetic (AAPL ASP#sym.times units, AMD data-centre share, MSFT capex/FCF); one portfolio chain (worst-fundamentals holding); one Spanish-language robustness case (latency breach); one YoY revenue lookup.

*Success trace (representative).* A screener question chains `screen_universe` #sym.arrow batch fundamentals; every reported figure matches captured tool output; a zero-growth constituent is correctly excluded; verdict STRONG with no gate fired.

*Failure trace (representative).* A comparison answer cited a fundamentals figure to a tool absent from the call trace — caught by the phantom-citation gate; the pre-gate rubric judge had scored the same answer highly, which is why gates precede the rubric.

*Judge calibration.* Gold set: 39 answers from real benchmark runs, hand-labelled by the author (strata: fabrication 9, leaked scaffolding 5, infrastructure non-answer 4, genuinely good 13, appropriate refusal 8). Confusion matrix (human vs. machine): PASS/PASS 17, PASS/FAIL 1, FAIL/PASS 3, FAIL/FAIL 18; raw agreement 0.90, $kappa approx 0.80$, with zero false-passes on fabrication. The rubric was designed by the same annotator, and the judge was repaired iteratively — each labelling round converted a discovered failure mode (e.g., a fabricated margin figure whose citation named a real but uncalled tool) into a new deterministic gate before re-measuring $kappa$ — hence the stated evaluator-overfitting risk.

*Citation-faithfulness rubric.* 0 = irrelevant; 1 = tangential; 2 = supports the claim directly or as a faithful synthesis; 3 = verbatim/near-verbatim. Recent cited answers are sampled online daily; the current sample is small and the mean is only moderate, so we report faithfulness as preliminary rather than as a headline figure.

*Prediction-market path status.* Ingestion (five Polymarket endpoint streams), snapshot/history/trade/open-interest hypertables, synthetic-document entity linking with per-entity polarity, move-signal detection, watchlist alerts, and the retrieval tool are implemented and code-complete; the end-to-end path is verified by live QA traces (June–July 2026) rather than by a dedicated benchmark stratum. Chat retrieval is keyword-based (AND-matched terms over proposition text); an entity-to-markets API exists but is not yet wired into the chat tool.

*Confidence-model note.* The June 2026 snapshot aggregate (all 4,750 relations in $[0.9,1.0]$, mean 0.996) reflects extractor score saturation under the then-deployed linear aggregation. A Beta-posterior evidence aggregation with per-cluster source-trust and decay weighting was implemented after this snapshot and produces graded distributions on the later live corpus; it is not part of the reported evaluation, and calibration against adjudicated labels is future work.

*Environment and reproduction.* Single-host containerised deployment (all services, PostgreSQL with TimescaleDB/pgvector/AGE, Kafka, object store) on commodity hardware; seeded corpus per §4. Routing ablation: committed training script, stratified 5-fold CV, fixed seed, isotonic calibration, out-of-fold metrics, 15,006 articles. Answer benchmark: committed runner and judge scripts, producing per-question JSON artifacts and a trend store.

// ---------------------------------------------------------------------------
#pagebreak()
#set heading(numbering: "A.1", outlined: false)
= Interface Screenshots

Three representative views from the deployed system (§3), captured on the seeded local instance.

#figure(
  grid(
    columns: 1,
    gutter: 6pt,
    image("figs/shot-enrichment.png", width: 100%),
  ),
  caption: [*Entity intelligence view.* NVIDIA knowledge-graph (15 nodes, 15 edges, depth 1) with relation-type filter bar, dossier (description, AI brief, top relations), path-insight panel, and live news feed. Right panel: PATH INSIGHTS traces multi-hop supply-chain routes (NVIDIA → Taiwan Semiconductor → …) scored by a graph signal.],
)

#figure(
  grid(
    columns: 1,
    gutter: 6pt,
    image("figs/shot-graph-evidence.png", width: 100%),
  ),
  caption: [*Graph-edge inspector.* Clicking an edge (SK Hynix IncSPIL → SUPPLIER OF → NVIDIA Corporation) opens the inspector showing the typed relation, temporal validity (JUN 3, 2026 → ONGOING), confidence (87/100), and the 10 supporting source passages that produced the edge — closing the loop from graph state to originating text.],
)

#figure(
  grid(
    columns: 1,
    gutter: 6pt,
    image("figs/shot-chat-trace.png", width: 100%),
  ),
  caption: [*Chat answer with inspectable evidence.* Query: "Trace how recent TSMC news could ripple through the supply chain to affect Apple and NVIDIA." The tool panel shows `get_entity_news` (×3, 301 ms) and `traverse_graph` (×2, 789 ms); citations [1][2] resolve to the news passages that grounded the assertions; RELATED TICKERS and CONVERSATION SOURCES expose the typed evidence in the context panel.],
)

// ---------------------------------------------------------------------------
// UNRESOLVED TODOs
// ---------------------------------------------------------------------------
// BLOCKING:
//  1. 2.5-minute screencast — not recorded. Mandatory. (visible TODO in §7)
//  2. Hosted instance app.worldview-labs.com is LIVE (2026-07-10 launch) but
//     reviewer access mode unresolved: login is Zitadel OIDC; need either a
//     demo account or a read-only mode; browser login itself listed as
//     unverified in launch notes. (visible TODO-VERIFY in §7)
//     NOTE: prediction-activation branch (6 topics + 4 migrations) is NOT yet
//     deployed to the hosted instance — demo of §2.4 currently requires the
//     local seeded install or a prod deploy of feat/prediction-data-activation.
// NON-BLOCKING:
//  4. TODO-VERIFY: EODHD subscription tier during measurement window (paper
//     wording "excludes data subscriptions" is safe either way).
//  5. Port to official EMNLP 2026 LaTeX (ACL) template for submission.
