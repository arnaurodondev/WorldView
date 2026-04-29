#!/usr/bin/env python3
"""Backfill script: populate instrument_fundamentals_snapshot for top-100 symbols.

WHY THIS SCRIPT EXISTS (PLAN-0050 T-D-4-03):
  The FundamentalsTab and InstrumentKeyMetrics panel in the frontend show "—"
  placeholders for eps_ttm, beta, avg_volume_30d, operating_cash_flow, capex,
  free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda, and
  credit_rating.  This script reads existing JSONB fundamentals section data from
  the market_data DB and derives the 10 values, UPSERTing one row per instrument.

  WHY run from market-ingestion (not market-data):
  The market-ingestion service is the owner of EODHD data pipelines — all
  data-fetch and write scripts live here.  Market-data is read-only from the
  outside; writes always go via the ingestion pipeline or trusted backfill scripts.

HOW IT WORKS:
  1. Connect to the market_data PostgreSQL database using asyncpg.
  2. For each known ticker, look up the instrument UUID in the instruments table.
  3. Read the most recent row from relevant section tables (highlights,
     cash_flow_statements, income_statements, balance_sheets, technicals_snapshots).
  4. Extract raw values with safe NULL handling.
  5. Compute derived values (FCF, FCF margin, interest coverage, net debt/EBITDA).
  6. UPSERT into instrument_fundamentals_snapshot (idempotent).

KNOWN LIMITATIONS (documented per task spec):
  - avg_volume_30d: EODHD Technicals section key "AverageVolume" not consistently
    present; falls back to NULL when missing.
  - credit_rating: Not available in standard EODHD Fundamentals response;
    EODHD does not expose S&P/Moody's credit ratings via their public API.
    This field will be NULL unless a future provider exposes it.

USAGE (dev environment):
  cd services/market-ingestion
  DATABASE_URL="postgresql://..." python scripts/backfill_fundamentals.py

ENV VARS:
  DATABASE_URL  — asyncpg-compatible postgres URL (required)
                  e.g. postgresql://user:pass@localhost/market_data
  BATCH_SIZE    — number of symbols per DB flush (default: 10)
  DRY_RUN       — set to "1" to skip UPSERTs and only log computed values
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

# ── Structured logging (project convention: structlog always) ──────────────────
# WHY: CLAUDE.md Rule 10 — structlog only.  This script imports directly so it
# can run without the full service stack.
try:
    import structlog

    log = structlog.get_logger(__name__)
except ImportError:
    # Fallback for environments where structlog is not installed
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(__name__)  # type: ignore[assignment]

# ── Top-100 equity symbols for the backfill ────────────────────────────────────
# WHY hardcoded here (not from DB): the backfill script must be runnable
# independently of the live ingestion stack.  The list mirrors the seed symbols
# in alembic/versions/0002_initial_seeds.py for the equity instruments.
# ETFs, indices, crypto, and forex are excluded: they have no earnings or debt
# fundamentals that would produce meaningful snapshot values.
TOP_EQUITY_SYMBOLS = [
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
    # Extended S&P 500 coverage
    "ADBE",
    "CRM",
    "ORCL",
    "CSCO",
    "INTC",
    "AMD",
    "QCOM",
    "TXN",
    "AVGO",
    "MU",
    "NFLX",
    "SBUX",
    "NKE",
    "MCD",
    "PEP",
    "TMO",
    "ABT",
    "MDT",
    "BMY",
    "GILD",
    "AMGN",
    "VRTX",
    "REGN",
    "SYK",
    "ZTS",
    "NEE",
    "DUK",
    "SO",
    "D",
    "AEP",
    "GS",
    "BAC",
    "C",
    "WFC",
    "USB",
    "BLK",
    "SCHW",
    "MET",
    "PRU",
    "AON",
    "LOW",
    "TGT",
    "BABA",
    "TSM",
    "SAP",
    "UPS",
    "FDX",
    "DAL",
    "UAL",
    "LUV",
    "DE",
    "HON",
    "GE",
    "MMM",
    "LMT",
    "RTX",
    "NOC",
    "HII",
    "TDG",
    "L",
    "COP",
    "SLB",
    "HAL",
    "VLO",
    "MPC",
    "AMT",
    "PLD",
    "CCI",
    "SPG",
    "O",
]


# ── Derivation helpers ─────────────────────────────────────────────────────────


def _safe_float(val: Any, label: str = "") -> float | None:
    """Coerce a JSONB value to float, returning None on failure.

    WHY safe (not strict): EODHD JSONB blobs may contain null, empty string,
    "N/A", or numeric-as-string variants.  Rather than crashing the backfill
    for one bad field, we log and continue with NULL.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, int | float):
        return float(val)
    if isinstance(val, str):
        cleaned = val.strip()
        if cleaned.lower() in {"", "n/a", "na", "none", "null", "nan", "-", "--"}:
            return None
        # Parenthesized negatives: (1234.5) → -1234.5
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = f"-{cleaned[1:-1]}"
        cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            if label:
                log.debug("backfill.coerce_failed", label=label, raw=str(val)[:50])
            return None
    if isinstance(val, Decimal):
        try:
            return float(val)
        except (InvalidOperation, ValueError):
            return None
    return None


