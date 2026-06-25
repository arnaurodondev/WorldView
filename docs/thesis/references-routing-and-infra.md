# References: Per-Item Routing SOTA + Infrastructure Bibliography

> Verified, cited reference set for the Worldview master's thesis (news ingestion → NLP
> routing → KG extraction → RAG chat). Every entry below was checked against a primary
> source (arXiv abstract page, publisher page, RFC, or official project docs) during
> research on 2026-06-12. Items that could not be fully verified are tagged **[UNVERIFIED]**.
>
> **Citation format:** `Authors. "Title." Venue, Year. URL/DOI.` Each entry adds a
> one-line *Core idea* and, for Part A, a *Mapping to our problem* note explaining the
> link to our embedding-based news router with LLM escalation.

---

## Part A — State of the Art for Per-Item Routing / Triage in LLM Pipelines

The thesis redesigns the news router so that, **per article**, it decides whether to run
expensive LLM extraction (knowledge-graph population) or cheap processing, using the
article's **semantic embedding** rather than hand-crafted features, with an **LLM
escalation only on ambiguous items**. The literature below is the SOTA this design builds on.

### A.1 LLM Cascades (cheap-then-escalate)

**Chen, L., Zaharia, M., & Zou, J. "FrugalGPT: How to Use Large Language Models While
Reducing Cost and Improving Performance." arXiv:2305.05176, 2023.**
<https://arxiv.org/abs/2305.05176>

- *Core idea:* Three cost-reduction strategies for LLM APIs — prompt adaptation, LLM
  approximation, and **LLM cascade**. FrugalGPT instantiates the cascade: query a cheap
  model first, and a learned **scorer** decides whether the answer is good enough or the
  query must escalate to a more expensive model. Matches GPT-4 quality at up to 98% cost
  reduction on their benchmarks.
- *Mapping to our problem:* This is the **direct ancestor of our triage gate**. Our cheap
  path (no LLM extraction) is the "cheap model"; full KG extraction is the "expensive
  model." FrugalGPT's learned scorer is the analog of our calibrated confidence on the
  embedding classifier that decides escalation. We adapt the cascade from *answer-quality*
  to *extraction-yield*.
- *How to cite in the thesis:* Cite as the foundational cascade/escalation pattern when
  justifying the cheap-then-escalate router topology (Methods, router design section).

### A.2 Learned Routers

**Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous, M. W., &
Stoica, I. "RouteLLM: Learning to Route LLMs with Preference Data." arXiv:2406.18665, 2024
(LMSYS).** <https://arxiv.org/abs/2406.18665> · Blog: <https://www.lmsys.org/blog/2024-07-01-routellm/>

- *Core idea:* Train a **router** that decides, per query, whether to send it to a weak
  (cheap) or strong (expensive) model. Four router architectures are studied:
  (1) **similarity-weighted (SW) ranking**, (2) **matrix factorization**, (3) a
  **BERT classifier**, and (4) a **causal-LLM classifier**. Routers are trained on
  Chatbot Arena **preference data** (plus data augmentation via golden labels / LLM
  judges); >2× cost reduction with no quality loss.
- *Mapping to our problem:* RouteLLM is the **closest published analog** to our learned
  router. Their BERT/embedding classifier variant is exactly our design (embedding →
  cheap binary decision). Crucially, **our retroactive extraction-yield label** (did full
  extraction actually produce useful KG triples for this article?) is the analog of
  RouteLLM's preference data — a cheap, automatically-derived outcome signal used to
  supervise the router instead of hand-crafted features.
- *How to cite in the thesis:* Primary citation for the "learned router supervised on
  outcome data" framing; contrast their query-routing-between-models with our
  per-document run/skip-extraction decision.

### A.3 Semantic / Embedding-Based Routing

**Aurelio Labs. "Semantic Router." Open-source library (MIT).**
<https://github.com/aurelio-labs/semantic-router> · <https://www.aurelio.ai/semantic-router>

