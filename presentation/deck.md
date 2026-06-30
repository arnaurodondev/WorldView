---
marp: true
theme: worldview-academic
paginate: true
size: 16:9
footer: 'Worldview · Thesis Defense · Arnau Rodon Comas'
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

<div class="subtitle" style="font-size:24px;line-height:1.3">An AI-Driven Financial Intelligence Platform for Market Data Aggregation and Insight Generation</div>

<div class="meta">

**Arnau Rodon Comas**
Bachelor's Thesis · Mathematical Engineering in Data Science
Universitat Pompeu Fabra · 2025–2026
Advisor: Víctor Casamayor

</div>

---

<!-- ================================================================ -->
<!-- PART 1 — DIVIDER · MOTIVATION                                     -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Part 1</div>

# The integration gap

<div class="sub">Structured and unstructured financial data never meet.</div>

---

<!-- _header: 'Part 1 · Motivation' -->
<!-- SLIDE — Two data tracks -->

## Two data tracks that never meet

<div style="display:flex;align-items:stretch;gap:18px;margin:18px 0">
  <div class="card blue-top" style="flex:1">
    <div class="tag">Structured · typed, scheduled</div>
    <div class="muted small" style="margin:8px 0 2px;font-weight:600">prices · OHLCV</div>
    <table class="mini">
      <tr><th>ticker</th><th>date</th><th>open</th><th>high</th><th>close</th></tr>
      <tr class="hl-row"><td>TSMC</td><td>06-24</td><td>102.4</td><td>105.1</td><td>104.0</td></tr>
      <tr><td>NVDA</td><td>06-24</td><td>195.2</td><td>197.0</td><td>196.3</td></tr>
    </table>
    <div class="muted small" style="margin:12px 0 2px;font-weight:600">fundamentals · TSMC</div>
    <table class="mini">
      <tr><th>metric</th><th>value</th><th>period</th></tr>
      <tr><td>revenue</td><td>$20.0B</td><td>Q2</td></tr>
      <tr><td>gross margin</td><td>53.2%</td><td>Q2</td></tr>
      <tr><td>EPS</td><td>1.48</td><td>Q2</td></tr>
    </table>
  </div>
  <div class="gap-q"><span class="qmark">?</span><span class="s">no shared key</span></div>
  <div class="card gold-top" style="flex:1">
    <div class="tag">Unstructured · prose, no schema</div>
    <div class="doc"><span class="doctype">News</span>"<mark>TSMC</mark> warns of capacity constraints amid surging AI-chip demand…" <span class="muted small">Reuters</span></div>
    <div class="doc"><span class="doctype">Filing</span>"…concentration of advanced-node capacity remains a key risk factor…" <span class="muted small">Form 20-F</span></div>
    <div class="doc"><span class="doctype">Transcript</span>"…we expect AI demand to stay strong well into next year…" <span class="muted small">Q2 earnings call</span></div>
  </div>
</div>

<p class="center muted">The same <mark>TSMC</mark> sits in every record above — yet <strong>nothing links the structured rows to the prose</strong>. That link is the integration problem.</p>

---

<!-- _class: vcenter -->
<!-- _header: 'Part 1 · Motivation' -->
<!-- SLIDE — Why integration matters: a motivating example -->

## Two kinds of risk

<div style="display:flex;align-items:center;gap:0;margin:18px 0">
  <div class="hold-region" style="flex:1">
    <div class="region-label">Direct · what you hold</div>
    <div class="noderow"><span class="gnode-sm held">NVDA</span><span class="gnode-sm held">AAPL</span><span class="gnode-sm held">MSFT</span></div>
    <p class="muted small" style="margin-top:10px">risk you can already <strong>see</strong> — once prices, news &amp; fundamentals are unified</p>
  </div>
  <div class="risk-link">
    <span class="pred">supplied_by</span>
    <span class="pred">lends_to</span>
    <span class="pred">customer_of</span>
    <span class="lk-arrow">▶</span>
    <span class="muted small" style="text-align:center">the knowledge<br>layer links them</span>
  </div>
  <div class="dep-region" style="flex:1">
    <div class="region-label">Indirect · what you depend on</div>
    <div class="noderow"><span class="gnode-sm hidden">Supplier A</span><span class="gnode-sm hidden">Foundry B</span><span class="gnode-sm hidden">Lender C</span></div>
    <p class="muted small" style="margin-top:10px">risk you <strong>can't</strong> see — companies you don't hold, but are exposed to</p>
  </div>
</div>

<div class="callout amber center">A shock in the right-hand layer still reaches your book — only a <em>linked</em> view makes that exposure visible.</div>

---

<!-- _class: vcenter -->
<!-- _header: 'Part 1 · Motivation' -->
<!-- SLIDE — Objectives & scope -->

## Objectives

