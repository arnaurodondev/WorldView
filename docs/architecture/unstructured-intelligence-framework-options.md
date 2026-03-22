# Unstructured Intelligence Framework Options

## Purpose

This note evaluates how Worldview should evolve the unstructured-data part of the platform so it can:

- retrieve relevant evidence quickly,
- build durable relations between entities, events, claims, and documents,
- reason about likely outcomes or second-order effects,
- stay operationally realistic for a thesis-grade system.

The goal is not to pick the most sophisticated standalone product. The goal is to pick the smallest architecture that can credibly support a market-intelligence workflow and still leave room for deeper knowledge and reasoning later.

## Current Repo Reality

The repo documentation describes a fairly rich S4-S8 pipeline:

- S4 content-ingestion
- S5 content-store
- S6 nlp-pipeline
- S7 knowledge-graph
- S8 rag-chat

However, the current implementation state is much earlier than the target design:

- the services above are mostly scaffolds,
- the docs assume pgvector and Apache AGE,
- the current local and test compose stacks do not yet clearly provision pgvector or AGE-capable images/extensions,
- the architecture docs already recommend the thesis-pragmatic merges of S4+S5 and S6+S7.

That matters because the main near-term bottleneck is not retrieval quality alone. It is system sprawl relative to current maturity.

## What Worldview Actually Needs

Worldview needs four distinct capabilities. They should not be collapsed into one product decision.

### 1. Evidence Retrieval

Find the right articles, filings, transcripts, company pages, macro releases, and event records quickly.

Core requirements:

- hybrid retrieval: lexical + vector + metadata + graph-aware filters,
- provenance preserved at every step,
- cheap filtering by company, sector, geography, time window, source class,
- chunk-level retrieval with article-level aggregation.

### 2. Knowledge Construction

Turn raw text into durable structures:

- entities: companies, executives, regulators, products, countries, indices,
- events: earnings, guidance cuts, acquisitions, sanctions, supply disruptions,
- claims: management statements, analyst claims, media claims,
- relations: supplier-of, competitor-of, exposed-to, operates-in, mentioned-with,
- temporal validity and provenance.

### 3. Reasoning About Outcomes

Worldview should not rely on an LLM alone to infer likely outcomes. Outcome reasoning should be a structured layer built on top of extracted evidence.

The useful pattern is:

- detect an event,
- map it to affected entities and exposures,
- propagate expected impact through a relation graph,
- score confidence using source quality, recency, and corroboration,
- let the LLM explain the reasoning path, not invent the path.

### 4. Operational Fit

The platform still needs to be deployable and defensible in a thesis environment.

Core constraints:

- minimal infrastructure count,
- clear migration path from scaffold to demo-ready system,
- easy local development,
- manageable data licensing and cost,
- no dependence on a brittle, novel stack before basic workflows are working.

## Recommended Capability Model

Worldview should be designed as three layers, not one monolith.

### Layer A. Retrieval and Storage Plane

This is the system of record for documents, chunks, embeddings, metadata, and read models.

Recommended near-term base:

- PostgreSQL for canonical metadata and queryable read models,
- pgvector for embeddings and nearest-neighbor search,
- MinIO for raw and normalized document artifacts,
- Valkey for caches and query/session acceleration.

### Layer B. Relation and Memory Plane

This stores entity and event relations, claim provenance, temporal facts, and reusable context.

This can start in PostgreSQL with relational edge tables and later evolve into:

- Apache AGE inside Postgres,
- Graphiti on a graph backend,
- Neo4j or Memgraph if graph traversal becomes central.

### Layer C. Reasoning Plane

This computes outcome hypotheses from structured evidence.

It should use:

- event templates,
- exposure graphs,
- scoring rules,
- optional probabilistic or ranking models,
- LLM synthesis only after evidence assembly.

This is where Worldview becomes more than a search system.

## Evaluation Of Candidate Solutions

### PostgreSQL + pgvector + Relational Graph Tables

What it solves:

- unified operational store,
- low infra overhead,
- strong metadata filtering,
- good-enough hybrid retrieval,
- easy fit with current repo assumptions.

Strengths:

- best fit for current maturity,
- easiest path to materialized read models,
- simple to run locally,
- preserves optionality for later graph specialization.

Weaknesses:

- complex multi-hop reasoning becomes awkward faster than in a native graph store,
- temporal relation reasoning needs explicit modeling discipline,
- ranking quality depends on careful application logic.

Assessment:

- best near-term system of record,
- should be the baseline even if a graph layer is added later.

### Apache AGE

What it solves:

- graph traversal inside PostgreSQL,
- Cypher-style graph queries without introducing a separate graph database.

Strengths:

- aligns with existing architecture docs,
- keeps graph and relational data close together,
- lower operational cost than a separate graph platform.

Weaknesses:

- current repo infra does not yet clearly provision it,
- smaller ecosystem than Neo4j,
- more friction than plain Postgres if the team is still building basics.

Assessment:

- a sensible medium step if the team wants graph traversal without committing to Neo4j or Memgraph,
- not the first thing to add before the ingestion and projection flow is working.

### Neo4j

What it solves:

- mature graph database,
- graph traversal and graph-native modeling,
- vector indexes and graph-plus-vector retrieval patterns.

Strengths:

- strongest general-purpose graph ecosystem in this set,
- excellent for GraphRAG and entity/event exploration,
- good fit if the demo emphasizes causal chains and explainable relationship walks.

Weaknesses:

- adds separate infrastructure and separate operational surface area,
- encourages early graph centralization before the pipeline is mature,
- can become overkill if most value still comes from document retrieval and SQL projections.

Assessment:

- strong later-stage option,
- not the best first move for this repo right now.

### Memgraph

What it solves:

- graph-native retrieval and graph algorithms,
- real-time graph operations with GraphRAG positioning.

Strengths:

- attractive for live, relation-heavy reasoning,
- good graph analytics story,
- strong when event propagation or influence modeling matters.

Weaknesses:

- adds a dedicated graph platform early,
- smaller adoption footprint than Neo4j,
- still requires the team to first solve extraction quality and relation quality.

Assessment:

- promising for a future graph-first iteration,
- not the right initial backbone.

### Weaviate

What it solves:

- vector-first retrieval with built-in hybrid vector + BM25 search,
- query-time fusion controls.

Strengths:

- strong retrieval ergonomics,
- useful when semantic search quality is the primary concern,
- simpler hybrid retrieval than assembling everything manually.

Weaknesses:

- relation modeling is not the center of gravity,
- another dedicated datastore before the current services are mature,
- can duplicate functionality that a Postgres-first stack can already cover adequately for a thesis build.

Assessment:

- good dedicated retrieval engine,
- weaker fit than Postgres-first for a system that also wants durable structured relations.

### Qdrant

What it solves:

- high-quality vector search and filtering,
- scalable semantic retrieval engine.

Strengths:

- efficient vector retrieval,
- clear operational role,
- good if retrieval latency and vector quality become dominant concerns.

Weaknesses:

- not a relation system,
- still requires a second store for structured knowledge,
- adds infra before the repo has earned it.

Assessment:

- good optional later retrieval specialization,
- not sufficient as the main intelligence backbone.

### Redis Vector Search

What it solves:

- very fast vector and filtered retrieval,
- cache plus retrieval in one system.

Strengths:

- good for hot working sets,
- natural fit with existing Valkey/Redis-style cache use,
- helpful for response-time optimization and session context.

Weaknesses:

- poor substitute for a canonical knowledge store,
- should not become the main source of truth for long-lived intelligence.

Assessment:

- useful acceleration layer,
- not a primary architecture choice.

### Graphiti

What it solves:

- temporal context graph construction,
- evolving facts with provenance and validity windows,
- hybrid retrieval over a graph-based memory layer.

Strengths:

- very aligned with market-intelligence needs around changing facts over time,
- better fit than generic GraphRAG for dynamic corpora,
- explicitly designed for context evolution rather than only static graph traversal.

Weaknesses:

- introduces a new conceptual layer and usually a graph backend,
- best value appears after extraction quality is already reasonably high,
- more appropriate as an intelligence-memory layer than as the base operational store.

Assessment:

- one of the most interesting later additions for Worldview,
- especially useful if the project wants temporal entity memory and provenance-aware context graphs,
- should sit above the retrieval plane, not replace it.

### Hindsight

What it solves:

- agent memory with retain, recall, and reflect,
- memory types such as observations, world facts, experiences, and mental models,
- multi-strategy retrieval across semantic, keyword, graph, and temporal signals.

Strengths:

- strong conceptual match for agentic research workflows,
- reflection capability is useful for iterative analysis,
- useful when the system must learn from prior interactions and not just search documents.

Weaknesses:

- optimized for agent memory, not for being the canonical enterprise knowledge system,
- could blur the line between durable facts and agent-generated memory unless carefully governed,
- does not remove the need for a clean document and knowledge backbone.

Assessment:

- best treated as an orchestration or analyst-memory layer,
- not a replacement for Postgres, vector search, or a durable knowledge graph,
- interesting for S8-style analyst copilots once the evidence stack exists.

## Bottom-Line Fit

If the question is "What should Worldview adopt first?" the answer is not Hindsight, Graphiti, Neo4j, or a dedicated vector database.

The first move should be:

1. merge services to reduce coordination cost,
2. build a PostgreSQL-first retrieval and projection layer,
3. add explicit entity, event, and claim models with provenance,
4. only then decide whether a graph-native or agent-memory layer is justified.

