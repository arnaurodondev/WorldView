# Instrument Brief Quality Eval — 2026-06-14

Adversarial QA of the per-company DAILY BRIEF after the v4.2 definition-first +
"make KG definition/narrative CITABLE" enhancement. Live generation via
`GET /v1/briefings/instrument/{entity_id}` (gateway :8000), Valkey cache busted
(`DEL briefing:instrument:v2:{eid}`) before each call. 5 entities, all HTTP 200.

## Per-entity scorecard

| Entity | OV opens from definition | Def+narr citations resolve (KG) | Staleness caveat | Hallucination | Usefulness (1-5) |
|--------|:---:|:---:|:---:|---|:---:|
| AAPL   | YES | **NO** | yes | mis-grounded citations | 3 |
| GOOGL  | YES | **NO** | **no** | mis-grounded citations | 3 |
| JPM    | YES | **NO** | yes | mis-grounded citations | 3 |
| TSLA   | YES | **NO** | **no** | mis-grounded citations | 3 |
| NVDA   | YES | **NO** | **no** | mis-grounded citations | 3 |

## What WORKS (v4.2 ordering fix — real win)
Every Entity Overview opens with the verbatim KG business definition, never with
price/market-cap/P-E. DeepSeek V4 Flash judge on the isolated OV section:
`opens_with_identity=true` and PASS for all 5 (ordering 8-9/10).

- **AAPL OV[0]:** "Apple Inc. designs, manufactures, and markets smartphones, personal
  computers, tablets, wearables, and accessories worldwide." (= DB `description` verbatim)
- **JPM OV[0]:** "JPMorgan Chase & Co. operates as a financial services company worldwide,
  offering consumer banking, commercial banking, and investment banking services."

## HEADLINE FAILURE 1 — KG citations do NOT resolve (offset mismatch)
0 of 5 briefs contain any "Entity definition (KG)" / "Thematic context (KG)" citation.
The raw LLM markdown DOES emit the right markers (AAPL OV bullets carry `[c14]`/`[c15]`),
but they resolve to the WRONG citations:
- `[c14]` → event "Apple unveiled its much-anticipated Siri update"
- `[c15]` → event "Apple is preparing a foldable iPhone"

Root cause: prompt/parser offset disagreement (the exact silent-drop class the code
comment at `brief_context_formatter.py:613 kg_description_offset` claims to fix).
`kg_description_offset` counts `events[:6]` (cap 6) → tells the LLM definition=`[c14]`.
But the final citation list (`materialize_brief_citations`) appends **20 events, no cap of 6**
(AAPL: 7 articles + 20 events = 27 cites). So positions 14/15 are events, and the KG
citations land out of range / are filtered out (KG present = **False** in all 5).
Net: the definition/narrative bullets are mis-attributed to unrelated event citations.

## HEADLINE FAILURE 2 — Price & Fundamentals section dropped in ALL 5
The LLM generates a full "### Price & Fundamentals" section in the raw markdown
(AAPL: "Market cap stands at $4.31T ... P/E TTM is 35.468 ... [fundamentals_context]"),
but the parsed/served brief has only 3 sections (Entity Overview, Recent Developments,
Key Events) — **no Price & Fundamentals** for any entity. The section is dropped because
`[fundamentals_context]` is not a numeric `[cN]` marker, so the backfill/uncited-bullet
pass discards those bullets. Fundamentals-as-support layer never reaches the user.

## FAILURE 3 — Staleness caveat inconsistent (2/5)
Narratives are **25 days old** (generated 2026-05-21), far past the prompt's "~1 week"
assumption. Caveat present only for AAPL ("though this context is not a recent catalyst")
and JPM. GOOGL/TSLA/NVDA layer the stale narrative theme into OV with NO caveat:
- **TSLA OV[1]:** "The company is a leading EV manufacturer with high exposure to the
  Electric Vehicles theme and is actively exploring AI integration..." (no caveat)
- **NVDA OV[1]:** "The company is a leading AI/ML enabler with significant exposure to the
  rapidly evolving AI sector..." (no caveat)

## Marker behaviour
`[cN]` markers in the **lead** DO resolve positionally to real article/event citations
(AAPL lead `[c3][c5][c17]` → Tariff article / WWDC-decline article / Tim-Cook event — correct).
No raw `[N#]`/`[Nx]` leaks. But OV-bullet markers mis-resolve (Failure 1) and
`[fundamentals_context]` causes section loss (Failure 2).

## DeepSeek V4 Flash judge
- Full-brief pass (LEAD+DETAILS) had high variance — judge conflated the LEAD (legitimately
  catalyst-led) with the Overview, giving false FAILs (NVDA 0, JPM 2).
- Isolated-OV pass (correct unit of evaluation): **5/5 PASS, opens_with_identity=true,
  ordering 8-9/10, usefulness 4/5.** Ordering fix validated.

## Coverage
All 5 entities have a definition (296-327 chars) and a current narrative (70-96 words) in
intelligence_db — no coverage gap. The gaps here are pipeline/parser bugs, not missing data.

## Bottom line
- Definition-first ordering: **SHIPPED and working** (5/5, never leads with financials).
- KG citations resolving to "Entity definition (KG)"/"Thematic context (KG)": **BROKEN** (0/5;
  offset mismatch mis-attributes them to event citations).
- Top remaining gaps: (1) the events-cap mismatch between `kg_description_offset` (`[:6]`) and
  `materialize_brief_citations` (uncapped) — fix to restore KG citation resolution;
  (2) parser drops the entire Price & Fundamentals section on the non-numeric
  `[fundamentals_context]` marker; (3) stale-narrative caveat fires only 2/5.