<div class="grid2">
  <div>
    <div class="rung l1"><span class="name">O-1 · Event-driven platform</span><span class="tag">multi-source, decoupled</span></div>
    <div class="rung l1"><span class="name">O-2 · Tiered NLP enrichment</span><span class="tag">NER · routing · extraction</span></div>
    <div class="rung l1"><span class="name">O-3 · Live knowledge graph</span><span class="tag">confidence + decay</span></div>
  </div>
  <div>
    <div class="rung l1"><span class="name">O-4 · Hybrid multi-modal RAG</span><span class="tag">grounded, cited</span></div>
    <div class="rung l1"><span class="name">O-5 · Five user journeys</span><span class="tag">frontend</span></div>
    <div class="rung l1"><span class="name">O-6 · Validate end-to-end</span><span class="tag">coverage + latency</span></div>
  </div>
</div>

<p class="center small muted" style="margin-top:18px">Scope: open and inspectable · single-operator · thesis-scale.</p>

---

<!-- _header: 'Part 1 · Motivation' -->
<!-- SLIDE — Where Worldview sits (capability gap, incl. GraphRAG) -->

## Why isn't this already solved?

| System | Price / yr | Ingest | NLP | Linked graph | Hybrid | Cites | Open |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Bloomberg / LSEG terminal | <span class="cost-bad">$20–30k / seat</span> | <span class="y">✓</span> | <span class="y">✓</span> | <span class="y">✓</span> | <span class="y">✓</span> | <span class="p">partial</span> | <span class="n">✗</span> |
| Open RAG — LangChain / Haystack | $0 + infra | <span class="n">✗</span> | <span class="n">✗</span> | <span class="n">✗</span> | <span class="y">✓</span> | <span class="p">partial</span> | <span class="y">✓</span> |
| Finance LLMs — FinBERT / BloombergGPT | varies | <span class="n">✗</span> | <span class="n">✗</span> | <span class="n">✗</span> | <span class="n">✗</span> | <span class="n">✗</span> | <span class="p">partial</span> |
| GraphRAG | $0 + infra | <span class="n">✗</span> | <span class="p">partial</span> | <span class="p">rebuild-only</span> | <span class="y">✓</span> | <span class="p">partial</span> | <span class="y">✓</span> |
| **Worldview** | <span class="cost-good">~$50 / mo</span> | <span class="y">✓</span> | <span class="y">✓</span> | <span class="y">✓</span> | <span class="y">✓</span> | <span class="y">✓</span> | <span class="y">✓</span> |

<p class="center muted" style="margin-top:14px">The capable system already exists — it costs <em>$20–30k a seat</em> and you can't inspect it. The open systems don't integrate. Worldview delivers the <strong>integrated, inspectable</strong> capability set for <em>~$50/month</em>.</p>

<style scoped>
table { font-size: 16px; width: 100%; table-layout: fixed; }
th, td { padding: 9px 6px; text-align: center; }
th:first-child, td:first-child { width: 25%; text-align: left; }
table tr:last-child td { background-color: var(--blue-soft) !important; }
</style>

---

<!-- ================================================================ -->
<!-- PART 2 — DIVIDER · WHAT WORLDVIEW IS                              -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Part 2</div>

# What Worldview is

<div class="sub">An integrated, event-driven intelligence platform — and four contributions.</div>

---

<!-- _header: 'Part 2 · The platform' -->
<!-- SLIDE — Four contributions (C-1..C-4) -->

## Four contributions

<div class="grid2">
  <div class="card blue-top">
    <h3>C-1 · Integrated platform</h3>
    <p>Ten hexagonal services on a Kafka backbone with schema-governed contracts, a transactional outbox, and a single API gateway — boots end-to-end on one host.</p>
  </div>
  <div class="card blue-top">
    <h3>C-2 · Cost-controlled enrichment</h3>
    <p>Every article is scored for financial relevance <em>before</em> any LLM call, then routed into effort tiers. ~$10–18/month at thesis scale.</p>
  </div>
  <div class="card blue-top">
    <h3>C-3 · Live knowledge graph</h3>
    <p>Per-edge confidence accumulates with corroboration and <em>decays</em> on a per-relation timescale; every edge links back to its source passage.</p>
  </div>
  <div class="card gold-top">
    <h3>C-4 · Grounded chatbot</h3>
    <p>LLM-driven tool use over vector, full-text, graph, and structured retrieval — streamed answers with inline citations.</p>
  </div>
</div>

---

<!-- _class: vcenter -->
<!-- _header: 'Part 2 · The platform' -->
<!-- SLIDE — The system: real topology diagram -->

## Ten services on one event backbone