- *Core idea:* Make routing decisions by **embedding the input and comparing it (cosine
  similarity) to route exemplar utterances**, with a tunable similarity threshold — no LLM
  call needed (≈100 ms vs seconds). Below-threshold inputs fall through (reject option).
- *Mapping to our problem:* Validates the **embedding-similarity-as-router** premise and
  the **threshold/fallthrough** mechanism we use: high-similarity-to-extractable articles
  → cheap accept/route; ambiguous (mid-similarity) items are the ones we escalate to the
  LLM. We replace fixed exemplars with a trained classifier head, but the routing-in-
  embedding-space principle is the same.
- *How to cite in the thesis:* Cite as the engineering precedent for embedding-space
  routing and similarity-threshold gating (related-work / design-rationale).

### A.4 Learning to Defer & Selective Prediction (the reject option)

**Mozannar, H., & Sontag, D. "Consistent Estimators for Learning to Defer to an Expert."
ICML 2020 (PMLR v119). arXiv:2006.01862.** <https://arxiv.org/abs/2006.01862>

- *Core idea:* Jointly learn a **classifier and a rejector** that can either predict or
  **defer** to a downstream expert, via a consistent surrogate loss (a reduction to
  cost-sensitive learning generalizing cross-entropy).
- *Mapping to our problem:* Formal grounding for our **defer-to-LLM** decision. The cheap
  embedding classifier is the "classifier"; the expensive LLM is the "expert"; the
  escalation rule is the learned "rejector." Their cost-sensitive framing lets us trade
  off LLM cost against missed-extraction cost in a principled loss.
- *How to cite in the thesis:* Theoretical justification for the deferral/escalation gate
  (Methods); cite alongside FrugalGPT to bridge theory (defer) and practice (cascade).

**Geifman, Y., & El-Yaniv, R. "SelectiveNet: A Deep Neural Network with an Integrated
Reject Option." ICML 2019 (PMLR v97). arXiv:1901.09192.** <https://arxiv.org/abs/1901.09192>

- *Core idea:* Train a network end-to-end to **optimize prediction and rejection jointly**
  at a target coverage, improving the risk–coverage trade-off over post-hoc
  confidence-thresholding.
- *Mapping to our problem:* Underpins the **risk–coverage view** of our router: at a given
  escalation budget (coverage = fraction handled cheaply), minimize extraction-error risk.
  Useful for setting/reporting the operating point of the triage gate.
