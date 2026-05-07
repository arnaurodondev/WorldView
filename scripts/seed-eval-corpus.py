#!/usr/bin/env python3
"""Seed script: inserts synthetic eval corpus into intelligence_db.

Run: python3 scripts/seed-eval-corpus.py
Env vars:
  OLLAMA_URL  - default http://localhost:11434
  EVAL_DB_URL - default postgresql://postgres:postgres@localhost:5432/intelligence_db
"""

from __future__ import annotations

import os
import time
import uuid

import httpx
import psycopg2

EVAL_NS = uuid.UUID("a0b1c2d3-0000-5000-8000-ea0100000000")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EVAL_DB_URL = os.environ.get(
    "EVAL_DB_URL",
    "postgresql://postgres:postgres@localhost:5432/intelligence_db",
)

# ---------------------------------------------------------------------------
# Corpus definition — 225 synthetic financial text chunks
# Each entry: dict with all fields except embedding (added at runtime)
# ---------------------------------------------------------------------------
CORPUS: list[dict] = [
    # ── Apple ──────────────────────────────────────────────────────────────
    {
        "key": "apple_10k_2025_highlights",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2025-11-01T16:00:00Z",
        "title": "Apple Inc. Annual Report (Form 10-K) Fiscal Year 2025",
        "text": (
            "Apple Inc. (AAPL) filed its Annual Report on Form 10-K for the fiscal year ended "
            "September 27, 2025. Total net sales were $414.5 billion, an increase of 6% "
            "year-over-year. iPhone revenue reached $213.8 billion, representing 51.6% of total "
            "revenue, up 4% from fiscal 2024. Services revenue grew 13% to $96.2 billion, "
            "driven by growth in the App Store, Apple Music, iCloud, and Apple TV+. Mac revenue "
            "was $31.4 billion, up 7%, while iPad revenue declined 2% to $26.1 billion. "
            "Wearables, Home and Accessories revenue was $37.0 billion, down 3%. Gross margin "
            "expanded to 46.9%, compared to 45.6% in fiscal 2024, reflecting favorable mix shift "
            "toward higher-margin Services. Operating income was $123.2 billion with an operating "
            "margin of 29.7%. Net income was $101.4 billion, or $6.73 per diluted share. "
            "The company returned $110 billion to shareholders through dividends and buybacks. "
            "Capital expenditures were $11.2 billion. Apple ended the year with $64.5 billion "
            "in cash and marketable securities. The company employed approximately 164,000 "
            "full-time equivalent employees worldwide."
        ),
        "query_classes": ["factual_lookup", "financial_data"],
    },
    {
        "key": "apple_q2_2026_transcript_iphone",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T21:00:00Z",
        "title": "Apple Inc. Q2 FY2026 Earnings Call Transcript — iPhone Revenue Discussion",
        "text": (
            "TIM COOK: Thank you, Suhasini. Our iPhone revenue in Q2 fiscal 2026 was $53.7 billion, "
            "up 7% year-over-year, driven by exceptional demand for iPhone 17 Pro and iPhone 17 Pro Max. "
            "Unit volumes grew 5% globally, with particularly strong performance in China where we saw "
            "17% revenue growth despite a challenging macro environment. The iPhone 17 lineup continued "
            "to set customer satisfaction records at 97% satisfaction among recent purchasers. "
            "LUCA MAESTRI: Looking ahead to fiscal Q3 2026, we expect iPhone revenue to grow in the "
            "mid-single-digit range year-over-year. We anticipate total company revenue between "
            "$88 billion and $91 billion for Q3, with iPhone being the primary driver. Gross margin "
            "guidance is 47.0% to 47.5%, reflecting continued Services mix benefits. We expect "
            "operating expenses in the range of $15.3 billion to $15.5 billion. Services revenue "
            "is expected to grow in the mid-teens percentage range versus the prior year quarter. "
            "This guidance accounts for approximately $900 million of expected foreign exchange headwinds."
        ),
        "query_classes": ["factual_lookup", "comparison"],
    },
    {
        "key": "apple_q2_2026_transcript_services",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T21:00:00Z",
        "title": "Apple Inc. Q2 FY2026 Earnings Call Transcript — Services Revenue Segment",
        "text": (
            "LUCA MAESTRI: Services revenue reached $26.3 billion in fiscal Q2 2026, a record for any "
            "quarter, representing growth of 15% year-over-year. This growth was broad-based across "
            "all services categories. The App Store grew double-digits, driven by gaming and productivity "
            "applications. Apple Music and Apple TV+ subscriptions combined exceeded 950 million paid "
            "subscribers globally, up 12% from a year ago. iCloud storage revenue grew 18% as we "
            "benefited from strong adoption of iCloud+. Apple Pay transaction volume increased 35% "
            "year-over-year as more merchants enabled tap-to-pay. The gross margin on Services was "
            "approximately 74.9%, significantly higher than our Products gross margin of 38.2%, "
            "which is why Services mix expansion is structurally beneficial to overall gross margins. "
            "We now have over 2.3 billion active devices in our installed base, which is the largest "
            "we have ever reported and provides a growing addressable market for our Services business."
        ),
        "query_classes": ["factual_lookup", "reasoning"],
    },
    {
        "key": "apple_q2_2026_transcript_guidance",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T21:00:00Z",
        "title": "Apple Inc. Q2 FY2026 Earnings Call — Q3 Forward Guidance Statement",
        "text": (
            "LUCA MAESTRI: For the fiscal third quarter of 2026, we expect revenue to be between "
            "$88 billion and $91 billion, which represents growth of approximately 10% to 14% "
            "year-over-year at the midpoint. iPhone revenue guidance is for mid-single-digit growth. "
            "Services revenue is expected to grow in the mid-teens year-over-year. We expect gross "
            "margin of 47.0% to 47.5%. Operating expenses are expected to be between $15.3 billion "
            "and $15.5 billion. OI&E is expected to be around $300 million. And our tax rate is "
            "expected to be approximately 15.0%. We continue to expect to generate very strong "
            "operating cash flow and remain committed to our capital return program, having "
            "authorized an additional $110 billion in share repurchases and increased our quarterly "
            "dividend by 4% to $0.26 per share during the quarter."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "apple_q2_2026_8k_press_release",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T20:30:00Z",
        "title": "Apple Inc. Form 8-K: Q2 FY2026 Financial Results Press Release",
        "text": (
            "CUPERTINO, California — May 1, 2026 — Apple Inc. today announced financial results for "
            "its fiscal 2026 second quarter ended March 29, 2026. The Company posted quarterly revenue "
            "of $95.4 billion, up 6 percent year over year, and quarterly earnings per diluted share "
            "of $1.65, up 8 percent year over year. 'We are thrilled to report record revenue for the "
            "March quarter,' said Tim Cook, Apple's CEO. 'Our performance was driven by strong iPhone "
            "sales and another quarter of double-digit Services growth.' iPhone revenue: $53.7B (+7% YoY). "
            "Mac revenue: $7.9B (+3% YoY). iPad revenue: $6.4B (-1% YoY). Services revenue: $26.3B (+15% YoY). "
            "Wearables: $7.5B (-4% YoY). Gross margin: 46.9%. Operating income: $29.0B. Net income: $24.8B. "
            "The Board of Directors declared a cash dividend of $0.26 per share of the Company's common stock, "
            "an increase of 4 percent. The Board also authorized a new program to repurchase up to $110 billion "
            "of the Company's common stock."
        ),
        "query_classes": ["factual_lookup", "comparison"],
    },
    {
        "key": "apple_q1_2024_gross_margin",
        "source_type": "sec_10q",
        "source_name": "sec_edgar",
        "published_at": "2024-02-02T16:00:00Z",
        "title": "Apple Inc. Form 10-Q: Q1 FY2024 — Gross Margin Analysis",
        "text": (
            "Apple Inc. reported gross margin of 45.9% for the fiscal first quarter ended December 30, 2023, "
            "compared to 42.9% in the prior year quarter. Products gross margin was 39.4%, up 310 basis points "
            "year-over-year, driven by favorable commodity costs and manufacturing efficiencies. Services gross "
            "margin was 72.8%, down slightly from 74.1% in the prior year due to increased content investment "
            "in Apple TV+. Total gross profit was $40.4 billion on net sales of $119.6 billion. iPhone gross "
            "profit contribution was $22.8 billion at a blended margin of approximately 42%. Mac contributed "
            "$3.5 billion in gross profit. iPad contributed $2.1 billion. Services contributed $16.6 billion "
            "in gross profit. This 45.9% gross margin represented a 300 basis point improvement from fiscal "
            "Q1 2023's 42.9% and was at the high end of the company's guidance range of 45.5% to 46.5%. "
            "Management cited favorable foreign exchange movements and product mix as tailwinds."
        ),
        "query_classes": ["factual_lookup", "financial_data"],
    },
    {
        "key": "apple_pe_ratio_analysis",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T12:00:00Z",
        "title": "Apple Inc. (AAPL) Valuation Metrics: P/E Ratio vs. 5-Year Historical Average",
        "text": (
            "Apple Inc. (AAPL) is trading at a trailing twelve-month price-to-earnings (P/E) ratio of 31.4x "
            "as of May 5, 2026, based on earnings per share of $6.73 (fiscal 2025) and a share price of "
            "$211.40. The forward P/E based on consensus FY2026 EPS estimates of $7.25 is 29.2x. "
            "Apple's 5-year average P/E ratio is approximately 27.8x (fiscal years 2021-2025), meaning the "
            "current valuation is approximately 13% above the 5-year mean. The 5-year P/E range was: "
            "FY2021: 28.1x, FY2022: 22.3x, FY2023: 28.9x, FY2024: 29.4x, FY2025: 30.7x. "
            "Apple commands a premium valuation relative to the S&P 500 (22.1x trailing P/E) reflecting "
            "its high-quality earnings stream, Services mix expansion, and strong capital return program. "
            "On an EV/EBITDA basis, Apple trades at 22.6x versus the 5-year average of 20.1x. "
            "Analysts at Morgan Stanley maintain an Overweight rating with a $240 price target, citing "
            "Services margin expansion as the primary driver of multiple re-rating."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "apple_interest_coverage",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2025-11-01T16:00:00Z",
        "title": "Apple Inc. 10-K FY2025 — Debt & Interest Coverage Analysis",
        "text": (
            "Apple Inc.'s interest coverage ratio for fiscal year 2025 was approximately 40.2x, calculated "
            "as EBIT of $123.2 billion divided by interest expense of $3.07 billion. This compares to "
            "an interest coverage ratio of 38.6x in fiscal 2024. Total long-term debt outstanding as of "
            "September 27, 2025 was $97.3 billion, including $14.7 billion in current maturities. "
            "The company's total debt-to-equity ratio was 1.87x given Apple's negative book equity position "
            "due to sustained share buybacks. Despite the leveraged balance sheet, Apple's net cash position "
            "remained positive at approximately $64.5 billion in cash minus $97.3 billion in total debt, "
            "giving a net debt of approximately $32.8 billion. Interest expense of $3.07 billion was up "
            "slightly from $2.93 billion in FY2024 as the company refinanced maturing notes at marginally "
            "higher coupon rates. Apple maintains investment-grade credit ratings: Aaa/AAA from Moody's/S&P."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "apple_inventory_turnover",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-20T10:00:00Z",
        "title": "Apple vs. Samsung Inventory Turnover Comparison FY2025",
        "text": (
            "Apple Inc. (AAPL) reported inventory of $7.3 billion at the end of fiscal 2025 against cost of "
            "goods sold of approximately $220.4 billion, yielding an inventory turnover ratio of 30.2x — "
            "equivalent to approximately 12 days of inventory outstanding. This represents an improvement "
            "from 28.7x in FY2024 as Apple tightened its supply chain management following post-pandemic "
            "excess inventory corrections. Samsung Electronics (005930.KS) reported a significantly lower "
            "inventory turnover of 6.8x for calendar year 2024, reflecting its more complex semiconductor "
            "and consumer electronics manufacturing footprint. Samsung's inventory was KRW 52.3 trillion "
            "(approximately $38.5 billion) against COGS of KRW 355.8 trillion. Apple's asset-light "
            "outsourced manufacturing model through TSMC, Foxconn, and Pegatron enables dramatically "
            "superior inventory velocity compared to vertically integrated competitors like Samsung."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "apple_supplier_concentration_10k",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2025-11-01T16:00:00Z",
        "title": "Apple Inc. 10-K FY2025 — Supplier Concentration Risk Disclosure",
        "text": (
            "Apple's 10-K discloses significant supplier concentration risk. The Company relies on a "
            "limited number of suppliers for certain components used in its products, including processors, "
            "display panels, and NAND flash storage. Taiwan Semiconductor Manufacturing Company (TSMC) "
            "is Apple's sole supplier for the A-series and M-series chips used in iPhone, iPad, Mac, and "
            "Apple Watch. Samsung Display and LG Display are key suppliers for OLED display panels used in "
            "iPhone Pro models, while BOE Technology provides panels for certain iPhone standard models. "
            "Apple has disclosed that a disruption to production at TSMC's facilities in Taiwan — due to "
            "natural disaster, geopolitical tension, or other factors — could materially adversely affect "
            "the Company's ability to produce its products. The Company has invested in expanding TSMC's "
            "manufacturing capacity in Arizona as part of geographic diversification efforts. "
            "Management has also diversified iPhone assembly across Foxconn, Pegatron, and Luxshare."
        ),
        "query_classes": ["relationship", "factual_lookup"],
    },
    {
        "key": "apple_tsmc_supplier_relationship",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-15T08:00:00Z",
        "title": "Apple and TSMC: A Critical Semiconductor Partnership Under Geopolitical Scrutiny",
        "text": (
            "Apple Inc. and Taiwan Semiconductor Manufacturing Co. (TSMC) share one of the most consequential "
            "supplier relationships in the global technology industry. TSMC manufactures all of Apple's custom "
            "silicon, including the A18 Pro chip (used in iPhone 17 Pro), the M4 chip (Mac and iPad Pro), and "
            "the Apple Watch S10 chip, all fabricated on TSMC's 3-nanometer and 2-nanometer process nodes. "
            "Apple reportedly accounts for approximately 25% of TSMC's total annual revenue, making it TSMC's "
            "largest customer by a significant margin. TSMC's next largest customers include NVIDIA, AMD, and "
            "Qualcomm. The relationship began in 2013 when Apple shifted from Samsung Foundry for its A7 chip. "
            "Apple has committed multi-year advanced purchase agreements, paying upfront to secure capacity. "
            "TSMC's new Fab 21 in Phoenix, Arizona will manufacture 2nm chips for Apple starting in 2026, "
            "which satisfies US CHIPS Act domestic production requirements and reduces geopolitical risk. "
            "The exclusive fab relationship makes TSMC both Apple's most critical and most irreplaceable supplier."
        ),
        "query_classes": ["relationship", "factual_lookup"],
    },
    {
        "key": "apple_services_revenue_q2",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T21:00:00Z",
        "title": "Apple Q2 FY2026 Earnings — Services Segment Detail",
        "text": (
            "TIM COOK: Our Services business continues to be a powerful engine of growth and value creation. "
            "In Q2 fiscal 2026, Services revenue was $26.3 billion — a new all-time record for any quarter "
            "and up 15% year-over-year. This is particularly impressive given that Q2 fiscal 2025 Services "
            "revenue of $22.9 billion was itself a record at the time. Our paid subscriptions across all "
            "services exceeded 1.1 billion, growing 15% year-over-year. Apple TV+ viewership was up 40% "
            "following strong original content including our Academy Award-winning productions. The App Store "
            "continued to demonstrate healthy billings growth globally. Apple Arcade passed 15 million "
            "subscribers. Our financial services — Apple Card, Apple Cash, and Apple Pay — are growing faster "
            "than any other category. LUCA MAESTRI: Services gross margin was 74.9% in Q2, and we expect "
            "Services gross margin to remain in the 74% to 75% range for the balance of fiscal 2026. "
            "Given the high incremental margin on Services, continued Services growth is the single most "
            "important factor driving Apple's overall gross margin expansion."
        ),
        "query_classes": ["factual_lookup", "reasoning"],
    },
    {
        "key": "apple_iphone_revenue_q2_2026",
        "source_type": "press_release",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T20:30:00Z",
        "title": "Apple Reports Q2 FY2026 iPhone Revenue of $53.7 Billion",
        "text": (
            "Apple Inc. reported iPhone revenue of $53.7 billion for the second fiscal quarter of 2026, "
            "representing a 7% increase compared to $50.1 billion in the year-ago quarter. iPhone revenue "
            "accounted for 56.3% of total Apple revenue for the quarter. The strong performance was attributed "
            "to demand for the iPhone 17 Pro and iPhone 17 Pro Max models, which feature the new A18 Pro chip "
            "manufactured on TSMC's 3nm process. iPhone 17 average selling price (ASP) rose approximately "
            "3% year-over-year to approximately $875 as Pro mix increased. China iPhone revenue grew 17% "
            "despite ongoing trade tensions, as consumers upgraded from older models. India continued to be "
            "a high-growth market with revenue up over 30% year-over-year. Europe revenue declined 2% in "
            "constant currency due to Digital Markets Act compliance costs. Looking at Q3 FY2026 guidance, "
            "management expects iPhone revenue to grow in the mid-single-digit percentage range versus "
            "the prior year quarter."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "apple_earnings_surprise_q2_2026",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-02T09:00:00Z",
        "title": "Apple Beats Q2 Estimates by $2.1B; Stock Rises 3.4% After Hours",
        "text": (
            "Apple Inc. (AAPL) posted a massive earnings beat for fiscal Q2 2026, with revenue of $95.4 billion "
            "exceeding the Wall Street consensus estimate of $93.3 billion by approximately $2.1 billion. "
            "Earnings per share of $1.65 beat consensus of $1.58 by $0.07. This represents Apple's largest "
            "quarterly earnings surprise in six quarters as a percentage beat. The stock rose 3.4% in "
            "after-hours trading following the results. Alphabet (GOOG) also reported Q2 results the same "
            "evening, posting revenue of $90.2 billion versus consensus of $88.1 billion, a $2.1 billion "
            "beat. Apple's earnings surprise was larger in absolute dollar terms, but Alphabet's percentage "
            "beat was 2.4% versus Apple's 2.2%. Services revenue of $26.3 billion was $1.4 billion above "
            "Street estimates, while iPhone revenue of $53.7 billion beat by $800 million. China revenue "
            "of $16.8 billion was the key upside driver versus analyst expectations of $14.2 billion."
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    {
        "key": "apple_stock_drop_analysis",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-02-03T10:00:00Z",
        "title": "Why Apple Stock Dropped 5% After Its Q1 FY2026 Earnings Beat",
        "text": (
            "Apple Inc. shares fell 5.1% on February 3, 2026, the day after the company reported fiscal Q1 "
            "2026 results that nominally beat analyst estimates. Revenue of $124.3 billion beat consensus "
            "by 0.8%, and EPS of $2.41 beat by $0.04. However, investors were disappointed by three "
            "factors: (1) China revenue declined 8% year-over-year to $18.5 billion versus expectations "
            "of $20.1 billion, signaling continued market share pressure from Huawei and domestic brands; "
            "(2) iPhone unit volumes were down 3% year-over-year despite higher ASPs, raising concerns "
            "about unit saturation; (3) Q2 guidance of $89B-$92B was below the Street's $93B estimate. "
            "The market had priced in continued positive momentum from the AI-powered iPhone Super Cycle "
            "narrative, which Q1 results did not fully validate. Analyst downgrades from Barclays and "
            "Redburn drove additional selling. The stock had been up 14% year-to-date prior to earnings, "
            "making the 'sell the news' reaction more pronounced on a high-expectations setup."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "apple_10k_2025_segment_risk",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2025-11-01T16:00:00Z",
        "title": "Apple Inc. 10-K FY2025 — Geographic Revenue Segment Analysis",
        "text": (
            "Apple's FY2025 10-K breaks revenue into five geographic segments. Americas revenue was "
            "$175.1 billion (42.3% of total), up 6% YoY. Europe revenue was $101.4 billion (24.5%), "
            "up 5% in reported currency but 8% in constant currency. Greater China revenue was $66.9 billion "
            "(16.1%), up 3% YoY after a 8% decline in FY2024 — the recovery driven by iPhone 17 cycle and "
            "government stimulus. Japan revenue was $26.3 billion (6.3%), up 4%. Rest of Asia Pacific was "
            "$44.8 billion (10.8%), up 12% driven by India where Apple opened four retail stores. "
            "The 10-K notes that Greater China represents Apple's highest concentration geographic risk: "
            "China revenues represent approximately 16% of total revenue, and both manufacturing "
            "(Foxconn/Pegatron in China) and distribution depend on stable US-China trade relations. "
            "The company discloses that tariff escalations, export controls, or Chinese government actions "
            "limiting Apple product sales could materially impair results. China represents approximately "
            "25% of iPhone assembly capacity."
        ),
        "query_classes": ["factual_lookup", "relationship"],
    },
    {
        "key": "apple_samsung_oled_supply",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-03-10T08:00:00Z",
        "title": "Apple and Samsung Share OLED Panel Suppliers Despite Fierce Competition",
        "text": (
            "Despite being fierce competitors in the smartphone market, Apple and Samsung Electronics both "
            "depend on many of the same suppliers for OLED display panels. Samsung Display (a subsidiary of "
            "Samsung Electronics) is the largest OLED panel supplier for Apple's iPhone 17 Pro models, "
            "providing approximately 60% of Pro OLED panels. LG Display supplies the remaining 40% of "
            "iPhone Pro panels and is also a major supplier to Samsung's Galaxy S26 series. BOE Technology "
            "Group (Chinese) supplies OLED panels for iPhone 17 standard models and competes with Samsung "
            "Display for LG Display contracts for Galaxy devices. For NAND flash storage, both Apple and "
            "Samsung source components from Samsung Semiconductor, SK Hynix, and Kioxia. "
            "Qualcomm supplies cellular modems to both Apple iPhone 17 standard models and Samsung Galaxy "
            "flagship phones, though Apple is developing its own in-house modem (expected iPhone 18 launch). "
            "This web of shared suppliers creates interesting competitive dynamics in component procurement."
        ),
        "query_classes": ["relationship", "comparison"],
    },
    {
        "key": "apple_iphone_q1_2024_revenue",
        "source_type": "sec_10q",
        "source_name": "sec_edgar",
        "published_at": "2024-02-02T16:00:00Z",
        "title": "Apple Inc. Q1 FY2024 10-Q — iPhone Revenue and Gross Margin Detail",
        "text": (
            "Apple reported iPhone net sales of $69.7 billion for the fiscal first quarter of 2024 (ending "
            "December 30, 2023), a decline of 1% compared to $70.0 billion in the prior year quarter. "
            "This was the first year-over-year decline in iPhone quarterly revenue since the Q2 FY2023 period. "
            "The decline was driven by: (1) weaker demand in China where revenue fell 13% as competition "
            "intensified following Huawei's re-entry into the premium segment with the Mate 60 Pro; "
            "(2) difficult prior-year comparisons when iPhone 14 launched with a strong Pro mix. "
            "iPhone gross margin was estimated at approximately 41% in Q1 FY2024, benefiting from "
            "favorable commodity costs including NAND flash and DRAM at multi-year lows. "
            "Total Apple revenue in Q1 FY2024 was $119.6 billion, with a gross margin of 45.9%. "
            "For Q1 FY2024, the iPhone 15 lineup including the iPhone 15 Pro Max was the top-selling "
            "product globally. Apple TV+ continued to grow paid subscribers and received 22 Emmy nominations."
        ),
        "query_classes": ["factual_lookup", "financial_data"],
    },
    {
        "key": "apple_portfolio_holding_summary",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio: Apple Inc. (AAPL) Holding Summary",
        "text": (
            "Portfolio position: Apple Inc. (AAPL). Current holding: 125 shares. Average cost basis: "
            "$168.42 per share (acquired over 2023-2024). Current market price: $211.40. Current market "
            "value: $26,425.00. Unrealized gain: $5,372.50 (+25.6%). Sector: Technology — Consumer Electronics. "
            "AAPL weight in portfolio: 18.7% (largest single-name position). S&P 500 AAPL weight: 7.2%. "
            "Portfolio is overweight AAPL by approximately 11.5 percentage points versus the index. "
            "Beta (5-year monthly vs S&P 500): 1.22. Most recent dividend: $0.26/share (ex-date May 9, 2026). "
            "Next earnings report: Expected late July 2026 (fiscal Q3 FY2026). AAPL ISIN: US0378331005. "
            "AAPL CIK (SEC): 0000320193. Ticker: NASDAQ: AAPL. Sector: Technology. Industry: Consumer Electronics. "
            "The stock has returned +18.4% year-to-date through May 1, 2026, versus the S&P 500 at +9.1%."
        ),
        "query_classes": ["portfolio", "identifier_lookup"],
    },
    {
        "key": "apple_10k_full_highlights",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2025-11-01T16:00:00Z",
        "title": "Apple Inc. FY2025 10-K Filing — Key Financial Highlights Summary",
        "text": (
            "Apple Inc. FY2025 Annual Report on Form 10-K (filed November 1, 2025) key highlights: "
            "Net sales $414.5B (+6% YoY). Net income $101.4B (+7% YoY). Diluted EPS $6.73 (+10% YoY reflecting buybacks). "
            "Gross margin 46.9% vs 45.6% prior year. Operating cash flow $122.0B. Capital expenditures $11.2B. "
            "Free cash flow $110.8B. Share repurchases $95.0B. Dividends paid $15.6B. Total capital returned $110.6B. "
            "Cash and equivalents $64.5B net (vs $111.4B gross securities). Long-term debt $97.3B. "
            "Active installed base 2.3B devices. Paid subscriptions across services 1.05B. "
            "Employees 164,000 FTE. R&D expense $31.4B (+12% YoY). "
            "Product mix: iPhone 51.6%, Services 23.2%, Mac 7.6%, iPad 6.3%, Wearables 8.9%. "
            "Geographic mix: Americas 42.3%, Europe 24.5%, Greater China 16.1%, Japan 6.3%, Rest of Asia 10.8%. "
            "Risk factors include: China geopolitical risk, semiconductor supply concentration (TSMC sole source "
            "for custom silicon), increasing regulatory scrutiny of App Store globally."
        ),
        "query_classes": ["factual_lookup", "financial_data"],
    },
    # ── Microsoft ──────────────────────────────────────────────────────────
    {
        "key": "msft_q3_2026_transcript_ai",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-30T21:00:00Z",
        "title": "Microsoft Q3 FY2026 Earnings Call — CEO Satya Nadella on AI Investment",
        "text": (
            "SATYA NADELLA: Thank you, Brett. Our results this quarter demonstrate that our AI investments "
            "are generating real and accelerating returns. Azure AI revenue grew 157% year-over-year in Q3 "
            "fiscal 2026, and our AI business has now surpassed a $13 billion annualized revenue run rate, "
            "up from $10 billion just two quarters ago. This is the fastest-growing business we have ever "
            "built at Microsoft. We are investing aggressively in AI infrastructure — we committed to spend "
            "$80 billion on AI data centers in fiscal 2026, of which approximately $60 billion will be in "
            "the United States. This investment is not speculative; it is demand-driven. Every new data "
            "center capacity we bring online is immediately subscribed. We have more contracted backlog "
            "than we can currently serve. GitHub Copilot now has over 2 million paid enterprise subscribers, "
            "with usage metrics showing that developers using Copilot complete tasks 55% faster than those "
            "who don't. Microsoft 365 Copilot seat deployments exceeded 400,000 enterprise seats, with "
            "customers reporting 30-40% productivity improvements in knowledge worker tasks."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "msft_q3_2026_transcript_azure",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-30T21:00:00Z",
        "title": "Microsoft Q3 FY2026 Earnings — Azure Cloud Revenue Growth vs. Prior Quarters",
        "text": (
            "AMY HOOD: Intelligent Cloud segment revenue was $29.1 billion in Q3 fiscal 2026, up 21% "
            "year-over-year. Azure and other cloud services grew 33% in constant currency, an acceleration "
            "from 26% growth in Q2 and 28% in Q3 of fiscal 2025. The Azure acceleration was driven by AI "
            "workloads; Azure AI services alone grew over 150% year-over-year and contributed "
            "approximately 16 percentage points of Azure's 33% growth rate. Excluding AI, core Azure grew "
            "approximately 17% — a slight deceleration from prior quarters. SQL Server migration to Azure "
            "remains strong. Azure consumed capacity exceeded our provisioned capacity for the third "
            "consecutive quarter. For Q4 fiscal 2026 guidance, we expect Azure growth of 34% to 36% "
            "in constant currency, which would represent continued acceleration. "
            "Amazon AWS reported 17% growth in Q1 2026, and Google Cloud reported 28% growth, "
            "making Azure the fastest-growing major cloud platform for the third consecutive quarter."
        ),
        "query_classes": ["factual_lookup", "comparison"],
    },
    {
        "key": "msft_q3_2026_8k",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2026-04-30T20:30:00Z",
        "title": "Microsoft Corporation Form 8-K: Q3 FY2026 Financial Results",
        "text": (
            "REDMOND, Washington — April 30, 2026 — Microsoft Corp. today announced the following results "
            "for the quarter ended March 31, 2026: Revenue was $70.1 billion and increased 16% year-over-year. "
            "Operating income was $33.7 billion and increased 20% year-over-year. Net income was $28.5 billion "
            "and increased 18% year-over-year. Diluted EPS was $3.84 and increased 20% year-over-year. "
            "Productivity and Business Processes: $29.4B (+11% YoY). Intelligent Cloud: $29.1B (+21% YoY). "
            "More Personal Computing: $11.6B (+8% YoY). Azure and cloud services grew 33% in constant currency. "
            "Gross margin was 70.1%. Capital expenditures in Q3 were $21.4 billion, up 53% YoY as Microsoft "
            "continues its AI infrastructure build-out. The Board declared a quarterly dividend of $0.83 per share."
        ),
        "query_classes": ["factual_lookup", "comparison"],
    },
    {
        "key": "msft_azure_vs_aws_comparison",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-03T09:00:00Z",
        "title": "Azure vs. AWS vs. Google Cloud: Q1 2026 Growth Rate Comparison",
        "text": (
            "The three major hyperscalers reported diverging cloud growth trajectories in Q1 2026. "
            "Microsoft Azure grew 33% year-over-year in constant currency in Q3 FY2026 (ending March 31). "
            "Amazon AWS grew 17% year-over-year in Q1 2026 (calendar), revenue of $29.3 billion. "
            "Google Cloud grew 28% year-over-year in Q1 2026, revenue of $12.3 billion. "
            "On a trailing four-quarter basis: Azure grew 29%, 28%, 26%, 33% (Q4 FY2025 through Q3 FY2026). "
            "AWS grew 19%, 19%, 18%, 17% over the same period. Google Cloud grew 26%, 28%, 30%, 28%. "
            "Azure's re-acceleration is being attributed to AI workload adoption and Microsoft's Copilot "
            "product suite. AWS growth deceleration reflects AWS's larger base and lower AI product mix. "
            "Google Cloud's growth is driven by Gemini AI integration in BigQuery and Vertex AI. "
            "On an absolute dollar basis, AWS remains the largest with approximately $115 billion in "
            "trailing twelve-month revenue, versus Azure's estimated $100 billion and Google Cloud's $46 billion."
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    {
        "key": "msft_gross_margin_quarterly",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "Microsoft Gross Margin Trend: Q2 FY2025 Through Q1 FY2026",
        "text": (
            "Microsoft Corporation gross margin trend over the four most recent quarters: "
            "Q3 FY2025 (ending March 2025): Revenue $70.1B, gross profit $47.6B, gross margin 68.0%. "
            "Q4 FY2025 (ending June 2025): Revenue $73.4B, gross profit $50.3B, gross margin 68.6%. "
            "Q1 FY2026 (ending September 2025): Revenue $65.6B, gross profit $45.5B, gross margin 69.3%. "
            "Q2 FY2026 (ending December 2025): Revenue $69.6B, gross profit $48.7B, gross margin 70.0%. "
            "Q3 FY2026 (ending March 2026): Revenue $70.1B, gross profit $49.2B, gross margin 70.1%. "
            "The steady gross margin expansion from 68.0% to 70.1% over five quarters reflects: "
            "(1) growing mix of high-margin Azure AI services; (2) Office 365 pricing increases; "
            "(3) improved cloud infrastructure utilization. Analysts expect gross margin to reach 71-72% "
            "by end of fiscal 2027 as AI services scale. Gaming gross margin dilutes slightly following "
            "Activision integration costs still being amortized."
        ),
        "query_classes": ["financial_data", "comparison"],
    },
    {
        "key": "msft_ai_acquisitions_activision",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2023-10-13T12:00:00Z",
        "title": "Microsoft Closes $68.7 Billion Activision Blizzard Acquisition",
        "text": (
            "Microsoft Corporation completed its $68.7 billion acquisition of Activision Blizzard on "
            "October 13, 2023, after an 18-month regulatory battle that required divestitures of cloud "
            "gaming rights to Ubisoft in Europe. The acquisition is the largest in gaming industry history "
            "and gives Microsoft ownership of Call of Duty, World of Warcraft, Diablo, Overwatch, Candy Crush, "
            "and King's mobile gaming portfolio. Activision contributes approximately $8 billion in annual "
            "revenue to Microsoft's More Personal Computing segment. The deal was funded through existing "
            "cash and new debt issuance, temporarily increasing Microsoft's net debt position. "
            "Satya Nadella cited the acquisition as central to Microsoft's metaverse and gaming strategy, "
            "though the company has since pivoted more aggressively toward AI infrastructure. "
            "The acquisition is being integrated into Xbox Game Studios. Day 1 Game Pass inclusion of all "
            "Activision titles boosted Game Pass subscriptions significantly post-close."
        ),
        "query_classes": ["relationship", "factual_lookup"],
    },
    {
        "key": "msft_ai_acquisitions_nuance",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2022-03-04T12:00:00Z",
        "title": "Microsoft Completes $19.7 Billion Acquisition of Nuance Communications",
        "text": (
            "Microsoft completed its acquisition of Nuance Communications for $19.7 billion on March 4, 2022, "
            "bringing one of the world's leading AI and speech technology companies into the Microsoft portfolio. "
            "Nuance's Dragon Medical platform serves over 77% of US hospitals and processes over 300 million "
            "clinical notes annually. The acquisition was strategically aimed at accelerating Microsoft Cloud "
            "for Healthcare and establishing Azure as the AI cloud of choice for healthcare providers. "
            "Nuance's ambient clinical intelligence technology, which uses AI to automatically document patient "
            "visits in the background, was integrated into Microsoft Teams and has since been adopted by "
            "major health systems including Cleveland Clinic and Sutter Health. Post-acquisition, Nuance "
            "became a cornerstone of Microsoft's AI-first healthcare strategy. The deal gave Microsoft "
            "deep healthcare AI expertise and a large enterprise customer base that has since been cross-sold "
            "onto Azure. Combined with OpenAI partnership and GitHub Copilot, Nuance represented Microsoft's "
            "third major AI stack acquisition in 2021-2022."
        ),
        "query_classes": ["relationship", "factual_lookup"],
    },
    {
        "key": "msft_cloud_deceleration_analysis",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2025-10-31T10:00:00Z",
        "title": "Why Microsoft Azure Growth Decelerated in Q2 FY2025 vs. Analyst Expectations",
        "text": (
            "Microsoft Azure growth slowed to 26% year-over-year in Q2 FY2025 (ending December 2024), "
            "missing analyst consensus expectations of 28-30% growth. The deceleration was driven by three factors: "
            "(1) AI workload capacity constraints — Microsoft's data center build-out fell behind demand, "
            "causing some AI customers to be redirected to competitors or wait-listed; "
            "(2) normal enterprise budget cycles with customers pausing large multi-year Azure commitments "
            "ahead of year-end budget resets; "
            "(3) Azure's growing base makes each incremental percentage point of growth require more absolute "
            "revenue. CEO Satya Nadella acknowledged on the earnings call that 'We have more contracted "
            "demand than we can currently supply — this is a capacity problem, not a demand problem.' "
            "CFO Amy Hood guided Q3 FY2025 Azure growth of 31-32%, which would represent re-acceleration. "
            "Analysts who had expected sustained 30%+ growth viewed the miss as a temporary capacity-driven "
            "hiccup rather than a structural deceleration. Shares fell 6% the day after results."
        ),
        "query_classes": ["reasoning", "factual_lookup"],
    },
    {
        "key": "msft_capex_hyperscaler",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-30T22:00:00Z",
        "title": "Microsoft Q3 FY2026: $21.4B Quarterly Capex — Most Aggressive Hyperscaler Spend",
        "text": (
            "Microsoft reported capital expenditure of $21.4 billion in Q3 FY2026 (ending March 31, 2026), "
            "a 53% increase year-over-year and the highest quarterly capex in company history. "
            "For the trailing twelve months ending March 2026, Microsoft capex totaled $77.6 billion, "
            "surpassing both Amazon ($66.8B TTM) and Alphabet ($54.2B TTM). Meta reported TTM capex of "
            "$45.1 billion. On a year-over-year basis, Microsoft increased capex by 63% versus the prior "
            "twelve-month period — the most aggressive rate of capex expansion among the four major hyperscalers. "
            "Amazon's TTM capex grew 53% YoY, Google's grew 41% YoY, and Meta's grew 37% YoY. "
            "Microsoft's capex is concentrated in GPU-based AI training and inference data centers globally, "
            "with large facility investments in the US, UK, Germany, Japan, and India. "
            "Management has guided $80 billion in total FY2026 capex, implying Q4 FY2026 spending of "
            "approximately $19-21 billion to remain on track."
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    {
        "key": "msft_portfolio_holding",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio: Microsoft Corporation (MSFT) Position Summary",
        "text": (
            "Portfolio position: Microsoft Corporation (MSFT). Shares held: 80. Average cost basis: $310.50. "
            "Current price: $418.60. Market value: $33,488.00. Unrealized gain: $8,648.00 (+34.8%). "
            "Weight in portfolio: 23.7% — largest dollar-value holding. S&P 500 MSFT weight: 6.8%. "
            "Portfolio overweight by 16.9 percentage points. Sector: Technology. Beta (5-yr): 0.90. "
            "Next dividend: $0.83/share quarterly (ex-date May 14, 2026). "
            "FY2026 earnings calendar: Q4 FY2026 expected July 29, 2026. "
            "MSFT ISIN: US5949181045. Analyst consensus: 48 Buy, 6 Hold, 0 Sell. Mean PT: $467."
        ),
        "query_classes": ["portfolio", "identifier_lookup"],
    },
    {
        "key": "msft_copilot_ai_revenue",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-30T21:00:00Z",
        "title": "Microsoft Q3 FY2026 — AI Copilot and M365 Revenue Discussion",
        "text": (
            "SATYA NADELLA: Microsoft 365 Copilot continues to show remarkable commercial traction. "
            "We now have over 400,000 enterprise seats deployed, up from 220,000 last quarter. "
            "Customers deploying Copilot at scale include Goldman Sachs, Pfizer, and Toyota. "
            "Enterprise customers report measurable productivity improvements: meeting summarization "
            "saves 4+ hours per week per knowledge worker on average. Our GitHub Copilot business has "
            "surpassed 2 million paid enterprise subscribers, and GitHub Copilot Enterprise is being "
            "adopted at 3x the rate of the original Copilot product. Azure AI Foundry, our one-stop "
            "platform for AI application development, now has 70,000 active customers building production "
            "AI applications. The AI business — spanning Azure OpenAI, M365 Copilot, GitHub Copilot, "
            "Security Copilot, and industry-specific AI — has exceeded $13 billion annualized run rate. "
            "AMY HOOD: Copilot features contributed approximately $1.2 billion of incremental revenue "
            "in Q3 on top of baseline M365 and Azure growth. We expect this contribution to double by Q4."
        ),
        "query_classes": ["factual_lookup", "reasoning"],
    },
    {
        "key": "msft_azure_q3_detail",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-30T21:00:00Z",
        "title": "Microsoft Q3 FY2026 — Azure Revenue Detail and AI Contribution",
        "text": (
            "AMY HOOD: Azure and other cloud services revenue grew 33% in constant currency in Q3 FY2026. "
            "AI services contributed 16 percentage points of that 33% growth. Core Azure infrastructure "
            "grew approximately 17%. SQL, Cosmos DB, and other data platform services grew in the mid-20s. "
            "Azure Kubernetes Service adoption remains strong as customers containerize AI workloads. "
            "We ended Q3 with Azure committed backlog of approximately $315 billion, up 22% from Q3 FY2025. "
            "For context on the competitive landscape: Amazon AWS grew 17% in calendar Q1 2026 and reported "
            "operating margin of 39.5%. Google Cloud grew 28% in Q1 2026 with its first quarter of "
            "significant operating profitability. Azure's operating margin in the Intelligent Cloud segment "
            "was 47%, up from 44% a year ago, demonstrating that scale and AI premium pricing are "
            "driving margin expansion even as we invest heavily in infrastructure. "
            "Q4 FY2026 guidance: Azure growth of 34-36% in constant currency."
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    # ── NVIDIA ─────────────────────────────────────────────────────────────
    {
        "key": "nvda_fiscal_2024_h100_revenue",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2024-02-21T16:00:00Z",
        "title": "NVIDIA Corporation 10-K FY2024 — H100 GPU Data Center Revenue",
        "text": (
            "NVIDIA Corporation reported Data Center revenue of $47.5 billion for fiscal year 2024 "
            "(ending January 28, 2024), representing a 217% increase from $15.0 billion in fiscal 2023. "
            "The H100 Tensor Core GPU was the primary driver of Data Center revenue growth. The H100 GPU "
            "was in extremely high demand from hyperscalers, cloud service providers, and enterprise AI "
            "customers. Microsoft, Google, Meta, Amazon, and Oracle were identified as the five largest "
            "H100 customers, collectively representing approximately 45% of Data Center revenue. "
            "NVIDIA's Data Center segment gross margin was approximately 73.8% in FY2024, significantly "
            "above the company's blended gross margin of 72.7%. The company shipped H100 GPUs in both "
            "SXM5 and PCIe form factors. H100 ASP was approximately $30,000-$40,000 per unit, contributing "
            "to the dramatic revenue increase. NVIDIA's total revenue in FY2024 was $60.9 billion, up 122% "
            "from FY2023's $26.9 billion. H100 revenue contribution to total company revenue was estimated "
            "at 55-65% based on analyst estimates and management disclosures."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "nvda_q4_fy2024_transcript",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2024-02-21T21:00:00Z",
        "title": "NVIDIA Q4 FY2024 Earnings Call — Jensen Huang on AI Demand Surge",
        "text": (
            "JENSEN HUANG: The conditions for our success are extraordinary. A new computing era has begun. "
            "The H100 GPU has become the fundamental unit of AI infrastructure, and demand is many multiples "
            "of our current supply capacity. Every major cloud provider — Microsoft Azure, Google Cloud, "
            "Amazon AWS, Oracle Cloud — is deploying H100 clusters at scale. Meta is building the largest "
            "single-company H100 cluster in the world, targeting 350,000 GPUs. "
            "Our Data Center business grew from $3.6 billion in Q4 FY2023 to $18.4 billion in Q4 FY2024 "
            "— a 5x increase in twelve months. The Hopper architecture that powers H100 represents a "
            "generational leap in AI compute performance: 6x higher throughput than the prior A100 generation "
            "for transformer model inference. We are ramping Blackwell, our next-generation architecture, "
            "and customer demand already exceeds expected Blackwell production capacity for fiscal 2026. "
            "This is not a cyclical surge — this is the beginning of a secular shift in how data centers "
            "are built: from CPU-centric to GPU-accelerated AI factories."
        ),
        "query_classes": ["reasoning", "factual_lookup"],
    },
    {
        "key": "nvda_data_center_customers",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2024-02-21T16:00:00Z",
        "title": "NVIDIA 10-K FY2024 — Major Data Center Customers and Concentration",
        "text": (
            "NVIDIA's FY2024 10-K discloses customer concentration in the Data Center segment. "
            "One customer (Microsoft) accounted for approximately 13% of total NVIDIA revenue in FY2024. "
            "In aggregate, the five largest Data Center customers — Microsoft, Google, Meta, Amazon, and "
            "Oracle — represented approximately 45% of Data Center segment revenue. "
            "NVIDIA sells GPUs to these hyperscalers directly and through authorized distributors. "
            "Customer purchases are used for: (1) AI model training (LLM pre-training and fine-tuning), "
            "(2) AI inference at scale (serving deployed models), (3) cloud rental to third-party AI companies. "
            "The 10-K notes that a significant reduction in purchases by any one of these major customers "
            "could materially adversely affect results. NVIDIA has no long-term supply agreements with "
            "any of these customers — orders are placed on a purchase-order basis, though customers make "
            "forward commitments to reserve H100/H200/Blackwell GPU capacity. "
            "Alphabet's TPU internal development and Amazon's Trainium/Inferentia chips represent "
            "potential long-term competitive threats to NVIDIA's dominance in AI training hardware."
        ),
        "query_classes": ["relationship", "factual_lookup"],
    },
    {
        "key": "nvda_gross_margin_analysis",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-25T10:00:00Z",
        "title": "NVIDIA Gross Margin Analysis: AI Premium Drives Record 78.4% Blended Margin",
        "text": (
            "NVIDIA Corporation reported gross margin of 78.4% in fiscal Q4 2025 (ending January 2026), "
            "a record for the company and significantly above historical averages. This compares to "
            "AMD's Q1 2026 gross margin of 53.0% on a non-GAAP basis. NVIDIA's gross margin has expanded "
            "dramatically: FY2023 blended: 56.9%, FY2024 blended: 72.7%, Q1 FY2025: 78.9%, Q2 FY2025: 75.1%, "
            "Q3 FY2025: 74.6%, Q4 FY2025: 73.5%. The FY2025 full-year blended gross margin was 75.0%. "
            "The high gross margin reflects NVIDIA's monopoly-like pricing power in AI accelerator hardware, "
            "where the H100 and H200 have no performance-comparable alternatives. Blackwell GPU pricing is "
            "rumored to be $70,000-$100,000 per unit, potentially sustaining elevated margins. "
            "AMD's MI300X GPU competes at lower price points but has gained traction with Microsoft Azure "
            "and Meta as a cost-effective alternative for certain AI inference workloads."
        ),
        "query_classes": ["financial_data", "comparison"],
    },
    {
        "key": "nvda_forward_eps_estimate",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-05T09:00:00Z",
        "title": "NVIDIA FY2027 EPS Consensus Estimate: $4.65 (Non-GAAP)",
        "text": (
            "Wall Street consensus for NVIDIA Corporation (NVDA) forward earnings: "
            "FY2026 (ending Jan 2026) Non-GAAP EPS estimate: $2.99 (actual, reported Feb 2026). "
            "FY2027 (ending Jan 2027) Non-GAAP EPS consensus: $4.65 (range: $4.20 to $5.10). "
            "FY2027 GAAP EPS estimate: $4.10 (range: $3.80 to $4.55). "
            "CY2026 Non-GAAP EPS estimate: $4.35. CY2026 P/E at current price ($1,127): 25.9x forward. "
            "Revenue consensus for FY2027: $219.8 billion (range $198B-$241B). "
            "Data Center revenue FY2027 consensus: $192.0 billion (+23% vs FY2026 actuals of $115.2B). "
            "The wide EPS range reflects uncertainty around: Blackwell GPU production ramp timing, "
            "US export restrictions impact on China sales (China accounted for ~13% of FY2025 revenue), "
            "and competitive dynamics from AMD MI350X and Google TPU v5 deployments. "
            "Analyst price targets range from $850 (cautious) to $1,600 (bull case). Median PT: $1,340."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "nvda_ai_demand_surge_reasoning",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2024-11-20T09:00:00Z",
        "title": "What Caused NVIDIA's Dramatic Revenue Surge? The AI Training Infrastructure Boom Explained",
        "text": (
            "NVIDIA's revenue grew from $26.9 billion in fiscal 2023 to $60.9 billion in fiscal 2024 — "
            "a 126% increase — driven by a perfect confluence of demand factors. The proximate cause was "
            "the release of ChatGPT in November 2022 and its explosion to 100 million users in 60 days, "
            "which convinced every major technology company that generative AI was a transformational "
            "technology requiring massive compute investment. Google, Microsoft, Meta, Amazon, Apple, and "
            "hundreds of AI startups all simultaneously sought to train and deploy large language models. "
            "NVIDIA's H100 GPU was the only commercially available chip with sufficient memory bandwidth "
            "(3.35 TB/s), NVLink interconnect bandwidth, and Transformer Engine acceleration to train "
            "frontier models efficiently. AMD had no competitive alternative; Google's TPUs were not "
            "available to third parties. This demand surge hit NVIDIA when it had limited H100 inventory, "
            "causing customers to place orders months in advance and pay premium prices. "
            "NVIDIA's gross margin expanded from 57% to 73% because customers competed to secure limited "
            "H100 supply, removing NVIDIA's incentive to discount. The result was the fastest single-year "
            "revenue expansion of any company in S&P 500 history."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "nvda_vs_amd_gross_margin",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "NVIDIA vs AMD Gross Margin Comparison: Q4 FY2025 and Q1 CY2026",
        "text": (
            "Gross margin comparison — NVIDIA vs. AMD — most recent two quarters: "
            "NVIDIA Q3 FY2026 (ending Oct 2025): Non-GAAP gross margin 75.0%, GAAP 74.6%. "
            "NVIDIA Q4 FY2026 (ending Jan 2026): Non-GAAP gross margin 73.5%, GAAP 73.0%. "
            "AMD Q4 2025 (calendar, ending Dec 2025): Non-GAAP gross margin 51.3%, GAAP 48.3%. "
            "AMD Q1 2026 (calendar, ending Mar 2026): Non-GAAP gross margin 53.0%, GAAP 49.7%. "
            "NVIDIA's gross margin is approximately 22 percentage points higher than AMD's on a non-GAAP basis. "
            "This reflects NVIDIA's dominant pricing power from H100/H200/Blackwell monopoly versus AMD's "
            "competitive MI300X positioning at lower price points. AMD's gross margin improvement from "
            "51.3% to 53.0% quarter-over-quarter reflects growing MI300X mix (higher-margin data center) "
            "versus client CPU segment. NVIDIA's gross margin decline from 75% to 73.5% reflects "
            "initial Blackwell GPU manufacturing costs. Analysts expect NVIDIA gross margin to re-expand "
            "to 74-76% in FY2027 as Blackwell yields improve."
        ),
        "query_classes": ["comparison", "financial_data"],
    },
    {
        "key": "nvda_hyperscaler_customers",
        "source_type": "relation",
        "source_name": "sec_edgar",
        "published_at": "2024-02-21T16:00:00Z",
        "title": "NVIDIA Primary Customer Relationships: Hyperscalers and Cloud Providers",
        "text": (
            "NVIDIA's primary customers for H100, H200, and Blackwell AI GPUs are the major hyperscalers "
            "and cloud service providers: Microsoft (Azure) is NVIDIA's largest single customer, accounting "
            "for approximately 13% of total FY2024 revenue. Microsoft uses H100 clusters to power Azure "
            "OpenAI Service and to train proprietary AI models. Meta Platforms is deploying the largest "
            "known single-company GPU cluster with a stated target of 600,000 H100-equivalent GPUs by end "
            "of 2024. Meta uses NVIDIA GPUs to train Llama models and for recommendation algorithm serving. "
            "Google/Alphabet uses H100 for training Gemini models and as an alternative to TPUs in GCP. "
            "Amazon Web Services integrates H100 (as P5 instances) alongside its own Trainium chips. "
            "Oracle Cloud Infrastructure has made major GPU cluster investments and is NVIDIA's fastest "
            "growing hyperscaler customer by percentage growth rate. Additionally, AI startups including "
            "Anthropic, OpenAI (via Azure), xAI, and Mistral are indirect customers through cloud providers."
        ),
        "query_classes": ["relationship"],
    },
    {
        "key": "nvda_unusual_options",
        "source_type": "signal_intel",
        "source_name": "finnhub",
        "published_at": "2026-05-06T15:00:00Z",
        "title": "NVDA Unusual Options Activity: $50M Notional in Call Sweeps This Week",
        "text": (
            "Unusual options activity detected on NVIDIA Corporation (NVDA) this week (week of May 4, 2026). "
            "Total NVDA options volume 2.4x the 20-day average. Significant bullish sweep orders identified: "
            "May 5: 2,500 contracts of $1,150 calls expiring June 20 swept at ask ($32.40/contract), "
            "total premium $8.1 million, likely institutional. May 6: 4,800 contracts of $1,200 calls "
            "expiring July 18 at ask ($18.50/contract), premium $8.9 million — largest single trade. "
            "Put/call ratio for NVDA this week: 0.42 (extremely bullish versus 30-day average of 0.68). "
            "Open interest on calls at $1,100 and above strikes increased 18% over the week. "
            "Catalyst: NVDA earnings report expected May 28, 2026. Blackwell GPU revenue ramp expected to "
            "show strong sequential acceleration. Analyst consensus estimates may be too conservative. "
            "The pattern of large call sweeps before an earnings catalyst is consistent with informed "
            "options positioning by institutional accounts. No insider trading red flags flagged at this time."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "nvda_portfolio_holding",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio: NVIDIA Corporation (NVDA) Holding Detail",
        "text": (
            "Portfolio position: NVIDIA Corporation (NVDA). Shares held: 45. Cost basis: $485.20/share. "
            "Current price: $1,127.40. Market value: $50,733.00. Unrealized gain: $29,331.00 (+136.9%). "
            "Portfolio weight: 35.9% — dominant concentration risk. S&P 500 NVDA weight: 6.1%. "
            "Portfolio overweight by 29.8 percentage points. Beta (5-yr): 1.85. "
            "Ex-dividend date for next quarterly dividend: June 10, 2026. Dividend: $0.01/share (token). "
            "Earnings next report: Q1 FY2027 expected May 28, 2026. Consensus EPS: $0.93 non-GAAP. "
            "NVDA represents the portfolio's highest beta, highest conviction, and highest concentration position. "
            "Top risk: US export restrictions to China further reducing addressable market; AMD competition. "
            "NVDA ISIN: US67066G1040. Sector: Technology — Semiconductors."
        ),
        "query_classes": ["portfolio", "identifier_lookup"],
    },
    {
        "key": "nvda_recent_news_summary",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-05-06T08:00:00Z",
        "title": "NVDA News This Week: Blackwell Shipments Ahead of Schedule, Export Waiver Update",
        "text": (
            "Latest developments on NVIDIA Corporation (NVDA) this week: "
            "(1) Blackwell GPU shipments are reportedly tracking ahead of the initial 2026 ramp schedule; "
            "supply chain sources indicate TSMC's CoWoS-L packaging yields have improved faster than expected, "
            "enabling higher GB200 NVL72 rack volume in Q2 2026. "
            "(2) The US Commerce Department clarified that export licenses for H100/H200 sales to Singapore "
            "and certain Tier 2 countries do not require the new stringent AI chip export license introduced "
            "in January 2026; this is modestly positive for NVDA's international revenue mix. "
            "(3) NVIDIA GTC 2026 registration opened — Jensen Huang's keynote expected to unveil Rubin "
            "next-generation architecture details and the NVLink Fusion roadmap. "
            "(4) Microsoft announced expanding its NVDA GPU fleet by 200,000 additional GB200 units for "
            "FY2026 delivery, reinforcing strong forward demand visibility. "
            "(5) NVDA stock hit a 52-week high of $1,142 on May 5, 2026, before pulling back to $1,127."
        ),
        "query_classes": ["factual_lookup", "signal_intel"],
    },
    {
        "key": "nvda_blackwell_chip_outlook",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-03-18T09:00:00Z",
        "title": "NVIDIA Blackwell GPU Ramp: GB200 Production Targets and Customer Delivery Schedule",
        "text": (
            "NVIDIA's Blackwell architecture (GB200, B100, B200 GPU family) began shipping in volume "
            "in Q4 fiscal 2025 (ending January 2026). Production ramp targets for fiscal 2026: "
            "Q4 FY2025 (Oct-Jan): ~200,000 GPU shipment equivalent. Q1 FY2026 (Feb-Apr): ~500,000 GPU equiv. "
            "Q2 FY2026 (May-Jul): ~700,000 GPU equiv. Q3 FY2026 (Aug-Oct): ~900,000 GPU equiv. "
            "The Blackwell B200 GPU offers 5x AI inference performance vs. H100 at comparable power envelopes. "
            "The GB200 NVL72 rack system (72 B200 GPUs in NVLink-connected configuration) provides "
            "30x LLM inference performance improvement vs. H100 8-GPU nodes. Pricing per GB200 GPU: "
            "approximately $40,000 rack price implies $70,000+ per GPU equivalent. Primary Blackwell customers: "
            "Microsoft (500,000+ GPUs contracted), Meta (400,000+), Google (350,000+), Amazon (250,000+). "
            "TSMC manufactures Blackwell chips on its 4NP process node, with CoWoS-L advanced packaging "
            "assembling the dual-die B200 chips. TSMC's packaging capacity was the primary production "
            "bottleneck that limited Q4 FY2025 Blackwell shipments. Packaging yields improved to ~82% "
            "by Q1 2026, enabling the production ramp."
        ),
        "query_classes": ["factual_lookup", "relationship"],
    },
    {
        "key": "nvda_data_center_revenue_fy2025",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2026-02-26T16:00:00Z",
        "title": "NVIDIA 10-K FY2026 — Data Center Revenue and Gross Margin Detail",
        "text": (
            "NVIDIA Corporation Data Center segment revenue for fiscal year 2026 (ending January 25, 2026) "
            "was $115.2 billion, an increase of 142% from $47.5 billion in fiscal 2025 (which itself was "
            "up 217% from fiscal 2024). Total company revenue was $130.5 billion, with Data Center "
            "comprising 88% of total revenue. Gaming segment revenue was $11.4 billion (+9% YoY). "
            "Professional Visualization was $2.3 billion (+17% YoY). Automotive was $1.7 billion (+55% YoY). "
            "OEM & Other was $0.2 billion. Full-year non-GAAP gross margin: 75.0%. GAAP gross margin: 74.6%. "
            "Non-GAAP operating income: $93.7 billion, operating margin 71.8%. "
            "Non-GAAP net income: $79.8 billion, EPS (diluted non-GAAP) $3.22. "
            "Fiscal 2026 free cash flow: $67.2 billion. Share repurchases: $35.7 billion. "
            "Headcount: 36,000 employees worldwide."
        ),
        "query_classes": ["factual_lookup", "financial_data"],
    },
    {
        "key": "nvda_h100_fy2024_detail",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2024-02-21T16:00:00Z",
        "title": "NVIDIA FY2024 10-K — H100 GPU Revenue Contribution and Customer Detail",
        "text": (
            "NVIDIA's fiscal 2024 (ending January 28, 2024) Data Center revenue was $47.5 billion. "
            "The H100 Tensor Core GPU was the primary product driving this growth. Based on management "
            "commentary and analyst estimates, H100 GPU sales contributed approximately 60-65% of total "
            "Data Center revenue — approximately $28-31 billion in H100-specific revenue. "
            "H100 was available in SXM5 (high-bandwidth NVLink-connected) and PCIe variants. "
            "Average selling price ranged from $25,000 (PCIe) to $40,000 (SXM5). "
            "An estimated 800,000 to 1.1 million H100 GPUs shipped in FY2024. "
            "The DGX H100 system (8x H100 in NVLink cluster) listed for $200,000, with large cluster "
            "purchases negotiated at significant discounts. NVIDIA's 10-K explicitly states that "
            "'A significant portion of our Data Center revenue in fiscal 2024 was attributable to products "
            "incorporating the Hopper architecture' — confirming H100 dominance. "
            "China Data Center revenue was approximately 20-25% of segment revenue before export restrictions."
        ),
        "query_classes": ["factual_lookup"],
    },
    # ── Tesla ──────────────────────────────────────────────────────────────
    {
        "key": "tsla_cybertruck_production_2026",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-01-30T10:00:00Z",
        "title": "Tesla Cybertruck Production Targets 2026: 150,000 Units Planned for Full Year",
        "text": (
            "Tesla Inc. provided updated Cybertruck production guidance on its Q4 2025 earnings call. "
            "CEO Elon Musk stated that Tesla is targeting 150,000 Cybertruck units for calendar year 2026, "
            "representing a 50% increase from the approximately 100,000 units produced in 2025. "
            "The Cybertruck's Gigafactory Texas production line has been expanded with additional tooling "
            "capacity. The Cybertruck Beast version (tri-motor, 845 hp) accounts for approximately 60% "
            "of production mix at an ASP of approximately $100,000, with the Cyberbeast being the primary "
            "profit contributor to the commercial pickup segment. "
            "Tesla also discussed the Cybertruck Cybercab adaptation — a commercial fleet conversion "
            "variant intended for robotaxi use — though this remains pre-production. "
            "For the Full Self-Driving (FSD) fiscal year 2026, Tesla expects approximately 1 million "
            "Cybertruck FSD subscriptions by year-end. "
            "Production constraints include 4680 battery cell supply from Nevada Gigafactory, which Tesla "
            "plans to expand to 300 GWh annual capacity by end of 2026."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "tsla_semi_production_nevada",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-28T08:00:00Z",
        "title": "Tesla Begins Semi Truck Mass Production at Nevada Gigafactory",
        "text": (
            "Tesla Inc. announced the start of mass production of the Tesla Semi truck at its Sparks, Nevada "
            "Gigafactory on April 28, 2026. Production targets for 2026 are 50,000 Semi units, ramping from "
            "approximately 12,000 units produced in 2025. Pepsi is the launch anchor customer with 400 Semis "
            "deployed in commercial fleet operations since December 2022. Walmart, UPS, Anheuser-Busch, and "
            "Sysco have placed orders exceeding 2,500 units combined. The Tesla Semi 500 (range 500 miles) "
            "has a pre-tax list price of $180,000 and the Semi 300 (range 300 miles) lists at $150,000. "
            "Payload capacity is 82,000 lbs (maximum legal weight). The Semi uses a four-motor drivetrain "
            "with independent motor-per-wheel and Tesla's Megapack-derived battery packs for 900 kWh total energy. "
            "Tesla's Nevada Gigafactory serves as both the Semi production site and houses the world's largest "
            "4680 battery cell production facility. Management expects Semi to be breakeven on a unit economics "
            "basis by Q3 2026 as production scale drives battery cost reductions."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "tsla_q1_2026_transcript_margin",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-23T21:00:00Z",
        "title": "Tesla Q1 2026 Earnings Call — Operating Margin Discussion",
        "text": (
            "VAIBHAV TANEJA (CFO): Our automotive gross margin in Q1 2026 was 16.3%, compared to 17.4% in "
            "Q1 2025 and 19.3% in Q1 2024. The 110 basis point year-over-year decline reflects the ongoing "
            "impact of price reductions implemented throughout 2024 and 2025 to defend volume against "
            "increasing competition from BYD, Xpeng, and other electric vehicle manufacturers. "
            "Total company operating margin was 6.1% in Q1 2026, versus 5.5% in Q4 2025. "
            "ELON MUSK: We made deliberate pricing decisions to maximize volume and market share. "
            "A Tesla at lower margin is better than no Tesla sold. We believe the long-term FSD and software "
            "revenue stream will more than compensate for near-term margin compression. Our Energy Storage "
            "segment gross margin was 24.4% in Q1, providing a diversifying profit stream. "
            "VAIBHAV TANEJA: R&D and SG&A expenses continue to increase as we invest in FSD, Cybercab, "
            "Semi, and Optimus robot programs. These investments pressure operating margin in the near term "
            "but are essential for Tesla's long-term competitive positioning."
        ),
        "query_classes": ["reasoning", "financial_data"],
    },
    {
        "key": "tsla_operating_margin_decline",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-25T10:00:00Z",
        "title": "Tesla Operating Margin Trend: Declining Despite Revenue Growth",
        "text": (
            "Tesla Inc. (TSLA) operating margin trend demonstrates a persistent decline despite revenue growth: "
            "Q1 2022: 19.2% operating margin on $18.8B revenue. "
            "Q1 2023: 11.4% on $23.3B revenue. Q1 2024: 5.5% on $21.3B revenue. "
            "Q3 2024: 10.8% on $25.2B (partial recovery from price stabilization). "
            "Q1 2025: 7.2% on $24.1B. Q4 2025: 5.5% on $26.4B. Q1 2026: 6.1% on $27.3B. "
            "The persistent margin compression despite revenue growth reflects: "
            "(1) Price cuts of 15-25% on Model 3/Y to compete with BYD and Xpeng; "
            "(2) Rising depreciation from factory capacity additions; "
            "(3) Elevated R&D spend on FSD, Optimus, Cybercab, Semi; "
            "(4) Higher SG&A from showroom expansion in China and Europe. "
            "Tesla's operating margin at 6.1% compares unfavorably to Ford at 5.2% (improving) and "
            "GM at 9.3% (stable). Tesla bulls argue that FSD software revenue, Energy Storage margins, "
            "and Optimus monetization will drive margin recovery in 2027-2028."
        ),
        "query_classes": ["reasoning", "financial_data"],
    },
    {
        "key": "tsla_debt_equity_ratio",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2026-02-05T16:00:00Z",
        "title": "Tesla Inc. 10-K FY2025 — Capital Structure and Debt-to-Equity Analysis",
        "text": (
            "Tesla Inc. balance sheet as of December 31, 2025 (fiscal year 2025): "
            "Total assets: $128.2 billion. Total debt: $5.8 billion (long-term debt $4.3B, current portion $1.5B). "
            "Total stockholders' equity: $74.9 billion. "
            "Debt-to-equity ratio: 5.8B / 74.9B = 0.077x (7.7%). Tesla has one of the lowest "
            "debt-to-equity ratios among major auto manufacturers. For comparison: Ford D/E = 3.2x, "
            "GM D/E = 2.8x, BYD D/E = 0.62x. Tesla substantially deleveraged from its 2019 peak "
            "debt-to-equity of approximately 2.4x as operating cash flow improved dramatically in 2021-2023. "
            "Net debt (debt minus cash): Tesla held $36.6 billion in cash and short-term investments as of "
            "December 31, 2025, making Tesla's net cash position $30.8 billion (net cash, not net debt). "
            "This strong balance sheet provides significant financial flexibility for R&D investment, "
            "factory construction, and share repurchases. Tesla initiated a $10 billion share repurchase "
            "program in February 2024."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "tsla_credit_lines_banks",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2026-02-05T16:00:00Z",
        "title": "Tesla 10-K FY2025 — Credit Facilities and Banking Relationships",
        "text": (
            "Tesla Inc.'s 10-K FY2025 discloses the following credit facilities and banking relationships: "
            "Revolving credit facility: $5.0 billion committed revolving credit line with a syndicate of "
            "lenders including Goldman Sachs, Morgan Stanley, JPMorgan Chase, Bank of America, Citibank, "
            "Wells Fargo, Deutsche Bank, and BNP Paribas. The facility matures in 2026 and was undrawn "
            "as of December 31, 2025. Automotive receivables securitization: Tesla maintains a $3.0 billion "
            "automotive receivables securitization facility through Morgan Stanley and Deutsche Bank. "
            "Chinese banking relationships: Gigafactory Shanghai construction and working capital are "
            "supported by credit facilities from Bank of China, China Merchants Bank, and Agricultural Bank "
            "of China totaling approximately CNY 14 billion ($2.0 billion equivalent). "
            "Term loan: $750 million term loan from JPMorgan Chase maturing Q3 2025 (repaid). "
            "Tesla's primary banking relationships for treasury and cash management include Goldman Sachs "
            "and JPMorgan Chase."
        ),
        "query_classes": ["relationship"],
    },
    {
        "key": "tsla_vs_ford_gm_gross_margin",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-30T10:00:00Z",
        "title": "Tesla vs Ford vs GM: Gross Margin Comparison Q1 2026 and Q4 2025",
        "text": (
            "Automotive gross margin comparison — Tesla, Ford, GM — two most recent quarters: "
            "Tesla Q4 2025: Automotive gross margin 16.9%. Tesla Q1 2026: 16.3%. "
            "Ford Q4 2025: Adjusted EBIT margin 4.1% (gross margin not directly reported; total gross ~8.2%). "
            "Ford Q1 2026: Adjusted EBIT margin 5.2%. "
            "General Motors Q4 2025: Adjusted EBIT margin 8.7%. GM Q1 2026: EBIT margin 9.3%. "
            "Tesla's automotive gross margin includes both hardware (vehicle) and software (FSD deferred revenue). "
            "Excluding FSD revenue, Tesla's underlying vehicle margin was approximately 14.8% in Q1 2026. "
            "GM's higher EBIT margin than Tesla reflects its stronger North American truck and SUV franchise "
            "(F-150 equivalent: GMC Sierra/Chevrolet Silverado) which command premium pricing. "
            "Ford's Pro commercial vehicle segment has a 10%+ EBIT margin, subsidizing the loss-making "
            "Ford Model e EV division which lost approximately $3.1 billion in 2025. "
            "Tesla's margin decline from 19% (2022) to 16% (2026) is the key competitive concern for investors."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "tsla_beta_sp500",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Tesla (TSLA) Beta Analysis: High Market Sensitivity Stock",
        "text": (
            "Tesla Inc. (TSLA) has a 5-year monthly beta of 2.31 versus the S&P 500 (as of May 2026). "
            "This makes TSLA the highest-beta stock in the demo portfolio, with returns that have historically "
            "been approximately 2.3x the S&P 500 on both the upside and downside. "
            "For comparison: AAPL beta 1.22, MSFT beta 0.90, NVDA beta 1.85, AMZN beta 1.15. "
            "TSLA's high beta reflects: high growth expectations embedded in valuation (P/E >60x forward), "
            "high retail investor ownership (~35% of float), high short interest (~2.8% of float), "
            "and news sensitivity around Elon Musk (Tesla/SpaceX/X/xAI executive overlap). "
            "On up-market days (>1% S&P 500), TSLA has historically outperformed by ~2.2x. "
            "On down-market days (<-1%), TSLA has historically underperformed by ~2.4x. "
            "Portfolio impact: TSLA's 12.4% portfolio weight combined with 2.31 beta contributes "
            "~28.6 beta-adjusted basis points of market sensitivity per $1 million in portfolio."
        ),
        "query_classes": ["portfolio"],
    },
    {
        "key": "tsla_portfolio_holding",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio: Tesla Inc. (TSLA) Position Summary",
        "text": (
            "Portfolio position: Tesla Inc. (TSLA). Shares: 75. Cost basis: $189.30/share (avg, accumulated 2023-2025). "
            "Current price: $232.80. Market value: $17,460.00. Unrealized gain: $3,263 (+23.0%). "
            "Portfolio weight: 12.4%. Beta: 2.31. Sector: Consumer Discretionary / EV Manufacturing. "
            "Ex-dividend date: Tesla does not currently pay a dividend. "
            "Next earnings: Q2 2026 expected late July 2026. "
            "Recent performance: TSLA up 4.2% YTD vs S&P 500 +9.1%. "
            "Key risk: margin compression from price cuts, Elon Musk brand/execution risk. "
            "TSLA ISIN: US88160R1014. Ticker: NASDAQ:TSLA."
        ),
        "query_classes": ["portfolio"],
    },
    {
        "key": "tsla_cybercab_production_detail",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-24T09:00:00Z",
        "title": "Tesla Begins Cybercab Robotaxi Production at Gigafactory Texas",
        "text": (
            "Tesla Inc. has begun initial production of the Cybercab autonomous robotaxi vehicle at "
            "Gigafactory Texas as of April 2026. The Cybercab is a two-seater EV designed specifically "
            "for autonomous ride-sharing, featuring no steering wheel or pedals — the first Tesla production "
            "vehicle without manual driver controls. Initial production targets are 5,000 Cybercabs for "
            "2026, scaling to 100,000 annually in 2027 subject to regulatory approval from NHTSA and state "
            "autonomous vehicle authorities. The vehicle uses the HW4 Full Self-Driving computer and "
            "Tesla's next-generation AI5 inference chip. Base price is expected at approximately $30,000. "
            "Elon Musk has stated Tesla plans to deploy Cybercabs in its own Tesla Network ride-sharing "
            "service, potentially enabling vehicle owners to generate income. "
            "The Cybercab is powered by a 60 kWh battery pack with wireless inductive charging capability. "
            "It will qualify for the $7,500 IRA federal EV tax credit. Production constraints include "
            "AI5 chip supply from Samsung Foundry."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "tsla_semi_production_detail",
        "source_type": "press_release",
        "source_name": "sec_edgar",
        "published_at": "2026-04-28T08:00:00Z",
        "title": "Tesla Semi Mass Production Launch: Press Release",
        "text": (
            "SPARKS, Nevada, April 28, 2026 — Tesla Inc. today announced the official launch of mass production "
            "for the Tesla Semi at its Gigafactory Nevada facility. The Tesla Semi 500, the flagship long-range "
            "variant with 500 miles of range on a single charge, will enter mass production first, followed by "
            "the Tesla Semi 300 in Q3 2026. Production guidance for calendar year 2026 is 50,000 units. "
            "Confirmed customer orders: Pepsi (4,000 units), Walmart (1,000 units), Amazon (1,800 units), "
            "UPS (150 units), FedEx (200 units), Sysco (100 units), Anheuser-Busch (200 units). "
            "The Semi uses a four permanent-magnet motor drivetrain with 500 kW of peak power per motor. "
            "Charging via Tesla Megacharger: 400 miles of range in 30 minutes at 1 MW power. "
            "Lifetime cost of ownership per mile is estimated at $1.26 versus $1.51 for diesel Class 8 trucks "
            "at $4.00/gallon diesel and $0.12/kWh electricity. CEO Elon Musk: 'The Semi will transform "
            "trucking economics, just as Tesla transformed passenger EV economics.'"
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "tsla_fsd_revenue_recognition",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-23T21:00:00Z",
        "title": "Tesla Q1 2026 Earnings — Full Self-Driving Revenue Recognition Discussion",
        "text": (
            "VAIBHAV TANEJA: Full Self-Driving revenue recognition continues to evolve as our FSD capabilities "
            "improve. In Q1 2026, we recognized approximately $0.9 billion of previously deferred FSD revenue "
            "following the achievement of FSD milestones under ASC 606 criteria. Total deferred FSD revenue "
            "on balance sheet as of March 31, 2026 was $6.8 billion, down from $7.4 billion a year ago as "
            "recognition has begun to exceed new deferrals. FSD v13 subscription revenue (at $99/month) "
            "contributed $0.31 billion in Q1 2026, growing 22% year-over-year. "
            "ELON MUSK: FSD v14 capability will enable unsupervised autonomous driving in geofenced areas "
            "in California and Texas by year-end 2026, subject to regulatory approval. This milestone would "
            "trigger additional deferred revenue recognition under our accounting policy. "
            "VAIBHAV TANEJA: We expect FSD-related revenue (recognized deferred plus subscriptions) of "
            "approximately $4 billion in fiscal 2026, a significant increase from $1.8 billion in fiscal 2025."
        ),
        "query_classes": ["factual_lookup", "reasoning"],
    },
    {
        "key": "tsla_energy_storage_revenue",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-23T21:00:00Z",
        "title": "Tesla Q1 2026 Earnings — Energy Storage Segment Performance",
        "text": (
            "VAIBHAV TANEJA: Our Energy Storage and Generation segment reported revenue of $3.7 billion "
            "in Q1 2026, up 67% year-over-year, driven by record Megapack deployments. "
            "Megapack deployments in Q1 2026 were 10.4 GWh, up 140% year-over-year. "
            "Energy Storage gross margin was 24.4%, a record for the segment and up from 20.1% in Q1 2025. "
            "We are benefiting from scale economies at Megafactory Lathrop, where Megapack production "
            "costs have declined 35% since 2023. Utility-scale energy storage demand is accelerating as "
            "grid operators deploy storage to support intermittent renewable generation. "
            "Tesla has a backlog of $12.3 billion in Megapack orders for delivery in 2026-2027. "
            "Solar roof deployments were 68 MW in Q1 2026, down sequentially due to installation crew "
            "availability constraints. The Energy segment's 24.4% gross margin is approaching our automotive "
            "segment margin, which demonstrates the business's potential as a significant profit driver "
            "independent of vehicle sales."
        ),
        "query_classes": ["factual_lookup"],
    },
    # ── Amazon ─────────────────────────────────────────────────────────────
    {
        "key": "amzn_aws_operating_margin_q1_2026",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T21:00:00Z",
        "title": "Amazon Q1 2026 Earnings — AWS Operating Margin and Profitability",
        "text": (
            "BRIAN OLSAVSKY (CFO): AWS delivered another quarter of strong financial performance in Q1 2026. "
            "AWS revenue was $29.3 billion, up 17% year-over-year. More importantly, AWS operating income "
            "was $11.5 billion, up 47% year-over-year, with an operating margin of 39.5% — a new all-time record "
            "for the segment. This compares to AWS operating margin of 37.6% in Q4 2025 and 37.6% in Q1 2025. "
            "The margin expansion reflects: (1) revenue scale covering fixed infrastructure costs; "
            "(2) improved server and network hardware utilization; (3) favorable energy cost trends in certain "
            "data center regions; (4) growing mix of higher-margin AI services. "
            "ANDY JASSY: AWS is the profit engine that funds our entire investment in consumer retail, logistics, "
            "advertising, and AI. The 39.5% operating margin demonstrates that cloud infrastructure, properly "
            "run at scale, can generate extraordinary returns. We continue to invest heavily in AI capabilities "
            "including Amazon Bedrock, SageMaker, and Trainium/Inferentia custom silicon to serve customers "
            "with lower-cost AI compute alternatives to GPU-based solutions."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "amzn_aws_q1_2026_8k",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T20:30:00Z",
        "title": "Amazon.com Inc. Form 8-K: Q1 2026 Financial Results",
        "text": (
            "SEATTLE — May 1, 2026 — Amazon.com, Inc. announced financial results for its first quarter "
            "ended March 31, 2026. Net sales were $187.0 billion, a 9% increase year-over-year. "
            "Operating income was $18.4 billion vs $15.3 billion in Q1 2025. "
            "North America net sales: $92.9B (+8% YoY). International net sales: $34.5B (+5% YoY). "
            "AWS net sales: $29.3B (+17% YoY). AWS operating income: $11.5B (+47% YoY). "
            "Advertising services net sales: $13.9B (+19% YoY). "
            "Net income: $17.1 billion vs $10.4 billion in Q1 2025. EPS: $1.59 vs $0.98. "
            "Capital expenditures Q1 2026: $24.3 billion (primarily AWS infrastructure). "
            "Q2 2026 guidance: net sales $159B-$164B, operating income $13.0B-$17.0B."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "amzn_free_cash_flow_fy2024",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2025-02-01T16:00:00Z",
        "title": "Amazon 10-K FY2024 — Free Cash Flow Analysis",
        "text": (
            "Amazon.com, Inc. generated free cash flow of $56.0 billion in fiscal year 2024, compared to "
            "$32.0 billion in fiscal 2023 — a 75% year-over-year increase. "
            "Operating cash flow was $115.9 billion. Capital expenditures (including acquisitions of property "
            "and equipment and capital leases) totaled $59.9 billion. "
            "Free cash flow = Operating cash flow ($115.9B) minus capex and capital leases ($59.9B) = $56.0B. "
            "On a trailing twelve-month basis as of December 31, 2024, this represents the highest annual "
            "free cash flow Amazon has ever generated. The dramatic improvement from FY2023 reflects: "
            "(1) AWS operating leverage with 17% revenue growth at 37%+ margins; "
            "(2) North American retail returning to profitability after years of losses; "
            "(3) advertising services growing at 19%, high-margin incremental revenue; "
            "(4) cost reduction initiatives reducing headcount by approximately 27,000 in 2023. "
            "Amazon's FY2024 free cash flow of $56 billion compares to Apple ($110B), Microsoft ($74B), "
            "and Meta ($52B) for the same calendar period."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "amzn_retail_margin_improvement",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T21:00:00Z",
        "title": "Amazon Q1 2026 Earnings — Retail Margin Improvement with Slowing Revenue Growth",
        "text": (
            "ANDY JASSY: Our North America retail segment delivered 5.5% operating margin in Q1 2026 versus "
            "3.8% in Q1 2025, demonstrating meaningful profitability improvement even as top-line growth "
            "moderates. NA revenue grew 8% year-over-year in Q1, slower than 12% in Q1 2025, but margin "
            "expanded 170 basis points. This is the retail segment's highest margin in several years. "
            "BRIAN OLSAVSKY: Three factors are driving retail margin improvement while growth slows: "
            "(1) Regionalized US fulfillment network: we redesigned our US distribution into 8 regions "
            "which reduced same-day and next-day shipping costs by reducing average package travel distance; "
            "(2) Third-party seller mix: 3P sellers accounted for 62% of unit sales in Q1 2026, up from 59% "
            "a year ago; 3P revenue (commissions + fulfillment fees) is substantially higher-margin than "
            "1P retail inventory sales; "
            "(3) Advertising attach: every retail transaction increasingly includes advertising impressions "
            "from Sponsored Products and Sponsored Brands, which are nearly pure profit margin."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "amzn_vs_azure_cloud_growth",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "AWS vs Azure Four-Quarter Cloud Growth Rate Comparison",
        "text": (
            "Cloud revenue growth rate comparison — AWS versus Azure — past four quarters: "
            "Q2 2025 (calendar): AWS +19%, Azure +26% constant currency. "
            "Q3 2025 (calendar): AWS +19%, Azure +28% constant currency. "
            "Q4 2025 (calendar): AWS +18%, Azure +26% constant currency. "
            "Q1 2026 (calendar): AWS +17%, Azure +33% constant currency. "
            "On a trailing four-quarter basis: AWS average growth 18.3%, Azure average 28.3%. "
            "Azure has consistently outgrown AWS by approximately 10 percentage points per quarter over "
            "this period. The gap widened in Q1 2026 due to Azure's AI services acceleration. "
            "On absolute revenue: AWS Q1 2026 revenue was $29.3 billion versus Azure's estimated $25.2B. "
            "AWS maintains the lead in absolute dollar terms, though Azure is closing the gap. "
            "AWS operating margin of 39.5% versus Azure (within Microsoft Intelligent Cloud) of ~47% "
            "illustrates different margin profile dynamics — Azure is part of a bundled segment. "
            "Market share estimates: AWS ~30%, Azure ~25%, Google Cloud ~12%, others ~33%."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "amzn_capex_hyperscaler",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-05-02T09:00:00Z",
        "title": "Amazon Q1 2026: $24.3B Capex Confirms Major AWS AI Infrastructure Push",
        "text": (
            "Amazon reported Q1 2026 capital expenditures of $24.3 billion, up 74% year-over-year from "
            "$13.9 billion in Q1 2025. This represents the largest quarterly capex in Amazon's history. "
            "Management guided 'similar or higher' capex for Q2-Q4 2026, implying full-year capex of "
            "approximately $100+ billion — a step-change from the $59.9 billion spent in FY2024. "
            "The increase is almost entirely attributable to AWS AI infrastructure: data centers for "
            "GPU-based AI training and inference, custom silicon (Trainium, Inferentia) manufacturing "
            "commitments, and network capacity. On a trailing four-quarter basis through Q1 2026, "
            "Amazon capex totaled $79.6 billion — behind Microsoft ($82.3B) but ahead of Alphabet ($58.1B) "
            "and Meta ($48.6B). Amazon's capex-to-revenue ratio increased from 8.2% in 2024 to an "
            "estimated 12.8% in 2026, the highest since Amazon's early e-commerce infrastructure build-out."
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    {
        "key": "amzn_institutional_blackrock",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-15T16:00:00Z",
        "title": "Amazon 13F: BlackRock Increases Position by 12M Shares in Q1 2026",
        "text": (
            "BlackRock Inc. (BLK) disclosed in its 13F-HR filing for Q1 2026 (filed May 15, 2026) that "
            "it increased its Amazon.com (AMZN) position by 12.3 million shares to 412.8 million shares. "
            "This represents a 3.1% quarter-over-quarter increase in BlackRock's AMZN stake, which now "
            "has a market value of approximately $94.2 billion at the current $228.20/share price. "
            "BlackRock is Amazon's second-largest institutional shareholder after Vanguard. "
            "The increase in BlackRock's position occurred across multiple index funds (S&P 500 ETF, "
            "total market ETF) and active strategies including BlackRock's Global Allocation Fund. "
            "At 3.1% of shares outstanding, BlackRock holds the largest individual institutional position "
            "in Amazon, followed by Vanguard (3.0%), State Street (1.8%), Fidelity (1.3%), and T. Rowe Price (0.9%)."
        ),
        "query_classes": ["relationship", "signal_intel"],
    },
    {
        "key": "amzn_institutional_vanguard",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-15T16:00:00Z",
        "title": "Vanguard 13F Q1 2026: Amazon Position Detail",
        "text": (
            "Vanguard Group disclosed in its 13F-HR for Q1 2026 that it holds 396.2 million shares of "
            "Amazon.com (AMZN), a decrease of 1.8 million shares (-0.5% QoQ) from its Q4 2025 position. "
            "Vanguard's AMZN stake represents 3.0% of shares outstanding and has a market value of "
            "$90.4 billion. The slight decrease reflects index rebalancing rather than a strategic decision "
            "to reduce Amazon exposure — Vanguard's index funds passively track the S&P 500 weighting. "
            "Amazon's S&P 500 weight increased marginally in Q1 2026 due to relative share price "
            "underperformance versus the index, which mechanically reduces index fund exposure. "
            "Vanguard, BlackRock, and State Street (the 'Big Three' passive managers) collectively own "
            "approximately 20.5% of Amazon's outstanding shares. These positions are purely index-driven "
            "and do not reflect active investment views on Amazon's business prospects."
        ),
        "query_classes": ["relationship", "signal_intel"],
    },
    {
        "key": "amzn_portfolio_holding",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio: Amazon.com Inc. (AMZN) Position",
        "text": (
            "Portfolio position: Amazon.com Inc. (AMZN). Shares: 55. Cost basis: $148.20/share. "
            "Current price: $228.20. Market value: $12,551.00. Unrealized gain: $4,400 (+54.0%). "
            "Portfolio weight: 8.9%. Sector: Consumer Discretionary / Technology. Beta: 1.15. "
            "Amazon does not pay a dividend. Next earnings: Q2 2026 expected late July 2026. "
            "AMZN ISIN: US0231351067. AWS operating margin of 39.5% is key earnings driver. "
            "YTD return: +12.3% vs S&P 500 +9.1%."
        ),
        "query_classes": ["portfolio"],
    },
    {
        "key": "amzn_aws_q3_2025_transcript",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2025-10-31T21:00:00Z",
        "title": "Amazon Q3 2025 Earnings — AWS Growth and AI Buildout",
        "text": (
            "BRIAN OLSAVSKY: AWS revenue in Q3 2025 was $27.5 billion, up 19% year-over-year. "
            "AWS operating income was $10.4 billion, operating margin 37.8% — a new quarterly high. "
            "Year-to-date AWS operating income of $30.6 billion demonstrates the scale and efficiency "
            "of our cloud infrastructure business. We are seeing strong AI workload demand from enterprises "
            "migrating data warehousing, ML training, and inference to AWS. Amazon Bedrock now has over "
            "100,000 active enterprise customers. SageMaker AI training workloads grew 50% year-over-year. "
            "ANDY JASSY: We are investing $75+ billion in AWS infrastructure in 2025, the majority of which "
            "is for AI compute capacity. Trainium 2 chip availability is expanding and we are seeing "
            "strong customer interest in Trainium as a cost-effective alternative to H100 for certain "
            "training workloads. AWS revenue growth of 19% in Q3 compares to Azure's 28% constant currency growth. "
            "We remain the largest cloud platform and are confident in our long-term market position."
        ),
        "query_classes": ["factual_lookup", "comparison"],
    },
    {
        "key": "amzn_fcf_fy2024_detail",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2025-02-05T10:00:00Z",
        "title": "Amazon FY2024 Free Cash Flow: $56B Record — Components and Drivers",
        "text": (
            "Amazon's fiscal year 2024 free cash flow breakdown: "
            "Net income: $59.2 billion (GAAP). Depreciation & amortization: $52.4B. "
            "Stock-based compensation: $24.1B. Working capital change: -$12.8B (higher inventory). "
            "Other: -$7.0B. Operating cash flow: $115.9B. "
            "Less: Property and equipment purchases: -$32.4B. "
            "Less: Finance lease acquisitions: -$27.5B. Free cash flow: $56.0B. "
            "Comparison of Amazon FCF 2020-2024: 2020: $26.4B, 2021: -$9.1B (warehouse buildout peak), "
            "2022: -$19.7B (continued over-investment), 2023: $32.0B (cost cuts begin), 2024: $56.0B. "
            "The recovery from negative FCF in 2021-2022 to $56B in 2024 is driven by AWS margin expansion, "
            "North America retail profitability, and right-sizing of fulfillment center capacity. "
            "Amazon generated more FCF per dollar of revenue than any comparable e-commerce company."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "amzn_aws_margin_trend",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-02T10:00:00Z",
        "title": "AWS Operating Margin Trend: Q1 2025 Through Q1 2026",
        "text": (
            "Amazon Web Services (AWS) operating margin quarterly trend: "
            "Q1 2025: $29.3B revenue... wait — Q1 2025 AWS revenue $25.0B, operating margin 37.6%. "
            "Q2 2025: $26.3B revenue, operating margin 38.7%. "
            "Q3 2025: $27.5B revenue, operating margin 37.8%. "
            "Q4 2025: $28.8B revenue, operating margin 37.6%. "
            "Q1 2026: $29.3B revenue, operating margin 39.5% (record). "
            "AWS has expanded operating margin by approximately 190 basis points over the trailing four quarters, "
            "driven by: high-margin AI services (Bedrock, SageMaker) growing faster than base compute; "
            "server hardware efficiency improvements reducing depreciation per unit; energy efficiency gains "
            "at newer data center facilities; and operating leverage from spreading fixed costs over higher revenue. "
            "AWS operating margin at 39.5% compares to Intelligent Cloud (Azure segment) at approximately 47%, "
            "though the Azure segment includes GitHub, LinkedIn, and other services alongside cloud infrastructure."
        ),
        "query_classes": ["factual_lookup", "comparison"],
    },
    {
        "key": "amzn_q4_2024_transcript",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2025-02-06T21:00:00Z",
        "title": "Amazon Q4 2024 Earnings Call — Andy Jassy on AWS and Retail Profitability",
        "text": (
            "ANDY JASSY: 2024 was an extraordinary year for Amazon across all of our businesses. "
            "AWS grew to a $115 billion annual run rate with 37.6% operating margin, generating "
            "over $35 billion in operating income for the full year. This is the largest and most "
            "profitable year AWS has ever had. In North America retail, we achieved a 5.1% operating margin "
            "for full year 2024, the first time North America retail has exceeded 5% EBIT margin. "
            "Our regionalized fulfillment network investment is paying off — same-day delivery now covers "
            "70% of US Prime members. Advertising services delivered $56.2 billion in revenue for 2024 "
            "at very high margins, contributing meaningfully to consolidated profitability. "
            "BRIAN OLSAVSKY: Total 2024 net income was $59.2 billion, up 95% from $30.4 billion in 2023. "
            "Diluted EPS was $5.53. Operating cash flow was $115.9 billion, free cash flow was $56.0 billion. "
            "We expect 2025 capex to be approximately $75 billion, driven predominantly by AWS AI infrastructure."
        ),
        "query_classes": ["factual_lookup", "reasoning"],
    },
    # ── Meta ───────────────────────────────────────────────────────────────
    {
        "key": "meta_buyback_announcement_2025",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2025-07-30T20:30:00Z",
        "title": "Meta Platforms Form 8-K: $50 Billion Share Repurchase Authorization",
        "text": (
            "MENLO PARK, California — July 30, 2025 — Meta Platforms, Inc. announced that its Board of "
            "Directors has authorized an additional $50 billion in share repurchases, increasing total "
            "authorized buyback capacity to approximately $30 billion (remaining unexecuted balance from "
            "prior authorizations plus this new $50 billion authorization). This is Meta's largest single "
            "buyback authorization in company history. Since going public in 2012, Meta has repurchased "
            "approximately $175 billion of shares. In Q2 2025, Meta repurchased $6.3 billion of Class A "
            "common stock. The new authorization has no expiration date. CEO Mark Zuckerberg: "
            "'Our strong free cash flow generation and confidence in Meta's long-term growth trajectory "
            "make continued buybacks a compelling capital allocation decision. We will continue to balance "
            "buybacks with our significant investments in AI infrastructure and the metaverse.' "
            "Meta reported Q2 2025 revenue of $42.3 billion (+22% YoY) and free cash flow of $14.8 billion."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "meta_ai_infrastructure_spend",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-30T21:00:00Z",
        "title": "Meta Q1 2026 Earnings Call — AI Infrastructure Investment Commitment",
        "text": (
            "MARK ZUCKERBERG: AI is central to everything we are building. In 2026, we plan to invest "
            "$60-65 billion in capital expenditures, primarily for AI training and inference infrastructure. "
            "This includes our Llama 4 training cluster — the largest single-company AI training cluster "
            "ever built, using 600,000 H100-equivalent GPUs across multiple data centers. "
            "This investment is already generating returns: Llama 4 powering AI features in Facebook, "
            "Instagram, and WhatsApp contributed to 8% engagement growth across our apps in Q1. "
            "Meta AI assistant has surpassed 900 million monthly active users across our platforms, "
            "making it the most widely used AI assistant in the world. Advertising efficiency powered by "
            "AI-driven targeting has improved advertiser ROI by approximately 25%, which is why our "
            "ad revenue grew 18% year-over-year in Q1 despite a challenging macroeconomic environment. "
            "SUSAN LI: Full-year 2026 capex guidance: $60-65 billion, up from $37.3 billion in 2025."
        ),
        "query_classes": ["factual_lookup", "comparison"],
    },
    {
        "key": "meta_ad_revenue_q1_2026",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-30T21:00:00Z",
        "title": "Meta Q1 2026 Earnings — Ad Revenue Recovery and Drivers",
        "text": (
            "SUSAN LI: Total revenue in Q1 2026 was $42.3 billion, up 18% year-over-year. "
            "Advertising revenue was $41.4 billion, up 18%. Family of Apps daily active people was 3.43 billion, "
            "up 7% year-over-year. Average price per ad increased 14% year-over-year. "
            "Ad impressions grew 4% year-over-year. The ad pricing improvement reflects: "
            "(1) AI-driven relevance improvements — our Andromeda and Advantage+ AI systems now select ads "
            "for each user from a much larger pool of relevant candidates, improving click-through rates "
            "by 15-20% versus a year ago; (2) Reels monetization maturation — Reels ad load and eCPM "
            "have converged with feed-based inventory; (3) Click-to-message ads (WhatsApp Business) "
            "now contribute over $1 billion per quarter; (4) China-based advertisers spending on "
            "US/EU user acquisition contributed approximately $6 billion in 2025. "
            "Operating income was $17.6 billion, operating margin 41.6%."
        ),
        "query_classes": ["reasoning", "factual_lookup"],
    },
    {
        "key": "meta_vs_snap_ad_revenue",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "Meta vs Snap Advertising Revenue Growth — Trailing Four Quarters",
        "text": (
            "Advertising revenue growth comparison — Meta Platforms vs. Snap Inc. — trailing four quarters: "
            "Q2 2025: Meta ad revenue +22%, Snap ad revenue +16%. "
            "Q3 2025: Meta ad revenue +19%, Snap ad revenue +15%. "
            "Q4 2025: Meta ad revenue +21%, Snap ad revenue +14%. "
            "Q1 2026: Meta ad revenue +18%, Snap ad revenue +12%. "
            "On a trailing four-quarter average: Meta +20%, Snap +14.3%. "
            "Meta's consistent outperformance reflects its dominant audience scale (3.4B daily active people) "
            "versus Snap's 450 million daily active users, as well as superior AI-driven ad targeting "
            "through Advantage+ which improves advertiser ROI. Snap's Spotlight short-form video platform "
            "has grown but has not closed the monetization gap with Meta Reels. "
            "Revenue absolute: Meta Q1 2026 $41.4B vs Snap $1.4B — Meta is 29x Snap's revenue. "
            "Meta's operating margin is 41.6% vs Snap's adjusted EBITDA margin of 6.1%."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "meta_arpu_north_america",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-30T21:00:00Z",
        "title": "Meta Q1 2026 Earnings — ARPU by Geography Including North America",
        "text": (
            "SUSAN LI: Revenue per person (ARPU) by geography for Q1 2026: "
            "United States and Canada: $68.44 ARPU per daily active person. This represents an increase "
            "of 12% from $61.08 in Q1 2025. US&C ARPU is Meta's highest by region. "
            "Europe: $19.76 ARPU per DAP, up 9% YoY. Asia Pacific: $5.32 ARPU per DAP, up 14% YoY. "
            "Rest of World: $4.11 ARPU per DAP, up 18% YoY. "
            "The US&C ARPU increase reflects: higher ad prices driven by AI targeting improvements; "
            "growth in click-to-message and shopping ads; and monetization of AI features through "
            "Meta Verified and Quest platform. Q1 is seasonally the weakest quarter for ARPU due to "
            "lower advertiser spend post-holiday season. Q4 2025 US&C ARPU was $81.12 — the seasonal "
            "peak. North America (US&C) accounted for approximately 47% of total revenue despite "
            "representing a smaller fraction of total daily active people."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "meta_insider_selling_2025",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2025-12-15T10:00:00Z",
        "title": "Meta Platforms: Mark Zuckerberg Sells $300M in Shares Q4 2025",
        "text": (
            "Meta Platforms CEO Mark Zuckerberg sold approximately 1.3 million shares of Meta Class A common "
            "stock in Q4 2025, totaling approximately $300 million in proceeds. The sales were executed under "
            "a pre-established Rule 10b5-1 trading plan, which Zuckerberg established in September 2025. "
            "Zuckerberg sold at prices ranging from $218 to $245 per share during October and November 2025. "
            "This follows prior selling activity: Zuckerberg sold approximately $428 million in Q3 2025, "
            "$512 million in Q2 2025, and $1.1 billion in Q1 2025. Total 2025 Zuckerberg share sales: "
            "approximately $2.3 billion. Despite the sales, Zuckerberg continues to hold approximately "
            "350 million shares (Class A and B combined), giving him 57% voting control via supervoting "
            "Class B shares. The 10b5-1 plan sales are pre-scheduled and do not necessarily reflect "
            "Zuckerberg's view on Meta's current valuation or near-term performance."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "meta_capex_hyperscaler",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-30T22:00:00Z",
        "title": "Meta Q1 2026 Capex: $13.7B Quarterly Spend on AI Infrastructure",
        "text": (
            "Meta Platforms reported Q1 2026 capital expenditure of $13.7 billion, up 61% year-over-year "
            "from $8.5 billion in Q1 2025. Full-year 2026 guidance: $60-65 billion, implying approximately "
            "$15-17 billion per quarter through the rest of 2026. "
            "Meta's capex is concentrated in AI compute: the Llama 4 training cluster in Iowa uses "
            "approximately 200,000 H100 GPUs, with additional clusters being built in Wyoming, Mississippi, "
            "and New Mexico. Meta is also constructing its first non-US AI data center in Singapore. "
            "Among the four major hyperscalers, capex rank by trailing twelve months (Q2 2025-Q1 2026): "
            "Microsoft $82.3B > Amazon $79.6B > Meta $48.6B > Alphabet $58.1B. "
            "On a year-over-year growth rate, Microsoft (+63%) grew capex fastest, followed by Amazon (+53%), "
            "then Google (+41%), then Meta (+37%)."
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    {
        "key": "meta_ad_recovery_reasoning",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2025-10-31T09:00:00Z",
        "title": "What Drove Meta's Advertising Revenue Recovery? Three Structural Factors",
        "text": (
            "Meta Platforms' advertising revenue recovered from the 2022 trough ($116B, -1% YoY) to "
            "consecutive growth quarters of 23%, 19%, 22%, and 21% through 2023-2024. Three structural "
            "factors drove this recovery: (1) ATT recovery — Apple's App Tracking Transparency (April 2021) "
            "initially devastated Meta's ad targeting precision, costing an estimated $10B+ in 2022. "
            "Meta rebuilt on-device AI with the Privacy Enhancing Technology (PET) framework to partially "
            "restore targeting without cross-app tracking; (2) Reels monetization — short-form video "
            "initially cannibalized higher-monetizing feed inventory, but Reels CPMs have risen to "
            "near-parity with feed ads as the format matured; (3) Advantage+ AI automation — Meta's "
            "AI-powered campaign automation now manages budget, bidding, and creative selection for over "
            "50% of Meta ad spend, with demonstrably better ROI driving advertising budget migration from "
            "competitors like Snap, Pinterest, and Twitter/X."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "meta_q4_2025_8k",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2026-01-29T20:30:00Z",
        "title": "Meta Platforms Form 8-K: Q4 2025 Financial Results",
        "text": (
            "MENLO PARK, California — January 29, 2026 — Meta Platforms, Inc. today reported financial "
            "results for the fourth quarter and full year ended December 31, 2025. "
            "Q4 2025: Revenue $48.4B (+21% YoY). Operating income $23.4B (+25% YoY). Net income $20.5B. "
            "Diluted EPS $8.02. Daily active people 3.35B (+5% YoY). ARPU $14.43 (+15% YoY). "
            "Full year 2025: Revenue $170.1B (+20% YoY). Operating income $76.2B (+38% YoY). "
            "Net income $62.3B. Diluted EPS $24.25. Free cash flow: $52.1B. "
            "Capex 2025: $37.3B (+38% YoY). Share repurchases: $19.2B. "
            "Q1 2026 Guidance: Revenue $41-43B (+16-22% YoY). Capex 2026 guidance: $60-65B."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "meta_q1_2026_8k_buyback",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2026-04-30T20:30:00Z",
        "title": "Meta Platforms Form 8-K: Q1 2026 Results and Buyback Update",
        "text": (
            "MENLO PARK, California — April 30, 2026 — Meta Platforms, Inc. reported Q1 2026 results. "
            "Q1 2026 revenue: $42.3B (+18% YoY). Operating income: $17.6B (+24% YoY). EPS: $6.43 (+29%). "
            "Share repurchases in Q1 2026: $4.1 billion of Class A common stock. As of March 31, 2026, "
            "approximately $38.7 billion remains available under authorized repurchase programs. "
            "Meta has repurchased approximately $182 billion of shares since its IPO in 2012. "
            "Q2 2026 revenue guidance: $44-48 billion, representing 15-25% growth year-over-year. "
            "2026 capex guidance maintained at $60-65 billion. MARK ZUCKERBERG: 'AI is transforming "
            "every part of our business and we are pleased with the early returns on our AI investments. "
            "Meta AI is now used by over 900 million people monthly.'"
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "meta_arpu_detail",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Meta Platforms ARPU Detail: North America Q1 2026 vs. Prior Quarters",
        "text": (
            "Meta Platforms average revenue per person (ARPU) for United States and Canada (US&C): "
            "Q1 2024: $54.11, Q2 2024: $66.03, Q3 2024: $63.54, Q4 2024: $76.39. "
            "Q1 2025: $61.08, Q2 2025: $72.45, Q3 2025: $69.32, Q4 2025: $81.12. "
            "Q1 2026: $68.44. "
            "Q1 is consistently the seasonal trough (low advertiser spend post-holidays), Q4 the peak (holidays). "
            "The year-over-year growth in Q1 2026 US&C ARPU of 12% reflects AI-driven ad price improvements. "
            "Global ARPU for Q1 2026: $12.32 (vs $10.81 in Q1 2025, +14% YoY). "
            "North America's high ARPU ($68.44) vs global ($12.32) demonstrates the premium US advertising market. "
            "Meta's long-term goal is to grow international ARPU toward North American levels as digital "
            "advertising penetration increases in India, Brazil, and Southeast Asia."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "meta_snap_comparison_detail",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "Meta vs Snap: Ad Revenue Growth Detailed Quarterly Comparison",
        "text": (
            "Detailed quarterly advertising revenue comparison: Meta Platforms vs Snap Inc. "
            "Q2 2025: Meta $38.7B (+22% YoY), Snap $1.25B (+16% YoY). "
            "Q3 2025: Meta $40.6B (+19% YoY), Snap $1.37B (+15% YoY). "
            "Q4 2025: Meta $47.2B (+21% YoY), Snap $1.56B (+14% YoY). "
            "Q1 2026: Meta $41.4B (+18% YoY), Snap $1.40B (+12% YoY). "
            "Four-quarter average growth: Meta +20.0%, Snap +14.3%. "
            "Meta's growth advantage over Snap has widened from roughly 4-5pp in early 2024 to 6-7pp. "
            "This divergence is driven by Reels monetization maturity and Advantage+ AI outperforming "
            "Snap's Dynamic Ads targeting capabilities. Snap's user growth (450M DAU) is also slower "
            "than Meta's Family of Apps (3.43B DAP). Meta trades at 22x 2026 earnings vs Snap at 65x — "
            "the valuation gap reflects Meta's demonstrated earnings power vs Snap's breakeven trajectory."
        ),
        "query_classes": ["comparison"],
    },
    # ── JPMorgan Chase ─────────────────────────────────────────────────────
    {
        "key": "jpm_dividend_q1_2026_8k",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2026-03-17T16:00:00Z",
        "title": "JPMorgan Chase Form 8-K: Q1 2026 Dividend Declaration",
        "text": (
            "NEW YORK — March 17, 2026 — JPMorgan Chase & Co. (NYSE: JPM) announced that its Board of "
            "Directors declared a quarterly cash dividend on the company's common stock of $1.40 per share, "
            "payable on April 30, 2026 to stockholders of record at the close of business on April 5, 2026. "
            "This dividend of $1.40 per share represents a 9.4% increase from the prior quarterly dividend "
            "of $1.28 per share declared in March 2025. On an annualized basis, JPMorgan's common stock "
            "dividend is $5.60 per share, yielding approximately 2.0% at the current share price of $278.50. "
            "JPMorgan Chase has paid uninterrupted dividends for 54 consecutive years and has increased the "
            "dividend for 12 consecutive years, reflecting the company's consistent capital generation. "
            "CEO Jamie Dimon: 'Our strong capital position and earnings power allow us to continue returning "
            "meaningful capital to shareholders while maintaining our fortress balance sheet.' "
            "The company also authorized $30 billion in share repurchases for 2026."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "jpm_q1_2026_transcript",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-11T13:00:00Z",
        "title": "JPMorgan Chase Q1 2026 Earnings Call — NII and Banking Revenue",
        "text": (
            "JAMIE DIMON: Q1 2026 demonstrated the power of JPMorgan's diversified business model. "
            "Net revenue was $46.4 billion, up 8% year-over-year. Net interest income was $24.1 billion, "
            "down 3% as rates declined, offset by strong fee-based revenue. "
            "JEREMY BARNUM (CFO): Net interest income declined due to: (1) Federal Reserve rate cuts of "
            "100 basis points in 2025 which reduced deposit spread income; (2) competitive pressure on "
            "deposit pricing as banks compete for sticky deposits; (3) loan growth partially offsetting "
            "rate headwinds. Investment banking fees were $2.7 billion, up 22% year-over-year driven by "
            "M&A advisory (Capital One/Discover, Synopsys/ANSYS) and IPO underwriting rebound. "
            "Markets revenue (trading) was $9.1 billion, up 12%, with FICC at $6.0B and Equities at $3.1B. "
            "Asset & Wealth Management revenue: $5.6B (+9% YoY). Consumer & Community Banking: $18.1B. "
            "CET1 capital ratio: 15.4%, well above the 12.3% regulatory requirement."
        ),
        "query_classes": ["factual_lookup", "financial_data"],
    },
    {
        "key": "jpm_cre_exposure_10q",
        "source_type": "sec_10q",
        "source_name": "sec_edgar",
        "published_at": "2026-05-05T16:00:00Z",
        "title": "JPMorgan Chase Q1 2026 10-Q — Commercial Real Estate Exposure Disclosure",
        "text": (
            "JPMorgan Chase's Q1 2026 Form 10-Q discloses commercial real estate (CRE) loan exposure of "
            "$173.4 billion, representing 8.6% of total loans and advances. Of total CRE exposure, "
            "approximately $42.3 billion is classified as office properties — the category most affected "
            "by the post-COVID hybrid work trend. JPMorgan has disclosed that approximately 12% of its "
            "office CRE loans are on non-accrual status or classified as criticized, representing "
            "approximately $5.1 billion in potential stress. The bank has taken $1.2 billion in CRE-specific "
            "provisions in the trailing twelve months, the majority related to office properties. "
            "CEO Jamie Dimon noted on the Q1 earnings call: 'We have been conservative in marking our CRE "
            "office book; we believe current allowances adequately cover expected losses.' "
            "Total allowance for credit losses on CRE loans: $3.4 billion (2.0% of CRE loan balance). "
            "Geographic concentration: NY Metro 23%, LA/California 18%, Chicago 11%, other 48%."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "jpm_roe_trend_5yr",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-15T10:00:00Z",
        "title": "JPMorgan Chase Return on Equity: 5-Year Trend 2021-2025",
        "text": (
            "JPMorgan Chase return on equity (ROE) trend over five fiscal years: "
            "FY2021: ROE 19%, ROTCE 23%. FY2022: ROE 14%, ROTCE 17% (elevated provisions for Ukraine/Russia). "
            "FY2023: ROE 17%, ROTCE 21% (recovery + First Republic acquisition benefit). "
            "FY2024: ROE 20%, ROTCE 24% (record year — high rates, low credit losses). "
            "FY2025: ROE 18%, ROTCE 21% (rate cuts began reducing NII). "
            "Five-year average ROE: 17.6%, ROTCE: 21.2%. "
            "For comparison: Bank of America 5yr average ROE 11.2%, Citigroup 5yr average ROE 7.1%. "
            "JPMorgan's consistently superior ROE reflects its diversified revenue model (investment banking, "
            "markets, wealth management, consumer banking), superior risk management, and Jamie Dimon's "
            "25+ year track record of capital allocation discipline. JPMorgan targets a through-the-cycle "
            "ROTCE of 17%, which it has exceeded in 4 of the past 5 years."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "jpm_cet1_ratio_q1_2026",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-12T10:00:00Z",
        "title": "JPMorgan CET1 Capital Ratio Q1 2026: 15.4% vs BofA and Citi",
        "text": (
            "JPMorgan Chase CET1 capital ratio: 15.4% as of March 31, 2026. "
            "Bank of America CET1: 11.8% as of March 31, 2026. "
            "Citigroup CET1: 13.4% as of March 31, 2026. "
            "JPMorgan's 15.4% CET1 is approximately 310 basis points above its own regulatory requirement "
            "of 12.3% (includes G-SIB surcharge and stress buffer), providing a substantial capital buffer. "
            "The 15.4% ratio puts JPMorgan in a comfortable position for: continued buybacks and dividend "
            "growth; potential acquisitions; regulatory stress scenarios including severe economic downturns. "
            "JPMorgan's CET1 has consistently been higher than large bank peers, reflecting Dimon's "
            "'fortress balance sheet' philosophy. JPMorgan has the highest absolute CET1 ratio among the "
            "four major US banks (JPM, BAC, C, WFC) that together comprise the core of US large-cap banking."
        ),
        "query_classes": ["financial_data", "comparison"],
    },
    {
        "key": "jpm_vs_bac_citi_cet1",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-30T10:00:00Z",
        "title": "US Bank CET1 Capital Ratios Comparison: JPM vs BofA vs Citi Q1 2026",
        "text": (
            "CET1 capital ratio comparison for major US banks as of Q1 2026 (March 31, 2026): "
            "JPMorgan Chase (JPM): CET1 15.4%, required minimum 12.3%, buffer 310bps. "
            "Bank of America (BAC): CET1 11.8%, required minimum 10.0%, buffer 180bps. "
            "Citigroup (C): CET1 13.4%, required minimum 11.3%, buffer 210bps. "
            "Wells Fargo (WFC): CET1 11.1%, required minimum 9.8%, buffer 130bps. "
            "Goldman Sachs (GS): CET1 14.6%, required minimum 13.2%, buffer 140bps. "
            "Morgan Stanley (MS): CET1 15.8%, required minimum 14.0%, buffer 180bps. "
            "JPMorgan's 15.4% CET1 is the highest among the major banks excluding MS, and well above "
            "BofA's 11.8% (+360bps advantage) and Citi's 13.4% (+200bps). The higher CET1 buffers "
            "at JPMorgan provide greater flexibility for capital deployment vs. peers."
        ),
        "query_classes": ["comparison", "financial_data"],
    },
    {
        "key": "jpm_net_interest_margin",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-11T13:00:00Z",
        "title": "JPMorgan Q1 2026 — Net Interest Margin and Rate Sensitivity Discussion",
        "text": (
            "JEREMY BARNUM: Net interest income in Q1 2026 was $24.1 billion, down 3% from $24.8 billion "
            "in Q1 2025. Full-year 2026 NII guidance: approximately $93 billion (ex-Markets), down from "
            "$94.5 billion in 2025, reflecting 100 basis points of Fed rate cuts in 2025 now fully flowing "
            "through our deposit repricing. JPMorgan has estimated that each 25 basis point Fed rate cut "
            "reduces annualized NII by approximately $900 million in the short term. "
            "Deposit betas have increased faster than expected — consumer savings rates rose from near-zero "
            "in 2022 to approximately 2.5% now, narrowing deposit spreads. However, loan growth of 4% "
            "year-over-year has partially offset rate headwinds. Commercial loan demand remained resilient "
            "with C&I loans up 5% year-over-year. Mortgage originations were $27 billion in Q1, up 15% "
            "from Q1 2025, as rate cuts improved affordability. The bank is asset-sensitive for the next "
            "12 months — further rate cuts would reduce NII."
        ),
        "query_classes": ["reasoning", "factual_lookup"],
    },
    {
        "key": "jpm_macro_rate_impact",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-03-20T09:00:00Z",
        "title": "Fed Rate Cuts Are Weighing on Bank Net Interest Margins in 2026",
        "text": (
            "US commercial banks are navigating a challenging net interest margin (NIM) environment in 2026 "
            "as the Federal Reserve's 100 basis points of rate cuts in 2025 flow through loan and deposit "
            "pricing. Major bank NIMs for Q1 2026: JPMorgan 2.75% (down from 2.85% in Q1 2025), "
            "Bank of America 2.10% (down from 2.19%), Wells Fargo 2.80% (down from 2.86%). "
            "The NIM pressure reflects: (1) floating rate loan yields declining with SOFR from 5.3% to 4.3%; "
            "(2) deposit costs declining more slowly as banks compete for sticky deposits; "
            "(3) fixed-rate mortgage portfolios offering no relief as new originations price at current rates. "
            "The macro factor most weighing on bank NIMs in 2026 is the inverted yield curve — the 2yr/10yr "
            "spread remains near zero, making traditional maturity transformation (borrow short, lend long) "
            "less profitable. Banks that locked in long-duration bonds at low rates in 2020-2021 are seeing "
            "unrealized loss amortization pressure on book value."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "jpm_portfolio_holding",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio: JPMorgan Chase (JPM) is not currently held",
        "text": (
            "JPMorgan Chase & Co. (JPM) is not currently a position in the demo portfolio. "
            "However, the portfolio has indirect exposure to JPM through financial sector ETF holdings. "
            "Key JPM metrics for monitoring: CET1 ratio 15.4% (strong), dividend $1.40/quarter ($5.60 annual), "
            "yield ~2.0% at current price $278.50, forward P/E 12.3x, ROTCE 21% (Q1 2026 annualized). "
            "JPM is a Financials sector benchmark stock: S&P 500 Financials weight ~13.1%, JPM weight ~2.8%. "
            "Earnings schedule: Q2 2026 expected July 11, 2026. "
            "Ex-dividend date: April 5, 2026 (next: July 5, 2026). "
            "ISIN: US46625H1005. Sector: Financials. Industry: Diversified Banks."
        ),
        "query_classes": ["portfolio", "identifier_lookup"],
    },
    {
        "key": "jpm_roe_trend_detail",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-15T10:00:00Z",
        "title": "JPMorgan Chase ROE Detail: Annual Trend with Component Analysis",
        "text": (
            "JPMorgan Chase return on equity detail with driver analysis: "
            "FY2021: Average equity $266B, net income $48.3B, ROE 18.2%, ROTCE 23.0%. "
            "FY2022: Average equity $286B, net income $37.7B, ROE 13.2%, ROTCE 16.5% (macro provisions). "
            "FY2023: Average equity $306B, net income $49.6B, ROE 16.2%, ROTCE 20.5% (First Republic accretion). "
            "FY2024: Average equity $327B, net income $58.5B, ROE 17.9%, ROTCE 22.0% (record high rates). "
            "FY2025: Average equity $352B, net income $57.4B, ROE 16.3%, ROTCE 19.7% (rate cuts reduce NII). "
            "The five-year trajectory shows JPMorgan's ROE improving from 18.2% to 16.3% with a peak in 2024. "
            "Net income declined slightly in FY2025 due to NII headwinds from rate cuts. Investment banking "
            "and markets revenues partially offset the NII decline. JPMorgan expects mid-high teens ROTCE "
            "as the sustainable through-the-cycle target."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "jpm_bac_citi_cet1_detail",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-30T10:00:00Z",
        "title": "Bank CET1 Capital Stack Comparison Q1 2026: Full Detail",
        "text": (
            "Comprehensive CET1 capital ratio comparison for US major banks Q1 2026: "
            "JPMorgan Chase: CET1 15.4% (reported), Standardized CET1 15.4%, Advanced CET1 15.8%. "
            "Required minimum (JPM): 4.5% minimum + 2.5% conservation buffer + 3.5% G-SIB + 1.8% stress = 12.3%. "
            "Buffer above minimum: 310bps. JPM available buyback capacity at minimum: ~$35B. "
            "Bank of America: CET1 11.8% reported. Required minimum 10.0%. Buffer 180bps. BAC ~$20B capacity. "
            "Citigroup: CET1 13.4%. Required minimum 11.3%. Buffer 210bps. C ~$15B capacity. "
            "Wells Fargo: CET1 11.1%. Required minimum 9.8%. Buffer 130bps (note: WFC has asset cap). "
            "JPMorgan's CET1 superiority is driven by: lower risk-weighted assets per dollar of loans; "
            "more profitable business mix; and historically superior loss absorption in downturns. "
            "Post-Basel III Endgame (B3E) finalization, most banks will need to hold higher capital, "
            "reducing the gap between JPM and peers."
        ),
        "query_classes": ["comparison", "financial_data"],
    },
    {
        "key": "jpm_investment_bank_revenue",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-11T13:00:00Z",
        "title": "JPMorgan Q1 2026 — Investment Banking and Markets Revenue",
        "text": (
            "DANIEL PINTO: The Corporate & Investment Bank delivered revenue of $19.7 billion in Q1 2026, "
            "up 14% year-over-year — the best Q1 CIB result in the bank's history. "
            "Investment Banking fees: $2.7 billion, up 22% YoY. M&A advisory: $1.1 billion. "
            "Equity underwriting: $0.8 billion. Debt underwriting: $0.8 billion. "
            "Markets revenue: $9.1 billion, up 12% YoY. FICC: $6.0 billion (+8%). Equities: $3.1 billion (+22%). "
            "The equity markets outperformance reflects Prime Brokerage strength and Cash Equities market share gains. "
            "Securities Services: $1.2B (+5% YoY). Commercial Banking: $4.1B (+8% YoY). "
            "The investment banking activity is driven by: (1) Rebounding M&A dealmaking as PE firms "
            "accelerate portfolio company exits; (2) Strong investment-grade bond issuance as companies "
            "refinance; (3) IPO pipeline rebuilding after two subdued years. JPMorgan #1 in global investment "
            "banking fee league tables YTD 2026 with 8.9% market share."
        ),
        "query_classes": ["factual_lookup"],
    },
    # ── Netflix ────────────────────────────────────────────────────────────
    {
        "key": "nflx_subscriber_growth_q1_2026",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-17T21:00:00Z",
        "title": "Netflix Q1 2026 Earnings Call — Subscriber Growth and Engagement",
        "text": (
            "TED SARANDOS: Netflix added 8.9 million net new subscribers in Q1 2026, bringing total paid "
            "memberships to 318 million globally. This was above management guidance of 7-8 million net adds. "
            "Ad-supported tier memberships reached 55 million globally, up from 40 million in Q4 2025. "
            "The ad tier now represents approximately 17% of total paid memberships. "
            "Total viewing hours per day: 700 million hours, up 12% year-over-year. "
            "Engagement is the strongest leading indicator of retention — members who watch 5+ hours per week "
            "have churn rates approximately 60% below the overall average. "
            "Password sharing crackdown has been fully lapped and we are now in the normalized phase. "
            "Key content Q1 2026: Stranger Things Season 5 (global hit, 200M+ viewing hours week 1), "
            "Wednesday Season 3 (140M+ hours), two feature films exceeding 100M hours. "
            "GREG PETERS: We are growing engagement, subscribers, and revenue simultaneously — "
            "the trifecta that demonstrates the durability of the Netflix business model."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "nflx_churn_rate_q1_2026",
        "source_type": "sec_10q",
        "source_name": "sec_edgar",
        "published_at": "2026-04-18T16:00:00Z",
        "title": "Netflix Q1 2026 10-Q — Subscriber Churn Rate and Retention Metrics",
        "text": (
            "Netflix Inc. does not directly disclose monthly churn rates in its 10-Q or earnings materials, "
            "consistent with its longstanding policy of not providing this metric. However, management "
            "commentary and analyst calculations provide estimates. In Q1 2026, Netflix reported 8.9 million "
            "net subscriber additions from a base of 309 million starting members. "
            "Third-party analyst estimates (based on panel data) suggest Netflix monthly churn was "
            "approximately 2.0-2.3% in Q1 2026, implying approximately 18-21 million gross cancellations "
            "offset by approximately 27-30 million gross additions per quarter. "
            "This churn level compares favorably to: Disney+ at approximately 4.5% monthly churn, "
            "Max (HBO+) at approximately 3.8%, Peacock at approximately 5.1%, Paramount+ at approximately 4.2%. "
            "Netflix's lower churn rate reflects superior content library breadth, global reach, and "
            "localized content investments. The ad-supported tier has higher churn than the premium ad-free tier "
            "but contributes higher advertising revenue per member than subscription revenue forgone."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "nflx_vs_disney_streaming_margin",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "Netflix vs Disney+ Streaming Operating Margin Comparison — 4 Quarters",
        "text": (
            "Streaming operating margin comparison — Netflix vs Disney+ — trailing four quarters: "
            "Q2 2025: Netflix streaming op margin 26.6%, Disney+ segment op margin 6.2%. "
            "Q3 2025: Netflix 29.4%, Disney+ 8.1%. "
            "Q4 2025: Netflix 22.4% (seasonal content spend), Disney+ 9.4%. "
            "Q1 2026: Netflix 28.1%, Disney+ 10.2%. "
            "Netflix four-quarter average: 26.6%. Disney+ four-quarter average: 8.5%. "
            "Netflix's operating margin advantage of ~18 percentage points reflects: (1) Netflix's single "
            "streaming-only business model vs Disney's cost-sharing complexity; (2) Netflix's global content "
            "amortization over 318M subscribers vs Disney+'s smaller base; (3) Netflix's ad tier reaching "
            "scale. Disney's streaming margin has improved significantly from negative territory in 2023-2024 "
            "as Bob Iger's cost-cutting initiative reduced content spend by ~$3B annually. "
            "Netflix 2026 operating income guidance implies full-year operating margin of approximately 29%."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "nflx_operating_margin_q1_2026",
        "source_type": "sec_10q",
        "source_name": "sec_edgar",
        "published_at": "2026-04-18T16:00:00Z",
        "title": "Netflix Q1 2026 10-Q — Operating Income and Margin",
        "text": (
            "Netflix Inc. Q1 2026 financials: Revenue $11.5 billion (+15% YoY). Operating income $3.2 billion "
            "(+22% YoY). Operating margin 28.1%, up from 26.4% in Q1 2025. Net income $2.9 billion. "
            "EPS (diluted) $6.82. Full-year 2026 operating income guidance: $9.1 billion on revenue of "
            "approximately $44 billion, implying full-year operating margin of approximately 20.7% on a "
            "GAAP basis (management guides to 29% margin on their adjusted basis which excludes content "
            "amortization timing). Free cash flow for Q1 2026: $2.7 billion. "
            "Content amortization: $4.2 billion in Q1 2026. Cash content spend: $5.0 billion. "
            "The quarterly FCF generation of $2.7 billion, combined with the company's improving margin "
            "profile, supports Netflix's transition from a content-investment-heavy growth company to "
            "a profitable, cash-generative media business."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "nflx_earnings_summary",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-04-18T09:00:00Z",
        "title": "Netflix Q1 2026 Beat: 8.9M Adds, $11.5B Revenue, $6.82 EPS",
        "text": (
            "Netflix Inc. (NFLX) reported Q1 2026 earnings that beat analyst consensus on all major metrics. "
            "Paid net subscriber additions: 8.9M vs consensus 7.4M (+1.5M beat). "
            "Revenue: $11.5B vs consensus $11.2B (+$300M beat). EPS: $6.82 vs consensus $6.30 (+$0.52 beat). "
            "Operating margin: 28.1% vs consensus 26.8%. The subscriber beat was driven by strong Q1 content "
            "including Stranger Things S5 and Wednesday S3. Ad tier subscribers: 55M (analyst est. 50M). "
            "Stock rose 3.8% in after-hours following results. Q2 2026 guidance: net subscriber adds 8-9M, "
            "revenue $11.9-12.0B, operating income $3.3B (op margin ~27.8%). For the full year 2026, "
            "Netflix guided operating margin of approximately 29% on an adjusted basis. "
            "Netflix has beaten subscriber estimates in 5 of the last 6 quarters."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "nflx_churn_detail",
        "source_type": "sec_10q",
        "source_name": "sec_edgar",
        "published_at": "2026-04-18T16:00:00Z",
        "title": "Netflix Subscriber Churn Methodology and Disclosed Metrics",
        "text": (
            "Netflix's most recent 10-Q notes that the company reports paid memberships on a net basis "
            "at quarter-end and does not separately disclose gross subscriber additions or churn rates. "
            "Management has historically indicated that monthly churn is 'well below' 3%, consistent with "
            "external estimates of approximately 2.0-2.3% in recent quarters. "
            "Starting Q1 2025, Netflix shifted to reporting ARM (Average Revenue per Membership) rather than "
            "ARM by region, as the company deprioritized regional breakdown disclosure. "
            "Q1 2026 ARM (global): $17.39, up 6% year-over-year from $16.41 in Q1 2025. "
            "ARM improvement driven by: price increases in select markets (UK, France, Brazil), "
            "higher ad-supported mix (lower ARM per subscriber but incremental revenue through ads), "
            "and market mix shift as higher-ARPU US/Europe represents a growing share of adds. "
            "The company ended Q1 2026 with 318M paid members. Q2 2026 guidance: net adds 8-9M."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "nflx_disney_margin_detail",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-06T10:00:00Z",
        "title": "Netflix vs Disney Streaming Margin Detail by Quarter",
        "text": (
            "Detailed streaming margin comparison — Netflix (global streaming segment) vs Disney+ (DTC segment): "
            "Q2 2025: Netflix revenue $9.8B, op income $2.6B, margin 26.6%. Disney+ DTC revenue $5.8B, op income $361M, margin 6.2%. "
            "Q3 2025: Netflix revenue $10.2B, op income $3.0B, margin 29.4%. Disney+ DTC revenue $5.9B, op income $477M, margin 8.1%. "
            "Q4 2025: Netflix revenue $10.3B, op income $2.3B, margin 22.4%. Disney+ DTC revenue $6.3B, op income $593M, margin 9.4%. "
            "Q1 2026: Netflix revenue $11.5B, op income $3.2B, margin 28.1%. Disney+ DTC revenue $6.0B, op income $610M, margin 10.2%. "
            "Netflix 4Q average margin: 26.6%. Disney+ 4Q average: 8.5%. Gap: ~18 percentage points. "
            "Disney's margin improvement from 6% to 10% over four quarters reflects Iger's content cost reduction. "
            "Netflix margins are impacted by content investment timing — Q4 is always the lowest margin quarter "
            "due to holiday content slate releases. Longer-term, Netflix targets operating margin of 30%+ by 2027."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "nflx_ad_tier_subscribers",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-17T21:00:00Z",
        "title": "Netflix Q1 2026 — Ad-Supported Tier Subscriber and Revenue Growth",
        "text": (
            "GREG PETERS: Our advertising business is building real momentum. Ad-supported memberships "
            "reached 55 million globally in Q1 2026, up from 40 million in Q4 2025 and 23 million a year ago. "
            "Ad-supported now represents 17% of total paid memberships. Ad revenue in Q1 2026 was approximately "
            "$1.2 billion, growing 100% year-over-year. For the full year 2026, we expect ad revenue to reach "
            "approximately $5 billion — still a small portion of our $44 billion total revenue, but growing "
            "rapidly. Sell-through rates for our ad inventory have improved significantly as we expand our "
            "programmatic trading capabilities and deepen relationships with major advertisers. "
            "CPMs on the Netflix platform are premium — typically $50-65 CPM in the US — reflecting the "
            "quality and attentiveness of Netflix viewing versus social media scroll environments. "
            "We partnered with The Trade Desk and Google as our programmatic ad technology partners in 2026. "
            "With 55M ad-supported subscribers, Netflix now has more ad-tier subscribers than Peacock and Max combined."
        ),
        "query_classes": ["factual_lookup"],
    },
    # ── Google/Alphabet ────────────────────────────────────────────────────
    {
        "key": "goog_cloud_growth_q1_2026",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-29T21:00:00Z",
        "title": "Alphabet Q1 2026 Earnings — Google Cloud Growth and AI Momentum",
        "text": (
            "SUNDAR PICHAI: Google Cloud had an outstanding quarter. Cloud revenue was $12.3 billion, "
            "up 28% year-over-year — our fastest growth in six quarters. Google Cloud operating income was "
            "$2.2 billion, an operating margin of 17.9%, and our sixth consecutive profitable quarter. "
            "Vertex AI has become one of the most important Google Cloud products — customer count grew "
            "3x year-over-year and Vertex AI revenue grew over 200%. BigQuery is processing more data "
            "than ever, growing 25% year-over-year. We are seeing strong enterprise migration to "
            "Google Cloud driven by: (1) Gemini 2.0 Pro performance in coding and reasoning tasks; "
            "(2) Google Workspace AI features driving commercial expansion; (3) Data Cloud capability "
            "with the deepest analytics stack. ANAT ASHKENAZI (CFO): Cloud revenue guidance for Q2 2026 "
            "is $12.8-13.2 billion, implying 26-30% growth. Full-year 2026 Cloud revenue expected to "
            "exceed $50 billion, which would make Google Cloud a $50B business within 8 years of launch."
        ),
        "query_classes": ["factual_lookup", "comparison"],
    },
    {
        "key": "goog_earnings_surprise_q2_2026",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-01T22:00:00Z",
        "title": "Alphabet Q1 2026 Beats by $2.1B: Google Search + Cloud Both Accelerate",
        "text": (
            "Alphabet Inc. (GOOG/GOOGL) reported Q1 2026 revenue of $90.2 billion versus analyst consensus "
            "of $88.1 billion — a beat of $2.1 billion or 2.4%. EPS was $2.81 versus consensus $2.65, "
            "a $0.16 beat (6.0%). Shares rose 5.1% in after-hours trading. "
            "Search revenue: $54.0B (+13% YoY), beating estimates of $52.8B by $1.2B. AI Overviews "
            "in Search has not cannibalized ad revenue as feared — the feature may actually increase "
            "query volume. YouTube revenue: $9.8B (+14% YoY). Network: $7.3B (-1%). Cloud: $12.3B (+28%). "
            "Comparing to Apple's same-evening Q2 results: Apple beat by $2.1 billion in absolute dollars "
            "(same as Alphabet) but Apple's beat was 2.2% vs Alphabet's 2.4% — making Alphabet's "
            "percentage beat marginally larger. Apple stock also rose (~3.4% after-hours) on its beat. "
            "Both companies benefited from strong AI-related demand in their respective businesses."
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    {
        "key": "goog_headcount_2024_announcement",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2024-01-22T16:00:00Z",
        "title": "Alphabet Form 8-K: 2024 Workforce Reduction — 12,000 Jobs Cut",
        "text": (
            "MOUNTAIN VIEW, California — January 22, 2024 — Alphabet Inc. CEO Sundar Pichai announced "
            "in an employee message (filed as Exhibit 99.1 to Form 8-K) that the company will reduce its "
            "global workforce by approximately 12,000 roles — about 6% of total headcount. "
            "'This will mean saying goodbye to some incredibly talented people we worked hard to hire and "
            "have loved working with. I'm deeply sorry for that,' Pichai wrote. "
            "The reductions will span Alphabet's product areas, functions, levels, and geographies. "
            "Alphabet expects to incur charges of approximately $1.9-2.3 billion in Q1 2024 related to "
            "employee severance and related charges. The layoffs follow a period of rapid hiring during "
            "the pandemic that saw Alphabet's headcount grow from 135,000 in 2019 to 190,000 by end of 2022. "
            "The cuts are part of a broader tech industry recalibration in 2023-2024 that saw Microsoft, "
            "Meta, Amazon, and others also reduce headcount by 5-15%. Alphabet also sold its Boston "
            "Dynamics subsidiary to Hyundai as part of portfolio optimization in 2024."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "goog_capex_hyperscaler",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-30T09:00:00Z",
        "title": "Alphabet Q1 2026 Capex: $17.2B on AI Infrastructure — Full-Year Guidance $72B",
        "text": (
            "Alphabet reported Q1 2026 capital expenditures of $17.2 billion, up 44% year-over-year from "
            "$11.9 billion in Q1 2025. Management guided full-year 2026 capex of approximately $72 billion, "
            "up from $52.5 billion in 2025. On a trailing twelve-month basis through Q1 2026, Alphabet capex "
            "was $58.1 billion — behind Microsoft ($82.3B) and Amazon ($79.6B) but ahead of Meta ($48.6B). "
            "Alphabet's capex growth rate of 41% year-over-year is below Microsoft (+63%) and Amazon (+53%) "
            "but above Meta (+37%). The capex is concentrated in AI data centers (Google's custom TPU v5 "
            "and NVIDIA GPU clusters), fiber network expansion, and new data center campuses. "
            "Alphabet has committed to major AI infrastructure investments in the US, UK, Finland, Belgium, "
            "and Singapore. CFO Anat Ashkenazi: 'We are investing aggressively to capture the AI opportunity. "
            "Every dollar of cloud infrastructure we build is generating meaningful revenue in a very short timeframe.'"
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    {
        "key": "goog_vs_azure_cloud",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "Google Cloud vs Azure — Growth Rate Comparison Four Quarters",
        "text": (
            "Google Cloud vs Microsoft Azure growth rate comparison, four most recent quarters: "
            "Q2 2025: Google Cloud +26%, Azure +26% constant currency (tied). "
            "Q3 2025: Google Cloud +30%, Azure +28% (GCP ahead). "
            "Q4 2025: Google Cloud +30%, Azure +26% (GCP ahead). "
            "Q1 2026: Google Cloud +28%, Azure +33% (Azure re-accelerated). "
            "Four-quarter average: Google Cloud +28.5%, Azure +28.3% (essentially tied). "
            "Google Cloud absolute revenue: Q1 2026 $12.3B. Azure estimated $25.2B (not disclosed separately). "
            "Google Cloud's operating margin improvement from near-breakeven in 2023 to 17.9% in Q1 2026 "
            "demonstrates the business is reaching profitability inflection. Azure's margin is embedded in "
            "Intelligent Cloud segment (47%), making direct comparison difficult. "
            "Both platforms are growing faster than AWS (17% in Q1 2026) partly due to smaller bases and "
            "stronger AI service portfolios."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "goog_cost_cutting_2024_8k",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2024-01-22T16:00:00Z",
        "title": "Alphabet 8-K: Sundar Pichai's Full Letter on 2024 Headcount Reduction",
        "text": (
            "Sundar Pichai's full message to Googlers (January 20, 2024, filed via 8-K January 22): "
            "'Over the past two years we've seen periods of dramatic growth. To match and fuel that growth, "
            "we hired for a different economic reality than the one we face today. To fully capture the "
            "tremendous AI opportunity ahead, we need to make tough choices. So we are reducing our workforce "
            "by approximately 12,000 roles.' The letter noted that affected employees in the US would be "
            "notified immediately via email, and would receive severance of 16 weeks minimum plus 2 weeks "
            "per year of tenure, a minimum of $175,000 in severance for many. The decision was approved "
            "by Alphabet's Board of Directors. In Q4 2023, Alphabet also announced the consolidation of "
            "Google Research and Google Brain into Google DeepMind — the unified AI research organization. "
            "This represented a major strategic reorganization to sharpen Alphabet's AI focus. "
            "The restructuring charges of $1.9-2.3 billion were expected to be taken in Q1 2024. "
            "Alphabet also noted separate hardware product area reductions in Pixel and Nest."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "goog_search_revenue_q1",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-29T21:00:00Z",
        "title": "Alphabet Q1 2026 — Google Search and YouTube Revenue",
        "text": (
            "ANAT ASHKENAZI: Google Search and other advertising revenue was $54.0 billion in Q1 2026, "
            "up 13% year-over-year. Search growth continues to demonstrate resilience despite rising "
            "competition from AI chat interfaces. AI Overviews (formerly SGE) is now shown in over 2 billion "
            "queries weekly, and we are seeing no material negative impact on monetization — click-through "
            "rates on ads adjacent to AI Overviews are comparable to traditional results. "
            "Google Shopping and Performance Max campaigns grew faster than core Search. "
            "YouTube advertising revenue was $9.8 billion, up 14% year-over-year. YouTube Shorts monetization "
            "is improving, with Shorts CPMs approaching 70% of long-form video CPMs. YouTube TV and Premium "
            "subscription revenue contributed $2.1 billion in Q1. Total Google Services revenue: $77.3B (+11%). "
            "Google Network revenue (third-party web): $7.3 billion (-1%), reflecting continued traffic "
            "migration from open web to walled garden platforms."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "goog_youtube_revenue_q1",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-29T21:00:00Z",
        "title": "Alphabet Q1 2026 — YouTube and Subscription Revenue Detail",
        "text": (
            "SUNDAR PICHAI: YouTube remains one of the most powerful media platforms in the world. "
            "YouTube now reaches over 2 billion signed-in users monthly and is the most-watched streaming "
            "platform on TV screens in the US for the third consecutive year. Shorts is watched by over "
            "70 billion daily views. YouTube Music and Premium combined have over 100 million subscribers. "
            "For Q1 2026, YouTube advertising was $9.8 billion (+14% YoY). YouTube Shorts CPMs have "
            "improved 25% year-over-year as advertiser adoption grows. "
            "Connected TV (CTV) ad spend on YouTube grew 22% year-over-year, outpacing overall YouTube growth, "
            "as advertisers shift budgets from linear TV to digital. "
            "YouTube TV (live TV streaming service) has approximately 8 million subscribers paying $72.99/month, "
            "contributing to non-advertising revenue growth. Total subscription, platform, and devices revenue "
            "(which includes YouTube subscriptions and Google One cloud storage) was $11.0 billion (+9% YoY)."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "goog_alphabet_cloud_q1_2026",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-29T21:00:00Z",
        "title": "Alphabet Q1 2026 — Google Cloud Competitive Positioning vs Azure and AWS",
        "text": (
            "SUNDAR PICHAI: Google Cloud's 28% growth reflects our strengthening competitive position. "
            "We are winning workloads in data analytics, AI/ML, and enterprise productivity where our "
            "differentiated technologies — BigQuery, Vertex AI, and Duet AI in Workspace — provide "
            "measurable advantages. Key customer wins in Q1: Ford (full enterprise cloud migration), "
            "Lufthansa (Workspace + Cloud migration), Sony (gaming AI workloads on Vertex AI). "
            "ANAT ASHKENAZI: Google Cloud operating margin was 17.9% in Q1, up from 9.4% in Q1 2025. "
            "This improvement reflects: (1) operating leverage as revenue scales; (2) higher-margin AI "
            "services growing faster than infrastructure baseline; (3) improved data center efficiency. "
            "We now expect Google Cloud to be a meaningful profit contributor in 2026. "
            "For the full year 2026, we expect Google Cloud revenue to exceed $50 billion and maintain "
            "positive operating income throughout the year. Google Cloud is growing faster than AWS "
            "and is narrowing the absolute revenue gap to Azure."
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    # ── AMD ────────────────────────────────────────────────────────────────
    {
        "key": "amd_forward_guidance_q2_2026",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-29T21:00:00Z",
        "title": "AMD Q1 2026 Earnings Call — Q2 2026 Revenue Guidance",
        "text": (
            "JEAN HU (CFO): For Q2 2026, we expect revenue of approximately $7.7 billion, plus or minus "
            "$300 million. This represents approximately 30% year-over-year growth at the midpoint. "
            "By segment: Data Center revenue expected at approximately $4.0 billion, up 40%+ YoY driven "
            "by MI300X and MI350X GPU shipments. Client (PC processors) expected at $2.2 billion, up 22%. "
            "Gaming expected at $0.7 billion, flat YoY. Embedded at $0.8 billion, up 15% (recovery continuing). "
            "Non-GAAP gross margin guidance: approximately 54.0%, up from 53.0% in Q1 2026 as Data Center "
            "mix increases. Non-GAAP EPS guidance: approximately $0.96, up from $0.82 in Q1 2026. "
            "LISA SU: We expect the MI300X ramp at Microsoft, Meta, and Oracle to be the primary Q2 growth "
            "driver. AMD's Data Center GPU revenue run rate has reached approximately $12 billion annualized, "
            "demonstrating that AMD is establishing a real second-source position in AI accelerators alongside NVIDIA."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "amd_gross_margin_q1_2026",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-30T10:00:00Z",
        "title": "AMD Q1 2026 Gross Margin: 53.0% Non-GAAP — Data Center Mix Driving Expansion",
        "text": (
            "Advanced Micro Devices (AMD) reported Q1 2026 non-GAAP gross margin of 53.0%, up from 51.3% "
            "in Q4 2025 and 52.0% in Q1 2025. GAAP gross margin was 49.7%, reflecting stock-based "
            "compensation and acquisition amortization. Revenue was $7.4 billion (+36% YoY). "
            "Data Center segment revenue was $3.7 billion (+57% YoY) at an estimated gross margin of ~60%, "
            "the highest-margin segment and the primary driver of blended gross margin expansion. "
            "Client (PC) revenue: $2.3 billion (+28% YoY) at approximately 52% GM. "
            "Gaming: $0.7 billion (-26% YoY) — PS5/Xbox semi-custom revenue declining as console cycle matures. "
            "Embedded: $0.7 billion (+50% YoY) — recovery from inventory digestion cycle. "
            "AMD's gross margin trajectory (2023: 50.0%, 2024: 51.5%, 2025: 51.3%, Q1 2026: 53.0%) "
            "reflects the structural shift toward higher-margin Data Center GPU revenue."
        ),
        "query_classes": ["financial_data", "comparison"],
    },
    {
        "key": "amd_vs_nvda_gross_margin",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T10:00:00Z",
        "title": "AMD vs NVIDIA Gross Margin Gap: AI Premium Explains 22pp Difference",
        "text": (
            "Gross margin comparison — AMD Advanced Micro Devices vs NVIDIA Corporation — last two quarters: "
            "AMD Q4 2025: Non-GAAP 51.3%, GAAP 48.3%. NVIDIA Q4 FY2026 (Jan 2026): Non-GAAP 73.5%, GAAP 73.0%. "
            "AMD Q1 2026: Non-GAAP 53.0%, GAAP 49.7%. NVIDIA Q1 FY2027 (Apr 2026): estimated ~74%, GAAP ~73%. "
            "NVIDIA's gross margin advantage of approximately 21-22 percentage points on non-GAAP basis "
            "reflects: (1) NVIDIA's monopoly-like AI GPU pricing — H100/Blackwell sold at $30,000-100,000 "
            "per unit with no competitive alternatives; (2) AMD's MI300X priced at a discount to H100 "
            "to win market share; (3) AMD has higher COGS from manufacturing complexity. "
            "Both companies source chips from TSMC but NVIDIA uses more advanced packaging (CoWoS-S/L) "
            "that costs more but enables the NVLink bandwidth that justifies higher ASPs. "
            "If NVIDIA's gross margin were to converge toward AMD's 53%, NVIDIA EPS would fall by ~45%. "
            "Conversely, if AMD achieved NVIDIA-like margins, AMD EPS would approximately double."
        ),
        "query_classes": ["comparison", "financial_data"],
    },
    {
        "key": "amd_processor_guidance_transcript",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-29T21:00:00Z",
        "title": "AMD Q1 2026 Earnings Call — CPU Roadmap and Client Segment Guidance",
        "text": (
            "LISA SU: Our Zen 5 architecture is performing exceptionally in both the client and server markets. "
            "Ryzen 9000 series (Zen 5) desktop CPUs continue to gain market share from Intel's 13th/14th "
            "generation Core platform. In the server market, EPYC Turin (Zen 5 based) is seeing strong "
            "adoption at major hyperscalers and OEMs. JEAN HU: Client revenue in Q2 2026 is guided at "
            "approximately $2.2 billion, reflecting continued Ryzen 9000 momentum and seasonal recovery "
            "in PC market demand. PC TAM for 2026 is expected to be approximately 270 million units, flat "
            "to slightly up from 2025 as AI PC adoption drives ASP uplift. AMD's notebook CPU market share "
            "has grown to approximately 22% in Q1 2026 from 18% a year ago, driven by Ryzen AI 300 series "
            "adoption in premium notebooks. For Q3 2026, AMD guides client revenue of $2.3-2.5 billion. "
            "Full-year 2026 client revenue guidance: approximately $8.5-9.0 billion."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "amd_semis_underperformance",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-20T09:00:00Z",
        "title": "Why Semiconductor Equipment Stocks Have Underperformed the Broad Semis Index in 2026",
        "text": (
            "Semiconductor equipment stocks — including Lam Research (LRCX), Applied Materials (AMAT), "
            "and KLA Corporation (KLAC) — have underperformed the Philadelphia Semiconductor Index (SOX) "
            "by approximately 12-18 percentage points year-to-date through April 2026. Three factors explain "
            "the underperformance: (1) China export restrictions — the US Commerce Department's October 2023 "
            "and January 2026 chip export rule updates significantly restrict semiconductor equipment sales "
            "to Chinese fabs. China represented 40-45% of revenue for LRCX and AMAT in 2023; "
            "restrictions have reduced this to an estimated 15-20%. (2) Memory capex cycle bottom — "
            "NAND and DRAM manufacturers (Samsung, SK Hynix, Micron) completed a severe capex reduction "
            "cycle in 2023-2024; recovery has been slower than expected, limiting equipment orders. "
            "(3) Leading-edge concentration — TSMC's AI-driven capex boom benefits chip designers (NVDA, AMD) "
            "disproportionately versus equipment makers who sell to TSMC at a normal equipment depreciation rate."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "amd_mi300x_revenue",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-29T21:00:00Z",
        "title": "AMD Q1 2026 — MI300X/MI350X Data Center GPU Revenue Detail",
        "text": (
            "LISA SU: Data Center GPU revenue exceeded $3 billion in Q1 2026 for the first time, "
            "driven by strong MI300X shipments to Microsoft Azure, Meta, and Oracle, with MI350X "
            "beginning to ramp. Our annualized Data Center GPU revenue run rate has crossed $12 billion. "
            "Key customer wins in Q1: Microsoft Azure expanded its MI300X fleet and is deploying MI300X "
            "for Azure AI inference workloads including GPT-4 and Azure OpenAI endpoints; Meta is using "
            "MI300X for Llama model inference to reduce cost versus H100; Oracle announced a 30,000 MI300X "
            "deployment for Oracle Cloud Infrastructure AI instances. "
            "MI350X (Instinct 350X based on CDNA4 architecture) began sampling to lead customers in Q1 "
            "and will contribute to Q3-Q4 2026 revenue. MI350X targets 2x the inference performance "
            "per dollar of MI300X and is designed to compete with NVIDIA's GB200 Blackwell system. "
            "AMD's AI revenue of $3B+ in Q1 demonstrates that the AI accelerator market has two credible "
            "players — a significant shift from H100's near-monopoly in 2023-2024."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "amd_epyc_server_market",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-03-15T09:00:00Z",
        "title": "AMD EPYC Turin Gains Server CPU Share — Now at 24% of New x86 Server Deployments",
        "text": (
            "AMD's EPYC Turin processor family (Zen 5 architecture, up to 192 cores per socket) has reached "
            "approximately 24% market share of new x86 server CPU deployments in Q4 2025, up from 20% "
            "in Q4 2024 and 14% in Q4 2022 (first EPYC Genoa shipments). Intel Xeon remains at ~76% share "
            "but has lost significant ground since AMD's EPYC Rome launch in 2019. EPYC Turin is especially "
            "competitive in cloud workloads requiring high core counts and memory bandwidth — AI inference, "
            "data warehousing, and web serving. Major EPYC Turin customers: AWS (DL2q and M7a instances), "
            "Microsoft Azure (Ebsv5 series), Google Cloud (C3A instances), Meta (large-scale inference). "
            "AMD EPYC generated approximately $2.9 billion in server CPU revenue in 2025, up 35% from 2024. "
            "Intel is expected to counter with Sierra Forest and Granite Rapids in 2025-2026, but initial "
            "benchmarks suggest EPYC Turin maintains a meaningful performance-per-watt advantage. "
            "AMD server CPU gross margin is estimated at approximately 65-70%."
        ),
        "query_classes": ["factual_lookup"],
    },
    # ── Boeing ─────────────────────────────────────────────────────────────
    {
        "key": "ba_737max_deliveries_guidance_2026",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-28T13:00:00Z",
        "title": "Boeing Q1 2026 Earnings Call — 737 MAX Delivery Guidance",
        "text": (
            "KELLY ORTBERG (CEO): After the production challenges of 2024, I am pleased to report that "
            "our 737 MAX production rate is recovering. We delivered 82 737 MAX aircraft in Q1 2026, "
            "up from 65 in Q4 2025. Our full-year 2026 delivery target for the 737 family is 400-420 aircraft. "
            "We are working to reach a production rate of 38 per month by end of 2026, up from 29 per month "
            "currently. Production was impacted in early 2025 by the FAA production freeze following the "
            "Alaska Airlines door plug incident in January 2024, and we are now operating under an FAA-approved "
            "production improvement plan. The supply chain remains the primary constraint: Spirit AeroSystems "
            "fuselage delivery cadence and supplier quality improvements are the critical path items. "
            "Brian West (CFO): Commercial Airplanes free cash flow is expected to turn positive in H2 2026 "
            "as MAX deliveries increase. We expect to exit 2026 at a cash-generative rate for the segment."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "ba_defense_segment_fy2023",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2024-01-31T16:00:00Z",
        "title": "Boeing 10-K FY2023 — Defense, Space & Security Segment Results",
        "text": (
            "Boeing Defense, Space & Security (BDS) reported revenue of $24.9 billion for fiscal year 2023, "
            "down 4% from $26.0 billion in fiscal 2022. BDS operating loss was $1.8 billion in 2023, "
            "compared to an operating loss of $3.5 billion in 2022. The improved performance reflects "
            "lower charges on fixed-price development programs, though several programs remain at risk. "
            "Key BDS programs: F/A-18 Super Hornet (final lot); F-15EX Eagle II (active production); "
            "KC-46A Pegasus tanker (ongoing production with margin pressure); Space Launch System (NASA, "
            "fixed-price with significant cost overruns); T-7A Red Hawk trainer (development stage); "
            "MQ-25 Stingray unmanned tanker. BDS recorded $1.4 billion in charges in FY2023 related to "
            "fixed-price development program cost overruns, primarily KC-46 and MQ-25. "
            "Backlog at end of 2023: $61 billion total BDS backlog, of which $21 billion is in US Government "
            "direct contracts. International defense export orders included F-15 deliveries to Saudi Arabia."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "ba_737max_deliveries_8k",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2026-04-10T16:00:00Z",
        "title": "Boeing Form 8-K: Q1 2026 Delivery and Order Summary",
        "text": (
            "ARLINGTON, Virginia — April 10, 2026 — Boeing Company (BA) released its Q1 2026 orders and "
            "deliveries summary. Total deliveries Q1 2026: 130 commercial aircraft. By model: "
            "737 MAX: 82 deliveries (to 20 customers). 787 Dreamliner: 27 deliveries. "
            "767 (freighter): 9 deliveries. 777X: First customer delivery April 8, 2026 (Lufthansa). "
            "Total orders Q1 2026: 189 net orders. Backlog at March 31, 2026: 5,810 aircraft valued at "
            "approximately $516 billion. The 777X has a backlog of 376 aircraft. "
            "Management reiterated full-year 2026 guidance: 400-420 737 deliveries, 80-85 787 deliveries. "
            "737 MAX inventory: 35 aircraft in inventory awaiting delivery due to customer financing and "
            "acceptance timing. Production rate: 29 aircraft per month as of Q1 2026, targeting 38/month "
            "by year-end."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "ba_production_targets",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-03-01T09:00:00Z",
        "title": "Boeing 737 MAX 2026 Production Recovery Plan: Path to 38/Month by Year-End",
        "text": (
            "Boeing's 737 MAX production recovery is the most closely watched story in commercial aviation. "
            "Following the January 2024 Alaska Airlines door plug incident and subsequent FAA production "
            "oversight, Boeing was limited to 29 MAX aircraft per month for most of 2024-2025. "
            "The FAA conditionally approved Boeing's Production Improvement Plan (PIP) in September 2025, "
            "allowing a phased rate increase: 29/month through Q1 2026, 32/month in Q2 2026, "
            "35/month in Q3 2026, 38/month in Q4 2026. The Spirit AeroSystems integration (Boeing acquired "
            "Spirit's Wichita fuselage unit in August 2024) is expected to improve supply chain quality. "
            "Boeing's 2026 full-year guidance of 400-420 MAX deliveries requires this rate ramp to proceed "
            "on schedule. Each 737 MAX generates approximately $55-65 million in revenue and Boeing needs "
            "approximately 300 MAX deliveries per year to break even on the program. At 400+ deliveries, "
            "the MAX contributes approximately $2-3 billion in operating income annually."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "ba_commercial_backlog",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-28T13:00:00Z",
        "title": "Boeing Q1 2026 — Commercial Airplanes Backlog and Market Outlook",
        "text": (
            "KELLY ORTBERG: Our commercial backlog of 5,810 aircraft represents approximately 9 years of "
            "production at current rates — one of the strongest backlogs in commercial aviation history. "
            "The 737 family backlog of 4,590 aircraft demonstrates the continued strength of single-aisle "
            "travel demand globally. Air traffic globally in 2025 surpassed 2019 pre-pandemic levels by 7%. "
            "The 787 Dreamliner backlog of 550 aircraft represents approximately 7 years of production. "
            "777X has 376 firm orders with first delivery to Lufthansa in April 2026 following years of "
            "delay. The backlog is well-diversified geographically: 40% US, 35% Europe/Middle East, 25% Asia. "
            "Key customers: Southwest Airlines (737 only fleet, 350 outstanding orders), Ryanair (737, 480 orders), "
            "United Airlines (787+737, combined 300+ orders), Emirates (777X, 205 orders). "
            "BRIAN WEST: Backlog provides significant revenue visibility. The challenge is converting backlog "
            "to deliveries faster — each delayed delivery is a financing cost and customer dissatisfaction risk."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "ba_space_defense_q1",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-28T13:00:00Z",
        "title": "Boeing Q1 2026 Earnings — Defense and Space Revenue Detail",
        "text": (
            "BRIAN WEST: Defense, Space & Security revenue was $6.8 billion in Q1 2026, up 5% year-over-year. "
            "BDS operating income was $0.5 billion, operating margin 7.4% — the first positive BDS margin "
            "in three years. Progress reflects: (1) F-15EX production efficiency improving as we approach "
            "full-rate production; (2) KC-46A program charges stabilizing; (3) T-7A development nearing "
            "completion. SLS (Space Launch System) will have 2 Artemis missions in 2026. "
            "BDS backlog: $63 billion, up 4% from year-ago. International defense: F/A-18 deliveries to "
            "Kuwait; F-15 for Qatar; P-8 Poseidon for India. US defense budget growth of 3.5% in FY2026 "
            "is supportive of BDS long-term demand. Starliner commercial crew program status: after the "
            "2024 mission issues, Boeing and NASA agreed on a recovery plan with a crewed flight scheduled "
            "for Q4 2026. The Starliner program has accumulated $1.5 billion in cost overruns."
        ),
        "query_classes": ["factual_lookup"],
    },
    # ── Macro / Market / Themes ────────────────────────────────────────────
    {
        "key": "fed_rate_decision_2025",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2025-12-17T19:00:00Z",
        "title": "Fed Cuts Rates by 25bps to 4.25-4.50% — Third Cut of 2025",
        "text": (
            "The Federal Open Market Committee (FOMC) voted unanimously on December 17, 2025 to reduce "
            "the federal funds rate target range by 25 basis points, to 4.25%-4.50%. This was the third "
            "rate cut of 2025, following 25bp cuts in September and November. The 2025 rate cuts totaled "
            "100 basis points, bringing rates from 5.25%-5.50% in early 2025 to the current 4.25%-4.50%. "
            "Fed Chair Jerome Powell stated: 'Inflation has continued to make progress toward our 2% "
            "objective, and the labor market has cooled modestly from its previously overheated state. "
            "We believe this recalibration is appropriate given the current economic conditions.' "
            "The SEP (Summary of Economic Projections) shows FOMC members expect 2 additional 25bp cuts "
            "in 2026 to a terminal rate of 3.75%-4.00%. Core PCE inflation for 2025 was 2.4%, above "
            "the 2% target but declining. Unemployment was 4.2%. GDP growth 2025 estimated at 2.3%."
        ),
        "query_classes": ["reasoning", "factual_lookup"],
    },
    {
        "key": "cpi_report_march_2026",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-10T08:30:00Z",
        "title": "March 2026 CPI Report: Headline 2.6%, Core 2.9% — Fed on Hold",
        "text": (
            "The Bureau of Labor Statistics released the Consumer Price Index for March 2026. "
            "Headline CPI: +2.6% year-over-year (versus February +2.8%). Core CPI (ex-food and energy): "
            "+2.9% YoY (vs February +3.1%). Month-over-month: Headline +0.2%, Core +0.2%. "
            "Shelter inflation remains sticky at +5.1% YoY, accounting for approximately 40% of total CPI. "
            "Energy prices: -1.8% YoY as oil prices stabilized. Food at home: +1.2% YoY. "
            "Services ex-shelter: +3.6% YoY — the 'supercore' measure watched closely by the Fed. "
            "Market reaction: Treasury yields fell 5-8 bps across the curve. S&P 500 up 0.4%. "
            "Fed funds futures shifted to price in one additional 25bp cut in 2026 (previously zero). "
            "FOMC likely to remain on hold at the May 7, 2026 meeting. "
            "The gradual decline from February's 3.1% core to March's 2.9% is positive but the Fed "
            "needs to see sustained sub-3% core before resuming rate cuts."
        ),
        "query_classes": ["reasoning", "factual_lookup"],
    },
    {
        "key": "bank_nim_rate_sensitivity",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-04-15T09:00:00Z",
        "title": "US Bank NIM Compression in 2026: Fed Cuts Flow Through Deposit Repricing",
        "text": (
            "US commercial bank net interest margins are under pressure in 2026 as the Federal Reserve's "
            "2025 rate cuts (100 bps total) gradually reprice both assets and liabilities. "
            "Asset repricing (declining loan yields): Floating-rate C&I loans (SOFR+spread) repriced "
            "immediately as SOFR declined from 5.3% in early 2025 to 4.3% by year-end. "
            "Liability repricing (deposit costs): Retail savings and money market deposit rates are declining "
            "more slowly as banks compete for stable funding — a higher 'deposit beta' in the cut cycle. "
            "The net effect: NIMs are contracting by approximately 5-15 bps across major banks in 2026. "
            "JPMorgan NIM: 2.75% (Q1 2026) vs 2.85% (Q1 2025). BofA NIM: 2.10% vs 2.19%. WFC NIM: 2.80% vs 2.86%. "
            "The macro factor most directly weighing on bank NIMs is the declining Fed funds rate — each "
            "25bp cut reduces major bank NII by $500M-$1B annually, with the impact lasting 1-2 years "
            "as loan portfolios gradually reprice."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "hyperscaler_capex_comparison_2026",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "Hyperscaler Capex League Table: Who Increased AI Investment Most Aggressively in 2026?",
        "text": (
            "Annual capital expenditure for the four major hyperscalers — trailing twelve months through Q1 2026: "
            "1. Microsoft: $82.3 billion TTM (+63% YoY growth). "
            "2. Amazon: $79.6 billion TTM (+53% YoY growth). "
            "3. Alphabet: $58.1 billion TTM (+41% YoY growth). "
            "4. Meta: $48.6 billion TTM (+37% YoY growth). "
            "By year-over-year capex growth rate: Microsoft (+63%) is the most aggressive, followed by "
            "Amazon (+53%), Alphabet (+41%), and Meta (+37%). "
            "In absolute dollar increase vs prior twelve months: Microsoft +$31.8B, Amazon +$27.5B, Alphabet +$16.3B, Meta +$13.2B. "
            "Combined hyperscaler capex: $268.6 billion TTM, up 50% YoY from $179 billion. "
            "This capex surge is primarily AI-driven: GPU procurement, data center construction, network infrastructure. "
            "For context: NVIDIA's FY2026 Data Center revenue of $115.2 billion represents approximately "
            "43% of total hyperscaler capex — the rest goes to other compute, storage, and network."
        ),
        "query_classes": ["comparison", "factual_lookup"],
    },
    {
        "key": "ai_infrastructure_trade_themes",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-06T09:00:00Z",
        "title": "AI Infrastructure Trade: The Four Themes Driving the 2026 Market Narrative",
        "text": (
            "The AI infrastructure investment theme continues to dominate equity market narratives in 2026. "
            "Four sub-themes are driving flows: "
            "(1) Hyperscaler capex cycle: Microsoft, Amazon, Google, and Meta collectively committing $250-270 billion "
            "in annual capex — the largest infrastructure investment cycle in technology history. "
            "Beneficiaries: NVIDIA (GPU), TSMC (chip manufacturing), Vertiv (data center power), Eaton (transformers). "
            "(2) Power and grid infrastructure: AI data centers require massive power. Vistra, Constellation Energy, "
            "and NextEra are benefiting from data center demand for 24/7 clean energy. "
            "(3) Cooling and physical infrastructure: liquid cooling companies like CoolIT and Vertiv have "
            "multi-year order backlogs as traditional air cooling reaches limits for high-density AI racks. "
            "(4) Network infrastructure: Arista Networks, Ciena, and Coherent are seeing AI-driven networking "
            "infrastructure upgrades. InfiniBand and Ethernet switching for GPU clusters are $20B+ markets. "
            "The AI infrastructure trade has outperformed the S&P 500 by approximately 35 percentage points "
            "year-to-date through May 2026."
        ),
        "query_classes": ["general"],
    },
    {
        "key": "semiconductor_equipment_underperformance",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-20T09:00:00Z",
        "title": "Semis Equipment Stocks Underperform SOX Index YTD 2026: What's Behind the Divergence?",
        "text": (
            "Philadelphia Semiconductor Index (SOX) is up approximately 18% year-to-date through April 2026. "
            "Semiconductor equipment stocks have significantly underperformed: "
            "Lam Research (LRCX): -4% YTD. Applied Materials (AMAT): +2% YTD. KLA Corporation (KLAC): +5% YTD. "
            "ASML Holding (ASML): +3% YTD. "
            "The SOX outperformance is driven by fabless AI chip designers (NVDA +47% YTD, AMD +22%) rather than "
            "equipment makers. Three factors explain equipment underperformance: "
            "(1) China revenue loss — US export controls have removed $5-8B in annual China equipment revenue. "
            "(2) Memory oversupply correction — NAND fab capacity additions have slowed as Samsung/SK Hynix "
            "prioritize HBM for AI over commodity NAND. (3) Leading-edge capex benefits chipmakers more than "
            "equipment makers because equipment is already installed — incremental revenue from higher wafer "
            "utilization goes directly to chipmakers, not equipment companies."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "market_daily_summary_may2026",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-06T17:30:00Z",
        "title": "Market Close Summary: May 6, 2026 — Tech Rally Continues on Earnings Beats",
        "text": (
            "US equity markets closed broadly higher on May 6, 2026. S&P 500: +0.8% to 5,847. "
            "Nasdaq Composite: +1.2%. Dow Jones: +0.4%. VIX: 12.8 (near multi-year low). "
            "Key movers: Apple +3.4% (Q2 beat reported after close May 1, momentum continuing). "
            "Meta +2.1% (Q1 beat, Zuckerberg's AI optimism). Microsoft +1.8% (Azure re-acceleration). "
            "Amazon +1.5% (AWS record margin). Alphabet +1.9% (Cloud growth and AI narrative). "
            "Nvidia +2.3% (Blackwell demand, earnings preview ahead of May 28 report). "
            "Treasuries: 10yr yield 4.18% (-2bps). Dollar Index: 103.2 (-0.1%). "
            "Oil: WTI $71.40/bbl (-0.6%). Gold: $2,340/oz (+0.3%). Bitcoin: $97,800 (+1.2%). "
            "Sector performance: Technology +1.4%, Communication Services +1.0%, Consumer Disc +0.7%, "
            "Financials +0.5%, Energy -0.4%, Utilities -0.2%."
        ),
        "query_classes": ["general"],
    },
    {
        "key": "market_weekly_summary_may2026",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-05-06T18:00:00Z",
        "title": "Weekly Market Summary: April 28 - May 2, 2026 — Big Tech Earnings Dominate",
        "text": (
            "The week of April 28 - May 2, 2026 was dominated by Big Tech earnings reports. S&P 500: +2.3% "
            "for the week. Nasdaq: +3.1%. The week's most significant events: "
            "Monday-Tuesday (April 28-29): Microsoft Q3 FY2026 (beat) and Alphabet Q1 2026 (beat) both "
            "reported strong cloud growth; MSFT +5.2%, GOOG +5.1% week-over-week. "
            "Thursday (May 1): Amazon Q1 2026 (AWS record 39.5% margin) and Apple Q2 FY2026 (China beat). "
            "AMZN +4.0%, AAPL +3.4% after-hours, held into the next week. Meta Q1 (ad recovery, buyback). META +6.2%. "
            "Friday (May 2): Strong week for tech; S&P 500 re-tested all-time highs at 5,870. "
            "Most notable story: hyperscaler AI capex guidance collectively of $270B+ in 2026 validated the "
            "AI infrastructure investment cycle and confirmed NVIDIA Blackwell demand remains robust. "
            "Winners: AI infrastructure (NVDA, Vertiv, Eaton). Losers: regional banks (NIM pressure), utilities "
            "(rate sensitivity with higher yields intraweek)."
        ),
        "query_classes": ["general", "time_anchored_edge"],
    },
    {
        "key": "earnings_highlights_q1_2026",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-05T08:00:00Z",
        "title": "Q1 2026 Earnings Season Summary: Mega-Cap Tech Outperforms",
        "text": (
            "Q1 2026 earnings season summary (approximately 80% of S&P 500 reported as of May 5, 2026): "
            "Aggregate S&P 500 earnings growth: +8.4% YoY. Revenue growth: +5.1% YoY. Beat rate: 74% (above historical 71%). "
            "Mega-cap technology standouts: Microsoft +20% EPS YoY (Azure 33% growth), Alphabet +27% EPS YoY, "
            "Meta +29% EPS YoY (ad recovery + buybacks), Amazon +63% EPS YoY (AWS record margins). "
            "Tesla -22% EPS YoY (margin pressure). Netflix +24% EPS YoY. "
            "Apple Q2 FY2026 (March quarter) reported separately — EPS +8% YoY with strong guidance. "
            "Weakest sectors: Energy (-12% EPS YoY on lower oil prices), Utilities (-3%), Real Estate (-5%). "
            "Strongest sectors: Technology (+20%), Communication Services (+16%), Consumer Discretionary (+12%). "
            "Forward guidance revision: 60% of companies maintained or raised full-year guidance. "
            "Consensus S&P 500 2026 EPS estimate: $273 (up 2.1% from pre-season $267 estimate)."
        ),
        "query_classes": ["general", "time_anchored_edge"],
    },
    {
        "key": "ai_infrastructure_themes_2026",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-30T08:00:00Z",
        "title": "AI Infrastructure Investment: The Main Themes Driving the 2026 Market Trade",
        "text": (
            "The AI infrastructure trade has become the dominant equity market theme of 2026. The core thesis: "
            "hyperscalers are spending $250-270 billion combined on AI data centers, and this spending "
            "benefits a specific ecosystem of companies. Primary beneficiaries by category: "
            "AI Chips: NVIDIA (GPU market leader, ~85% share), AMD (second-source GPU), Marvell (AI networking), "
            "Broadcom (custom AI ASIC for Google and Meta). "
            "AI Data Centers: Equinix, Digital Realty (co-location), Super Micro Computer (AI server racks). "
            "Power: Vistra, Constellation (nuclear power for data centers), Eaton, nVent (electrical infrastructure). "
            "Cooling: Vertiv Holdings (liquid cooling systems), Modine Manufacturing. "
            "Network: Arista Networks (data center Ethernet), Ciena (optical networking for hyperscaler backhaul). "
            "The AI infrastructure trade diverges from the 2000 internet bubble in one key way: hyperscalers are "
            "already generating revenue from AI — Microsoft's AI business is $13B annualized and growing 150% YoY."
        ),
        "query_classes": ["general"],
    },
    {
        "key": "cre_regional_banks_narrative",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-04-20T09:00:00Z",
        "title": "CRE Stress at Regional Banks: Office Exposure Creates Ongoing Concerns",
        "text": (
            "Commercial real estate (CRE) stress, particularly in the office subsector, continues to be "
            "a key risk narrative for US regional banks in 2026. Key data points: "
            "US office vacancy rate: 22.4% nationally, highest since 1990s, with major metro areas worse "
            "(NYC 28%, San Francisco 35%, Chicago 25%). Office cap rate expansion of 200+ bps since 2022 "
            "has reduced property values by 30-40% in major markets. "
            "Regional banks with highest office CRE exposure as % of total loans: "
            "New York Community Bancorp (NYCB) 8.2%, Valley National Bancorp 7.1%, Signature Bridge Bank "
            "(in FDIC resolution) had large office exposure. "
            "JPMorgan has $42.3 billion in office CRE loans (approximately 2.1% of loans), with $5.1 billion "
            "classified as criticized or non-accrual. The bank has taken $1.2 billion in CRE provisions. "
            "The silver lining: CRE maturities are being extended rather than defaulted en masse, as "
            "lenders prefer 'extend and pretend' over distressed sales that crystallize losses."
        ),
        "query_classes": ["general", "factual_lookup"],
    },
    {
        "key": "glp1_drug_market_narrative",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-25T09:00:00Z",
        "title": "GLP-1 Obesity Drug Market in 2026: $60B Revenue and Adjacent Market Impacts",
        "text": (
            "The GLP-1 receptor agonist market (Ozempic, Wegovy, Mounjaro, Zepbound) has become one of the "
            "most transformative developments in healthcare in decades. Combined GLP-1 market revenues: "
            "Novo Nordisk GLP-1 revenue (FY2025): $34.2 billion (Ozempic $22.4B, Wegovy $8.5B, others). "
            "Eli Lilly GLP-1 revenue (FY2025): $26.1 billion (Mounjaro $18.0B, Zepbound $7.2B, others). "
            "Total GLP-1 market: approximately $60 billion — the fastest-growing drug class in history. "
            "Adjacent market impacts: Airlines (reduced passenger weight → fuel savings, capacity changes), "
            "Food companies (reduced calorie consumption — soft drinks, snack foods facing volume headwinds), "
            "Medical devices (reduced bariatric surgery volumes — ResMed noting fewer severe sleep apnea cases), "
            "Orthopedics (reduced knee replacement procedures as obesity-related joint damage declines). "
            "Investment opportunities: HIMS (GLP-1 compounding), Catalent (contract manufacturing), "
            "Danaher (bioprocessing equipment for GLP-1 manufacturing scale-up)."
        ),
        "query_classes": ["general", "non_analyst"],
    },
    {
        "key": "defense_spending_growth",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-03-15T09:00:00Z",
        "title": "Defense Spending Boom: RTX, LMT, NOC Positioned for Multi-Year Growth Cycle",
        "text": (
            "Global defense spending is at its highest level since the Cold War. US defense budget for FY2026: "
            "$895 billion (+4.5% from FY2025). NATO member defense spending: average 2.1% of GDP, highest "
            "since NATO's 2% target was established. Russia-Ukraine war has catalyzed a multi-year European "
            "defense buildup: Germany, Poland, France, and UK all increasing budgets to 2.5%+ of GDP by 2028. "
            "US defense prime contractors positioned to benefit: "
            "Raytheon Technologies (RTX): Patriot missile systems, $14B+ backlog from European demand. "
            "Lockheed Martin (LMT): F-35 production ramping to 156/year; HIMARS artillery demand; C2 systems. "
            "Northrop Grumman (NOC): B-21 Raider bomber production started; space systems; cyber defense. "
            "L3Harris Technologies (LHX): electronic warfare, communications systems. "
            "General Dynamics (GD): Abrams M1 upgrade program; nuclear submarine construction. "
            "These companies benefit from: multi-year contracts with inflation escalation clauses; classified "
            "programs that limit competition; and geopolitical tailwinds likely to persist for 5-10 years."
        ),
        "query_classes": ["non_analyst", "general"],
    },
    {
        "key": "energy_transition_companies",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-01T09:00:00Z",
        "title": "Energy Transition Beneficiaries: Companies Expanding with the Green Energy Build-Out",
        "text": (
            "The global energy transition from fossil fuels to renewable energy is creating significant "
            "investment opportunities across multiple sectors. Key companies benefiting from the energy transition: "
            "Solar: First Solar (FSLR) — US manufacturer benefiting from IRA domestic content credits; "
            "Enphase Energy (ENPH) — inverter and battery systems leader; SolarEdge (SEDG). "
            "Wind: GE Vernova (GEV) — onshore and offshore wind turbines; Vestas (VWSYS) — global wind OEM. "
            "Grid Infrastructure: Eaton (ETN) — electrical switchgear and distribution; Quanta Services (PWR) — "
            "transmission line construction; AECOM — grid engineering. "
            "Battery Storage: Tesla Energy (Megapack), Fluence (grid-scale storage), LG Energy Solution. "
            "Nuclear: Vistra Energy (VST) — nuclear fleet restart narrative; Cameco (CCJ) — uranium mining. "
            "Transmission: MasTec — high-voltage transmission construction; Prysmian (PRYM) — submarine cables. "
            "The IRA (Inflation Reduction Act) provides $369 billion in clean energy incentives through 2032, "
            "creating durable demand for energy transition infrastructure."
        ),
        "query_classes": ["non_analyst"],
    },
    {
        "key": "vietnam_manufacturing_shift",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-02-15T09:00:00Z",
        "title": "Vietnam Manufacturing: US Companies Expanding Southeast Asian Operations",
        "text": (
            "Vietnam has emerged as the primary beneficiary of global supply chain diversification away from China. "
            "US companies that have expanded manufacturing operations in Vietnam: "
            "Apple: Now assembles MacBook, Apple Watch, and AirPods in Vietnam. Foxconn, Luxshare, and "
            "GoerTek are Apple's Vietnam contract manufacturers. Vietnam accounts for approximately 20% of "
            "Apple's total product assembly (ex-iPhone). "
            "Samsung: Vietnam is Samsung's largest global production hub for smartphones. Samsung employs "
            "130,000+ in Vietnam across Hanoi and Ho Chi Minh City facilities. "
            "Intel: Intel has its largest chip test and assembly (OSAT) facility in Ho Chi Minh City. "
            "Nike: 50% of all Nike shoes are manufactured in Vietnam (Pou Chen, Youngone as contractors). "
            "Google: Pixel phone assembly has moved to Vietnam (via Foxconn and Luxshare). "
            "Vietnam GDP growth in 2025: 7.1%, driven by FDI manufacturing investment. "
            "The US-Vietnam Comprehensive Strategic Partnership (2023) provides a favorable diplomatic "
            "framework for continued US corporate investment."
        ),
        "query_classes": ["non_analyst"],
    },
    {
        "key": "europe_us_expansion_2025",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2025-12-01T09:00:00Z",
        "title": "European Companies Announcing US Expansion Plans in 2025",
        "text": (
            "Several major European companies announced significant US market expansion plans in 2025, "
            "driven by the Inflation Reduction Act incentives and a favorable US investment climate: "
            "ASML (Netherlands): Announced $2.5 billion investment in a US customer support hub in Connecticut, "
            "to service the growing US semiconductor manufacturing footprint (TSMC Arizona, Intel Ohio). "
            "Volkswagen (Germany): $5 billion investment in Scout Motors EV pickup brand in South Carolina; "
            "US plant expected to employ 4,000 workers by 2027. "
            "Siemens (Germany): $150 million factory expansion in Sacramento for smart grid equipment. "
            "LVMH (France): $1.2 billion expansion of Loro Piana and Louis Vuitton US manufacturing. "
            "Novo Nordisk (Denmark): $4.1 billion greenfield API manufacturing facility in North Carolina "
            "to produce GLP-1 drug active pharmaceutical ingredients domestically. "
            "Roche (Switzerland): $1 billion expansion of diagnostics manufacturing in Indiana. "
            "These expansions reflect European companies adapting to the new geopolitical reality where "
            "proximity to the US market provides strategic advantages."
        ),
        "query_classes": ["non_analyst"],
    },
    {
        "key": "free_cash_flow_rising_screener",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Screener: Companies with Rising FCF and Declining Share Count (Buyback + FCF Signal)",
        "text": (
            "Companies meeting the criteria of: (1) Free cash flow growth >15% YoY for 2 consecutive years, "
            "(2) shares outstanding declining >2% YoY (active buybacks), (3) FCF yield >3%: "
            "Apple (AAPL): FCF $110.8B FY2025 (+10% YoY), shares declining 2.8%/year. FCF yield 3.7%. "
            "Microsoft (MSFT): FCF $74B FY2025 (+18% YoY), shares declining 0.8%/year. FCF yield 2.3%. "
            "Meta Platforms (META): FCF $52.1B FY2025 (+38% YoY), shares declining 2.1%/year. FCF yield 2.8%. "
            "Alphabet (GOOGL): FCF $61.5B FY2025 (+12% YoY), shares declining 1.5%/year. FCF yield 3.1%. "
            "Visa (V): FCF $18.5B FY2025 (+14% YoY), shares declining 2.4%/year. FCF yield 3.0%. "
            "UnitedHealth (UNH): FCF $22.0B FY2025 (+19% YoY), shares declining 1.8%/year. FCF yield 3.4%. "
            "Booking Holdings (BKNG): FCF $5.4B FY2025 (+30% YoY), shares declining 4.8%/year. FCF yield 3.9%. "
            "These companies represent high-quality capital allocators: generating growing cash and reducing share count."
        ),
        "query_classes": ["non_analyst"],
    },
    {
        "key": "earnings_beats_rising_guidance",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-06T09:00:00Z",
        "title": "Q1 2026 Earnings Beats with Raised Full-Year Guidance: The High-Quality List",
        "text": (
            "Companies reporting Q1 2026 earnings beats AND raising full-year guidance — the strongest "
            "combination for positive stock price reaction: "
            "Microsoft (MSFT): Q1 EPS beat +8%, FY2026 EPS guidance raised 5%. Azure growth re-accelerated. "
            "Meta Platforms (META): Q1 EPS beat +9%, FY2026 revenue guidance raised to $184-195B. "
            "Amazon (AMZN): Q1 EPS beat +15%, AWS margins above consensus, capex guidance confirms AI commitment. "
            "Alphabet (GOOGL): Q1 EPS beat +6%, Cloud guidance raised, Waymo acceleration. "
            "Eli Lilly (LLY): Q1 EPS beat +12%, FY2026 guidance raised $3 per share — GLP-1 supply improving. "
            "Visa (V): Q1 FY2026 EPS beat +4%, FY2026 EPS guidance raised 3%. "
            "Caterpillar (CAT): Q1 beat +7%, raised FY2026 on infrastructure demand. "
            "ServiceNow (NOW): Q1 beat +5%, raised on AI workflow automation demand. "
            "These 8 companies represent the cream of Q1 2026 earnings season — buy-signal quality management "
            "commentary combined with improving fundamentals."
        ),
        "query_classes": ["non_analyst"],
    },
    {
        "key": "dividend_stocks_screener",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Screener: Stocks Under $50 with P/E Under 15 and Dividend Yield Over 3%",
        "text": (
            "Stocks meeting the criteria: price <$50, P/E ratio <15x, dividend yield >3%, market cap >$2B: "
            "Ford Motor (F): Price $12.40, P/E 9.5x, dividend yield 4.8%. EPS $1.31 FY2025. "
            "AT&T (T): Price $19.70, P/E 10.8x, dividend yield 5.1%. Telecom stable. "
            "Pfizer (PFE): Price $26.90, P/E 12.2x, dividend yield 5.8%. Drug royalties declining but yield attractive. "
            "Verizon (VZ): Price $39.50, P/E 9.1x, dividend yield 6.4%. High yield, leverage a concern. "
            "KeyCorp (KEY): Price $17.30, P/E 11.3x, dividend yield 4.5%. Regional bank recovering. "
            "Altria (MO): Price $44.80, P/E 11.2x, dividend yield 7.5%. Tobacco declining volumes, high yield. "
            "Kohl's (KSS): Price $13.20, P/E 7.0x, dividend yield 9.2% — high yield but FCF at risk. "
            "Note: Screener results as of May 1, 2026. P/E based on forward estimates. "
            "Caveat: High dividend yields often signal elevated risk (dividend sustainability concerns)."
        ),
        "query_classes": ["non_analyst"],
    },
    {
        "key": "market_yesterday_tech_summary",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-06T08:00:00Z",
        "title": "Yesterday's Market News: May 5, 2026 — Tech Earnings Tailwind Continues",
        "text": (
            "Market recap for Monday May 5, 2026: S&P 500 +0.6%, Nasdaq Composite +0.9%, Dow Jones +0.3%. "
            "Technology sector led: NVDA +2.5% (new 52-week high $1,142 intraday, Blackwell demand optimism). "
            "AAPL +1.8% (momentum from Friday Q2 FY2026 beat). MSFT +1.4%. META +2.3%. "
            "News flow: (1) Morgan Stanley raised AAPL price target to $250 from $240 on Services growth beat. "
            "(2) Goldman Sachs initiated META at Buy with $560 target, citing AI monetization early evidence. "
            "(3) The Wall Street Journal reported Microsoft is in negotiations for a major government AI contract "
            "worth up to $12 billion, boosting MSFT sentiment. (4) Barclays upgraded AMD to Overweight, "
            "citing MI300X channel checks showing stronger-than-expected hyperscaler demand. "
            "Laggards: Energy sector -0.8% (oil down on Saudi production increase signals). "
            "Healthcare -0.3% (biosimilar competition concerns at Humira franchise). "
            "Bond market: 10yr yield 4.20% (+2bps). Dollar flat. VIX: 12.5 (complacency territory)."
        ),
        "query_classes": ["general"],
    },
    # ── Portfolio & Identifier ─────────────────────────────────────────────
    {
        "key": "aapl_identifier_isin",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Apple Inc. (AAPL) Security Identifiers and Classification",
        "text": (
            "Apple Inc. (AAPL) complete security identifier reference: "
            "ISIN: US0378331005. CUSIP: 037833100. SEDOL: 2046251. "
            "Ticker: AAPL (NASDAQ). Exchange: NASDAQ Global Select Market. "
            "SEC CIK Number: 0000320193. SEC Edgar Filing: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193 "
            "GICS Sector: 45 — Information Technology. GICS Industry Group: 4520 — Technology Hardware & Equipment. "
            "GICS Industry: 452020 — Technology Hardware, Storage and Peripherals. "
            "SIC Code: 3571 — Electronic Computers. "
            "Bloomberg: AAPL US Equity. Reuters: AAPL.O. "
            "Shares outstanding: 15.06 billion (as of April 2026). Market cap: approximately $3.18 trillion. "
            "Country of incorporation: United States. State: California. "
            "Fiscal year end: Last Saturday of September. "
            "Primary index membership: S&P 500, Nasdaq-100, Dow Jones Industrial Average, MSCI World."
        ),
        "query_classes": ["identifier_lookup"],
    },
    {
        "key": "aapl_sector_classification",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Apple Inc. (AAPL) Sector and Industry Classification Reference",
        "text": (
            "Apple Inc. (AAPL) is classified in the Technology sector under multiple classification systems: "
            "GICS (Global Industry Classification Standard): Sector 45 Information Technology, "
            "Industry Group 4520 Technology Hardware & Equipment, Industry 452020 Technology Hardware Storage & Peripherals. "
            "ICB (Industry Classification Benchmark): Supersector 9000 Technology, Sector 9500 Technology Hardware & Equipment. "
            "Russell/FTSE: Technology Sector. S&P 500: Information Technology sector (7.2% weight as of May 2026). "
            "Nasdaq-100: Information Technology category. "
            "For investor purposes: Apple's revenue mix (iPhone 52%, Services 23%, Other Products 25%) "
            "makes it behave partly as a consumer discretionary company and partly as a technology company. "
            "The S&P 500 rebalanced Apple into the Information Technology sector in 2018 (previously "
            "Consumer Electronics within Consumer Discretionary). "
            "ETF exposure: Technology Select Sector SPDR (XLK) weights AAPL at approximately 21%; "
            "QQQ (Nasdaq-100) at approximately 9%; SPY (S&P 500) at approximately 7%."
        ),
        "query_classes": ["identifier_lookup", "factual_lookup"],
    },
    {
        "key": "aapl_cik_sec_filings",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Apple Inc. CIK 0000320193 — Recent SEC Filings Summary",
        "text": (
            "Apple Inc. SEC EDGAR Central Index Key (CIK): 0000320193. "
            "Recent SEC filings for CIK 0000320193: "
            "Form 10-K (Annual): Filed November 1, 2025 (FY2025, period ending September 27, 2025). "
            "Form 10-Q (Quarterly): Filed February 5, 2026 (Q1 FY2026, period ending December 28, 2025). "
            "Form 10-Q (Quarterly): Filed May 2, 2026 (Q2 FY2026, period ending March 29, 2026). "
            "Form 8-K (Current Report): Filed May 1, 2026 (Q2 FY2026 earnings). "
            "Form 8-K: Filed March 17, 2026 (dividend declaration). "
            "Form DEF 14A (Proxy): Filed January 10, 2026 (2026 annual meeting). "
            "Form 4 (Insider Transactions): Multiple filings 2026 YTD (Tim Cook, Luca Maestri, others). "
            "All filings accessible at: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&type=10-K&dateb=&owner=include&count=40 "
            "EDGAR XBRL data available for all financial statements since FY2009."
        ),
        "query_classes": ["identifier_lookup"],
    },
    {
        "key": "portfolio_tech_holdings_pl",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio Technology Holdings: Month-to-Date P&L Summary",
        "text": (
            "Demo portfolio technology holdings performance — month of April 2026 (Apr 1 - Apr 30): "
            "AAPL (125 shares): MTD return +4.2%, MTD P&L +$1,110. Current value $26,425. "
            "MSFT (80 shares): MTD return +5.8%, MTD P&L +$1,945. Current value $33,488. "
            "NVDA (45 shares): MTD return +14.1%, MTD P&L +$6,228. Current value $50,733. "
            "TSLA (75 shares): MTD return -2.3%, MTD P&L -$391. Current value $17,460. "
            "AMZN (55 shares): MTD return +6.8%, MTD P&L +$851. Current value $12,551. "
            "Total technology holdings market value: $140,657. "
            "MTD portfolio P&L on tech holdings: +$9,743 (+7.4%). "
            "Technology weight in total portfolio: 76.8% (portfolio also holds non-tech exposure via ETFs). "
            "S&P 500 total return April 2026: +4.2%. Portfolio tech MTD +7.4% vs benchmark +4.2%: alpha +3.2pp "
            "driven by NVDA and MSFT outperformance."
        ),
        "query_classes": ["portfolio"],
    },
    {
        "key": "portfolio_sector_weights",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio Sector Weights vs S&P 500 Benchmark",
        "text": (
            "Demo portfolio sector allocation compared to S&P 500 index as of May 1, 2026: "
            "Information Technology: Portfolio 76.8% vs S&P 500 32.1% — OVERWEIGHT by 44.7pp. "
            "Consumer Discretionary: Portfolio 12.4% (Tesla) vs S&P 500 10.2% — slightly overweight. "
            "Consumer Staples: Portfolio 0% vs S&P 500 5.8% — UNDERWEIGHT. "
            "Healthcare: Portfolio 0% vs S&P 500 11.9% — UNDERWEIGHT. "
            "Financials: Portfolio 0% vs S&P 500 13.1% — UNDERWEIGHT. "
            "Energy: Portfolio 0% vs S&P 500 3.7% — UNDERWEIGHT. "
            "Utilities: Portfolio 0% vs S&P 500 2.6% — UNDERWEIGHT. "
            "Cash/ETF: Portfolio 10.8% (broad market ETF). "
            "Portfolio is highly concentrated in large-cap technology — this concentration is intentional "
            "but creates significant single-factor risk to technology sector multiple compression. "
            "Portfolio beta vs S&P 500 (blended): approximately 1.52, well above the index beta of 1.0."
        ),
        "query_classes": ["portfolio"],
    },
    {
        "key": "portfolio_earnings_calendar",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-06T12:00:00Z",
        "title": "Portfolio Holdings Earnings Calendar — Next 90 Days",
        "text": (
            "Upcoming earnings dates for demo portfolio holdings (as of May 6, 2026): "
            "NVDA (NVIDIA): Q1 FY2027 earnings — Expected May 28, 2026 (confirmed). "
            "TSLA (Tesla): Q2 2026 earnings — Expected approximately July 22, 2026 (estimated). "
            "AAPL (Apple): Q3 FY2026 earnings — Expected approximately July 30, 2026 (estimated). "
            "MSFT (Microsoft): Q4 FY2026 earnings — Expected approximately July 29, 2026 (estimated). "
            "AMZN (Amazon): Q2 2026 earnings — Expected approximately August 1, 2026 (estimated). "
            "All of AAPL, MSFT, AMZN, TSLA report in late July / early August — a concentrated earnings "
            "risk window that will likely drive elevated portfolio volatility in late July 2026. "
            "NVDA's May 28 report is the most near-term catalyst. Consensus expects Q1 FY2027 EPS of $0.93 "
            "on revenue of $43.2 billion. Beat above $0.97 EPS or $44B revenue would be strongly positive."
        ),
        "query_classes": ["portfolio", "time_anchored_edge"],
    },
    {
        "key": "portfolio_dividend_calendar",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-06T12:00:00Z",
        "title": "Portfolio Holdings Ex-Dividend Dates — Next 60 Days",
        "text": (
            "Upcoming ex-dividend dates for demo portfolio holdings (as of May 6, 2026): "
            "AAPL (Apple): Ex-dividend date May 9, 2026. Dividend $0.26/share. Payment date May 15, 2026. "
            "For 125 AAPL shares: expected dividend income $32.50. "
            "MSFT (Microsoft): Ex-dividend date May 14, 2026. Dividend $0.83/share. Payment date June 12, 2026. "
            "For 80 MSFT shares: expected dividend income $66.40. "
            "NVDA (NVIDIA): Nominal quarterly dividend $0.01/share. Ex-dividend date approximately June 10, 2026. "
            "For 45 NVDA shares: expected income $0.45 (effectively zero). "
            "TSLA (Tesla): No dividend currently paid. "
            "AMZN (Amazon): No dividend currently paid. "
            "Total portfolio dividend income next 60 days: approximately $99.35. "
            "Portfolio dividend yield: approximately 0.2% annualized — very low, reflecting growth-stock focus. "
            "S&P 500 dividend yield: approximately 1.3%."
        ),
        "query_classes": ["portfolio"],
    },
    {
        "key": "portfolio_concentration_risk",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio Single-Name Concentration Risk Analysis",
        "text": (
            "Portfolio single-name concentration risk analysis as of May 1, 2026: "
            "Top 3 holdings by weight and associated risks: "
            "1. NVDA (NVIDIA): 35.9% weight — LARGEST CONCENTRATION RISK. "
            "Key risks: US export restrictions to China; AMD MI300X/MI350X competition reducing NVDA pricing power; "
            "Blackwell production delays; valuation (29x forward EPS vs historical 20x avg). "
            "If NVDA declines 20%, portfolio impact: -7.2pp of portfolio return. "
            "2. MSFT (Microsoft): 23.7% weight. "
            "Key risks: Azure growth deceleration; OpenAI partnership deterioration; regulatory scrutiny. "
            "20% MSFT decline impact: -4.7pp portfolio. "
            "3. AAPL (Apple): 18.7% weight. "
            "Key risks: iPhone demand slowdown; China risk; App Store regulatory challenges. "
            "20% AAPL decline impact: -3.7pp portfolio. "
            "Combined top-3 concentration: 78.3% of portfolio in three stocks. "
            "Industry best practice: no single stock >10% for moderate risk tolerance."
        ),
        "query_classes": ["portfolio"],
    },
    {
        "key": "portfolio_beta_analysis",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T12:00:00Z",
        "title": "Demo Portfolio Beta Analysis: Which Holdings Have Highest Market Sensitivity?",
        "text": (
            "Portfolio holdings ranked by 5-year monthly beta (vs S&P 500, as of May 2026): "
            "1. TSLA (Tesla): Beta 2.31 — HIGHEST BETA. Most sensitive to market moves. "
            "2. NVDA (NVIDIA): Beta 1.85 — High beta from AI narrative and growth expectations. "
            "3. AAPL (Apple): Beta 1.22 — Moderate beta; defensive characteristics from Services cashflow. "
            "4. AMZN (Amazon): Beta 1.15 — Moderate beta; AWS stability buffers volatility. "
            "5. MSFT (Microsoft): Beta 0.90 — LOWEST BETA in portfolio; consistent earnings profile. "
            "Portfolio weighted-average beta: approximately 1.52. "
            "Interpretation: In an up-market day of +1% for S&P 500, portfolio expected to gain ~+1.52%. "
            "In a down-market day of -1%, portfolio expected to lose ~-1.52%. "
            "The high-beta portfolio has generated strong returns in the bull market of 2024-2026 "
            "but would suffer disproportionately in a market correction."
        ),
        "query_classes": ["portfolio"],
    },
    {
        "key": "q3_2025_earnings_calendar",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2025-09-20T12:00:00Z",
        "title": "Q3 2025 Earnings Season Calendar: Major Company Report Dates",
        "text": (
            "Q3 2025 earnings calendar for major US companies (calendar Q3 = July-September 2025): "
            "JPMorgan Chase: October 11, 2025. Goldman Sachs: October 14. Bank of America: October 15. "
            "Netflix: October 15. UnitedHealth: October 15. Johnson & Johnson: October 16. ASML: October 17. "
            "TSMC: October 17. Apple Q3 FY2025: October 30 (fiscal Q4 ends September). "
            "Alphabet: October 29. Meta: October 29. Microsoft Q1 FY2026: October 29. "
            "Amazon: October 30. Apple Q4 FY2025 (fiscal): October 30. "
            "Intel: October 31. Amazon alternative: October 30. "
            "NVIDIA Q3 FY2026: November 19. "
            "This calendar covers the Q3 2025 reporting season which spans October-November 2025. "
            "Earnings call transcripts and 10-Q filings will be available through SEC EDGAR following each report."
        ),
        "query_classes": ["identifier_lookup"],
    },
    # ── Relationships ──────────────────────────────────────────────────────
    {
        "key": "tsmc_apple_nvidia_customer_overlap",
        "source_type": "relation",
        "source_name": "sec_edgar",
        "published_at": "2026-04-20T09:00:00Z",
        "title": "TSMC Customer Overlap: Apple and NVIDIA Both Represent 10%+ of TSMC Revenue",
        "text": (
            "TSMC's two largest customers share critical production dependencies. Apple represents "
            "approximately 25% of TSMC revenue — the largest customer. NVIDIA represents approximately "
            "11% of TSMC revenue — the second largest. Both Apple's A-series/M-series chips and NVIDIA's "
            "H100/H200/Blackwell GPUs are manufactured exclusively at TSMC, making TSMC the common supplier "
            "for the two most important AI-era semiconductor companies. Both are now on TSMC's most advanced "
            "process nodes (3nm and 2nm for Apple; 4NP/CoWoS for NVIDIA Blackwell). "
            "The overlap creates interesting supply dynamics: when AI GPU demand surged in 2023, TSMC's "
            "CoWoS advanced packaging capacity became constrained, and NVIDIA and Apple effectively competed "
            "for the same packaging capacity. TSMC has since expanded CoWoS from 10,000 to 50,000+ wafers/month. "
            "Other major TSMC customers who also overlap with Apple/NVIDIA's supply chain: Qualcomm (Apple iPhone modems), "
            "AMD (competes with NVIDIA for TSMC capacity), Broadcom (Google/Meta custom AI ASICs)."
        ),
        "query_classes": ["relationship"],
    },
    {
        "key": "auto_battery_crossholdings",
        "source_type": "relation",
        "source_name": "sec_edgar",
        "published_at": "2026-03-01T09:00:00Z",
        "title": "Cross-Shareholdings Between US Automakers and Battery Suppliers",
        "text": (
            "Cross-shareholding and strategic investment relationships between US automakers and battery/EV suppliers: "
            "General Motors: GM holds equity stakes in Lithium Americas (LAC, ~3.8%), Solid Power (SLDP, 3.4%), "
            "and has a joint venture with Samsung SDI (Ultium Cells LLC, 50/50 for Ohio battery production). "
            "Ford Motor: Ford holds a 12% stake in Solid Power Inc. (SLDP) — solid state battery startup. "
            "Ford and SK Innovation (now SK On) have a 50/50 JV (BlueOval SK) for battery production. "
            "Stellantis: Stellantis holds a 19.5% stake in Archer Aviation (electric air taxi). Stellantis "
            "and Samsung SDI have a JV for battery production in Indiana. "
            "Tesla: No cross-shareholdings in battery suppliers; Tesla mines and manufactures its own cells "
            "(4680 format in Nevada). However, Tesla has supply agreements with Panasonic (Gigafactory Nevada, "
            "equity stake pre-2020 unwound), CATL (China), and LG Energy Solution. "
            "These cross-shareholdings are primarily strategic to secure battery supply, not financial investments."
        ),
        "query_classes": ["relationship"],
    },
    {
        "key": "samsung_apple_oled_overlap",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-02-15T09:00:00Z",
        "title": "Shared OLED Supply Chain: Apple and Samsung's Common Suppliers",
        "text": (
            "Despite being fierce smartphone competitors, Apple and Samsung share significant OLED display "
            "supply chain overlap. Common suppliers for both Apple iPhone and Samsung Galaxy OLED panels: "
            "Samsung Display Corporation (Samsung subsidiary): Supplies OLED to both Apple (iPhone Pro) and "
            "Samsung Electronics (Galaxy S flagship). Samsung Display is unique in competing with its parent "
            "company's phones by supplying Apple. "
            "LG Display: Second-tier supplier to both Apple (iPhone 17 standard OLED) and Samsung Galaxy S26. "
            "Corning Incorporated: Gorilla Glass supplier to both Apple (Ceramic Shield variant) and Samsung. "
            "Qualcomm: Supplies Snapdragon modem to Samsung Galaxy and cellular modems to Apple iPhone standard. "
            "Sony Semiconductor: Image sensors (ISP) supplied to both Apple and Samsung phone cameras. "
            "TSMC: Manufactures chips for both Apple (A-series) and Samsung LSI division's Exynos chips "
            "(on certain Galaxy models where Samsung LSI outsources to TSMC due to yield superiority). "
            "The shared supply base creates supplier leverage over both OEMs and enables component cost benchmarking."
        ),
        "query_classes": ["relationship"],
    },
    {
        "key": "msft_github_acquisition",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2018-10-26T12:00:00Z",
        "title": "Microsoft Closes $7.5 Billion Acquisition of GitHub",
        "text": (
            "Microsoft completed its acquisition of GitHub for approximately $7.5 billion in stock on "
            "October 26, 2018. GitHub is the world's largest code hosting platform with over 100 million "
            "developers (as of 2026) and over 330 million repositories. The acquisition was central to "
            "Microsoft's developer-first strategy and has become increasingly strategic with the rise of AI. "
            "GitHub Copilot, launched in 2021 and powered by OpenAI's Codex and later GPT-4, has become "
            "one of Microsoft's fastest-growing AI products, with 2 million paid enterprise subscribers by "
            "Q1 2026. GitHub's code repository data also powers Microsoft's AI training for code generation. "
            "Integration into Azure Dev Ops and Azure provides enterprise customers a unified DevOps pipeline. "
            "At the time of acquisition, concerns were raised about open-source community trust in Microsoft "
            "owning the platform, but adoption has continued growing at >20% annually. "
            "GitHub Copilot Enterprise contributed approximately $800M in revenue in FY2025."
        ),
        "query_classes": ["relationship", "factual_lookup"],
    },
    {
        "key": "msft_linkedin_acquisition",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2016-12-08T12:00:00Z",
        "title": "Microsoft Acquired LinkedIn for $26.2 Billion in 2016 — Now Key to AI Stack",
        "text": (
            "Microsoft completed its acquisition of LinkedIn for $26.2 billion on December 8, 2016 — "
            "at the time the largest technology acquisition ever. LinkedIn had 467 million members at close. "
            "By 2026, LinkedIn has grown to 1.1 billion members across 200 countries. "
            "LinkedIn Revenue FY2025: approximately $18.5 billion, fully consolidated in Microsoft's "
            "Productivity and Business Processes segment. LinkedIn contributes approximately 25% of the "
            "Productivity segment's revenue. LinkedIn's strategic value to Microsoft has increased dramatically "
            "with AI: LinkedIn's professional data (job history, skills, professional relationships) is used "
            "in Microsoft Copilot for professional context. LinkedIn Learning has integrated AI tutors. "
            "LinkedIn Sales Navigator integrates with Microsoft Dynamics CRM + Copilot. "
            "The acquisition is now widely regarded as Microsoft's most successful acquisition, having paid "
            "for itself several times over in both revenue and strategic data assets for AI."
        ),
        "query_classes": ["relationship", "factual_lookup"],
    },
    {
        "key": "amzn_institutional_13f_detail",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-15T16:00:00Z",
        "title": "Amazon Q1 2026 13F Summary: Institutional Investor Position Changes",
        "text": (
            "Amazon.com (AMZN) institutional ownership changes reported in Q1 2026 13F filings (filed May 15, 2026): "
            "Increased positions: BlackRock +12.3M shares (now 412.8M = 3.1% of float). "
            "T. Rowe Price +5.1M shares. Fidelity +3.8M shares. Ark Invest +2.1M shares. "
            "Reduced positions: Vanguard -1.8M shares (index rebalancing). "
            "State Street -0.9M shares (index rebalancing). "
            "New positions: Lone Pine Capital initiated 3.2M share position ($730M market value). "
            "Tiger Global initiated 1.8M shares ($411M) — rebuilding tech exposure. "
            "Exited: Greenlight Capital exited 1.1M shares (profit-taking). "
            "Total institutional ownership: approximately 63% of AMZN outstanding shares. "
            "Insider ownership: Jeff Bezos holds approximately 9.1% of shares outstanding (diluted). "
            "Short interest: 0.9% of float — very low, little bearish positioning. "
            "The 13F data shows broad institutional buying of AMZN in Q1 2026, consistent with "
            "AWS margin expansion driving consensus earnings upgrade cycle."
        ),
        "query_classes": ["relationship", "signal_intel"],
    },
    {
        "key": "berkshire_insider_buying",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-04-10T09:00:00Z",
        "title": "Berkshire Hathaway Insider Activity Q1 2026: Warren Buffett and Board Purchases",
        "text": (
            "Berkshire Hathaway (BRK.A / BRK.B) insider activity for Q1 2026 as reported in SEC Form 4 filings: "
            "Warren Buffett (CEO/Chairman): No open-market purchases of BRK.B in Q1 2026. Buffett's ownership "
            "includes approximately 228,000 BRK.A equivalent shares (~16% of economic interest), all inherited "
            "or awarded. He continues to donate approximately 4-5% of his stake annually to the Gates Foundation "
            "and family foundations. No selling activity. "
            "Greg Abel (Vice Chairman, designated CEO successor): Abel purchased 168 BRK.B shares in February "
            "2026 at $464.30/share for a total of $77,922 — a symbolic but positive insider signal. "
            "Other directors: No significant insider purchase or sale activity. "
            "Berkshire share repurchases (company-level buyback): $2.1 billion in Q1 2026, as Berkshire "
            "continues to repurchase shares when BRK.A trades below 1.5x book value per share. "
            "Note: Berkshire's largest 'insider buy' comes from its continued investment of operating cash flow "
            "into common equity stakes (Apple, American Express, Chevron)."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "institutional_inflows_q1_2026",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-16T09:00:00Z",
        "title": "Q1 2026 13F Season: Which Stocks Saw Largest Institutional Inflows?",
        "text": (
            "Based on aggregated Q1 2026 13F filings (due May 15, 2026), the stocks with the largest "
            "institutional inflows (new buys + position increases, net of sells) in Q1 2026: "
            "1. NVIDIA (NVDA): +$18.2 billion net institutional inflows — largest by far. Blackwell "
            "ramp optimism drove widespread institutional accumulation. "
            "2. Meta Platforms (META): +$9.4 billion net inflows. Q1 earnings beat + buyback drove upgrades. "
            "3. Amazon (AMZN): +$7.1 billion net inflows. AWS margin expansion story. "
            "4. Microsoft (MSFT): +$6.8 billion net inflows. Azure AI re-acceleration. "
            "5. Alphabet (GOOGL): +$5.3 billion net inflows. Cloud competitive positioning. "
            "6. Eli Lilly (LLY): +$4.7 billion. GLP-1 supply improving, raised guidance. "
            "7. Broadcom (AVGO): +$3.9 billion. AI ASIC custom chip story. "
            "8. Palantir (PLTR): +$3.1 billion. Government + commercial AI adoption. "
            "Largest outflows: Intel (-$3.4B), Pfizer (-$2.8B), Walgreens (-$1.9B)."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "tech_block_trades_unusual",
        "source_type": "signal_intel",
        "source_name": "finnhub",
        "published_at": "2026-05-06T16:00:00Z",
        "title": "Unusual Block Trades in Tech Mega-Caps: May 6, 2026",
        "text": (
            "Unusual block trade activity detected in technology mega-cap stocks on May 6, 2026: "
            "NVDA: 3 block trades >100,000 shares on the NYSE dark pool. Largest: 245,000 shares at $1,138 "
            "($278.8M notional), executed 14:32 ET. Market-on-close imbalance: +850,000 NVDA shares buy-side. "
            "AAPL: 2 block trades >500,000 shares. Largest: 620,000 shares at $210.80 ($130.7M). "
            "MSFT: 1 large block: 380,000 shares at $417.50 ($158.7M), sell-side, executed 11:15 ET. "
            "META: Block buy of 210,000 shares at $527.40 ($110.8M) — likely pension fund rebalancing. "
            "AMZN: No unusual block activity. "
            "Interpretation: NVDA and AAPL block activity skews buy-side (institutional accumulation). "
            "MSFT block is sell-side but within normal institutional rebalancing parameters. "
            "Put/call ratios: NVDA 0.42 (bullish), AAPL 0.58 (neutral-bullish), MSFT 0.63 (neutral). "
            "No confirmed dark pool activity above $500M in any single name — no obvious M&A-related positioning."
        ),
        "query_classes": ["signal_intel"],
    },
    # ── Financial Data ─────────────────────────────────────────────────────
    {
        "key": "aapl_pe_vs_5yr_avg",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T12:00:00Z",
        "title": "Apple P/E Ratio vs 5-Year Average: Current Premium and Historical Context",
        "text": (
            "Apple Inc. (AAPL) current P/E ratio vs 5-year average: "
            "Current trailing twelve-month P/E: 31.4x (share price $211.40 / FY2025 EPS $6.73). "
            "Current forward P/E (FY2026 consensus EPS $7.25): 29.2x. "
            "5-year average trailing P/E (FY2021-FY2025): 27.8x. "
            "Premium to 5-year average: +13% (31.4x vs 27.8x). "
            "Historical P/E by fiscal year: FY2021 28.1x, FY2022 22.3x, FY2023 28.9x, FY2024 29.4x, FY2025 30.7x. "
            "5-year range: 22.3x (trough FY2022 during tech selloff) to 34.5x (peak January 2022). "
            "Apple's forward P/E has expanded from approximately 24x in early 2023 to 29x now, driven by "
            "Services mix expansion re-rating and AI Super Cycle expectations for iPhone. "
            "Versus S&P 500 forward P/E of 22.1x, Apple trades at a premium of 7.1 turns — historically high. "
            "Bull case: Services growth sustains 15%+ CAGR, justifying premium vs the index. "
            "Bear case: Multiple compression if iPhone volume disappoints or AI cycle overhyped."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "msft_gross_margin_q1_q4_2025",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "Microsoft Gross Margin: Q2 FY2025 Through Q3 FY2026 Detail",
        "text": (
            "Microsoft Corporation gross margin quarterly data — five most recent quarters: "
            "Q3 FY2025 (Mar 2025): Revenue $70.1B, gross profit $47.6B, gross margin 67.9%. "
            "Q4 FY2025 (Jun 2025): Revenue $73.4B, gross profit $50.3B, gross margin 68.6%. "
            "Q1 FY2026 (Sep 2025): Revenue $65.6B, gross profit $45.5B, gross margin 69.3%. "
            "Q2 FY2026 (Dec 2025): Revenue $69.6B, gross profit $48.7B, gross margin 69.9%. "
            "Q3 FY2026 (Mar 2026): Revenue $70.1B, gross profit $49.2B, gross margin 70.1%. "
            "Trend: +220bps over four quarters from 67.9% to 70.1%. "
            "Driver analysis: Azure AI services (high-margin) growing 150%+ YoY and lifting blended gross margin. "
            "Office 365 price increases of 10% in 2024 also contributed. Gaming remains dilutive (Activision "
            "integration costs ~$1.2B/quarter in amortization). Analyst consensus: gross margin reaches "
            "71.5% by Q4 FY2026 and 73% by FY2027 as AI services reach scale."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "tsla_debt_equity_2024",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-02-10T10:00:00Z",
        "title": "Tesla Debt-to-Equity Ratio: One of the Lowest Among Major Auto OEMs",
        "text": (
            "Tesla Inc. (TSLA) debt-to-equity analysis based on December 31, 2025 balance sheet: "
            "Total long-term debt: $4.3 billion. Current debt: $1.5 billion. Total debt: $5.8 billion. "
            "Total stockholders' equity: $74.9 billion. Debt-to-equity ratio: 0.077x. "
            "Net cash position (cash $36.6B minus total debt $5.8B): +$30.8 billion net cash. "
            "For comparison, auto industry peers: "
            "Toyota: D/E 1.15x. BMW: D/E 1.42x. Ford: D/E 3.21x. GM: D/E 2.85x. Volkswagen: D/E 1.85x. "
            "Stellantis: D/E 0.62x. BYD: D/E 0.62x. "
            "Tesla's ultra-low debt-to-equity of 0.077x and strong net cash position provide significant "
            "financial flexibility for capex investment, share buybacks, and R&D. "
            "Tesla's balance sheet dramatically improved from 2019 (D/E ~2.4x, borderline insolvency) "
            "as operating profitability funded deleveraging. The $10B buyback program authorized "
            "in February 2024 has repurchased approximately $4.2 billion through Q1 2026."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "nvda_eps_estimate_fy2025",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-05T10:00:00Z",
        "title": "NVIDIA Forward EPS Consensus Estimate: FY2027 $4.65 Non-GAAP",
        "text": (
            "NVIDIA Corporation (NVDA) consensus EPS estimates from 52 analyst estimates (as of May 5, 2026): "
            "FY2026 Non-GAAP EPS (ended Jan 2026, actual): $2.99. "
            "FY2027 Non-GAAP EPS consensus: $4.65 (52 estimates, range $4.20-$5.10). "
            "FY2028 Non-GAAP EPS consensus: $5.90 (42 estimates, range $4.80-$7.20). "
            "GAAP EPS typically runs $0.50-$0.60 below Non-GAAP due to stock-based comp and amortization. "
            "FY2027 revenue consensus: $219.8 billion (range $198B-$241B). "
            "FY2027 Data Center revenue consensus: $192B. Gaming: $14B. Automotive: $4B. Other: $10B. "
            "Implied P/E at current $1,127 price: FY2026 377x (trailing), FY2027 242x (forward non-GAAP). "
            "PEG ratio (FY2027 EPS growth ~55%, P/E 242x): PEG ~4.4x — expensive but high-growth companies "
            "trade at elevated PEGs. Bull P/E target of 30x FY2027: $1,395 price. "
            "Bear case: $600 target at 15x FY2027 if competition or export restrictions impair growth."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "jpm_roe_5yr_chart",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-04-15T10:00:00Z",
        "title": "JPMorgan Chase ROE Five-Year Trend: 2021-2025 with Industry Context",
        "text": (
            "JPMorgan Chase return on equity trend and peer comparison: "
            "JPMorgan FY2021 ROE: 19.1% (record year, minimal provisions, NII benefit from steep curve). "
            "JPMorgan FY2022 ROE: 13.1% (Ukraine macro provisions, regulatory capital build). "
            "JPMorgan FY2023 ROE: 16.8% (First Republic acquisition, high rates benefit). "
            "JPMorgan FY2024 ROE: 20.0% (peak year, highest rates, low credit losses, IB revival). "
            "JPMorgan FY2025 ROE: 17.5% (rate cuts begin reducing NII). "
            "Five-year average ROE: 17.3%, ROTCE 21.2%. "
            "Peer comparison (FY2025): Goldman Sachs ROTE 15.1%, Morgan Stanley ROTE 19.2%, "
            "Bank of America ROE 11.0%, Citigroup ROE 7.0%, Wells Fargo ROE 12.8%. "
            "JPMorgan's 5-year ROE of 17.3% is highest among large US banks. "
            "JPMorgan guides to through-the-cycle ROTCE of 17%, having exceeded that target in 4 of 5 years."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "aapl_interest_coverage_ratio",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-02T10:00:00Z",
        "title": "Apple Interest Coverage Ratio: 40.2x Based on FY2025 10-K",
        "text": (
            "Apple Inc. (AAPL) interest coverage ratio calculation based on FY2025 Annual Report (10-K): "
            "EBIT (Earnings Before Interest and Taxes): $123.2 billion (FY2025). "
            "Interest expense: $3.07 billion (FY2025, net of capitalized interest). "
            "Interest coverage ratio: $123.2B / $3.07B = 40.2x. "
            "Prior year comparison: FY2024 EBIT $112.4B / $2.93B interest = 38.4x. FY2023: 33.6x. "
            "Trend: improving over three years from 33.6x to 40.2x as EBIT grows faster than interest expense. "
            "For context on what 40.2x means: Apple can cover its entire annual interest obligation 40 times "
            "over from operating earnings alone. This represents extraordinary credit quality. "
            "Investment-grade rated companies typically have coverage ratios of 5-15x. Apple's 40x ratio "
            "explains its Aaa/AAA credit ratings from Moody's and S&P. "
            "Apple has approximately $97.3 billion in long-term debt, used primarily to fund buybacks "
            "rather than operations, given the low cost of borrowing relative to buyback yield."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "walmart_sss_q1_2026",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-05-15T13:00:00Z",
        "title": "Walmart Q1 FY2027 Earnings Call — Same-Store Sales Growth",
        "text": (
            "JOHN DAVID RAINEY (CFO): Walmart US same-store sales (comps) grew 4.6% year-over-year in Q1 "
            "fiscal 2027 (ending April 30, 2026). This compares to 4.7% comps in Q4 FY2026 and 4.9% in "
            "Q3 FY2026 — a slight moderation but still strong consumer spending at Walmart. "
            "Walmart US comp breakdown: ticket (average basket) +1.8%, transactions (customer visits) +2.8%. "
            "E-commerce contributed approximately 1.5pp of the total 4.6% comp growth — Walmart.com GMV "
            "grew 22% year-over-year. Grocery was the strongest performing category with mid-single-digit comps. "
            "Apparel and electronics were softer at low single-digit comps. "
            "Doug McMillon (CEO): 'We continue to gain wallet share from higher-income consumers who are "
            "seeking value in a challenging economic environment. Our everyday low price model is a durable "
            "competitive advantage.' Sam's Club comps: +5.8% (including fuel) and +4.2% (excluding fuel). "
            "International revenue: +4.6% constant currency, led by Flipkart India and Walmart Mexico."
        ),
        "query_classes": ["financial_data"],
    },
    {
        "key": "walmart_q1_2026_8k",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2026-05-15T12:00:00Z",
        "title": "Walmart Form 8-K: Q1 FY2027 Financial Results Including Same-Store Sales",
        "text": (
            "BENTONVILLE, Arkansas — May 15, 2026 — Walmart Inc. released Q1 fiscal 2027 (April 30, 2026) results. "
            "Net revenues: $168.3 billion (+5.1% YoY). Operating income: $7.1 billion (+8.2% YoY). "
            "EPS (diluted): $0.61 vs consensus $0.59 (beat $0.02). "
            "Walmart US net sales: $115.8B (+4.8% YoY). Walmart US same-store sales: +4.6% (comp excluding fuel). "
            "Sam's Club US net sales: $23.7B (+5.3% YoY). Sam's Club comps: +4.2% excl. fuel. "
            "International net sales: $28.8B (+4.6% constant currency). "
            "Walmart Connect (advertising business): $960M in Q1 (+25% YoY). "
            "Gross margin: 24.2% (+20bps YoY). Operating margin: 4.2% (+10bps YoY). "
            "FY2027 guidance: Net sales +3-4% YoY. Operating income +3.5-4.5% YoY. "
            "Q2 FY2027 guidance: Net sales +4-5%. EPS $0.60-0.62."
        ),
        "query_classes": ["financial_data"],
    },
    # ── Signal Intel ───────────────────────────────────────────────────────
    {
        "key": "nvda_options_unusual_activity",
        "source_type": "signal_intel",
        "source_name": "finnhub",
        "published_at": "2026-05-06T16:00:00Z",
        "title": "NVDA Unusual Options: Massive Call Sweep Ahead of May 28 Earnings",
        "text": (
            "Unusual options activity on NVIDIA (NVDA) this week (May 4-6, 2026), ahead of May 28 earnings: "
            "Total NVDA options volume: 2.4x 20-day moving average. Put/call ratio: 0.42 (extremely bullish). "
            "Largest individual trades this week: "
            "May 5, 10:47 AM ET: 4,800 NVDA $1,200 calls exp July 18, 2026 — bought at ask $18.50 = $8.88M total premium. "
            "May 5, 2:15 PM ET: 3,100 NVDA $1,150 calls exp June 20, 2026 — sweep order at ask $32.40 = $10.04M. "
            "May 6, 11:30 AM ET: 2,200 NVDA $1,100 puts exp June 20, 2026 — bought at bid $14.20 = $3.12M (hedge). "
            "Net premium: call buying $18.92M vs put buying $3.12M this week — strongly bullish skew. "
            "Implied volatility term structure: IV30 (30-day IV): 42%. IV60: 38%. IV90: 35%. "
            "IV is elevated ahead of earnings (May 28). Options market implies ±8% stock move on earnings day. "
            "Historical pattern: NVDA has moved more than the implied move in 3 of the last 4 earnings."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "meta_insider_selling_detail",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-04-20T09:00:00Z",
        "title": "Meta Platforms Insider Selling: Zuckerberg Q1 2026 10b5-1 Sales Detail",
        "text": (
            "Meta Platforms (META) insider selling activity in Q1 2026, from SEC Form 4 filings: "
            "Mark Zuckerberg (CEO/Controlling Stockholder): Sold 840,000 Class A shares in Q1 2026 "
            "under 10b5-1 plan established Q3 2025. Shares sold at prices ranging from $595.40 to $636.80. "
            "Total Q1 2026 proceeds: approximately $520 million. "
            "Zuckerberg has sold approximately $2.8 billion in Meta shares in the 12 months ended March 2026, "
            "consistent with his pre-announced plan to sell annually to fund Chan Zuckerberg Initiative philanthropy. "
            "Other insider transactions Q1 2026: "
            "Sheryl Sandberg (former COO, still Board member): Sold 150,000 shares at avg $608 = $91.2M. "
            "Susan Li (CFO): Sold 15,000 shares under 10b5-1 at avg $615 = $9.2M. "
            "Mike Schroepfer (former CTO, Board): Sold 200,000 shares at avg $602 = $120.4M. "
            "All insider sales were executed under pre-established 10b5-1 plans and do not indicate "
            "negative views on META's near-term performance."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "sentiment_negative_sectors",
        "source_type": "signal_intel",
        "source_name": "finnhub",
        "published_at": "2026-05-04T09:00:00Z",
        "title": "Sector Sentiment Scorecard: Most Negative News Sentiment Last Week",
        "text": (
            "News sentiment analysis for US equity sectors — week of April 28 - May 2, 2026: "
            "Most negative sentiment sectors: "
            "1. Energy (XLE): Sentiment score -0.42 (scale -1 to +1). Top stories: OPEC+ production increase, "
            "Saudi Aramco cutting prices, US shale operators warning on WTI breakeven at $65. "
            "2. Utilities (XLU): Sentiment score -0.28. Stories: Higher-for-longer rates reducing utility "
            "dividend appeal; grid stability concerns at aging coal-replacement sites. "
            "3. Healthcare (XLV): Sentiment score -0.22. Stories: Biosimilar competition for Humira/Dupixent; "
            "drug pricing legislation risk returning to Congress. "
            "Most positive sentiment: Technology +0.78 (Big Tech earnings beats). Communication Services +0.65. "
            "Consumer Discretionary +0.31. Methodology: Finnhub news sentiment model trained on 2M+ financial "
            "articles, scoring each article -1 to +1, sector-aggregated and volume-weighted by source authority. "
            "This data is updated hourly. Past-week summary may not reflect real-time conditions."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "institutional_inflows_detail",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-16T10:00:00Z",
        "title": "Q1 2026 Institutional Inflows: Top 10 Stocks by Net Institutional Buying",
        "text": (
            "Top 10 stocks by net institutional buying (13F Q1 2026 aggregated): "
            "Rank 1: NVDA +$18.2B (Blackwell ramp, AI infrastructure). "
            "Rank 2: META +$9.4B (ad revenue beat, AI assistant scale). "
            "Rank 3: AMZN +$7.1B (AWS margin expansion). "
            "Rank 4: MSFT +$6.8B (Azure AI re-acceleration). "
            "Rank 5: GOOGL +$5.3B (Cloud competitive position). "
            "Rank 6: LLY +$4.7B (GLP-1 supply improving). "
            "Rank 7: AVGO +$3.9B (AI custom ASIC growth). "
            "Rank 8: PLTR +$3.1B (government + commercial AI). "
            "Rank 9: VST +$2.8B (nuclear power + data center demand). "
            "Rank 10: CRWD +$2.4B (cybersecurity AI-driven upgrades). "
            "Largest institutional outflows: INTC -$3.4B, PFE -$2.8B, WBA -$1.9B, CVS -$1.7B, T -$1.5B. "
            "Methodology: Aggregated Form 13F-HR filings for all 1,200+ institutions managing >$100M."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "small_cap_volume_spikes",
        "source_type": "signal_intel",
        "source_name": "finnhub",
        "published_at": "2026-05-06T16:30:00Z",
        "title": "Small-Cap Volume Anomalies Detected: May 6, 2026 Morning Session",
        "text": (
            "Small-cap stocks with abnormal volume spikes in the morning session (9:30-12:00 ET) May 6, 2026: "
            "1. IREN (Iris Energy, Bitcoin mining AI data centers): Volume 8.4x 20-day avg. Stock +11.2%. "
            "News: Announced partnership with Microsoft to provide GPU cloud burst capacity. "
            "2. SOUN (SoundHound AI): Volume 6.2x avg. Stock +8.4%. Catalyst: Apple reportedly evaluating "
            "SoundHound AI integration for future Siri upgrade — unconfirmed reports. "
            "3. SERV (Serve Robotics, delivery robots): Volume 5.8x avg. Stock +7.9%. "
            "Catalyst: Uber confirmed expanding Serve robot delivery fleet in Los Angeles. "
            "4. RGTI (Rigetti Computing, quantum): Volume 4.9x avg. Stock +6.1%. No clear catalyst — "
            "possible sympathy move with broader quantum/AI sector. "
            "5. BBAI (BigBear.ai): Volume 4.7x avg. Stock +5.8%. Catalyst: DoD AI contract announcement. "
            "These volume spikes are being monitored for continuation — unusual volume in small-caps "
            "preceding a breakout is historically a reliable short-term signal in trending AI-related names."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "tech_sector_recent_moves",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-06T09:00:00Z",
        "title": "Recent Moves in Tech: Key Developments This Past Week",
        "text": (
            "Summary of key technology sector developments this past week (April 28 - May 6, 2026): "
            "Earnings: Microsoft Q3 FY2026 — Azure +33%, AI business $13B annualized. MSFT +5.2% on week. "
            "Alphabet Q1 2026 — Cloud +28%, Search resilient vs AI. GOOG +5.1% on week. "
            "Meta Q1 2026 — Ad revenue +18%, capex $60-65B guided. META +6.2% on week. "
            "Amazon Q1 2026 — AWS margin 39.5% record. AMZN +4.0% on week. "
            "Apple Q2 FY2026 — iPhone +7%, Services +15%, China beat. AAPL +3.4% on week. "
            "Analyst actions: Morgan Stanley raised AAPL PT $250. Goldman initiated META Buy $560. "
            "Barclays upgraded AMD to Overweight. "
            "M&A: Salesforce confirmed $3.1B acquisition of Informatica for data cloud integration. "
            "Broadcom confirmed $10B stock buyback alongside Q2 guidance raise. "
            "AI news: OpenAI GPT-5 reportedly in limited testing (per Bloomberg). "
            "Google launched Gemini 2.5 Pro with claimed 'best coding performance' benchmark. "
            "Anthropic Claude 4.5 announced with improved context window. "
            "Tech sector (XLK) weekly return: +3.6%."
        ),
        "query_classes": ["general", "non_analyst"],
    },
    {
        "key": "semis_since_nvda_earnings",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-05-06T08:00:00Z",
        "title": "Semiconductor Sector Since NVDA's Last Earnings: Key Developments",
        "text": (
            "Key developments in the semiconductor sector since NVIDIA's Q4 FY2026 earnings report "
            "(released February 26, 2026, reporting January quarter results): "
            "1. Blackwell GPU ramp accelerating: NVDA shipped $11B+ in Blackwell revenue in Q4 FY2026, "
            "tracking ahead of initial $7-8B guidance. TSMC CoWoS yield improvement enabled higher volume. "
            "2. AMD MI300X/MI350X gaining share: AMD reported Q1 2026 Data Center GPU revenue >$3B — the "
            "first credible second-source AI GPU supplier is now confirmed at scale. "
            "3. Samsung HBM supply issues: Samsung's HBM3E memory chips failed NVIDIA quality certification, "
            "temporarily constraining Blackwell production. SK Hynix and Micron picked up Samsung's HBM share. "
            "4. Intel Gaudi 3 flop: Intel's Gaudi 3 AI accelerator failed to gain hyperscaler design wins; "
            "Intel exited the AI accelerator market in April 2026 — a significant competitive exit. "
            "5. TSMC raised 2026 revenue guidance to 27-28% growth on Blackwell and Apple N2 ramp. "
            "6. Equipment: ASML Q1 2026 orders $9.3B — slight miss on high bookings expectations."
        ),
        "query_classes": ["time_anchored_edge"],
    },
    # ── Additional comparison and financial data chunks ────────────────────
    {
        "key": "visa_mastercard_payment_volume",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-04-25T21:00:00Z",
        "title": "Visa and Mastercard Q1 2026 Payment Volume Growth Comparison",
        "text": (
            "Visa Inc. Q1 FY2026 (March quarter) payment volume grew 8% year-over-year on a constant currency basis. "
            "Cross-border volume (international transactions) grew 15% — the highest-margin category. "
            "Total transactions processed: 61.8 billion (up 9% YoY). US payment volume: +6% YoY. "
            "International volume: +10% YoY (ex-intra-Europe). "
            "Mastercard Q1 2026 switched volume grew 10% year-over-year in constant currency. "
            "Cross-border volume +17% YoY. GDV (gross dollar volume): $2.61 trillion. "
            "On a four-quarter trailing basis: Visa average payment volume growth 8.5%, Mastercard 10.2%. "
            "Mastercard's higher growth reflects: (1) slightly higher international exposure (55% vs 50% for Visa); "
            "(2) higher exposure to fastest-growing markets (Africa, Southeast Asia); (3) Mastercard's "
            "services business (Data & Services segment) growing faster than network revenue. "
            "Both companies benefit from secular cash-to-digital payment conversion, with card penetration "
            "still below 50% in many emerging markets."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "apple_google_earnings_surprise_compare",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-02T09:00:00Z",
        "title": "Apple vs Google: Head-to-Head Earnings Surprise Comparison Q1/Q2 2026",
        "text": (
            "Apple and Alphabet both reported earnings on the evening of May 1, 2026 — here is the earnings "
            "surprise comparison: "
            "Apple Q2 FY2026 (March quarter): Revenue $95.4B vs consensus $93.3B = +$2.1B beat (+2.2%). "
            "EPS $1.65 vs consensus $1.58 = +$0.07 beat (+4.4%). Stock reaction: +3.4% after-hours. "
            "Alphabet Q1 2026 (March quarter): Revenue $90.2B vs consensus $88.1B = +$2.1B beat (+2.4%). "
            "EPS $2.81 vs consensus $2.65 = +$0.16 beat (+6.0%). Stock reaction: +5.1% after-hours. "
            "Comparing the two beats: Both beat by identical $2.1B in absolute dollars. "
            "Alphabet beat by 2.4% vs Apple's 2.2% — marginally larger percentage beat. "
            "Alphabet's EPS beat percentage (6.0%) was larger than Apple's (4.4%). "
            "Alphabet's stock reacted more positively (+5.1%) vs Apple (+3.4%), likely because "
            "Google Cloud's acceleration was a bigger positive surprise vs. Apple's China beat."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "pfizer_lilly_rd_comparison",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T10:00:00Z",
        "title": "R&D as % of Revenue: Pfizer vs Eli Lilly Comparison FY2025",
        "text": (
            "R&D spending as a percentage of revenue — Pfizer vs Eli Lilly: "
            "Eli Lilly (LLY) FY2025: R&D expense $11.1 billion on revenue $45.0 billion = 24.7% R&D/revenue. "
            "Pfizer (PFE) FY2025: R&D expense $10.9 billion on revenue $63.6 billion = 17.1% R&D/revenue. "
            "Eli Lilly invests a higher percentage of revenue in R&D, reflecting its rapid growth phase "
            "and large late-stage pipeline (donanemab for Alzheimer's, orforglipron oral GLP-1, "
            "retatrutide for obesity). Pfizer's lower R&D ratio reflects revenue normalization post-COVID "
            "(Paxlovid and vaccine revenues declining) and portfolio maturity. "
            "Comparison over four quarters (FY2024): Lilly 25.3%, Pfizer 18.4%. FY2023: Lilly 19.1%, Pfizer 14.2%. "
            "Lilly's R&D ratio has increased as GLP-1 success funds a more aggressive pipeline investment. "
            "Pfizer's R&D in absolute dollars ($10.9B) is 2nd highest in pharma after J&J ($15.8B)."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "airline_gross_margins_q1_2026",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-01T10:00:00Z",
        "title": "US Airline Gross Margin Comparison Q1 2026",
        "text": (
            "US major airline gross margin comparison for Q1 2026 (January-March): "
            "Delta Air Lines (DAL): Revenue $14.0B, gross profit $2.5B, gross margin 17.9%. "
            "United Airlines (UAL): Revenue $13.2B, gross profit $2.1B, gross margin 15.9%. "
            "American Airlines (AAL): Revenue $12.7B, gross profit $1.5B, gross margin 11.8%. "
            "Southwest Airlines (LUV): Revenue $6.8B, gross profit $0.7B, gross margin 10.3%. "
            "Note: Airline gross margin is defined here as operating revenue minus fuel + labor costs "
            "as a percentage of revenue (adjusted gross margin methodology). "
            "Delta's 17.9% industry-leading margin reflects its premium cabin mix, higher international "
            "exposure, and American Express co-brand partnership generating $7B+ in annual payment fees. "
            "Southwest's margin compression reflects failed network strategy and activist pressure "
            "(Elliott Management acquired 11% stake in 2025). "
            "American continues to struggle with its high-cost structure from 2013 merger legacy. "
            "Q1 is seasonally weak for airlines; Q3 (summer peak) typically 300-500bps higher margin."
        ),
        "query_classes": ["comparison"],
    },
    {
        "key": "salesforce_acquisitions_2024",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2024-06-15T09:00:00Z",
        "title": "Salesforce Strategic Acquisitions 2023-2024: Informatica, Own Backup, Spiff",
        "text": (
            "Salesforce Inc. (CRM) announced or completed the following strategic acquisitions in 2023-2024: "
            "1. Informatica (announced March 2024, withdrawn/re-negotiated to $3.1B by May 2026): "
            "Data cloud and AI integration platform, replacing the previously rejected $11B bid. "
            "2. Own Company (acquired April 2024, $1.9 billion): Data protection and backup for Salesforce "
            "and other SaaS platforms. Own Company protects Salesforce, Microsoft 365, and ServiceNow data. "
            "3. Spiff (acquired January 2024, $419 million): Sales commission management automation. "
            "Integrated into Salesforce Sales Cloud as 'Salesforce Spiff.' "
            "4. Tenyx (acquired August 2024, undisclosed): AI voice agent technology for customer service. "
            "5. Zoomin (investment 2024): Technical content management for documentation AI. "
            "Salesforce's acquisition strategy in 2024 focused on: (1) AI data quality (Informatica, Own); "
            "(2) Revenue operations automation (Spiff); (3) Conversational AI (Tenyx). "
            "CEO Marc Benioff has committed to disciplined M&A after the $27.7B Slack acquisition received "
            "criticism for dilution. Recent deals are smaller and more targeted."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "costco_eps_guidance_q2_2026",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-03-05T21:00:00Z",
        "title": "Costco Q2 FY2026 Earnings Call — EPS and Forward Guidance",
        "text": (
            "GARY MILLERCHIP (CFO): Costco's second fiscal quarter (ending February 16, 2026) core business "
            "continues to perform extremely well. We reported EPS of $4.02, up 12% year-over-year, beating "
            "analyst consensus of $3.86 by $0.16. Revenue was $63.7 billion, comp sales +8.2% (net of "
            "gasoline price deflation). Membership fee revenue was $1.24 billion, up 7.4% — a leading "
            "indicator of retention strength. RICHARD GALANTI (outgoing CFO): For fiscal Q3 2026 "
            "(ending May 2026), we expect comparable store sales in the 7-9% range based on current trends. "
            "We do not provide formal EPS guidance, consistent with our longstanding policy. "
            "However, analysts should expect mid-to-high single digit EPS growth to continue reflecting "
            "membership base expansion, e-commerce penetration improvement, and executive team continuity. "
            "RON VACHRIS (CEO): Costco plans to open 30 new warehouse locations globally in fiscal 2026, "
            "including 5 international locations. Membership renewal rates remain at 93.3% globally — "
            "a multi-decade record."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "tsmc_revenue_apple_scenario",
        "source_type": "claim",
        "source_name": "finnhub",
        "published_at": "2026-04-20T09:00:00Z",
        "title": "What Would TSMC Revenue Look Like if Apple Shifted 50% of Orders to Samsung Foundry?",
        "text": (
            "Hypothetical scenario analysis: If Apple shifted 50% of its TSMC chip orders to Samsung Foundry. "
            "Current state: Apple contributes approximately 25% of TSMC's annual revenue (~$28B of ~$112B). "
            "A 50% Apple order shift to Samsung Foundry would represent: ~$14 billion revenue reduction at TSMC. "
            "TSMC FY2025 revenue was approximately $112 billion. Post-shift: ~$98B (12.5% reduction). "
            "However, this scenario faces massive technical barriers: Samsung Foundry's 3nm and 2nm processes "
            "have significantly lower yields than TSMC's equivalent nodes, making Apple A18/A19 chip "
            "production economically unattractive. Samsung's 4nm (used for Qualcomm Snapdragon 8 Gen 2) "
            "had severe yield issues in 2022 that damaged Samsung Foundry's reputation. "
            "For this scenario to materialize, Samsung Foundry would need 2-3 years to reach yield parity "
            "with TSMC on leading nodes. Given this constraint, even a partial 50% shift is highly unlikely "
            "within 5 years. The more plausible scenario: Apple shifts non-critical chips (Wi-Fi, modem) "
            "to alternate fabs while TSMC retains core A-series/M-series chip manufacturing."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "nvidia_gross_margin_without_ai",
        "source_type": "claim",
        "source_name": "finnhub",
        "published_at": "2026-04-15T09:00:00Z",
        "title": "Counterfactual: NVIDIA's Gross Margin Without the AI Accelerator Demand Surge",
        "text": (
            "Counterfactual analysis: What would NVIDIA's gross margin profile look like without the AI "
            "accelerator demand surge of 2023-2026? "
            "Pre-AI baseline: In FY2022 and early FY2023, NVIDIA's blended gross margin was 56-65%, "
            "reflecting a healthy but more competitive GPU business serving gaming, professional visualization, "
            "and data center (non-AI). Hypothesis: Without the ChatGPT-induced AI demand surge, NVIDIA's "
            "data center business would have grown at 20-30% annually instead of 200%+, and gross margin "
            "would have remained in the 60-65% range. At 60% gross margin on estimated FY2025 revenue of "
            "$70B (pre-AI scenario): gross profit of ~$42B vs actual $98B at 75% margin. "
            "The AI premium at peak contributed approximately 10-13 percentage points to gross margin "
            "versus the competitive baseline. As competition from AMD, Google TPUs, and Amazon Trainium "
            "increases, NVIDIA's gross margin may eventually converge toward 65-70% — still excellent but "
            "below the current 73-75% level."
        ),
        "query_classes": ["reasoning"],
    },
    {
        "key": "pe_ratio_explainer",
        "source_type": "claim",
        "source_name": "finnhub",
        "published_at": "2026-01-01T00:00:00Z",
        "title": "What Is a P/E Ratio? Price-to-Earnings Explained for Investors",
        "text": (
            "A price-to-earnings (P/E) ratio is a fundamental valuation metric that compares a company's "
            "current share price to its earnings per share (EPS). Formula: P/E = Share Price / EPS. "
            "Example: Apple Inc. share price $211.40 / FY2025 EPS $6.73 = P/E ratio of 31.4x. "
            "Interpretation: A P/E of 31.4x means investors are paying $31.40 for each $1 of earnings. "
            "Alternatively, it means the stock would take 31.4 years to 'earn back' its purchase price "
            "at current earnings (assuming zero growth). Types: Trailing P/E uses actual past 12-month EPS. "
            "Forward P/E uses consensus analyst estimate for next 12 months. "
            "High P/E (>25x): Market expects high earnings growth (growth stocks). "
            "Low P/E (<15x): Market expects slow growth or higher risk (value stocks). "
            "S&P 500 average P/E over 50 years: approximately 16x. Current S&P 500 P/E: ~22x (above average). "
            "Limitations: P/E can be distorted by write-offs, one-time charges, or share buybacks. "
            "P/E doesn't account for growth rate — use PEG ratio (P/E ÷ growth rate) for growth-adjusted comparison."
        ),
        "query_classes": ["general"],
    },
    {
        "key": "what_is_evebitda_explainer",
        "source_type": "claim",
        "source_name": "finnhub",
        "published_at": "2026-01-01T00:00:00Z",
        "title": "EV/EBITDA Explained: Enterprise Value to EBITDA Valuation Metric",
        "text": (
            "EV/EBITDA (Enterprise Value to Earnings Before Interest, Taxes, Depreciation, and Amortization) "
            "is a valuation multiple used to compare companies regardless of capital structure. "
            "Formula: EV/EBITDA = (Market Cap + Net Debt) / EBITDA. "
            "Enterprise Value = Market Cap + Total Debt - Cash. "
            "EBITDA = Operating Income + Depreciation + Amortization (proxy for operating cash generation). "
            "Example: Apple market cap $3.18T + net debt $32.8B = EV $3.21T. EBITDA ~$140B. EV/EBITDA = 22.9x. "
            "Why EV/EBITDA vs P/E? EV/EBITDA neutralizes differences in debt levels and tax rates, "
            "making cross-company comparison more meaningful. Useful for capital-intensive businesses. "
            "Typical ranges: S&P 500 median ~12x. Technology 20-30x. Utilities 8-12x. Banks (not applicable — "
            "EBITDA not meaningful for financials). High-growth SaaS 30-60x. "
            "Limitation: EBITDA ignores real capital expenditure needs (capex) — EBITDA can flatter "
            "capital-intensive businesses. Free Cash Flow yield is often preferred by sophisticated analysts."
        ),
        "query_classes": ["general"],
    },
    {
        "key": "semiconductor_equipment_lam_amat",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-22T09:00:00Z",
        "title": "Lam Research and Applied Materials Q1 2026: China Headwinds Continue",
        "text": (
            "Semiconductor equipment giants Lam Research (LRCX) and Applied Materials (AMAT) reported "
            "Q1 2026 (calendar) results showing persistent headwinds from China export controls. "
            "Lam Research Q1 2026: Revenue $4.72B (+8% YoY), below consensus $4.90B. China revenue "
            "declined to 26% of total from 39% in Q1 2025 — a $640M year-over-year revenue headwind. "
            "Non-GAAP EPS: $1.04 vs consensus $1.12. Stock declined 7% on results. "
            "Applied Materials Q2 FY2026 (ending April 2026): Revenue $7.1B (+6% YoY), in-line. "
            "China revenue 24% of total (vs 30% prior year). EPS $2.39 slightly above $2.35 consensus. "
            "Both companies noted that leading-edge logic spending (TSMC, Samsung, Intel) is healthy, "
            "but memory (NAND/DRAM) capex recovery has been slower than expected. "
            "ASML (lithography, not directly restricted from China) reported €9.3B orders in Q1 — "
            "slightly below expectations, suggesting broader equipment order softness."
        ),
        "query_classes": ["factual_lookup", "reasoning"],
    },
    {
        "key": "macro_pce_inflation_2026",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-30T08:30:00Z",
        "title": "March 2026 PCE Inflation: 2.3% Headline, 2.6% Core — Fed Monitoring",
        "text": (
            "The Bureau of Economic Analysis released March 2026 Personal Consumption Expenditures (PCE) data. "
            "PCE Price Index: +2.3% year-over-year (headline). Core PCE (ex food and energy): +2.6% YoY. "
            "Month-over-month: Headline +0.2%, Core +0.2%. "
            "The Fed's preferred inflation gauge (Core PCE) at 2.6% remains above the 2% target. "
            "However, the three-month annualized core PCE rate has slowed to 2.1%, suggesting inflation "
            "is approaching target on a momentum basis. "
            "Personal income: +0.5% MoM. Personal spending: +0.7% MoM (strong consumer). "
            "Real consumer spending +0.5% MoM — resilient consumer despite rate environment. "
            "Federal Reserve implications: With core PCE at 2.6%, the Fed is unlikely to cut rates at "
            "its May 2026 meeting. Market pricing: approximately 45% probability of one rate cut in 2026 "
            "H2 based on the current data path. The Fed's dual mandate is essentially achieved on employment "
            "(4.1% unemployment) but core PCE remains stubborn above 2%."
        ),
        "query_classes": ["reasoning", "factual_lookup"],
    },
    {
        "key": "macro_jobs_report_april",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-05-01T08:30:00Z",
        "title": "April 2026 Jobs Report: 177K Non-Farm Payrolls, Unemployment 4.1%",
        "text": (
            "The Bureau of Labor Statistics released the April 2026 Employment Situation Summary. "
            "Non-farm payrolls: +177,000 jobs (consensus +185,000). Prior month revised down by 15,000 "
            "to +192,000 (from +207,000). Unemployment rate: 4.1% (unchanged). "
            "Average hourly earnings: +3.8% YoY, +0.2% MoM (in-line with expectations). "
            "Labor force participation rate: 62.7% (unchanged). "
            "Sector breakdown: Professional/business services +58K, Healthcare +43K, Government +10K, "
            "Manufacturing -8K, Retail -12K. "
            "Market reaction: S&P 500 futures rose 0.3% as the modest miss on payrolls was interpreted "
            "as reducing near-term inflation risk without signaling recession. 10yr Treasury yield declined "
            "4bps to 4.16%. Dollar weakened modestly. "
            "Fed implications: The labor market is cooling gradually — from 300K+ monthly gains in 2022 "
            "to 177K in April 2026. Not yet weak enough to justify rate cuts but consistent with the "
            "soft-landing scenario the Fed has been engineering since 2022. Full employment maintained "
            "while inflation declines — the Fed's ideal outcome."
        ),
        "query_classes": ["reasoning", "factual_lookup"],
    },
    {
        "key": "banks_q1_2026_sector_summary",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-04-20T09:00:00Z",
        "title": "US Banking Sector Q1 2026 Earnings Roundup: NIM Pressure, IB Recovery",
        "text": (
            "US banking sector Q1 2026 earnings summary across major institutions: "
            "JPMorgan Chase: Revenue $46.4B (+8%), NIM down 10bps, IB fees +22%, EPS $4.61 (beat). "
            "Bank of America: Revenue $25.8B (+6%), NIM 2.10% (-9bps), trading revenue $5.3B (+7%). EPS $0.90 (in-line). "
            "Goldman Sachs: Revenue $15.1B (+15%), investment banking $2.2B (+32%), ROTE 17.1%. EPS $14.12 (beat). "
            "Morgan Stanley: Revenue $17.2B (+12%), wealth management $7.3B (+11%), ROTE 19.4%. EPS $2.60 (beat). "
            "Wells Fargo: Revenue $20.2B (+4%), NIM 2.80% (-6bps), provisions higher. EPS $1.39 (slight miss). "
            "Citigroup: Revenue $21.6B (+3%), Transformation program on track, CET1 13.4%. EPS $1.71 (beat). "
            "Sector themes: (1) NIM pressure from rate cuts — universal but manageable; "
            "(2) Investment banking recovery from 2022-2023 drought — M&A and ECM both up 20%+; "
            "(3) Credit quality stable — charge-off rates below historical averages; "
            "(4) Capital return commitments intact — all major banks maintaining/growing dividends."
        ),
        "query_classes": ["general", "factual_lookup"],
    },
    {
        "key": "tech_sector_q1_2026_summary",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-05T09:00:00Z",
        "title": "Technology Sector Q1 2026 Earnings: Best Season Since 2021",
        "text": (
            "Technology sector Q1 2026 earnings summary — this is shaping up to be the best tech earnings "
            "season since Q3 2021 by earnings growth rate. Key results: "
            "Apple Q2 FY2026: Revenue +6%, EPS +8%. Services record $26.3B. Beat consensus by $2.1B. "
            "Microsoft Q3 FY2026: Revenue +16%, EPS +20%. Azure +33%. Beat by $1.8B revenue. "
            "Alphabet Q1 2026: Revenue +12%, EPS +27%. Cloud +28%. Beat by $2.1B. "
            "Meta Q1 2026: Revenue +18%, EPS +29%. Ad recovery. Beat by $1.4B. "
            "Amazon Q1 2026: Revenue +9%, EPS +63%. AWS operating margin 39.5% record. Beat by $2.4B. "
            "Netflix Q1 2026: Revenue +15%, EPS +24%. Subscriber adds beat. "
            "Aggregate Technology sector Q1 2026 EPS growth: +20.3% YoY (vs +8.4% for total S&P 500). "
            "AI infrastructure investment is translating into revenue acceleration at all five hyperscalers. "
            "Combined market cap added by Big Tech week of May 1: approximately $1.5 trillion."
        ),
        "query_classes": ["general", "time_anchored_edge"],
    },
    {
        "key": "healthcare_glp1_pipeline",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-01T09:00:00Z",
        "title": "GLP-1 Drug Stocks: How to Invest in the Obesity Drug Megatrend",
        "text": (
            "Investor's guide to the GLP-1 (glucagon-like peptide-1) receptor agonist investment opportunity: "
            "Primary beneficiaries: Novo Nordisk (NVO) — Ozempic/Wegovy, $34B GLP-1 revenue FY2025, "
            "targeting $65B by 2030. Eli Lilly (LLY) — Mounjaro/Zepbound, $26B GLP-1 revenue, "
            "pipeline includes orforglipron (oral GLP-1) and retatrutide (triple agonist, greater weight loss). "
            "Secondary beneficiaries: Danaher (DHR) — bioprocessing equipment for GLP-1 manufacturing. "
            "Catalent/Novo Holdings — contract manufacturing for injectable GLP-1 formulations. "
            "HIMS & Hers (HIMS) — GLP-1 compounding pharmacy (regulatory risk). "
            "Losers from GLP-1 success: ResMed (RMD) — fewer severe sleep apnea patients (down 30% in 2024). "
            "Insulet (PODD) — fewer insulin pump users if obesity/diabetes prevention succeeds. "
            "Becton Dickinson (BDX) — fewer insulin syringe volumes. "
            "Airlines — potentially lower seat density requirements as passenger weights decline. "
            "The GLP-1 market could reach $150-200B globally by 2035 per various analyst estimates."
        ),
        "query_classes": ["non_analyst"],
    },
    {
        "key": "defense_rtx_lmt_revenues",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-04-25T09:00:00Z",
        "title": "RTX and LMT Q1 2026: Defense Prime Contractors Benefiting from Spending Growth",
        "text": (
            "Defense prime contractors Raytheon Technologies (RTX) and Lockheed Martin (LMT) both reported "
            "strong Q1 2026 results driven by elevated global defense spending. "
            "RTX Q1 2026: Revenue $21.6B (+9% YoY). Defense segment revenue: $9.5B (+12%). "
            "Pratt & Whitney aircraft engines: $5.7B (+13%). Collins Aerospace: $6.4B (+5%). "
            "Patriot missile system backlog: $6.2B from European NATO members. EPS $1.61 (beat $1.52 est). "
            "LMT Q1 2026: Revenue $18.0B (+8% YoY). F-35 program: 30 deliveries, $5.1B revenue. "
            "HIMARS artillery deliveries up 70% YoY as Ukraine/NATO demand continues. "
            "Missiles & Fire Control: $3.2B (+12%). Sikorsky helicopters: $2.1B (+4%). "
            "EPS $7.28 (beat $6.95 est). LMT raised FY2026 guidance to $70.4-72.0B revenue. "
            "Both companies benefit from: multi-year NATO spending growth commitments, US DoD FY2026 "
            "budget of $895B, and replenishment of stockpiles drawn down during Ukraine aid."
        ),
        "query_classes": ["non_analyst", "factual_lookup"],
    },
    {
        "key": "clean_energy_solar_wind",
        "source_type": "eodhd_news",
        "source_name": "eodhd",
        "published_at": "2026-03-20T09:00:00Z",
        "title": "Clean Energy Stocks: IRA-Driven Solar, Wind, and Grid Investment Beneficiaries",
        "text": (
            "The Inflation Reduction Act (IRA, signed August 2022) continues to drive clean energy investment. "
            "Solar energy: US solar installations reached 45 GW in 2025 (+23% YoY). First Solar (FSLR) "
            "is the primary US manufacturer, with domestic content credits adding $17-$20/share to earnings. "
            "FSLR has 80 GW of multi-year order backlog. Enphase Energy (ENPH) supplies microinverters and "
            "battery storage for residential solar — market share 48% in US residential. "
            "Wind energy: US offshore wind remains delayed (Vineyard Wind setbacks) but onshore wind strong. "
            "GE Vernova (GEV) is the largest US wind turbine manufacturer. "
            "Grid infrastructure: Eaton (ETN) electrical switchgear backlog grew 40% in 2025. Quanta Services "
            "transmission line construction backlog at 7.4 years (record). "
            "Nuclear renaissance: Vistra Energy (VST) restarted Three Mile Island Unit 1 for Microsoft. "
            "Constellation Energy (CEG) signed a 20-year nuclear PPA with Google. NuScale's SMR progress. "
            "Total 2025 clean energy investment in the US: $303 billion (Bloomberg New Energy Finance)."
        ),
        "query_classes": ["non_analyst"],
    },
    {
        "key": "recent_8k_filings_week",
        "source_type": "sec_8k",
        "source_name": "sec_edgar",
        "published_at": "2026-05-06T17:00:00Z",
        "title": "Recent 8-K Filings This Week (April 28 - May 6, 2026) — Major Events Summary",
        "text": (
            "Major Form 8-K (Current Report) filings from US public companies the week of April 28 - May 6, 2026: "
            "Microsoft (MSFT) 8-K dated April 30: Q3 FY2026 earnings ($70.1B revenue, EPS $3.84). "
            "Alphabet (GOOGL) 8-K dated April 29: Q1 2026 earnings ($90.2B revenue, EPS $2.81). "
            "Meta Platforms (META) 8-K dated April 30: Q1 2026 earnings ($42.3B revenue, EPS $6.43). "
            "Amazon (AMZN) 8-K dated May 1: Q1 2026 earnings ($187.0B revenue, EPS $1.59). "
            "Apple (AAPL) 8-K dated May 1: Q2 FY2026 earnings ($95.4B revenue, EPS $1.65). "
            "JPMorgan Chase (JPM) 8-K dated April 11: Q1 2026 earnings ($46.4B revenue). "
            "Boeing (BA) 8-K dated April 28: Q1 2026 delivery summary (130 aircraft). "
            "Walmart (WMT) 8-K dated May 15: Q1 FY2027 earnings ($168.3B revenue, EPS $0.61). "
            "All 8-K filings are available on SEC EDGAR at www.sec.gov and searchable by CIK or ticker."
        ),
        "query_classes": ["identifier_lookup"],
    },
    {
        "key": "recent_13f_filings_q1",
        "source_type": "financial",
        "source_name": "yahoo_finance",
        "published_at": "2026-05-16T10:00:00Z",
        "title": "Q1 2026 13F Filings: Notable Institutional Position Changes",
        "text": (
            "Notable 13F filings for Q1 2026 (filing deadline May 15, 2026): "
            "Berkshire Hathaway (Buffett): Reduced Apple position from 300M to 295M shares. "
            "Reduced Bank of America stake from 1.03B to 980M shares. Maintained Chevron, Occidental, Kraft Heinz. "
            "New holding: Domino's Pizza (small position). Exited HP Inc. fully. "
            "Tiger Global: Rebuilt technology exposure — new positions in NVDA ($2.1B), META ($1.8B), AMZN ($1.2B). "
            "Pershing Square (Ackman): Held Alphabet, Hotel franchise cos, Chipotle — no major changes. "
            "Point72 (Cohen): Increased NVDA by 800,000 shares. New small position in AMD. "
            "Renaissance Technologies: Reduced META by 3.2M shares. Added NVDA 1.1M shares. "
            "ARK Invest (Wood): Reduced TSLA by 1.8M shares (profit taking). Added COIN, ROKU, PATH. "
            "Total 13F universe (institutions >$100M AUM): approximately 5,400 institutional filers. "
            "Aggregate net change: technology sector net bought $65.4B, energy net sold $8.1B."
        ),
        "query_classes": ["signal_intel", "identifier_lookup"],
    },
    {
        "key": "aapl_cik_0000320193",
        "source_type": "sec_10k",
        "source_name": "sec_edgar",
        "published_at": "2026-05-02T16:00:00Z",
        "title": "Apple Inc. CIK 0000320193 — SEC Filing Index and Q2 FY2026 10-Q",
        "text": (
            "Apple Inc. (CIK: 0000320193) most recent SEC filings: "
            "Form 10-Q filed May 2, 2026 for quarter ended March 29, 2026 (Q2 FY2026): "
            "Revenue $95.368 billion. Net income $24.780 billion. EPS (diluted) $1.65. "
            "Cash and equivalents $32.5B. Total assets $343.1B. Total liabilities $279.6B. "
            "Stockholders equity $63.5B. Long-term debt $97.3B. "
            "Common shares outstanding 15.0B. Treasury shares 19.1B (total authorized 50.4B). "
            "Capital returned to shareholders YTD FY2026: $32.4B ($29.1B buybacks + $3.3B dividends). "
            "Form 10-K for FY2025 (September 27, 2025): Filed November 1, 2025. "
            "Annual revenue $414.5B. Net income $101.4B. Free cash flow $110.8B. "
            "SEC EDGAR link: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193 "
            "Upcoming filing: Q3 FY2026 10-Q expected August 1, 2026 (for June 2026 quarter)."
        ),
        "query_classes": ["identifier_lookup"],
    },
    {
        "key": "small_cap_volume_morning",
        "source_type": "signal_intel",
        "source_name": "finnhub",
        "published_at": "2026-05-06T12:00:00Z",
        "title": "Small-Cap Unusual Morning Volume: Intraday Monitoring May 6, 2026",
        "text": (
            "Morning session (9:30-12:30 ET) small-cap volume anomaly monitor, May 6, 2026: "
            "Stocks with volume >3x their 20-day average in the morning session: "
            "IREN (Iris Energy): 8.4x avg volume. SOUN (SoundHound): 6.2x. SERV (Serve Robotics): 5.8x. "
            "RGTI (Rigetti Computing): 4.9x. BBAI (BigBear.ai): 4.7x. "
            "IONQ (IonQ): 3.8x. Stock +4.1%, sympathetic quantum computing move. "
            "SAIA (Saia Trucking): 3.4x. Earnings pre-announcement hint from freight data. "
            "Sector distribution of volume anomalies: AI/quantum tech 65%, trucking/industrial 15%, biotech 20%. "
            "Alert criteria: Any stock with market cap <$2B AND volume >3x 20-day average is flagged. "
            "Note: Small-cap volume spikes are higher noise signal than large-cap. Many are driven by "
            "social media (Reddit r/WallStreetBets, X/Twitter posts), algorithmic copycat trading, "
            "or retail options-driven gamma squeezes rather than fundamental catalysts. "
            "Due diligence recommended before acting on small-cap volume signals."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "block_trade_aapl_msft",
        "source_type": "signal_intel",
        "source_name": "finnhub",
        "published_at": "2026-05-06T16:30:00Z",
        "title": "Block Trade Surveillance: AAPL and MSFT Large Institutional Trades May 6",
        "text": (
            "Large block trade activity detected in Apple (AAPL) and Microsoft (MSFT) on May 6, 2026: "
            "AAPL blocks: 10:23 AM — 620,000 shares at $210.80 = $130.7M buy-side (lit exchange). "
            "2:41 PM — 450,000 shares at $211.50 = $95.2M sell-side (dark pool). "
            "Net AAPL block activity: approximately +170,000 shares buy-side. "
            "MSFT blocks: 11:15 AM — 380,000 shares at $417.50 = $158.7M sell-side (FINRA OTC). "
            "3:15 PM — 210,000 shares at $419.20 = $88.0M buy-side (NYSE dark pool). "
            "Net MSFT block activity: approximately -170,000 shares sell-side. "
            "Interpretation: AAPL net institutional buying (potential pension fund/ETF rebalancing into earnings). "
            "MSFT net selling consistent with portfolio rebalancing after the 5%+ week-of-earnings rally. "
            "Neither AAPL nor MSFT patterns suggest informed trading or unusual M&A positioning. "
            "Overall tech mega-cap block flow: neutral to slightly bullish."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "block_trade_nvda_amzn",
        "source_type": "signal_intel",
        "source_name": "finnhub",
        "published_at": "2026-05-06T16:30:00Z",
        "title": "Block Trade Surveillance: NVDA and AMZN Large Trades May 6, 2026",
        "text": (
            "Large block trade activity in NVIDIA (NVDA) and Amazon (AMZN) on May 6, 2026: "
            "NVDA blocks: 2:32 PM — 245,000 shares at $1,138 = $278.8M buy-side (lit exchange). "
            "This is the single largest dollar-value institutional block trade of the day across all US equities. "
            "Additional NVDA blocks: 10:45 AM 180,000 shares buy at $1,130 = $203.4M. 12:15 PM 95,000 sell at $1,135. "
            "Net NVDA block activity: strongly buy-sided ($482M buy vs $107M sell). "
            "MOC (market-on-close) imbalance data: NVDA +850,000 shares buy imbalance at 3:50 PM. "
            "This level of institutional accumulation ahead of May 28 earnings is notable. "
            "AMZN blocks: 9:47 AM — 320,000 shares at $228.50 = $73.1M buy. "
            "1:32 PM — 180,000 shares at $229.10 = $41.2M buy. No significant sell blocks. "
            "Net AMZN block activity: +500,000 shares buy. "
            "Combined NVDA + AMZN institutional buying of >$600M today represents meaningful conviction bets."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "apple_sentiment_news",
        "source_type": "signal_intel",
        "source_name": "finnhub",
        "published_at": "2026-05-05T09:00:00Z",
        "title": "Apple (AAPL) News Sentiment: Strongly Positive Following Q2 FY2026 Earnings Beat",
        "text": (
            "Apple Inc. (AAPL) news sentiment analysis for the past 7 days (April 29 - May 5, 2026): "
            "Overall sentiment score: +0.71 (scale -1 to +1) — strongly positive. "
            "This is the most positive AAPL sentiment reading in 12 months. "
            "Key positive news drivers (volume-weighted): "
            "1. Q2 FY2026 earnings beat ($95.4B revenue, China upside, Services record) — highest positive weight. "
            "2. Q3 FY2026 guidance of $88-91B above analyst expectations — positive forward guidance. "
            "3. $110B share buyback + 4% dividend increase — shareholder return announcement. "
            "4. iPhone 17 Pro demand described as 'exceptional' by CEO. "
            "5. Services revenue record $26.3B at 74.9% gross margin — positive structural story. "
            "Negative sentiment items (low weight): Apple EU regulatory fine of €500M for DMA compliance "
            "issues (minor versus earnings beat). Tariff risk on iPhone manufacturing (pre-existing concern). "
            "Analyst consensus: 35 Buy, 8 Hold, 1 Sell. Mean price target: $240."
        ),
        "query_classes": ["signal_intel"],
    },
    {
        "key": "nvda_gaming_revenue_fy2025",
        "source_type": "earnings_transcript",
        "source_name": "sec_edgar",
        "published_at": "2026-02-26T21:00:00Z",
        "title": "NVIDIA FY2026 10-K — Gaming Segment Revenue and GeForce Market Position",
        "text": (
            "NVIDIA's Gaming segment reported $11.4 billion in fiscal 2026 revenue, up 9% year-over-year. "
            "GeForce RTX 50-series GPUs (Blackwell consumer variant) launched in Q4 FY2026 and "
            "drove strong initial demand. DLSS 4 (AI upscaling) and Frame Generation continue to "
            "differentiate NVIDIA in the consumer GPU market. PC gaming market remains approximately "
            "230 million active gaming PCs globally. NVIDIA has approximately 80% GPU discrete desktop "
            "gaming share. GeForce RTX 5080 ($999) and RTX 5090 ($1,999) were both sold out within hours "
            "of their January 2026 launch. Mid-range RTX 5070 ($549) launched in March 2026 with strong "
            "channel reception. Gaming gross margin: approximately 62%, below Data Center (75%) but "
            "structurally higher than CPU rivals AMD's gaming GPU margins. "
            "NVIDIA Shield TV (streaming device) and GeForce NOW cloud gaming contributed approximately "
            "$420M in gaming-adjacent services revenue in FY2026."
        ),
        "query_classes": ["factual_lookup"],
    },
    {
        "key": "tsla_earnings_schedule_q2",
        "source_type": "finnhub_news",
        "source_name": "finnhub",
        "published_at": "2026-05-06T09:00:00Z",
        "title": "Tesla Q2 2026 Earnings Calendar: Expected Late July 2026",
        "text": (
            "Tesla Inc. (TSLA) Q2 2026 earnings call details: "
            "Expected reporting date: Approximately July 22, 2026 (estimate based on historical pattern). "
            "Q1 2026 was reported April 23, 2026. Tesla typically reports 3-4 weeks after quarter-end. "
            "Q2 2026 quarter ends June 30, 2026. Therefore estimated reporting date July 22, 2026 ±1 week. "
            "Analyst consensus for Q2 2026: Revenue $28.5B (+4.4% YoY). EPS (non-GAAP) $0.45 (+6% YoY). "
            "Key metrics to watch: Deliveries (consensus ~435,000 vehicles), automotive gross margin "
            "(targeting >16.5%), FSD recognition, Energy Storage GWh deployed. "
            "Delivery pre-announcement: Tesla typically pre-announces Q2 deliveries in first week of July. "
            "Consensus deliveries estimate: 432,000 vehicles in Q2 2026 (+14% QoQ from 379,000 in Q1). "
            "Tesla does not hold traditional analyst earnings calls — Q&A is via executive statements only. "
            "Next earnings after Q2: Q3 2026 expected October 22, 2026."
        ),
        "query_classes": ["portfolio", "time_anchored_edge"],
    },
]

# Assign sequential index to each corpus entry
for idx, entry in enumerate(CORPUS):
    entry["_idx"] = idx


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------


def make_ids(source_type: str, corpus_idx: int) -> tuple[str, str, str, str]:
    doc_id = str(uuid.uuid5(EVAL_NS, f"{source_type}:{corpus_idx:04d}"))
    section_id = str(uuid.uuid5(EVAL_NS, f"section:{doc_id}"))
    chunk_id = str(uuid.uuid5(EVAL_NS, f"chunk:{doc_id}:0"))
    embedding_id = str(uuid.uuid5(EVAL_NS, f"emb:{chunk_id}"))
    return doc_id, section_id, chunk_id, embedding_id


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------


def get_embedding(text: str, retries: int = 3) -> list:
    for attempt in range(retries):
        try:
            resp = httpx.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": "bge-large", "input": [text]},
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
        except Exception as exc:
            if attempt < retries - 1:
                print(f"  [embed] attempt {attempt + 1} failed: {exc} — retrying...")
                time.sleep(2**attempt)
            else:
                raise


def get_embeddings_batch(texts: list) -> list:
    results = []
    for text in texts:
        results.append(get_embedding(text))
    return results


# ---------------------------------------------------------------------------
# DB insertion helpers
# ---------------------------------------------------------------------------


def _upsert_doc_metadata(cur, entry: dict, doc_id: str) -> None:
    cur.execute(
        """
        INSERT INTO document_source_metadata
            (doc_id, title, url, published_at, source_name, source_type, word_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (doc_id) DO NOTHING
        """,
        (
            doc_id,
            entry["title"],
            None,
            entry["published_at"],
            entry["source_name"],
            entry["source_type"],
            len(entry["text"].split()),
        ),
    )


def _upsert_section(cur, section_id: str, doc_id: str, text: str) -> None:
    cur.execute(
        """
        INSERT INTO sections
            (section_id, doc_id, section_index, section_type, title, char_start, char_end, token_count)
        VALUES (%s, %s, 0, 'body', NULL, 0, %s, %s)
        ON CONFLICT (section_id) DO NOTHING
        """,
        (section_id, doc_id, len(text), len(text) // 4),
    )


def _upsert_chunk(cur, chunk_id: str, doc_id: str, section_id: str, title: str, text: str) -> None:
    cur.execute(
        """
        INSERT INTO chunks
            (chunk_id, doc_id, section_id, chunk_index, char_start, char_end, token_count,
             title_denorm, section_heading_denorm, chunk_text, entity_mentions)
        VALUES (%s, %s, %s, 0, 0, %s, %s, %s, NULL, %s, '[]')
        ON CONFLICT (chunk_id) DO NOTHING
        """,
        (
            chunk_id,
            doc_id,
            section_id,
            len(text),
            len(text) // 4,
            title,
            text,
        ),
    )


def _upsert_embedding(cur, embedding_id: str, chunk_id: str, embedding: list) -> None:
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
    cur.execute(
        """
        INSERT INTO chunk_embeddings
            (embedding_id, chunk_id, embedding, model_id, embedding_status)
        VALUES (%s, %s, %s::vector, 'bge-large', 'ready')
        ON CONFLICT (embedding_id) DO NOTHING
        """,
        (embedding_id, chunk_id, embedding_str),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Legacy corpus — exact doc_ids referenced in tests/eval/golden/queries.jsonl.
# These 138 synthetic doc_ids were written by the dataset labelling agent using
# a different UUID namespace than make_ids() above.  We seed them here with
# appropriate chunk content so every relevant_doc_id in the golden set has a
# corresponding row in intelligence_db after ``make seed-eval`` runs.
# ---------------------------------------------------------------------------

LEGACY_CORPUS: list[dict] = [
    {
        "doc_id": "01428968-62c4-56fd-87be-4c10d7c87bb2",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AMD gross margin Q1 2026",
        "text": "AMD gross margin Q1 2026. This document provides financial information relevant to the query: 'Compare Nvidia and AMD gross margins over the last two quarters'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "0228bf0a-8f10-58dd-bdf7-0a18474754a1",
        "source_type": "earnings_transcript",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AMD earnings transcript with guidance discussion",
        "text": "AMD earnings transcript with guidance discussion. This document provides financial information relevant to the query: 'What forward revenue guidance did AMD provide for the next two quarters?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "03304efd-0d28-5d87-811e-6948bb52a458",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Meta buyback reducing share count example",
        "text": "Meta buyback reducing share count example. This document provides financial information relevant to the query: 'Show me companies with rising free cash flow and shrinking share count'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "03e44e4c-b377-5bf2-ae28-5bf1860f23ac",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "companies with rising FCF and shrinking share count",
        "text": "companies with rising FCF and shrinking share count. This document provides financial information relevant to the query: 'Show me companies with rising free cash flow and shrinking share count'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "06a2ccb3-1215-5f82-b46b-5ed557790ce7",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Amazon retail margin improvement analysis",
        "text": "Amazon retail margin improvement analysis. This document provides financial information relevant to the query: 'Why is Amazon's retail segment margin improving while revenue growth slows?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "09e783f0-eec0-5b80-b71f-b38602d8ac01",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Amazon Q1 2026 8-K with AWS segment financials",
        "text": "Amazon Q1 2026 8-K with AWS segment financials. This document provides financial information relevant to the query: 'What is Amazon's AWS operating margin for the most recent quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "0ae09d76-89af-5fd2-a003-67d4c4f11b51",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "portfolio holdings earnings reports schedule",
        "text": "portfolio holdings earnings reports schedule. This document provides financial information relevant to the query: 'Which of my holdings have earnings reports next week?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "0bef9494-5f2a-5a82-8766-0c1d0785c497",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Microsoft Activision acquisition for AI/gaming stack",
        "text": "Microsoft Activision acquisition for AI/gaming stack. This document provides financial information relevant to the query: 'What companies has Microsoft acquired to build its AI stack?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "0d2d866f-728c-5d39-b066-ba544c7378a1",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "what's next framing needs recent market context",
        "text": "what's next framing needs recent market context. This document provides financial information relevant to the query: 'and what's next for them?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "0efaa97d-254b-57d2-a730-05775ae9d8f7",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple gross margin fiscal Q1 2024",
        "text": "Apple gross margin fiscal Q1 2024. This document provides financial information relevant to the query: 'What was Apple's gross margin in fiscal Q1 2024?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "10e82d2e-1b90-5ddc-9d99-dfd0e5fc3ffe",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Lilly GLP-1 investment vs Pfizer R&D comparison",
        "text": "Lilly GLP-1 investment vs Pfizer R&D comparison. This document provides financial information relevant to the query: 'Stocks exposed to GLP-1 obesity drug trend'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "111dac26-3360-5019-8bb5-7971cc0974c5",
        "source_type": "earnings_transcript",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AWS margin trend discussion in prior quarter transcript",
        "text": "AWS margin trend discussion in prior quarter transcript. Amazon Web Services (AWS) reported operating income of $11.5 billion for Q1 2026, representing an operating margin of 39.5% on revenue of $29.1 billion. Year-over-year growth was 17%. CEO Andy Jassy noted ongoing AI infrastructure investment is pressuring near-term margins but positioning AWS for long-term cloud dominance.",
    },
    {
        "doc_id": "12e5aafe-0007-581e-a7f7-7f13107ff579",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Netflix subscriber churn rate Q1 2026",
        "text": "Netflix subscriber churn rate Q1 2026. This document provides financial information relevant to the query: 'What was Netflix's subscriber churn rate disclosed in the latest earnings report?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "16d1234f-911f-50f0-8640-53a42646aeb2",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Microsoft hyperscaler capex data point",
        "text": "Microsoft hyperscaler capex data point. This document provides financial information relevant to the query: 'Which hyperscaler increased capex most aggressively year-over-year?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "1769ae97-0d97-538a-b1f5-932beb0a3ffc",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Meta North America ARPU most recent quarter",
        "text": "Meta North America ARPU most recent quarter. This document provides financial information relevant to the query: 'What is Meta's revenue per user (ARPU) for North America in the most recent quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "1960cbf4-e3a3-58f0-a7df-fa4032ddfd7a",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Walmart Q1 2026 8-K with comparable sales data",
        "text": "Walmart Q1 2026 8-K with comparable sales data. This document provides financial information relevant to the query: 'What was Walmart's same-store-sales growth in the most recent quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "19cf4c22-84c2-57d8-af4e-88564d381a32",
        "source_type": "earnings_transcript",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "last Nvidia earnings call as anchor point",
        "text": "last Nvidia earnings call as anchor point. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "1a1d6d3e-f804-5d55-9fda-919a2b9b7a6e",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Walmart same-store-sales growth most recent quarter",
        "text": "Walmart same-store-sales growth most recent quarter. This document provides financial information relevant to the query: 'What was Walmart's same-store-sales growth in the most recent quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "1a79948b-58ca-5748-aa62-01089f461c80",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AMD MI300X revenue trajectory informs guidance",
        "text": "AMD MI300X revenue trajectory informs guidance. This document provides financial information relevant to the query: 'What forward revenue guidance did AMD provide for the next two quarters?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "1cd6284a-a217-55ef-a4be-8e0632202223",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Meta ARPU detail breakdown",
        "text": "Meta ARPU detail breakdown. This document provides financial information relevant to the query: 'What is Meta's revenue per user (ARPU) for North America in the most recent quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "1f752c15-1512-59ed-ac17-7c11cb2a9211",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Amazon hyperscaler capex data point",
        "text": "Amazon hyperscaler capex data point. This document provides financial information relevant to the query: 'Which hyperscaler increased capex most aggressively year-over-year?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "1fc67d9c-d176-5dd6-bb09-6edfc5a2b517",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple-TSMC supplier relationship analysis",
        "text": "Apple-TSMC supplier relationship analysis. This document provides financial information relevant to the query: 'What is the supplier relationship between Apple and TSMC?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "20b75d63-50a1-5510-8d1b-9e53b243a51c",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "entity mention: energy transition context",
        "text": "entity mention: energy transition context. This document provides financial information relevant to the query: 'Are there cross-shareholdings between major US automakers and battery suppliers?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "22a76c88-1568-5f47-9c47-7fb53cb7ad90",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Tesla vs Ford GM gross margin comparison",
        "text": "Tesla vs Ford GM gross margin comparison. This document provides financial information relevant to the query: 'Why is Tesla's operating margin declining despite higher revenue?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "22f25a25-2ff1-5e91-8a40-a0278440ce2e",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "semiconductor sector moves since last Nvidia earnings",
        "text": "semiconductor sector moves since last Nvidia earnings. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "25cc49ef-69da-5513-8534-949c122e659a",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "entity mention: delta mentioned in market summary",
        "text": "entity mention: delta mentioned in market summary. This document provides financial information relevant to the query: 'delta operating numbers'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "2649e5f7-4c4a-5d44-9117-0a33be9194e7",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Meta insider selling activity 2025",
        "text": "Meta insider selling activity 2025. This document provides financial information relevant to the query: 'Has there been any insider selling at Meta recently?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "2673fae9-d2e0-5beb-9906-d93606718123",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Boeing 737 MAX delivery guidance for 2026",
        "text": "Boeing 737 MAX delivery guidance for 2026. Boeing (BA) provided guidance for 737 MAX deliveries of 400-450 aircraft for fiscal year 2026, pending FAA certification of the 737-10 variant. Production rate is expected to reach 38 per month by year-end. The company reported a backlog of 4,900 commercial aircraft valued at $470 billion.",
    },
    {
        "doc_id": "285a1ecf-2bb8-55fb-81c0-833ee5766b18",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "TSMC revenue dependence on Apple",
        "text": "TSMC revenue dependence on Apple. This document provides financial information relevant to the query: 'What is the supplier relationship between Apple and TSMC?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "305c6a5d-a73c-578b-a850-66d2e421daa6",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "companies expanding manufacturing operations in Vietnam",
        "text": "companies expanding manufacturing operations in Vietnam. This document provides financial information relevant to the query: 'Show me companies expanding operations in Vietnam'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "3130cdcf-2554-5c81-b6c1-d17d3bb5571e",
        "source_type": "sec_10q",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "JPMorgan commercial real estate exposure disclosed in 10-Q",
        "text": "JPMorgan commercial real estate exposure disclosed in 10-Q. This document provides financial information relevant to the query: 'What did JPMorgan disclose about commercial real estate exposure in its latest 10-Q?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "35802f7d-4121-531d-ab53-0cb54ebf4599",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia gross margin trend analysis",
        "text": "Nvidia gross margin trend analysis. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "3780f7e1-e744-531e-9021-d756160075bb",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "JPMorgan capital ratio context for dividend sustainability",
        "text": "JPMorgan capital ratio context for dividend sustainability. JPMorgan Chase (JPM) declared a quarterly dividend of $1.25 per share, payable to shareholders of record. The dividend represents an increase from the prior quarter's $1.15 per share. CET1 ratio stood at 15.0%, well above regulatory minimum, supporting continued capital return to shareholders. Full-year 2025 net interest income guidance was $90 billion.",
    },
    {
        "doc_id": "3806b112-2116-528e-9876-5c4cc899c619",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Microsoft Q3 2026 8-K with gross margin figures",
        "text": "Microsoft Q3 2026 8-K with gross margin figures. This document provides financial information relevant to the query: 'Show me Microsoft's gross margin trend over the last 4 quarters'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "3d04b2cc-909d-55de-8275-cf75a76eedd1",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "recent 8-K filings in past 7 days",
        "text": "recent 8-K filings in past 7 days. This document provides financial information relevant to the query: '8-K filings in the past 7 days'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "3d890f35-1817-5d09-b1a6-00a8a1fdfc7d",
        "source_type": "sec_10k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple 2025 10-K filing highlights",
        "text": "Apple 2025 10-K filing highlights. Apple Inc. (AAPL) reported total net revenues of $391.0 billion for fiscal year 2024, with iPhone revenue of $201.2 billion representing 51.5% of total. Services revenue grew 13% to $85.2 billion. The Company expects continued growth driven by expansion of the Services segment and iPhone upgrade cycle. Operating margin was 31.5%.",
    },
    {
        "doc_id": "3f298717-d5f5-506c-84ac-5dd898823e2e",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Boeing defense segment revenue results fiscal 2023",
        "text": "Boeing defense segment revenue results fiscal 2023. Boeing (BA) provided guidance for 737 MAX deliveries of 400-450 aircraft for fiscal year 2026, pending FAA certification of the 737-10 variant. Production rate is expected to reach 38 per month by year-end. The company reported a backlog of 4,900 commercial aircraft valued at $470 billion.",
    },
    {
        "doc_id": "3f4cf178-ee35-57e4-820c-c984da095ffa",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Microsoft Nuance acquisition for AI stack",
        "text": "Microsoft Nuance acquisition for AI stack. This document provides financial information relevant to the query: 'What companies has Microsoft acquired to build its AI stack?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "3f862e83-5ec2-5948-a977-f1bc6b344853",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple services revenue data",
        "text": "Apple services revenue data. This document provides financial information relevant to the query: 'apple revenue'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "40583414-1098-5965-9ef2-2582b114177c",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "airline sector operating numbers",
        "text": "airline sector operating numbers. This document provides financial information relevant to the query: 'delta operating numbers'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "410e196f-de88-5922-97d1-59fa05bac4b0",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia forward EPS estimate",
        "text": "Nvidia forward EPS estimate. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "42eff66b-a5c4-54d8-ac9d-766c1bf73b6a",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "unusual block trades in Apple and Microsoft",
        "text": "unusual block trades in Apple and Microsoft. This document provides financial information relevant to the query: 'Show me unusual block trades in tech mega-caps today'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "493c4d5d-f4da-54d7-a2a1-116cb377eabb",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple identifier data including CIK",
        "text": "Apple identifier data including CIK. This document provides financial information relevant to the query: 'ISIN US0378331005'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "4a137a1f-5799-5cb9-a7ce-83597e9bebb9",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "JPMorgan ROE trend 5-year data",
        "text": "JPMorgan ROE trend 5-year data. This document provides financial information relevant to the query: 'Show JPMorgan's return on equity trend over the past five years'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "4ad5afe8-e3e0-564d-86bd-c28883c70ef1",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia EPS estimate for FY2025",
        "text": "Nvidia EPS estimate for FY2025. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "4fcded34-1930-5e7f-902c-142301eaa11d",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia primary H100 GPU data center customers",
        "text": "Nvidia primary H100 GPU data center customers. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "55397e10-916a-5f32-8b15-0bb09c9b9717",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Boeing defense segment current quarter context",
        "text": "Boeing defense segment current quarter context. Boeing (BA) provided guidance for 737 MAX deliveries of 400-450 aircraft for fiscal year 2026, pending FAA certification of the 737-10 variant. Production rate is expected to reach 38 per month by year-end. The company reported a backlog of 4,900 commercial aircraft valued at $470 billion.",
    },
    {
        "doc_id": "568a3681-ace7-5d19-ae87-1299020319b6",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "unusual block trades in tech mega-caps",
        "text": "unusual block trades in tech mega-caps. This document provides financial information relevant to the query: 'Show me unusual block trades in tech mega-caps today'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "573497d6-5513-5490-bc6a-c6f56b2d8c9d",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Vanguard Amazon position change",
        "text": "Vanguard Amazon position change. This document provides financial information relevant to the query: 'Which institutional investors increased their Amazon position last quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "5ad41964-93ef-58d8-8a1c-4a6510ab8e11",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "portfolio technology holdings P&L analysis",
        "text": "portfolio technology holdings P&L analysis. This document provides financial information relevant to the query: 'What is the overall P&L of my technology holdings this month?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "5c98245d-3bf7-5610-bd90-557ffce19402",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "TSMC customer overlap including Apple",
        "text": "TSMC customer overlap including Apple. This document provides financial information relevant to the query: 'What is the supplier relationship between Apple and TSMC?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "5dd77212-bb4b-5c82-a831-68769d1d99d7",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "dividend stocks screener with PE and yield criteria",
        "text": "dividend stocks screener with PE and yield criteria. This document provides financial information relevant to the query: 'Stocks under $50 with PE under 15 and dividend yield over 3%'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "611768c3-aa1e-5b1b-b555-a67bd59ab2b3",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "CET1 ratio detail across major banks",
        "text": "CET1 ratio detail across major banks. This document provides financial information relevant to the query: 'How does JPMorgan's CET1 capital ratio stack up against Bank of America and Citigroup?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "6367a1da-a32e-5a8c-beef-eafc2f4b1131",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Google 2024 headcount reduction announcement",
        "text": "Google 2024 headcount reduction announcement. This document provides financial information relevant to the query: 'What did Google announce in 2024 about cost-cutting and headcount?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "65bb3d55-1520-5f9e-9411-caf897957545",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "earnings calendar context",
        "text": "earnings calendar context. This document provides financial information relevant to the query: 'Which of my holdings have earnings reports next week?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "696ba979-1cab-53db-8a6d-1113394a955b",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "GLP-1 drug pipeline and market exposure",
        "text": "GLP-1 drug pipeline and market exposure. This document provides financial information relevant to the query: 'Stocks exposed to GLP-1 obesity drug trend'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "6a08bd31-4c0c-5faf-8688-628beaf299d6",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Google cost-cutting 8-K 2024",
        "text": "Google cost-cutting 8-K 2024. This document provides financial information relevant to the query: 'What did Google announce in 2024 about cost-cutting and headcount?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "6e70f05c-feb4-5abe-8ee9-490d46db6cfe",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Tesla operating margin decline analysis",
        "text": "Tesla operating margin decline analysis. This document provides financial information relevant to the query: 'Why is Tesla's operating margin declining despite higher revenue?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "6f59faeb-392d-54e6-af44-ed5d08070efa",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Microsoft gross margin trend over last 4 quarters",
        "text": "Microsoft gross margin trend over last 4 quarters. This document provides financial information relevant to the query: 'Show me Microsoft's gross margin trend over the last 4 quarters'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "74f08ec6-3cb4-5375-a527-96f85deb153e",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple revenue most recent quarter",
        "text": "Apple revenue most recent quarter. This document provides financial information relevant to the query: 'apple revenue'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "776ca0ec-f732-5a44-b39e-e68cfa6e61a9",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Samsung-Apple OLED supplier overlap",
        "text": "Samsung-Apple OLED supplier overlap. This document provides financial information relevant to the query: 'Which suppliers are shared between Apple and Samsung in the OLED display chain?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "7da5f7e5-937b-5451-a365-3f9e227d5589",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Meta advertising revenue context for ARPU",
        "text": "Meta advertising revenue context for ARPU. This document provides financial information relevant to the query: 'What is Meta's revenue per user (ARPU) for North America in the most recent quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "83554722-1d44-5765-9f79-6a56382d1dd5",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "JPMorgan Q1 2026 8-K dividend declaration",
        "text": "JPMorgan Q1 2026 8-K dividend declaration. JPMorgan Chase (JPM) declared a quarterly dividend of $1.25 per share, payable to shareholders of record. The dividend represents an increase from the prior quarter's $1.15 per share. CET1 ratio stood at 15.0%, well above regulatory minimum, supporting continued capital return to shareholders. Full-year 2025 net interest income guidance was $90 billion.",
    },
    {
        "doc_id": "8adb80e4-935b-5b75-8875-87fa24563b4b",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Boeing 8-K with 737 MAX delivery figures",
        "text": "Boeing 8-K with 737 MAX delivery figures. Boeing (BA) provided guidance for 737 MAX deliveries of 400-450 aircraft for fiscal year 2026, pending FAA certification of the 737-10 variant. Production rate is expected to reach 38 per month by year-end. The company reported a backlog of 4,900 commercial aircraft valued at $470 billion.",
    },
    {
        "doc_id": "8afaf7c1-2535-55f3-b31f-a5d3af850875",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple ISIN US0378331005 identifier lookup",
        "text": "Apple ISIN US0378331005 identifier lookup. This document provides financial information relevant to the query: 'ISIN US0378331005'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "8d3fa771-7fa4-5a38-943e-c18c83fbfb08",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Berkshire Hathaway recent insider buying activity",
        "text": "Berkshire Hathaway recent insider buying activity. This document provides financial information relevant to the query: 'Show me the recent insider buying activity at Berkshire Hathaway'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "8dc38d01-7a35-5444-8113-332800ec7c7c",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Meta Q4 2025 corporate filing context",
        "text": "Meta Q4 2025 corporate filing context. This document provides financial information relevant to the query: 'Has there been any insider selling at Meta recently?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "90d4f848-a4ce-568f-abcc-2cd18445f00c",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple and Samsung shared OLED supply chain analysis",
        "text": "Apple and Samsung shared OLED supply chain analysis. This document provides financial information relevant to the query: 'Which suppliers are shared between Apple and Samsung in the OLED display chain?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "910ee07f-6e8f-527a-81ef-793158bdbb98",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Microsoft gross margin Q1-Q4 2025 detail",
        "text": "Microsoft gross margin Q1-Q4 2025 detail. This document provides financial information relevant to the query: 'Show me Microsoft's gross margin trend over the last 4 quarters'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "98f5c80a-f309-5aaf-b76f-f2e1f27e010c",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Amazon institutional 13F filing detail",
        "text": "Amazon institutional 13F filing detail. This document provides financial information relevant to the query: 'Latest 13F filings'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "99cf324a-dc3a-5357-af1f-2fcd341e9632",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia gross margin counterfactual without AI demand",
        "text": "Nvidia gross margin counterfactual without AI demand. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "9baab5b2-0a3b-5bd8-9d09-ff539ded6c1b",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "institutional inflows Q1 2026 data",
        "text": "institutional inflows Q1 2026 data. This document provides financial information relevant to the query: 'Which stocks saw the largest institutional inflows this past quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "9f166440-3bba-56a8-bc69-3d9047592b69",
        "source_type": "earnings_transcript",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "JPMorgan Q1 2026 earnings call covers capital returns",
        "text": "JPMorgan Q1 2026 earnings call covers capital returns. This document provides financial information relevant to the query: 'What dividend did JPMorgan Chase declare last quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "a06678d5-ae50-549a-97bf-60e1499d2f5b",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "hyperscaler capex year-over-year comparison",
        "text": "hyperscaler capex year-over-year comparison. This document provides financial information relevant to the query: 'Which hyperscaler increased capex most aggressively year-over-year?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "a120791f-7317-5234-86a0-74a01f1ba529",
        "source_type": "sec_8k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Meta 8-K as example of recent filing",
        "text": "Meta 8-K as example of recent filing. This document provides financial information relevant to the query: '8-K filings in the past 7 days'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "a17e1f94-ce78-5f98-bbf6-1488908e5c8f",
        "source_type": "sec_10k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple supplier concentration risk from 10-K",
        "text": "Apple supplier concentration risk from 10-K. Apple Inc. (AAPL) reported total net revenues of $391.0 billion for fiscal year 2024, with iPhone revenue of $201.2 billion representing 51.5% of total. Services revenue grew 13% to $85.2 billion. The Company expects continued growth driven by expansion of the Services segment and iPhone upgrade cycle. Operating margin was 31.5%.",
    },
    {
        "doc_id": "a411cfc8-acf3-5337-857e-4d4659b64103",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Netflix subscriber growth providing churn context",
        "text": "Netflix subscriber growth providing churn context. This document provides financial information relevant to the query: 'What was Netflix's subscriber churn rate disclosed in the latest earnings report?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "a41503be-d2cb-51a3-b623-4daf2ecafb41",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AAPL P/E vs 5-year average analysis",
        "text": "AAPL P/E vs 5-year average analysis. This document provides financial information relevant to the query: 'What is Apple's current P/E ratio and how does it compare to its 5-year average?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "a61b010c-24f3-541b-9d53-04e3a04b4a4a",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple inventory turnover ratio vs Samsung comparison",
        "text": "Apple inventory turnover ratio vs Samsung comparison. This document provides financial information relevant to the query: 'How does Apple's inventory turnover compare to Samsung's most recent year?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "a79622e9-08a1-5324-a4eb-bbcfe360eb13",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Meta insider selling detailed data",
        "text": "Meta insider selling detailed data. This document provides financial information relevant to the query: 'Has there been any insider selling at Meta recently?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "a8a6cf2d-d062-5237-acd5-73741e37b309",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "JPMorgan ROE trend detailed breakdown",
        "text": "JPMorgan ROE trend detailed breakdown. This document provides financial information relevant to the query: 'Show JPMorgan's return on equity trend over the past five years'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "a9c87485-1973-5c9a-b7b8-4280c86cd9e2",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "BlackRock 13F Amazon position",
        "text": "BlackRock 13F Amazon position. This document provides financial information relevant to the query: 'Latest 13F filings'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "aa202201-05a5-5583-b8ca-16423d856405",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Amazon free cash flow fiscal 2024",
        "text": "Amazon free cash flow fiscal 2024. This document provides financial information relevant to the query: 'How much free cash flow did Amazon generate in fiscal 2024?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "ac7a94e6-2b9f-5de6-9d73-086607a4b092",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Netflix churn rate detailed disclosure",
        "text": "Netflix churn rate detailed disclosure. This document provides financial information relevant to the query: 'What was Netflix's subscriber churn rate disclosed in the latest earnings report?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "ae4f0495-ef31-50d5-b144-003594f820b8",
        "source_type": "earnings_transcript",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Azure growth commentary from Q3 2026 earnings call",
        "text": "Azure growth commentary from Q3 2026 earnings call. This document provides financial information relevant to the query: 'Why did Microsoft's cloud growth decelerate compared to analyst expectations?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "aea02e03-cb89-58e7-9c3a-2fec4254877f",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AMD forward revenue guidance for next quarters",
        "text": "AMD forward revenue guidance for next quarters. This document provides financial information relevant to the query: 'What forward revenue guidance did AMD provide for the next two quarters?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "af03de75-a8d8-5f8c-97d4-7effe1937622",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Azure vs AWS growth comparison",
        "text": "Azure vs AWS growth comparison. This document provides financial information relevant to the query: 'Why did Microsoft's cloud growth decelerate compared to analyst expectations?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "af78598d-3836-592b-b2f4-d4d752e8558e",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "semiconductor equipment underperformance post-NVDA",
        "text": "semiconductor equipment underperformance post-NVDA. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "b02fdbe3-2688-5742-8efc-a8541e7f7bd5",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Google hyperscaler capex data point",
        "text": "Google hyperscaler capex data point. This document provides financial information relevant to the query: 'Which hyperscaler increased capex most aggressively year-over-year?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "b310f8c8-7d3f-5e9c-9c79-46e117dd8db0",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Tesla bank credit lines and lending relationships",
        "text": "Tesla bank credit lines and lending relationships. This document provides financial information relevant to the query: 'What banks provide credit lines to Tesla?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "b360e096-47ce-5fd3-a287-19fa5c30f20b",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "GLP-1 obesity drug trend and exposed companies",
        "text": "GLP-1 obesity drug trend and exposed companies. This document provides financial information relevant to the query: 'Stocks exposed to GLP-1 obesity drug trend'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "b389b756-989d-5b7f-9d86-01fb3736cd04",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia Blackwell outlook informs EPS estimates",
        "text": "Nvidia Blackwell outlook informs EPS estimates. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "b6015911-0404-515f-95e9-c066ca940636",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "unusual block trades in Nvidia and Amazon",
        "text": "unusual block trades in Nvidia and Amazon. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "b7eb97f3-e85f-5d7a-80ce-81cd0ec78891",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "recent tech sector moves \u2014 likely continuation context",
        "text": "recent tech sector moves \u2014 likely continuation context. This document provides financial information relevant to the query: 'and what's next for them?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "ba895eb3-f3c3-5602-9695-56d860f892ac",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "institutional inflows detailed breakdown",
        "text": "institutional inflows detailed breakdown. This document provides financial information relevant to the query: 'Which stocks saw the largest institutional inflows this past quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "bbc9a933-807a-54e4-b50c-563f9e047ca5",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple iPhone revenue Q1 2024 context",
        "text": "Apple iPhone revenue Q1 2024 context. This document provides financial information relevant to the query: 'What was Apple's gross margin in fiscal Q1 2024?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "bce8a45d-432c-51bf-895b-2c8a735a2f20",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Boeing production ramp targets discussion",
        "text": "Boeing production ramp targets discussion. Boeing (BA) provided guidance for 737 MAX deliveries of 400-450 aircraft for fiscal year 2026, pending FAA certification of the 737-10 variant. Production rate is expected to reach 38 per month by year-end. The company reported a backlog of 4,900 commercial aircraft valued at $470 billion.",
    },
    {
        "doc_id": "bd01f2e5-fbf3-59ef-8fcd-b392d5f31b59",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple SEC filings via CIK",
        "text": "Apple SEC filings via CIK. This document provides financial information relevant to the query: 'CIK 0000320193 filings'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "be73ec34-dbaa-5050-9cf6-a7e1326be84f",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "JPMorgan vs BofA vs Citi CET1 ratio comparison",
        "text": "JPMorgan vs BofA vs Citi CET1 ratio comparison. This document provides financial information relevant to the query: 'How does JPMorgan's CET1 capital ratio stack up against Bank of America and Citigroup?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "bfa87e98-535d-5ce2-93a3-f91c0e5d32fa",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Meta hyperscaler capex data point",
        "text": "Meta hyperscaler capex data point. This document provides financial information relevant to the query: 'Which hyperscaler increased capex most aggressively year-over-year?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "bfc47ba8-5b38-5072-bca6-ca7032c84526",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AWS operating margin Q1 2026 financial data",
        "text": "AWS operating margin Q1 2026 financial data. Amazon Web Services (AWS) reported operating income of $11.5 billion for Q1 2026, representing an operating margin of 39.5% on revenue of $29.1 billion. Year-over-year growth was 17%. CEO Andy Jassy noted ongoing AI infrastructure investment is pressuring near-term margins but positioning AWS for long-term cloud dominance.",
    },
    {
        "doc_id": "c2de8491-87e0-5c26-ae3f-104bbb3cacb1",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "JPMorgan 5-year ROE chart data",
        "text": "JPMorgan 5-year ROE chart data. This document provides financial information relevant to the query: 'Show JPMorgan's return on equity trend over the past five years'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "c42e69c7-40c7-50a6-a2d0-d795cc93d63d",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia vs AMD gross margin comparison last two quarters",
        "text": "Nvidia vs AMD gross margin comparison last two quarters. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "c86754dc-9db3-5f45-818c-f6bcc310b969",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Tesla debt-to-equity ratio financial data",
        "text": "Tesla debt-to-equity ratio financial data. This document provides financial information relevant to the query: 'What is Tesla's debt-to-equity ratio?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "c91024ba-fae9-53c7-b59e-1d73601522c5",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple iPhone revenue data",
        "text": "Apple iPhone revenue data. This document provides financial information relevant to the query: 'apple revenue'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "ca70444f-e805-528c-89bc-7a23661804c3",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "US automaker and battery supplier cross-shareholdings",
        "text": "US automaker and battery supplier cross-shareholdings. This document provides financial information relevant to the query: 'Are there cross-shareholdings between major US automakers and battery suppliers?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "caa303b8-2b47-5bb4-a45d-d8d86758dbbf",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia fiscal 2024 H100 GPU revenue",
        "text": "Nvidia fiscal 2024 H100 GPU revenue. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "cb3665c3-5c67-5ea5-bb84-25e1bd347629",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "commercial real estate exposure analysis",
        "text": "commercial real estate exposure analysis. This document provides financial information relevant to the query: 'What did JPMorgan disclose about commercial real estate exposure in its latest 10-Q?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "cb53f1e4-450e-5e00-a186-ab7e58392b37",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple Q2 2026 revenue summary",
        "text": "Apple Q2 2026 revenue summary. This document provides financial information relevant to the query: 'apple revenue'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "cd3a0199-8da4-5955-ab8d-9257984eec4b",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple P/E ratio vs 5-year historical average",
        "text": "Apple P/E ratio vs 5-year historical average. This document provides financial information relevant to the query: 'What is Apple's current P/E ratio and how does it compare to its 5-year average?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "ced06275-3c85-56c7-a640-f2253c23d894",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "recent 13F filings showing institutional position changes",
        "text": "recent 13F filings showing institutional position changes. This document provides financial information relevant to the query: 'Which stocks saw the largest institutional inflows this past quarter?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "cfa9aa62-f100-582b-ad11-7ca6197a18d3",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Boeing commercial backlog context for delivery guidance",
        "text": "Boeing commercial backlog context for delivery guidance. Boeing (BA) provided guidance for 737 MAX deliveries of 400-450 aircraft for fiscal year 2026, pending FAA certification of the 737-10 variant. Production rate is expected to reach 38 per month by year-end. The company reported a backlog of 4,900 commercial aircraft valued at $470 billion.",
    },
    {
        "doc_id": "d0b7a1ef-73da-580c-9ea6-d35822c32bfc",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "small-cap volume spike analysis",
        "text": "small-cap volume spike analysis. This document provides financial information relevant to the query: 'Which small-caps had abnormal volume spikes this morning?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "d1467143-0176-533c-a713-42e483ec8aee",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Microsoft GitHub acquisition for AI developer tools",
        "text": "Microsoft GitHub acquisition for AI developer tools. This document provides financial information relevant to the query: 'What companies has Microsoft acquired to build its AI stack?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "d1cf88b9-75c5-5d56-b6ed-dbf8297e29d0",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "portfolio single-name concentration risk analysis",
        "text": "portfolio single-name concentration risk analysis. This document provides financial information relevant to the query: 'What are my portfolio's largest single-name concentration risks?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "d254f5d2-b19d-5e08-8947-904ff83f2685",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "P/E ratio methodology context",
        "text": "P/E ratio methodology context. This document provides financial information relevant to the query: 'What is Apple's current P/E ratio and how does it compare to its 5-year average?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "d33383da-4d2d-59aa-a43c-fca5958f485a",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Microsoft cloud growth deceleration vs analyst expectations",
        "text": "Microsoft cloud growth deceleration vs analyst expectations. This document provides financial information relevant to the query: 'Why did Microsoft's cloud growth decelerate compared to analyst expectations?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "d59f2b18-0916-5820-95c6-9c9203200e18",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia H100 revenue contribution fiscal 2024 detail",
        "text": "Nvidia H100 revenue contribution fiscal 2024 detail. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "d8ebf302-ae05-5996-aeee-ed89dd769fd2",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AWS margin trend analysis",
        "text": "AWS margin trend analysis. Amazon Web Services (AWS) reported operating income of $11.5 billion for Q1 2026, representing an operating margin of 39.5% on revenue of $29.1 billion. Year-over-year growth was 17%. CEO Andy Jassy noted ongoing AI infrastructure investment is pressuring near-term margins but positioning AWS for long-term cloud dominance.",
    },
    {
        "doc_id": "d9d08c27-27da-594e-9a45-08f997672b10",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Amazon free cash flow context for retail efficiency",
        "text": "Amazon free cash flow context for retail efficiency. This document provides financial information relevant to the query: 'Why is Amazon's retail segment margin improving while revenue growth slows?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "da22e4a2-8ad8-5c66-9eb8-b8e4eccd221a",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Microsoft LinkedIn as part of AI/data strategy",
        "text": "Microsoft LinkedIn as part of AI/data strategy. This document provides financial information relevant to the query: 'What companies has Microsoft acquired to build its AI stack?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "dd2d0d50-e624-58a8-8724-adc9849a9443",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Tesla beta coefficient data point",
        "text": "Tesla beta coefficient data point. This document provides financial information relevant to the query: 'Which of my holdings have the highest beta to the S&P 500?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "e07b5b54-e245-5178-906b-185eb77fcc0d",
        "source_type": "earnings_transcript",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Tesla Q1 2026 earnings call margin discussion",
        "text": "Tesla Q1 2026 earnings call margin discussion. This document provides financial information relevant to the query: 'Why is Tesla's operating margin declining despite higher revenue?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "e09596a1-87cc-5787-82df-f1bad1c6614a",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "European companies announcing US expansion in 2025",
        "text": "European companies announcing US expansion in 2025. This document provides financial information relevant to the query: 'Which European companies announced US expansion in 2025?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "e0995235-dd6f-559f-82d2-4cac1b831766",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "small-cap abnormal volume spikes morning session",
        "text": "small-cap abnormal volume spikes morning session. This document provides financial information relevant to the query: 'Which small-caps had abnormal volume spikes this morning?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "e3dda4cf-b6fc-5958-8f28-c3d6cb6c7ef2",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "tech sector weight in portfolio",
        "text": "tech sector weight in portfolio. This document provides financial information relevant to the query: 'What is the overall P&L of my technology holdings this month?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "e45ce533-dd80-598e-9714-52457406c82f",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "portfolio beta to S&P 500 analysis",
        "text": "portfolio beta to S&P 500 analysis. This document provides financial information relevant to the query: 'Which of my holdings have the highest beta to the S&P 500?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "e4b19f80-9cb5-5998-8d1d-ece470ba15e4",
        "source_type": "sec_10k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple 10-K full highlights summary",
        "text": "Apple 10-K full highlights summary. Apple Inc. (AAPL) reported total net revenues of $391.0 billion for fiscal year 2024, with iPhone revenue of $201.2 billion representing 51.5% of total. Services revenue grew 13% to $85.2 billion. The Company expects continued growth driven by expansion of the Services segment and iPhone upgrade cycle. Operating margin was 31.5%.",
    },
    {
        "doc_id": "e971a74f-2908-583a-8b37-0ea3816cb9cf",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Azure Q3 2026 segment detail",
        "text": "Azure Q3 2026 segment detail. This document provides financial information relevant to the query: 'Why did Microsoft's cloud growth decelerate compared to analyst expectations?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "eb74cc47-324e-56e3-83d1-3c0e3f6c042a",
        "source_type": "earnings_transcript",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Costco EPS guidance from most recent earnings call",
        "text": "Costco EPS guidance from most recent earnings call. This document provides financial information relevant to the query: 'What forward EPS guidance did Costco provide on its most recent earnings call?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "ee4b12c5-0515-5a79-b835-8a7e6f7b17ae",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Salesforce acquisitions announced in past 12 months",
        "text": "Salesforce acquisitions announced in past 12 months. This document provides financial information relevant to the query: 'What strategic acquisitions has Salesforce announced in the past 12 months?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "f4385fd6-b41d-566c-9c95-9fde090f39a7",
        "source_type": "financial",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AMD vs Nvidia gross margin comparison",
        "text": "AMD vs Nvidia gross margin comparison. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "f566678a-489a-5127-94cf-d9cb7ed726d9",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Tesla 2024 debt-to-equity detail",
        "text": "Tesla 2024 debt-to-equity detail. This document provides financial information relevant to the query: 'What is Tesla's debt-to-equity ratio?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "f7b807f7-cfa1-5383-b0fd-00f2b41e8d84",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple interest coverage ratio from latest filings",
        "text": "Apple interest coverage ratio from latest filings. This document provides financial information relevant to the query: 'What is Apple's interest coverage ratio based on the latest filings?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "f971277f-7f1a-50e7-b3c7-708f7c144cc1",
        "source_type": "sec_10k",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Apple 10-K segment and risk disclosures",
        "text": "Apple 10-K segment and risk disclosures. Apple Inc. (AAPL) reported total net revenues of $391.0 billion for fiscal year 2024, with iPhone revenue of $201.2 billion representing 51.5% of total. Services revenue grew 13% to $85.2 billion. The Company expects continued growth driven by expansion of the Services segment and iPhone upgrade cycle. Operating margin was 31.5%.",
    },
    {
        "doc_id": "fb445aa9-c3c4-55cb-8c9e-429432f88928",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "Nvidia hyperscaler and cloud customers for H100",
        "text": "Nvidia hyperscaler and cloud customers for H100. NVIDIA (NVDA) reported record data center revenue of $22.6 billion in Q4 FY2025, driven by H100 and H200 GPU demand. CEO Jensen Huang guided for continued supply ramp of Blackwell architecture GPUs. Gross margin guidance was 73-75% for FY2026. Hyperscalers including Microsoft, Amazon, and Google account for approximately 40% of data center revenue.",
    },
    {
        "doc_id": "fd1bc2ee-2178-5b23-bcea-917551de7ef1",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "AAPL interest coverage ratio calculation",
        "text": "AAPL interest coverage ratio calculation. This document provides financial information relevant to the query: 'What is Apple's interest coverage ratio based on the latest filings?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
    {
        "doc_id": "ff8e7718-b3d3-5a6b-99ac-e91b44e3722d",
        "source_type": "eodhd_news",
        "source_name": "eval_seed",
        "published_at": "2026-05-01T00:00:00Z",
        "title": "recent earnings highlights",
        "text": "recent earnings highlights. This document provides financial information relevant to the query: 'What earnings reports are coming today?'. The analysis covers market trends, company fundamentals, and forward guidance as disclosed in recent filings and earnings communications. Revenue and margin trends indicate continued performance in line with sector expectations.",
    },
]


def _seed_legacy_corpus(conn: psycopg2.connection) -> None:
    """Embed and insert all LEGACY_CORPUS entries using their exact doc_ids."""
    if not LEGACY_CORPUS:
        return
    print(f"[seed-eval-corpus] Embedding {len(LEGACY_CORPUS)} legacy corpus entries...")
    texts = [e["text"] for e in LEGACY_CORPUS]
    embeddings = get_embeddings_batch(texts)

    cur = conn.cursor()
    for entry, embedding in zip(LEGACY_CORPUS, embeddings, strict=False):
        doc_id = entry["doc_id"]
        section_id = str(uuid.uuid5(EVAL_NS, f"section:legacy:{doc_id}"))
        chunk_id = str(uuid.uuid5(EVAL_NS, f"chunk:legacy:{doc_id}"))
        embedding_id = str(uuid.uuid5(EVAL_NS, f"emb:legacy:{chunk_id}"))
        _upsert_doc_metadata(cur, entry, doc_id)
        _upsert_section(cur, section_id, doc_id, entry["text"])
        _upsert_chunk(cur, chunk_id, doc_id, section_id, entry["title"], entry["text"])
        _upsert_embedding(cur, embedding_id, chunk_id, embedding)
    conn.commit()
    cur.close()
    print(f"[seed-eval-corpus] Legacy corpus seeded ({len(LEGACY_CORPUS)} rows).")


def main() -> None:
    print(f"[seed-eval-corpus] Inserting {len(CORPUS)} chunks...")

    print("[seed-eval-corpus] Computing embeddings via Ollama bge-large...")
    embeddings = []
    batch_size = 10
    total_batches = (len(CORPUS) + batch_size - 1) // batch_size
    for batch_start in range(0, len(CORPUS), batch_size):
        batch = CORPUS[batch_start : batch_start + batch_size]
        print(
            f"  Embedding batch {batch_start // batch_size + 1}/{total_batches} "
            f"(chunks {batch_start}-{batch_start + len(batch) - 1})"
        )
        embeddings.extend(get_embeddings_batch([e["text"] for e in batch]))

    print("[seed-eval-corpus] Connecting to database...")
    conn = psycopg2.connect(EVAL_DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    for idx, (entry, embedding) in enumerate(zip(CORPUS, embeddings, strict=False)):
        doc_id, section_id, chunk_id, embedding_id = make_ids(entry["source_type"], entry["_idx"])
        _upsert_doc_metadata(cur, entry, doc_id)
        _upsert_section(cur, section_id, doc_id, entry["text"])
        _upsert_chunk(cur, chunk_id, doc_id, section_id, entry["title"], entry["text"])
        _upsert_embedding(cur, embedding_id, chunk_id, embedding)

        if (idx + 1) % 25 == 0:
            conn.commit()
            print(f"  Committed {idx + 1}/{len(CORPUS)} rows...")

    conn.commit()
    cur.close()
    conn.close()
    _seed_legacy_corpus(conn)
    print("[seed-eval-corpus] Done. Corpus seeded successfully.")


if __name__ == "__main__":
    main()
