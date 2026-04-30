"""Bootstrap canonical entities for the 7 NER classes that previously had ZERO seeds.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-30

PLAN-0057 Wave A-3 — closes audit finding F-CRIT-10.

Background: ``canonical_entities`` had only 5 entity_types seeded
(financial_instrument, industry_group, sector, technology_theme, industry =
83 rows total). The other 7 GLiNER classes — currency, regulatory_body,
government_body, person, financial_institution, location, commodity,
macroeconomic_indicator, index — had **zero** rows, so NER mentions for those
classes failed to resolve at any cascade stage. Audit measured
0% resolution for currency / regulatory_body / government_body, 0.4% for
person, 0.1% for location.

This migration seeds ~224 canonical entities across 9 classes:
  *  33 currencies          (ISO-4217 majors + 3 crypto)
  *  25 regulatory bodies   (SEC, FCA, ECB, Fed, FOMC, FINRA, ...)
  *  25 government bodies   (US Treasury, US Senate, EU Commission, ...)
  *  30 indices             (S&P 500, NASDAQ, FTSE 100, Nikkei 225, ...)
  *  25 commodities         (Crude Oil/WTI, Brent, Gold, Wheat, ...)
  *  30 macro indicators    (CPI, NFP, GDP, Fed Funds Rate, ...)
  *  30 locations           (US, China, Japan, Germany, UK, ...)
  *  20 persons             (top central bankers + finance figures)
  *   6 financial institutions (non-listed only — Vanguard, Fidelity,
                                Bridgewater, BlackRock-asset-mgr, Brookfield,
                                Apollo — to avoid duplication with the 40
                                publicly-listed financial_instrument seeds)

Each canonical gets:
  - canonical_entities row with metadata.description (1-2 sentence factual blurb)
    + metadata.seed_source = 'F-CRIT-10' for clean rollback discrimination
  - 2-3 entity_aliases rows: EXACT (full name) + EXACT (short code/abbrev) +
    optional SYMBOL (for currency $/€/¥ — though common ones are skipped
    because they are too ambiguous to match to a single entity)
  - 2 entity_embedding_state rows (definition + narrative); financial_instrument
    overlap absent here because we don't seed listed instruments, so no
    fundamentals_ohlcv view rows. ``next_refresh_at = now()`` makes the rows
    immediately due for DefinitionRefreshWorker / NarrativeRefreshWorker on
    next cycle.

Idempotent: ON CONFLICT (entity_id) DO NOTHING on canonical_entities; the new
``uidx_entity_aliases_entity_norm_type`` UNIQUE INDEX (Wave A-2) handles alias
de-dup; entity_embedding_state composite PK handles view-row de-dup.

Stable UUIDv7-shaped IDs: ``0195daad-<prefix>-<counter>-8YYY-XXXXXXXXXXXX``
with prefix per class (c001..c009) and counter incrementing per row. Mirrors
the namespace pattern of seeds/003 (a*** for sectors, b*** for industry_groups).
"""

from __future__ import annotations

import json

from alembic import op

revision: str = "0009"
down_revision: str = "0008"
branch_labels = None
depends_on = None


# ── Seed data ──────────────────────────────────────────────────────────────────


# Currencies: (code, full_name, region) — ISO-4217 majors + 3 crypto.
# Symbol aliases are intentionally OMITTED for ambiguous symbols ($/€/¥/£).
_CURRENCIES = [
    ("USD", "US Dollar", "United States"),
    ("EUR", "Euro", "Eurozone"),
    ("GBP", "Pound Sterling", "United Kingdom"),
    ("JPY", "Japanese Yen", "Japan"),
    ("CHF", "Swiss Franc", "Switzerland"),
    ("CAD", "Canadian Dollar", "Canada"),
    ("AUD", "Australian Dollar", "Australia"),
    ("NZD", "New Zealand Dollar", "New Zealand"),
    ("CNY", "Chinese Yuan Renminbi", "China"),
    ("HKD", "Hong Kong Dollar", "Hong Kong"),
    ("SGD", "Singapore Dollar", "Singapore"),
    ("INR", "Indian Rupee", "India"),
    ("KRW", "South Korean Won", "South Korea"),
    ("BRL", "Brazilian Real", "Brazil"),
    ("MXN", "Mexican Peso", "Mexico"),
    ("RUB", "Russian Ruble", "Russia"),
    ("ZAR", "South African Rand", "South Africa"),
    ("TRY", "Turkish Lira", "Turkey"),
    ("SEK", "Swedish Krona", "Sweden"),
    ("NOK", "Norwegian Krone", "Norway"),
    ("DKK", "Danish Krone", "Denmark"),
    ("PLN", "Polish Zloty", "Poland"),
    ("CZK", "Czech Koruna", "Czech Republic"),
    ("HUF", "Hungarian Forint", "Hungary"),
    ("ILS", "Israeli New Shekel", "Israel"),
    ("AED", "UAE Dirham", "United Arab Emirates"),
    ("SAR", "Saudi Riyal", "Saudi Arabia"),
    ("THB", "Thai Baht", "Thailand"),
    ("IDR", "Indonesian Rupiah", "Indonesia"),
    ("MYR", "Malaysian Ringgit", "Malaysia"),
    ("BTC", "Bitcoin", "(cryptocurrency)"),
    ("ETH", "Ethereum", "(cryptocurrency)"),
    ("USDT", "Tether", "(cryptocurrency)"),
]

