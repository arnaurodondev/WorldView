# Confidence & Temporal-Decay Redesign — Review + SOTA + Proposal

**Date:** 2026-06-11 · **Status:** design note (no code changed) · **Owner:** Arnau

Investigation of the current relation-confidence/decay mechanism, a state-of-the-art
review, and a ranked enhancement proposal. Informs both the platform and the thesis
(Ch. 4 §4.3 / Appendix E claim of "temporally-decaying confidence").

---

## 1. Current mechanism (as built)

- **Decay class is per-predicate, fixed.** At canonicalization (`blocks/canonicalization.py`)
  the extracted predicate is matched against `relation_type_registry` (exact → ANN
  soft-map → propose-unknown). The match carries `(semantic_mode, decay_class,
  decay_alpha, base_confidence)`. 32 predicates → 6 classes; unknown → `DURABLE`.
- **Class → fixed params** (`decay_class_config`): PERMANENT/DURABLE/SLOW/MEDIUM/FAST/
  EPHEMERAL with half-lives ∞/730/180/60/14/3 d and a **`recompute_interval_minutes`**
  column (7d/7d/1d/6h/1h/15min) **that nothing reads.**
- **Formula** (`domain/confidence.py`): `C = clip(support + corroboration − contradiction, 0, 1)`
  with `support = Σ(wᵢ·swᵢ)/Σ(wᵢ)`, `wᵢ = exp(−α·age)`; corroboration = diversity
  bonus gated at `wᵢ ≥ 0.1`, capped 0.20; contradiction = top-3 decayed strengths,
  capped 0.60.
- **Worker** (`workers/confidence.py`): every 15 min, recomputes **only triples with
  new unprocessed `relation_evidence_raw` rows**. Evidence-driven; no staleness sweep.
- **`suggested_decay_class`** exists in the relation-type-proposal event but is hardcoded
  `None` — the extractor never suggests anything.

### Two independent defects
- **A — recompute is evidence-driven, not time-driven.** Confidence frozen between
  evidence arrivals. `recompute_interval_minutes` is dead.
- **B — the formula barely decays even when recomputed.** `support` is a *normalised
  weighted average*, so `exp(−α·age)` cancels: a single-source fact's support = its
  `source_weight` regardless of age. Only the corroboration gate and contradiction decay
  move with wall-clock time.

**Live evidence both are real:** EPHEMERAL (3-day half-life) relations average confidence
**1.000**; FAST (14-day) average **0.987**; platform-wide 13 distinct values, avg 0.989.
**Fixing A alone will not produce decay — B must also change.** The thesis claim of
temporally-decaying confidence is currently not true in practice.

---

## 2. State of the art (what large systems do)

- **Industrial KGs use calibrated probabilistic fusion, not additive heuristics.**
  Google **Knowledge Vault** (KDD 2014): extractor confidences + graph priors →
  **calibrated P(true)**; **Knowledge-Based Trust** (PVLDB 2015): source trust from fact
  correctness; **Diffbot**: [0,1] confidence, **discard < 0.5**, provenance per fact;
  **NELL**: candidate→promoted **gate** at ~0.9; **Wikidata**: no probability — **rank** +
  **valid-time qualifiers** P580/P582/P585.
- **"Is it still true now?" → explicit valid-time intervals beat continuous decay**
  (temporal-DB / SQL:2011 / Allen algebra / bitemporal "AS OF"). Continuous decay is the
  right tool only for facts with **no crisp expiry** (signals). The TKG-embedding
  literature (TTransE/HyTE/TNTComplEx/RE-NET/TGN) is about link *forecasting*, not
  asserted-fact decay.
- **Decay-function families** (Elasticsearch ships exp/gauss/linear in production):
  exponential (memoryless), **power-law** (human-memory forgetting fits power law better —
  heavy tail, "fades but never zero"), **step/box-car** (valid-until-expiry — the correct
  shape for stateful facts), logistic (stable then rots), **Hawkes self-exciting** (each new
  corroboration *re-boosts* then decays — Know-Evolve, Graph Hawkes), gauss (delayed peak).
- **LLM-derived validity is an active area** and points the way the user suggested:
  Almquist & Jatowt (ECIR 2019) **validity-period buckets**; "Mitigating Temporal
  Misalignment by Discarding Outdated Facts" (EMNLP 2023) **per-fact duration prediction**;
  **HALO** (2025) data-driven **per-relation half-life** (`t½ = ½·mean update interval`);
  **Chronocept** (2025) per-fact **skew-normal validity curve** (location/scale/skew).
  Caveat: temporal-commonsense benchmarks (TimeBench, MCTACO) show raw LLM duration
  reasoning is **unreliable and overconfident** → constrain + calibrate + default-fallback.

(Full citations in the research brief appended to the session transcript.)

---

## 3. Proposed enhanced design (mapped onto our code)

The spine already exists (6 classes, `recompute_interval_minutes`, `semantic_mode`
RELATION_STATE vs TEMPORAL_CLAIM, the `suggested_decay_class` hook, `confidence_last_computed_at`).
The redesign reuses all of it.

### Fix A — decay-class-aware time-driven recompute (the worker you greenlit)
Add a **staleness sweep** to `ConfidenceWorker`, alongside the evidence path: select
relations where `confidence_last_computed_at + (recompute_interval_minutes) < now()`,
recompute with a fresh `now`. Reads the dead column; cadence is per-class. Cheap.

### Fix B — make confidence actually decay, split by fact nature
- **Stateful facts (`RELATION_STATE`: employs, listed_on, board_member_of, headquartered_in,
  subsidiary_of, …): valid-time interval + step decay.** Add `valid_from / valid_to`. Full
  confidence until `valid_to` (or a contradiction/end-event), then drop to a floor — *not*
  exponential. A still-true CEO must not fade. Enables "AS OF" queries / backtesting.
