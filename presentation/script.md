# Worldview — Defense Speaker Script

> **Format:** ~25 min talk + 10 min Q&A. Audience: technical jury (infra /
> distributed-systems background, mixed depth). Goal: explain the *key*
> components clearly, motivate every design decision, prove the core idea works.
>
> **Timing target per act** (cumulative):
> Act 1 ~4 min · Act 2 ~3 min (→7) · Act 3 ~8 min (→15) · Act 4 ~5 min (→20) ·
> Act 5 ~3 min (→23) · Demo ~3 min (→26*) — trim to land at 25.
>
> **Delivery notes:** one idea per slide; let the diagrams do the work; pause on
> the three "hard problem" slides — those are what this jury came to hear. Say
> the numbers slowly, they're the evidence. Don't read the slides verbatim.

---

## SLIDE 1 — Title  *(~20s)*

"Good morning. My name is Arnau Rodon, and this is my bachelor's thesis:
*Worldview — an open financial intelligence platform*. Over the next 25 minutes
I'll show you the problem it solves, how it's built as a distributed system, and
then I'll demo it live."

---

## ACT 1 — THE PROBLEM

### SLIDE 2 — One portfolio, too many signals  *(~50s)*

"Imagine you hold a portfolio of 30 companies. To actually understand it, for
*each* company you need to track prices, fundamentals, the news flow, and
regulatory filings. The news alone is on the order of three thousand items a
week. No human reads that — and the tools that digest it for you are either
extremely expensive or don't really exist in the open. That's the surface
problem: information overload."

### SLIDE 3 — The risk you don't see  *(~70s — slow down, this is the hook)*

"But there's a deeper problem, and it's the one this thesis is really about.
The risk to your portfolio is often *not* in the companies you hold — it's in
the companies they **depend on**.

Take this chain: Supplier A makes a critical component for Manufacturer B, and
you hold B. If A has a disruption — a fire, a sanction, a shortage — B is hit,
and so are you. But here's the thing: **A may never appear in your portfolio at
all.** You can't see this risk by watching your holdings. You can only see it if
something has *linked* A to B in the first place.

Capturing those indirect links — at scale, automatically, from news — is the
core idea of Worldview. Keep this picture in mind; we'll come back to it."

### SLIDE 4 — Why isn't this already solved?  *(~50s)*

"So why doesn't this exist already? It kind of does — on Bloomberg or LSEG
terminals, which link data like this but cost twenty to thirty thousand dollars
per seat per year. On the open side, you have great tools — FinBERT, vector
databases — but they don't *link* anything into a graph, and they're not
conversational. So there's a gap: the systems that connect everything are
locked behind terminal pricing, and the open systems don't connect anything.
Worldview aims to sit in that empty bottom row — open, affordable, linked, and
conversational."

---

## ACT 2 — WHAT IT IS

### SLIDE 5 — Three things, end to end  *(~50s)*

"At the highest level Worldview does three things. One: it **ingests
everything** — market data, news, filings, fundamentals — from many providers,
in a decoupled, fault-tolerant way. Two: it **links that into a knowledge
graph** — entities and the relations between them, where every fact carries a
confidence that decays over time. Three: it **answers questions with
citations** — a chatbot that retrieves over the graph and grounds every claim in
a real source. And it does all of this open-source, on commodity hardware, for
under fifty dollars a month in external APIs."

### SLIDE 6 — The system: 10 services  *(~40s)*

"Here's the whole system. Ten backend services, each owning its own database,
all communicating over a Kafka event backbone. One frontend, six shared
libraries. I'm showing you this diagram once to orient you — but I am *not*
going to walk through ten services one by one. That would be a catalog, and
you'd be asleep by service four."

### SLIDE 7 — Two journeys, not ten services  *(~50s)*

