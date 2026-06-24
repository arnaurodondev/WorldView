---
marp: true
theme: worldview-light
paginate: true
size: 16:9
footer: 'Worldview — Final Thesis Defense · Arnau Rodon Comas'
---

<!-- ================================================================ -->
<!-- SLIDE 1 — Title                                                   -->
<!-- ================================================================ -->
<!-- _class: title -->
<!-- _paginate: false -->
<!-- _footer: '' -->

<svg width="0" height="0"></svg>

# Worldview

<div class="accent-line"></div>

<div class="subtitle">An Open Financial Intelligence Platform</div>

<div class="meta">

**Arnau Rodon Comas**
Bachelor's Thesis · Mathematical Engineering in Data Science
Universitat Pompeu Fabra · 2025–2026
Advisor: Víctor Casamayor

</div>

---

<!-- ================================================================ -->
<!-- ACT 1 — DIVIDER                                                   -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Act 1</div>

# The problem

<div class="sub">Financial intelligence fails when signals are not <em>linked</em>.</div>

---

<!-- SLIDE 2 — One portfolio, too many signals -->

## One portfolio, too many signals

<div class="cards cols-4">
  <div class="card blue-top"><div class="tag">Prices</div><p>OHLCV, intraday moves</p></div>
  <div class="card blue-top"><div class="tag">Fundamentals</div><p>earnings, margins, ownership</p></div>
  <div class="card blue-top"><div class="tag">News</div><p>thousands of items a week</p></div>
  <div class="card blue-top"><div class="tag">Filings</div><p>regulatory, analyst reports</p></div>
</div>

<div class="metrics">
  <div class="metric"><div class="num">~3,000</div><div class="lbl">news items per week<br>for a 30-position portfolio</div></div>
  <div class="metric blue"><div class="num">1</div><div class="lbl">analyst<br>can't read that</div></div>
</div>

<p class="center muted">Four signal streams, per company — multiplied across the whole book.</p>

---

<!-- SLIDE 3 — The risk you don't see  (PROTECTED — main hook) -->

## The risk you don't see

<p class="lead">The risk is often <strong>not</strong> the company you hold —<br>it's the company <em>it depends on</em>.</p>

<div class="graph">
  <div class="gnode" style="border-color:var(--red);background:var(--red-soft)">Supplier A<br><span class="small muted" style="font-weight:500">disruption</span></div>
  <div class="gedge"><span class="pred">supplies</span><div class="line"></div><span class="arrowhead">▶</span></div>
  <div class="gnode">Manufacturer B</div>
  <div class="gedge"><span class="pred">you hold</span><div class="line"></div><span class="arrowhead">▶</span></div>
  <div class="gnode gold">Your portfolio</div>
</div>

<div class="callout amber center"><strong>Hidden exposure:</strong> A never appears in your holdings — yet its shock reaches you.</div>

---

<!-- SLIDE 4 — Why isn't this already solved? -->

## Why isn't this already solved?

| Platform | Cost / year | Open | Conversational | Linked graph |
|---|---|:--:|:--:|:--:|
| Bloomberg / LSEG | <span class="hl">$20–30k / seat</span> | — | ✗ | partial |
| FinBERT + vector DB | $0 | ✓ | ✗ | ✗ |
| BloombergGPT | closed | ✗ | ✗ | ✗ |
| **Worldview** | **$0 infra · <$50/mo** | ✓ | ✓ | ✓ live |

<p class="center muted" style="margin-top:18px">The systems that <em>link</em> everything are locked behind terminal pricing.<br>The open systems <em>don't link</em> anything.</p>

<!-- highlight Worldview row -->
<style scoped>
table tr:last-child td { background-color: var(--blue-soft) !important; }
</style>

---

<!-- ================================================================ -->
<!-- ACT 2 — DIVIDER                                                   -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Act 2</div>

# What Worldview does

<div class="sub">Turn market signals into <em>linked, cited</em> intelligence.</div>

---

<!-- SLIDE 5 — Three things, end to end -->

## Three things, end to end

