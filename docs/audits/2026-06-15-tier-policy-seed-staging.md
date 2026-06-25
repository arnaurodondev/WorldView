# Tier-1/Tier-2 Tickerless-Company Ingestion Policy Seed — Staging Note

**Date:** 2026-06-15
**Author:** market-data ingestion (automated build + dry-run)
**Status:** STAGED — built, resolved, dry-run. **NOT applied.** No git commit.
**Script:** `scripts/data/seed_tier_policies.py` (+ `test_seed_tier_policies.py`)
**Upstream context:** `docs/audits/2026-06-14-tickerless-instrument-companies-followup.md`
("## Relevance & coverage analysis")

---

## Why this is staged, not applied (GATING)

EODHD daily quota is **exhausted**: confirmed via
`GET https://eodhd.com/api/user` on 2026-06-15 →
`"apiRequests":100000, "dailyRateLimit":100000, "extraLimit":0`.

Adding new EODHD-fundamentals (and EODHD OHLCV) polling policies now would
schedule calls that immediately fail against a 0-headroom quota. A parallel
investigation is assessing whether news polling can be optimized to free quota.
`--apply` runs **only after**: (a) the EODHD-budget investigation lands,
(b) the `AAPL.MX` / exchange-qualified matching fix lands, and (c) quota has
headroom. Until then: **build + resolve + dry-run + stage only.**

---

## Verified per-policy-kind tuples (mirrored exactly from live data)

Read straight from existing fully-covered symbols (`A`, `ACGL`, `ABT`) — the
dominant cluster present for ~450–630 live symbols. A new symbol is therefore
indistinguishable from one the platform already ingests.

| # | provider | dataset_type | variant | timeframe | base_int | min_int | jitter | priority | tier | enabled |
|---|----------|--------------|---------|-----------|----------|---------|--------|----------|------|---------|
| 1 | alpaca | ohlcv | (none) | 1m  | 60    | 60   | 5   | 100 | **= candidate tier** | true |
| 2 | eodhd  | ohlcv | (none) | 1d  | 21600 | 3600 | 60  | 5   | 2 | true |
| 3 | eodhd  | ohlcv | (none) | 1w  | 43200 | 3600 | 60  | 4   | 2 | true |
| 4 | eodhd  | ohlcv | (none) | 1mo | 86400 | 3600 | 60  | 3   | 2 | true |
| 5 | eodhd  | fundamentals | General | (none) | 86400 | 3600 | 300 | 2 | 2 | true |

- **Provider split:** Alpaca serves the 1m OHLCV stream; EODHD serves the daily/
  weekly/monthly OHLCV bars + the `General` fundamentals dataset. (Verified.)
- **Tier:** only the Alpaca 1m policy tracks the candidate's tier (Alpaca OHLCV
  rows are tier-1 in the live data); all EODHD rows are uniformly tier=2, mirrored.
- Other defaults set explicitly: `enabled=true`, `market_hours_only=false`,
  `post_market_only=false`, `backfill_enabled=false`, `backfill_chunk_days=30`,
  `adaptive_*` left at DB defaults.
- **`id`:** 26-char ULID via `common.ids.new_ulid` (e.g. `01HXD71F64D9BF2A312CF6A23D`).

## Idempotency / unique constraint

There is **no unique constraint** on `polling_policies` — only the **non-unique**
matching index `ix_polling_policies_matching` on
`(provider, dataset_type, dataset_variant, symbol, exchange, timeframe)`.
The script de-dups itself: before each insert it `SELECT`s for an existing row on
exactly that 6-tuple (NULL-safe via `IS NOT DISTINCT FROM`) and skips if present.
Re-runs are a no-op for already-seeded / pre-existing symbols.

---

## Resolved Tier-1-US apply-ready list (36 symbols)

High-confidence, unambiguous **US-primary-listed common stock**, resolved by hand
from the Tier-1 head of the tickerless-FI mention ranking. `count` = news-corpus
entity mentions (tier-1 = ≥5). Symbols already covered in the live table are
**skipped automatically** by idempotency (flagged below).