def _try_keys(data: dict[str, Any], *keys: str) -> float | None:
    """Try multiple JSONB keys in order; return first coercible non-None value."""
    for key in keys:
        val = data.get(key)
        result = _safe_float(val, label=key)
        if result is not None:
            return result
    return None


def derive_fundamentals_snapshot(
    *,
    highlights: dict[str, Any],
    cash_flow: dict[str, Any],
    income: dict[str, Any],
    balance: dict[str, Any],
    technicals: dict[str, Any],
) -> dict[str, Any]:
    """Compute all 10 snapshot fields from EODHD section JSONB data.

    WHY compute here (not in SQL): derived formulas involve division with
    safe NULL semantics and the logic is easier to test in Python than in SQL.

    EODHD field names (confirmed from API docs 2024-Q4):
      Highlights: EarningsShare, RevenueTTM, EBITDA, MarketCapitalization
      Technicals: Beta, AverageVolume (not always present)
      CashFlow:   operatingCashFlow / totalCashFromOperatingActivities, capitalExpenditures
      Income:     ebit, interestExpense
      Balance:    cash / cashAndEquivalents, longTermDebt + shortLongTermDebt, netDebt
    """
    # ── EPS TTM ───────────────────────────────────────────────────────────────
    eps_ttm = _try_keys(highlights, "EarningsShare", "DilutedEpsTTM", "eps", "EPS")

    # ── Beta ──────────────────────────────────────────────────────────────────
    beta = _try_keys(technicals, "Beta", "beta")

    # ── Average volume 30D ────────────────────────────────────────────────────
    # EODHD NOTE: "AverageVolume" is present in the Technicals section for
    # most large-cap US equities.  Small-cap or foreign listings may lack it.
    avg_volume_raw = _try_keys(technicals, "AverageVolume", "averageVolume")
    avg_volume_30d: int | None = int(avg_volume_raw) if avg_volume_raw is not None else None

    # ── Operating Cash Flow ───────────────────────────────────────────────────
    operating_cf = _try_keys(
        cash_flow,
        "operatingCashFlow",
        "totalCashFromOperatingActivities",
        "OperatingCashFlow",
    )

    # ── Capital Expenditures (CapEx) ──────────────────────────────────────────
    # WHY abs(): EODHD reports capex as a negative number in the CF statement
    # (it's a cash outflow).  We store the absolute value for clarity in the UI;
    # the FCF derivation below subtracts it explicitly.
    capex_raw = _try_keys(cash_flow, "capitalExpenditures", "CapitalExpenditures")
    capex: float | None = abs(capex_raw) if capex_raw is not None else None

    # ── Free Cash Flow (derived) ──────────────────────────────────────────────
    free_cash_flow: float | None = None
    if operating_cf is not None and capex is not None:
        free_cash_flow = operating_cf - capex

    # ── FCF Margin (derived) ──────────────────────────────────────────────────
    # FCF margin = FCF / Revenue;  NULL when revenue = 0 or missing.
    fcf_margin: float | None = None
    if free_cash_flow is not None:
        revenue = _try_keys(highlights, "RevenueTTM", "Revenue", "revenue")
        if revenue and revenue != 0:
            fcf_margin = free_cash_flow / revenue

    # ── Interest Coverage (derived) ───────────────────────────────────────────
    # interest_coverage = EBIT / interest_expense
    # WHY EBIT from income statement (not highlights): the income statement section
    # stores the actual annual EBIT figure; highlights.EBITDA would need depreciation
    # subtracted which we don't have available in this context.
    interest_coverage: float | None = None
    ebit = _try_keys(income, "ebit", "EBIT", "operatingIncome")
    interest_expense = _try_keys(income, "interestExpense", "InterestExpense")
    if ebit is not None and interest_expense is not None and interest_expense != 0:
        interest_coverage = ebit / abs(interest_expense)

    # ── Net Debt / EBITDA (derived) ───────────────────────────────────────────
    # net_debt_to_ebitda = (total_debt - cash) / EBITDA
    # WHY prefer netDebt from balance sheet when available: EODHD sometimes provides
    # a pre-computed netDebt figure that is more accurate than the sum approach.
    net_debt_to_ebitda: float | None = None
    ebitda = _try_keys(highlights, "EBITDA", "EBITDAttm", "ebitda")
    if ebitda is not None and ebitda > 0:
        # Try pre-computed net debt first
        net_debt = _try_keys(balance, "netDebt", "NetDebt")
        if net_debt is None:
            # Derive: net_debt = total_debt - cash_and_equivalents
            total_debt = _try_keys(balance, "shortLongTermDebtTotal", "shortLongTermDebt", "longTermDebt")
            cash = _try_keys(balance, "cashAndEquivalents", "cash", "Cash")
            if total_debt is not None and cash is not None:
                net_debt = total_debt - cash
        if net_debt is not None:
            net_debt_to_ebitda = net_debt / ebitda

    # ── Credit Rating ─────────────────────────────────────────────────────────
    # WHY NULL: EODHD standard Fundamentals endpoint does NOT expose credit ratings
    # (S&P/Moody's/Fitch).  This would require a separate credit-rating data source.
    # Documented limitation — Wave D accepts NULL; a future data provider wave
    # (e.g. Bloomberg Data License, S&P Market Intelligence) could populate this.
    credit_rating: str | None = None

    return {
        "eps_ttm": eps_ttm,
        "beta": beta,
        "avg_volume_30d": avg_volume_30d,
        "operating_cash_flow": operating_cf,
        "capex": capex,
        "free_cash_flow": free_cash_flow,
        "fcf_margin": fcf_margin,
        "interest_coverage": interest_coverage,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "credit_rating": credit_rating,
    }


