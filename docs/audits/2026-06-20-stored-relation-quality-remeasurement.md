# Stored Relation Quality — Trustworthy Re-measurement — 2026-06-20

**Question.** The prior audit
(`docs/audits/2026-06-20-stored-relation-quality-validation.md`) reported only
**27.6% SUPPORTED** for the gpt-oss-era stored graph. A spot-check found that number
is an *unreliable pessimistic floor* for three reasons. This re-measurement fixes all
three and pins the real number, then locates exactly where the pipeline fails.

**Three fixes applied (vs the prior run):**

1. **ALL-EVIDENCE judging** — judge every distinct `relation_evidence` snippet for a
   relation, not just the single longest one; SUPPORTED if *any* snippet asserts it.
2. **Stronger, independent judge** — `Qwen/Qwen3-235B-A22B-Instruct-2507` (reasoning
   model, `reasoning_effort=low`) instead of the over-flagging budget judge
   `deepseek-ai/DeepSeek-V4-Flash`. Qwen did *not* extract these relations
   (extractor = gpt-oss-120b) → no self-preference bias.
3. **Direction conventions injected** — the canonical subject→object meaning of all 32
   predicates (read verbatim from `libs/prompts/src/prompts/extraction/deep.py` +
   `services/knowledge-graph/.../domain/enums.py`) is given to the judge so it applies
   the *same* convention the extractor was told to use, plus an explicit fairness rule
   (consortium membership / apposition / hedged verbs all count as support).

Same **382 relation_ids** re-judged → directly comparable to the 27.6% baseline.
Script: `scripts/eval/remeasure_stored_relation_quality.py`. Raw verdicts:
`/tmp/wv_remeasure_verdicts.json` (0 judge errors). Pipeline-origin diagnosis:
`/tmp/wv_origin_verdicts.json`.

---

## Headline — the real number

| Metric | Prior (Flash, 1-snippet, no conventions) | **This re-measurement (Qwen, all-evidence, conventions)** |
|---|---|---|
| **Sample / predicate-balanced support** | **27.6%** (RECENT) / 28.3% (ALL) | **36.9%** (95% CI **32.2–41.9%**) |
| **Volume-weighted support** (weighted by real predicate frequency in the 13,449-row graph) | *not computed* | **48.8%** (approx 95% CI 44.0–54.0%) |
| RECENT (gpt-oss) | 27.6% | **36.6%** (CI 30.8–42.8%) |
| OLDER (Qwen-extracted) | 29.5% | **37.4%** (CI 29.8–45.7%) |

**The trustworthy headline is ~37% predicate-balanced, ~49% volume-weighted.** The
27.6% was indeed too harsh — but the truth is **not** rosy. **Roughly half the
relations a user actually encounters are not asserted by their own evidence.** The
era gap remains statistically insignificant: the gpt-oss model switch did not move
stored quality.

Why volume-weighted (48.8%) > predicate-balanced (36.9%): the highest-frequency
predicate, `listed_on` (1,497 rows), is the *best* (86% supported), while the worst
predicates (`credit_rating`, `price_target`, `reported_revenue_of`) are rare. The
graph is better than a flat per-predicate average suggests, but still coin-flip.

---

## Full verdict breakdown (382 relations)

| | SUPPORTED | UNSUPPORTED | WRONG_DIRECTION | CO_MENTION | WRONG_PREDICATE |
|---|---|---|---|---|---|
| **ALL** | **141 (36.9%)** | 140 (36.6%) | 56 (14.7%) | 33 (8.6%) | 12 (3.1%) |
| RECENT | 89 (36.6%) | 94 | 35 | 17 | 8 |
| OLDER | 52 (37.4%) | 46 | 21 | 16 | 4 |

Pure noise (CO_MENTION + UNSUPPORTED, i.e. no real relation in the evidence): **45%**.
Note the *shape* shifted vs the prior run: CO_MENTION collapsed (44%→8.6%) because the
stronger judge correctly reclassified most "both entities co-occur" cases as outright
UNSUPPORTED, and WRONG_DIRECTION **rose** (8.1%→14.7%) because Qwen catches direction
errors the budget judge missed.

---

## Delta attribution: where did 27.6% → 36.9% come from?

The net headline gain is **+9.3 pts**, but it is a *mix* of upgrades and new catches.
Of the **51** relations that flipped NON-SUPPORTED → SUPPORTED:

| Fix | Flips it explains | Mechanism |
|---|---|---|
| **(2)+(3) Stronger judge + conventions** | **44 / 51** | Single-snippet relations (same text the Flash judge saw) that Flash wrongly flagged. 31 were CO_MENTION→SUPPORTED (Flash too strict on relation-bearing language), 7 were WRONG_DIRECTION→SUPPORTED (convention/consortium reinterpretation), 6 WRONG_PREDICATE→SUPPORTED. |
| **(1) All-evidence** | **7 / 51** | Only 37 of 382 relations have >1 distinct snippet; the extra snippets rescued 7. |

**All-evidence is the weakest of the three fixes.** Crucial empirical finding: distinct
evidence text averages only **1.18 snippets/relation** (median 1, max 8) — *not* the
~6.5 assumed. The "6.5" was an artifact of the *same* snippet being duplicated across
many `relation_evidence` rows (one relation had the identical sentence stored 141×).
**Adding evidence breadth barely helps because the breadth does not exist.**

Counterweight: the stronger judge also **downgraded 18** relations Flash had called
SUPPORTED (12 → WRONG_DIRECTION, 4 → UNSUPPORTED). So the true methodology effect is
+51 −18 = +33 net SUPPORTED. **The gain is judge quality + conventions, not evidence
breadth.**

### Concrete relations Flash mis-flagged that Qwen+conventions correctly passes

| Triple | Flash verdict | Qwen reason |
|---|---|---|
| Kennedy-Wilson `acquired_by` Fairfax | WRONG_DIRECTION | consortium incl. Fairfax acquiring Kennedy-Wilson ⇒ correct |
| Methanex `analyst_rating` Zacks | WRONG_PREDICATE | Zacks issued a rating on Methanex — convention satisfied |
| GE HealthCare `divested_from` GE Aerospace | WRONG_DIRECTION | spun off from GE ⇒ matches divested_from convention |
| NVIDIA `price_target` RBC Capital | WRONG_DIRECTION | RBC set a $250 PT on NVIDIA — convention satisfied |
| A.O. Smith `downgraded_by` JPMorgan | WRONG_DIRECTION | JPMorgan downgraded A.O. Smith — convention satisfied |
| Schlumberger `supplier_of` BP | WRONG_PREDICATE | OneSubsea JV (Schlumberger) to supply BP subsea system |

These are pure judge/convention errors in the prior audit — the stored relations were
correct all along.

---

## Failure location — where the pipeline actually breaks

### By pipeline origin (241 surviving defects, LLM-diagnosed)

| Origin | Count | Share | What it means |
|---|---|---|---|
| **EXTRACTION** | **184** | **76%** | Model invented / mis-directed / wrong-predicate / promoted a co-mention. |
| **ENTITY_RESOLUTION** | **54** | **22%** | A subject/object is the wrong or nonsensical entity for the predicate. |
| **EVIDENCE_STORAGE** | **3** | **1%** | Relation plausibly true but the stored snippet is too short to prove it. |

**This is the single most decision-relevant result.** Only **3 of 241** defects (1%)
are the evidence-storage truncation problem. **The planned "capture the full
sentence/paragraph" fix will not move the support rate** — the unsupported relations
are genuinely wrong, not under-evidenced. Manual confirmation: short-evidence
"UNSUPPORTED" cases are hallucinations, not truncations (e.g. *"Laura Gentile, a former
ESPN executive"* → stored as `Laura Gentile employs ESPN`; the sentence is complete,
the relation is fabricated and inverted).

### By verdict × origin

- **WRONG_DIRECTION (56):** 54 are EXTRACTION (the model genuinely swapped subject/object).
  Concentrated in firm-vs-company predicates: `price_target` (7), `credit_rating` (6),
  `appointed_as` (5), `downgraded_by` (5), `analyst_rating` (4). The model cannot reliably
  decide which side is the company vs the analyst/rating firm.
  - *Real defects:* `Wedbush analyst_rating Amazon` (firm as subject), `Brian Nowak
    appointed_as Morgan Stanley` (person as subject), `Motorola acquired_by D-Fend`
    (Motorola acquired D-Fend, not vice-versa).
- **UNSUPPORTED (140):** 93 EXTRACTION (hallucination), 45 ENTITY_RESOLUTION.
- **ENTITY_RESOLUTION real defects:** `American Express competes_with Dow Jones` (index
  as competitor), `Berkshire Hathaway corporate_action Stock futures`, `SpaceX
  earnings_released Investors Title Co.`, `Simply Wall St. credit_rating Salesforce`
  (a website as a rating agency), `UBS.US downgraded_by Roth Capital` (subject is the
  wrong company entirely — evidence is about Assured Guaranty). This is the same class
  as the prior audit's xAI / closed-end-fund conflation.

### Worst predicates — by support rate AND by volume of bad relations in the graph