| symbol | name | mentions | live status |
|--------|------|----------|-------------|
| NKE  | NIKE | 139 | already present (skipped) |
| MRVL | Marvell Technology | 105 + 34 ("Marvell") | NEW |
| CTRN | Citi Trends Inc | 118 | NEW |
| WDC  | Western Digital | 77 | already present (skipped) |
| ITIC | Investors Title Co. | 74 | NEW |
| MU   | Micron Tech | 67 | already present (skipped) |
| TMHC | Taylor Morrison Home | 66 | NEW |
| DECK | Deckers Outdoor Corp | 51 | already present (skipped) |
| RDW  | Redwire | 42 | NEW |
| PINS | Pinterest | 41 | NEW |
| NEM  | Newmont Corp (Newmont Mining) | 37 | already present (skipped) |
| ATI  | ATI Inc. | 36 | NEW |
| RH   | RH (Restoration Hardware) | 34 | NEW |
| GFS  | GlobalFoundries Inc. | 32 | NEW |
| SYK  | Stryker | 30 | NEW |
| BF.B | Brown-Forman (Class B) | 29 | NEW (no Alpaca 1m — dotted ticker) |
| SMCI | Super Micro | 24 | partially present (alpaca skipped) |
| FIBK | First Interstate BancSystem | 23 | NEW |
| WHR  | Whirlpool | 22 | NEW |
| RGTI | Rigetti Computing | 22 | NEW |
| TPR  | Tapestry | 21 | NEW |
| PEBO | Peoples Bancorp | 21 | NEW |
| ALGM | Allegro MicroSystems | 21 | NEW |
| PLD  | Prologis | 20 | partially present |
| MCK  | McKesson | 19 | partially present |
| LHX  | L3Harris | 16 | partially present |
| IAC  | IAC Inc. | 16 | NEW |
| AAOI | Applied Optoelectronics | 16 | NEW |
| CPA  | Copa Holdings | 16 | NEW |
| SMTC | Semtech Corp | 18 | NEW |
| PLUS | ePlus Inc | 18 | NEW |
| BB   | BlackBerry (NYSE) | 18 | NEW |
| ROG  | Rogers Corp | 17 | NEW |
| CELH | Celsius Holdings | 17 | NEW |
| ETN  | Eaton Corp. Plc (NYSE) | 17 | partially present |

> NOTE: `BF.B` is a dotted (class-B) US ticker — kept because it is a genuine
> US-primary listing, not an exchange-qualified foreign artifact. Its Alpaca 1m
> policy is absent in the dry-run only because Alpaca uses a different class
> notation; the EODHD policies seed correctly. Confirm Alpaca symbology before apply.

### Dry-run result for the resolved Tier-1-US list

```
--tier 1 (full set):      118 new rows  | skipped 62 (already present)
  alpaca:ohlcv          22
  eodhd:fundamentals    24   <-- NEW EODHD-fundamentals = the quota impact
  eodhd:ohlcv           72

--tier 1 --only-ohlcv:     94 new rows  | skipped 50
  alpaca:ohlcv          22
  eodhd:ohlcv           72
  eodhd:fundamentals     0
```

**Quota impact of a full `--apply`: 24 new EODHD-fundamentals policies + 72 new
EODHD OHLCV-bar policies** (96 new EODHD-scheduled streams total). `--only-ohlcv`
drops the 24 fundamentals streams. Verified the dry-run wrote nothing (table row
count unchanged at 3045; `MRVL` still 0 policies).

---

## Deferred list (needs EODHD resolution / listing decision — NOT seeded)

### Foreign / ADR-ambiguous (local-vs-ADR listing choice — resolve post-quota)
Samsung Electronics, Toyota / Toyota Motor, Alibaba, Roche, Lenovo Group, Infineon,
Rio Tinto Group, SK Telecom, Saputo, Coca-Cola Europacific Partners, Nebius, IREN
Ltd., BYD Company, Xiaomi, CNOOC, SAIC Motor, Iberdrola, TeamViewer, Volvo Group,
ABB, Bekaert, Worley, Kuehne+Nagel, Nippon Paint, NEC, Sigma Healthcare, UCB,
Zealand Pharma, Pembina Pipeline, Brookfield (Renewable/Infrastructure/Corp),
Usinas Siderurgicas, Copa* (kept — US-listed), etc.
→ Need EODHD to pick the right exchange suffix (`.US` ADR vs local `.KO/.T/.HK/...`).

### Non-instrument noise (exclude entirely — not ingestion targets)
ETFs, iShares, SOXX, JEPI, VIG, VOOG, FTEC, FMS, SMCX, CONL, TMV, SNPD; index
funds / mutual funds / hedge funds; Cash, 401(k), IRA, Roth IRA, REIT(s), Treasuries
/ U.S. Treasury / Treasury bills, municipal bonds, ABS, CMBS, "notes due 2029",
"senior notes due 2032", "Preferred Stock Series MM", EPS, "American depositary
receipt/share", A-shares, stablecoins, ADA, credit card. (Many are data-quality
mistypes flagged by `reprofile_tickerless_entities.py`.)

### Excluded — exchange-qualified / foreign-listing artifacts (separate matching fix)
`NVDA.US`, `AVGO.US`, `SPCX.US`, `NYSEARCA:GLD`, and any `EXCH:SYM` / `*.MX/.BA/.SN`
forms. These are a **matching-fix** concern (the `AAPL.MX` work), **not** new
ingestion targets, and are explicitly excluded by the resolver.

### All of Tier-2 (1–4 mentions, ≈232 names) — DEFERRED
Long tail; resolve names→tickers via EODHD symbol search **after** quota recovers.
The script already supports `--tier 2` / `--tier all`; `TIER2_US_CANDIDATES` is
intentionally empty until EODHD resolution is run.

---

## How to apply (orchestrator, post-gate)

```bash
source .venv312/bin/activate
# Preferred staged rollout — OHLCV first (lighter EODHD cost), fundamentals later:
python scripts/data/seed_tier_policies.py --tier 1 --only-ohlcv --apply
python scripts/data/seed_tier_policies.py --tier 1 --apply   # adds the 24 fundamentals
```

Confirm EODHD `apiRequests < dailyRateLimit` with meaningful headroom first.
