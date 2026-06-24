# CIKM 2026 Industry Day — Event Analysis & Worldview Positioning Strategy

> **Compiled**: 2026-06-22 (web-verified against official CIKM 2025/2026 pages, SIGWEB conference reports, ACM DL)
> **Target**: CIKM 2026 Industry Day Talk — Rome, Industry Day **7 Nov 2026** (conference 7–11 Nov)
> **Deadline**: **29 Jun 2026, 23:59 AoE** (postponed from 22 Jun) · Notification ~3–7 Aug · Camera-ready 20 Aug
> **What you submit**: 2-page ACM `sigconf` talk proposal, non-anonymous, via EasyChair track "CIKM 2026 Industry Day"

---

## 1. What CIKM is (and is not)

- **35th edition**, running since 1992. Sponsored by ACM SIGIR + SIGWEB. **CORE Rank A** (one tier below the A* trio SIGIR/KDD/WWW; equal to WSDM).
- Unites three communities: **Information Retrieval + Databases + Knowledge Management**. Modern framing: "all topics in data science, foundational + applied."
- **Large and growing**: CIKM 2025 (Seoul) = 1,436 in-person attendees, 46 countries, 2,890 submissions, 870 accepted. Main-track acceptance ~23–27%.
- **Unusually applied** for an A-tier venue: it runs BOTH an Applied Research Paper track AND a full-day Industry Day, and has a fintech-friendly sponsor base.

### Two industry-facing venues — don't conflate them
| | Applied Research Papers | **Industry Day Talks ← our target** |
|---|---|---|
| Submit | 7-page full paper | **2-page proposal** |
| Review | Peer-reviewed, single-blind | Curated by Industry Day chairs |
| Archival | Full paper in ACM DL | **Abstract** published in proceedings |
| Deployment rule | Deployment + post-launch metrics **or desk-reject** | Softer — "realistic evaluation + clear path to deployment" OK |
| Deadline | 23 May 2026 (PASSED) | **29 Jun 2026** |

The Applied Research deadline already passed and its "deployed-with-post-launch-metrics-or-desk-reject" rule is a hard fit problem for a thesis project. **Industry Day is the right, and still-open, door.**

---

## 2. Who attends / who decides

- **Industry Day Co-Chairs (our reviewers)**: **Edgar Meij (Bloomberg)** + **Tracy Holloway King (Adobe)**.
  - Meij = IR / knowledge-graph / entity-linking researcher in the **finance** domain (Bloomberg). A financial KG + RAG system is directly his wheelhouse.
  - King = search-quality / computational linguistics leader (Adobe).
  - **This is close to a best-case reviewer draw for Worldview.**
- **Program Chairs** include **Vanessa Murdock (Amazon)**; General Chairs Antonella Poggi (Sapienza) + Nicola Ferro (Padova).
- **Corporate presence**: Amazon (Diamond sponsor, very heavy paper presence), Microsoft, Alibaba/Taobao, Baidu, LinkedIn, Tencent, plus fintech sponsors **Bloomberg, Turing, Clearwater Analytics, FinVolution**.

---

## 3. What gets presented — patterns from 2022–2025

**Recurring Industry Day / Applied themes, most → least common:**
1. Recommendation systems (dominant)
2. E-commerce search & product discovery
3. Advertising / CTR / ad-creative generation
4. **LLMs in production + RAG** — the clear *rising* theme (2024→2025)
5. Neural / dense retrieval at scale
6. **Fraud / financial-crime detection** (strong secondary cluster — mostly graph/GNN)
7. Spatio-temporal / logistics
8. **Knowledge graphs / entity linking** — present but usually a *supporting* technique, rarely the headline

**Concrete 2023 Industry Day talk titles (the best-documented year):**
- "Proactive and Automatic Detection of Product Misclassifications at Massive Scale" — Amazon
- "Unleashing the Power of LLMs for Legal Applications" — (likely Thomson Reuters)
- "Harnessing GPT for Topic-Based Call Segmentation in Dynamics 365 Sales" — Microsoft
- "Vigil: End-to-End Monitoring for Large-Scale Recommender Systems" — Glance

**Selection signal (identical wording every year):**
> "CIKM is a technical conference, so preference will be given to talks describing **applied research and technical challenges rather than product presentations**."

What they reward: real problem + significance, **design tradeoffs**, **what did NOT work**, scale/data/privacy/regulation challenges, **metrics**, lessons learned. The only named negative is "product presentations / pitches."

---

## 4. The whitespace — why Worldview is distinctive

- Finance content at CIKM 2022–2025 is **dominated by Chinese payment/e-commerce fraud-GNN work** (Tencent, Meituan, Ant). **Almost no Western market-intelligence / financial-KG systems.**
- No confirmed Bloomberg/JPMorgan/Visa CIKM industry paper in-window. **Financial KG + market-intelligence RAG is genuinely under-represented at CIKM.**
- Yet it sits squarely in the **rising LLM/RAG/KG-in-production** theme AND is chaired in 2026 by a Bloomberg finance-KG researcher.
- **Net: under-served niche + hot method + ideal reviewer = strong differentiation** against a field of recommendation/ads papers.

---

## 5. CIKM 2026 themes Worldview maps onto (verbatim topic areas)