"Instead, I'll follow **two journeys** through the system. The first —
*generation*, on the left — is how an article out in the world becomes a fact in
our knowledge graph. The second — *access*, on the right — is how a user's
question becomes a grounded answer. Every one of those ten services shows up on
one of these two paths. I'll introduce each service the moment we reach it, and
I'll attach the interesting engineering decision right there in context. Let's
start with the first journey."

---

## ACT 3 — TRACE 1: FROM AN ARTICLE TO A FACT

### SLIDE 8 — The lifecycle question  *(~40s)*

"The question this trace answers: an article publishes somewhere on the
internet — how does it end up as a structured fact we can query? It goes through
a medallion pipeline: raw HTML, to a bronze layer, cleaned into silver, then
enriched, and finally promoted into the knowledge graph. Let me walk the
interesting steps."

### SLIDE 9 — Ingest, then decouple  *(~50s)*

"First, ingestion. We have adapters that pull from many providers — news,
regulatory feeds, even prediction markets. The raw content goes into object
storage, and then — this is the important part — we publish an **event** to
Kafka. Everything downstream reacts to that event. No service ever calls another
service directly. That decoupling is what makes the platform fault-tolerant: if
the NLP stage is slow or down, ingestion doesn't even notice. It just keeps
publishing events, and the backlog drains later."

### SLIDE 10 — Hard problem #1: the dual write  *(~70s — slow, this is for the jury)*

"And that immediately gives us our first hard distributed-systems problem. When
we ingest, we need to do **two** writes: save the data to our database, *and*
publish an event to Kafka. Those are two different systems. What if the database
commit succeeds but the Kafka publish fails — or vice versa? Now the world and
our database disagree, silently, forever.

The solution is the **transactional outbox pattern**. Instead of publishing to
Kafka directly, we write the event as a row into an *outbox table*, inside the
**same database transaction** as the data itself. So it's one atomic commit —
either both the data and the event are saved, or neither is. Then a separate
dispatcher reads the outbox and publishes to Kafka asynchronously, retrying
until it succeeds. No dual-write inconsistency, no lost events. This pattern is
used everywhere a service writes data and emits an event."

### SLIDE 11 — Not every article deserves an LLM  *(~55s)*

"Next, enrichment — and here cost becomes the constraint. Running a language
model over every single article would be expensive. So before extraction, a
**routing gate** scores each article on how likely it is to contain something
useful, and assigns an effort tier. Over a 30-day live window of about seven
thousand articles, roughly 57% got medium effort, 32% deep, 11% light. The
effect: hosted-inference spend stays around ten to eighteen dollars a month —
comfortably under my fifty-dollar budget. Cost control isn't an afterthought;
it's a routing decision made per article."

### SLIDE 12 — Extract entities and relations  *(~55s)*

"Now the actual extraction. A language model reads the text and emits triples —
subject, predicate, object. Two design choices matter here. First, the
predicates come from a **closed vocabulary** — the model picks from a fixed list
of relation types, it can't invent arbitrary strings, which keeps the graph
clean. Second, entities are resolved through a **cascade**: we try the cheapest
match first — an exact alias, then a ticker symbol — and only fall back to fuzzy
matching or embedding similarity if those miss. The output of all this is
exactly the relation from our opening slide: *NVIDIA is supplied by TSMC* — with
the sentence it came from attached as evidence."

### SLIDE 13 — The fact lands in the graph  *(~50s)*

"And now that fact physically lands in the knowledge graph, stored as a
versioned edge in Apache AGE, our graph database. Crucially, when the *same*
relation shows up in many different articles, we don't store duplicates — we
**corroborate**. On average each edge is backed by about sixteen pieces of
evidence. So the hidden dependency from slide three — supplier to manufacturer —
is now a real, queryable, evidence-backed edge in the graph. That's the whole
generation journey: text in, structured fact out."

### SLIDE 14 — Hard problem #2: idempotency  *(~50s)*