# ── Database helpers ───────────────────────────────────────────────────────────


async def _fetch_latest_section(
    conn: Any,
    instrument_id: str,
    table_name: str,
) -> dict[str, Any]:
    """Return the most recent data JSONB blob for an instrument + section table.

    WHY ORDER BY ingested_at DESC LIMIT 1: fundamentals are re-ingested
    periodically; the most recent row is the current snapshot.
    Returns an empty dict if no row exists (instrument not yet ingested).
    """
    row = await conn.fetchrow(
        f"""
        SELECT data FROM {table_name}
        WHERE instrument_id = $1
        ORDER BY ingested_at DESC
        LIMIT 1
        """,  # noqa: S608
        instrument_id,
    )
    if row is None:
        return {}
    data = row["data"]
    if isinstance(data, str):
        # asyncpg with JSONB codec configured → already dict; without codec → str
        return json.loads(data)  # type: ignore[no-any-return]
    return data or {}  # type: ignore[return-value]


async def _upsert_snapshot(
    conn: Any,
    instrument_id: str,
    snap: dict[str, Any],
    *,
    dry_run: bool,
) -> None:
    """UPSERT one snapshot row into instrument_fundamentals_snapshot.

    WHY ON CONFLICT DO UPDATE: the backfill must be idempotent — running it
    twice should produce the same result.  The primary key is instrument_id
    so the ON CONFLICT clause updates all computed columns on duplicate.
    """
    if dry_run:
        log.info(
            "backfill.dry_run",
            instrument_id=instrument_id,
            eps_ttm=snap.get("eps_ttm"),
            beta=snap.get("beta"),
            fcf=snap.get("free_cash_flow"),
        )
        return

    await conn.execute(
        """
        INSERT INTO instrument_fundamentals_snapshot (
            instrument_id,
            eps_ttm, beta, avg_volume_30d,
            operating_cash_flow, capex, free_cash_flow, fcf_margin,
            interest_coverage, net_debt_to_ebitda, credit_rating,
            updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now()
        )
        ON CONFLICT (instrument_id) DO UPDATE SET
            eps_ttm             = EXCLUDED.eps_ttm,
            beta                = EXCLUDED.beta,
            avg_volume_30d      = EXCLUDED.avg_volume_30d,
            operating_cash_flow = EXCLUDED.operating_cash_flow,
            capex               = EXCLUDED.capex,
            free_cash_flow      = EXCLUDED.free_cash_flow,
            fcf_margin          = EXCLUDED.fcf_margin,
            interest_coverage   = EXCLUDED.interest_coverage,
            net_debt_to_ebitda  = EXCLUDED.net_debt_to_ebitda,
            credit_rating       = EXCLUDED.credit_rating,
            updated_at          = now()
        """,
        instrument_id,
        snap["eps_ttm"],
        snap["beta"],
        snap["avg_volume_30d"],
        snap["operating_cash_flow"],
        snap["capex"],
        snap["free_cash_flow"],
        snap["fcf_margin"],
        snap["interest_coverage"],
        snap["net_debt_to_ebitda"],
        snap["credit_rating"],
    )


