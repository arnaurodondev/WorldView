# Brief Quality Re-Eval — 2026-06-14 (independent live verification)

Skeptical re-verification of the 5 bug fixes shipped in rag-chat / brief-scheduler
(prompts instrument **v4.3**, morning **v4.8**). All briefs generated LIVE through S9
(:8000) with the Valkey cache busted (`DEL briefing:instrument:v2:{eid}` for instrument;
morning via `POST /briefings/morning/generate` which always regenerates). Containers
confirmed running NEW images (rag-chat + brief-scheduler "Up ~minutes"); in-container
`prompts/briefing/instrument.py version="4.3"`, `morning.py` v4.8 history present.

Entities: AAPL `…1001`, GOOGL `…1003`, NVDA `…1006`. Morning portfolio: 10 holdings.
All generations HTTP 200/202, `cached=False` (instrument) / distinct `generated_at`
05:10:18 vs 05:10:55 (morning, 2 fresh runs).

## PASS/FAIL table

| # | Check | Verdict | Live evidence (one line) |
|---|-------|:---:|---|
| BUG 1 | Instrument KG citations resolve | **PASS** | All 3 OV open with `Entity definition (KG)` (doc=`kg-definition:…`) + `Thematic context (KG)` (doc=`kg-narrative:…`) real text — AAPL OV[0] cite = "Entity definition (KG)". |
| BUG 2 | Price & Fundamentals section renders | **PASS** | All 3 have non-empty "Price & Fundamentals"; every bullet cites `Fundamentals snapshot (structured data)`; literal `[fundamentals_context]` present = False in all 3. |
| BUG 3 | Staleness caveat deterministic | **PASS** | Caveat present in the narrative block of all 3: AAPL "this thematic context is ~25 days old and is not a recent catalyst"; GOOGL "~25 days old and is NOT a recent catalyst"; NVDA "[STALE 25 days] … background only and not a recent catalyst". |
| BUG 4 | Morning sign/attribution gate | **PASS** | AMZN both runs: "the [c2] Graviton5 story is positive but the stock is down … net effect unclear" — no DOWN move asserts a positive same-topic article as driver; every neg-move bullet hedged, 0 asserted_driver. |
| BUG 5 | No stray market-snapshot cite / no range markers | **PASS** | Market-Snapshot "SPY +0.50%, QQQ +0.46%, VIX 21.38" carries no `[cN]` in either run; range markers `[cA-cB]` = NONE both runs; sector line uses literal `[sector line]` not an article cite. |
| REG A | Instrument OV opens from definition | **PASS** | OV[0] cite = "Entity definition (KG)" for AAPL/GOOGL/NVDA (never financials). |
| REG B | Morning 0 filler / grounded drivers survive | **PASS** | Fabricated filler = 0 both runs; GOOGL `[c1]` + TSLA `[c6]` "driven by … positive sentiment aligns" still surface (not collapsed to idiosyncratic). |
| REG C | All `[cN]` resolve / no new dangling markers | **PASS** | Instrument section bullets carry no inline markers; lead residual after frontend strip = NONE; morning markers all in-range (≤55), residual after strip = NONE, no ranges. |

## Notes / minor residual observations (not blocking)
- **BUG 3 granularity**: the KG narrative is rendered as TWO thematic bullets; the caveat
  is attached to ONE of them (GOOGL bullet[1], NVDA bullet[2]), not repeated on the second
  thematic sentence. The narrative BLOCK always carries the caveat now (vs 2/5 before), so
  the determinism fix holds; per-sentence repetition is a cosmetic nicety, not a regression.
- **Raw `narrative`/`lead` fields** still contain inline `[cN]` markers by design. The
  frontend (`StructuredBrief.LeadProse`) strips `\[c\d+\]` and `\[N\d+\]` and renders
  citation chips, so the RENDERED surface is clean. Because no range markers are emitted,
  nothing escapes the single-marker strip. Instrument briefs are rendered from the structured
  `sections` (already marker-free) plus the cleaned `lead`.
- **Sector line marker fix**: previously `[c1]` (an Alphabet article) was mis-attached to
  META's sector claim; now a literal `[sector line]` token is used and the sector figure
  comes from joined context, not a citation.

## Verdict
The briefs are now **production-quality**: all 5 fixes hold end-to-end on cache-busted live
generations, and no regression was introduced. Single most important remaining gap (minor):
the morning brief's `[sector line]` literal token is not a resolvable citation chip — it will
render as bare text in the UI unless the frontend special-cases it; consider mapping it to a
"Sector context (structured)" chip for parity with the instrument KG/fundamentals chips.
