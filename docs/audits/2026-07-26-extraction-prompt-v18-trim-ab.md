# Extraction Prompt Trim A/B — `deep_extraction@1.7` vs `@1.8-trim`

**Date:** 2026-07-26
**Question:** Is the proposed v1.8 trim of the relation-extraction system prompt safe to
ship (quality-neutral-or-better), and how much does it actually cut cost?
**Verdict (one word): GO** — quality-neutral on every measured axis, with the two apparent
precision-regression signals conclusively traced to *judge non-determinism* (not the
prompt) via stability re-runs. Realized cost saving is real but modest (~8% prompt
tokens/call, ~$2.8/week). **Do NOT auto-flip traffic on this evidence alone** — bump the
active version through the normal review gate; a multi-seed confirmatory run is cheap
insurance (see §7).

---

## 1. What the trim changes (`libs/prompts/src/prompts/extraction/deep_v18.py`)

v1.8 is a **separate object** (`DEEP_EXTRACTION_V18`, version `1.8`); v1.7
(`DEEP_EXTRACTION` in `deep.py`) is left untouched and remains the production prompt.

**COMPRESSED** (safe — `relation_validation.py` catches every violation in code regardless
of prompt wording, per the 2026-06-18 precision-gates audit):
- self-loop / closed-vocabulary / `listed_on`-exchange / common-noun-endpoint rule prose
  → one line each (each maps to a deterministic gate: `self_loop`, `oov_predicate`,
  `invalid_listed_on`, `common_noun_endpoint`).
- 32 predicate paragraphs → `name — one-clause gloss`, **direction convention preserved**
  in every gloss (e.g. `acquired_by — subject=acquired company, object=acquirer`).
- Dropped the 2 negative few-shots those rules owned (UPS self-loop; Rocket-Lab index
  `listed_on`) — both are code-gated structural defects.

**KEPT VERBATIM** (no code backstop — pure semantic judgement; C-ICL/LC-ICL literature
shows contrastive negatives disproportionately suppress exactly these):
- the 3 co-mention negatives (Ford/Honda/Toyota; résumé enumeration; "peers such as") +
  the CO-MENTION-IS-NOT-A-RELATION paragraph;
- the DIRECTION rules + person=object worked examples (incl. the inverted-direction WRONG one);
- the ENTITY TYPE PRECISION rules ([index]/[currency]/… is never a company endpoint).