- *How to cite in the thesis:* Cite for the selective-classification / risk–coverage
  evaluation of the router; pairs with the (earlier) selective-classification baseline:
  Geifman & El-Yaniv, "Selective Classification for Deep Neural Networks," NeurIPS 2017,
  arXiv:1705.08500 (<https://arxiv.org/abs/1705.08500>) — included as supporting reference.

### A.5 Embedding-Based Text Classification + Calibration

**Tunstall, L., Reimers, N., Jo, U. E. S., Bates, L., Korat, D., Wasserblat, M., &
Pereg, O. "Efficient Few-Shot Learning Without Prompts" (SetFit). arXiv:2209.11055, 2022.**
<https://arxiv.org/abs/2209.11055>

- *Core idea:* **SetFit** fine-tunes a Sentence-Transformer contrastively on a few labeled
  pairs, then trains a lightweight classification head on the embeddings — high accuracy
  with no prompts and far fewer parameters / much faster than PET/PEFT.
- *Mapping to our problem:* Direct method blueprint for our **cheap embedding classifier**:
  embed the article, train a small head on a modest set of retroactively-labeled examples.
  Justifies that a small, prompt-free classifier on embeddings is sufficient for the
  cheap routing decision.
- *How to cite in the thesis:* Primary method citation for the embedding-classifier head
  of the router (Methods, router model).

**Platt, J. C. "Probabilistic Outputs for Support Vector Machines and Comparisons to
Regularized Likelihood Methods." Advances in Large Margin Classifiers, MIT Press, 1999,
pp. 61–74.** <https://www.csie.ntu.edu.tw/~cjlin/papers/plattprob.pdf>

- *Core idea:* **Platt scaling** — fit a sigmoid (logistic) on a held-out set to map raw
  classifier scores to calibrated posterior probabilities.
- *Mapping to our problem:* We need a **calibrated** score to set the escalation threshold;
  Platt scaling turns the classifier's raw output into a probability so the
  "ambiguous-zone" thresholds are meaningful and tunable to a cost budget.
- *How to cite in the thesis:* Cite when describing threshold calibration of the router.

**Zadrozny, B., & Elkan, C. "Transforming Classifier Scores into Accurate Multiclass
Probability Estimates." KDD 2002.** DOI:10.1145/775047.775151 ·
<https://dl.acm.org/doi/10.1145/775047.775151>

- *Core idea:* **Isotonic regression** calibration — a non-parametric, monotonic mapping
  (pair-adjacent-violators) from scores to probabilities; more flexible than Platt's
  sigmoid when the distortion is non-sigmoidal.
- *Mapping to our problem:* Alternative/robust calibrator for the router threshold when
  the score→probability relationship is not sigmoidal; cite as the second calibration
  option alongside Platt.
- *How to cite in the thesis:* Cite jointly with Platt as the calibration toolkit for
  decision thresholds. **[Note: verify exact ACL/KDD page numbers before final.]**

### A.6 Embedding Models Relevant to the Router

**Xiao, S., Liu, Z., Zhang, P., & Muennighoff, N. "C-Pack: Packed Resources For General
Chinese Embeddings" (BGE / FlagEmbedding). arXiv:2309.07597, 2023; SIGIR 2024,
DOI:10.1145/3626772.3657878.** <https://arxiv.org/abs/2309.07597>

- *Core idea:* Releases the **BGE** embedding model family plus the C-MTEB benchmark,
  C-MTP training data, and the FlagEmbedding training recipe; SOTA general-purpose text
  embeddings at release.
- *Mapping to our problem:* **BGE (bge-large-en-v1.5) is the production embedding model**
  in our pipeline; this is its canonical citation. The article embeddings the router
  classifies are BGE vectors.
- *How to cite in the thesis:* Cite wherever the embedding backbone is named (System
  Architecture, embedding service; router input features).

**Schechter Vera, H., et al. (Google DeepMind). "EmbeddingGemma: Powerful and Lightweight
Text Representations." arXiv:2509.20354, 2025.** <https://arxiv.org/abs/2509.20354> ·
<https://huggingface.co/google/embeddinggemma-300m>

- *Core idea:* A **308M-parameter** Gemma-3-based embedding model (bidirectional
  attention), 768-dim output **truncatable via MRL to 512/256/128**, SOTA on MTEB for
  models <500M, 100+ languages, on-device-friendly.
- *Mapping to our problem:* Candidate **lightweight embedding backbone** for the router and
  for on-device/cheap embedding; the MRL truncation lets us trade router latency vs
  accuracy. Cite when discussing embedding-model choice and the cheap-path budget.
- *How to cite in the thesis:* Cite in the embedding-model comparison / future-work on a
  smaller router backbone. **[Author list: verify the full byline on the arXiv PDF before
  final — first author confirmed, full list abbreviated here.]**

**Kusupati, A., Bhatt, G., Rege, A., Wallingford, M., Sinha, A., Ramanujan, V.,
Howard-Snyder, W., Chen, K., Kakade, S., Jain, P., & Farhadi, A. "Matryoshka
Representation Learning." NeurIPS 2022. arXiv:2205.13147.**
<https://arxiv.org/abs/2205.13147>

- *Core idea:* Train a single embedding so that **prefixes of the vector** are themselves
  usable representations (coarse-to-fine), enabling adaptive truncation (e.g. 768→512→256)
  with no retraining and no inference cost.
- *Mapping to our problem:* The mechanism behind EmbeddingGemma's truncatable dims; lets
  the router use a **short embedding for the cheap pass and a longer one only when needed**,
  directly serving the cost/latency budget of per-item routing.
- *How to cite in the thesis:* Cite when justifying embedding-dimension truncation for the
  cheap router path.

**Muennighoff, N., Tazi, N., Magne, L., & Reimers, N. "MTEB: Massive Text Embedding
Benchmark." EACL 2023. arXiv:2210.07316, 2022.** <https://arxiv.org/abs/2210.07316>

- *Core idea:* A benchmark of **8 tasks / 58 datasets / 112 languages** for text
  embeddings; shows no single embedding dominates all tasks. Public leaderboard.
- *Mapping to our problem:* The **evaluation standard** we appeal to when justifying the
  choice of BGE/EmbeddingGemma as the router's embedding backbone.
- *How to cite in the thesis:* Cite when reporting/justifying embedding-model selection.

---

## Part B — Infrastructure & Algorithm Bibliography (canonical references for what the system *uses*)

Grouped by topic. Each entry: full citation + one-line note on where in the thesis it applies.

### B.1 Streaming / Kafka

**Kreps, J., Narkhede, N., & Rao, J. "Kafka: a Distributed Messaging System for Log
Processing." NetDB 2011 (6th Int'l Workshop on Networking Meets Databases, co-located with
SIGMOD), Athens, pp. 1–7.**
<https://www.microsoft.com/en-us/research/wp-content/uploads/2017/09/Kafka.pdf>