<div class="topo">
  <div class="topo-layer"><span class="topo-tag">access</span>
    <span class="svc"><b>Frontend</b><span class="r">Next.js</span></span><span class="ga">▸</span>
    <span class="svc gw"><b>S9 Gateway</b><span class="r">one door</span></span>
    <span class="svc"><b>S1 Portfolio</b></span>
  </div>
  <div class="topo-layer"><span class="topo-tag">data</span>
    <span class="svc"><b>S2 Mkt Ingest</b></span>
    <span class="svc"><b>S3 Market Data</b></span>
    <span class="svc"><b>S4 Content Ingest</b></span>
    <span class="svc"><b>S5 Content Store</b></span>
  </div>
  <div class="topo-bus">Kafka event backbone — services publish &amp; consume events, never call each other</div>
  <div class="topo-layer"><span class="topo-tag">intelligence</span>
    <span class="svc intel"><b>S6 NLP</b></span>
    <span class="svc intel"><b>S7 Knowledge Graph</b></span>
    <span class="svc intel"><b>S8 RAG / Chat</b></span>
    <span class="svc intel"><b>S10 Alerts</b></span>
  </div>
  <div class="arch-store">one PostgreSQL — TimescaleDB · pgvector · Apache AGE</div>
</div>

<p class="center muted">Ten services · one event spine · one store · one door. I follow <em>two journeys</em>, not a catalog of ten services.</p>

---

<!-- _class: vcenter -->
<!-- _header: 'Part 2 · The platform' -->
<!-- SLIDE — Architecture foundations (event-driven · gateway · hexagonal) -->

## Architecture foundations

<div class="found3">
  <div class="fcard blue-top">
    <h3>Event-driven</h3>
    <p>Services talk only through Kafka — never directly. One slow or failed stage never blocks another.</p>
    <div class="glyph"><span class="gb">S6</span><span class="ga">▸</span><span class="gb hot">Kafka</span><span class="ga">▸</span><span class="gb">S7</span></div>
  </div>
  <div class="fcard blue-top">
    <h3>One door</h3>
    <p>A single API gateway authenticates every request and signs the internal token backends trust.</p>
    <div class="glyph"><span class="gb">Frontend</span><span class="ga">▸</span><span class="gb hot">Gateway</span><span class="ga">▸</span><span class="gb">services</span></div>
  </div>
  <div class="fcard blue-top">
    <h3>Hexagonal layering</h3>
    <p>Same inward dependency structure in every service. Use cases test in seconds; arch tests fail the build on a violation.</p>
    <div class="glyph"><span class="gb">API</span><span class="ga">▸</span><span class="gb">App</span><span class="ga">▸</span><span class="gb hot">Domain</span><span class="ga">◀</span><span class="gb">Infra</span></div>
  </div>
</div>

---

<!-- _class: vcenter -->
<!-- _header: 'Part 2 · The platform' -->
<!-- SLIDE — Two journeys: real intelligence.png -->

## Two journeys through the system

<div class="lane gen">
  <span class="lane-tag">Generation</span>
  <div class="flow" style="margin:0;flex-wrap:nowrap">
    <div class="step">Article</div><div class="arr">▶</div>
    <div class="step">Ingest</div><div class="arr">▶</div>
    <div class="step">Enrich</div><div class="arr">▶</div>
    <div class="step gold">Graph</div>
  </div>
</div>

<div class="lane acc">
  <span class="lane-tag">Access</span>
  <div class="flow" style="margin:0;flex-wrap:nowrap">
    <div class="step">Question</div><div class="arr">▶</div>
    <div class="step">Retrieve</div><div class="arr">▶</div>
    <div class="step">Ground</div><div class="arr">▶</div>
    <div class="step gold">Answer</div>
  </div>
</div>

<div class="shared-store">one PostgreSQL — read and written by both journeys</div>

<p class="center muted">Generation continuously builds the graph; access queries it on demand. Every service sits on one of these two paths.</p>

---

<!-- ================================================================ -->
<!-- PART 3 — DIVIDER · GENERATION                                     -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Part 3</div>

# Generation: article → fact

<div class="sub">How raw text becomes a queryable, evidence-backed graph edge.</div>

---

<!-- _class: vcenter -->
<!-- _header: 'Part 3 · Generation' -->
<!-- SLIDE — Medallion lifecycle -->

## An article publishes. How does it become a fact?

<div class="flow">
  <div class="step">Raw HTML<span class="s">as fetched</span></div>
  <div class="arr">▶</div>
  <div class="step blue">Bronze<span class="s">stored, immutable</span></div>
  <div class="arr">▶</div>
  <div class="step blue">Silver<span class="s">cleaned, deduped</span></div>
  <div class="arr">▶</div>
  <div class="step blue">Enriched<span class="s">entities + relations</span></div>
  <div class="arr">▶</div>
  <div class="step gold">Knowledge graph<span class="s">evidence attached</span></div>
</div>

<p class="center muted" style="margin-top:14px">The <em>medallion lifecycle</em> — each stage adds structure; raw bytes are never thrown away.</p>

---

