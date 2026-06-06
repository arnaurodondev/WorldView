"""Expand polling_policies to the full S&P 500 universe + 7 global indices.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-06

PLAN-0106 Wave A-1 — S&P 500 Universe Expansion.

What this migration does
------------------------
1. Inserts fundamentals + OHLCV (1d/1w/1mo) polling policies for every S&P
   500 constituent that is NOT already covered by migration 0002.
2. Inserts OHLCV (1d/1w/1mo) polling policies for 7 major global indices
   (DAX, FTSE 100, CAC 40, Euro Stoxx 50, Nikkei 225, Hang Seng, Shanghai).
3. Does NOT insert quotes (Alpaca 1m covers intraday) or news_sentiment
   (moving to S4).

All inserts use ``ON CONFLICT (id) DO NOTHING`` so the migration is safe to
re-run on databases that already have these policies.

Forward-compat (R5):
    Only INSERT rows — no schema changes.  Rollback deletes the inserted rows
    by ID.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Deterministic ID helper (copied verbatim from migration 0011)
# ---------------------------------------------------------------------------


def _ulid_from_seed(seed: str) -> str:
    """Deterministic 26-char ULID-like ID from a seed string."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"01HX{h[:22].upper()}"


# ---------------------------------------------------------------------------
# Table definition (mirrors migration 0002 + adds tier/post_market_only from 0008)
# ---------------------------------------------------------------------------