- *Applies to:* The Kafka backbone and **log-based event architecture** — cite when
  introducing the streaming/event spine of the platform.

**Narkhede, N., Shapira, G., & Palino, T. "Kafka: The Definitive Guide: Real-Time Data and
Stream Processing at Scale." O'Reilly Media, 1st ed. 2017 (2nd ed. 2022: Shapira, Palino,
Sivaram & Petty). ISBN 978-1-4919-3616-0.**
<https://www.oreilly.com/library/view/kafka-the-definitive/9781491936153/>

- *Applies to:* Practical Kafka design (partitions, consumer groups, delivery semantics) —
  cite for operational/streaming-design decisions.

### B.2 Data Systems (architecture)

**Kleppmann, M. "Designing Data-Intensive Applications: The Big Ideas Behind Reliable,
Scalable, and Maintainable Systems." O'Reilly Media, 2017. ISBN 978-1-4493-7332-0.**
<https://dataintensive.net/>

- *Applies to:* The **canonical reference for the whole data architecture** — reliability,
  partitioning, replication, stream processing, the dual-write/derived-data discussion.
  Cite broadly in System Architecture.

### B.3 Transactional Outbox / CDC (the dual-write problem)

**Richardson, C. "Microservices Patterns: With Examples in Java." Manning, 2018.
ISBN 978-1-6172-9454-9.** <https://www.manning.com/books/microservices-patterns> ·
Pattern page: <https://microservices.io/patterns/data/transactional-outbox.html>

- *Applies to:* The **transactional outbox pattern** we use to avoid dual-write
  inconsistency (DB + Kafka in one transaction) — cite in the outbox/eventing section.

**Debezium (Red Hat). "Debezium — Change Data Capture." Official documentation.**
<https://debezium.io/documentation/>

- *Applies to:* Change-data-capture / log-based outbox relay — cite if/where CDC is used
  to publish committed changes to Kafka. (Verify whether the deployed system uses Debezium
  or a polling-publisher outbox before citing as *used*.)

### B.4 Observability (Prometheus / Grafana / SRE)

**Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (eds.). "Site Reliability Engineering:
How Google Runs Production Systems." O'Reilly Media, 2016. ISBN 978-1-4919-2912-4.**
<https://sre.google/sre-book/table-of-contents/>

- *Applies to:* SLO/error-budget and monitoring philosophy — cite in the
  observability/operations section.

**Majors, C., Fong-Jones, L., & Miranda, G. "Observability Engineering: Achieving
Production Excellence." O'Reilly Media, 2022. ISBN 978-1-4920-7644-5.**
<https://www.oreilly.com/library/view/observability-engineering/9781492076438/>