<div class="cards cols-4">
  <div class="card blue-top">
    <div class="numbadge">1</div>
    <h3>Ingest</h3>
    <p>Market data, news, filings, fundamentals — many providers, decoupled.</p>
  </div>
  <div class="card blue-top">
    <div class="numbadge">2</div>
    <h3>Link</h3>
    <p>A knowledge graph of entities and relations, each fact with confidence that <em>decays</em>.</p>
  </div>
  <div class="card gold-top">
    <div class="numbadge">3</div>
    <h3>Answer</h3>
    <p>A grounded chatbot that <strong>cites every claim</strong> in a real source.</p>
  </div>
</div>

<div class="callout blue center">Open-source · commodity hardware · <strong>&lt;$50/month</strong> in external APIs</div>

---

<!-- SLIDE 6 — The system: 10 services on one event backbone -->

## The system: 10 services on one event backbone

<div class="flow" style="margin:14px 0 6px">
  <div class="step">Data<br>providers<span class="s">5 sources</span></div>
  <div class="arr">▶</div>
  <div class="step blue">Kafka backbone<span class="s">event spine</span></div>
  <div class="arr">▶</div>
  <div class="step">Service groups<span class="s">ingest · NLP · graph · chat</span></div>
  <div class="arr">▶</div>
  <div class="step gold">Frontend<span class="s">one app</span></div>
</div>

<div class="metrics" style="margin-top:10px">
  <div class="metric blue"><div class="num">10</div><div class="lbl">backend services</div></div>
  <div class="metric blue"><div class="num">8</div><div class="lbl">databases<br>(one per service)</div></div>
  <div class="metric blue"><div class="num">6</div><div class="lbl">shared libraries</div></div>
</div>

<p class="center small muted">Database-per-service · no service calls another directly · full topology in appendix</p>

---

<!-- SLIDE 7 — Two journeys, not ten services -->

## Two journeys, not ten services

<div class="twocol">
  <div class="panel good">
    <h3>① Generation</h3>
    <div class="flow" style="margin:14px 0">
      <div class="step">Article</div><div class="arr">▶</div>
      <div class="step">Extract</div><div class="arr">▶</div>
      <div class="step gold">Graph</div>
    </div>
    <p class="muted center">An article becomes a fact.</p>
  </div>
  <div class="panel" style="background:var(--gold-soft);border:1px solid #E6C98A">
    <h3 style="color:var(--gold)">② Access</h3>
    <div class="flow" style="margin:14px 0">
      <div class="step">Question</div><div class="arr">▶</div>
      <div class="step">Retrieve</div><div class="arr">▶</div>
      <div class="step gold">Cite</div>
    </div>
    <p class="muted center">A question becomes a grounded answer.</p>
  </div>
</div>

<p class="center muted" style="margin-top:14px">Every service appears <em>when it matters</em> — not as a catalog.</p>

---

<!-- ================================================================ -->
<!-- ACT 3 — DIVIDER                                                   -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Act 3 · Trace 1</div>

# From an article to a fact

<div class="sub">How raw text becomes a queryable graph edge.</div>

<div class="miniflow">
  <span class="m">Raw HTML</span><span class="a">▶</span>
  <span class="m">Cleaned text</span><span class="a">▶</span>
  <span class="m">Extracted relation</span><span class="a">▶</span>
  <span class="m">Graph edge</span>
</div>

---

<!-- SLIDE 8 — An article publishes. How does it become a fact? -->

## An article publishes. How does it become a fact?

<div class="flow" style="margin:40px 0">
  <div class="step">Raw HTML<span class="s">as fetched</span></div>
  <div class="arr">▶</div>
  <div class="step blue">Bronze<span class="s">stored</span></div>
  <div class="arr">▶</div>
  <div class="step blue">Silver<span class="s">cleaned</span></div>
  <div class="arr">▶</div>
  <div class="step blue">Enriched<span class="s">entities + relations</span></div>
  <div class="arr">▶</div>
  <div class="step gold">Knowledge graph<span class="s">evidence attached</span></div>
</div>

<p class="center muted">The <em>medallion lifecycle</em> — each stage adds structure, nothing is thrown away.</p>

---

<!-- SLIDE 9 — Step 1 — Ingest, then decouple -->

## Step 1 — Ingest, then decouple

