# Worldview — Defense Speaker Script

> **Format:** ~25 min talk + 10 min Q&A. Audience: technical jury (infra /
> distributed-systems background, mixed depth). Goal: make it unmistakably a
> *thesis defense* — state the objectives, motivate every design decision, show
> the platform, and be honest about the limits.
>
> **Timing per part** (cumulative): Part 1 ~5 min · Part 2 ~4 (→9) · Part 3 ~5
> (→14) · Part 4 ~3 (→17) · Part 5 ~2 (→19) · Demo + close ~3 (→22).
>
> **Delivery notes:** one idea per slide; let the diagrams do the work; slow down
> on the two hook slides (3–4). Say the numbers slowly — they're the evidence.
> Don't read the slides verbatim.
>
> **Protect at all costs:** slides 3, 4, 17, 22, and the demo. **Cut first if
> long:** trim the retrieval-loop slide (21) to the fan-out only; the pipeline
> detail on slide 16 can compress.

---

## SLIDE 1 — Title  *(~20s)*

"Good morning everyone. I'm Arnau Rodon, and today I have the pleasure to walk you through my final thesis, *Worldview — an
AI-driven financial intelligence platform for market-data aggregation and insight
generation*."

---

## PART 1 — MOTIVATION

### SLIDE 2 — The integration gap *(divider, ~10s)*

"But before delving into the project, let me start with the problem we are trying to tackle, an *integration* problem."

### SLIDE 3 — Two data tracks that never meet  *(~70s — slow, this is the setup)*

"Financial data arrives to us along two very different tracks. On one side we have
**structured** data, mainly prices and quarterly fundamentals, which arrive on a
regular schedule and come from stable sources. On the other side we have
**unstructured** data — news articles, filings, and in the last few years even
prediction-market snapshots. Every company has data in both worlds: take TSMC, where
we have a row in a price table and a handful of fundamentals, but we also have the
company's name buried inside a news story, a filing, or an earnings call. The
problem is that nothing enables us to connect all data points, so the thesis is focused
on closing this integration gap.

### SLIDE 4 — The risk you can't see  *(~70s — the hook; slow down)*

"But why is this integration gap so important? It matters because the moment you
hold an asset, you're exposed to a risk — and being able to quantify that risk is
key. And that risk really comes in two kinds. The most obvious one comes from the
companies or assets you actually hold; that risk becomes clear once we close the
integration gap — pulling every price, every filing, and every news story about
the company to get a clear, structured view. But there's a second kind of risk,
that we're also really interested in, and it's the risk from assets or companies
that we do not hold but have an impact on our asset. Let's use as an example NVIDIA,
NVIDIA depends on a supplier, if that company hits a problem, a chain effect could be
generated and the shock could travel until it reaches our asset. This risk cannot be
observed by simply analyzing our positions; we need a more complex knowledge layer that exposes
these risks too.

### SLIDE 5 — Objectives  *(~45s)*

"With that problem in mind, before starting we set six objectives. First, an
**event-driven platform** that could ingest many data types from many sources at once.
Second, a **tiered NLP pipeline** to enrich all that unstructured data. Third, a
**live knowledge graph** where every fact carries a confidence that decays over time.
Fourth, a **chatbot** that answers by combining several kinds of retrieval and grounds
every claim. Fifth, a **frontend** that actually surfaces all of it to the user. And
sixth, an **end-to-end evaluation** of quality, coverage, and latency.

### SLIDE 6 — Why isn't this already solved?  *(~55s)*

"And you might be asking, isn't this already solved? The answer is yes — with a but.
Terminals like Bloomberg or LSEG already do most of it: they ingest everything, run
NLP, even carry supply-chain relationships — so I won't pretend they can't. The but
is the cost: twenty to thirty thousand dollars per user a year, and you can't inspect
them or build on top of them. The open tools — LangChain, GraphRAG, the
finance-specific models — are the opposite: cheap and inspectable, but they don't
*integrate* data; they assume it's already ingested and indexed, and something like
GraphRAG rebuilds its whole graph offline instead of keeping it live. Worldview is the
attempt to sit in that empty row — integrated *and* inspectable, for around fifty
dollars a month."