<!-- _header: 'Part 3 · Generation' -->
<!-- SLIDE — Ingest, then decouple -->

## Step 1 — Ingest, then decouple

<div class="twocol" style="align-items:center">
  <div>
    <div class="rung l1"><span class="name">1 · Adapter fetches</span><span class="tag">news · filings · markets</span></div>
    <div class="rung l1"><span class="name">2 · Raw content stored</span><span class="tag">object storage</span></div>
    <div class="rung l1"><span class="name">3 · Event published</span><span class="tag">→ Kafka</span></div>
  </div>
  <div style="display:flex;align-items:center;gap:14px;height:100%">
    <div class="step blue" style="text-align:center;padding:24px 22px;border-radius:3px;border:1px solid #BFD8F0;background:var(--blue-soft);font-weight:700">Kafka<span class="s">event spine</span></div>
    <span class="arr">▶</span>
    <div style="display:flex;flex-direction:column;gap:9px">
      <span class="pill">NLP</span><span class="pill">storage</span><span class="pill">graph</span><span class="pill">indexing</span>
    </div>
  </div>
</div>

<div class="callout amber"><strong>No downstream service blocks ingestion.</strong> Services react to events — if NLP is slow, ingestion never notices; the backlog drains later.</div>


---

<!-- _header: 'Part 3 · Generation' -->
<!-- SLIDE — Cost-controlled routing (C-2) -->

## Step 2 — Not every article deserves an LLM

<div class="figrow">
  <div class="fcol-txt">
    <div class="bars">
      <div class="bar-row"><div class="bar-head"><span>Medium effort</span><span class="v">56.9%</span></div><div class="bar-track"><div class="bar-fill" style="width:56.9%"></div></div></div>
      <div class="bar-row"><div class="bar-head"><span>Deep effort</span><span class="v">31.8%</span></div><div class="bar-track"><div class="bar-fill" style="width:31.8%"></div></div></div>
      <div class="bar-row"><div class="bar-head"><span>Light effort</span><span class="v">11.2%</span></div><div class="bar-track"><div class="bar-fill" style="width:11.2%"></div></div></div>
    </div>
    <p class="muted">The gate routes each article into one of four effort tiers — deep extraction is reserved for the minority that warrant it.</p>
  </div>
  <div class="fcol-txt narrow">
    <div class="card blue-top">
      <h3>The relevance gate</h3>
      <p>A small model embeds the article's <strong>title + subtitle</strong> and predicts its extraction yield — then assigns an effort tier.</p>
      <div class="glyph" style="margin-top:6px">
        <span class="gb">title + subtitle</span><span class="ga">▸</span><span class="gb hot">embed</span><span class="ga">▸</span><span class="gb">yield</span><span class="ga">▸</span><span class="gb">tier</span>
      </div>
    </div>
    <p class="center muted small" style="margin-top:12px">Runs <em>before</em> any model call.</p>
  </div>
</div>

---

<!-- _header: 'Part 3 · Generation' -->
<!-- SLIDE — The real NLP pipeline (nlp-pipeline.png) -->

## Step 3 — The enrichment pipeline

<div class="figrow">
  <div class="fcol-txt narrow">
    <div class="card" style="margin-bottom:10px"><p><strong>Closed predicate vocabulary.</strong> The model picks from a fixed relation set — it cannot invent arbitrary types, which keeps the graph canonicalisable.</p></div>
    <div class="card"><p><strong>Entity-resolution cascade.</strong> Cheapest match first: alias → ticker → fuzzy → embedding. Unresolved mentions are kept, never dropped.</p></div>
  </div>
  <div class="fcol-img">
    <div class="pipe">
      <div class="pstep">recognize entities<span class="s">GLiNER · zero-shot NER</span></div>
      <div class="pdrop">▼</div>
      <div class="pstep">route by relevance</div>
      <div class="pdrop">▼</div>
      <div class="pstep gate">◆ suppression gate<span class="s">drop low-value articles</span></div>
      <div class="pdrop">▼</div>
      <div class="pstep">embed</div>
      <div class="pdrop">▼</div>
      <div class="pstep gate">◆ novelty gate<span class="s">skip redundant articles</span></div>
      <div class="pdrop">▼</div>
      <div class="pstep">resolve → extract<span class="s">Qwen3-235B · closed vocabulary</span></div>
      <div class="pdrop">▼</div>
      <div class="pstep" style="border-color:var(--gold);color:#6f4d08">enriched fact event</div>
    </div>
  </div>
</div>

---

<!-- _header: 'Part 3 · Generation' -->
<!-- SLIDE — The fact lands in the graph (C-3) -->

## Step 4 — The fact lands in the graph

<div class="graph">
  <div class="gnode">NVIDIA</div>
  <div class="gedge"><span class="pred">supplied_by</span><div class="line"></div><span class="arrowhead">▸</span></div>
  <div class="gnode gold">TSMC</div>
