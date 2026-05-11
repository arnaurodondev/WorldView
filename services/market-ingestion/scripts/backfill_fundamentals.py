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
  6. PLAN-0053 T-C-3-02: when EODHD returns NULL for eps_ttm or beta, fall back
     to Alpha Vantage's OVERVIEW endpoint and tag the source per field.
  7. UPSERT into instrument_fundamentals_snapshot (idempotent).

PLAN-0053 T-C-3-01 — Coverage observability:
  - Each ticker emits a structured per-field "backfill.field_coverage" event with
    populated/null status across all 10 frontend-displayed fields.
  - At end-of-run, an aggregate "backfill.field_population_pct" event is emitted
    with the percentage of tickers populated per field.
  - With ``--export-coverage=<path.csv>`` the script writes a per-ticker x per-field
    coverage matrix (rows = tickers, columns = fields, cells = populated/null/error).

KNOWN LIMITATIONS (documented per task spec):
  - avg_volume_30d: EODHD Technicals section key "AverageVolume" not consistently
    present; falls back to NULL when missing.
  - credit_rating: Not available in standard EODHD Fundamentals response;
    EODHD does not expose S&P/Moody's credit ratings via their public API.
    This field will be NULL unless a future provider exposes it.

USAGE (dev environment):
  cd services/market-ingestion
  DATABASE_URL="postgresql://..." python scripts/backfill_fundamentals.py
  # Export coverage matrix for ops review:
  DATABASE_URL=... python scripts/backfill_fundamentals.py --export-coverage=cov.csv

ENV VARS:
  DATABASE_URL          — asyncpg-compatible postgres URL (required)
                          e.g. postgresql://user:pass@localhost/market_data
  BATCH_SIZE            — number of symbols per DB flush (default: 10)
  DRY_RUN               — set to "1" to skip UPSERTs and only log computed values
  ALPHA_VANTAGE_API_KEY — optional; enables AV fallback for eps_ttm + beta
                          (PLAN-0053 T-C-3-02). Empty/unset → AV fallback skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
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


# ── Frontend-displayed fields (PLAN-0053 T-C-3-01 coverage observability) ────
# These are the 10 fields rendered by FundamentalsTab.tsx in the "Debt & Credit"
# and "Cash Flow" sections plus the basic Beta / Avg-Volume / EPS metrics. The
# coverage logger tracks populated/null/error for each ticker x each field so
# operators can see exactly where EODHD is short and where the Alpha Vantage
# fallback (T-C-3-02) recovered a value.
_FRONTEND_FIELDS: tuple[str, ...] = (
    "eps_ttm",
    "beta",
    "avg_volume_30d",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "fcf_margin",
    "interest_coverage",
    "net_debt_to_ebitda",
    "credit_rating",
)