# Regulatory bodies: (abbrev, full_name, description).
_REGULATORY_BODIES = [
    (
        "SEC",
        "U.S. Securities and Exchange Commission",
        "U.S. federal agency overseeing securities markets, investor protection, and corporate disclosure.",
    ),
    (
        "FCA",
        "Financial Conduct Authority",
        "United Kingdom regulator overseeing financial firms and markets to maintain integrity and consumer protection.",
    ),
    (
        "ECB",
        "European Central Bank",
        "Central bank of the Eurozone; sets monetary policy for the euro and supervises major banks.",
    ),
    (
        "BoE",
        "Bank of England",
        "Central bank of the United Kingdom; responsible for monetary policy and financial stability.",
    ),
    ("BoJ", "Bank of Japan", "Central bank of Japan; sets monetary policy and conducts foreign-exchange operations."),
    (
        "PBoC",
        "People's Bank of China",
        "Central bank of the People's Republic of China; sets monetary policy and manages the renminbi.",
    ),
    (
        "RBI",
        "Reserve Bank of India",
        "Central bank of India; regulator of banking, currency issuance, and monetary policy.",
    ),
    (
        "Federal Reserve",
        "Federal Reserve System",
        "Central banking system of the United States; sets U.S. monetary policy and supervises banks.",
    ),
    (
        "FOMC",
        "Federal Open Market Committee",
        "Monetary-policy committee of the U.S. Federal Reserve; sets the federal funds target rate.",
    ),
    (
        "FINRA",
        "Financial Industry Regulatory Authority",
        "Self-regulatory organization overseeing U.S. brokerage firms and registered representatives.",
    ),
    (
        "CFTC",
        "Commodity Futures Trading Commission",
        "U.S. federal regulator of futures, options, and derivatives markets.",
    ),
    (
        "SEBI",
        "Securities and Exchange Board of India",
        "Indian capital-markets regulator overseeing securities, intermediaries, and investor protection.",
    ),
    (
        "BaFin",
        "Federal Financial Supervisory Authority",
        "Germany's integrated financial-services regulator overseeing banks, insurers, and securities.",
    ),
    (
        "ESMA",
        "European Securities and Markets Authority",
        "EU-level regulator coordinating securities-markets supervision across member states.",
    ),
    (
        "AMF",
        "Autorité des marchés financiers",
        "France's securities-markets regulator overseeing listed companies, intermediaries, and asset managers.",
    ),
    ("FDIC", "Federal Deposit Insurance Corporation", "U.S. agency providing deposit insurance and bank supervision."),
    (
        "OCC",
        "Office of the Comptroller of the Currency",
        "U.S. federal regulator chartering and supervising national banks and federal savings associations.",
    ),
    (
        "IMF",
        "International Monetary Fund",
        "Multilateral institution promoting monetary cooperation, exchange-rate stability, and lending to member countries.",
    ),
    (
        "World Bank",
        "World Bank Group",
        "Multilateral development bank providing loans and grants to low- and middle-income countries.",
    ),
    (
        "BIS",
        "Bank for International Settlements",
        "International institution serving central banks; promotes monetary and financial cooperation.",
    ),
    (
        "IOSCO",
        "International Organization of Securities Commissions",
        "Global standard-setter for securities regulation, coordinating national regulators.",
    ),
    ("SNB", "Swiss National Bank", "Central bank of Switzerland; sets monetary policy and manages the franc."),
    (
        "RBA",
        "Reserve Bank of Australia",
        "Central bank of Australia; responsible for monetary policy and currency issuance.",
    ),
    ("BoC", "Bank of Canada", "Central bank of Canada; sets monetary policy and issues currency."),
    (
        "ESM",
        "European Stability Mechanism",
        "Eurozone permanent crisis-resolution mechanism providing financial assistance to member states.",
    ),
]

# Government bodies: (short_name, full_name, description).
_GOVERNMENT_BODIES = [
    (
        "US Treasury",
        "United States Department of the Treasury",
        "U.S. federal department managing government finances, public debt, and tax policy.",
    ),
    (
        "US Congress",
        "United States Congress",
        "Bicameral legislature of the U.S. federal government, comprising the House of Representatives and Senate.",
    ),
    (
        "US House",
        "United States House of Representatives",
        "Lower chamber of the U.S. Congress, with 435 members apportioned by population.",
    ),
    ("US Senate", "United States Senate", "Upper chamber of the U.S. Congress, with two senators per state."),
    (
        "White House",
        "Executive Office of the President",
        "Office supporting the President of the United States; coordinates federal executive policy.",
    ),
    (
        "US State Department",
        "United States Department of State",
        "U.S. federal department conducting foreign relations and diplomacy.",
    ),
    (
        "OFAC",
        "Office of Foreign Assets Control",
        "U.S. Treasury bureau administering and enforcing economic and trade sanctions.",
    ),
    (
        "USTR",
        "Office of the United States Trade Representative",
        "U.S. agency responsible for developing and recommending trade policy and negotiating trade agreements.",
    ),
    (
        "European Commission",
        "European Commission",
        "Executive branch of the European Union, proposing legislation and implementing decisions.",
    ),
    (
        "European Parliament",
        "European Parliament",
        "Directly elected legislative body of the European Union with 705 members.",
    ),
    (
        "European Council",
        "European Council",
        "EU institution defining general political direction and priorities, composed of heads of state or government.",
    ),
    (
        "Council of the EU",
        "Council of the European Union",
        "Legislative body of the EU representing member-state governments; co-legislator with the European Parliament.",
    ),
    (
        "UK Treasury",
        "HM Treasury",
        "United Kingdom government department responsible for economic and financial policy.",
    ),
    (
        "UK Parliament",
        "Parliament of the United Kingdom",
        "Bicameral legislature of the United Kingdom, comprising the House of Commons and House of Lords.",
    ),
    (
        "Bundestag",
        "German Federal Parliament (Bundestag)",
        "Constitutional and legislative body of the Federal Republic of Germany.",
    ),
    (
        "Bundesrat",
        "German Federal Council (Bundesrat)",
        "German constitutional body representing the 16 federated states at the federal level.",
    ),
    (
        "NPC",
        "National People's Congress",
        "China's national legislature, the highest organ of state power in the People's Republic of China.",
    ),
    (
        "State Council of China",
        "State Council of the People's Republic of China",
        "Chief administrative authority of the People's Republic of China; the central government cabinet.",
    ),
    ("CCP", "Communist Party of China", "Founding and ruling political party of the People's Republic of China."),
    (
        "Diet of Japan",
        "National Diet of Japan",
        "Japan's bicameral national legislature, comprising the House of Representatives and House of Councillors.",
    ),
    ("Knesset", "Knesset", "Unicameral national legislature of Israel."),
    ("Lok Sabha", "Lok Sabha", "Lower house of India's Parliament, directly elected by the people."),
    (
        "Politburo",
        "Politburo of the Chinese Communist Party",
        "Decision-making committee of the Chinese Communist Party, with about 25 members.",
    ),
    (
        "G7",
        "Group of Seven",
        "Intergovernmental forum of seven major advanced economies: Canada, France, Germany, Italy, Japan, UK, US.",
    ),
    (
        "G20",
        "Group of Twenty",
        "International forum of 19 countries plus the European Union, representing major advanced and emerging economies.",
    ),
]