</div>

<p class="center"><span class="pill">Apache AGE</span> &nbsp; <span class="pill">versioned edge</span> &nbsp; <strong>corroborated, not duplicated</strong> — 16.2 evidence rows per edge on average · 4,700+ relations on the seeded corpus.</p>

<div class="callout blue center" style="margin-top:6px"><strong>…and each entity earns a grounded description:</strong></div>

<div class="flow" style="margin-top:12px">
  <div class="step">NVIDIA's edges<br>+ evidence</div><div class="arr">▶</div>
  <div class="step blue">LLM<span class="s">grounded</span></div><div class="arr">▶</div>
  <div class="step" style="max-width:340px;font-weight:500;font-size:14px;text-align:left;line-height:1.35">"NVIDIA designs GPUs; depends on TSMC for advanced-node fabrication…" <span class="pill">[1]</span> <span class="pill">[2]</span></div><div class="arr">▶</div>
  <div class="step gold">embedded<span class="s">for retrieval</span></div>
</div>

---

<!-- _header: 'Part 3 · Generation' -->
<!-- SLIDE — Facts age, so does confidence (C-3 decay) -->

## Facts age — so does confidence

<div class="figrow">
  <div class="fcol-txt">
    <div class="graph" style="margin:2px 0 12px;justify-content:flex-start">
      <div class="gnode">NVIDIA</div>
      <div class="gedge"><span class="pred">supplied_by</span><div class="line"></div><span class="arrowhead">▸</span></div>
      <div class="gnode gold">TSMC</div>
    </div>
    <div class="card">
      <div class="muted small" style="font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">the edge record</div>
      <table class="mini">
        <tr><td>relation</td><td>supplied_by</td></tr>
        <tr><td>confidence</td><td>0.82 · decaying</td></tr>
        <tr><td>class</td><td>slow — ~2 yr half-life</td></tr>
        <tr><td>evidence</td><td>"TSMC supplies advanced nodes…" (Reuters)</td></tr>
      </table>
    </div>
  </div>
  <div class="fcol-txt narrow">
    <div class="ladder">
      <div class="rung l1"><span class="name">Permanent</span><span class="tag">incorporated_in</span></div>
      <div class="rung l2"><span class="name">Slow · ~2 yr</span><span class="tag">owns</span></div>
      <div class="rung l3"><span class="name">Medium · ~60 d</span><span class="tag">analyst_rating</span></div>
      <div class="rung l4"><span class="name">Ephemeral · ~3 d</span><span class="tag">momentum</span></div>
    </div>
    <p class="center" style="margin-top:12px"><span class="gold" style="font-family:var(--serif);font-size:30px;font-weight:600">1.0 → 0.16</span><br><span class="muted small">ephemeral edge over its half-life · Beta posterior</span></p>
  </div>
</div>

---

<!-- ================================================================ -->
<!-- PART 4 — DIVIDER · ACCESS                                         -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Part 4</div>

# Access: question → answer

<div class="sub">How a user's question becomes a grounded, cited response.</div>

---

<!-- _header: 'Part 4 · Access' -->
<!-- SLIDE — One door, typed tools -->

## One door, typed tools

<div class="callout blue" style="font-size:24px;border-radius:3px;margin-bottom:22px">💬 &nbsp;<em>"What's my exposure to TSMC?"</em></div>

<div class="flow">
  <div class="step blue">API Gateway<span class="s">the only door</span></div>
  <div class="arr">▶</div>
  <div class="step">Chat service<span class="s">classifies intent</span></div>
  <div class="arr">▶</div>
  <div class="step gold">Typed tools<span class="s">function API</span></div>
</div>

<div class="twocol" style="margin-top:8px">
  <div class="card"><h3>The model reasons; typed tools fetch</h3><p>The LLM never touches a database directly — it calls a typed tool manifest over the whole platform.</p></div>
  <div class="card blue-top"><div class="tag">security</div><p>The single gateway authenticates and signs a short-lived internal token the backends trust.</p></div>
</div>

---

<!-- _header: 'Part 4 · Access' -->
<!-- SLIDE — The retrieval loop (tool-chain.png) -->

## The retrieval loop

<div class="fan">
  <div class="fan-q">"What's my exposure to TSMC?" &nbsp;<span class="muted small">→ intent classified</span></div>
  <div class="muted small" style="margin:2px 0">▼&nbsp; the agent fans out — <strong>22 typed tools across 6 domains</strong>, in parallel</div>
  <div class="fan-row">
    <div class="fan-mod"><b>Graph</b><span class="s">dependency edges</span><span class="pill">traverse_graph</span></div>
    <div class="fan-mod"><b>Documents &amp; news</b><span class="s">vector + BM25</span><span class="pill">search_documents</span></div>
    <div class="fan-mod"><b>Market &amp; funds</b><span class="s">prices · ratios</span><span class="pill">get_fundamentals</span></div>
    <div class="fan-mod"><b>Portfolio</b><span class="s">your holdings</span><span class="pill">get_portfolio</span></div>
    <div class="fan-mod"><b>Entity intel</b><span class="s">profiles · narratives</span><span class="pill">get_entity</span></div>
  </div>
  <div class="pdrop">▼</div>
  <div class="fan-fuse">rank fusion · RRF + trust &nbsp;→&nbsp; grounded answer</div>