Ranked by *estimated unsupported relations actually sitting in the 13,449-row graph*
(`frequency × (1 − support)`):

| predicate | freq | support | est. unsupported in graph |
|---|---|---|---|
| competes_with | 1,263 | 33% | **~842** |
| analyst_rating | 949 | 23% | **~730** |
| operates_in_country | 1,923 | 69% | ~592 |
| partner_of | 1,137 | 54% | ~525 |
| regulates | 586 | 18% | ~479 |
| price_target | 436 | 8% | ~402 |
| has_executive | 801 | 54% | ~370 |
| produces | 496 | 27% | ~361 |
| is_in_sector | 683 | 50% | ~342 |
| headquartered_in | 780 | 60% | ~312 |

Rock-bottom by *rate*: `credit_rating` 0%, `earnings_released` 0%, `price_target` 8%,
`corporate_action` 8%, `downgraded_by` 8%, `reported_revenue_of` 8%, `market_share_claim`
10%. These are precisely the predicates added in the recent taxonomy expansion (PLAN-0089
Lever-4) — the model was given new predicate labels it cannot apply reliably.

**Estimated total: ~6,900 of 13,449 stored relations (~51%) are unsupported by their
own evidence.** The graph is ~half noise, and the noise is almost entirely an
*extraction-quality* problem, not a storage or breadth problem.

---

## Prioritized recommendations (targeting where the model actually fails)

1. **Do NOT prioritise the evidence-storage rewrite for quality.** Only 1% of defects
   are truncation. Capturing fuller sentences is fine for UX/citations but will not
   raise the support rate. Re-allocate that effort.

2. **Fix direction on firm-vs-company predicates (highest-leverage extraction fix).**
   `price_target`, `analyst_rating`, `credit_rating`, `downgraded_by`, `appointed_as`
   together account for the bulk of WRONG_DIRECTION. Add explicit few-shot direction
   examples to `DEEP_EXTRACTION` for each (the prompt has them for `has_executive` but
   not for analyst/rating predicates), e.g. *"'Wedbush rates Amazon Buy' → subject=Amazon,
   object=Wedbush"*. A deterministic post-extraction normaliser could also auto-swap when
   the object is a known analyst/ratings firm and the subject is a known issuer.

3. **Suppress the worst new predicates until extraction is reliable.**
   `credit_rating` (0%), `earnings_released` (0%), `corporate_action` (8%),
   `market_share_claim` (10%), `reported_revenue_of` (8%) are near-pure noise. Either
   add targeted few-shots or gate them behind a higher confidence threshold / drop them
   from the live graph. They are low-volume, so removing them is cheap and immediately
   lifts perceived quality.

4. **Tighten `competes_with` / `regulates` / `produces` co-mention promotion.** These
   are high-volume and ~20–33% supported; the dominant defect is the model asserting a
   relation from mere adjacency ("intensifying competition with established chipmakers"
   → a specific `competes_with` edge). Add an explicit prompt rule: do not emit a
   relation unless a relation-bearing verb names *both* the specific subject and object.

5. **Add an entity-type guard at relation write time (entity-resolution, 22% of
   defects).** Reject relations whose object type is invalid for the predicate (index/
   currency/number as `competes_with`/`corporate_action`/`credit_rating` object; firm as
   `analyst_rating` *subject*). This is the same defect class flagged in the prior audit
   and is deterministically catchable from `canonical_entities.entity_type`.

6. **Run a small (~150) human-labelled gold set** to calibrate the Qwen judge itself —
   the 36.9%/48.8% figures rest on one strong LLM judge; a gold set would convert these
   into validated precision numbers and let you measure future extraction-prompt changes
   against ground truth rather than against a judge.

---

## Method notes / caveats

- DB access was strictly READ-ONLY: a single batched `psql` SELECT pulled all distinct
  evidence snippets for the 382 relations via the `(relation_id, evidence_date)` index
  (~19 ms/relation, partition-pruned); the script then only called DeepInfra. No writes,
  no high-concurrency scans (the postgres OOM in the prior run is avoided).
- Conventions for symmetric predicates (`competes_with`, `partner_of`) were judged
  direction-agnostic, so those never count as WRONG_DIRECTION.
- The volume-weighted CI is approximate (Wilson interval over the raw judged n, which is
  conservative — ~12 judged per predicate, not thousands). Treat 48.8% as a point
  estimate with a ±5 pt band.
- Files written: `scripts/eval/remeasure_stored_relation_quality.py`, this report,
  `/tmp/wv_remeasure_verdicts.json`, `/tmp/wv_origin_verdicts.json`. No code edited, no
  git operations.