<div class="twocol">
  <div>
    <div class="rung l1"><span class="name">1 · Adapter fetches</span><span class="tag">news · filings · markets</span></div>
    <div class="rung l1"><span class="name">2 · Raw content stored</span><span class="tag">object storage</span></div>
    <div class="rung l1"><span class="name">3 · Event published</span><span class="tag">→ Kafka</span></div>
  </div>
  <div style="display:flex;align-items:center;gap:14px;height:100%">
    <div class="step blue" style="text-align:center;padding:24px 22px;border-radius:12px;border:1px solid #BFD8F0;background:var(--blue-soft);font-weight:700">Kafka<span class="s">event spine</span></div>
    <span class="arr">▶</span>
    <div style="display:flex;flex-direction:column;gap:9px">
      <span class="pill">NLP</span><span class="pill">storage</span><span class="pill">graph</span><span class="pill">indexing</span>
    </div>
  </div>
</div>

<div class="callout blue"><strong>No downstream service blocks ingestion.</strong> No service calls another directly — they react to events.</div>

---

<!-- SLIDE 10 — Hard problem #1 — the dual write  (PROTECTED) -->

## Hard problem #1 — the dual write

<div class="twocol">
  <div class="panel bad">
    <h3>Naïve dual write</h3>
    <div class="row"><span class="ok">✓</span> Database write</div>
    <div class="row"><span class="no">✗</span> Kafka publish fails</div>
    <div class="result">→ silent inconsistency, forever</div>
  </div>
  <div class="panel good">
    <h3>Transactional outbox</h3>
    <div class="row"><span class="ok">✓</span> Data + event in <em>one</em> DB transaction</div>
    <div class="row"><span class="ok">✓</span> Dispatcher publishes later, retries</div>
    <div class="result">→ no lost events</div>
  </div>
</div>

<div class="flow" style="margin:16px 0 0">
  <div class="step">write data<br>+ outbox row</div><div class="arr">▶</div>
  <div class="step">commit<span class="s">atomic</span></div><div class="arr">▶</div>
  <div class="step">dispatcher</div><div class="arr">▶</div>
  <div class="step blue">Kafka</div>
</div>

---

<!-- SLIDE 11 — Step 2 — Not every article deserves an LLM -->

## Step 2 — Not every article deserves an LLM

<div class="twocol" style="align-items:center">
  <div>
    <div class="flow" style="margin:0 0 22px;justify-content:flex-start">
      <div class="step">Articles</div><div class="arr">▶</div>
      <div class="step blue">Relevance gate<span class="s">scores each article</span></div>
    </div>
    <div class="bars">
      <div class="bar-row"><div class="bar-head"><span>Medium effort</span><span class="v">56.9%</span></div><div class="bar-track"><div class="bar-fill" style="width:56.9%;background:#5C93C9"></div></div></div>
      <div class="bar-row"><div class="bar-head"><span>Deep effort</span><span class="v">31.8%</span></div><div class="bar-track"><div class="bar-fill" style="width:31.8%;background:#2F6FB0"></div></div></div>
      <div class="bar-row"><div class="bar-head"><span>Light effort</span><span class="v">11.2%</span></div><div class="bar-track"><div class="bar-fill" style="width:11.2%;background:#9CC3E8"></div></div></div>
    </div>
  </div>
  <div>
    <div class="metric"><div class="num">~$10–18</div><div class="lbl">hosted inference / month<br>(well under the $50 ceiling)</div></div>
    <p class="center muted small" style="margin-top:18px">6,955 articles over 30 days.<br><em>Cost control is a routing decision.</em></p>
  </div>
</div>

---

<!-- SLIDE 12 — Step 3 — Extract entities and relations -->

## Step 3 — Extract entities and relations

<div class="flow" style="margin:18px 0">
  <div class="step">Article sentence</div><div class="arr">▶</div>
  <div class="step blue">LLM extraction</div><div class="arr">▶</div>
  <div class="step gold" style="font-size:22px">NVIDIA <span style="color:var(--gold)">—supplied_by→</span> TSMC</div>
</div>

<div class="cards" style="margin-top:8px">
  <div class="card blue-top"><h3>Closed predicate vocabulary</h3><p>The model picks from a fixed relation set — it can't invent arbitrary types.</p></div>
  <div class="card blue-top"><h3>Entity-resolution cascade</h3>
    <p><span class="pill">alias</span> → <span class="pill">ticker</span> → <span class="pill">fuzzy</span> → <span class="pill">embedding</span> — cheapest check first.</p>
  </div>