---

## PART 2 — WHAT WORLDVIEW IS

### SLIDE 7 — What Worldview is *(divider, ~10s)*

"So what is it — concretely, and what does it contribute?"

### SLIDE 8 — Four contributions  *(~50s)*

"First of all, **C-1**: the integrated
platform itself — ten services on a Kafka event backbone with standardized
contracts. **C-2**: a cost-controlled enrichment
pipeline that scores every article/filling/report *before* spending a language model on it.
**C-3**: a live knowledge graph where each edge has a confidence that accumulates
with evidence and decays over time. And **C-4**: a grounded chatbot that retrieves
across vector, text, graph, and structured data and cites every claim it makes."

### SLIDE 9 — Ten services on one event backbone  *(~40s)*

"Here's the whole system at a glance. Ten backend services in three layers: an
**access layer** on top — the frontend, the API gateway, and the service that stores
user data; a **data layer** in the middle that ingests and processes everything; and
an **intelligence layer** below that turns it into knowledge. Everything talks through
Kafka events — no service calls another directly. I won't walk all ten one by one;
instead I'll follow the two main journeys of the platform."

### SLIDE 10 — Architecture foundations  *(~50s)*

"But before delving into the two journeys, I want to mention the three key foundations
that make this platform hold together. **Event-driven**: services talk only
through Kafka, so one slow or failed stage never blocks another. **One door**: a
single API gateway is the only entry point; it authenticates every request and signs the internal token
the backends trust. And third, each service follows a **hexagonal architecture**: the core use cases do not depend directly on Kafka, PostgreSQL, external APIs, or framework code. Those details sit at the edges. This makes the system easier to test, easier to evolve, and safer to refactor.

### SLIDE 11 — Two journeys through the system  *(~45s)*

"The two journeys that better show the entire system are these two: the generation of
intelligence and enrichment of the knowledge graph given an input article.
And the access of the intelligence from the user point of view. Every one of the ten services
sits on one of these two paths. The rest of the talk is just these two journeys, in
order."

---

## PART 3 — GENERATION: ARTICLE → FACT

### SLIDE 12 — Generation *(divider, ~10s)*

"Let's start with the first journey: how raw text becomes a queryable, evidence-backed edge."

### SLIDE 13 — How does an article become a fact?  *(~40s)*

"So an overview of the process is: first an article is published somewhere on the internet.
It's first ingested as raw HTML into an immutable bronze layer inside the object storage
of the platform, then it's cleaned, deduplicated and saved again
in the silver layer, then enriched with entities, relations and metadata, and finally promoted
into the knowledge graph. Each stage only adds the required metadata and structure,
no byte of the original information is thrown away. Let's go now into each step more
carefully."

### SLIDE 14 — Step 1: ingest, then decouple  *(~45s)*

"It all starts with ingestion. Adapters inside the platform are responsible
for pulling information from many providers, the raw content
lands in object storage — in our case MinIO — and then we publish an **event** to
Kafka. Everything downstream reacts to that event; nobody calls anybody directly.
That decoupling is the whole point: if the
NLP stage is slow or down, ingestion doesn't even notice; the backlog just drains
later."

### SLIDE 15 — Step 2: not every article deserves an LLM  *(~50s)*

"Once an article is in the platform, we enrich it, however, not every article deserves the full
treatment, because running a language model over every single article would be expensive and wasteful.
So before any of that, a lightweight **relevance gate** decides how much effort each
article is worth. It embeds the article's title and subtitle and predicts how much
useful information we'd actually get out of it, and from that score it routes the
article into one of three tiers, light, medium and deep. Since this runs before the entire enrichment
of the article, we only ever pay for the articles that earn it.
And that's the second contribution."