# Indices: (short_name, full_name, ticker_symbol, description).
_INDICES = [
    (
        "S&P 500",
        "S&P 500 Index",
        "SPX",
        "Capitalisation-weighted index of 500 of the largest U.S. publicly-traded companies.",
    ),
    (
        "Nasdaq Composite",
        "Nasdaq Composite Index",
        "IXIC",
        "Capitalisation-weighted index of all Nasdaq-listed common stocks, with heavy technology weighting.",
    ),
    (
        "Nasdaq-100",
        "Nasdaq-100 Index",
        "NDX",
        "Modified capitalisation-weighted index of the 100 largest non-financial companies on Nasdaq.",
    ),
    (
        "Dow Jones Industrial Average",
        "Dow Jones Industrial Average",
        "DJIA",
        "Price-weighted index of 30 prominent U.S. publicly-traded companies.",
    ),
    (
        "Russell 2000",
        "Russell 2000 Index",
        "RUT",
        "Capitalisation-weighted index of approximately 2,000 small-cap U.S. companies.",
    ),
    (
        "Russell 1000",
        "Russell 1000 Index",
        "RUI",
        "Capitalisation-weighted index of the 1,000 largest U.S. companies, representing about 92% of U.S. equity market cap.",
    ),
    (
        "Russell 3000",
        "Russell 3000 Index",
        "RUA",
        "Capitalisation-weighted index of the 3,000 largest U.S. companies, representing about 98% of U.S. equity market cap.",
    ),
    ("S&P MidCap 400", "S&P MidCap 400 Index", "MID", "Capitalisation-weighted index of 400 mid-cap U.S. companies."),
    (
        "Wilshire 5000",
        "Wilshire 5000 Total Market Index",
        "W5000",
        "Total-market index intended to measure performance of all U.S.-listed equity securities with readily available prices.",
    ),
    (
        "VIX",
        "CBOE Volatility Index",
        "VIX",
        "Real-time index representing expected 30-day volatility of the S&P 500, derived from option prices.",
    ),
    (
        "FTSE 100",
        "FTSE 100 Index",
        "UKX",
        "Capitalisation-weighted index of the 100 largest companies listed on the London Stock Exchange.",
    ),
    (
        "FTSE 250",
        "FTSE 250 Index",
        "MCX",
        "Capitalisation-weighted index of the 101st-350th largest companies listed on the London Stock Exchange.",
    ),
    (
        "DAX",
        "Deutscher Aktienindex (DAX)",
        "DAX",
        "Capitalisation-weighted index of the 40 largest German blue-chip companies listed on the Frankfurt Stock Exchange.",
    ),
    (
        "MDAX",
        "MDAX Index",
        "MDAX",
        "Capitalisation-weighted index of 50 medium-sized German companies that rank below the DAX.",
    ),
    (
        "CAC 40",
        "CAC 40 Index",
        "PX1",
        "Capitalisation-weighted index of the 40 most significant stocks on Euronext Paris.",
    ),
    (
        "EURO STOXX 50",
        "EURO STOXX 50 Index",
        "SX5E",
        "Capitalisation-weighted blue-chip index of the 50 largest Eurozone companies.",
    ),
    (
        "STOXX Europe 600",
        "STOXX Europe 600 Index",
        "SXXP",
        "Capitalisation-weighted index of 600 European companies covering 17 countries.",
    ),
    (
        "IBEX 35",
        "IBEX 35 Index",
        "IBEX",
        "Capitalisation-weighted index of the 35 most-liquid Spanish stocks listed on the Madrid Stock Exchange.",
    ),
    (
        "FTSE MIB",
        "FTSE MIB Index",
        "FTSEMIB",
        "Capitalisation-weighted index of the 40 largest Italian companies listed on Borsa Italiana.",
    ),
    ("AEX", "AEX Index", "AEX", "Capitalisation-weighted index of 25 leading Dutch companies on Euronext Amsterdam."),
    (
        "SMI",
        "Swiss Market Index",
        "SMI",
        "Capitalisation-weighted index of the 20 largest and most-liquid Swiss equities.",
    ),
    (
        "OMXS30",
        "OMX Stockholm 30 Index",
        "OMXS30",
        "Capitalisation-weighted index of the 30 most-traded stocks on the Stockholm Stock Exchange.",
    ),
    (
        "Nikkei 225",
        "Nikkei 225 Index",
        "N225",
        "Price-weighted index of 225 large publicly-owned companies in Japan, listed on the Tokyo Stock Exchange.",
    ),
    (
        "TOPIX",
        "Tokyo Price Index",
        "TOPIX",
        "Capitalisation-weighted index of all companies in the Tokyo Stock Exchange Prime Section.",
    ),
    (
        "Hang Seng Index",
        "Hang Seng Index",
        "HSI",
        "Capitalisation-weighted index of the largest companies on the Hong Kong Stock Exchange.",
    ),
    (
        "Hang Seng Tech Index",
        "Hang Seng Technology Index",
        "HSTECH",
        "Capitalisation-weighted index of the 30 largest technology companies in Hong Kong.",
    ),
    (
        "Shanghai Composite",
        "Shanghai Stock Exchange Composite Index",
        "SSEC",
        "Capitalisation-weighted index of all stocks traded on the Shanghai Stock Exchange.",
    ),
    (
        "CSI 300",
        "CSI 300 Index",
        "CSI300",
        "Capitalisation-weighted index of the top 300 stocks listed on the Shanghai and Shenzhen exchanges.",
    ),
    (
        "KOSPI",
        "Korea Composite Stock Price Index",
        "KOSPI",
        "Capitalisation-weighted index of all common stocks traded on the Korea Exchange's Stock Market Division.",
    ),
    (
        "S&P/ASX 200",
        "S&P/ASX 200 Index",
        "XJO",
        "Capitalisation-weighted index of 200 of the largest Australian Securities Exchange-listed companies.",
    ),
]

