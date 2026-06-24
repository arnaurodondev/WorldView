# Deep-Extraction Prompt Re-A/B — `deep_extraction@1.4` vs `@1.6`

**Date:** 2026-06-14
**Author:** A/B re-validation (read-only on codebase; one report file; live DeepInfra calls
through the retry-enabled production adapter)
**Question:** Is the precision-tuned `deep_extraction@1.6` ready to drive the ~17k-article
re-extraction? This is the GO gate from the prior A/B (§6 of
`docs/audits/2026-06-13-extraction-prompt-ab-test.md`).
**Verdict (one word): TUNE** — see §6. v1.6 roughly **halves** v1.5's defect rate
(NEW-triple clean **30% → 54%**) and **mitigates** the `019eb387` collapse, but it does
**NOT** clear the GO gate: it still emits self-loops, out-of-vocabulary predicates, and
index-as-`listed_on` triples, and the `019eb387` control still **bails to 0 on ~1 run in 3**.
Do **NOT** re-extract 17k articles on `@1.6` as written.

---

## 1. Method (faithful replication of production Block 10, retry-enabled)

The deep-extraction call path was replicated exactly from
`services/nlp-pipeline/.../application/blocks/deep_extraction.py`. **Unlike the prior A/B**,
both arms were driven through the production retry-enabled adapter
`ml_clients.adapters.deepseek_extraction.DeepSeekExtractionAdapter.extract` — the path that
bound-retries 429/5xx/timeout (commit landed per
`docs/audits/2026-06-14-extraction-transient-failure-investigation.md`). This removes the
production-noise confound (429 → empty) the prior A/B flagged: a transient failure now
surfaces as a `RetryableError` (recorded as an explicit error), never as a fake empty result.

| Knob | Production value | Used in re-A/B |
|---|---|---|
| Model | `Qwen/Qwen3-235B-A22B-Instruct-2507` | same |
| Endpoint | DeepInfra OpenAI-compatible (`api.deepinfra.com/v1/openai`) | same |
| Adapter | `DeepSeekExtractionAdapter.extract` (retry on 429/5xx/timeout) | same (BOTH arms) |
| Messages | `system=rendered prompt`, `user=window text` | same |
| `response_format` / `temperature` / `max_tokens` | `json_object` / `0.0` / `4096` | same |
| `extra_body` | `reasoning_effort=none`, `prompt_cache_key=kg_extraction_v1` | same |
| Windowing | ≤24,000 word-tokens → single window | same (all docs < limit) |
| `entities` slot | order-preserving dedup of ALL mention texts | same |

- **Prompt versions (hashes confirmed distinct):**
  - `@1.4` = `git show HEAD:libs/prompts/src/prompts/extraction/deep.py` → `deep_extraction@1.4#e263af2c7e1b`
  - `@1.6` = working tree → `deep_extraction@1.6#893101856c61` (matches the task-stated hash)
- **Venv:** `/Users/arnaurodon/.../worldview/.venv312/bin/python`; verified `prompts.__file__`
  and `ml_clients.__file__` both resolve to the **main** tree (NOT `.claude/worktrees`).
- **Sample:** the SAME 15 empty-cohort + 8 control docs as the prior A/B (for comparability),
  including the catastrophic-collapse control `019eb387` (crude-oil).

### 1.1 IMPORTANT confound discovered during this run — provider non-determinism + burst load

This run hit a heavy DeepInfra busy-hour. Two artifacts must be read before the numbers:

1. **Wall-clock timeouts under load.** Run-1 of the control cohort returned
   `RetryableError: wall-clock timeout after 90.0s` for 4 docs (the adapter's per-attempt cap
   firing after exhausted retries during a burst). These are **not** prompt behaviour. They were
   re-run **serially** (low concurrency, generous 150s/attempt, 6 attempts) until they resolved
   cleanly. The final per-article table uses the clean serial reruns.