- **Signal facts (`TEMPORAL_CLAIM`: sentiment_signal, price_target, analyst_rating,
  market_share_claim, …): absolute recency multiplier.** `C = base × shape(age)` so an old
  signal genuinely decays toward a floor on its class cadence. This is what makes
  EPHEMERAL/FAST drop from 1.0.

### User idea 1 — LLM-suggested, bucket-constrained, default-backed validity
Fill the `suggested_decay_class` hook. At extraction the LLM emits, via **schema-constrained
decoding**, `{decay_class ∈ 6 buckets, decay_shape ∈ {step,exp,power,logistic,gauss},
valid_to?, self_confidence}`. **Clamp to buckets; fall back to the predicate default when
self_confidence < θ or output is OOD.** Per-fact resolution (interim vs permanent CEO; a
"through FY25" guidance) without losing safe defaults. Keep the LLM on a leash (benchmarks
say it's overconfident on durations).

### User idea 2 — multiple decay shapes
Add a `decay_shape` enum + a small strategy registry in `domain/confidence.py`:
step (stateful), fast-exp (sentiment), **power-law** (durable-but-aging, better tail),
logistic/gauss (delayed-peak signals). Selected per predicate, overridable per fact.

### SOTA must-have — calibration
Maintain a small labelled set (fact → was-it-true-at-date-X); fit **isotonic/Platt**
raw→calibrated P(true). Optionally adopt a **discard/quarantine threshold** (Diffbot <0.5 /
NELL promotion gate) and **source-trust weighting** (KBT) for corroboration.

---

## 3b. Current WEIGHTING defects (parallel investigation — Appendix E)

Grounding the "the weighting formulas may be naive" concern. Confirmed in the live code/DB:

1. **Corroboration/diversity bonus is effectively broken.** The worker builds every
   `EvidenceInput` with **`source_type="unknown"`, `source_name="unknown"` hardcoded**
   (`workers/confidence.py` ~line 145). Corroboration counts *distinct* `(source_type,
   source_name)` pairs — so no matter how many independent sources corroborate, the set
   size is **always 1** → bonus pinned at ≤ 0.05. The multi-source reward the formula is
   designed for never fires. (This, plus support ≈ `source_trust_weight` ≈ 0.9–0.95 for SEC,
   explains the observed avg 0.989 / max 1.0.)
2. **`extraction_confidence` is ignored.** Each evidence row stores the LLM's own
   extraction confidence, but `EvidenceInput` never includes it → it does not enter the score.
3. **`base_confidence` (per-predicate prior) is ignored.** Carefully maintained per predicate
   in `relation_type_registry` (has_executive 0.9 … competes_with 0.45) and stored on the
   relation, but **never passed to `compute_confidence`** — a Knowledge-Vault-style prior we
   have and don't use.
4. **`source_trust_weights` are hand-set constants** (sec_10k 0.95 → manual 0.50; 12 rows),
   not learned/calibrated, and **no source-independence handling** (syndicated Reuters/AP wire
   counts as many independent sources).
5. **`support` is a normalized average** (decay cancels — see Defect B) and is uncalibrated
   (not a P(true)).

These are exactly the targets of the parallel SOTA weighting investigation (truth-discovery /
iterative source reliability, log-odds / noisy-OR pooling with diminishing returns, source-copy
down-weighting, calibration, subjective-logic/Beta-posterior confidence). The Appendix E rewrite
and the formula waves below will incorporate its recommendations.

## 4. Phased plan

| Phase | Scope | Touches | Effect |
|---|---|---|---|
| **1** | Staleness sweep (A) + absolute recency decay for TEMPORAL_CLAIM signals (B-min); keep RELATION_STATE non-decaying for now | `workers/confidence.py`, `domain/confidence.py`, read `recompute_interval_minutes` | Makes the thesis claim true: signals decay on cadence; stateful facts stay stable |
| **2** | `decay_shape` enum + strategy registry; `valid_from/valid_to` + step decay for stateful facts (migration, R24); LLM-suggested class/shape/valid_to via the proposal hook (S6 prompt + schema) | `intelligence-migrations`, `domain/confidence.py`, `libs/prompts`, S6 extraction | Per-fact validity, correct shapes, valid-time "AS OF" |
| **3** (stretch / thesis novelty) | Calibration (isotonic) + discard threshold + source-trust weighting; Chronocept-style continuous curve as a demonstrator | new calib step, S6/S7 | Industry-grade calibrated probabilities; research novelty |

---

## 5. Open decisions (need sign-off before building)

1. **Scope now:** Phase 1 only (minimal — make decay real on the cadence), or Phase 1+2?
2. **Confidence becomes time-dependent** (it will actively drop for aged signals). Downstream
   consumers — rag-chat `trust`/`fusion_score`, alerts, the Intelligence tab — will see
   changing values. Confirm that's wanted (it's the point, but it changes displayed numbers).
3. **Valid-time columns** (`valid_from/valid_to`, maybe bitemporal `ingested_at`): add via
   `intelligence-migrations` (R24)? Bitemporal or valid-time only?
4. **LLM extraction change** (Phase 2) touches the S6 prompt + proposal schema — bigger blast
   radius; constrained decoding + calibration required.
5. **Thesis:** Ch. 4 §4.3 / Appendix E currently describe exponential per-predicate decay.
   At minimum reconcile wording with reality; if we ship Phase 2/3 the enhanced model is a
   genuine contribution worth writing up. Decide scope vs. thesis deadline.

**Recommendation:** do **Phase 1 now** (it's what you already greenlit and it makes the
existing thesis claim honest), then decide Phase 2 as a deliberate scope/novelty call
against the thesis timeline.
