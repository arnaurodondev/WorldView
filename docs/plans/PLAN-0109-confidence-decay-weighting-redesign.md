# PLAN-0109 — Confidence, Decay & Weighting Redesign (S7)

**Status:** draft · **Created:** 2026-06-11 · **Design note:** `docs/audits/2026-06-11-confidence-decay-redesign.md`
**Scope decision:** full (decay 1+2+3 + weighting overhaul), confidence is allowed to change downstream.

Two parallel SOTA investigations (decay; weighting) converge on a single conclusion: the decay
fix and the weighting fix are **the same change** — replace the bounded-additive formula with a
**calibrated, time-aware log-odds (logit) model**. This plan sequences that.

---

## Target model (what we are building toward)

**Backbone: Beta / subjective-logic posterior** (decided 2026-06-11). Per relation, accumulate a
decay-weighted, syndication-deduped *evidence mass*:

```
m_g  =  d_g · source_trust_g · extraction_conf_g          # per source-cluster g (decay-weighted)
R    =  Σ_g m_g            (positive evidence mass)
S    =  Σ_j s_j            (contradiction mass)
a0, b0 = κ · base_confidence ,  κ · (1 − base_confidence)  # prior pseudo-counts from the predicate prior
C_raw  =  (a0 + R) / (a0 + b0 + R + S)                     # Beta posterior mean  (= subjective-logic projected prob.)
u      =  (a0 + b0) / (a0 + b0 + R + S)                    # uncertainty (thin-node signal, exposed in API/UI)
C      =  calibrate( C_raw )                               # Beta calibration → P(true)  (Wave 6)
```

- `source_trust_g` = trust from the now-live `source_trust_weights` table; `extraction_conf_g` =
  the (currently ignored) per-evidence extraction confidence; `d_g` = **absolute** temporal-decay
  factor `shape(age_g)`.
- **Decay multiplies each evidence mass (absolute), so it does NOT cancel** (fixes Defect B). The
  **decay floor is per-semantic-mode** (decided 2026-06-11):
  - `RELATION_STATE` (stateful): **hold** — confidence stays at its evidence-backed level until a
    `valid_to` / end-event / contradiction invalidates it (step, no continuous drift). Freshness for
    stateful facts is carried by valid-time + contradictions (W3), not the decay curve.
  - `TEMPORAL_CLAIM` (signal): **decay toward a low floor (~0.1)**, distinct from the extraction
    prior (a stale signal is uninformative, not "baseline plausible"). Implemented as a low
    effective floor as `d_g → 0`, not `base_confidence`.
- **Bounded by construction** (no logit(1.0)=∞ clamping) and yields **uncertainty `u` for free**,
  unifying support / contradiction / unknown in one object (Jøsang subjective logic, SOTA R5).
- **Stateful facts** (`RELATION_STATE`) use **step/valid-interval** `d_g` (hold until `valid_to`),
  not continuous decay. Independent corroboration has natural diminishing returns (no 0.20 cap).
- Recompute runs on a **per-class cadence** (Fix A), not only on new evidence.

This simultaneously fixes: Defect A (frozen between evidence), Defect B (decay cancels), broken
corroboration (`"unknown"` hardcode), dead `base_confidence`, dead `source_trust_weights`, ignored
`extraction_confidence`, arbitrary additive caps, no source-independence, uncalibrated output.

---