If the question is "What is the most interesting future enhancement once the basics are working?" the strongest candidates are:

- Graphiti for temporal context graphs,
- Neo4j or Memgraph for graph-heavy reasoning and exploration,
- Hindsight for analyst-agent memory and reflective workflows.

## Recommended Architecture For Worldview

### Phase 1. Thesis-Pragmatic Baseline

Recommended service shape:

- merge S4 + S5 into a single Content Service,
- merge S6 + S7 into a single Intelligence Service,
- keep S8 RAG/Chat as the synthesis and interaction layer.

Data model:

- documents table for canonical content records,
- chunks table for retrieval units,
- embeddings table or pgvector columns,
- entities table,
- events table,
- claims table,
- edges table for typed relations,
- evidence tables linking all extracted objects back to document spans and source metadata.

Retrieval:

- lexical search,
- vector search,
- metadata filters,
- reranking,
- result assembly into entity dossiers and event timelines.

Reasoning:

- rule-based impact templates,
- exposure mapping using typed edges,
- confidence scoring by source quality, recency, and corroboration.

### Phase 2. Temporal Knowledge Layer

Once the baseline works, add one of these:

- Apache AGE if the team wants to stay inside Postgres,
- Graphiti if temporal facts and provenance-rich context are the main differentiator,
- Neo4j or Memgraph if deep graph traversal becomes central to the user experience.

The main addition in this phase is not just a graph database. It is temporal fact management:

- when a relation became valid,
- when it stopped being valid,
- which sources support it,
- how confident the system is in it.

### Phase 3. Analyst Memory And Reflective Workflows

This is where Hindsight becomes interesting.

Use cases:

- retain investigation context across sessions,
- remember prior hypotheses and failed leads,
- store analyst-specific working assumptions separately from canonical facts,
- support reflective workflows after new evidence arrives.

Important rule:

- Hindsight-style memory should augment analyst workflow, not become the authoritative fact store.

### Phase 4. Forecasting And Outcome Modeling

For reasoning about likely outcomes, the clean pattern is:

- ingest new evidence,
- extract structured events and claims,
- map events into an exposure graph,
- score first-order and second-order impacts,
- generate scenarios with explicit evidence chains.

Practical scoring inputs:

- event type,
- affected entity type,
- relation distance,
- source credibility,
- source count and corroboration,
- temporal decay,
- historical analogs,
- market regime context.

This can stay deterministic at first. A thesis system does not need a full probabilistic graphical model on day one.

## Performance Improvements That Fit The Current Repo

These are the most useful improvements for the existing architecture.

### 1. Reduce Service Chatter

Merge the content and intelligence service pairs first. This removes avoidable network hops and deployment friction.

### 2. Build Read-Optimized Projections

Do not query raw extraction tables for every user request. Maintain projections for:

- company dossier,
- topic dossier,
- event timeline,
- article summary,
- relation neighborhood,
- watchlist-specific evidence bundles.

### 3. Use Selective Reprocessing

Avoid full re-embedding or full re-extraction on every document update.

Use:

- content hashes,
- chunk hashes,
- versioned extraction stages,
- invalidation only for affected artifacts.

### 4. Keep Provenance Cheap To Query

Store evidence references so the system can explain itself without expensive joins across large raw payloads.

### 5. Cache Hot Question Patterns

Use Valkey for:

- recent entity dossiers,
- watchlist event summaries,
- retrieval candidate sets,
- partial conversation context.

### 6. Budget The Retrieval Fan-Out

Hybrid retrieval can become slow if every query hits every store deeply.

Use staged fan-out:

- metadata narrowing first,
- lexical and vector candidate generation second,
- graph expansion only for shortlisted entities or events,
- reranking last.

## Data Providers That Fit Worldview

The provider mix should be layered, just like the system architecture.

### Core Structured Market Baseline

#### EODHD

Why it fits:

- already relevant to the surrounding workspace,
- broad market/fundamental coverage,
- useful as a baseline price and reference-data provider.

Role:

- broad structured market data backbone.

#### SEC EDGAR

Why it fits:

- official US filings source,
- real-time submission updates,
- company submissions and XBRL company facts APIs,
- bulk archives available nightly.

Role:

- authoritative filings and reported facts,
- best source for grounding 10-K, 10-Q, 8-K, and XBRL-based intelligence.

#### FRED

Why it fits:

- official macro and rates reference source,
- release metadata, series, observations, revisions, and tags.

Role:

- macro context layer for rates, inflation, labor, growth, and release-aware analysis.

### Open Or Broad Unstructured Event Layer

#### GDELT

Why it fits:

- open global event and knowledge graph dataset,
- news and event monitoring at very large scale,
- global coverage, multilingual processing, frequent updates,
- includes event streams, knowledge graphs, quotes, geographic data, relationship graph experiments.