"Two more hard problems before we move on, because this is an event-driven
system and you'll want to know I handled them. The first: Kafka gives you
*at-least-once* delivery, which means every consumer **will**, eventually,
receive the same message twice. If a consumer naively processes every message,
you get double facts. The solution is **idempotent consumers** — each consumer
records the IDs of events it has already processed and checks before acting. A
re-delivery becomes a harmless no-op."

### SLIDE 15 — Hard problem #3: schema evolution  *(~45s)*

"The second: services deploy independently, so their message formats drift over
time. If I add a field to an event, I must not break consumers still running the
old code. So every event is wrapped in a **versioned envelope**, and the schemas
are Avro, validated for **forward compatibility** — you can add fields with
defaults, but you can never remove or rename one. That discipline is what lets
ten services evolve without a coordinated big-bang deploy."

### SLIDE 16 — Facts age, so does confidence  *(~60s)*

"One last idea on the graph side, and it's a nice one. Not all facts are equally
durable. 'Company X is incorporated in Delaware' is basically permanent. 'X owns
Y' is durable, maybe a couple of years. 'Analyst rating' is good for weeks.
'Intraday momentum' is stale in days. So every edge's confidence is modeled as a
**Beta posterior that decays over time**, with a half-life set by the relation's
class. I verified this live: an ephemeral relation's confidence drops from one
point zero all the way to about zero-point-one-six over its half-life — exactly
as designed.

I'll be honest about the limitation here: on my seeded evaluation data the
confidence values saturate near one, because the extractor currently emits a
near-constant high score. The *decay mechanism* is correct and live, but the
absolute calibration of those scores is still future work. I'd rather you hear
that from me than find it in the appendix."

---

## ACT 4 — TRACE 2: FROM A QUESTION TO A GROUNDED ANSWER

### SLIDE 17 — "What's my exposure to TSMC?"  *(~50s)*

"Second journey: a user asks a question. Every request enters through a single
API gateway — that's the only door into the system; it handles authentication
and signs an internal token that the backend services trust. The chat service
then classifies the **intent** of the question and decides which tools to call.
And that's the key design point: the language model never touches a database
directly. It calls **typed tools** — think of it as a function API over the
whole platform. The model reasons; the tools fetch."

### SLIDE 18 — Four ways to retrieve  *(~50s)*

"There are four retrieval modalities. Graph traversal — follow the dependency
edges we just built. Hybrid document search — vector similarity plus keyword
search, merged together. Structured lookups — prices, fundamentals, the exact
numbers. And entity intelligence — profiles, contradictions between sources. The
agent chooses and combines these per question, often firing several in parallel,
and then the results are fused by rank before going to the model."

### SLIDE 19 — Fuse, ground, cite  *(~55s)*

"Here's the flow concretely. The question 'what's my exposure' is classified as
a supply-chain question. The agent fires graph traversal, document search, and a
fundamentals lookup. Their results are rank-merged. Then — and this is the part
that matters for trust — the model writes the answer **only from the retrieved
context**, and every claim carries a citation marker that resolves back to a
real source chunk. We even run a deterministic check that rejects a *phantom
citation* — a citation pointing to a tool that was never actually called. The
goal is simple: no ungrounded claims about your money."

### SLIDE 20 — The payoff: surfacing the hidden link  *(~55s)*

"And this is the payoff — it closes the loop with slide three. The system can
now answer that original question, *including* the indirect, non-obvious
connections. To rank discovered paths, I use a *weirdness* score that rewards
paths that are both surprising **and** reliable — so a genuine cross-sector
bridge ranks high, but a path that just routes through some giant hub does not.
When I manually reviewed the top twenty paths it surfaced, **zero** were noise.
That's the core thesis claim, demonstrated: the platform surfaces real hidden
dependencies, not tautologies."

---

## ACT 5 — DOES IT ACTUALLY RUN?

### SLIDE 21 — A real distributed system on one machine  *(~45s)*

