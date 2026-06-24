# Worldview Defense — Anticipated Q&A

> Jury: technical, infra / distributed-systems leaning. They will probe
> **design rationale** ("why this, not that?"), **failure modes** ("what happens
> when X breaks?"), and **honesty about evaluation**. For each question below:
> a crisp spoken answer (lead with the answer, then one reason), the slide to
> jump back to, and a note on where it's deeper in the thesis.
>
> Golden rules in Q&A:
> 1. **Answer the question asked**, in one sentence, *then* elaborate.
> 2. If you don't know, say "I didn't measure that — here's what I'd expect and
>    why." Never bluff a number.
> 3. Every "why X" question is really "did you consider the alternative?" — name
>    the alternative and the tradeoff.

---

## A. Architecture & distributed systems (most likely)

**Q1. Why Kafka / event-driven instead of REST calls between services?**
"Decoupling and fault tolerance. With REST, a slow or down NLP service would
block ingestion synchronously and cascade failures upstream. With an event log,
ingestion just publishes and moves on; consumers process at their own pace and a
backlog drains when they recover. It also gives me replay — I can reprocess
history by re-reading the topic. The tradeoff is eventual consistency and harder
debugging, which is why idempotency and the outbox pattern are mandatory."
→ Slides 9, 10, 14.

**Q2. You said at-least-once. Did you consider exactly-once semantics?**
"I deliberately chose at-least-once delivery plus idempotent consumers, rather
than Kafka's exactly-once transactional mode. Exactly-once adds coordination
overhead and only holds *within* Kafka — the moment you write to an external
database or call an LLM, you're outside that guarantee anyway. Idempotency at the
consumer is simpler and covers the real failure: duplicate delivery. So I get
effectively-once *processing* without the transactional cost."
→ Slide 14.

**Q3. The outbox dispatcher publishes asynchronously — what if it crashes
between commit and publish?**
"That's exactly the case the outbox handles. The event is already durably
committed as a row in the database, in the same transaction as the data. If the
dispatcher crashes, the row is still there; on restart it picks up unpublished
rows and sends them. Worst case is *delayed* delivery, never *lost* delivery.
The consumer's idempotency then absorbs any duplicate if the dispatcher published
but crashed before marking the row sent."
→ Slide 10.

**Q4. How do you handle ordering? Events can arrive out of order.**
"Within a Kafka partition order is preserved, and I partition by entity/aggregate
key so all events for the same subject stay ordered. Across partitions there's no
global order — but the design doesn't need one. Facts are corroborative and
carry timestamps; the graph confidence model integrates evidence regardless of
arrival order, and bitemporal versioning records valid-time separately from
ingestion-time."
→ Slide 13, 16. Deeper: Appendix E (confidence model), D (bitemporal schema).

**Q5. What happens when a consumer falls behind — backpressure?**
"Lag is visible as Kafka consumer-group offset lag, which I monitor. Because
consumers are decoupled, lag is absorbed as backlog rather than failure — the
producer side is never throttled by a slow consumer. For the LLM stages, the
routing gate is itself a load shed: it caps how much expensive work enters the
pipeline per article. If I needed more, the lever is consumer parallelism via
partition count."
→ Slides 9, 11.

**Q6. Database-per-service — how do you do queries that span services?**
"I never join across service databases — that's a hard rule. Cross-service data
moves one of two ways: as Kafka events that each service projects into its own
read model, or as a synchronous REST call through the gateway when it must be
live. The knowledge graph is essentially a materialized cross-domain read model
built from events, which is what lets the chat layer answer questions that span
prices, news, and relations without any service reaching into another's DB."
→ Slides 6, 7, 21.

**Q7. Why a graph database (AGE) and not just Postgres tables or a vector DB?**
"The core queries are *traversals* — 'what does B depend on, and what do those
depend on' — which are recursive joins that get ugly and slow in relational SQL
and are impossible in a pure vector store. A property graph expresses multi-hop
paths natively. I used Apache AGE specifically so the graph lives *inside*
Postgres — I get Cypher traversal and SQL/relational integrity in one engine,
without operating a separate graph database. Vector search still exists, but for
document retrieval, not relationship traversal."
→ Slides 13, 18.

**Q8. Why hexagonal architecture / why the six shared libraries?**
"Consistency and testability across ten services. The hexagonal layering keeps
the domain logic free of infrastructure, so I can unit-test business rules
without Kafka or a database. The shared libraries enforce the things that *must*
be identical everywhere — ID generation, time handling, the event envelope,
messaging — so a fix to the outbox or the schema envelope lands in all services
at once instead of being reimplemented ten times with ten subtle bugs."
→ Slide 21. Deeper: Appendix A.

---

## B. NLP / knowledge graph / ML

**Q9. Which model do you use for extraction, and why a hosted LLM?**
"Extraction runs on a hosted open-weights model via DeepInfra — it keeps cost in
the ten-to-twenty-dollar-a-month range while giving better relation extraction
than the small local models I tried. NER is a local zero-shot model (GLiNER) so
the cheap, high-volume step stays free; only the selective, high-value extraction
hits the paid API, gated by the router."
→ Slides 11, 12. (Be ready: it has changed during development — currently a
gpt-oss-class model at medium effort; the *architecture* is model-agnostic.)

**Q10. Your confidence values saturate near 1.0 — isn't the confidence model
useless then?**
"On the seeded evaluation corpus, yes, the *absolute* values aren't meaningful —
and I say so explicitly. The reason is upstream: the extractor emits a
near-constant high score, so there's no contradicting evidence to pull
confidence down. But two things hold: the *decay* dimension works and is verified
live — ephemeral facts visibly age out — and on the larger live snapshot, with
real contradictions and syndication dedup, confidence does spread (stateful
facts average 0.84, signals 0.29). The fix is calibrating the extractor's score
against a gold set, which is named future work, not a hidden flaw."
→ Slide 16, 26.

**Q11. How do you prevent the graph from filling with garbage / hallucinated
relations?**
"Four guardrails. The predicate vocabulary is closed, so the model can't invent
relation types. Entity resolution is a cascade that rejects entities it can't
ground. There are deterministic validation gates — self-loops, out-of-vocabulary
predicates, common-noun subjects, invalid 'listed_on' targets — that drop junk
before it's written. And every edge keeps its evidence sentences, so a bad edge
is auditable and traceable to its source."
→ Slides 12, 13.

**Q12. The graph is 87% orphan entities — doesn't that mean it mostly doesn't
work?**
"It means the *universe* is broad but the *signal* is concentrated, which is what
you'd want. Most orphans are entities mentioned in a single article with no
follow-up — they're cheap to keep and harmless. The connected sub-graph is the
product: it has meaningful density, about 2.6 edges per entity, with a max degree
of 342 on the hubs. Coverage of the connected core grows directly with corpus
size; orphan ratio is a function of how much news you've ingested, not a defect."
→ Slide 26.

**Q13. What is the 'weirdness' metric exactly, and why should I trust
'0/20 noise'?**
"Weirdness ranks a discovered path by three things — how statistically
surprising the link is, how semantically distant the endpoints are, and how
fresh the evidence is — all multiplied by a reliability gate, the harmonic mean
of the edge confidences, so a noisy path can't rank high no matter how
surprising. The '0 of 20' is a manual quality check: I reviewed the top-twenty
ranked paths and none were tautologies or artifacts. It's a small,
single-reviewer check — I present it as directional evidence, not a precision@K
with confidence intervals."
→ Slide 20. Deeper: Appendix E (weirdness formula + ablation).

---

## C. RAG / chat / evaluation

**Q14. How do you stop the chatbot from hallucinating financial facts?**
"Three layers. The model answers only from retrieved tool context, not free
recall. Every claim must carry a citation that resolves to a real chunk. And a
deterministic checker rejects phantom citations and cross-checks numeric claims
against the actual tool outputs — if the prose says a margin the tool never
returned, it fails. Grounding is enforced mechanically, not just prompted."
→ Slides 19, 23.

**Q15. LLM-as-judge — isn't that circular / unreliable?**
"That's the right worry, which is why the judge isn't purely an LLM. The
*decisive* checks are deterministic gates — phantom citation, leaked scaffolding,
numeric contradiction — that need no judgment. The LLM only scores the soft
dimensions on top. And I validated the whole judge against my own hand labels:
Cohen's kappa around 0.95 on a 39-answer gold set. The honest caveat is that it's
a single annotator — me — so it's high agreement, not inter-annotator
reliability. That's listed as a limitation."
→ Slide 23, 26.

**Q16. You report 43% verdict variance across runs — how is that acceptable?**
"It's expected and I surface it rather than hide it. The variance comes from the
agent's tool-*planning* step running at non-zero temperature, so the same
question sometimes takes a different tool path. I handle it two ways: I report
results as patterns over multiple runs, not a single pass rate, and majority
voting over three runs settles to a stable verdict. Setting temperature to zero
would reduce variance but also reduce the agent's ability to recover from a bad
first tool choice — a tradeoff I chose deliberately."
→ Slide 26.

**Q17. Why no precision@K / recall / nDCG on retrieval?**
"Because honest IR metrics need an expert-annotated gold set of query-to-relevant
-document judgments, which I didn't have the resources to build to a defensible
standard. Rather than report a weak number dressed as rigorous, I evaluated what
I *could* defend — end-to-end answer quality with a validated judge, and latency.
Building that retrieval gold set is explicit future work."
→ Slide 26.

---

## D. Scope, cost, product

**Q18. Could this scale to production / many users?**
"The architecture is built for it — stateless services behind the gateway scale
horizontally, and throughput scales with Kafka partition count and consumer
replicas. What I haven't done is load-test at scale or move off single-node
Postgres; today it's a single-machine deployment proving the design. The
bottleneck at scale would be the graph database and the hosted-LLM rate limits,
both addressable."
→ Slide 21, 22.

**Q19. The <$50/month — what's actually in that, and is it realistic?**
"It's the hosted-inference spend from my usage ledger — the paid extraction and
chat LLM calls — projected from a 30-day live window at ten to eighteen dollars.
It excludes my own hardware, which is the point of the 'zero infra' claim: the
software is open-source and self-hosted, only the model API is paid, and the
router keeps that cheap. What it does *not* include is a fully-local-model
counterfactual, which I flag as future work."
→ Slides 4, 5, 11.

**Q20. What's genuinely novel here vs. just integrating existing tools?**
"The integration *is* part of the contribution — no open system combines all six
axes: multi-source ingestion, live NLP, a confidence-weighted knowledge graph,
hybrid multi-modal retrieval, inline citations, and affordability. But the
specific novel pieces are the cost-routing gate that makes live NLP economically
viable, the time-decaying confidence model on graph edges, and the weirdness
metric for surfacing non-obvious dependency paths. Those aren't off-the-shelf."
→ Slides 4, 11, 16, 20.

---

## E. Curveballs / honesty traps

**Q21. If you had to cut one of the ten services, which and why?**
Honest, decisive answer: "The alert service (S10) is the most independent — it's
a consumer of graph-change events, so removing it wouldn't touch the core
generation or access journeys. I'd never cut the content-store or NLP services;
they're the spine." (Shows you understand your own dependency structure.)

**Q22. What was the hardest bug or the thing you got most wrong?**
Have one real story ready — e.g. the silent-drop in extraction where the prompt
advertised values from one source but the lookup used another, dropping ~80% of
output; found via an all-green/zero-output audit. Lesson: "all green" dashboards
can hide zero real output, so I now test for output presence, not just absence of
errors. (This demonstrates engineering maturity better than any feature.)

**Q23. If you started over, what would you change architecturally?**
"I'd invest in the evaluation gold set *first*, before building features — a lot
of my evaluation limitations trace back to not having ground truth early. I'd
also calibrate the extractor confidence from day one rather than retrofitting."

**Q24. Is the AI/LLM layer essential, or could rules do this?**
"Extraction genuinely needs the LLM — relation extraction from free-form
financial news is beyond practical rules. But notice how much *isn't* LLM: NER,
entity resolution, routing signals, confidence, decay, and graph traversal are
all deterministic. The LLM does the one thing only it can do — turn prose into
structured triples — and everything around it is engineered, auditable, and
cheap. That boundary is intentional."
→ Slides 11, 12, 16.
