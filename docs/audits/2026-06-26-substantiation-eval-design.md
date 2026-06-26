# Design: Value-Based Substantiation for the Chat-Quality Eval

**Date:** 2026-06-26
**Status:** Design (mini-plan for `/implement`) — no product/eval code written yet.
**Recommendation:** Option (i) — emit returned VALUE fields in `grounding_sample`.

---

## Root cause (confirmed by code + run artifacts)

The substantiation machinery in `scripts/chat_quality_judge.py` is **fully built and
correct** — claim regex (`_CLAIM_NUMBER_RE`), scale-suffix parsing (`B/M/K/T`, `%` in
`_SCALE_SUFFIX`), field-alias association (`_nearest_field`, `_FIELD_ALIASES`), and
rel/abs tolerance (`_values_within_tolerance`). It is **starved at the source**: the
only value-bearing channel is the streamed `grounding_sample.fields`, and for the
financial/comparison tools that map contains **only entity identifiers**
(`{"ticker":"NVDA","ticker_2":"AMD"}`).

Traced end to end:

1. **Tool handlers discard structured numbers.**
   `services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py` —
   `_handle_get_fundamentals_history_batch` (L674-709), `_handle_query_fundamentals`
   (L806-821), `_handle_get_fundamentals_history`, `_handle_compare_entities`. Each
   has the numeric rows in hand (`periods_data`, `snap_dict`, `rows`, `snapshot`) but
   renders them into a markdown `text` blob and **returns a `RetrievedItem` with no
   structured numeric fields** — only `citation_meta=CitationMeta(entity_name=ticker, …)`.

2. **`RetrievedItem` has no slot for them.**
   `services/rag-chat/src/rag_chat/domain/entities/chat.py` L134-156: frozen dataclass;
   `CitationMeta` (L124-131) carries only `title/url/source_name/published_at/entity_name`.
   No metric/extra dict.

3. **The sample builder can only read what is there.**
   `sse_emitter.py` `build_grounding_sample` (L707-816) + `_grounding_field_value`
   (L673-704). The allow-list *does* list `revenue, eps, gross_profit, pe_ratio,
   market_cap` (L638-659) — but the probe is `getattr(item,"revenue")` →
   `citation_meta.revenue` → `item.get("revenue")`, all `None`. Only `ticker` resolves
   (via the `entity_name` fallback, L697-700).

