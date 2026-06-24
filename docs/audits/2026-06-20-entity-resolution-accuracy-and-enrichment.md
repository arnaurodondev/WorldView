# Entity-Resolution Accuracy & Extraction-Prompt Enrichment (#2)

**Date:** 2026-06-20
**Type:** Read-only investigation (no code changes)
**Question:** Should the extraction prompt's entity allow-list be enriched with **canonical entity
detail** (ticker, entity_type, short description) for resolved mentions — and for which entities?
**Decision context:** Enhancement #2 (canonical detail) vs Enhancement #1 (GLiNER `mention_class`
type label, prototyped separately).

---

## TL;DR / Recommendation

- **Resolution is correct ~91% overall** (86/95 judged), but accuracy is **stage-dependent and the
  errors are exactly the kind that would mislead the model if injected.**
  - Stage 1 (exact): **100%** (25/25)
  - Stage 2 (ticker): **80%** (20/25) — *the worst stage, and the source of the known xAI conflation*
  - Stage 3 (fuzzy): **92%** (23/25)
  - Stage 4 (ANN): **90%** (18/20) — but negligible volume (37 rows total in prod)
- **The known xAI failure is a STAGE-2 (ticker) error, not fuzzy/ANN.** The mention `xAI`
  (Elon Musk's company) resolves **67 times** via stage 2 to *"XAI Octagon Floating Rate &
  Alternative Income Trust"* — a closed-end fund — because stage 2 uppercases any ≤6-char surface
  and matches it as a ticker. The original hypothesis (errors cluster in fuzzy/ANN) is **wrong**:
  the dangerous conflations cluster in **stage 2 ticker collisions**.
- **Canonical detail coverage is thin and partly noisy:** only **10%** of entities have a ticker,
  **13%** have a description, and **~46% of those descriptions are useless** (23% are the name
  echoed verbatim, 23% are <40 chars). Genuine descriptions average **~400 chars** — heavy for
  prompt injection.
- **Recommendation:** **Do a NARROW, gated version of #2 — inject `entity_type` + `ticker` only,
  and only for stage-1 / stage-3+ resolutions, explicitly EXCLUDING the bare-ticker stage-2 path
  unless `len(surface) > 2` and the case matches.** Do **not** inject the free-text `description`
  (noisy, long, low coverage). **#1 (mention_class) is the higher-value, zero-risk win and should
  ship first**; #2's marginal value over #1 is modest and bounded by the 10% ticker / 13% desc
  coverage. Ship #1 unconditionally; ship #2 only as `entity_type`+`ticker`, gated, as a follow-up.

---

## 1. Resolution Accuracy

### Method
- Sampled 95 resolved mentions from `nlp_db.entity_mentions` (`resolved_entity_id IS NOT NULL`),
  stratified by `resolution_stage` (1=exact, 2=ticker, 3=fuzzy, 4=ANN), most-recent first.
- Joined each to its `intelligence_db.canonical_entities` row (name, type, ticker, description).
- Judged each (mention surface + GLiNER class) vs (canonical name/type/ticker/desc) with an
  independent judge — `Qwen/Qwen3-235B-A22B-Instruct-2507` on DeepInfra, `reasoning_effort=low`,
  `temperature=0` — verdict CORRECT / WRONG / UNSURE.

### Production stage distribution (all resolved mentions)
| stage | meaning | rows | % | avg conf |
|------:|---------|-----:|----:|---------:|
| 1 | exact | 101,190 | 63% | 1.000 |
| 2 | ticker | 39,760 | 25% | 0.934 |
| 3 | fuzzy | 19,311 | 12% | 0.863 |
| 4 | ANN | 37 | ~0% | 0.731 |

Stage 4 (ANN) is effectively unused in production (37 rows) — its accuracy is statistically
irrelevant. The mass of resolutions is stage 1 (exact, perfect) and stage 2 (ticker, the weak link).

### Judged accuracy
| stage | n | CORRECT | WRONG | acc (decided) |
|------:|--:|--------:|------:|--------------:|
| 1 exact | 25 | 25 | 0 | **100%** |
| 2 ticker | 25 | 20 | 5 | **80%** |
| 3 fuzzy | 25 | 23 | 2 | **92%** |
| 4 ANN | 20 | 18 | 2 | **90%** |
| **overall** | **95** | **86** | **9** | **91%** |

### The 9 wrong resolutions — two distinct error classes
**(a) Genuine wrong-referent (would actively MISLEAD the model) — all stage 2/3:**
- `Citi` → **Citi Trends Inc** (stage 2) — different company (a discount retailer, not Citigroup)
- `WTI futures` → **Colgate-Palmolive (CL)** (stage 3) — oil contract resolved to a consumer-goods firm
- `General Instrument` → fund w/ ticker **GOOGL**, type `unknown` (stage 4)
- **`xAI` → XAI Octagon Floating Rate & Alternative Income Trust** (stage 2; 67 occurrences in prod)

**(b) Type-label nuance / same real-world entity (judge flagged on `entity_type` mismatch, but the
referent is correct):**
- `UBS` (financial_institution) → **UBS.US** (financial_instrument, ticker UBS) — same bank
- `Microsoft` → **Microsoft shares** (financial_instrument) — same company, the equity row
- `Reuters` → **Thomson Reuters (TRI)** — effectively the same org
- `Regal Rexnord Corporation` → **Regal Rexnord** (financial_instrument) — same company

> **Key implication:** the type-label "errors" in class (b) are why injecting the canonical
> `entity_type` is *helpful, not harmful* — the canonical `financial_instrument` label is actually
> the more precise tradable-entity label. The genuine danger is class (a), which is concentrated in
> the **bare-uppercase-ticker stage-2 path**.

### Root cause of the stage-2 collisions
`entity_resolution.py::_stage2_ticker_isin` treats **any uppercase surface ≤6 chars as a ticker**
(`ticker = text if text.isupper() and len(text) <= 6 else None`). `xAI` uppercases to `XAI`, which
is a real fund ticker → deterministic mis-resolution at confidence 0.93. These collisions are the
single most dangerous input for #2: high stated confidence, wrong referent.

---

## 2. Canonical-Detail Coverage & Quality

`intelligence_db.canonical_entities` — **25,057 rows**:
| field | coverage |
|-------|---------:|
| entity_type (always set) | 25,057 (100%) |
| ticker non-empty | 2,553 (**10%**) |
| description non-empty | 3,329 (**13%**) |

**Entity-type distribution (top):** organization 7,036 · person 6,945 · financial_instrument 5,221
(2,330 with ticker — tickers live almost entirely here) · unknown 2,396 · place 2,176 · index 521.

**Description quality (of the 3,329 that have one):**
- **758 (23%)** are the canonical name echoed verbatim (`description == name`) — zero signal.
- **768 (23%)** are <40 chars — mostly name fragments.
- Remaining ~46% are genuine prose but **median ~412 chars, p90 ~514 chars** — too long to inject
  per-entity into an already-large extraction prompt.
- Some genuine descriptions are *ambiguous/generic* and would mislead (e.g. `Lee` →
  "a South Korean surname commonly associated with...Samsung and Hyundai").

**Conclusion on detail quality:**
- `entity_type` — **100% coverage, clean, 1 token** → safe and cheap to inject.
- `ticker` — **10% coverage**, clean where present, deterministic → safe, useful where it exists.
- `description` — **13% coverage, ~46% noise, long, occasionally misleading** → **not safe / not
  worth the tokens** for prompt injection in its current state.

---

## 3. Recommendation for #2 (and ranking vs #1)

### What #1 and #2 actually plug into
The allow-list is built in `deep_extraction.py::_run_extraction_window`:
`mention_names = list(dict.fromkeys(m.mention_text for m in mentions))` → joined into the
`{entities}` slot of `DEEP_EXTRACTION` (libs/prompts) as a flat comma-separated string of surfaces.
- **#1** annotates each surface with its GLiNER `mention_class` (always present on every mention,
  *never wrong* — it is the detector's own type, not a resolution). Zero lookup, ~1 token/entity.
- **#2** would annotate *resolved* surfaces with `canonical_entities` detail, requiring a batch
  lookup of `resolved_entity_id`s at prompt-build time and risking propagation of resolution errors.

### Recommendation
1. **Ship #1 first, unconditionally.** It is the always-available, never-wrong type label, costs ~1
   token/entity and one no-op (the data is already on the mention), and gives the model the same
   type signal #2 would — *without* any dependency on resolution correctness or canonical coverage.
   This is the dominant, zero-risk win.

2. **Ship #2 only as a NARROW, GATED follow-up:**
   - **Inject `entity_type` and `ticker` only. Do NOT inject `description`** (13% coverage, ~46%
     noise, ~400-char median, occasionally misleading).
   - **Gate on resolution stage/confidence:**
     - **Always safe:** stage 1 (exact, 100% accurate).
     - **Safe enough:** stage 3 (fuzzy, 92%) and stage 4 (ANN, 90% but ~0 volume).
     - **DANGEROUS — exclude or harden:** stage 2 (ticker, 80%) is where the genuine wrong-referent
       conflations live (xAI, Citi). Either (a) **exclude stage-2 ticker resolutions from #2**, or
       (b) only inject for stage-2 hits whose surface is **not a bare uppercase ≤6-char token** (the
       exact collision pattern) — i.e. require `len(surface) > 2 and surface == canonical ticker`.
   - **Also gate `confidence`** as a backstop (e.g. skip injection below ~0.90) — though note the
     xAI error has conf 0.93, so confidence alone is insufficient; the *stage-2 ticker path* is the
     real discriminator.
   - Because `entity_type` is the only high-coverage field and #1 already supplies a type label,
     #2's incremental value is mostly the **`ticker` disambiguator on the ~10% of entities that have
     one** (e.g. tells the model `Apple → AAPL` so it groups "Apple" / "Apple Inc." / "AAPL"). This
     is real but modest.

3. **#2 vs #1 ranking:** **#1 > #2.** #1 delivers ~80% of the type-signal benefit at 0% risk and 0
   lookup cost. #2 adds a ticker disambiguator only where coverage exists (10%) and only after
   you've built the stage-2 exclusion gate to avoid re-injecting the xAI-class errors. Treat #2 as a
   *small, optional, gated enhancement on top of #1*, not a substitute for it. **Do not inject the
   description field at all** until canonical descriptions are cleaned (drop name-echoes, cap length,
   filter generic/ambiguous bios).

### Suggested injected shape (if #2 is built)
Per resolved, gated entity, append a compact tag — e.g.:
`Apple Inc. [type=financial_instrument, ticker=AAPL]` — and leave unresolved / stage-2-bare-ticker
surfaces as plain text (exactly as today). No `description`.

---

## Appendix — Queries & artifacts
- Stage distribution: `nlp_db.entity_mentions GROUP BY resolution_stage` (101190/39760/19311/37).
- Coverage: `intelligence_db.canonical_entities` (25057 total; 2553 ticker; 3329 desc; 758 name-echo).
- xAI conflation: `mention_text ILIKE 'xai'` → 67× stage-2 → `XAI Octagon...Trust`
  (entity_id `86631568-cbc9-4f4a-a4c8-db9a14bbd57f`).
- Stage-2 root cause: `entity_resolution.py::_stage2_ticker_isin`,
  `ticker = text if text.isupper() and len(text) <= 6 else None`.
- Judge: Qwen3-235B-A22B-Instruct-2507, reasoning_effort=low, temp=0, 95 samples, 9 WRONG.