# Commodities: (short_name, full_name, ticker, category, description).
_COMMODITIES = [
    (
        "Crude Oil",
        "Crude Oil (WTI)",
        "CL",
        "energy",
        "West Texas Intermediate light sweet crude oil, the U.S. benchmark crude grade traded on NYMEX.",
    ),
    (
        "Brent Crude",
        "Brent Crude Oil",
        "BZ",
        "energy",
        "International benchmark light sweet crude oil sourced from the North Sea, traded on ICE.",
    ),
    (
        "Natural Gas",
        "Natural Gas",
        "NG",
        "energy",
        "Henry Hub natural gas futures, the U.S. benchmark for natural gas prices, traded on NYMEX.",
    ),
    (
        "Heating Oil",
        "Heating Oil",
        "HO",
        "energy",
        "ULSD (ultra-low-sulphur diesel) heating oil futures traded on NYMEX.",
    ),
    (
        "RBOB Gasoline",
        "RBOB Gasoline",
        "RB",
        "energy",
        "Reformulated Blendstock for Oxygenate Blending gasoline futures, the U.S. wholesale gasoline benchmark.",
    ),
    ("Gold", "Gold", "GC", "metal", "Gold futures contract, a major safe-haven precious metal traded on COMEX."),
    ("Silver", "Silver", "SI", "metal", "Silver futures contract, an industrial and precious metal traded on COMEX."),
    ("Copper", "Copper", "HG", "metal", "Copper futures contract, a key industrial metal traded on COMEX."),
    (
        "Platinum",
        "Platinum",
        "PL",
        "metal",
        "Platinum futures contract, a precious and industrial metal traded on NYMEX.",
    ),
    (
        "Palladium",
        "Palladium",
        "PA",
        "metal",
        "Palladium futures contract, a precious metal used heavily in catalytic converters, traded on NYMEX.",
    ),
    (
        "Aluminium",
        "Aluminium",
        "ALI",
        "metal",
        "Aluminium futures contract, a key industrial metal traded on the London Metal Exchange.",
    ),
    (
        "Zinc",
        "Zinc",
        "ZNC",
        "metal",
        "Zinc futures contract, an industrial metal used primarily for galvanising steel, traded on the LME.",
    ),
    (
        "Nickel",
        "Nickel",
        "NIK",
        "metal",
        "Nickel futures contract, an industrial metal used in stainless steel and batteries, traded on the LME.",
    ),
    (
        "Lead",
        "Lead",
        "LED",
        "metal",
        "Lead futures contract, an industrial metal used in batteries, traded on the LME.",
    ),
    ("Iron Ore", "Iron Ore", "TIO", "metal", "Iron ore futures contract, the primary raw material for steelmaking."),
    (
        "Wheat",
        "Wheat",
        "ZW",
        "agricultural",
        "Chicago soft red winter wheat futures, a global agricultural commodity benchmark traded on CBOT.",
    ),
    (
        "Corn",
        "Corn",
        "ZC",
        "agricultural",
        "Corn futures contract, a global feed-grain and biofuel commodity traded on CBOT.",
    ),
    (
        "Soybeans",
        "Soybeans",
        "ZS",
        "agricultural",
        "Soybean futures contract, a global oilseed commodity traded on CBOT.",
    ),
    (
        "Soybean Oil",
        "Soybean Oil",
        "ZL",
        "agricultural",
        "Soybean oil futures contract, used in food and biofuels, traded on CBOT.",
    ),
    (
        "Soybean Meal",
        "Soybean Meal",
        "ZM",
        "agricultural",
        "Soybean meal futures contract, an animal-feed protein commodity, traded on CBOT.",
    ),
    (
        "Cotton",
        "Cotton",
        "CT",
        "agricultural",
        "Cotton futures contract, the global benchmark for fibre prices, traded on ICE.",
    ),
    (
        "Coffee",
        "Coffee",
        "KC",
        "soft",
        "Arabica coffee futures contract, the global benchmark for high-quality coffee, traded on ICE.",
    ),
    (
        "Cocoa",
        "Cocoa",
        "CC",
        "soft",
        "Cocoa futures contract, the global benchmark for chocolate raw materials, traded on ICE.",
    ),
    (
        "Sugar",
        "Sugar No. 11",
        "SB",
        "soft",
        "Raw sugar futures contract, the global benchmark for sugar prices, traded on ICE.",
    ),
    (
        "Live Cattle",
        "Live Cattle",
        "LE",
        "livestock",
        "Live cattle futures contract, a beef-supply benchmark traded on CME.",
    ),
]