4. **The harness cannot recover the values.**
   `tests/validation/chat_eval/harness.py` L630-649 builds each `tool_results` entry
   from the **SSE `tool_result` event only** — `{tool, status, item_count,
   [grounding_sample]}`. The full rows never cross the SSE boundary (the item `text`
   isn't in that event either). **There is no harness-side copy of the payload.**

5. **Net effect in the run** (`run_20260626T013908Z`, 67 Qs): 30 Qs call a value tool,
   26 show `coverage:"verified"` — but "verified" only means *a sample dict was
   present*; since `ticker` is non-numeric, `_collect_grounding_fields` yields no float
   and every numeric claim is `unmatched`. **0 substantiated, 413 unmatched.** Worse:
   because `revenue`/`eps` aren't present even as *names*, claims associate to no field
   → `unmatched` (neutral), so they never reach the `unsupported` class. Coverage falsely
   reads "verified".

---

## Two options

### (ii) Capture full payloads in the harness — REJECTED
The harness only sees the SSE stream, and the `tool_result` event deliberately carries
no rows (it is the UI/eval contract). To make payloads available you would have to add a
new value-bearing field to the SSE event anyway — i.e. *exactly* option (i)'s backend
change, plus a second redaction/cap path in the harness. No saving; strictly worse.

### (i) Emit returned VALUE fields in the grounding sample — RECOMMENDED
Minimal, localized, already behind `CHAT_EVAL_GROUNDING_SAMPLES` (default OFF →
byte-identical prod frames, NFR-2). The matcher already consumes exactly this shape. Only
the *production of structured fields* is missing. **The entire fix is "stop discarding the
numbers the handler already computed."**

---

## Recommended implementation (option i)

**Design choice:** carry structured numbers on the item; do **not** re-parse the markdown
`text` (brittle — "$81.6B" loses precision, period columns ambiguous, duplicates
formatting logic).

### Change 1 — extensible field on `RetrievedItem`
`services/rag-chat/src/rag_chat/domain/entities/chat.py`
- Add `grounding_fields: tuple[tuple[str, str], ...] = ()` to `RetrievedItem`
  (frozen/hashable-friendly; ordered key→str-value pairs). Plumb through `create()` as an
  optional kwarg defaulting to `()`. No fusion-score impact (mirrors
  `extraction_confidence` / `graph_enrichment`). Generic bag keeps the domain entity
  tool-agnostic; the allow-list in `sse_emitter` stays the single gate on exposure.

### Change 2 — populate it in the four value handlers
`services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py` — emit the
**latest period** (+ snapshot scalars) as **raw, unscaled numeric** strings so the
matcher's scale logic stays authoritative:

| Tool | `grounding_fields` emitted (latest period unless noted) |
|---|---|
| `_handle_query_fundamentals` | `ticker` + each requested metric with `coverage=="ok"`: `revenue, eps, gross_profit, net_income, pe_ratio, forward_pe, market_cap, ebitda, free_cash_flow` (from `rows[-1]`/`snapshot`) |
| `_handle_get_fundamentals_history_batch` | per ticker: `ticker` + latest-period `revenue, eps, gross_profit, pe_ratio, market_cap` |
| `_handle_get_fundamentals_history` | same metric set, latest period |
| `_handle_compare_entities` | per entity row: `ticker` + the compare core metrics already computed |

Emit raw floats as strings (`"81600000000"`, `"1.87"`, `"0.586"`). Do **not** pre-scale;
`_sample_value_to_float` parses bare numbers and avoids double-scaling. **Skip any metric
whose coverage is `missing`/`partial`** so a value-less metric never enters as a phantom
number (correctly leaves gross-margin → `unsupported` when the agent asserts it).

### Change 3 — allow-list alignment
`sse_emitter.py` `_GROUNDING_FIELD_ALLOWLIST` (L638-659): extend the fundamentals/compare
entries to the metric set above (add `net_income, forward_pe, ebitda, free_cash_flow`).
Add `get_quote` → `("ticker","price","change_pct")` if a quote tool exists in the
registry. Keep `GROUNDING_MAX_FIELDS_PER_ROW` at 8 (5 metrics + ticker fits).

### Change 4 — builder reads the new field
`sse_emitter.py` `_grounding_field_value` (L673-704): after the direct-attr /
citation_meta probes, add a lookup into `item.grounding_fields` (dict-ify the tuple once).
This is the one builder edit; caps, redaction, byte-budget and `revenue_2` suffixing
already work.

### Matcher changes — none required; two optional hardenings
The matcher already handles scale, `%`, commas, `$`, aliases, and `revenue_2`
normalization (`_collect_grounding_field_names` strips `_\d+$`). Optional:
- **Period alignment:** we emit only the latest period, so cross-period false-contradiction
  is unlikely; leave multi-period out of v1.
- **Margin as ratio vs %:** if a handler emits `gross_margin` as a ratio (`0.586`) but the
  answer says "58.6%", add `gross_margin`/`net_margin`/`operating_margin` to a small
  "percent-valued" set in the judge so a `%` claim is compared against `ratio*100`. Cheap,
  one dict.

---

## Value-field schema (the `grounding_fields` entries)

Per row, a flat key→string-number map. Keys are canonical snake_case metric names matching
`_FIELD_ALIASES`. Values are `str(raw_float)` (unscaled, no `$`/`%`/commas). Example for
NVDA latest quarter:

```
(("ticker","NVDA"), ("revenue","81600000000"), ("eps","1.87"),
 ("gross_profit","..."), ("pe_ratio","..."), ("market_cap","..."))
```

---

## Test plan
- **Unit (handlers)** `services/rag-chat/tests/.../handlers/test_market.py`: each of the 4
  handlers, given a fixture S3 response, returns a `RetrievedItem` whose `grounding_fields`
  has the expected raw numbers for the latest period; a `missing`-coverage metric is absent.
- **Unit (builder)** existing `sse_emitter` tests: `build_grounding_sample(
  "get_fundamentals_history_batch", [item_with_grounding_fields])` → `fields` contains
  `revenue`/`eps` (not just `ticker`); caps/redaction hold; flag-off path unchanged.
- **Unit (judge)** `scripts/tests/test_substantiation_check.py` +
  `test_grounding_cross_check.py`: smoke — answer `"Revenue $81.6B, EPS $1.87"` +
  `grounding_sample.fields={"revenue":"81600000000","eps":"1.87"}` → `substantiated==2,
  unmatched==0`; contradiction case (`"$200B"` → `contradicted==1`).
- **Harness regression:** `grounding_sample` with numeric fields round-trips through
  `harness.py` verbatim (already does — no change there).
- **E2E smoke (1 Q):** re-run `ru_nvda_amd_compare_qtr` with
  `CHAT_EVAL_GROUNDING_SAMPLES=true` → `substantiated > 0`.

---

## Expected coverage effect
- **30 / 67** run questions invoke a value-bearing tool → become verifiable (today: 0).
  The remaining 37 are news/relationship/screener/refusal/signal with no numeric tool
  claim to substantiate (correctly stay `presumed`/`unmatched`).
- The degenerate `413 unmatched / 0 substantiated / 26 false-"verified"` becomes a real
  signal: financial Qs report meaningful `substantiated`/`contradicted`/`unsupported`
  counts, and "verified" coverage stops being vacuous.

---

## Files to touch (exact)
1. `services/rag-chat/src/rag_chat/domain/entities/chat.py` — add `grounding_fields` to
   `RetrievedItem` + `create()`.
2. `services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py` — populate it in
   `_handle_query_fundamentals`, `_handle_get_fundamentals_history`,
   `_handle_get_fundamentals_history_batch`, `_handle_compare_entities`.
3. `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py` —
   `_grounding_field_value` reads `grounding_fields`; extend `_GROUNDING_FIELD_ALLOWLIST`.
4. *(optional)* `scripts/chat_quality_judge.py` — percent-valued field set for margins.
5. Tests as above.

**No prod behavior change** (flag default OFF; legacy 4-key SSE payload byte-identical).
**No new SSE field, no harness change, no DB/migration.**
