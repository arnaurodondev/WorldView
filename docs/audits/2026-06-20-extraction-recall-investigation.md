# Extraction Recall Root-Cause Investigation (2026-06-20)

**Context.** In the model-switch A/B (`results/model_switch_ab/`), **recall was the lowest
quality dimension** for the new extraction model: `openai/gpt-oss-120b@medium` scored
**recall 3.8 / 5** vs precision 5.0 and adherence 5.0; the old Qwen3-235B scored recall 3.6.
"Recall" = did extraction capture the events/claims/relations a careful analyst would
extract from the article. This report root-causes the recall gap with quantified evidence
from the A/B artefacts plus a small live re-extraction probe.

> **Scope correction (important).** The judge's RECALL rubric
> (`scripts/eval/extraction_quality_eval.py` §B, lines 618-623) scores **events + claims +
> relations together**, not relations in isolation. So the headline "recall 3.8" is a
> *combined* coverage score, not a pure relation-extraction-recall metric. This materially
> changes the diagnosis: most of what drags recall down is **missed claims**, not missed
> relations.

---

## Headline result

Across the 20 `gpt-oss-120b@medium` arm articles there were **24 missed items** total
(the judge's `missed_items` counts). Classifying every one of them by type:

| Missed-item type | Count | Share |
|---|---:|---:|
| **claim** (financial figures, ratings, TSR, guidance, qualitative facts) | **16** | **67%** |
| relation | 4 | 17% |
| event | 3 | 12% |
| event attribute (a date the event omitted) | 1 | 4% |

**The dominant recall leak is missed CLAIMS, not missed relations.** Two-thirds of every
recall penalty in the A/B is the model declining to emit a `claim` for a clearly-stated
fact (e.g. "1/3/5-yr total shareholder returns 4.03%/23.15%/25.09%", "Zacks Rank #4 (Sell)",
"EPS guidance ~$19.15", "Truist reiterated a Buy rating", "$325M price + 9.65% stake").
The relation-extraction subsystem is actually in good shape — only **4 of 24** misses were
relations, and two of those four are not real recall bugs at all (see below).

---

## Per-cause verdict (confirm / refute)

### CAUSE #1 — Entity allow-list bottleneck (GLiNER NER ceiling) — **CONFIRMED, dominant relation-cause**

Relation extraction can only emit a relation whose **both** endpoints are in the `{entities}`
allow-list (= `entity_mentions.mention_text` from GLiNER; the golden set assembles this
exactly as production does — `assemble_golden_set`, lines 264-322). If GLiNER misses an
entity, every relation touching it is unreachable — a hard recall ceiling.

Of the 4 relation misses, **2 are caused by an off-list endpoint (50%)**:

- **`019ede68-892`** (Thai-language "My ENet" launch): allow-list = `ENet, My ENet` only.
  **`Mavenir` is absent from the allow-list but present in the text.** The judge flagged a
  missed `ENet–Mavenir partnership`. The *same article in 4 other languages*
  (`019ede68-a11` zh, `-9ac` de, `-94c` de, English variants) **did** have `Mavenir`
  on-list and **did** capture the partnership. This is a concrete **GLiNER multilingual
  NER-recall gap**: the Thai (and Indonesian `-65b`, Chinese `-a73`) renderings lost the
  vendor entity, collapsing the allow-list to 2 items.
- **`019ede3b-3bb`** (Kardigan): missed "trades under symbol **KARD**" — `KARD` is off-list
  (and also has no predicate; see Cause #3). Marginal: tickers are rarely KG node entities.

**Live proof (probe H-B).** Re-running the Thai article with `Mavenir` repaired into the
allow-list (`ENet, My ENet, Mavenir`) **immediately produced the missed relation**:
`ENet --partner_of--> Mavenir` (n_relations 1 → 2). The relation was suppressed *purely*
because GLiNER didn't surface Mavenir in Thai — not by the prompt or the model.

> The Thai/Indonesian/Chinese variants all show **entity_count = 2-4** vs 4 for the German
> variant of the same story — a measurable multilingual NER coverage drop.

### CAUSE #2 — Precision-tuned v1.6 prompt over-suppressing — **REFUTED (not in play)**

The brief hypothesises a v1.6 prompt with a strict RELATION ASSERTION TEST + aggressive
CO-MENTION-IS-NOT-A-RELATION rules. **That prompt was not used in this A/B.** The deployed
template is **`DEEP_EXTRACTION` v1.5** (`libs/prompts/src/prompts/extraction/deep.py:9`,
`version="1.5"`) and the harness renders that exact template
(`_render_extraction_prompt` → `DEEP_EXTRACTION.render`, lines 372-380). There is **no
co-mention-suppression block and no "RELATION ASSERTION TEST"** anywhere in v1.5
(`grep` returns nothing). So over-suppression by a precision-tuned prompt cannot explain
this A/B's recall. (If a v1.6 with those rules is later deployed, it should be re-evaluated —
but it is not the current cause.)

### CAUSE #3 — Closed predicate vocabulary — **CONFIRMED (minor, but real)**

v1.5 ships ~38 predicates (lines 41-79). There is **no predicate for index membership**
("added to / is a member of S&P 500", `member_of_index` / `added_to_index`):

- **`019ede63-6f0`** (Marvell): missed "Marvell is set to join the **S&P 500** on June 22".
  Both endpoints (`Marvell Technology`, `S&P 500`) ARE on the allow-list — so this is **not**
  an allow-list miss; it is a **predicate gap**. In the live re-run the model visibly tried
  to force-fit it: it emitted `Marvell Technology --corporate_action--> S&P 500` — a
  semantically wrong predicate, evidence the model *wanted* to express the fact but had no
  correct slot. Under v1.5's "pick the closest match, no other values allowed" instruction
  the model otherwise drops such facts.

Impact is small (1 clear relation, ~marginal others) but it is a clean, low-risk fix.

### CAUSE #4 — `reasoning_effort=medium` under-enumerates → raise it — **REFUTED, and raising it is HARMFUL**

The config comment (`services/nlp-pipeline/src/nlp_pipeline/config.py:155`) calls medium
"validated optimal". Scrutinising that against the recall evidence:

- "Optimal" there meant the precision/latency/fabrication balance (recall was only 3.62 in
  that audit — i.e. *medium was never recall-optimal*, it was the best overall tradeoff).
- **Raising effort to `high` breaks extraction entirely.** Probe result: on every one of the
  4 worst articles, `@high` returned **`status=json_error`**. Direct inspection of the raw
  call: `tokens_out = 8192` (the full cap) with **`content_len = 0`** — the reasoning model
  spent its entire budget on hidden chain-of-thought and emitted **empty content**. This is
  exactly the empty-output failure mode the config docstring already warns about
  (lines 151-154). So higher reasoning_effort does not lift recall; it zeroes the output.

`reasoning_effort` is therefore **not a recall lever** — leave it at medium.

### CAUSE #5 — Windowing loses cross-window relations — **REFUTED (impossible here)**

`deep_extraction.py` splits only articles **> 24,000 tokens** (`SINGLE_WINDOW_TOKEN_LIMIT`,
line 68). The **largest** article in the entire golden set is **1,165 words (~1.6k tokens)** —
every article fits in a single window. **No article in this A/B was multi-window**, so
windowing contributes exactly zero to the recall gap.

---

## Ranked root causes

| Rank | Cause | Scope | Evidence | Severity |
|---|---|---|---|---|
| **1** | **Missed CLAIMS** (model is conservative about emitting `claim` items for stated facts/figures/ratings) | **67% of all misses (16/24)** | judge justifications: TSR, Zacks rank, EPS guidance, "reiterated Buy", $325M/9.65%, fair-value narratives, iOS/Android, MDE platform | **Dominant** |
| **2** | **GLiNER allow-list ceiling** (esp. multilingual NER drop) | 50% of relation misses (2/4); the Thai/Indo/zh "My ENet" cluster | H-B probe: adding `Mavenir` → partnership appears; entity_count 2 vs 4 across language variants | High (for relations) |
| **3** | **Predicate vocabulary gap** (no index-membership predicate) | 1 clear relation (Marvell→S&P 500) | both endpoints on-list yet dropped; model force-fit `corporate_action` | Minor |
| — | v1.6 over-suppression | n/a | v1.5 deployed; no co-mention rule exists | Not a cause |
| — | reasoning_effort too low | n/a | `@high` → empty content (tokens_out=8192, content_len=0) | Not a fix (harmful) |
| — | windowing | n/a | max article 1,165 words ≪ 24k-token threshold | Not a cause |

**Dominant vs minor:** the single biggest recall lever is **claim coverage** (#1), followed
by **NER coverage** for relations (#2). The predicate gap (#3) is real but marginal. The
three brief-suggested mechanisms most likely to be "tried first" (raise reasoning_effort,
loosen the precision prompt, fix windowing) are all **non-causes** here.

---

## Recommendations (prioritised, low-risk, precision-preserving)

Precision is currently 5.0 / fabrication ~0; every change below is additive coverage with a
guardrail so it cannot regress precision.

1. **Lift claim recall via the prompt (highest leverage, no model/infra change).**
   v1.5's claim guidance is thin relative to its rich relation few-shots. Add a short
   **"CLAIMS — extract these when explicitly stated"** checklist enumerating the high-value
   claim types the judge repeatedly flags as missed: analyst rating / rating change
   ("reiterated Buy", "Zacks Rank #4"), price target value, EPS/revenue **guidance** figures,
   total-shareholder-return / period-return figures, and named risk factors. Mirror the
   existing few-shot style (1-2 correct examples). Keep the existing verbatim-evidence and
   confidence-floor rules so precision holds. **This directly targets 67% of the misses.**
   Re-run `scripts/eval/extraction_quality_eval.py` on the frozen golden set to confirm
   recall ↑ and precision flat before/after (this is a new prompt **version**, e.g. v1.7 —
   bump `version=` + CHANGELOG per libs/prompts policy).

2. **Close the GLiNER multilingual NER gap (highest leverage for *relations*).**
   The Thai/Indonesian/Chinese "My ENet" variants dropped `Mavenir` while the German/English
   ones kept it. Two complementary, low-risk options:
   - Verify GLiNER is invoked with multilingual labels/threshold tuning on non-English text;
     the per-language entity_count drop (2 vs 4 for the same story) is the smoking gun.
   - As a backstop, **union the relevance/routing entities (e.g. the article's watchlist /
     resolved tickers) into the allow-list** so a known subject like Mavenir is never absent
     even when GLiNER misses it in a low-resource language. This is additive and cannot
     introduce off-list violations (the strings are canonical).
   Validate with the H-B style probe (`scripts/eval/recall_probe_2026_06_20.py`).

3. **Add an index-membership predicate (cheap, closes Cause #3).**
   Add `member_of_index` (or `added_to_index`) to the v1.5/next predicate list with a
   one-line description + example ("Marvell joins the S&P 500" → subject=company,
   object=index). Update the controlled-vocabulary enum the adherence checker uses so it
   stays in lock-step. Marginal recall gain, zero precision risk.

4. **Do NOT raise `reasoning_effort`.** Confirmed harmful (`@high` → empty output). Leave at
   `medium`. If anyone proposes it for recall, point them at the probe evidence.

5. **Do NOT touch windowing for recall.** Irrelevant at current article sizes.

### Suggested validation loop
Re-run the existing harness on the frozen golden set after #1-#3:
`python scripts/eval/extraction_quality_eval.py run …` then judge, and compare aggregate
recall vs precision deltas. Target: recall ≥ 4.3 with precision still ≥ 4.9 and
fabricated_items ≈ 0.

---

## Artefacts referenced
- A/B data: `results/model_switch_ab/{judge_scores,golden_set,model_runs}.json`
- Prompt (deployed): `libs/prompts/src/prompts/extraction/deep.py` (v1.5)
- Harness / judge rubric: `scripts/eval/extraction_quality_eval.py` (§B recall, lines 618-623; allow-list assembly 264-322)
- Windowing constants: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py:68-69`
- reasoning_effort config claim: `services/nlp-pipeline/src/nlp_pipeline/config.py:150-167`
- Live probe (this investigation): `scripts/eval/recall_probe_2026_06_20.py`