# Macroeconomic indicators: (short_name, full_name, description).
_MACRO_INDICATORS = [
    (
        "CPI",
        "Consumer Price Index",
        "Measure of the average change over time in prices paid by urban consumers for a basket of goods and services.",
    ),
    (
        "Core CPI",
        "Core Consumer Price Index",
        "CPI excluding volatile food and energy components; preferred measure of underlying inflation.",
    ),
    (
        "PPI",
        "Producer Price Index",
        "Measure of the average change over time in selling prices received by domestic producers.",
    ),
    ("Core PPI", "Core Producer Price Index", "PPI excluding food and energy; gauge of underlying producer inflation."),
    (
        "NFP",
        "Nonfarm Payrolls",
        "Monthly count of paid U.S. workers excluding farm workers, government employees, and a few other categories.",
    ),
    (
        "Unemployment Rate",
        "Unemployment Rate",
        "Percentage of the labour force that is jobless and actively seeking employment.",
    ),
    (
        "Initial Jobless Claims",
        "Initial Jobless Claims",
        "Weekly count of first-time applicants for U.S. unemployment insurance benefits.",
    ),
    (
        "Continuing Claims",
        "Continuing Jobless Claims",
        "Weekly count of people receiving ongoing U.S. unemployment insurance benefits.",
    ),
    (
        "GDP",
        "Gross Domestic Product",
        "Total monetary value of all final goods and services produced within a country's borders in a period.",
    ),
    (
        "Real GDP",
        "Real Gross Domestic Product",
        "GDP adjusted for inflation; reflects underlying growth in goods-and-services output.",
    ),
    (
        "ISM Manufacturing PMI",
        "ISM Manufacturing Purchasing Managers' Index",
        "Diffusion index measuring U.S. manufacturing activity; >50 indicates expansion, <50 contraction.",
    ),
    (
        "ISM Services PMI",
        "ISM Services Purchasing Managers' Index",
        "Diffusion index measuring U.S. services-sector activity; >50 indicates expansion.",
    ),
    (
        "Retail Sales",
        "Retail Sales",
        "Monthly measure of total receipts of retail and food-services stores, a key consumer-spending gauge.",
    ),
    (
        "Industrial Production",
        "Industrial Production",
        "Measure of output from manufacturing, mining, and electric- and gas-utility industries.",
    ),
    (
        "Capacity Utilization",
        "Capacity Utilization",
        "Percentage of total industrial capacity actually being used in production.",
    ),
    (
        "Housing Starts",
        "Housing Starts",
        "Monthly measure of new privately-owned residential construction projects begun in the U.S.",
    ),
    (
        "Existing Home Sales",
        "Existing Home Sales",
        "Monthly count of completed sales transactions for previously-owned single-family homes, condos, and co-ops.",
    ),
    ("New Home Sales", "New Home Sales", "Monthly count of newly-constructed single-family homes sold in the U.S."),
    (
        "Building Permits",
        "Building Permits",
        "Monthly count of permits issued for new construction projects, a leading housing-activity indicator.",
    ),
    (
        "Personal Income",
        "Personal Income",
        "Monthly measure of income received by U.S. residents from wages, salaries, dividends, and other sources.",
    ),
    (
        "Personal Spending",
        "Personal Spending",
        "Monthly measure of consumer spending on goods and services in the U.S.",
    ),
    (
        "PCE Price Index",
        "Personal Consumption Expenditures Price Index",
        "Measure of inflation in personal consumption; the Fed's preferred inflation gauge.",
    ),
    (
        "Core PCE",
        "Core Personal Consumption Expenditures Price Index",
        "PCE excluding food and energy; the Fed's preferred underlying-inflation measure.",
    ),
    (
        "Trade Balance",
        "Trade Balance",
        "Difference between a country's exports and imports of goods and services over a period.",
    ),
    (
        "Current Account",
        "Current Account Balance",
        "Broad measure of a country's transactions with the rest of the world, including trade, income, and transfers.",
    ),
    (
        "Federal Funds Rate",
        "Federal Funds Rate",
        "Interest rate at which U.S. depository institutions lend reserve balances to other depository institutions overnight.",
    ),
    (
        "10-Year Treasury Yield",
        "10-Year U.S. Treasury Yield",
        "Yield on the U.S. 10-year Treasury note; a benchmark long-term interest rate.",
    ),
    (
        "2-Year Treasury Yield",
        "2-Year U.S. Treasury Yield",
        "Yield on the U.S. 2-year Treasury note; closely tracks Fed-policy expectations.",
    ),
    (
        "M2 Money Supply",
        "M2 Money Supply",
        "Measure of U.S. money supply including currency, demand deposits, savings deposits, and money-market securities.",
    ),
    (
        "FOMC Decision",
        "FOMC Interest-Rate Decision",
        "Federal Open Market Committee's announcement of the federal funds rate target and policy stance.",
    ),
]

# Locations: (short_name, full_name, iso2, demonym_or_None_skip, description).
# Demonyms intentionally OMITTED for ambiguity reasons (e.g. "American" can
# modify many entities). Only short codes that are unambiguous resolve.
_LOCATIONS = [
    (
        "United States",
        "United States of America",
        "US",
        "Federal republic of 50 states in North America; the world's largest economy by nominal GDP.",
    ),
    (
        "China",
        "People's Republic of China",
        "CN",
        "East Asian sovereign state; the world's second-largest economy by nominal GDP and most populous country.",
    ),
    ("Japan", "Japan", "JP", "Island country in East Asia; the world's third-largest economy by nominal GDP."),
    (
        "Germany",
        "Federal Republic of Germany",
        "DE",
        "Central European federal republic; the largest national economy in Europe.",
    ),
    (
        "United Kingdom",
        "United Kingdom of Great Britain and Northern Ireland",
        "GB",
        "Sovereign country in northwestern Europe; a major global financial centre.",
    ),
    (
        "France",
        "French Republic",
        "FR",
        "Western European republic; one of the largest economies in the European Union.",
    ),
    ("Italy", "Italian Republic", "IT", "Southern European republic; a major Eurozone economy."),
    ("Spain", "Kingdom of Spain", "ES", "Southern European kingdom; one of the largest Eurozone economies."),
    (
        "Netherlands",
        "Kingdom of the Netherlands",
        "NL",
        "Western European kingdom; a major trading nation and Eurozone member.",
    ),
    (
        "Switzerland",
        "Swiss Confederation",
        "CH",
        "Central European federal republic; a major global financial centre and home to many multinationals.",
    ),
    ("Sweden", "Kingdom of Sweden", "SE", "Northern European kingdom; a major Nordic economy."),
    (
        "Russia",
        "Russian Federation",
        "RU",
        "Transcontinental country spanning Eastern Europe and Northern Asia; major energy producer.",
    ),
    (
        "India",
        "Republic of India",
        "IN",
        "South Asian republic; one of the world's largest economies and most populous countries.",
    ),
    (
        "Brazil",
        "Federative Republic of Brazil",
        "BR",
        "South American federal republic; the largest economy in Latin America.",
    ),
    ("Mexico", "United Mexican States", "MX", "North American federal republic; a major emerging-market economy."),
    ("Argentina", "Argentine Republic", "AR", "South American federal republic; a major Latin American economy."),
    (
        "Canada",
        "Canada",
        "CA",
        "North American federal parliamentary democracy; the world's second-largest country by area.",
    ),
    (
        "Australia",
        "Commonwealth of Australia",
        "AU",
        "Country comprising the Australian mainland and Tasmania; major commodity exporter.",
    ),
    (
        "New Zealand",
        "New Zealand",
        "NZ",
        "Island country in the southwestern Pacific; advanced economy with strong agricultural exports.",
    ),
    (
        "Saudi Arabia",
        "Kingdom of Saudi Arabia",
        "SA",
        "Western Asian absolute monarchy; the world's largest oil exporter.",
    ),
    (
        "UAE",
        "United Arab Emirates",
        "AE",
        "Federation of seven emirates in Western Asia; a major regional financial and trade hub.",
    ),
    ("Israel", "State of Israel", "IL", "Western Asian republic; a major centre for technology innovation."),
    ("Turkey", "Republic of Türkiye", "TR", "Transcontinental republic spanning Western Asia and Southeastern Europe."),
    (
        "South Korea",
        "Republic of Korea",
        "KR",
        "East Asian republic; a major industrial economy with strong technology and automotive sectors.",
    ),
    (
        "Singapore",
        "Republic of Singapore",
        "SG",
        "Southeast Asian sovereign island city-state; a major global financial centre.",
    ),
    (
        "Hong Kong",
        "Hong Kong Special Administrative Region",
        "HK",
        "Special administrative region of China; a major global financial centre.",
    ),
    (
        "Taiwan",
        "Republic of China (Taiwan)",
        "TW",
        "East Asian island state; a leading global producer of semiconductors.",
    ),
    (
        "Indonesia",
        "Republic of Indonesia",
        "ID",
        "Southeast Asian island state; the largest economy in Southeast Asia.",
    ),
    (
        "South Africa",
        "Republic of South Africa",
        "ZA",
        "Southernmost country in Africa; the most industrialised African economy.",
    ),
    (
        "Eurozone",
        "Eurozone",
        None,
        "Monetary union of 20 European Union member states that have adopted the euro as their primary currency.",
    ),
]