"Quick reality check for an infra audience: this isn't slideware. The whole
thing — about fifty containers, ten services, Kafka, eight databases, and the
observability stack — comes up with a single command. Every service owns its own
database; there is no shared schema and no cross-service database access, ever.
And six shared libraries keep all ten services consistent on the things that
must be consistent: ID generation, event contracts, messaging, storage. Zero
infrastructure cost — it all runs on commodity hardware."

### SLIDE 22 — Fast where the user feels it  *(~45s)*

"Is it fast? Where it matters, yes. A price-chart read comes back at a 95th
percentile of thirty-two milliseconds — that's six and a quarter times under my
two-hundred-millisecond budget, thanks to TimescaleDB time-partitioning and a
read replica. A two-hop graph traversal is about three hundred milliseconds.
Chat first-token is under a second when warm — and where it's slower, the
latency is almost entirely the hosted language model, not our code. Our tools
themselves return in tens of milliseconds."

### SLIDE 23 — How do I know the answers are good?  *(~55s)*

"Last credibility question: how do I know the chatbot's answers are actually
good, and not just plausible? I built a two-tier evaluation using an LLM as a
judge. First, **deterministic gates** fire — did a citation point to a tool that
wasn't called, did tool scaffolding leak into the answer, does a number
contradict the data we actually retrieved? Any of those is an outright failure,
checked before anything subjective. Only then does a soft rubric score grounding,
routing, and coherence. And I validated the judge itself against my own hand
labels — Cohen's kappa of about zero-point-nine-five, well above the
zero-point-seven bar. So the automated judge agrees with a human almost all the
time."

---

## ACT 6 — DEMO + CLOSE

### SLIDE 24 — Live demo  *(~3 min — see demo-flow notes)*

"Now let me show you the real thing." *(Switch to the running platform. Follow
the demo flow — if anything stalls, cut to the backup recording without
comment.)*

> **Demo flow (target 3 min):**
> 1. Dashboard — the overload problem, made navigable *(~30s)*.
> 2. Open an entity (e.g. NVIDIA) → Intelligence tab → show the linked
>    relations / the TSMC edge in the graph *(~60s)*. This is the slide-3 payoff,
>    live.
> 3. Open chat → ask the supply-chain / exposure question → show the streaming
>    answer **with citations** → click a citation to show the source *(~75s)*.
> 4. One sentence: "Everything you just saw came through the two journeys I
>    described." *(~15s)*

### SLIDE 25 — Results against the objectives  *(~40s)*

"To summarize against my six objectives: the event-driven platform, the
cost-controlled NLP, the five user journeys, and the latency targets all passed.
The knowledge graph and the RAG chat I'm marking as *pass with a partial* — the
mechanisms are live and working, but confidence calibration and judge
generalization are honest gaps, which brings me to limitations."

### SLIDE 26 — What I'd flag honestly  *(~50s)*

"Four things I'd flag if I were reviewing this myself. Confidence isn't
calibrated yet — the formula is right, the inputs aren't. The judge is validated
against a single annotator, me — high agreement, but not inter-annotator. The
chat benchmark has real run-to-run variance because the agent plans tools at
non-zero temperature, so I read the results as patterns, not exact pass rates.
And the graph is still sparse — about thirteen percent of entities have an edge —
which improves as the corpus grows. None of these break the core idea, but
they're the honest edges of it."

### SLIDE 27 — Contributions and what's next  *(~40s)*

"To close on contributions: an open, end-to-end platform that turns
unstructured news into a queryable dependency graph; a cost-controlled NLP
pipeline; and a grounded, cited conversational layer with a reproducible
evaluation harness. Next steps are calibrating that confidence, validating the
judge with more annotators, and densifying the graph."

### SLIDE 28 — Thank you  *(~15s)*

"That's Worldview. Thank you — I'm happy to take your questions."

---

## Timing safety valves (if running long)

- **Cut first:** Slide 15 (schema evolution) can compress to one sentence.
- **Then:** Slide 18 can fold into 19.
- **Protect at all costs:** Slides 3, 10, 13, 20, and the demo. Those carry the
  thesis.