</div>

<p class="center muted">The model picks &amp; combines whichever modalities the question needs — results stream back over SSE.</p>

---

<!-- _class: vcenter -->
<!-- _header: 'Part 4 · Access' -->
<!-- SLIDE — Fuse, ground, cite (C-4) -->

## Grounded &amp; cited — a worked example

<div class="ex">
  <div class="ex-q">"What's my exposure to TSMC?"</div>
  <div class="ex-block">
    <div class="ex-label">retrieved</div>
    <div class="ex-rows">
      <div class="ex-row"><span class="ex-tag">graph</span>NVIDIA —supplied_by→ TSMC</div>
      <div class="ex-row"><span class="ex-tag">graph</span>TSMC —customer→ Apple · AMD · Qualcomm</div>
      <div class="ex-row"><span class="ex-tag">portfolio</span>you hold NVDA · 4.2% of book</div>
      <div class="ex-row"><span class="ex-tag">docs</span>"TSMC warns of capacity constraints…" (Reuters)</div>
      <div class="ex-row"><span class="ex-tag">docs</span>"Analysts flag NVIDIA supply-chain risk" (Bloomberg)</div>
      <div class="ex-row"><span class="ex-tag">market</span>TSMC gross margin 53% · NVDA +2.1% today</div>
    </div>
  </div>
  <div class="ex-block">
    <div class="ex-label">answer</div>
    <div class="ex-rows">
      <div class="ex-answer">You hold <strong>NVIDIA</strong> (4.2%) <span class="pill">[1]</span>, which is supplied by <strong>TSMC</strong> <span class="pill">[2]</span>. TSMC just flagged capacity constraints <span class="pill">[3]</span> and analysts are pricing supply-chain risk into NVIDIA <span class="pill">[4]</span> — an <em>indirect exposure</em> you don't hold directly.
      <div class="ex-cite">[1] portfolio · NVDA &nbsp; [2] graph edge · NVIDIA→TSMC &nbsp; [3] Reuters · Jun 24 &nbsp; [4] Bloomberg · Jun 25</div></div>
    </div>
  </div>
</div>


---

<!-- ================================================================ -->
<!-- PART 5 — DIVIDER · EVALUATION                                     -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Part 5</div>

# Evaluation

<div class="sub">Does it run, is it fast, are the answers good?</div>


---

<!-- _class: vcenter -->
<!-- _header: 'Part 5 · Evaluation' -->
<!-- SLIDE — How do I know the answers are good? (LLM-as-judge pipeline) -->

## How do I know the answers are good?

<div class="flow" style="margin:8px 0 4px">
  <div class="step">Question<span class="s">from the eval set</span></div><div class="arr">▶</div>
  <div class="step">/chat endpoint<span class="s">system under test</span></div><div class="arr">▶</div>
  <div class="step">Answer<span class="s">+ citations</span></div><div class="arr">▶</div>
  <div class="step blue">LLM judge</div>
</div>

<p class="center muted small" style="margin:2px 0">▼&nbsp; the judge scores each answer on —</p>

<div class="jbar gates"><span class="jlbl">Tier 1 · gates</span><span class="muted small">pass / fail</span> &nbsp; <span class="pill">phantom citation</span> <span class="pill">leaked scaffolding</span> <span class="pill">contradicts data</span></div>
<div class="jbar rubric"><span class="jlbl">Tier 2 · rubric</span><span class="muted small">graded 0–N</span> &nbsp; <span class="pill">grounding</span> <span class="pill">routing</span> <span class="pill">coherence</span></div>

<p class="center muted small" style="margin:4px 0">▼&nbsp; combined</p>

<div class="center"><span class="score-box">final score per answer</span></div>

---

<!-- _header: 'Part 5 · Evaluation' -->
<!-- SLIDE — Results against objectives -->

## Results against the objectives

| # | Objective | Result | Note |
|---|---|:--:|---|
| O-1 | Event-driven multi-source platform | <span class="badge pass">PASS</span> | |
| O-2 | Cost-controlled NLP (<$50/mo) | <span class="badge pass">PASS</span> | ~$10–18/mo |
| O-3 | Live graph w/ confidence + decay | <span class="badge pass">PASS</span> <span class="badge partial">PARTIAL</span> | mechanism live · calibration pending |
| O-4 | Hybrid multi-modal grounded RAG | <span class="badge pass">PASS</span> <span class="badge partial">PARTIAL</span> | modalities live · faithfulness preliminary |
| O-5 | Five end-to-end user journeys | <span class="badge pass">PASS</span> | |
| O-6 | Latency & functional coverage | <span class="badge pass">PASS</span> | chart 32 ms p95 |