2. **Model non-determinism at temperature=0.** On `019eb387` the SAME inputs give wildly
   different counts across identical calls (see §4.2). When `@1.4` and `@1.6` were called
   back-to-back sharing `prompt_cache_key`, `@1.4` momentarily read [0,0,0] — but **isolated
   serial `@1.4` reliably returns 12–21 relations** (5/5 runs: 12,16,14,21,12). So `@1.4`'s
   prior-A/B baseline (~11–14) **still holds**; the transient [0,0,0] was burst/cache noise.
   This non-determinism is itself a finding: it means recall on a single run is noisy for BOTH
   arms, so precision (which is structural, not count-based) is the decisive signal.

---

## 2. Headline: did `@1.6` fix the v1.5 defects?

| §6 GO-gate criterion | Target | `@1.5` (prior) | `@1.6` (this run) | Pass? |
|---|---|---|---|---|
| NEW-triple precision clean | ≥85% | 30% | **54%** | **FAIL** (improved, not enough) |
| Zero OOV predicates | 0 | 5 | **3** (`advertises_on`×2, `consulted`×1) | **FAIL** |
| Zero self-loops | 0 | 8 | **5** | **FAIL** |
| Zero index-as-`listed_on` | 0 | ≥2 | **2** (`UPS listed_on S&P 500`; `Costco listed_on COST`) | **FAIL** |
| No control-doc collapse to 0 | 0 | `019eb387` 13→0 (reproducible) | `019eb387` = [8,11,7,0,13,0] over 6 runs → **2/6 still 0** | **FAIL** |

**Direction is right, magnitude is short.** v1.6 roughly halves every defect class versus v1.5
and turns the deterministic v1.5 0-collapse into a *probabilistic* ~33% bail — but it does not
reach zero on any of the four hard gates. The negative few-shot, the in-recall-block precision
rules, and the softened empty-array framing are all helping, yet the model still leaks the
exact patterns those rules name (`advertises_on`, self-loops, index-as-`listed_on`).

---

## 3. Recall (empty cohort, 14 docs scored; `019eb387` excluded as unstable)

| Framing | v1.4 → v1.6 |
|---|---|
| Empty-cohort docs with fresh-`@1.4`=0 | 4/14; of those **1** flips to non-empty under `@1.6` (`019ebe9c` Fox: 0→9) |
| Mean relations/article (all 22 stable docs) | `@1.4` **3.8** → `@1.6` **3.5** (−8% THIS run) |
| Total relations (22 docs) | `@1.4` **84** → `@1.6` **78** |

**Reading:** On this busy-hour run `@1.6` did **not** show a net recall gain — it was slightly
below `@1.4`, dragged down by partial-bail on several empty-cohort docs (`019e8e5c` 4→0,
`019eb4a1` 5→1, `019eb7d6` 5→1, `019eb54b` 8→3). This is the SAME instability class as the
`019eb387` collapse, just less extreme: under load the softened framing still lets the model
under-extract. The one genuine recall win is `019ebe9c` (Fox, 0→9) — but 2 of those 9 are the
`advertises_on` OOV defect, so even the flagship recall flip is partly defective. The
prompt-attributable recall benefit is **not robust** at temperature=0 under provider load.

---

## 4. Precision (hand-read every `@1.6` relation against the verbatim text)

### 4.1 All-relations tally (78 stable `@1.6` relations, both cohorts, `019eb387` excluded)

| Category | Count | Share |
|---|---:|---:|
| Clean & grounded | 57 | **73%** |
| Borderline (true but weak/redundant/dir-ambiguous) | 6 | 8% |
| **Defective** | **15** | **19%** |

### 4.2 NEW-triple tally (37 triples `@1.6` emitted that `@1.4` did not — directly comparable to the prior 30%)

| Category | Count | Share | vs `@1.5` |
|---|---:|---:|---|
| Clean & grounded | 20 | **54%** | 30% |
| Borderline | 5 | 14% | 9% |
| **Defective** | **12** | **32%** | 60% |

### 4.3 Defect breakdown (all 15 defective stable relations)