Role:

- global event detection,
- geopolitical and macro narrative monitoring,
- useful for early-warning and cross-border signals.

Caveat:

- huge and noisy,
- should be filtered and projected into domain-specific event models rather than queried raw in the application path.

#### Event Registry

Why it fits:

- article and event-centric news API,
- good for event grouping, concept extraction workflows, and targeted news monitoring.

Role:

- curated event/news aggregation layer,
- useful if Worldview wants cleaner event-centric ingestion than raw news scraping.

### Premium Or Higher-Signal Structured + Alternative Data

#### Finnhub

Why it fits:

- unusually broad coverage across company news, filings, transcripts, estimates, ownership, supply-chain relationships, ESG, lobbying, transcripts, patents, and economic calendars.

Role:

- high-value enrichment source,
- especially strong if the project wants one provider that adds both structured finance and alternative/company intelligence.

Best uses in Worldview:

- transcripts,
- filing metadata,
- analyst expectations,
- supply-chain and ownership relations,
- newsroom and press release ingestion.

#### Financial Modeling Prep

Why it fits:

- broad and pragmatic API surface,
- strong coverage for profiles, statements, transcripts, news, SEC filing search, ownership, sector snapshots, and bulk endpoints.

Role:

- practical structured-data enrichment and bulk ingestion source.

Best uses in Worldview:

- bulk backfills,
- statement normalization,
- transcript coverage,
- news and SEC discovery.

#### Tiingo

Why it fits:

- consistent REST and websocket model,
- EOD, IEX, fundamentals, forex, crypto, and news support,
- explicit performance and format design.

Role:

- reliable market and news feed candidate when cleaner market-data plumbing is preferred over very broad alternative datasets.

### Simpler News Layer

#### NewsAPI

Why it fits:

- easy keyword and headline search across a large source base,
- quick integration for prototyping.

Role:

- lightweight news bootstrap source.

Caveat:

- better for prototype ingestion and coverage expansion than for high-confidence event intelligence on its own.

### Optional Premium Real-Time Market Data

#### Massive.com / Polygon

Why it fits conceptually:

- strong market-data reputation for real-time and historical feeds.

Role:

- premium real-time equities/options/market microstructure candidate if the project later needs faster production-grade market feeds.

Caveat:

- official docs were not source-validated in this pass because the fetch attempt hit a certificate issue,
- keep it as a candidate, not a hard recommendation from this note.

## Recommended Provider Stack By Phase

### Lowest-Cost Credible Stack

- EODHD
- SEC EDGAR
- FRED
- direct company IR and newsroom pages
- selected RSS/news feeds or NewsAPI

This is enough to build a defensible first demo.

### Better Intelligence Stack

- EODHD
- SEC EDGAR
- FRED
- GDELT
- Event Registry
- direct company IR/newsroom feeds

This is the best balance if the goal is strong event and narrative awareness.

### Higher-Signal Premium Stack

- EODHD or Tiingo for baseline market coverage
- SEC EDGAR
- FRED
- GDELT or Event Registry
- Finnhub or Financial Modeling Prep for transcripts, filings, alternative data, and enrichment

This is the strongest fit for a more complete market-intelligence workflow.

## Concrete Recommendation

Worldview should not jump straight to a dedicated graph or memory platform.

The recommended order is:

1. merge S4+S5 and S6+S7,
2. implement Postgres + pgvector + MinIO + Valkey as the real working baseline,
3. model entities, events, claims, and evidence explicitly,
4. build read models for dossier, timeline, and exposure views,
5. add temporal graph capabilities only when relation-heavy workflows are working,
6. add Hindsight-like agent memory only after canonical fact handling is stable.

If one advanced addition should be prioritized after the baseline, Graphiti is the most interesting fit for Worldview's long-term direction because it directly addresses evolving facts, provenance, and temporal context. Hindsight is best added later as a reflective analyst-memory layer. Neo4j or Memgraph should be considered only when the graph itself becomes a core user-facing asset rather than an internal support structure.

## Suggested ADR Candidates

The following are worth formal ADRs once the team wants to commit:

- merge unstructured services for thesis scope,
- choose baseline retrieval store and vector strategy,
- decide whether graph stays inside Postgres or moves to a dedicated graph backend,
- define the canonical entity-event-claim-evidence model,
- define a reasoning policy that separates scored evidence from LLM narration.

## Final Take

The right answer for Worldview is not "pick the fanciest GraphRAG stack."

The right answer is:

- keep the system of record simple,
- make knowledge construction explicit,
- treat memory systems like Hindsight as augmentation layers,
- treat graph systems like Graphiti, AGE, Neo4j, or Memgraph as optional relation accelerators,
- reserve the real differentiation for provenance-aware reasoning over entity and event exposure.

That path is both technically credible and realistic for the current repo state.