---

<!-- ================================================================ -->
<!-- PART 6 — DIVIDER · DEMO & CONCLUSIONS                             -->
<!-- ================================================================ -->
<!-- _class: divider -->
<!-- _paginate: false -->

<div class="kicker">Part 6</div>

# Demo &amp; conclusions

<div class="sub">The platform, live — then where it stands.</div>

---

<!-- _class: divider -->
<!-- _paginate: false -->
<!-- _footer: '' -->
<!-- SLIDE — Demo (audience-facing placeholder; flow + backup live in the script only) -->

# Demo

---

<!-- _class: vcenter -->
<!-- _header: 'Part 6 · Demo & conclusions' -->
<!-- SLIDE — Contributions & what's next (C-1..C-4) -->

## Contributions &amp; what's next

<div class="twocol">
  <div class="panel good">
    <h3>Contributions</h3>
    <p>✓ <strong>C-1</strong> Integrated event-driven platform<br>✓ <strong>C-2</strong> Cost-controlled enrichment pipeline<br>✓ <strong>C-3</strong> Live knowledge graph w/ decaying confidence<br>✓ <strong>C-4</strong> Grounded, cited multi-modal chat</p>
  </div>
  <div class="panel" style="background:var(--gold-soft);border:1px solid #E6C98A">
    <h3 style="color:var(--gold)">What's next</h3>
    <p class="muted small" style="margin:0 0 6px">several of these close the honest gaps from the talk</p>
    <p>→ Calibrate extractor confidence — off the saturation ceiling<br>→ Inter-annotator judge validation — beyond a single labeller<br>→ Densify the graph — today only ~13% of entities carry an edge<br>→ Scale beyond one host — Kubernetes, multi-region, multi-tenant<br>→ Fold prediction-market signals into the graph</p>
  </div>
</div>

---

<!-- ================================================================ -->
<!-- SLIDE — Thank you                                                 -->
<!-- ================================================================ -->
<!-- _class: title -->
<!-- _paginate: false -->
<!-- _footer: '' -->

# Thank you

<div class="accent-line"></div>

<div class="subtitle">Questions?</div>

<div class="meta">

**Arnau Rodon Comas**
github.com/arnaurodondev/WorldView
Worldview — An AI-Driven Financial Intelligence Platform

</div>

---

<!-- ================================================================ -->
<!-- BACKUP — clean Q&A slides (not presented)                         -->
<!-- ================================================================ -->
<!-- _class: vcenter -->
<!-- _header: 'Backup · transactional outbox' -->
<!-- _paginate: false -->
<!-- _footer: '' -->

## Hard problem — the dual write

<div class="twocol">
  <div class="panel bad">
    <h3>Naïve dual write</h3>
    <div class="row"><span class="ok">✔</span> Database write</div>
    <div class="row"><span class="no">✘</span> Kafka publish fails</div>
    <div class="result">→ silent inconsistency, forever</div>
  </div>
  <div class="panel good">
    <h3>Transactional outbox</h3>
    <div class="row"><span class="ok">✔</span> Data + event in <em>one</em> DB transaction</div>
    <div class="row"><span class="ok">✔</span> Dispatcher publishes later, retries</div>
    <div class="result">→ no lost events</div>
  </div>
</div>

<div class="flow" style="margin-top:18px">
  <div class="step">write data<br>+ outbox row</div><div class="arr">▶</div>
  <div class="step">commit<span class="s">atomic</span></div><div class="arr">▶</div>
  <div class="step">dispatcher<span class="s">reads outbox</span></div><div class="arr">▶</div>
  <div class="step blue">Kafka</div>
</div>

---

<!-- _class: vcenter -->
<!-- _header: 'Backup · idempotent consumers' -->
<!-- _paginate: false -->
<!-- _footer: '' -->

## Hard problem — messages arrive twice

<div class="flow" style="margin:16px 0">
  <div class="step blue">Event <span class="pill">E123</span></div><div class="arr">▶<small>first time</small></div>
  <div class="step">Consumer<span class="s">process ✓</span></div>
</div>
<div class="flow" style="margin:24px 0">
  <div class="step bad">Event <span class="pill">E123</span> again</div><div class="arr">▶<small>re-delivered</small></div>
  <div class="step">Consumer<span class="s">checks processed IDs → no-op</span></div>
</div>

<div class="callout blue"><strong>At-least-once delivery means duplicates are normal.</strong> Idempotent consumers turn re-delivery into a no-op — never a double fact.</div>

---