### SLIDE 16 — Step 3: the enrichment pipeline  *(~55s)*

"So for the articles that make it through, the pipeline starts by **recognizing the
entities** — a zero-shot model, GLiNER, tags the financial entities with no
fine-tuning. Then the relevance score routes the article — that's the **first cost
gate**. Whatever survives gets **embedded**, and right after comes the **second cost
gate**: a novelty check that downgrades an article if it's just repeating coverage we
already have. The ones left go through the last two steps together — entity
**resolution**, matching each mention to its canonical record through a
cheap-to-expensive cascade, alias then ticker then fuzzy then embedding; and
**extraction**, where the model pulls the relations, but only from a fixed, **closed
vocabulary**, so it can't invent a relation type. And out comes an enriched fact
event, ready for the graph."

### SLIDE 17 — Step 4: the fact lands in the graph  *(~50s — protect)*

"And then the fact actually lands in the graph saying NVIDIA is supplied by TSMC. The important detail is that when the same
relation turns up across many different articles, we don't store it again — we
**corroborate** it with multiple pieces of evidence. So the hidden dependency from the news
becomes now a real, queryable, evidence-backed edge.

### SLIDE 18 — Facts age, so does confidence  *(~55s)*

"One last idea on the graph side — and it's the third contribution. Every edge carries
a rich little record: the relation, the evidence sentence behind it, and a
**confidence that decays over time**. On screen you can see a confidence of 0.82, class
'slow', with a half-life of about two years — because facts don't age the same way:
'incorporated in' is permanent, 'owns' holds for years, an analyst rating for weeks. So
we model confidence as a **Beta posterior that decays**, with the half-life set by the
relation type.

---

## PART 4 — ACCESS: QUESTION → ANSWER

### SLIDE 19 — Access *(divider, ~10s)*

"So that was generation — text in, structured knowledge out. Now let's follow the
second journey, the one that goes the other way: how a user's **question** becomes a
grounded, cited **answer**."

### SLIDE 20 — One door, typed tools  *(~45s)*

"Every request enters through a single API gateway — the only **door** into the
platform. It authenticates the request and signs a short-lived internal token the
backends trust, so nothing reaches a service without passing through it first. From
there the chat service reads the question's **intent** and decides which tools to call.
And here's the key point: the language model never touches a database directly. It
calls **typed tools** — a function API over the whole platform. The model reasons; the
tools fetch — it decides *what* it needs, never *how* the data comes out."

### SLIDE 21 — The retrieval loop  *(~50s)*

"Now here's the actual mechanism behind that. Once the intent is classified, the
agent **fans out — in parallel — across five retrieval modalities** at once. It
traverses the knowledge **graph** over the dependency edges, it runs a hybrid
document and news search that combines vector similarity with keyword matching, it
does structured lookups over market data and fundamentals, it reads the user's own
**portfolio**, and it pulls pre-computed entity intelligence. Altogether that's
twenty-two typed tools across six domains, and the model picks and combines whichever
ones the question actually needs. Those results are merged before the model writes
its answer, and everything streams back to the user as it happens."

### SLIDE 22 — Grounded & cited: a worked example  *(~50s)*

"Let's make that concrete with the same question — *what's my exposure to TSMC?* The
loop comes back with several things at once: two **graph edges**, telling us NVIDIA
is supplied by TSMC and showing TSMC's other customers; a **portfolio row**, that
you hold NVIDIA at four-point-two percent of your book; two **news chunks**, one from
Reuters and one from Bloomberg; and a **market row** with TSMC's margins. And the
crucial part is that the model writes the answer **only from that retrieved context**
— nothing else. Every single claim carries a **citation**, bracket-one through
bracket-four, and each one resolves back to a real source. So there are no ungrounded
claims about your money. This is the fourth contribution — and it's exactly the hook
from slide four, now answered: the hidden exposure is surfaced, and every word of it
is traceable."

### SLIDE 23 — Evaluation *(divider, ~10s)*

