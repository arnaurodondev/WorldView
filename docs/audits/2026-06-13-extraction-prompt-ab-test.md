# Deep-Extraction Prompt A/B Test — `deep_extraction@1.4` vs `@1.5`

**Date:** 2026-06-13
**Author:** A/B validation (read-only on codebase; one report file; live DeepInfra calls)
**Question:** Should the team commit to re-extracting ~17k articles under the new
`deep_extraction@1.5` prompt (recall rebalance), or not?
**Verdict (one word): TUNE** — see §6. v1.5 raises recall but introduces material
precision defects (out-of-vocabulary predicates, self-loops, null/common-noun
endpoints, a wrong-direction relation, and a *reproducible* total-collapse-to-zero
regression on a real control article). Do **NOT** re-extract 17k articles on
`@1.5` as written; fix the defects in §6 and re-run this A/B first.

---

## 1. Method (faithful replication of production Block 10)

The deep-extraction call path was replicated exactly from
`services/nlp-pipeline/.../application/blocks/deep_extraction.py`
(`_build_prompt` → `_run_extraction_window`) and
`libs/ml-clients/.../adapters/deepseek_extraction.py`:

| Knob | Production value | Used in A/B |
|---|---|---|
| Model | `Qwen/Qwen3-235B-A22B-Instruct-2507` (`config.py:132` `extraction_api_model_id`) | same |
| Endpoint | DeepInfra OpenAI-compatible (`api.deepinfra.com/v1/openai`) | same |
| Messages | `system=rendered prompt`, `user=window text` | same |
| `response_format` | `{"type":"json_object"}` | same |
| `temperature` | `0.0` | same |
| `max_tokens` | `4096` | same |
| `extra_body` | `reasoning_effort=none`, `prompt_cache_key=kg_extraction_v1` | same |
| Windowing | ≤24,000 word-tokens → single window | same (all sampled docs < limit) |
| `entities` slot | `dict.fromkeys(m.mention_text for m in mentions)` — ALL mentions, order-preserving dedup | same (pulled from `nlp_db.entity_mentions`) |
| `text` slot | `string_agg(chunk_text ORDER BY chunk_index)` | same (pulled from `nlp_db.chunks`) |

- Prompt versions: `@1.5` loaded from the working tree
  (`prompts.extraction.deep`, `content_hash=1deb61c06878`); `@1.4` loaded from
  `git show HEAD:libs/prompts/src/prompts/extraction/deep.py`
  (`content_hash=e263af2c7e1b`). **Hashes differ — confirmed distinct prompts.**
- Venv: `/Users/arnaurodon/.../worldview/.venv312/bin/python`; verified
  `prompts.__file__` resolves to the **main** tree
  (`libs/prompts/src/prompts/__init__.py`), NOT `.claude/worktrees`.
- Each doc was rendered + called under BOTH versions with identical inputs/params.
  429 `engine_overloaded` responses were retried with exponential backoff (the
  provider was under load); no doc was scored from a failed call.

### 1.1 Two baselines — read this before the numbers

There are **two** legitimate "before" pictures, and they tell different stories:

* **DB baseline** = what is persisted in `intelligence_db.relation_evidence_raw`
  today (the audit's 71%-empty cohort). This is what a re-extraction would
  *replace*. By construction all 15 empty-cohort docs have **0** narrative
  relations in the DB.
* **Fresh-`@1.4` baseline** = re-calling `@1.4` *now* on the same inputs.

These diverge sharply: most "empty-cohort" docs **return relations when `@1.4`
is re-called fresh** (mean 3.2 rel/doc; only 4/15 truly return 0). That means
the DB's 71%-empty rate is **largely production noise** — 429s/timeouts
substituted as empty results, model-snapshot drift, and the inherent
non-determinism of DeepInfra at `temperature=0` — **not** a deterministic
prompt failure that `@1.5` alone fixes. This materially weakens the audit's
"the prompt under-elicits recall" attribution and is the single most important
finding of this A/B.

---

## 2. Sample

- **Empty cohort (15):** `full_pipeline` + ≥2 distinct resolved canonical entities
  + **0** narrative relation evidence in `relation_evidence_raw`
  (`canonical_type <> 'is_in_sector'`), source ∈ {eodhd_ticker_news, finnhub,
  eodhd, newsapi}, 600–9000 chars of chunk text. Deterministically spread-sampled
  from the 4,748-doc crux pool.
- **Control (8):** same filters but **had ≥1** narrative relation (precision guardrail).

---

## 3. Recall — empty cohort (15 docs)

| Framing | v1.4 → v1.5 |
|---|---|
| **vs DB baseline** (all 15 had 0 persisted) | **12 of 15** now yield ≥1 relation under `@1.5` (3 stay 0 — all genuinely low-signal: ETF-comparison, DCF-valuation, dividend-screener) |
| **vs fresh-`@1.4`** (identical inputs) | only **1 of 15** flips 0→≥1 (`019eb1e3` Eaton: 0→6); 11 were already non-empty under fresh `@1.4` |
| Mean relations/article (empty cohort) | `@1.4` **3.2** → `@1.5` **4.0** (+25%) |
| Docs that returned 0 under fresh calls | `@1.4`: 4/15 → `@1.5`: 3/15 |

**Reading:** Against the live DB, `@1.5` looks like a 12/15 recall win — but most
of that gain is recoverable by simply re-running `@1.4` (i.e. re-extraction at all,
without prompt noise), because the DB zeros were production failures, not prompt
failures. The *prompt-attributable* recall gain on identical inputs is modest:
**+0.8 relations/article and one true 0→6 flip.**

---

## 4. Precision — the critical guardrail (hand-read every NEW relation)

A "NEW" relation = a distinct `(subject, predicate, object)` triple emitted by
`@1.5` that `@1.4` did not emit on the same input. Each was judged against the
verbatim text + the supplied allow-list. **`@1.5` introduced 53 NEW triples across
the 23 docs** (21 classified mechanically by predicate/endpoint, 32 hand-read).

### 4.1 Grounded-vs-defective tally of the 53 NEW triples

| Category | Count | Examples |
|---|---:|---|
| **Grounded & correct** (both endpoints in text, right predicate/direction) | **16** | `Garmin listed_on NYSE`; `Disney listed_on NYSE`; `Fox listed_on NASDAQ`; `Visa competes_with Mastercard`; `Starbucks has_executive Brian Niccol`; `Caesars listed_on NASDAQ`; `Zacks analyst_rating Eaton`; `analysts earnings_guidance Broadcom`; `Alkermes produces Lumryz` |
| **Borderline** (true but weak/redundant) | **5** | `Fertitta owns_stake_in Caesars` (redundant w/ `acquired_by`); `Tillman board_member_of Fertitta`; `Zacks price_target Eaton` (Zacks Rank ≠ price target); `SpaceX competes_with Nvidia` (marketing aside) |
| **Self-loop** (subject == object) | **8** | `UPS earnings_released UPS`; `Stryker price_target Stryker`; `Palo Alto headquartered_in Palo Alto`; `USDs produces USDs` |
| **Null / common-noun endpoint** (object is `None`/`"stock"`/`"e-commerce"`) | **8** | `Eaton listed_on stock`; `Eaton reported_revenue_of stock`; `Viper earnings_released None`; `Costco reported_revenue_of e-commerce` |
| **Out-of-vocabulary predicate** (schema violation — not 1 of the 32 types) | **5** | `AT& advertises_on Fox`; `FanDuel advertises_on Fox`; `Coca-Cola advertises_on Telemundo`; `Alibaba capital_raise SpaceX`; `Saudi Aramco capital_raise SpaceX` |
| **Hallucinated / wrong-direction** (not supported by text) | **11** | `SpaceX earnings_released Wall Street`; `Rocket Lab listed_on S&P 500` (index, not exchange); `UPS listed_on S&P 500` (×2 surfaces); `Boyu investment_in Starbucks` (Boyu bought China ops); `Bloomberg reported_revenue_of Japan` (Bloomberg is the *reporter*); `Sazaby subsidiary_of Starbucks`; `BearingPoint competes_with Danske Bank` (it is a client/partner); `Costco price_target/earnings_guidance Zacks` |

**NEW-triple precision: 16/53 clean (30%); 5 borderline (9%); 32/53 (60%)
defective** (8 self-loop + 8 null/common-noun endpoint + 5 schema-violation +
11 hallucination/wrong-direction). This is a **material precision regression** in
the incremental output — three out of five new triples are not usable as written.

> The clean 16 are genuinely valuable (textbook `listed_on EXCHANGE`,
> `has_executive`, `competes_with`, the `analyst_rating`/`price_target` cases the
> audit cited) — the *direction* of the change is right. But they arrive bundled
> with twice as many defective triples.

> Note: `@1.4` is not perfect either — it emits `Phillips 66 regulates oil`
> (hallucination, endpoint not in list), `Fox corporate_action Fox` (self-loop),
> `…earnings_released None` artifacts. But `@1.5` *adds* defect classes (`advertises_on`
> OOV, more self-loops, wrong-direction) on top, and the few-shot's `listed_on`
> emphasis is over-firing into index targets (`listed_on S&P 500` appears on
> `019eb4a1` and `019eb54b`).

### 4.2 Control cohort — did `@1.5` regress good cases? YES, once, severely.

7 of 8 control docs were stable-or-better (`@1.5` typically added a correct
`listed_on EXCHANGE`). **But `019eb387`** ("U.S. Crude Oil Storage Levels…") is a
**reproducible catastrophic regression**:

| Run | `@1.4` relations | `@1.5` relations |
|---|---|---|
| A/B pass | 11 | **0** |
| Stability re-runs (×3 each) | [13, 10, 14] | **[0, 0, 0]** |

`@1.4` reliably extracts the grounded `Chevron listed_on NYSE`,
`ExxonMobil listed_on NYSE`, `Devon Energy listed_on NYSE`,
`Diamondback Energy listed_on NASDAQ` (all verbatim `(NYSE:CVX)` etc. in the text).
`@1.5` returns an **empty array every time**. The article's allow-list is
polluted with ambiguous lowercase common nouns (`Oil`, `oil`, `U.S.`,
`United States`, `Middle East`) mixed with real tickers; the v1.5 recall framing
("an empty array is correct ONLY when…") appears to make the model bail entirely
on the harder, noisier entity set rather than extract the easy `listed_on` pairs.
**A recall-rebalance prompt that turns a clean 13-relation article into 0 is a
showstopper for an unattended 17k-doc re-extraction.**

---

## 5. Malformed JSON / schema violations under `@1.5`

- **No** JSON-parse failures (`response_format=json_object` held on all 23 docs,
  both versions; `malformed=false` everywhere).
- **Schema violations DID occur** at the *value* level under `@1.5`:
  out-of-vocabulary predicates `advertises_on` (×3, doc `019ebe9c`) and
  `capital_raise` (×2, doc `019eb270`) — neither is one of the 32 allowed types.
  Downstream these map to `canonical_type IS NULL` and are dropped at Block 11
  (so they cost recall, not correctness), but they show the recall directive is
  loosening the closed-vocabulary discipline the audit confirmed `@1.4` held
  perfectly (0 OOV predicates in 76,869 rows). `@1.4` emitted **0** OOV predicates
  on the same 23 docs.
- Truncated entity ref `AT&` (from `AT&T`/`AT&amp;T` HTML-entity surface) under
  `@1.5` — an allow-list-membership break.

---

## 6. Verdict: **TUNE** (not GO, not NO-GO)

**Why not GO:** precision on the incremental output is only 30% clean / 60%
defective, `@1.5` introduces out-of-vocabulary predicates and more self-loops/null-endpoints,
and it has a *reproducible* 13→0 collapse on a real control article. Re-extracting
17k articles on this prompt would inject thousands of self-loops, OOV-dropped
predicates, and wrong-direction edges, and would *lose* clean relations on the
common-noun-heavy article class. The KG already fights self-loops (BP-384/385) and
provisional noise — `@1.5` as written feeds those failure modes.

**Why not NO-GO:** there is a real, repeatable recall benefit — `@1.5` correctly
adds `listed_on EXCHANGE` on most analyst/earnings articles (18 clean new
relations, incl. the textbook `listed_on`/`price_target` cases the audit cited),
and the one true 0→6 flip (Eaton) is a genuine fix. The *direction* of the change
is right; the execution is too loose.

**Fix before re-running the A/B, then re-extract:**

1. **Re-assert the closed-vocabulary + self-loop + endpoint rules inside the new
   recall block.** The recall directive currently competes with, and is weakening,
   the precision rules. Add explicit lines to `@1.6`: "NEVER emit a predicate
   outside the 32-type list (no `advertises_on`, no `capital_raise`)." "NEVER emit
   a relation where subject_ref == object_ref." "NEVER use `null`, `"stock"`,
   `"shares"`, `"e-commerce"`, or a generic common noun as an endpoint — both
   endpoints must be specific named entities from the list."
2. **Constrain `listed_on` to real exchanges.** The new few-shot is over-firing
   `listed_on S&P 500`/`listed_on <index>`. Add: "`listed_on` object MUST be a
   stock exchange (NYSE, NASDAQ, LSE…), never an index (S&P 500, Dow) or a
   common noun."
3. **Diagnose & fix the common-noun-allow-list collapse (`019eb387`).** The empty
   array on a 13-relation article is the highest-severity issue. Likely the recall
   framing interacts badly when the list mixes ambiguous lowercase nouns with
   tickers. Consider softening "An empty array is correct ONLY when…" back toward a
   neutral "extract every grounded relation; an empty array is acceptable when none
   exist" — keep the cross-sentence directive and the multi-relation few-shot, drop
   the absolutist framing.
4. **Re-baseline the audit's recall claim.** Because fresh `@1.4` already recovers
   11/15 of the "empty" cohort, run the cohort-wide recall measurement against
   **fresh `@1.4`**, not the DB, before sizing the re-extraction ROI. Much of the
   71%-empty headline is production noise (429/timeout-as-empty), addressable by
   the BP-677 timeout-vs-empty distinction and retry hardening that already landed —
   not by the prompt.
5. **Then re-run this exact A/B on `@1.6`** (same 15+8 docs + add ~10
   common-noun-heavy / non-English-exchange docs to stress the collapse case).
   GO only when NEW-relation precision ≥ ~85% clean, zero OOV predicates, zero
   self-loops, and no control doc collapses to 0.

---

## 7. Per-article results table

Counts are distinct `(subject, predicate, object)` triples from fresh live calls.
`new` = triples in `@1.5` not in `@1.4`; `drop` = triples in `@1.4` not in `@1.5`.

| cohort | doc | title (short) | v1.4 | v1.5 | new | drop | notes |
|---|---|---|---:|---:|---:|---:|---|
| empty | 019e7ec6 | Meta $1,500 by 2030 | 2 | 2 | 1 | 1 | v1.5 swaps subject `Meta Stock`→`META` (both grounded) |
| empty | 019e8e5c | SpaceX IPO 55% drop | 5 | 2 | 2 | 5 | v1.5 DROPS 5 grounded `produces` (endpoints not in list), ADDS 2 hallucinated `…Wall Street` |
| empty | 019eb1e3 | Eaton (ETN) trending | 0 | 6 | 6 | 0 | true 0→6 flip; but 4/6 use `"stock"` as endpoint (defective) |
| empty | 019eb35f | May 2026 Dividend Stocks | 0 | 0 | 0 | 0 | genuinely low-signal (screener table) |
| empty | 019eb4a1 | Why Wall St bets on RKLB | 4 | 5 | 4 | 3 | ADDS `listed_on S&P 500` (WRONG); 2 `produces` endpoints not in list |
| empty | 019eb54b | UPS down 2% | 2 | 6 | 4 | 0 | 3 NEW are self-loops/`listed_on S&P 500` |
| empty | 019eb5e6 | IHE vs IXJ ETF | 0 | 0 | 0 | 0 | genuinely low-signal (ETF comparison) |
| empty | 019eb6d2 | Xylem fair value? | 0 | 0 | 0 | 0 | genuinely low-signal (DCF valuation) |
| empty | 019eb7d6 | Alkermes +21% | 7 | 7 | 3 | 3 | parity; v1.5 adds `Lumryz produces` (better than v1.4 `owns_stake_in`) |
| empty | 019eba20 | BearingPoint DK +85% | 4 | 3 | 1 | 2 | NEW `competes_with Danske` is hallucinated; lost 2 grounded `produces` |
| empty | 019eba6d | Sperax SperaxOS | 5 | 5 | 2 | 2 | 2 NEW are self-loops (`Palo Alto…`, `USDs…`) |
| empty | 019ebe9c | Fox 800+ WC ad spots | 5 | 6 | 5 | 4 | +`listed_on NASDAQ` (good) but 3× OOV `advertises_on`, `AT&` truncated |
| empty | 019ebebf | Broadcom beat | 5 | 5 | 2 | 2 | both grounded (`earnings_guidance`, 2nd `analyst_rating`) |
| empty | 019ebef2 | Viper Energy (VNOM) | 5 | 8 | 3 | 0 | 3 NEW all have `None` object (defective) |
| empty | 019ec381 | Stryker cyber/robotics | 4 | 5 | 2 | 1 | 2 NEW are self-loops (`Stryker…Stryker`) |
| control | 019eb270 | SpaceX starts trading | 6 | 7 | 3 | 2 | `competes_with Nvidia` weak + 2× `capital_raise` (OOV) |
| control | 019eb387 | **U.S. Crude Oil Storage** | **11** | **0** | 0 | 11 | **REPRODUCIBLE COLLAPSE → 0** (see §4.2) |
| control | 019eb491 | Costco digital surge | 4 | 5 | 4 | 3 | `price_target/earnings_guidance Zacks` borderline-wrong |
| control | 019eb512 | Visa/MC $38B swipe deal | 6 | 7 | 1 | 0 | +`Visa competes_with Mastercard` (grounded ✓) |
| control | 019eb580 | Tigress raises PT Garmin | 4 | 4 | 1 | 1 | +`Garmin listed_on NYSE` (✓), drops `…None` artifact |
| control | 019eb5e1 | Raymond James lifts DIS | 4 | 5 | 1 | 0 | +`Disney listed_on NYSE` (✓) — clean improvement |
| control | 019eb697 | Fertitta to acquire CZR | 3 | 5 | 3 | 1 | +`listed_on NASDAQ` (✓), `owns_stake_in` redundant |
| control | 019eb731 | Starbucks Japan stake | 7 | 10 | 5 | 2 | +`has_executive` (✓) but +`Boyu investment_in Starbucks` (WRONG dir) + `Sazaby subsidiary_of` (hallucinated) + `Bloomberg reported_revenue_of` (hallucinated) |

---

## 8. Reproduction

- Harness: `/tmp/ab_harness.py` (throwaway), `/tmp/rerun_one.py` (stability).
- Inputs: `/tmp/doc_text.json`, `/tmp/doc_mentions_all.json`,
  `/tmp/doc_mentions_resolved.json`, `/tmp/sample_empty.txt`,
  `/tmp/sample_control.txt`, `/tmp/deep_v14.py` (= `git show HEAD:…/deep.py`).
- Raw outputs: `/tmp/ab_results_empty.json`, `/tmp/ab_results_control.json`.
- No git / DB-write / container changes were made. The only persisted artifact
  is this report.