Strongest overlaps (cite these explicitly in the "Relevance" section):
- **Information Access and Retrieval** — RAG, *generation of knowledge graphs from unstructured data*, QA/dialogue ← core of Worldview
- **Agentic AI for Information and Knowledge Tasks** — tool use, planning, multi-agent orchestration ← multi-agent RAG chat
- **Trustworthy and Responsible AI** — hallucination detection/mitigation, **factuality and grounding, attribution** ← citation-grounding + judge
- **Evaluation** — benchmarks, **LLM-as-judge**, reproducibility ← CHAT_QUALITY_JUDGE v2 eval framework
- **Special / Mining Multi-Modal Content** — knowledge extraction, KG representations ← GLiNER NER + LLM relation extraction
- **Applications: business**

**Industry Day themes** (must show relevance to these too): deployed systems; system design & scalability; **production metrics & measurement**; practical challenges (data/privacy/integrity/scale/regulation); domain-specific learnings; **academia↔industry crossover** (explicitly invites student/academic talks).

---

## 6. How to frame Worldview as competitively as possible

### Positioning one-liner
> "A deployed, citation-grounded financial knowledge-graph + multi-agent RAG platform — and the production lessons from running KG extraction, retrieval grounding, and LLM-as-judge evaluation at thesis-grade scale."

### The 3 framing rules
1. **Applied research, NOT a product pitch.** Never sell features. Lead with a *technical problem* and the *engineering tradeoffs* you made. The word "platform" is fine; the word "solution/launch/customers" reads as a pitch — avoid.
2. **Show what didn't work.** The CFP explicitly rewards failure lessons. Worldview has gold here: the all-green/zero-output eval bug class, extraction silent-drop on entity-ref mismatch, GLiNER thread-thrashing, KG promoter O(n²) density blowups, prompt input/lookup mismatch. Pick 1–2 as honest "here's what bit us in production" moments — this is exactly the texture they want and what large-company talks usually can't share candidly.
3. **Quantify.** Bring concrete metrics: extraction precision/support numbers, relation-cap effects, the eval-framework deltas (e.g. fabrication 1.83→0.17 with news-grounding), latency/throughput on the live pipeline. Even realistic-evaluation numbers count.

### Candidate talk angle (pick ONE — don't spread thin)
- **A (recommended): "Grounding a Financial Knowledge Graph for RAG: extraction, validation gates, and LLM-as-judge evaluation in production."** Hits the most 2026 themes (KG-from-unstructured + RAG + trustworthy/grounding + evaluation), plays to Meij directly, and the whitespace is widest here.
- **B: "What we learned shipping a multi-agent financial RAG assistant"** — agentic AI theme; good but more crowded.
- **C: "Deterministic precision gates for LLM relation extraction"** — narrow/deep; strong "what didn't work" + metrics story, but less headline reach.

### Title craft
Concrete + technical + domain-specific beats grand. Mirror the 2023 talk style ("Proactive and Automatic Detection of … at Massive Scale"). Include "production" or "deployed," "financial/market," and the method ("knowledge graph," "RAG," "LLM-as-judge").

### 2-page structure to write
1. **Title + abstract** (problem + why it matters + what the audience learns)
2. **The applied problem & context** (market-intelligence from news at scale; why KG+RAG; the real constraints)
3. **System design & key tradeoffs** (KG on Postgres+AGE+pgvector; GLiNER+LLM extraction; multi-agent RAG; one architecture sentence per layer)
4. **What broke & what we learned** (1–2 concrete production failures + fixes)
5. **Evaluation & metrics** (eval framework v2, judge methodology, grounding deltas)
6. **Relevance to CIKM 2026 themes & topics** (explicit bullet mapping — this is a *stated* selection signal)
7. **Speaker bio + speaker details** (non-anonymous; doesn't count to 2 pages)
8. **GenAI Usage Disclosure** (required by general submission policy; doesn't count to limit)

### Logistics to plan now
- **In-person required** in Rome — no pre-recorded talks. Budget travel + ≥1-day registration. Confirm your supervisor/department can fund or co-fund.
- Talk is **15–20 min incl. Q&A**.
- Verify notification date discrepancy (Industry Day page says 3 Aug; Important Dates says 7 Aug).

---

## 7. Open risks / things to verify
- Registration fee schedule not yet published.
- Industry Day talk acceptance rate is not published (curated, not a numeric quota) — relevance + technical depth are the levers.
- Confirm whether you must avoid double-submission tension with EMNLP Demo / REALM (different content framings, so likely fine, but the EMNLP Demo paper and this proposal should be clearly distinct artifacts).

---

## Sources
- CIKM 2026 Industry Day Talks — https://cikm2026.diag.uniroma1.it/industry-day-talks/
- CIKM 2026 Important Dates — https://cikm2026.diag.uniroma1.it/important-dates/
- CIKM 2026 Full Research CFP (topic list) — https://cikm2026.diag.uniroma1.it/full-research-papers/
- CIKM 2026 Applied Research CFP — https://cikm2026.diag.uniroma1.it/applied-research-papers/
- CIKM 2026 organization/chairs — https://cikm2026.diag.uniroma1.it/scientific-chairs/
- CIKM 2025 Industry Day Talks call — https://cikm2025.org/calls/industry-day-talks
- CIKM 2025 conference report — http://www.cs.emory.edu/~jyang71/files/cikm2025report.pdf
- CIKM 2024 conference report (SIGWEB) — https://fgullo.github.io/files/papers/SIGWEBNewsl25.pdf
- CIKM 2023 Industry Day talk list (ELRA) — https://list.elra.info/mailman3/hyperkitty/list/corpora@list.elra.info/thread/G7Z776PZRLG3QFUBBRYCAQWWS5PFS4PJ/
- CORE portal (CIKM rank) — https://portal.core.edu.au/conf-ranks/25/
- EasyChair submission — https://easychair.org/my/conference?conf=cikm26