_POLICIES_TABLE = sa.table(
    "polling_policies",
    sa.column("id", sa.String),
    sa.column("provider", sa.String),
    sa.column("dataset_type", sa.String),
    sa.column("dataset_variant", sa.String),
    sa.column("symbol", sa.String),
    sa.column("exchange", sa.String),
    sa.column("timeframe", sa.String),
    sa.column("base_interval_sec", sa.Integer),
    sa.column("min_interval_sec", sa.Integer),
    sa.column("jitter_sec", sa.Integer),
    sa.column("adaptive_enabled", sa.Boolean),
    sa.column("adaptive_k", sa.Float),
    sa.column("adaptive_half_life_sec", sa.Integer),
    sa.column("priority", sa.Integer),
    sa.column("enabled", sa.Boolean),
    sa.column("backfill_enabled", sa.Boolean),
    sa.column("backfill_start_date", sa.Date),
    sa.column("backfill_chunk_days", sa.Integer),
    sa.column("market_hours_only", sa.Boolean),
    sa.column("tier", sa.Integer),
    sa.column("post_market_only", sa.Boolean),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

# ---------------------------------------------------------------------------
# Symbols already seeded in migration 0002 — excluded from this expansion.
# Keeping this set explicit prevents duplicate-ID collisions.
# ---------------------------------------------------------------------------
_EXISTING_US_SYMBOLS: frozenset[str] = frozenset(
    [
        "AAPL",
        "MSFT",
        "GOOGL",
        "AMZN",
        "NVDA",
        "TSLA",
        "META",
        "BRK-B",
        "JNJ",
        "V",
        "WMT",
        "JPM",
        "PG",
        "XOM",
        "MA",
        "UNH",
        "HD",
        "COST",
        "MRK",
        "BA",
        "PFE",
        "LLY",
        "AXP",
        "MS",
        "DIS",
        "IBM",
        "EXC",
        "CAT",
        "KO",
        "CVX",
        # ETFs (US exchange)
        "XLK",
        "XLV",
        "XLE",
        "XLY",
        "VTV",
        "QQQ",
        "IBIT",
        "MSTR",
        "PPA",
        "SPY",
        "IVV",
        "VOO",
        "VTI",
        "IEF",
        "TLT",
        "AGG",
        "SHY",
        "GLD",
        "SLV",
        "USO",
    ]
)

# ---------------------------------------------------------------------------
# NEW S&P 500 constituents — cleaned and deduplicated.
# All exchange="US".  Symbols already in _EXISTING_US_SYMBOLS are not here.
# ---------------------------------------------------------------------------
_NEW_SP500_SYMBOLS: list[str] = [
    # A
    "GOOG",  # Alphabet Class C (GOOGL already exists)
    "MMM",  # 3M
    "AOS",  # A.O. Smith
    "ABT",  # Abbott Laboratories
    "ABBV",  # AbbVie
    "ACN",  # Accenture
    "ADBE",  # Adobe
    "AMD",  # Advanced Micro Devices
    "AES",  # AES Corporation
    "AFL",  # Aflac
    "A",  # Agilent Technologies
    "APD",  # Air Products
    "AKAM",  # Akamai Technologies
    "ALK",  # Alaska Air
    "ALB",  # Albemarle
    "ARE",  # Alexandria Real Estate
    "ALGN",  # Align Technology
    "ALLE",  # Allegion
    "LNT",  # Alliant Energy
    "ALL",  # Allstate
    "MO",  # Altria Group
    "AMCR",  # Amcor
    "AEE",  # Ameren
    "AEP",  # American Electric Power
    "AMT",  # American Tower
    "AWK",  # American Water Works
    "AMP",  # Ameriprise Financial
    "AME",  # AMETEK
    "AMGN",  # Amgen
    "APH",  # Amphenol
    "ADI",  # Analog Devices
    "ANSS",  # ANSYS
    "AON",  # Aon
    "APA",  # APA Corporation
    "AMAT",  # Applied Materials
    "APTV",  # Aptiv
    "ACGL",  # Arch Capital Group
    "ADM",  # Archer-Daniels-Midland
    "ANET",  # Arista Networks
    "AJG",  # Arthur J. Gallagher
    "AIZ",  # Assurant
    "T",  # AT&T
    "ATO",  # Atmos Energy
    "ADSK",  # Autodesk
    "AZO",  # AutoZone
    "AVB",  # AvalonBay Communities
    "AVY",  # Avery Dennison
    "AXON",  # Axon Enterprise
    # B
    "BKR",  # Baker Hughes
    "BALL",  # Ball Corporation
    "BAC",  # Bank of America
    "BBWI",  # Bath & Body Works
    "BAX",  # Baxter International
    "BDX",  # Becton Dickinson
    "BBY",  # Best Buy
    "BIO",  # Bio-Rad Laboratories
    "TECH",  # Bio-Techne
    "BIIB",  # Biogen
    "BLK",  # BlackRock
    "BX",  # Blackstone
    "BCR",  # Bard (now BD — keeping as BCR per instructions)
    "BMY",  # Bristol-Myers Squibb
    "AVGO",  # Broadcom
    "BR",  # Broadridge Financial
    "BRO",  # Brown & Brown
    "BF-B",  # Brown-Forman Class B
    "BLDR",  # Builders FirstSource
    "BG",  # Bunge Global
    # C
    "CDNS",  # Cadence Design Systems
    "CZR",  # Caesars Entertainment
    "CPT",  # Camden Property Trust
    "CPB",  # Campbell Soup
    "COF",  # Capital One Financial
    "CAH",  # Cardinal Health
    "KMX",  # CarMax
    "CCL",  # Carnival
    "CARR",  # Carrier Global
    "CTLT",  # Catalent
    "CBOE",  # Cboe Global Markets
    "CBRE",  # CBRE Group
    "CDW",  # CDW Corporation
    "CE",  # Celanese
    "COR",  # Cencora (formerly AmerisourceBergen)
    "CNC",  # Centene
    "CNX",  # CNX Resources
    "CDAY",  # Ceridian HCM
    "CF",  # CF Industries
    "CRL",  # Charles River Laboratories
    "SCHW",  # Charles Schwab
    "CHTR",  # Charter Communications
    "CMG",  # Chipotle Mexican Grill
    "CB",  # Chubb
    "CHD",  # Church & Dwight
    "CI",  # Cigna
    "CINF",  # Cincinnati Financial
    "CTAS",  # Cintas
    "CSCO",  # Cisco Systems
    "C",  # Citigroup
    "CFG",  # Citizens Financial Group
    "CLX",  # Clorox
    "CME",  # CME Group
    "CMS",  # CMS Energy
    "CTSH",  # Cognizant Technology
    "CL",  # Colgate-Palmolive
    "CMCSA",  # Comcast
    "CAG",  # Conagra Brands
    "COP",  # ConocoPhillips
    "ED",  # Consolidated Edison
    "STZ",  # Constellation Brands
    "CEG",  # Constellation Energy
    "COO",  # Cooper Companies
    "CPRT",  # Copart
    "GLW",  # Corning
    "CPAY",  # Corpay
    "CSGP",  # CoStar Group
    "CTRA",  # Coterra Energy
    "CCI",  # Crown Castle
    "CSX",  # CSX Corporation
    "CMI",  # Cummins
    "CVS",  # CVS Health
    # D
    "DHR",  # Danaher
    "DRI",  # Darden Restaurants
    "DVA",  # DaVita
    "DAY",  # Dayforce (Ceridian)
    "DECK",  # Deckers Outdoor
    "DE",  # Deere & Company
    "DAL",  # Delta Air Lines
    "DVN",  # Devon Energy
    "DXCM",  # DexCom
    "FANG",  # Diamondback Energy
    "DLR",  # Digital Realty Trust
    "DFS",  # Discover Financial Services
    "DG",  # Dollar General
    "DLTR",  # Dollar Tree
    "D",  # Dominion Energy
    "DPZ",  # Domino's Pizza
    "DOV",  # Dover Corporation
    "DHI",  # D.R. Horton
    "DOW",  # Dow Inc.
    "DTE",  # DTE Energy
    "DUK",  # Duke Energy
    "DD",  # DuPont de Nemours
    # E
    "EMN",  # Eastman Chemical
    "ETN",  # Eaton Corporation
    "EBAY",  # eBay
    "ECL",  # Ecolab
    "EIX",  # Edison International
    "EW",  # Edwards Lifesciences
    "EA",  # Electronic Arts
    "ELV",  # Elevance Health
    "EMR",  # Emerson Electric
    "ENPH",  # Enphase Energy
    "ETR",  # Entergy
    "EOG",  # EOG Resources
    "EPAM",  # EPAM Systems
    "EFX",  # Equifax
    "EQIX",  # Equinix
    "EQR",  # Equity Residential
    "EQT",  # EQT Corporation
    "ESS",  # Essex Property Trust
    "EL",  # Estee Lauder Companies
    "ETSY",  # Etsy
    "EG",  # Everest Group
    "EVRG",  # Evergy
    "ES",  # Eversource Energy
    "EXPD",  # Expeditors International
    "EXPE",  # Expedia Group
    "EXR",  # Extra Space Storage
    # F
    "FFIV",  # F5 Networks
    "FDS",  # FactSet Research
    "FICO",  # Fair Isaac (FICO)
    "FAST",  # Fastenal
    "FRT",  # Federal Realty Investment Trust
    "FDX",  # FedEx
    "FIS",  # Fidelity National Information Services
    "FITB",  # Fifth Third Bancorp
    "FSLR",  # First Solar
    "FE",  # FirstEnergy
    "FI",  # Fiserv
    "FMC",  # FMC Corporation
    "F",  # Ford Motor
    "FTNT",  # Fortinet
    "FTV",  # Fortive
    "FOXA",  # Fox Corporation Class A
    "FOX",  # Fox Corporation Class B
    "BEN",  # Franklin Resources
    "FCX",  # Freeport-McMoRan
    # G
    "GRMN",  # Garmin
    "IT",  # Gartner
    "GE",  # GE Aerospace
    "GEHC",  # GE HealthCare Technologies
    "GEN",  # Gen Digital
    "GNRC",  # Generac Holdings
    "GIS",  # General Mills
    "GM",  # General Motors
    "GPC",  # Genuine Parts
    "GILD",  # Gilead Sciences
    "GS",  # Goldman Sachs
    # H
    "HAL",  # Halliburton
    "HIG",  # Hartford Financial Services
    "HAS",  # Hasbro
    "HCA",  # HCA Healthcare
    "DOC",  # Healthpeak Properties
    "HSIC",  # Henry Schein
    "HSY",  # Hershey
    "HES",  # Hess Corporation
    "HPE",  # Hewlett Packard Enterprise
    "HLT",  # Hilton Worldwide
    "HOLX",  # Hologic
    "HON",  # Honeywell International
    "HRL",  # Hormel Foods
    "HST",  # Host Hotels & Resorts
    "HWM",  # Howmet Aerospace
    "HPQ",  # HP Inc.
    "HUBB",  # Hubbell
    "HUM",  # Humana
    "HBAN",  # Huntington Bancshares
    "HII",  # Huntington Ingalls Industries
    # I
    "IEX",  # IDEX Corporation
    "IDXX",  # IDEXX Laboratories
    "ITW",  # Illinois Tool Works
    "ILMN",  # Illumina
    "INCY",  # Incyte
    "IR",  # Ingersoll Rand
    "PODD",  # Insulet Corporation
    "INTC",  # Intel
    "ICE",  # Intercontinental Exchange
    "IFF",  # International Flavors & Fragrances
    "IP",  # International Paper
    "IPG",  # Interpublic Group
    "INTU",  # Intuit
    "ISRG",  # Intuitive Surgical
    "IVZ",  # Invesco
    "INVH",  # Invitation Homes
    "IQV",  # IQVIA Holdings
    "IRM",  # Iron Mountain
    # J
    "JBHT",  # J.B. Hunt Transport
    "JBL",  # Jabil Circuit
    "JKHY",  # Jack Henry & Associates
    "J",  # Jacobs Solutions
    "JCI",  # Johnson Controls
    "JNPR",  # Juniper Networks
    # K
    "K",  # Kellanova
    "KVUE",  # Kenvue
    "KDP",  # Keurig Dr Pepper
    "KEY",  # KeyCorp
    "KEYS",  # Keysight Technologies
    "KMB",  # Kimberly-Clark
    "KIM",  # Kimco Realty
    "KMI",  # Kinder Morgan
    "KLAC",  # KLA Corporation
    "KHC",  # Kraft Heinz
    "KR",  # Kroger
    # L
    "LHX",  # L3Harris Technologies
    "LH",  # Laboratory Corporation
    "LRCX",  # Lam Research
    "LW",  # Lamb Weston Holdings
    "LVS",  # Las Vegas Sands
    "LDOS",  # Leidos Holdings
    "LEN",  # Lennar
    "LII",  # Lennox International
    "LEVI",  # Levi Strauss
    "LIN",  # Linde
    "LYV",  # Live Nation Entertainment
    "LKQ",  # LKQ Corporation
    "LMT",  # Lockheed Martin
    "L",  # Loews Corporation
    "LOW",  # Lowe's Companies
    "LULU",  # Lululemon Athletica
    "LYB",  # LyondellBasell Industries
    # M
    "MTB",  # M&T Bank
    "MRO",  # Marathon Oil
    "MPC",  # Marathon Petroleum
    "MKTX",  # MarketAxess Holdings
    "MAR",  # Marriott International
    "MMC",  # Marsh & McLennan
    "MLM",  # Martin Marietta Materials
    "MAS",  # Masco
    "MTCH",  # Match Group
    "MKC",  # McCormick & Company
    "MCD",  # McDonald's
    "MCK",  # McKesson
    "MDT",  # Medtronic
    "MET",  # MetLife
    "MTD",  # Mettler-Toledo International
    "MGM",  # MGM Resorts International
    "MCHP",  # Microchip Technology
    "MU",  # Micron Technology
    "MSCI",  # MSCI Inc.
    "MNST",  # Monster Beverage
    "MCO",  # Moody's Corporation
    "MOS",  # Mosaic
    "MSI",  # Motorola Solutions
    "MHK",  # Mohawk Industries
    "MOH",  # Molina Healthcare
    "TAP",  # Molson Coors Beverage
    "MDLZ",  # Mondelez International
    "MPWR",  # Monolithic Power Systems
    "MRNA",  # Moderna
    # N
    "NDAQ",  # Nasdaq Inc.
    "NTAP",  # NetApp
    "NFLX",  # Netflix
    "NEM",  # Newmont
    "NWSA",  # News Corp Class A
    "NWS",  # News Corp Class B
    "NEE",  # NextEra Energy
    "NKE",  # Nike
    "NI",  # NiSource
    "NDSN",  # Nordson
    "NSC",  # Norfolk Southern
    "NTRS",  # Northern Trust
    "NOC",  # Northrop Grumman
    "NCLH",  # Norwegian Cruise Line Holdings
    "NRG",  # NRG Energy
    "NUE",  # Nucor
    "NVR",  # NVR Inc.
    "NXPI",  # NXP Semiconductors
    # O
    "ORLY",  # O'Reilly Automotive
    "OXY",  # Occidental Petroleum
    "ODFL",  # Old Dominion Freight Line
    "OMC",  # Omnicom Group
    "ON",  # ON Semiconductor
    "OKE",  # ONEOK
    "ORCL",  # Oracle
    "OTIS",  # Otis Worldwide
    # P
    "PCAR",  # PACCAR
    "PKG",  # Packaging Corporation
    "PANW",  # Palo Alto Networks
    "PARA",  # Paramount Global
    "PH",  # Parker Hannifin
    "PAYX",  # Paychex
    "PAYC",  # Paycom Software
    "PYPL",  # PayPal Holdings
    "PNR",  # Pentair
    "PEP",  # PepsiCo
    "PCG",  # PG&E Corporation
    "PM",  # Philip Morris International
    "PSX",  # Phillips 66
    "PNW",  # Pinnacle West Capital
    "PXD",  # Pioneer Natural Resources
    "PBI",  # Pitney Bowes
    "POOL",  # Pool Corporation
    "PPG",  # PPG Industries
    "PPL",  # PPL Corporation
    "PFG",  # Principal Financial Group
    "PGR",  # Progressive
    "PLD",  # Prologis
    "PRU",  # Prudential Financial
    "PEG",  # Public Service Enterprise Group
    "SOLV",  # Solventum (formerly 3M Health Care)
    "PTC",  # PTC Inc.
    "PSA",  # Public Storage
    "PHM",  # PulteGroup
    # Q
    "QRVO",  # Qorvo
    "PWR",  # Quanta Services
    "QCOM",  # Qualcomm
    # R
    "RL",  # Ralph Lauren
    "RJF",  # Raymond James Financial
    "RTX",  # RTX Corporation (Raytheon)
    "O",  # Realty Income
    "REG",  # Regency Centers
    "REGN",  # Regeneron Pharmaceuticals
    "RF",  # Regions Financial
    "RSG",  # Republic Services
    "RMD",  # ResMed
    "RVTY",  # Revvity (formerly PerkinElmer)
    "ROK",  # Rockwell Automation
    "ROL",  # Rollins
    "ROP",  # Roper Technologies
    "ROST",  # Ross Stores
    "RCL",  # Royal Caribbean Cruises
    # S
    "SPGI",  # S&P Global
    "CRM",  # Salesforce
    "SBAC",  # SBA Communications
    "SLB",  # Schlumberger (SLB)
    "STX",  # Seagate Technology
    "SEE",  # Sealed Air
    "SRE",  # Sempra Energy
    "NOW",  # ServiceNow
    "SHW",  # Sherwin-Williams
    "SPG",  # Simon Property Group
    "SWKS",  # Skyworks Solutions
    "SJM",  # Smucker (J.M.)
    "SNA",  # Snap-on
    "SO",  # Southern Company
    "LUV",  # Southwest Airlines
    "SWK",  # Stanley Black & Decker
    "SBUX",  # Starbucks
    "STT",  # State Street
    "STLD",  # Steel Dynamics
    "STE",  # STERIS
    "SYK",  # Stryker
    "SYF",  # Synchrony Financial
    "SNPS",  # Synopsys
    "SYY",  # Sysco
    # T
    "TMUS",  # T-Mobile US
    "TROW",  # T. Rowe Price
    "TTWO",  # Take-Two Interactive
    "TPR",  # Tapestry
    "TRGP",  # Targa Resources
    "TGT",  # Target
    "TEL",  # TE Connectivity
    "TDY",  # Teledyne Technologies
    "TFX",  # Teleflex
    "TER",  # Teradyne
    "TXN",  # Texas Instruments
    "TXT",  # Textron
    "TMO",  # Thermo Fisher Scientific
    "TJX",  # TJX Companies
    "TSCO",  # Tractor Supply
    "TT",  # Trane Technologies
    "TDG",  # TransDigm Group
    "TRV",  # Travelers Companies
    "TRMB",  # Trimble Inc.
    "TFC",  # Truist Financial
    "TYL",  # Tyler Technologies
    "TSN",  # Tyson Foods
    # U
    "USB",  # U.S. Bancorp
    "UBER",  # Uber Technologies
    "UDR",  # UDR Inc.
    "ULTA",  # Ulta Beauty
    "UNP",  # Union Pacific
    "UAL",  # United Airlines Holdings
    "UPS",  # United Parcel Service
    "URI",  # United Rentals
    "UHS",  # Universal Health Services
    # V
    "VLO",  # Valero Energy
    "VTR",  # Ventas
    "VLTO",  # Veralto
    "VRSN",  # VeriSign
    "VRSK",  # Verisk Analytics
    "VZ",  # Verizon Communications
    "VRTX",  # Vertex Pharmaceuticals
    "VTRS",  # Viatris
    "VICI",  # VICI Properties
    "VMC",  # Vulcan Materials
    # W
    "WRB",  # W.R. Berkley
    "GWW",  # W.W. Grainger
    "WAB",  # Wabtec Corporation
    "WBA",  # Walgreens Boots Alliance
    "WAT",  # Waters Corporation
    "WEC",  # WEC Energy Group
    "WFC",  # Wells Fargo
    "WELL",  # Welltower
    "WST",  # West Pharmaceutical Services
    "WDC",  # Western Digital
    "WY",  # Weyerhaeuser
    "WHR",  # Whirlpool
    "WMB",  # Williams Companies
    "WTW",  # Willis Towers Watson
    "XEL",  # Xcel Energy
    "XYL",  # Xylem
    # Y
    "YUM",  # Yum! Brands
    # Z
    "ZBRA",  # Zebra Technologies
    "ZBH",  # Zimmer Biomet Holdings
    "ZION",  # Zions Bancorporation
    "ZTS",  # Zoetis
]

# ---------------------------------------------------------------------------
# Global indices — (symbol, exchange) tuples
# ---------------------------------------------------------------------------
_GLOBAL_INDICES: list[tuple[str, str]] = [
    ("GDAXI", "INDX"),  # DAX
    ("FTSE", "INDX"),  # FTSE 100
    ("FCHI", "INDX"),  # CAC 40
    ("STOXX50E", "INDX"),  # Euro Stoxx 50
    ("N225", "INDX"),  # Nikkei 225
    ("HSI", "INDX"),  # Hang Seng
    ("000001.SS", "SHG"),  # Shanghai Composite
]


# ---------------------------------------------------------------------------
# ID helpers for downgrade
# ---------------------------------------------------------------------------


def _sp500_policy_ids() -> list[str]:
    ids: list[str] = []
    for sym in _NEW_SP500_SYMBOLS:
        ids.append(_ulid_from_seed(f"eodhd:fundamentals:{sym}:US::General"))
        for tf in ("1d", "1w", "1mo"):
            ids.append(_ulid_from_seed(f"eodhd:ohlcv:{sym}:US:{tf}:"))
    return ids


def _index_policy_ids() -> list[str]:
    ids: list[str] = []
    for sym, exch in _GLOBAL_INDICES:
        for tf in ("1d", "1w", "1mo"):
            ids.append(_ulid_from_seed(f"eodhd:ohlcv:{sym}:{exch}:{tf}:"))
    return ids


# ---------------------------------------------------------------------------
# Upgrade / Downgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    now = datetime.now(tz=UTC)
    conn = op.get_bind()

    # ---------------------------------------------------------------
    # 1. Fundamentals + OHLCV policies for new S&P 500 constituents
    # ---------------------------------------------------------------
    for sym in _NEW_SP500_SYMBOLS:
        # fundamentals — daily, priority 2
        conn.execute(
            sa.text(
                """
                INSERT INTO polling_policies (
                    id, provider, dataset_type, dataset_variant,
                    symbol, exchange, timeframe,
                    base_interval_sec, min_interval_sec, jitter_sec,
                    adaptive_enabled, adaptive_k, adaptive_half_life_sec,
                    priority, enabled, backfill_enabled,
                    backfill_start_date, backfill_chunk_days,
                    market_hours_only, tier, post_market_only,
                    created_at, updated_at
                ) VALUES (
                    :id, :provider, :dataset_type, :dataset_variant,
                    :symbol, :exchange, :timeframe,
                    :base_interval_sec, :min_interval_sec, :jitter_sec,
                    :adaptive_enabled, :adaptive_k, :adaptive_half_life_sec,
                    :priority, :enabled, :backfill_enabled,
                    :backfill_start_date, :backfill_chunk_days,
                    :market_hours_only, :tier, :post_market_only,
                    :created_at, :updated_at
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": _ulid_from_seed(f"eodhd:fundamentals:{sym}:US::General"),
                "provider": "eodhd",
                "dataset_type": "fundamentals",
                "dataset_variant": "General",
                "symbol": sym,
                "exchange": "US",
                "timeframe": None,
                "base_interval_sec": 86400,
                "min_interval_sec": 3600,
                "jitter_sec": 300,
                "adaptive_enabled": False,
                "adaptive_k": 1.0,
                "adaptive_half_life_sec": 3600,
                "priority": 2,
                "enabled": True,
                "backfill_enabled": False,
                "backfill_start_date": None,
                "backfill_chunk_days": None,
                "market_hours_only": False,
                "tier": 2,
                "post_market_only": False,
                "created_at": now,
                "updated_at": now,
            },
        )

        # OHLCV 1d / 1w / 1mo
        for tf, base_int, prio in [("1d", 21600, 5), ("1w", 43200, 4), ("1mo", 86400, 3)]:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO polling_policies (
                        id, provider, dataset_type, dataset_variant,
                        symbol, exchange, timeframe,
                        base_interval_sec, min_interval_sec, jitter_sec,
                        adaptive_enabled, adaptive_k, adaptive_half_life_sec,
                        priority, enabled, backfill_enabled,
                        backfill_start_date, backfill_chunk_days,
                        market_hours_only, tier, post_market_only,
                        created_at, updated_at
                    ) VALUES (
                        :id, :provider, :dataset_type, :dataset_variant,
                        :symbol, :exchange, :timeframe,
                        :base_interval_sec, :min_interval_sec, :jitter_sec,
                        :adaptive_enabled, :adaptive_k, :adaptive_half_life_sec,
                        :priority, :enabled, :backfill_enabled,
                        :backfill_start_date, :backfill_chunk_days,
                        :market_hours_only, :tier, :post_market_only,
                        :created_at, :updated_at
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": _ulid_from_seed(f"eodhd:ohlcv:{sym}:US:{tf}:"),
                    "provider": "eodhd",
                    "dataset_type": "ohlcv",
                    "dataset_variant": None,
                    "symbol": sym,
                    "exchange": "US",
                    "timeframe": tf,
                    "base_interval_sec": base_int,
                    "min_interval_sec": 3600,
                    "jitter_sec": 60,
                    "adaptive_enabled": False,
                    "adaptive_k": 1.0,
                    "adaptive_half_life_sec": 3600,
                    "priority": prio,
                    "enabled": True,
                    "backfill_enabled": False,
                    "backfill_start_date": None,
                    "backfill_chunk_days": None,
                    "market_hours_only": False,
                    "tier": 2,
                    "post_market_only": False,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    # ---------------------------------------------------------------
    # 2. OHLCV policies for global indices
    # ---------------------------------------------------------------
    for sym, exch in _GLOBAL_INDICES:
        for tf, base_int, prio in [("1d", 21600, 5), ("1w", 43200, 4), ("1mo", 86400, 3)]:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO polling_policies (
                        id, provider, dataset_type, dataset_variant,
                        symbol, exchange, timeframe,
                        base_interval_sec, min_interval_sec, jitter_sec,
                        adaptive_enabled, adaptive_k, adaptive_half_life_sec,
                        priority, enabled, backfill_enabled,
                        backfill_start_date, backfill_chunk_days,
                        market_hours_only, tier, post_market_only,
                        created_at, updated_at
                    ) VALUES (
                        :id, :provider, :dataset_type, :dataset_variant,
                        :symbol, :exchange, :timeframe,
                        :base_interval_sec, :min_interval_sec, :jitter_sec,
                        :adaptive_enabled, :adaptive_k, :adaptive_half_life_sec,
                        :priority, :enabled, :backfill_enabled,
                        :backfill_start_date, :backfill_chunk_days,
                        :market_hours_only, :tier, :post_market_only,
                        :created_at, :updated_at
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": _ulid_from_seed(f"eodhd:ohlcv:{sym}:{exch}:{tf}:"),
                    "provider": "eodhd",
                    "dataset_type": "ohlcv",
                    "dataset_variant": None,
                    "symbol": sym,
                    "exchange": exch,
                    "timeframe": tf,
                    "base_interval_sec": base_int,
                    "min_interval_sec": 3600,
                    "jitter_sec": 60,
                    "adaptive_enabled": False,
                    "adaptive_k": 1.0,
                    "adaptive_half_life_sec": 3600,
                    "priority": prio,
                    "enabled": True,
                    "backfill_enabled": False,
                    "backfill_start_date": None,
                    "backfill_chunk_days": None,
                    "market_hours_only": False,
                    "tier": 2,
                    "post_market_only": False,
                    "created_at": now,
                    "updated_at": now,
                },
            )


def downgrade() -> None:
    conn = op.get_bind()
    all_ids = _sp500_policy_ids() + _index_policy_ids()
    conn.execute(
        sa.text("DELETE FROM polling_policies WHERE id = ANY(:ids)").bindparams(
            sa.bindparam("ids", value=all_ids, type_=sa.ARRAY(sa.String))
        )
    )