</div>

<p class="center muted small" style="margin-top:10px">Every triple keeps its <em>evidence sentence</em>.</p>

---

<!-- SLIDE 13 — Step 4 — The fact lands in the graph  (PROTECTED) -->

## Step 4 — The fact lands in the graph

<div class="twocol" style="align-items:center">
  <div>
    <div class="graph" style="justify-content:flex-start">
      <div class="gnode">NVIDIA</div>
      <div class="gedge"><span class="pred">supplied_by</span><div class="line"></div><span class="arrowhead">▶</span></div>
      <div class="gnode gold">TSMC</div>
    </div>
    <div style="display:flex;gap:8px;margin-top:18px">
      <span class="pill">versioned edge</span><span class="pill">Apache AGE</span><span class="pill">corroborated, not duplicated</span>
    </div>
  </div>
  <div class="center">
    <div class="evstack"><div class="metric" style="border:none;box-shadow:none;padding:6px"><div class="num">16.2</div><div class="lbl">evidence rows<br>per edge, on average</div></div></div>
  </div>
</div>

<div class="callout amber center" style="margin-top:22px">The hidden dependency from Slide 3 is now <strong>queryable</strong>.</div>

---

<!-- SLIDE 14 — Hard problem #2 — messages arrive twice -->

## Hard problem #2 — messages arrive twice

<div class="flow" style="margin:24px 0">
  <div class="step blue">Event <span class="pill">E123</span></div><div class="arr">▶<small>first time</small></div>
  <div class="step">Consumer<span class="s">process ✓</span></div>
</div>
<div class="flow" style="margin:24px 0">
  <div class="step bad">Event <span class="pill">E123</span> again</div><div class="arr">▶<small>re-delivered</small></div>
  <div class="step">Consumer<span class="s">checks processed IDs → no-op</span></div>
</div>

<div class="callout blue"><strong>At-least-once delivery means duplicates are normal.</strong> Idempotent consumers turn re-delivery into a no-op — never a double fact.</div>

---

<!-- SLIDE 15 — Hard problem #3 — schemas change over time -->

## Hard problem #3 — schemas change over time

<div class="twocol" style="align-items:center">
  <div class="flow" style="margin:0;flex-direction:column;gap:16px">
    <div class="step blue">Producer <span class="pill">v2</span><span class="s">adds a new field</span></div>
    <div class="arr" style="transform:rotate(90deg)">▶</div>
    <div class="step">Consumer <span class="pill">v1</span><span class="s">still works — field has a default</span></div>
    <div><span class="badge pass">forward compatible</span></div>
  </div>
  <div class="card">
    <h3>The rules</h3>
    <div class="row" style="display:flex;gap:8px;margin:8px 0"><span class="ok" style="color:var(--green);font-weight:800">✓</span> Add fields with defaults</div>
    <div class="row" style="display:flex;gap:8px;margin:8px 0"><span class="no" style="color:var(--red);font-weight:800">✗</span> Never remove fields</div>
    <div class="row" style="display:flex;gap:8px;margin:8px 0"><span class="no" style="color:var(--red);font-weight:800">✗</span> Never rename fields</div>
    <p class="muted small" style="margin-top:12px">Versioned event envelope + Avro schemas.</p>
  </div>
</div>

---

<!-- SLIDE 16 — Facts age — so does confidence -->

## Facts age — so does confidence

<div class="twocol" style="align-items:center">
  <div class="ladder">
    <div class="rung l1"><span class="name">Permanent</span><span class="tag">incorporated_in</span></div>
    <div class="rung l2"><span class="name">Slow · ~2 yr</span><span class="tag">owns / acquired</span></div>
    <div class="rung l3"><span class="name">Medium · ~60 d</span><span class="tag">analyst_rating</span></div>
    <div class="rung l4"><span class="name">Ephemeral · ~3 d</span><span class="tag">intraday_momentum</span></div>
  </div>
  <div class="center">
    <svg viewBox="0 0 320 200" width="340" height="200">
      <line x1="40" y1="20" x2="40" y2="170" stroke="#C7D2E2" stroke-width="1.5"/>
      <line x1="40" y1="170" x2="300" y2="170" stroke="#C7D2E2" stroke-width="1.5"/>
      <path d="M40,28 C110,55 170,140 300,162" fill="none" stroke="#2F6FB0" stroke-width="3"/>
      <circle cx="40" cy="28" r="6" fill="#A9760B"/>
      <text x="52" y="26" font-size="15" fill="#A9760B" font-weight="700">1.000</text>
      <circle cx="300" cy="162" r="6" fill="#586781"/>
      <text x="232" y="158" font-size="15" fill="#586781" font-weight="700">0.165</text>
      <text x="150" y="192" font-size="13" fill="#586781">time →</text>
    </svg>
    <p class="muted small">Beta posterior + class-specific half-life</p>
  </div>