# ── Main backfill loop ─────────────────────────────────────────────────────────


async def run_backfill(
    database_url: str,
    symbols: list[str],
    *,
    batch_size: int = 10,
    dry_run: bool = False,
) -> None:
    """Execute the full backfill for *symbols* against *database_url*.

    PLAN-0050 T-D-4-03 requirements:
    - Set application_name="market-ingestion-backfill-fundamentals" (BP-256)
    - Set command_timeout=300 (BP-256)
    - Register JSONB type codec (BP-256)
    - Idempotent UPSERT
    - Treat NULL gracefully; do NOT crash on missing data
    """
    try:
        import asyncpg  # type: ignore[import-not-found]
    except ImportError:
        log.error("backfill.asyncpg_missing", msg="pip install asyncpg")
        sys.exit(1)

    # WHY application_name: identifies this connection in pg_stat_activity;
    # critical for DBA observability when long-running backfills run in prod.
    conn: Any = await asyncpg.connect(
        database_url,
        server_settings={"application_name": "market-ingestion-backfill-fundamentals"},
        command_timeout=300,  # BP-256: never hang indefinitely
    )

    # WHY register jsonb codec: asyncpg returns JSONB columns as raw strings by
    # default.  Registering this codec makes asyncpg decode them to Python dicts
    # automatically, matching the behaviour the rest of the codebase expects.
    # BP-256: always register when reading or writing JSONB over asyncpg.
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )

    log.info(
        "backfill.start",
        symbols_count=len(symbols),
        batch_size=batch_size,
        dry_run=dry_run,
    )

    ok = 0
    skipped = 0
    errors = 0

    for i, ticker in enumerate(symbols):
        try:
            # Look up instrument UUID by ticker symbol
            row = await conn.fetchrow(
                "SELECT id FROM instruments WHERE symbol = $1 LIMIT 1",
                ticker,
            )
            if row is None:
                log.debug("backfill.instrument_not_found", ticker=ticker)
                skipped += 1
                continue

            instrument_id: str = str(row["id"])

            # Fetch latest rows from all required section tables sequentially.
            # WHY NOT asyncio.gather: a single asyncpg connection can only execute
            # one statement at a time — gathering across the same connection
            # raises InterfaceError("another operation is in progress").  Use
            # sequential awaits (each section table is a small indexed lookup,
            # ≪10ms — no meaningful gain from parallelism here).  This bug was
            # caught by F-DP1-03 (PLAN-0050 deep iter-1 QA): backfill returned
            # 100 errors and 0 successes.
            highlights = await _fetch_latest_section(conn, instrument_id, "highlights")
            cash_flow = await _fetch_latest_section(conn, instrument_id, "cash_flow_statements")
            income = await _fetch_latest_section(conn, instrument_id, "income_statements")
            balance = await _fetch_latest_section(conn, instrument_id, "balance_sheets")
            technicals = await _fetch_latest_section(conn, instrument_id, "technicals_snapshots")

            # Compute derived metrics (NULL-safe — missing sections → all NULLs)
            snap = derive_fundamentals_snapshot(
                highlights=highlights,
                cash_flow=cash_flow,
                income=income,
                balance=balance,
                technicals=technicals,
            )

            await _upsert_snapshot(conn, instrument_id, snap, dry_run=dry_run)
            ok += 1

            if (i + 1) % batch_size == 0:
                log.info(
                    "backfill.progress",
                    processed=i + 1,
                    total=len(symbols),
                    ok=ok,
                    skipped=skipped,
                    errors=errors,
                )

        except Exception as exc:
            log.error(
                "backfill.symbol_error",
                ticker=ticker,
                error=str(exc),
                exc_info=True,
            )
            errors += 1
            # WHY continue on error: a single bad instrument should not abort
            # the entire backfill.  The next run will retry failed instruments.

    await conn.close()

    log.info(
        "backfill.complete",
        total=len(symbols),
        ok=ok,
        skipped=skipped,
        errors=errors,
    )

    if errors:
        sys.exit(1)


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(  # noqa: T201
            "ERROR: DATABASE_URL env var is required.\n"
            "Example: DATABASE_URL=postgresql://user:pass@localhost/market_data "
            "python scripts/backfill_fundamentals.py",
            file=sys.stderr,
        )
        sys.exit(1)

    batch_size = int(os.environ.get("BATCH_SIZE", "10"))
    dry_run = os.environ.get("DRY_RUN", "0") == "1"

    asyncio.run(
        run_backfill(
            database_url,
            TOP_EQUITY_SYMBOLS,
            batch_size=batch_size,
            dry_run=dry_run,
        )
    )


if __name__ == "__main__":
    main()