- *Applies to:* The metrics/traces/logs observability stack — cite for the
  instrumentation rationale.

**Rabenstein, B., & Volz, J. "Prometheus: A Next-Generation Monitoring System." USENIX
SREcon15 Europe, Dublin, 2015.**
<https://www.usenix.org/conference/srecon15europe/program/presentation/rabenstein>

- *Applies to:* The Prometheus metrics system design (pull model, time-series, PromQL) —
  cite when introducing the metrics backend. **[UNVERIFIED title:** the specific talk
  "Practical Anatomy of Today's Monitoring Systems" could not be confirmed; the verified
  primary reference is the SREcon15 talk above. Use that, or the official Prometheus docs
  <https://prometheus.io/docs/introduction/overview/>, rather than the unverified title.**]**

### B.5 Graph / Knowledge Graph

**Apache AGE. "Apache AGE — A Graph Extension for PostgreSQL." Apache Software Foundation,
official site & docs.** <https://age.apache.org/> · <https://github.com/apache/age>

- *Applies to:* The graph store — AGE runs the property-graph + openCypher layer inside
  PostgreSQL. Cite when introducing the KG storage/query engine.

**Francis, N., Green, A., Guagliardo, P., Libkin, L., Lindaaker, T., Marsault, V.,
Plantikow, S., Rydberg, M., Selmer, P., & Taylor, A. "Cypher: An Evolving Query Language
for Property Graphs." SIGMOD 2018, pp. 1433–1445. DOI:10.1145/3183713.3190657.**
<https://homepages.inf.ed.ac.uk/libkin/papers/sigmod18.pdf>

- *Applies to:* The **(open)Cypher** query language and the **property-graph data model** —
  cite when describing KG queries/traversals.

### B.6 NER / Extraction

**Zaratiana, U., Tomeh, N., Holat, P., & Charnois, T. "GLiNER: Generalist Model for Named
Entity Recognition using Bidirectional Transformer." NAACL 2024. arXiv:2311.08526, 2023.**
<https://arxiv.org/abs/2311.08526>

- *Applies to:* The **zero-shot / generalist NER** stage of the NLP pipeline — cite where
  entity extraction is described.

### B.7 Identifiers / Time

**Davis, K. R., Peabody, B., & Leach, P. (eds.). "RFC 9562: Universally Unique IDentifiers
(UUIDs)." IETF, May 2024.** <https://www.rfc-editor.org/rfc/rfc9562> ·
<https://datatracker.ietf.org/doc/rfc9562/>

- *Applies to:* **UUIDv7** time-ordered IDs (48-bit Unix-ms prefix → index locality) used
  for all entity/event IDs — cite in the data-model / ID-strategy note (our Rule 6).

### B.8 Retrieval / RAG

**Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H.,
Lewis, M., Yih, W., Rocktäschel, T., Riedel, S., & Kiela, D. "Retrieval-Augmented
Generation for Knowledge-Intensive NLP Tasks." NeurIPS 2020. arXiv:2005.11401, 2020.**
<https://arxiv.org/abs/2005.11401>

- *Applies to:* The **RAG chat** subsystem — the foundational citation for retrieval-
  augmented generation. Cite at the top of the RAG-chat chapter.

**Karpukhin, V., Oğuz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D., & Yih, W.
"Dense Passage Retrieval for Open-Domain Question Answering." EMNLP 2020, pp. 6769–6781.
arXiv:2004.04906.** <https://aclanthology.org/2020.emnlp-main.550/>

- *Applies to:* **Dense (dual-encoder) retrieval** — cite when describing dense retrieval /
  hybrid dense+sparse retrieval and reranking in the RAG pipeline.

### B.9 Architecture Patterns

**Cockburn, A. "Hexagonal Architecture (Ports and Adapters)." 2005 (orig. concept c.
2005).** <https://alistair.cockburn.us/hexagonal-architecture/>

- *Applies to:* The **ports-and-adapters / hexagonal** layering (domain / application /
  infrastructure) used across all services — cite in the per-service architecture
  description. (A 2024 book, Cockburn & Garrido de Paz, *Hexagonal Architecture
  Explained*, exists as a fuller treatment.)

### B.10 Serialization / Schema Registry

**Apache Avro. "Apache Avro Specification (v1.11)." Apache Software Foundation.**
<https://avro.apache.org/docs/1.11.1/specification/> · Project: <https://avro.apache.org/>

- *Applies to:* The **Avro** event serialization format and JSON-schema-based schema
  evolution (forward/backward compatibility) — cite for the event-contract layer.

**Confluent. "Schema Registry / Avro Serdes." Official documentation.**
<https://docs.confluent.io/platform/current/schema-registry/fundamentals/serdes-develop/serdes-avro.html>

- *Applies to:* The **Schema Registry** (versioned schemas, schema-id wire format,
  compatibility enforcement) — cite when describing forward-compatible schema management
  (our Rule 11). Vendor docs, not academic; cite as a technical reference.

### B.11 Storage Engines

**TimescaleDB (Tiger Data). "TimescaleDB — Time-Series Extension for PostgreSQL." Official
docs.** <https://docs.timescale.com/> · <https://github.com/timescale/timescaledb>

- *Applies to:* **Hypertables** (automatic time partitioning into chunks) for OHLCV /
  market time-series — cite where the time-series store is described. **[UNVERIFIED:** no
  peer-reviewed SIGMOD demo paper was located in research; cite the official docs /
  GitHub as the canonical reference, not an academic paper.**]**

**PostgreSQL Global Development Group. "PostgreSQL Documentation."**
<https://www.postgresql.org/docs/>

- *Applies to:* The relational substrate underneath AGE/TimescaleDB and all service DBs —
  cite once when introducing the storage layer.

---

## Verification Summary

**Fully verified against primary sources (arXiv/RFC/SIGMOD/publisher/official docs):**
FrugalGPT (2305.05176), RouteLLM (2406.18665 + LMSYS blog, all 4 router variants
confirmed), Semantic Router (Aurelio repo/site), Mozannar & Sontag (2006.01862, ICML
2020), SelectiveNet (1901.09192, ICML 2019) + Selective Classification (1705.08500),
SetFit (2209.11055), Platt 1999, Zadrozny & Elkan (KDD 2002), BGE/C-Pack (2309.07597,
SIGIR 2024), EmbeddingGemma (2509.20354), Matryoshka (2205.13147, NeurIPS 2022), MTEB
(2210.07316), Kafka paper (NetDB 2011), Kafka Definitive Guide (O'Reilly), DDIA
(Kleppmann 2017), Microservices Patterns (Richardson 2018), Debezium docs, Google SRE
book (2016), Observability Engineering (2022), Apache AGE docs, Cypher (SIGMOD 2018,
DOI 10.1145/3183713.3190657), GLiNER (2311.08526), RFC 9562 (UUIDv7), RAG (2005.11401),
DPR (2004.04906, EMNLP 2020), Hexagonal Architecture (Cockburn), Apache Avro spec,
Confluent Schema Registry docs, PostgreSQL docs.

**Could NOT fully verify (flagged inline):**
1. **Prometheus "Practical Anatomy of Today's Monitoring Systems"** — exact talk title
   unconfirmed; verified substitute is Rabenstein & Volz, *Prometheus: A Next-Generation
   Monitoring System*, USENIX SREcon15 Europe (2015), or the official Prometheus docs.
2. **TimescaleDB SIGMOD demo paper** — no peer-reviewed academic paper located; cite
   official TimescaleDB docs / GitHub instead.
3. **EmbeddingGemma full author byline** — first author and DeepMind affiliation confirmed
   via arXiv:2509.20354; full author list abbreviated here and should be copied verbatim
   from the arXiv PDF before final.
4. **Zadrozny & Elkan exact KDD 2002 page numbers** — DOI verified; confirm page range
   before final.