# Persons: (full_name, last_name_or_None_if_ambiguous, title, organization, description).
_PERSONS = [
    (
        "Jerome Powell",
        "Powell",
        "Chair",
        "Federal Reserve",
        "Chair of the Board of Governors of the U.S. Federal Reserve System.",
    ),
    (
        "Christine Lagarde",
        "Lagarde",
        "President",
        "European Central Bank",
        "President of the European Central Bank, responsible for Eurozone monetary policy.",
    ),
    (
        "Kazuo Ueda",
        "Ueda",
        "Governor",
        "Bank of Japan",
        "Governor of the Bank of Japan, leading Japan's central bank and monetary policy.",
    ),
    (
        "Andrew Bailey",
        "Bailey",
        "Governor",
        "Bank of England",
        "Governor of the Bank of England, leading the United Kingdom's central bank.",
    ),
    (
        "Pan Gongsheng",
        "Pan Gongsheng",
        "Governor",
        "People's Bank of China",
        "Governor of the People's Bank of China, China's central bank.",
    ),
    (
        "Shaktikanta Das",
        "Das",
        "Governor",
        "Reserve Bank of India",
        "Governor of the Reserve Bank of India, India's central bank.",
    ),
    (
        "Janet Yellen",
        "Yellen",
        "Former Treasury Secretary",
        "U.S. Treasury",
        "Former U.S. Secretary of the Treasury (2021-2025) and former Federal Reserve Chair.",
    ),
    (
        "Scott Bessent",
        "Bessent",
        "Treasury Secretary",
        "U.S. Treasury",
        "U.S. Secretary of the Treasury, responsible for federal economic and financial policy.",
    ),
    (
        "Jamie Dimon",
        "Dimon",
        "CEO",
        "JPMorgan Chase",
        "Chairman and CEO of JPMorgan Chase, the largest U.S. bank by assets.",
    ),
    ("Larry Fink", "Fink", "CEO", "BlackRock", "Chairman and CEO of BlackRock, the world's largest asset manager."),
    (
        "David Solomon",
        "Solomon",
        "CEO",
        "Goldman Sachs",
        "Chairman and CEO of Goldman Sachs, a leading global investment bank.",
    ),
    (
        "Ted Pick",
        "Pick",
        "CEO",
        "Morgan Stanley",
        "CEO of Morgan Stanley, a leading global investment bank and wealth manager.",
    ),
    (
        "Warren Buffett",
        "Buffett",
        "Chairman & CEO",
        "Berkshire Hathaway",
        "Chairman and CEO of Berkshire Hathaway and one of the most successful investors in history.",
    ),
    (
        "Elon Musk",
        "Musk",
        "CEO",
        "Tesla, SpaceX",
        "CEO of Tesla and SpaceX; founder of multiple major technology companies.",
    ),
    (
        "Tim Cook",
        "Cook",
        "CEO",
        "Apple Inc.",
        "Chief Executive Officer of Apple Inc., the world's most valuable company by market capitalisation.",
    ),
    ("Satya Nadella", "Nadella", "CEO", "Microsoft", "Chairman and CEO of Microsoft Corporation."),
    (
        "Sundar Pichai",
        "Pichai",
        "CEO",
        "Alphabet, Google",
        "CEO of Alphabet and Google, leading the parent of Google's search, advertising, and cloud businesses.",
    ),
    (
        "Mark Zuckerberg",
        "Zuckerberg",
        "Chairman & CEO",
        "Meta Platforms",
        "Chairman and CEO of Meta Platforms, the parent of Facebook, Instagram, and WhatsApp.",
    ),
    (
        "Jensen Huang",
        "Huang",
        "CEO",
        "NVIDIA",
        "Founder and CEO of NVIDIA Corporation, a leading designer of GPUs and AI hardware.",
    ),
    (
        "Bill Ackman",
        "Ackman",
        "CEO",
        "Pershing Square Capital",
        "Founder and CEO of Pershing Square Capital Management, a major activist hedge fund.",
    ),
]