</div>

<div class="callout amber"><strong>Honest limit:</strong> on seeded data confidence saturates near 1.0 — the extractor emits a near-constant score, so absolute <em>calibration is still pending</em>.</div>

---

<!-- ================================================================ -->
<!-- ACT 4 — DIVIDER                                                  -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Act 4 · Trace 2</div>

# From a question to a grounded answer

<div class="sub">How the user gets a <em>cited</em> response.</div>

<div class="miniflow">
  <span class="m">Question</span><span class="a">▶</span>
  <span class="m">Tools</span><span class="a">▶</span>
  <span class="m">Retrieved context</span><span class="a">▶</span>
  <span class="m">Answer + citations</span>
</div>

---

<!-- SLIDE 17 — What's my exposure to TSMC? -->

## "What's my exposure to TSMC?"

<div class="callout blue" style="font-size:24px;border-radius:14px;margin-bottom:22px">💬 &nbsp;<em>"What's my exposure to TSMC?"</em></div>

<div class="flow" style="margin:10px 0">
  <div class="step blue">API Gateway<span class="s">the only door</span></div><div class="arr">▶</div>
  <div class="step">Chat service<span class="s">classifies intent</span></div><div class="arr">▶</div>
  <div class="step gold">Typed tools<span class="s">function API</span></div>
</div>

<div class="cards" style="margin-top:14px">
  <div class="card"><h3>The model reasons; typed tools fetch.</h3><p>The LLM never touches a database directly.</p></div>
  <div class="card blue-top"><div class="tag">security</div><p>Single gateway authenticates and signs a trusted internal token.</p></div>
</div>

---

<!-- SLIDE 18 — Four ways to retrieve, in parallel -->

## Four ways to retrieve, in parallel

<div class="grid2">
  <div class="card blue-top"><h3>Graph traversal</h3><p>Follow dependency edges &nbsp;<span class="pill">traverse_graph</span></p></div>
  <div class="card blue-top"><h3>Hybrid document search</h3><p>Vector + keyword, merged &nbsp;<span class="pill">search_documents</span></p></div>
  <div class="card blue-top"><h3>Structured lookups</h3><p>Prices, fundamentals &nbsp;<span class="pill">get_fundamentals</span></p></div>
  <div class="card blue-top"><h3>Entity intelligence</h3><p>Profiles, contradictions &nbsp;<span class="pill">get_entity</span></p></div>
</div>

<div class="callout blue center"><strong>rank fusion</strong> — the agent combines modalities per question, then fuses results by rank</div>

---

<!-- SLIDE 19 — Fuse → ground → cite -->

## Fuse → ground → cite

<div class="flow" style="margin:18px 0;flex-wrap:nowrap">
  <div class="step">Intent</div><div class="arr">▶</div>
  <div class="step blue">Tools fired<span class="s">graph · docs · funds</span></div><div class="arr">▶</div>
  <div class="step">Rank fusion<span class="s">RRF</span></div><div class="arr">▶</div>
  <div class="step">Grounded<br>generation</div><div class="arr">▶</div>
  <div class="step gold">Answer + <span class="pill">[1]</span><span class="pill">[2]</span></div>
</div>

<div class="twocol" style="margin-top:14px">
  <div class="card"><p>The model writes the answer <strong>only from retrieved context</strong> — every claim carries a citation that resolves to a real source chunk.</p></div>
  <div class="panel bad"><h3>🛡 Phantom-citation gate</h3><p style="color:#7a2f2c">A <span class="pill">[n]</span> pointing to a tool that was never called is <strong>rejected</strong>.</p></div>