## Confirmed current defects (grounding)
Decay: (A) recompute evidence-driven only; (B) `support` normalized average → decay cancels;
`recompute_interval_minutes` dead. Weighting: corroboration broken (`source_type/name="unknown"`
hardcoded in `workers/confidence.py:147-148` — **but the real values ARE stored on
`relation_evidence_raw`**, so it's a read fix); `base_confidence` never passed to the formula;
`source_trust_weights` table never JOINed (per-evidence weight is a constant 0.9/1.0); arbitrary
constants everywhere except `α = ln2/half_life`. Live: avg conf 0.989, bimodal 0.95/1.0.

---

## Waves (dependency-ordered)

### Wave 1 — New Beta/subjective-logic core + wire the dead inputs  ✅ DONE (2026-06-13)
**Shipped:** `domain/confidence.py` `compute_confidence_beta` (+ `BetaConfidence` with uncertainty `u`);
worker reads `base_confidence`, real `source_type`/`source_name`/`extraction_confidence`, JOINs
`source_trust_weights`; `get_all_raw_for_triple` returns source identity; settings
`confidence_formula_v2` (+ κ / signal-floor / default-trust); 8 unit tests (33 pass), ruff+mypy clean.
**Validated** (dry-run, 2000 real relations): v1 distinct=2 (bimodal 0.95/1.0) → v2 distinct=233
(graded 0.13–0.997); per-mode floor holds — RELATION_STATE avg 0.78, TEMPORAL_CLAIM avg 0.23 (decayed
to ~0.1 floor); uncertainty populated. Flag enabled in env + gitops (3 files); scheduler healthy.
Backfill of the existing corpus lands with W2's staleness sweep (worker is still evidence-driven).
*(original sub-tasks below for reference)*

- W1-1 `domain/confidence.py`: implement the logit model above behind `Settings.confidence_formula_v2`
  (keep v1 as fallback for A/B + safe rollout). Prior from `base_confidence`; per-source LLR terms;
  contradiction LLR; `σ()`.
- W1-2 `workers/confidence.py`: pass **real** `source_type`/`source_name`/`extraction_confidence`
  (read from the evidence rows — they exist) and the relation's `base_confidence` into the formula.
  Removes the `"unknown"` hardcode (un-breaks corroboration).
- W1-3 JOIN/lookup `source_trust_weights` → per-source-type `p_g` (un-dead the table); fold
  `extraction_confidence`.
- W1-4 Unit tests: prior influence, monotonic in evidence, diminishing returns, contradiction pulls down,
  single-source = prior+one-LLR. **Gate:** ruff+mypy+unit; live distribution graded (not bimodal).

### Wave 2 — Time-driven decay (Fix A) + absolute decay  ✅ DONE (2026-06-14)
- W2-1 ✅ `ConfidenceWorker` staleness sweep: `fetch_due_for_recompute` reads the (formerly dead)
  `decay_class_config.recompute_interval_minutes`, recomputes due relations with fresh `now` each cycle
  (excludes no-evidence relations). Shared `_recompute_relation` helper used by both passes. +1 sweep
  unit test (34 pass), ruff+mypy clean.
- W2-2 ⏳ absolute exp decay for signals + step/hold for stateful is LIVE; the full non-exp shape
  registry (power/logistic/gauss) is deferred to fold in with W5 per-fact shapes.
- **Validated live** (one triggered cycle, 2559 relations swept): distinct confidence 2 → 230
  (0.128–1.0); EPHEMERAL 1.000→**0.165**, FAST 0.987→**0.226**, MEDIUM→0.573; stateful holds (avg 0.83).
  Idempotent (subsequent cycles sweep 0). Scheduler healthy; runs on the 15-min cadence going forward.

### Wave 3 — Bitemporal valid-time for stateful facts  ✅ DONE (2026-06-14)
**Shipped:** migration `0056_relations_history_bitemporal` (append-only `relations_history`:
valid-time `valid_from`/`valid_to` + transaction-time `recorded_at`; idempotent, schema-resolved,
fail-loud; rollback-tested up→down→up). `compute_confidence_beta` gains `valid_to` → **step decay**
(stateful fact expires to the floor once `now > valid_to`). Repo `append_relation_history` +
`get_confidence_as_of` (AS-OF reconstruction); worker appends a version row each recompute and feeds
`valid_to` into the formula. +3 domain tests (36 pass), ruff+mypy clean.
**Validated live:** expired stateful relation 1.000→**0.100** (step fired); 321 history rows captured
(valid+transaction time); AS-OF row present; scheduler healthy. (valid_to population for the rest of
the corpus comes from end-event detection / W5 LLM — the step logic is in place and proven.)
*(original sub-tasks below for reference)*

- W3-1 Migration in `intelligence-migrations` (R24): **valid time** (`valid_from`, `valid_to`) +
  **transaction time** (`ingested_at`, and a versioning strategy so "what did we believe on date X"
  is answerable — either a `relations_history` append table or system-versioned rows). Forward-compatible.
- W3-2 Populate `valid_from` from `evidence_date`; `valid_to` from end-events/contradictions (later LLM);
  stamp `ingested_at` on every write; version prior state on confidence/validity change.
- W3-3 Step decay for `RELATION_STATE`; bitemporal `AS OF (valid_time, transaction_time)` read path.
  **Gate:** migration rollback test; both AS-OF axes queryable.

### Wave 4 — Source independence (syndication dedup)  ✅ DONE (2026-06-14)
**Shipped:** `EvidenceInput.dedup_key` + clustering in `compute_confidence_beta` — reprints sharing a
key (hash of normalised evidence text) contribute ONCE, at the cluster's best (highest-mass) member;
keyless pieces stay independent. Worker derives the key from `evidence_text` (self-contained — S5's
MinHash clusters are cross-DB/off-limits under R9). +2 domain tests (38 pass), ruff+mypy clean.
**Validated live:** the 906 relations over-corroborated by verbatim reprints dropped avg **0.957 →
0.902** after re-sweep with dedup; scheduler healthy. No migration. (Near-dup/MinHash via an
S5→S6→S7 cluster-id propagation is a future refinement; verbatim syndication is handled now.)

### Wave 5 — LLM-derived per-fact validity  ✅ DONE (2026-06-14)
**Shipped:** DEEP_EXTRACTION prompt v1.4→v1.5 (relations may emit `valid_to`, ISO end-date, with
explicit guidance + schema); `_EXTRACTION_SCHEMA` accepts `valid_to`; S6 `_build_raw_relations` forwards
it (carried in `raw_relations_json` — no Avro change); S7 `RawRelation.valid_to` + `_parse_dt_optional`
(absence → None, never now) + `RelationRepository.upsert(valid_to=…)` with `COALESCE` (a NULL never
clobbers an existing end-date) + port updated. No migration (column existed). +4 consumer tests; full
suites green. **Validated live:** deployed `upsert(valid_to)` wrote `relations.valid_to`; recompute
stepped that relation 0.918→0.100 (W5→W3 integration); prompt v1.5 confirmed in the article-consumer
(needed a `--no-cache` rebuild — a stale `libs/prompts` build-cache layer first baked v1.4).

### Wave 6 — Calibration  ✅ DONE (2026-06-14)
**Shipped:** `domain/calibration.py` — `BetaCalibrator` (`P = sigmoid(a·ln s + b·ln(1−s) + c)`,
identity-capable), `fit_beta_calibrator` (logistic-loss GD), `expected_calibration_error`; wired
optionally into `compute_confidence_beta` and the worker (built from `confidence_calibration_{a,b,c}`,
**identity by default → true no-op** until fitted); `scripts/fit_confidence_calibration.py` (LLM-
adjudicated labelling → fit → ECE → params to set). +6 tests. The offline fitting run (labelling +
κ/floor tuning) is the documented operator step.

### Wave 7 — Thesis reconcile  ◑ model described (agent); final numbers pending
Appendix E + Ch.4 §4.3 already rewritten to the Beta/subjective-logic model (8 SOTA bib entries);
empirical placeholders ("pending calibration") ready to fill with the live QA numbers. Deferred the
number-fill to avoid clobbering the user's concurrent thesis edits (Appendix D actively changing).

### QA (2026-06-14) — exhaustive live validation, all waves
Regression: KG **1568 passed**, NLP 68, prompts pass. Rebuilt + recreated all modified containers
(scheduler, enriched-consumer, kg-api, article-consumer), all healthy. Live: W1 graded (232/79 distinct
per mode), W2 sweep idempotent, W3 history 1240→1782 + step-decay, W4 syndication 0.957→0.902, W5
valid_to→step-decay + v1.5 deployed, W6 calibration identity no-op. Platform 77/81 healthy (the 1
`alert-1` unhealthy is pre-existing/unrelated). One pre-existing `StrEnum` lint in fundamentals_refresh
(not authored here) left untouched.

### Wave 5 (original sub-tasks for reference) —
- W5-1 S6 extraction (libs/prompts): schema-constrained output
  `{decay_class∈6, decay_shape∈5, valid_to?, self_confidence}`; fill the `suggested_decay_class` hook +
  `relation.type.proposed` schema. Clamp to buckets; **fall back to predicate default** when
  `self_confidence<θ` or OOD. **Gate:** constrained-decoding adherence; default-fallback path tested.

### Wave 6 — Calibration & evaluation
- W6-1 Build a small labelled adjudication set (~200–500 relations, true/false-as-of-date).
- W6-2 Beta calibration `P = σ(a·ln s + b·ln(1−s) + c)` raw→P(true); reliability diagram + **ECE**.
- W6-3 (opt) Subjective-logic / Beta-posterior uncertainty `u` exposed in API/UI (fixes thin-node).
  **Gate:** ECE reported; calibrated curve monotone.

### Wave 7 — Thesis rewrite (Appendix E + Ch. 4 §4.3)
- W7-1 Rewrite Appendix E to the log-odds/calibrated model with citations (KV, TruthFinder, log-odds
  pooling, Beta calibration, subjective logic, HALO/Chronocept for per-fact validity).
- W7-2 Ch. 4 §4.3 prose + figure; present the enhanced model as a contribution. **Gate:** compile clean.

---

## Dependencies
W1 is the spine. W2 ⇐ W1. W3 schema can start in parallel; step-decay integration ⇐ W1/W2. W4 enhances
W1's sum. W5 feeds W1/W2/W3 params. W6 ⇐ W1–W2 stable. W7 ⇐ W1–W4 (and W6 if calibration is in-thesis).

## Cross-cutting
- Roll out behind `confidence_formula_v2` flag; recompute backfill after each formula wave.
- Every formula constant that survives must be either derived (`α=ln2/t½`) or calibrated.
- All env/config changes synced to `worldview-gitops` (per standing instruction).
- Downstream (rag-chat fusion/trust, alerts, Intelligence tab) will see decaying values — intended.

## Decisions (locked 2026-06-11)
- Scope: full redesign (decay 1+2+3 + weighting). Confidence allowed to change downstream.
- **Backbone: Beta / subjective-logic posterior** (bounded; yields uncertainty `u`).
- **Decay floor: per-semantic-mode** — stateful holds until invalidated; signals decay to a low floor (~0.1).
- W3: **bitemporal** — proposed impl: a `relations_history` append table (explicit, R24-friendly) +
  `ingested_at`/valid-time on `relations`.
- W4 (syndication): **reuse the existing S5 MinHash/LSH dedup** (`minhash_signatures`/`dedup_hashes`) —
  propagate the near-duplicate cluster id to evidence; don't build new clustering.
- W6 (calibration labels): **LLM-adjudicator-assisted** labelling (strong model judges fact vs source
  passage → true/false/unsupported) with a human spot-check, to make ~300 labels feasible solo.
- W2 default shapes: power-law for DURABLE/SLOW, fast-exp for FAST/EPHEMERAL signals, step for stateful;
  per-fact LLM override (W5).
- Thesis (W7): **after the model stabilizes** (Waves 1–4, ideally + W6 calibration), with real numbers.
- Plan **refined wave-by-wave before implementation**; Wave 1 design settled (backbone + floor).