# Non-listed financial institutions only (the listed ones are already in
# canonical_entities as financial_instrument seeds; seeding them again here
# would create duplicate canonicals).
_FINANCIAL_INSTITUTIONS = [
    (
        "Vanguard",
        "The Vanguard Group",
        "American investment-advisor; the world's second-largest asset manager and a pioneer of low-cost index funds.",
    ),
    (
        "Fidelity",
        "Fidelity Investments",
        "Privately-held American multinational financial-services corporation; one of the world's largest asset managers.",
    ),
    (
        "Bridgewater Associates",
        "Bridgewater Associates",
        "American hedge-fund firm founded by Ray Dalio; one of the world's largest hedge funds.",
    ),
    (
        "Brookfield Asset Management",
        "Brookfield Asset Management",
        "Canadian alternative-asset manager focused on real estate, infrastructure, renewable power, and private equity.",
    ),
    (
        "Apollo Global Management",
        "Apollo Global Management",
        "American private-equity and alternative-asset manager headquartered in New York City.",
    ),
    (
        "Blackstone",
        "Blackstone Inc.",
        "American alternative-asset manager and one of the largest private-equity firms in the world.",
    ),
]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _uuid(prefix: str, counter: int) -> str:
    """Build a stable UUIDv7-shaped ID. ``prefix`` is 4 hex chars (e.g. 'c001'),
    ``counter`` becomes the next 4 hex digits + tail.

    Pattern: ``0195daad-<prefix>-7<counter:03x>-8<counter:03x>-<12-hex-counter>``.
    Mirrors the seeds/003 pattern with the v7 marker (7) and variant (8) nibbles.
    """
    c4 = f"{counter:04x}"
    return f"0195daad-{prefix}-7{c4[:3]}-8{c4[:3]}-{counter:012x}"


def _norm(text: str) -> str:
    return text.lower().strip()


def _values_clause_canonical(rows: list[tuple[str, str, str, dict]]) -> str:
    """Build a multi-row VALUES clause for canonical_entities INSERT.

    Each row: (entity_id, canonical_name, entity_type, metadata_dict).
    """
    parts = []
    for entity_id, canonical_name, entity_type, metadata in rows:
        # Escape single quotes by doubling them.
        cn = canonical_name.replace("'", "''")
        meta_json = json.dumps(metadata).replace("'", "''")
        parts.append(f"('{entity_id}', '{cn}', '{entity_type}', '{meta_json}'::jsonb)")
    return ",\n  ".join(parts)


def _values_clause_alias(rows: list[tuple[str, str, str]]) -> str:
    """Each row: (entity_id, alias_text, alias_type)."""
    parts = []
    for entity_id, alias_text, alias_type in rows:
        at = alias_text.replace("'", "''")
        norm = _norm(alias_text).replace("'", "''")
        parts.append(f"('{entity_id}', '{at}', '{norm}', '{alias_type}', true, 'seed:F-CRIT-10')")
    return ",\n  ".join(parts)


def _emit_canonical_block(label: str, rows: list[tuple[str, str, str, dict]]) -> None:
    if not rows:
        return
    op.execute(
        f"-- F-CRIT-10 seed: {label}\n"
        "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type, metadata) "
        f"VALUES {_values_clause_canonical(rows)} "
        "ON CONFLICT (entity_id) DO NOTHING"
    )


def _emit_alias_block(label: str, rows: list[tuple[str, str, str]]) -> None:
    if not rows:
        return
    op.execute(
        f"-- F-CRIT-10 alias seed: {label}\n"
        "INSERT INTO entity_aliases "
        "(entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
        f"VALUES {_values_clause_alias(rows)} "
        "ON CONFLICT DO NOTHING"
    )


# ── Per-class builders ─────────────────────────────────────────────────────────


def _build_currency_rows() -> tuple[list, list]:
    canonicals: list[tuple[str, str, str, dict]] = []
    aliases: list[tuple[str, str, str]] = []
    for i, (code, full_name, region) in enumerate(_CURRENCIES, start=1):
        eid = _uuid("c001", i)
        desc = f"The {full_name} ({code}) is the official currency of {region}. ISO-4217 code: {code}."
        canonicals.append(
            (
                eid,
                full_name,
                "currency",
                {
                    "description": desc,
                    "iso_code": code,
                    "region": region,
                    "seed_source": "F-CRIT-10",
                },
            )
        )
        aliases.append((eid, full_name, "EXACT"))
        if _norm(code) != _norm(full_name):
            aliases.append((eid, code, "EXACT"))
    return canonicals, aliases


def _build_regulator_rows() -> tuple[list, list]:
    canonicals: list[tuple[str, str, str, dict]] = []
    aliases: list[tuple[str, str, str]] = []
    for i, (abbrev, full_name, desc) in enumerate(_REGULATORY_BODIES, start=1):
        eid = _uuid("c002", i)
        canonicals.append(
            (
                eid,
                full_name,
                "regulatory_body",
                {
                    "description": desc,
                    "abbreviation": abbrev,
                    "seed_source": "F-CRIT-10",
                },
            )
        )
        aliases.append((eid, full_name, "EXACT"))
        if _norm(abbrev) != _norm(full_name):
            aliases.append((eid, abbrev, "EXACT"))
    return canonicals, aliases


def _build_govt_rows() -> tuple[list, list]:
    canonicals: list[tuple[str, str, str, dict]] = []
    aliases: list[tuple[str, str, str]] = []
    for i, (short_name, full_name, desc) in enumerate(_GOVERNMENT_BODIES, start=1):
        eid = _uuid("c003", i)
        canonicals.append(
            (
                eid,
                full_name,
                "government_body",
                {
                    "description": desc,
                    "seed_source": "F-CRIT-10",
                },
            )
        )
        aliases.append((eid, full_name, "EXACT"))
        if _norm(short_name) != _norm(full_name):
            aliases.append((eid, short_name, "EXACT"))
    return canonicals, aliases


def _build_index_rows() -> tuple[list, list]:
    canonicals: list[tuple[str, str, str, dict]] = []
    aliases: list[tuple[str, str, str]] = []
    for i, (short_name, full_name, ticker, desc) in enumerate(_INDICES, start=1):
        eid = _uuid("c004", i)
        canonicals.append(
            (
                eid,
                full_name,
                "index",
                {
                    "description": desc,
                    "ticker": ticker,
                    "seed_source": "F-CRIT-10",
                },
            )
        )
        # full_name + short_name + ticker — three aliases per index (collapse if same)
        seen: set[str] = set()
        for txt in (full_name, short_name, ticker):
            n = _norm(txt)
            if n in seen:
                continue
            seen.add(n)
            aliases.append((eid, txt, "EXACT" if txt != ticker else "TICKER"))
    return canonicals, aliases