<!-- _class: vcenter -->
<!-- _header: 'Backup · schema evolution' -->
<!-- _paginate: false -->
<!-- _footer: '' -->

## Hard problem — schemas change over time

<div class="twocol" style="align-items:center">
  <div class="flow" style="margin:0;flex-direction:column;gap:16px">
    <div class="step blue">Producer <span class="pill">v2</span><span class="s">adds a new field</span></div>
    <div class="arr" style="transform:rotate(90deg)">▶</div>
    <div class="step">Consumer <span class="pill">v1</span><span class="s">still works — field has a default</span></div>
    <div><span class="badge pass">forward compatible</span></div>
  </div>
  <div class="card">
    <h3>The rules</h3>
    <p><span style="color:var(--green);font-weight:800">✔</span> Add fields with defaults<br><span style="color:var(--red);font-weight:800">✘</span> Never remove fields<br><span style="color:var(--red);font-weight:800">✘</span> Never rename fields</p>
    <p class="muted">Versioned event envelope + Avro schemas, validated in the registry.</p>
  </div>
</div>

---

<!-- _class: vcenter -->
<!-- _header: 'Backup · distributed system + latency' -->
<!-- _paginate: false -->
<!-- _footer: '' -->

## A real distributed system, on one machine

<div class="metrics">
  <div class="metric blue"><div class="num">~50</div><div class="lbl">application processes</div></div>
  <div class="metric blue"><div class="num">8</div><div class="lbl">logical databases<br>(one PostgreSQL cluster)</div></div>
  <div class="metric blue"><div class="num">6</div><div class="lbl">shared libraries</div></div>
</div>

<div class="bars" style="margin-top:12px">
  <div class="bar-row"><div class="bar-head"><span>Price chart <span class="pill">/ohlcv</span></span><span class="v gold">32 ms p95</span></div><div class="bar-track"><div class="bar-fill gold" style="width:16%"></div></div></div>
  <div class="bar-row"><div class="bar-head"><span>Graph traversal (depth-2)</span><span class="v">305 ms p95</span></div><div class="bar-track"><div class="bar-fill" style="width:40%"></div></div></div>
  <div class="bar-row"><div class="bar-head"><span>Chat first token (cached)</span><span class="v">924 ms p95</span></div><div class="bar-track"><div class="bar-fill" style="width:64%"></div></div></div>
</div>

<p class="center muted" style="margin-top:10px">Database-per-service · $0 infrastructure · boots with one command. Our code answers in tens of ms; chat latency is the <em>external LLM</em>.</p>

---

<!-- _class: vcenter -->
<!-- _header: 'Backup · confidence & decay' -->
<!-- _paginate: false -->
<!-- _footer: '' -->

## Confidence — accumulate, decay, contradict

<div class="grid2">
  <div class="card blue-top"><h3>Accumulate</h3><p>Each independent observation raises confidence with <em>diminishing returns</em> — a Beta posterior, not a counter.</p></div>
  <div class="card blue-top"><h3>Decay</h3><p>Evidence is down-weighted on a per-predicate timescale — six decay classes, permanent through ephemeral.</p></div>
  <div class="card blue-top"><h3>Contradict</h3><p>Conflicting evidence <em>demotes</em> within a bounded range — it never erases a well-supported edge.</p></div>
  <div class="card"><h3>Half-life by class</h3><p><span class="pill">incorporated_in</span> permanent · <span class="pill">owns</span> ~2 yr · <span class="pill">analyst_rating</span> ~60 d · <span class="pill">momentum</span> ~3 d</p></div>
</div>

<div class="callout amber center">The decay class comes from the relation <em>type</em> (a registry), not the LLM — the LLM only emits the per-evidence confidence.</div>

---

<!-- _class: vcenter -->
<!-- _header: 'Backup · entity-resolution cascade' -->
<!-- _paginate: false -->
<!-- _footer: '' -->

## Entity resolution — cheapest match first

<div class="flow">
  <div class="step">mention<span class="s">"NVIDIA"</span></div><div class="arr">▶</div>
  <div class="step">alias<span class="s">exact</span></div><div class="arr">▶</div>
  <div class="step">ticker<span class="s">NVDA</span></div><div class="arr">▶</div>
  <div class="step">fuzzy<span class="s">string sim</span></div><div class="arr">▶</div>
  <div class="step blue">embedding<span class="s">nearest canonical</span></div>
</div>

<div class="callout blue center">Each step runs only if the cheaper ones miss. Unresolved mentions are kept as <strong>anchors</strong> for extraction — never silently dropped.</div>

---

<!-- _header: 'Backup · full service topology' -->
<!-- _paginate: false -->
<!-- _footer: '' -->

## Full service topology

<div class="fig">
  <img src="../thesis/diagrams/topology.png" alt="Full Worldview service topology" />
  <div class="figcap">Reference diagram from the thesis — every service, contract, and external boundary.</div>
</div>