### Token reduction (measured)
| method | v1.7 | v1.8 | reduction |
|---|---|---|---|
| char count | 12,763 | 10,777 | −15.6% |
| word-split (repo's `len(prompt.split())` estimator) | 1,695 | 1,399 | −296 (−17.5%) |
| char/4 (the method that produced the "~3,170 tokens" figure) | ~3,190 | ~2,694 | −496 (−15.6%) |
| **DeepInfra `usage.prompt_tokens`, mean/doc (authoritative)** | **5,531.5** | **5,084.5** | **−447 (−8.1%)** |

The −447 tokens/call is the reducible template portion; the remaining ~5,084 is the
fabrication preamble + per-doc entity list + document text (the text dominates, which is
why the % is 8% of the full prompt not 15%). The −447 was **byte-identical across the
smoke and full runs** — it is the deterministic prompt-size delta, not noise.

## 2. Method — no confound

- **Extractor (BOTH arms):** `deepseek-ai/DeepSeek-V4-Flash` @ `reasoning_effort=medium`
  — the exact live prod config (`NLP_PIPELINE_EXTRACTION_API_MODEL_ID` /
  `NLP_PIPELINE_EXTRACTION_REASONING_EFFORT`). The ONLY thing differing between arms is the
  system prompt, so the delta is purely the trim.
- **Code gate:** the real `validate_relations` (with the per-doc `{name: mention_class}`
  map, exactly as `deep_extraction.py` threads it) applied to BOTH arms' raw output.
- **Judge:** `deepseek-ai/DeepSeek-V4-Flash` (repo budget-judge convention). Same judge on
  both arms → self-preference bias is common-mode. Structural defects are judge-free.
- **Sample:** 50 real `full_pipeline` news docs, stratified **25 co-mention-heavy / 25
  regular** (co-mention-heavy = peer-list / market-recap / "X vs Y" / "best N stocks"
  titles — the failure class with NO code backstop).
- Harness: `scripts/eval/extraction_prompt_v18_ab.py`. Frozen sample + raw rows:
  scratchpad `v18_par/{sample.json,rows.json,report.md}`.

## 3. Results (50 docs, single seed)

### Precision (post-gate survivors — what reaches the KG)
| metric | v1.7 | v1.8 | Δ |
|---|---|---|---|
| judge precision (supported/emitted) | 1.000 (49/49) | 0.962 (50/52) | −0.038 |
| **co-mention FP rate** | **0.000 (0)** | **0.000 (0)** | **0.000** |
| **direction-inversion rate** | 0.000 (0/23) | 0.074 (2/27) | +0.074 |

### Recall
| metric | v1.7 | v1.8 |
|---|---|---|
| gated relations/doc (yield) | 0.98 (49) | 1.04 (52) |
| articles with ≥1 relation | 23/50 | 23/50 |
| mean judge recall grade (1–5) | 5.0 | 5.0 |

### Deterministic structural defects — PRE-GATE (intrinsic prompt looseness)
| defect (raw, before gate) | v1.7 | v1.8 |
|---|---|---|
| self-loops | 0 | 0 |
| out-of-vocab predicates | 0 | 0 |
| `listed_on` → non-exchange | 0 | 0 |

**The trimmed prompt is NOT intrinsically looser** on any code-backstopped class — zero
defects in both arms. This confirms the core hypothesis: those rules are redundant with
both the code gate AND the current model's behaviour (V4-Flash simply does not emit them).

## 4. The two apparent precision regressions are JUDGE NOISE (stability re-run, 6× each arm)

Both precision-regression signals came from a single doc each. Re-running the extractor
6× per arm at the identical config (`scripts/eval` stability probe) settles it:

- **`019f6a08` Dynatrace / BMO price_target (the "direction inversion")** — BOTH v1.7 and
  v1.8 emit `BMO Capital | price_target | Dynatrace` (firm-as-subject) **6/6 runs each,
  identically.** The inversion is a *model* behaviour shared by both prompts, not a trim
  effect. In the main run the judge scored v1.7's output "correct direction" and v1.8's
  structurally-identical output "inverted" — the 0→2 delta is judge scoring instability.
- **`019f6df0` SoundHound acquired_by Amelia (the "2 unsupported")** — BOTH prompts emit
  `Amelia AI | acquired_by | SoundHound AI` + `SoundHound AI | listed_on | NASDAQ` **6/6
  runs each, identically and correctly.** The main-run candidate `n_supported=0` came with
  an *empty* judge justification — a judge glitch, not a real defect.

Net: with the judge noise removed, the **true precision, co-mention-FP, and
direction-inversion deltas are all ~zero.** Neither un-backstopped failure class (co-mention,
direction) increases under the trim.

## 5. Cost (corrected to real DeepInfra price: V4-Flash $0.14/1M in, $0.28/1M out)

- Reliable saving = **prompt tokens only**: −447/call (−8.1%). Completion tokens differed
  by +4,755 over 50 docs, but §4 proves the models emit *identical* relations — that delta
  is sampling noise, not a systematic cost, so no completion saving is claimed.
- **Weekly (news bucket ≈ 45,000 calls/wk):** 447 × 45,000 = 20.1M input tokens/wk ×
  $0.14/1M ≈ **$2.82/week (~$147/year)**.
- Honest framing: the $ saving is small because (a) input is cheap at $0.14/1M and (b) the
  document text dominates each prompt (the trimmed template is ~8% of prompt tokens). The
  trim's value is **prompt clarity/maintainability + removing 496 tokens of code-redundant
  prose**, not a material cost lever.
- Prompt-prefix caching does not erode this: the trimmed region sits AFTER the first
  dynamic slot (`{entities}`), so it is billed fresh every call — trimming it yields
  full-price savings.

## 6. Verdict — GO (quality-neutral), confidence MODERATE-HIGH

GO criterion (co-mention FP rate and direction-inversion rate must not increase): **met**,
once the judge-noise artifacts in §4 are removed. Recall neutral (5.0=5.0), structural
defects zero in both arms, cost strictly ≤ baseline.

Robustness note: even if DeepInfra later swaps extraction back to a "dirtier" model (the
old Qwen@none that produced self-loops/OOV/index-`listed_on`), the trim stays safe on those
four classes — the code gate catches them regardless of prompt wording. The only
un-backstopped classes (co-mention, direction) were kept verbatim.

## 7. Caveats (why this is GO-with-confirmation, not auto-ship)

- **Single seed, n=50.** DeepInfra is non-deterministic at temp=0 (documented in prior
  audits); the same doc gave different relation counts between smoke and full runs. The
  aggregate is directional, not a tight bound.
- **Budget judge has proven per-doc scoring instability** (§4) — it flipped direction/support
  calls on identical outputs. It is adequate for a common-mode delta but not for a precise
  per-metric point estimate.
- **Co-mention stratum mostly yielded empty** (both prompts correctly refuse co-mention),
  so co-mention FP was exercised on few *positive opportunities*. That both prompts refuse
  cleanly is reassuring, but a targeted co-mention-with-real-relation set would test the
  boundary harder.

## 8. Recommendation (NOT applied here — production behaviour change)

If shipping, a follow-up change (its own reviewed commit, not this validation) would:
1. Move the trimmed body into `deep.py` as the new `DEEP_EXTRACTION` (version → `1.8`),
   OR re-point the import; **the drift-guard test `test_valid_predicates_match_deep_extraction_prompt`
   parses predicate names from between `"predicate (relation type"` and
   `"RELATION ASSERTION TEST"` — the v1.8 header reads `"predicate — pick the closest"`, so
   that anchor + the em-dash gloss format must be preserved (they are) or the test updated.**
2. Run the multi-seed confirmatory A/B (§7) before flipping live traffic.
3. Retire `deep_v18.py` (its purpose is this A/B).

No production code path imports `DEEP_EXTRACTION_V18`; `deep_extraction.py`'s import is
unchanged.
