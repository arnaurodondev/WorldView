# Morning Brief Quality Eval — Root-Cause Attribution Enhancement

Date: 2026-06-14 · Evaluator: adversarial QA · Method: 3 live force-regens + DeepSeek-V4-Flash judge (2 passes)
Endpoint: `POST /v1/briefings/morning/generate` (force regen, 202 + sync gen) → `GET /v1/briefings/morning` (S9 @ :8000)
Containers: rag-chat, brief-scheduler, api-gateway all healthy. Demo portfolio: AAPL MSFT NVDA AMZN TSLA GOOGL META JPM NFLX DIS.

## Aggregate (3 runs, 10 holdings each)

| Run | Grounded (entity news + cite) | Sector-attributed | Honest "idiosyncratic — no driver" | FABRICATED filler | [cN] resolution | Leaked [N#]/[Nx] |
|-----|---|---|---|---|---|---|
| 1 | 3 (TSLA, GOOGL, AMZN) | 1 (META) | 6 | 0 | 8/8 in-range | none |
| 2 | 3 (TSLA, GOOGL, AMZN) | 1 (META) | 6 | 0 | 8/8 in-range | none |
| 3 | 3 (TSLA, GOOGL, AMZN) | 1 (META) | 6 | 0 | 7/7 in-range | none |
| **avg** | **3.0** | **1.0** | **6.0** | **0.0** | **100% in-range** | **0** |

- Citation list size: 56 every run; markers are 1-indexed (`[c1]` = citations[0]).
- ZERO forbidden filler ("momentum-driven" / "riding the rally" / "tracking the broader market") in any run.
- ZERO leaked old-form `[N#]`/`[Nx]` markers — the migration to `[cN]` is clean and the frontend-strip is not even needed at this layer.
- The ladder is visibly working: entity-news for the movers, sector for META, honest "idiosyncratic — no identifiable driver" for the 6 flat/no-news names.

## BEST grounded bullets (driver + resolved citation)

- Run1: `GOOGL +3.13% pre-mkt — driven by the Alphabet Search AI and mobility revenue story [c1]; adds $110 despite its sector being -0.21%`
  → `[c1]` = "Alphabet Ties Search AI And Mobility Closer To Revenue Potential". Relevant article, correct ticker, AND flags the sector divergence. Textbook.
- Run1: `TSLA +3.17% pre-mkt — driven by the SpaceX IPO-day narrative and Cathie Wood's move [c6]`
  → `[c6]` = "Longtime SpaceX Investor Cathie Wood Made This Move on IPO Day." Real, resolvable, topical.
- Run1 (honest divergence handling): `AMZN -0.88% ... (the Graviton5 chip news [c2] is positive but the Oracle wealth story [c9] is negative; net effect unclear)` — refreshingly candid about contradictory signals rather than inventing a clean cause.

## FAILED / weak attributions (the real remaining gap)

The failure mode is no longer fabricated *filler* — it is **causal over-attribution against topically-adjacent citations**. The cited article is real and on-topic, but does not establish the cause→price-move link asserted:

- AMZN every run: `-0.88% ... driven by the Graviton5 chip story [c2]` — `[c2]` = "Amazon Graviton5 Chip Aims To **Deepen** AWS AI Margins And Moat" — a *positive* article used to explain a *negative* move ("sell the news" / "margin pressure" are the model's invention, not the article's).
- AMZN: `Oracle's collapse [c9/c10] is a tangential headwind` — `[c10]` = "Oracle Stock Collapse Hits Larry Ellison's Wealth" — no Amazon linkage at all.
- Run3: `META +0.55% — tracking Communication Services -0.21% [c1]` — `[c1]` is an **Alphabet** article, not a sector-index source. The sector figure (-0.21%) is real (it comes from joined sector context, not the citation), but the `[c1]` marker on a sector claim is mis-attached.
- **Marker-accuracy bug**: `[c13]` on the Market-Snapshot SPY/QQQ/VIX line resolves to an UNRELATED article that changes run-to-run — Run1 "Why Rocket Lab stock tumbled", Run3 "IMAAVY Breakthrough ... Johnson And Johnson". The macro/market line should not carry an article citation; it's grabbing a random alert/article id.
- Run3 introduced a non-standard range marker `[c13-c20]` ("Multiple GRAPH_CHANGE alerts") — not a clean `[cN]` and would render oddly.

## DeepSeek-V4-Flash judge (temp=0, 2 passes — identical both passes, low variance)

| Run | Groundedness | Honesty | Usefulness | Verdict |
|-----|---|---|---|---|
| 1 | 7 | 8 | 7 | WEAK |
| 2 | 7 | 9 | 8 | WEAK |
| 3 | 6 | 7 | 6 | WEAK |

Judge consensus weakest point (all 3 runs): drivers attributed to citations that are real but do **not** support the claimed cause-effect — concentrated on AMZN (positive Graviton5 article used for a negative move; unrelated Oracle story), and the TSLA/SpaceX and META/sector marker mis-attachments. Honesty scores high (6 honest-idiosyncratic calls per run are correct); groundedness is the ceiling.

## Bottom line

The enhancement **delivered against the headline baseline**: fabricated *filler* drivers went from **7/10 → 0/10**, and grounded/honest attribution went from **3/10 grounded → 4/10 attributed (3 entity + 1 sector) + 6/10 honestly idiosyncratic, with 0 fabricated filler**. Citation migration to `[cN]` is clean (100% in-range resolution, zero leaked old-form markers). The brief now explains WHY, with sector-divergence callouts and candid "net effect unclear" handling. Usefulness ~3.5–4/5.

**Top remaining quality gap**: causal over-attribution to topically-adjacent citations (the judge's WEAK verdict), worst on AMZN where a *positive* article ([c2] Graviton5) is repeatedly invoked to "explain" a *negative* move, plus the macro/market-snapshot line attaching a random, run-varying article id (`[c13]`). These resolve-in-range but are semantically wrong — the next fix is a relevance/sign gate: a citation may only back a driver if the article's subject entity == the holding AND its sentiment sign is consistent with the move (or the bullet must downgrade to sector/idiosyncratic). Range markers like `[c13-c20]` should also be normalized.