| Defect class | Count | Examples |
|---|---:|---|
| **Self-loop** (subject == object) | **5** | `META earnings_released META`; `Eaton earnings_released Eaton`; `Rocket Lab earnings_released Rocket Lab`; `Alkermes earnings_released Alkermes`; `Garmin earnings_released Garmin` |
| **OOV predicate** (schema violation) | **3** | `AT&T advertises_on Fox`; `FanDuel advertises_on Fox`; `Starbucks consulted investment banks` |
| **index/ticker as `listed_on`** | **2** | `UPS listed_on S&P 500` (index); `Costco listed_on COST` (ticker, not an exchange) |
| **Hallucination (not grounded)** | **2** | `SpaceX competes_with Alibaba`; `Nvidia competes_with Alibaba` (Alibaba named only as a past-IPO record) |
| **Ticker-as-endpoint** | **1** | `Costco earnings_released COST` |
| **Wrong direction** | **1** | `Boyu Capital investment_in Starbucks` (Boyu *bought* the China unit *from* Starbucks — reversed) |
| **Empty-evidence / hallucination** | **1** | `Starbucks headquartered_in Japan` (`evidence_text=""`; Starbucks HQ is Seattle) |

**The self-loop `earnings_released X→X` pattern is the single most persistent defect** — it
appears on 5 distinct earnings articles despite v1.6's explicit numbered rule #1 ("NO
self-loops") AND the negative few-shot showing exactly `UPS earnings_released UPS` as REJECTED.
The model treats "Company X reported earnings" as a self-relation regardless. Likewise
`advertises_on` survives despite being named verbatim as forbidden in rule #3 and the negative
few-shot. **Naming a defect in the prompt is not eliminating it.**

### 4.4 The decisive control: `019eb387` (U.S. Crude Oil Storage) — collapse MITIGATED, not FIXED

Entity list (verbatim): `U.S., Oil, Chevron, NYSE, ExxonMobil, oil, United States, Middle East,
Devon Energy, Diamondback Energy, NASDAQ` — the common-noun-polluted list that triggered the
v1.5 collapse.

| Prompt | Relation count over isolated serial runs |
|---|---|
| `@1.4` | **[12, 16, 14, 21, 12]** (5/5 non-zero — stable, matches prior A/B ~11–14) |
| `@1.5` (prior A/B) | **[0, 0, 0]** (deterministic collapse) |
| `@1.6` (this run) | **[8, 11, 7, 0, 13, 0]** — **4/6 recover, 2/6 still bail to 0** |

When `@1.6` *does* fire it recovers the grounded `Chevron/ExxonMobil/Devon listed_on NYSE` +
`Diamondback listed_on NASDAQ` pairs the audit cared about — **but** the same runs also add
common-noun defects (`Oil operates_in_country Middle East`, `Oil produces oil` (`oil` is a
common noun), `Chevron headquartered_in U.S.`). So even the recovered output mixes the 4 clean
`listed_on` triples with ~4 defective ones. **A 33% probability of a clean 13-relation article
silently producing 0 is disqualifying for an unattended 17k-doc re-extraction** — at that rate
~1/3 of common-noun-heavy articles would be lost, exactly the failure mode v1.6 was meant to fix.

---

## 5. Control cohort — did `@1.6` regress good cases?

7 of 8 control docs are stable-or-better; `@1.6` consistently adds the correct
`listed_on EXCHANGE` (`Garmin→NYSE`, `Disney→NYSE`, `Caesars→NASDAQ`) the audit wanted, and the
`019eb512` Visa/Mastercard settlement and `019eb697` Caesars M&A cases are clean. **But** it
adds garbage on two: `019eb491` Costco (`listed_on COST` + `earnings_released COST` ticker
endpoints) and `019eb731` Starbucks (`consulted` OOV, `Boyu investment_in Starbucks`
wrong-direction, `Starbucks headquartered_in Japan` empty-evidence hallucination). The
`019eb387` collapse (§4.4) is the one severe control regression that remains.

---

## 6. Verdict: **TUNE** — fails the GO gate