"So those are the two journeys — text in one side, answers out the other. The last
thing I owe you is the honest part: does it actually run, is it fast, and are the
answers any good?"

### SLIDE 24 — How do I know the answers are good?  *(~60s)*

"Now the more interesting question, and the one I care most about: how do I know the
answers are good, and not just plausible? For that I built an **LLM-as-judge**
framework that works as a pipeline — a question goes into the **/chat** endpoint, the
answer comes back, and an **LLM judge** scores it, in two tiers. **Tier one** is a set
of **deterministic gates** — a citation that points to nothing, leaked
tool-scaffolding, or a number that contradicts what we retrieved. Any one of those is
an automatic **fail**, before anything subjective. **Tier two** is a softer
**rubric** — grounding, routing, coherence — graded by the model. It all combines into
a final score per answer."

### SLIDE 25 — Results against the objectives  *(~40s)*

"So let me put it against the six objectives we set at the very start. The
**event-driven platform**, the **cost-controlled NLP**, the **five user journeys**,
and the **latency** targets all **pass** cleanly. The **knowledge graph** and the
**RAG chat** also **pass on the mechanism** — both are live and working end to end —
but I'll be honest that there are still some **quality inconsistencies** there that
would need further work: the graph's confidence isn't fully calibrated yet, and the
chat's citation faithfulness is still preliminary. Honest things to keep working on —
and a good moment to stop talking and just show you the thing."

---

## PART 6 — DEMO & CONCLUSIONS

### SLIDE 26 — Demo & conclusions *(divider, ~10s)*

"So let me show you the real platform, live — and then I'll close."

### SLIDE 27 — Live demo  *(~3 min — see demo flow)*

"This is the actual running platform, nothing pre-baked — and if anything stalls I'll
quietly cut to a recording. Let me take you through the same story we've been building
toward, but live: from the overload, to a hidden link, to a cited answer about your
own money."

*(If anything stalls, cut to the backup recording without comment.)*

> **Demo flow (target 3 min):**
> 1. Dashboard — the overload problem, made navigable *(~30s)*.
> 2. Open an entity (e.g. NVIDIA) → Intelligence tab → show the linked relations /
>    the supplier edge in the graph *(~60s)*. This is the slide-4 payoff, live —
>    aside: "a manual review of the top-twenty paths this surfaced found none to be noise."
> 3. Open chat → ask the exposure question → show the streaming answer **with
>    citations** → click a citation to show the source *(~75s)*.
> 4. One line: "Everything you just saw came through the two journeys." *(~15s)*

### SLIDE 28 — Contributions & what's next  *(~40s)*

"So to bring it together — four contributions: an **integrated, event-driven
platform**; a **cost-controlled enrichment pipeline** that decides what's worth a
model before spending one; a **live knowledge graph** whose confidence decays over
time; and a **grounded, cited, multi-modal chatbot** — all wrapped in a **reproducible
evaluation harness**. And where does it go next? Several of the steps are the **gaps
I've flagged** along the way — calibrating the extractor's confidence off that
saturation ceiling, validating the judge beyond my own labels, and densifying the
graph, which today covers only about **thirteen percent** of entities. The bigger
ambition is to **scale beyond a single host** — Kubernetes, multi-region,
**multi-tenant** for real users — and to fold **prediction-market signals** into the
same graph. The nice part is that the **Chapter-3 contracts carry over unchanged** —
only the substrate underneath grows."

### SLIDE 29 — Thank you  *(~15s)*

"And that's Worldview. Thank you all very much for your time — I'd be genuinely happy
to take any questions you have."

---

## Timing safety valves (if running long)

- **Cut first:** Slide 21 (retrieval loop) → name the fan-out, skip listing all five
  modalities.
- **Then:** Slide 18 (facts age) → drop the half-life examples; Slide 16 (pipeline) →
  gates + extraction only.
- **Protect at all costs:** Slides 3, 4, 17, 22, and the demo. Those carry the thesis.