</div>

---

<!-- SLIDE 20 — The payoff: surfacing the hidden link  (PROTECTED) -->

## The payoff: surfacing the hidden link

<div class="twocol" style="align-items:center;grid-template-columns:1.15fr 0.85fr">
  <div>
    <div class="callout blue" style="margin-bottom:14px"><em>"What's my exposure to TSMC?"</em></div>
    <div class="graph" style="justify-content:flex-start">
      <div class="gnode" style="font-size:20px;padding:12px 18px">You</div>
      <div class="gedge" style="min-width:90px"><span class="pred small">holds</span><div class="line"></div><span class="arrowhead">▶</span></div>
      <div class="gnode" style="font-size:20px;padding:12px 18px">B</div>
      <div class="gedge" style="min-width:110px"><span class="pred small">supplied_by</span><div class="line"></div><span class="arrowhead">▶</span></div>
      <div class="gnode gold" style="font-size:20px;padding:12px 18px">TSMC</div>
    </div>
    <p class="muted" style="margin-top:14px">Paths ranked by <em>surprising</em> <strong>and</strong> <em>reliable</em> — real cross-sector bridges, not tautologies.</p>
  </div>
  <div class="center">
    <div class="hero-num">0 / 20</div>
    <div class="hero-lbl">top-ranked paths flagged<br>as noise (manual review)</div>
  </div>
</div>

---

<!-- ================================================================ -->
<!-- ACT 5 — DIVIDER                                                  -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Act 5</div>

# Does it actually run?

<div class="sub">Infrastructure credibility, latency, and evaluation.</div>

---

<!-- SLIDE 21 — A real distributed system, on one machine -->

## A real distributed system, on one machine

<div class="metrics">
  <div class="metric blue"><div class="num">~50</div><div class="lbl">containers</div></div>
  <div class="metric blue"><div class="num">8</div><div class="lbl">databases</div></div>
  <div class="metric blue"><div class="num">6</div><div class="lbl">shared libraries</div></div>
</div>

<div class="flow" style="margin:18px 0 10px">
  <div class="step gold"><span class="pill">make dev</span></div><div class="arr">▶</div>
  <div class="step">services + Kafka<br>+ databases + observability</div>
</div>

<div class="cards" style="margin-top:8px">
  <div class="card blue-top"><h3>Database per service</h3><p>No shared schema · no cross-service DB access.</p></div>
  <div class="card gold-top"><h3>$0 infrastructure</h3><p>Commodity hardware, open-source throughout.</p></div>
</div>

---

<!-- SLIDE 22 — Fast where the user feels it -->

## Fast where the user feels it

<div class="bars" style="margin-top:10px">
  <div class="bar-row">
    <div class="bar-head"><span>Price chart &nbsp;<span class="pill">/ohlcv</span></span><span class="v gold">32 ms p95</span></div>
    <div class="bar-track"><div class="bar-fill gold" style="width:16%"></div></div>
  </div>
  <div class="bar-row">
    <div class="bar-head"><span>Graph traversal (depth-2)</span><span class="v">305 ms p95</span></div>
    <div class="bar-track"><div class="bar-fill" style="width:33%"></div></div>
  </div>
  <div class="bar-row">
    <div class="bar-head"><span>Chat first token (cached)</span><span class="v">924 ms p95</span></div>
    <div class="bar-track"><div class="bar-fill" style="width:60%"></div></div>
  </div>
</div>

<div class="metrics" style="margin-top:6px">
  <div class="metric"><div class="num">6.25×</div><div class="lbl">under the chart budget</div></div>
  <div class="metric blue" style="flex:2"><div class="num" style="font-size:30px;padding-top:10px">mostly the hosted LLM</div><div class="lbl">chat latency is external, not our code</div></div>
</div>

---

<!-- SLIDE 23 — How do I know the answers are good? -->

## How do I know the answers are good?