def _coverage_status(value: Any) -> str:
    """Return ``populated`` if ``value is not None`` else ``null``.

    WHY a tiny helper: the field-coverage logger and the CSV writer must agree
    exactly on the populated/null encoding — keeping the logic in one place
    avoids divergence (e.g. one path treating 0.0 as null and the other not).
    """
    return "populated" if value is not None else "null"


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
    eps_ttm_source: str | None = None,
    beta_source: str | None = None,
    has_source_columns: bool = False,
) -> None:
    """UPSERT one snapshot row into instrument_fundamentals_snapshot.

    WHY ON CONFLICT DO UPDATE: the backfill must be idempotent — running it
    twice should produce the same result.  The primary key is instrument_id
    so the ON CONFLICT clause updates all computed columns on duplicate.

    PLAN-0053 T-C-3-02: ``eps_ttm_source`` / ``beta_source`` are written when
    the destination DB has the ``eps_ttm_source``/``beta_source`` columns
    (added by market-data migration 013).  ``has_source_columns=False``
    falls back to the original 11-column INSERT — keeps the script working
    against pre-migration databases (e.g. local dev that hasn't migrated).
    """
    if dry_run:
        log.info(
            "backfill.dry_run",
            instrument_id=instrument_id,
            eps_ttm=snap.get("eps_ttm"),
            eps_ttm_source=eps_ttm_source,
            beta=snap.get("beta"),
            beta_source=beta_source,
            fcf=snap.get("free_cash_flow"),
        )
        return

    if has_source_columns:
        # Extended INSERT including the two source columns (T-C-3-02).
        await conn.execute(
            """
            INSERT INTO instrument_fundamentals_snapshot (
                instrument_id,
                eps_ttm, beta, avg_volume_30d,
                operating_cash_flow, capex, free_cash_flow, fcf_margin,
                interest_coverage, net_debt_to_ebitda, credit_rating,
                eps_ttm_source, beta_source,
                updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, now()
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
                eps_ttm_source      = EXCLUDED.eps_ttm_source,
                beta_source         = EXCLUDED.beta_source,
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
            eps_ttm_source,
            beta_source,
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


async def _column_exists(conn: Any, table: str, column: str) -> bool:
    """Return True iff the given column exists on the given table.

    WHY runtime check (not config flag): the script lives in market-ingestion
    but the DDL it depends on lives in market-data alembic migrations.  When
    operators run the backfill against a database whose migration has not yet
    been applied (e.g. local dev that's behind master), the script must still
    work against the original 11-column schema — silently skipping the source
    columns rather than crashing on a missing-column error.
    """
    row = await conn.fetchrow(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = $1 AND column_name = $2
        LIMIT 1
        """,
        table,
        column,
    )
    return row is not None


# ── Main backfill loop ─────────────────────────────────────────────────────────


async def run_backfill(
    database_url: str,
    symbols: list[str],
    *,
    batch_size: int = 10,
    dry_run: bool = False,
    export_coverage_path: str | None = None,
    alpha_vantage_api_key: str | None = None,
) -> None:
    """Execute the full backfill for *symbols* against *database_url*.

    PLAN-0050 T-D-4-03 requirements:
    - Set application_name="market-ingestion-backfill-fundamentals" (BP-256)
    - Set command_timeout=300 (BP-256)
    - Register JSONB type codec (BP-256)
    - Idempotent UPSERT
    - Treat NULL gracefully; do NOT crash on missing data

    PLAN-0053 T-C-3-01:
    - Per-field structured logging (``backfill.field_coverage`` per ticker).
    - Aggregate ``backfill.field_population_pct`` at end-of-run.
    - Optional ``export_coverage_path`` writes a per-ticker x per-field CSV.

    PLAN-0053 T-C-3-02:
    - When ``alpha_vantage_api_key`` is provided AND eps_ttm or beta is NULL
      after EODHD-derivation, query Alpha Vantage's OVERVIEW endpoint to fill
      the gap. Source is recorded as ``eodhd | alpha_vantage | none`` per
      field when the destination DB has the source columns (migration 013).
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

    # PLAN-0053 T-C-3-02: probe for the migration-013 columns once per run so
    # the per-row UPSERT doesn't repeat the information_schema query 100x.
    # Both columns are added together by the same migration so probing one is
    # sufficient.
    has_source_columns = await _column_exists(conn, "instrument_fundamentals_snapshot", "eps_ttm_source")

    # PLAN-0053 T-C-3-02: lazily construct the Alpha Vantage adapter only when
    # an API key is provided and the source columns exist (otherwise the AV
    # value would be written but the source column wouldn't — confusing audit
    # trail).  Import is local to avoid a hard dependency on the adapter when
    # the script runs without AV configured.
    av_adapter = None
    if alpha_vantage_api_key and has_source_columns:
        try:
            from market_ingestion.infrastructure.external.alpha_vantage_adapter import (  # type: ignore[import-untyped]
                AlphaVantageFundamentalsAdapter,
            )

            av_adapter = AlphaVantageFundamentalsAdapter(api_key=alpha_vantage_api_key)
            log.info("backfill.alpha_vantage_enabled")
        except ImportError as exc:
            log.warning("backfill.alpha_vantage_unavailable", error=str(exc))

    log.info(
        "backfill.start",
        symbols_count=len(symbols),
        batch_size=batch_size,
        dry_run=dry_run,
        has_source_columns=has_source_columns,
        alpha_vantage_enabled=av_adapter is not None,
        export_coverage_path=export_coverage_path,
    )

    ok = 0
    skipped = 0
    errors = 0

    # PLAN-0053 T-C-3-01: per-ticker x per-field coverage matrix used both for
    # the optional CSV export and the aggregate end-of-run percentage event.
    # Each cell is one of "populated" | "null" | "error" (errors are tickers
    # where derivation crashed before producing a snapshot).
    coverage_matrix: dict[str, dict[str, str]] = {}

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

            # ── Source attribution (T-C-3-02) ─────────────────────────────────
            # When EODHD provided a value the source is "eodhd"; otherwise we
            # try Alpha Vantage and tag accordingly. "none" means neither
            # provider had data for this ticker — preserved so downstream
            # observability can distinguish "we tried and failed" from "we
            # haven't tried yet".
            eps_ttm_source: str | None = "eodhd" if snap["eps_ttm"] is not None else None
            beta_source: str | None = "eodhd" if snap["beta"] is not None else None

            if av_adapter is not None and (snap["eps_ttm"] is None or snap["beta"] is None):
                try:
                    av_overview = await av_adapter.fetch_overview(ticker)
                except Exception as av_exc:
                    # WHY broad except: AV adapter raises a mix of httpx + JSON +
                    # rate-limit exceptions; treat any failure as "AV unavailable
                    # for this ticker" rather than aborting the whole backfill.
                    log.warning(
                        "backfill.alpha_vantage_error",
                        ticker=ticker,
                        error=str(av_exc),
                    )
                    av_overview = None

                if av_overview is not None:
                    if snap["eps_ttm"] is None and av_overview.eps_ttm is not None:
                        snap["eps_ttm"] = av_overview.eps_ttm
                        eps_ttm_source = "alpha_vantage"
                    if snap["beta"] is None and av_overview.beta is not None:
                        snap["beta"] = av_overview.beta
                        beta_source = "alpha_vantage"

            # If still NULL after both providers, mark as "none" so the source
            # column truthfully reflects "we tried and got nothing".
            if snap["eps_ttm"] is None and eps_ttm_source is None:
                eps_ttm_source = "none"
            if snap["beta"] is None and beta_source is None:
                beta_source = "none"

            # ── Per-field coverage logging (T-C-3-01) ─────────────────────────
            # Emit a single structured event with status of every frontend-
            # displayed field.  WHY one event (not 10): structlog correlates
            # them better and the consumer (Loki/Grafana) needs only a single
            # row per ticker.
            field_status = {field: _coverage_status(snap.get(field)) for field in _FRONTEND_FIELDS}
            coverage_matrix[ticker] = field_status
            log.info(
                "backfill.field_coverage",
                ticker=ticker,
                instrument_id=instrument_id,
                eps_ttm_source=eps_ttm_source,
                beta_source=beta_source,
                **field_status,
            )

            await _upsert_snapshot(
                conn,
                instrument_id,
                snap,
                dry_run=dry_run,
                eps_ttm_source=eps_ttm_source,
                beta_source=beta_source,
                has_source_columns=has_source_columns,
            )
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
            # Mark every field as "error" so the export row is preserved with
            # an honest status rather than silently absent.
            coverage_matrix[ticker] = dict.fromkeys(_FRONTEND_FIELDS, "error")
            errors += 1
            # WHY continue on error: a single bad instrument should not abort
            # the entire backfill.  The next run will retry failed instruments.

    # ── Close the AV adapter's underlying httpx client (no-op if unused) ────
    if av_adapter is not None:
        await av_adapter.close()

    await conn.close()

    # ── Aggregate field-population percentages (T-C-3-01) ─────────────────────
    # WHY only over the populated/null universe: rows where the entire ticker
    # errored aren't a meaningful denominator for "% of tickers we got data for"
    # — they distort the metric. Operators who want the error count look at the
    # "errors" tally above.
    if coverage_matrix:
        non_error = {ticker: row for ticker, row in coverage_matrix.items() if any(v != "error" for v in row.values())}
        denom = len(non_error)
        pct: dict[str, float] = {}
        if denom > 0:
            for field in _FRONTEND_FIELDS:
                populated = sum(1 for row in non_error.values() if row[field] == "populated")
                pct[field] = round(100.0 * populated / denom, 1)
        log.info("backfill.field_population_pct", denominator=denom, **pct)

    # ── Optional CSV export (T-C-3-01) ────────────────────────────────────────
    if export_coverage_path:
        try:
            with open(export_coverage_path, "w", newline="", encoding="utf-8") as fp:
                writer = csv.writer(fp)
                writer.writerow(["ticker", *_FRONTEND_FIELDS])
                # WHY sorted: deterministic output makes diffs between runs
                # readable; operators eyeball the CSV in a spreadsheet.
                for ticker in sorted(coverage_matrix.keys()):
                    row_data = coverage_matrix[ticker]
                    writer.writerow([ticker, *(row_data[f] for f in _FRONTEND_FIELDS)])
            log.info(
                "backfill.coverage_exported",
                path=export_coverage_path,
                rows=len(coverage_matrix),
            )
        except OSError as exc:
            # WHY non-fatal: a write failure on the CSV shouldn't fail the
            # backfill itself — the data is already in the DB.
            log.error("backfill.coverage_export_failed", path=export_coverage_path, error=str(exc))

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
    """CLI entry point.

    PLAN-0053 T-C-3-01 introduces ``--export-coverage`` so we promoted env-var-only
    config to argparse for ergonomics; ``DATABASE_URL`` / ``BATCH_SIZE`` / ``DRY_RUN``
    remain primary for backward compatibility (operators run this from systemd or
    cron with env vars), and the CLI flags only add new capabilities.
    """
    parser = argparse.ArgumentParser(
        description="Backfill instrument_fundamentals_snapshot — see module docstring",
    )
    parser.add_argument(
        "--export-coverage",
        type=str,
        default=None,
        help=("Write per-ticker x per-field coverage matrix to this CSV path. " "Cells are populated/null/error."),
    )
    args = parser.parse_args()

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
    # PLAN-0053 T-C-3-02: empty / unset key disables the AV fallback chain.
    av_key = os.environ.get("ALPHA_VANTAGE_API_KEY") or None

    asyncio.run(
        run_backfill(
            database_url,
            TOP_EQUITY_SYMBOLS,
            batch_size=batch_size,
            dry_run=dry_run,
            export_coverage_path=args.export_coverage,
            alpha_vantage_api_key=av_key,
        )
    )


if __name__ == "__main__":
    main()