**Why not GO:** every one of the four §6 hard gates fails — NEW-triple clean is **54%** (gate
≥85%), and the counts are **3 OOV predicates, 5 self-loops, 2 index/ticker-as-`listed_on`,
and a still-reproducible ~33% 0-collapse on `019eb387`**. Re-extracting 17k articles on `@1.6`
would still inject thousands of self-loops (the KG actively fights these — BP-384/385), drop
OOV predicates at Block 11 (recall loss), emit index-as-`listed_on` edges, and silently lose
~1/3 of common-noun-heavy articles. The retry hardening removed the 429-as-empty confound, but
the residual empties on `019eb387`/`019e8e5c`/etc. are now provably **prompt/model behaviour**,
not transient failures.

**Why not NO-GO:** the change is clearly working in the right direction. v1.6 **halved** the
defect rate (60% → 32% on NEW triples; clean 30% → 54%), turned the deterministic v1.5
0-collapse into a recoverable-most-of-the-time event, and the clean output is genuinely good
(textbook `listed_on EXCHANGE`, `price_target`, `has_executive`, the Visa/MC and Caesars cases).
The negative few-shot and in-block precision rules help — they just have not driven the named
defects to zero.

**Fix before the next re-A/B, then re-extract:**

1. **Self-loop is now structural, not stylistic — enforce it in code, not (only) the prompt.**
   The model emits `earnings_released X→X` on 5/5 earnings articles despite an explicit rule
   AND a negative few-shot naming that exact triple. Add a deterministic post-filter in
   `deep_extraction.py` (or Block 11) that DROPS any relation with `subject_ref == object_ref`.
   This is a 2-line guard that guarantees the zero-self-loop gate regardless of model drift.
2. **Validate the closed predicate vocabulary in code.** `advertises_on` and `consulted` still
   leak. Drop any relation whose predicate ∉ the 32-type set at parse time (it is already
   dropped downstream as `canonical_type IS NULL`, but an explicit filter makes the gate
   measurable and stops it costing a relation slot).
3. **Validate `listed_on` object against a real-exchange allow-list in code.** Reject
   `listed_on <index>` / `listed_on <ticker>` deterministically (`UPS→S&P 500`, `Costco→COST`).
4. **The `019eb387` 0-bail is the highest-severity remaining item.** The softened framing
   reduced but did not remove it. Options: (a) further calibrate the empty-array sentence; (b)
   pre-filter the entity allow-list to drop bare common nouns (`Oil`, `oil`, `U.S.`,
   `United States`, `Middle East`) BEFORE rendering the prompt — this is likely the real root
   cause (the polluted list confuses the model), and a list-hygiene step would also kill the
   `Oil produces oil` / `Oil operates_in_country …` defects at the source.
5. **Re-baseline recall on a quiet hour.** This run hit a busy hour; both arms were noisy. Run
   the cohort-wide recall measurement when DeepInfra is not under burst load (the retry adapter
   makes this safe) so the recall-gain claim is not masked by load-induced partial bails.
6. **Then re-run this exact A/B on the post-fix prompt + code filters.** GO only when
   NEW-relation precision ≥85% clean, **0** OOV predicates, **0** self-loops, **0**
   index/ticker-as-`listed_on`, and `019eb387` is non-zero on **all** stability runs.