<div class="twocol" style="grid-template-columns:1.3fr 0.7fr;align-items:center">
  <div>
    <div class="panel bad" style="margin-bottom:14px">
      <h3>🛡 Tier 1 — deterministic gates <span class="small" style="color:#7a2f2c">(fire first)</span></h3>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
        <span class="pill">phantom citation</span><span class="pill">leaked scaffolding</span><span class="pill">contradicts retrieved data</span>
      </div>
    </div>
    <div class="panel good">
      <h3>Tier 2 — soft rubric</h3>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
        <span class="pill">grounding</span><span class="pill">routing</span><span class="pill">coherence</span>
      </div>
    </div>
  </div>
  <div class="center">
    <div class="hero-num">κ ≈ 0.95</div>
    <div class="hero-lbl">judge vs. my hand labels<br>(bar was ≥ 0.70)</div>
  </div>
</div>

---

<!-- ================================================================ -->
<!-- ACT 6 — DIVIDER / DEMO                                           -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Act 6</div>

# Live demo

<div class="sub">~3 minutes · video backup ready</div>

<div class="miniflow">
  <span class="m">Dashboard</span><span class="a">▶</span>
  <span class="m">Entity graph</span><span class="a">▶</span>
  <span class="m">Cited chat answer</span>
</div>

---

<!-- SLIDE 25 — Results against the objectives -->

## Results against the objectives

| # | Objective | Result | Note |
|---|---|:--:|---|
| O-1 | Event-driven multi-source platform | <span class="badge pass">PASS</span> | |
| O-2 | Cost-controlled NLP (&lt;$50/mo) | <span class="badge pass">PASS</span> | ~$10–18/mo |
| O-3 | Live graph w/ confidence + decay | <span class="badge partial">PARTIAL</span> | calibration pending |
| O-4 | Hybrid multi-modal grounded RAG | <span class="badge partial">PARTIAL</span> | quality bounded |
| O-5 | Five end-to-end user journeys | <span class="badge pass">PASS</span> | |
| O-6 | Latency & functional coverage | <span class="badge pass">PASS</span> | chart 32 ms p95 |

---

<!-- SLIDE 26 — What I'd flag honestly -->

## What I'd flag honestly

<div class="grid2">
  <div class="card" style="border-left:4px solid var(--amber)">
    <h3>Confidence calibration</h3>
    <p>Formula is live and correct — but the extractor emits a near-constant score, so absolute values aren't trustworthy yet.</p>
  </div>
  <div class="card" style="border-left:4px solid var(--amber)">
    <h3>Single-annotator judge</h3>
    <p>κ ≈ 0.95 is high, but against <em>my</em> labels — no inter-annotator gold set.</p>
  </div>
  <div class="card" style="border-left:4px solid var(--amber)">
    <h3>Benchmark variance</h3>
    <p><strong>~43%</strong> of questions flip verdict across runs — the agent plans tools at non-zero temperature. Read as patterns, not exact rates.</p>
  </div>
  <div class="card" style="border-left:4px solid var(--amber)">
    <h3>Sparse graph</h3>
    <p>Only <strong>~13%</strong> of entities carry an edge — coverage grows with corpus size.</p>
  </div>
</div>

---

<!-- SLIDE 27 — Contributions & what's next -->

## Contributions & what's next

<div class="twocol">
  <div class="panel good">
    <h3>Contributions</h3>
    <div class="row">✓ Open, end-to-end financial intelligence platform</div>
    <div class="row">✓ News-to-graph dependency extraction</div>
    <div class="row">✓ Cost-controlled NLP pipeline</div>
    <div class="row">✓ Grounded, cited RAG chat</div>
    <div class="row">✓ Reproducible evaluation harness</div>
  </div>
  <div class="panel" style="background:var(--gold-soft);border:1px solid #E6C98A">
    <h3 style="color:var(--gold)">Next</h3>
    <div class="row">→ Calibrate extractor confidence</div>
    <div class="row">→ Inter-annotator judge validation</div>
    <div class="row">→ Densify the graph</div>
    <div class="row">→ Cost counterfactual vs. fully-local stack</div>
  </div>
</div>

---

<!-- SLIDE 28 — Thank you -->
<!-- _class: title -->
<!-- _paginate: false -->
<!-- _footer: '' -->

# Thank you

<div class="accent-line"></div>

<div class="subtitle">Questions?</div>

<div class="meta">

**Arnau Rodon Comas**
github.com/arnaurodondev/WorldView
Worldview — An Open Financial Intelligence Platform

</div>