def _build_commodity_rows() -> tuple[list, list]:
    canonicals: list[tuple[str, str, str, dict]] = []
    aliases: list[tuple[str, str, str]] = []
    for i, (short_name, full_name, ticker, category, desc) in enumerate(_COMMODITIES, start=1):
        eid = _uuid("c005", i)
        canonicals.append(
            (
                eid,
                full_name,
                "commodity",
                {
                    "description": desc,
                    "ticker": ticker,
                    "category": category,
                    "seed_source": "F-CRIT-10",
                },
            )
        )
        seen: set[str] = set()
        for txt, atype in ((full_name, "EXACT"), (short_name, "EXACT"), (ticker, "TICKER")):
            n = _norm(txt)
            if n in seen:
                continue
            seen.add(n)
            aliases.append((eid, txt, atype))
    return canonicals, aliases


def _build_macro_rows() -> tuple[list, list]:
    canonicals: list[tuple[str, str, str, dict]] = []
    aliases: list[tuple[str, str, str]] = []
    for i, (short_name, full_name, desc) in enumerate(_MACRO_INDICATORS, start=1):
        eid = _uuid("c006", i)
        canonicals.append(
            (
                eid,
                full_name,
                "macroeconomic_indicator",
                {
                    "description": desc,
                    "abbreviation": short_name,
                    "seed_source": "F-CRIT-10",
                },
            )
        )
        aliases.append((eid, full_name, "EXACT"))
        if _norm(short_name) != _norm(full_name):
            aliases.append((eid, short_name, "EXACT"))
    return canonicals, aliases


def _build_location_rows() -> tuple[list, list]:
    canonicals: list[tuple[str, str, str, dict]] = []
    aliases: list[tuple[str, str, str]] = []
    for i, (short_name, full_name, iso2, desc) in enumerate(_LOCATIONS, start=1):
        eid = _uuid("c007", i)
        meta: dict = {
            "description": desc,
            "seed_source": "F-CRIT-10",
        }
        if iso2:
            meta["iso2"] = iso2
        canonicals.append((eid, full_name, "location", meta))
        seen: set[str] = set()
        for txt in (full_name, short_name):
            n = _norm(txt)
            if n in seen:
                continue
            seen.add(n)
            aliases.append((eid, txt, "EXACT"))
    return canonicals, aliases


def _build_person_rows() -> tuple[list, list]:
    canonicals: list[tuple[str, str, str, dict]] = []
    aliases: list[tuple[str, str, str]] = []
    for i, (full_name, last_name, title, org, desc) in enumerate(_PERSONS, start=1):
        eid = _uuid("c008", i)
        canonicals.append(
            (
                eid,
                full_name,
                "person",
                {
                    "description": desc,
                    "title": title,
                    "organization": org,
                    "seed_source": "F-CRIT-10",
                },
            )
        )
        aliases.append((eid, full_name, "EXACT"))
        # Last-name-only alias is risky for ambiguous names; only emit when
        # explicitly distinct from full_name and not a common-word collision.
        if (
            last_name
            and _norm(last_name) != _norm(full_name)
            and last_name
            not in (
                # Common-word collisions to avoid:
                "Cook",
                "Fink",
                "Pick",
            )
        ):
            aliases.append((eid, last_name, "EXACT"))
    return canonicals, aliases


def _build_finst_rows() -> tuple[list, list]:
    canonicals: list[tuple[str, str, str, dict]] = []
    aliases: list[tuple[str, str, str]] = []
    for i, (short_name, full_name, desc) in enumerate(_FINANCIAL_INSTITUTIONS, start=1):
        eid = _uuid("c009", i)
        canonicals.append(
            (
                eid,
                full_name,
                "financial_institution",
                {
                    "description": desc,
                    "seed_source": "F-CRIT-10",
                },
            )
        )
        aliases.append((eid, full_name, "EXACT"))
        if _norm(short_name) != _norm(full_name):
            aliases.append((eid, short_name, "EXACT"))
    return canonicals, aliases


# ── Migration ──────────────────────────────────────────────────────────────────


def upgrade() -> None:
    builders = [
        ("currencies", _build_currency_rows),
        ("regulatory bodies", _build_regulator_rows),
        ("government bodies", _build_govt_rows),
        ("indices", _build_index_rows),
        ("commodities", _build_commodity_rows),
        ("macro indicators", _build_macro_rows),
        ("locations", _build_location_rows),
        ("persons", _build_person_rows),
        ("financial institutions", _build_finst_rows),
    ]
    for label, builder in builders:
        canonicals, aliases = builder()
        _emit_canonical_block(label, canonicals)
        _emit_alias_block(label, aliases)

    # Seed entity_embedding_state with 2 view rows (definition + narrative) per
    # newly-seeded canonical. ``next_refresh_at = now()`` makes them immediately
    # due for the refresh workers' next cycle. financial_instrument fundamentals_ohlcv
    # is intentionally absent — none of our seeds are financial_instrument type.
    op.execute(
        """
INSERT INTO entity_embedding_state (entity_id, view_type, last_refreshed_at, next_refresh_at, refresh_count)
SELECT ce.entity_id, vt.view_type, now(), now(), 0
FROM canonical_entities ce
CROSS JOIN (VALUES ('definition'), ('narrative')) AS vt(view_type)
WHERE ce.metadata ->> 'seed_source' = 'F-CRIT-10'
ON CONFLICT (entity_id, view_type) DO NOTHING
"""
    )


def downgrade() -> None:
    # CASCADE deletes from canonical_entities cascade to entity_aliases and
    # entity_embedding_state via FK constraints (intelligence_db 0001 schema).
    op.execute("DELETE FROM canonical_entities WHERE metadata ->> 'seed_source' = 'F-CRIT-10'")