> **Strong recommendation:** ship gates #1–#3 as deterministic code filters (post-extraction
> validation) rather than relying on the prompt to self-police. The evidence here is decisive:
> the model ignores explicitly-named, few-shot-demonstrated prohibitions ~1/3 of the time.
> A code-level validator makes the zero-self-loop / zero-OOV / valid-exchange gates *guaranteed*
> and removes them from the model's non-determinism budget. With those filters in place a
> re-A/B would likely clear the precision gates immediately, leaving only the `019eb387`
> recall-bail (gate #4) to tune.

---

## 7. Per-article results table (`@1.4` vs `@1.6`)

Counts are distinct `(subject, predicate, object)` triples from live calls through the
retry-enabled adapter. `@1.6` defects hand-classified against verbatim text + the supplied
allow-list. (`019eb387` shown with its 6-run stability range; all others single clean run.)

| cohort | doc | title (short) | v1.4 | v1.6 | v1.6 defects |
|---|---|---|---:|---:|---|
| empty | 019e7ec6 | Meta $1,500 by 2030 | 2 | 3 | 1 self-loop (`META earnings_released META`) |
| empty | 019e8e5c | SpaceX IPO 55% drop | 4 | 0 | partial bail (recall loss, not defect) |
| empty | 019eb1e3 | Eaton (ETN) trending | 3 | 3 | 1 self-loop; 1 borderline (`reported_revenue_of` index) |
| empty | 019eb35f | May 2026 Dividend Stocks | 0 | 0 | — (genuinely low-signal screener) |
| empty | 019eb4a1 | Why Wall St bets on RKLB | 5 | 1 | 1 self-loop; partial bail |
| empty | 019eb54b | UPS down 2% | 8 | 3 | 1 index-as-`listed_on` (`UPS→S&P 500`) |
| empty | 019eb5e6 | IHE vs IXJ ETF | 0 | 0 | — (genuinely low-signal) |
| empty | 019eb6d2 | Xylem fair value? | 0 | 0 | — (genuinely low-signal DCF) |
| empty | 019eb7d6 | Alkermes +21% | 5 | 1 | 1 self-loop; partial bail |
| empty | 019eba20 | BearingPoint DK +85% | 3 | 2 | 0 (clean: `partner_of` + `has_executive`) |
| empty | 019eba6d | Sperax SperaxOS | 5 | 5 | 0 (clean — v1.5's 2 self-loops are GONE here) |
| empty | 019ebe9c | Fox 800+ WC ad spots | 0 | 9 | **2 OOV `advertises_on`**; recall flip 0→9 |
| empty | 019ebebf | Broadcom beat | 5 | 3 | 0 (clean) |
| empty | 019ebef2 | Viper Energy (VNOM) | 5 | 5 | 0 (clean — v1.5's `None` endpoints GONE) |
| empty | 019ec381 | Stryker cyber/robotics | 4 | 3 | 0 (clean — v1.5's self-loop GONE) |
| control | 019eb270 | SpaceX starts trading | 5 | 5 | 2 hallucinated `competes_with Alibaba` |
| control | 019eb387 | **U.S. Crude Oil Storage** | 12–21 | **[8,11,7,0,13,0]** | **2/6 collapse to 0**; recovered runs add `Oil`/`oil` common-noun defects |
| control | 019eb491 | Costco digital surge | 5 | 5 | `listed_on COST` + `earnings_released COST` (ticker endpoints) |
| control | 019eb512 | Visa/MC $38B swipe deal | 6 | 6 | 0 (2 borderline `filed_lawsuit_against` direction) |
| control | 019eb580 | Tigress raises PT Garmin | 4 | 5 | 1 self-loop (`Garmin earnings_released Garmin`); +`listed_on NYSE` ✓ |
| control | 019eb5e1 | Raymond James lifts DIS | 4 | 5 | 0 (clean; +`Disney listed_on NYSE` ✓) |
| control | 019eb697 | Fertitta to acquire CZR | 3 | 3 | 0 (clean; +`Caesars listed_on NASDAQ` ✓) |
| control | 019eb731 | Starbucks Japan stake | 7 | 11 | `consulted` OOV; `Boyu investment_in Starbucks` wrong-dir; `headquartered_in Japan` empty-evidence |

---

## 8. Reproduction

- Harness: `/tmp/ab_harness_v16.py` (drives BOTH arms through `DeepSeekExtractionAdapter.extract`).
- Inputs (reused from prior A/B): `/tmp/doc_text.json`, `/tmp/doc_mentions_all.json`,
  `/tmp/sample_empty.txt`, `/tmp/sample_control.txt`, `/tmp/deep_v14.py` (= `git show HEAD:…/deep.py`).
- Raw outputs: `/tmp/ab_v16_results_empty.json`, `/tmp/ab_v16_results_control.json`.
- `019eb387` stability + `@1.4` isolation runs: ad-hoc serial probes (see §4.2, §1.1).
- No git / DB-write / container changes were made. The only persisted artifact is this report.
