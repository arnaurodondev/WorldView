#!/usr/bin/env python3
"""Seed market-data ingestion polling policies for Tier-1/Tier-2 tickerless-company candidates.

CONTEXT (see docs/audits/2026-06-14-tickerless-instrument-companies-followup.md):
the relevance analysis identified ingestion-worthy tickerless ``financial_instrument``
canonicals — large/mega-cap names (Marvell, Nike, Micron, Western Digital,
GlobalFoundries, Deckers, Newmont, …) that are mentioned in the news corpus but have
no symbol wired into ``ingestion_db.polling_policies``, so no OHLCV (Alpaca) /
fundamentals (EODHD) ingestion ever runs for them.

This script, given a list of ``(symbol, exchange, tier)`` candidates, creates the
CANONICAL per-symbol policy set (verified against the live ``polling_policies`` table
on 2026-06-15 — the dominant cluster present for ~450-630 symbols):

  #  provider  dataset_type  variant   timeframe  base_int  min_int  jitter  priority  tier   enabled
  1  alpaca    ohlcv         (none)    1m         60        60       5       100       <cand> t
  2  eodhd     ohlcv         (none)    1d         21600     3600     60      5         2      t
  3  eodhd     ohlcv         (none)    1w         43200     3600     60      4         2      t
  4  eodhd     ohlcv         (none)    1mo        86400     3600     60      3         2      t
  5  eodhd     fundamentals  General   (none)     86400     3600     300     2         2      t

WHY these exact tuples: they were read straight from existing fully-covered symbols
(e.g. ``A``, ``ACGL``, ``ABT``) so a new symbol is INDISTINGUISHABLE from one the
platform already ingests — the scheduler treats it identically.  The ``tier`` of the
Alpaca 1m policy tracks the candidate's tier (Alpaca OHLCV rows are tier-1 in the live
data); the EODHD policies are uniformly tier=2 in the live data, so we mirror that and
keep them at 2 regardless of candidate tier.

IDEMPOTENCY: there is NO unique constraint on ``polling_policies`` — only a NON-unique
matching index ``ix_polling_policies_matching`` on
``(provider, dataset_type, dataset_variant, symbol, exchange, timeframe)``.  So we
de-dup ourselves: before inserting a policy we SELECT for an existing row on exactly
that 6-tuple and skip if one is present.  A re-run is therefore a no-op for already-
seeded (or pre-existing) symbols.  (Verified 2026-06-15: MU/WDC/NKE/DECK/NEM already
have policies and are correctly skipped; MRVL/GFS are absent and would be seeded.)

ID convention: ``polling_policies.id`` is a 26-char ULID (``common.ids.new_ulid``),
matching every existing row (e.g. ``01HXD71F64D9BF2A312CF6A23D``).

SAFETY / DISCIPLINE:
  • DRY-RUN by DEFAULT.  Prints every row it WOULD insert, the total count, and a
    per-provider breakdown (EODHD-fundamentals vs Alpaca-OHLCV) so the API-budget
    impact is explicit, then exits writing NOTHING.
  • ``--apply`` is GATED by the orchestrator: EODHD's daily quota is currently
    exhausted (100,000/100,000) and a parallel investigation is freeing budget.
    Applying new EODHD-fundamentals policies now would fail/worsen quota.  Do NOT
    pass ``--apply`` until quota has headroom.
  • ``--tier {1,2,all}`` filters which candidate tier(s) to seed.
  • ``--only-ohlcv`` skips the EODHD-fundamentals policy (zero NEW fundamentals quota
    impact — only the Alpaca 1m + EODHD OHLCV bar policies are created).  Note the
    EODHD OHLCV bar policies (1d/1w/1mo) still consume EODHD quota; ``--only-ohlcv``
    only drops the ``General`` fundamentals policy, which is the heaviest per-symbol
    EODHD call.

Usage:
    python scripts/data/seed_tier_policies.py                       # DRY RUN, all tiers
    python scripts/data/seed_tier_policies.py --tier 1              # DRY RUN, tier-1 only
    python scripts/data/seed_tier_policies.py --tier 1 --only-ohlcv # DRY RUN, no fundamentals
    python scripts/data/seed_tier_policies.py --tier 1 --apply      # GATED — orchestrator only
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass

import psycopg

from common.ids import new_ulid  # type: ignore[import-untyped]

# Default DSN targets the local docker-compose Postgres ``ingestion_db``.
# Override via the INGESTION_DB_DSN env var (e.g. for a staging/prod run).
_INGESTION_DSN = os.environ.get(
    "INGESTION_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/ingestion_db",
)


@dataclass(frozen=True)
class Candidate:
    """One resolved ingestion target: a ticker on a given exchange at a given tier."""

    symbol: str
    exchange: str
    tier: int


@dataclass(frozen=True)
class PolicyRow:
    """A single ``polling_policies`` row to be inserted.

    Field values mirror the live canonical per-symbol policy set exactly.  Only
    ``symbol``/``exchange``/``tier`` vary per candidate; everything else is fixed
    per policy kind.
    """

    provider: str
    dataset_type: str
    dataset_variant: str | None
    symbol: str
    exchange: str
    timeframe: str | None
    base_interval_sec: int
    min_interval_sec: int
    jitter_sec: int
    priority: int
    tier: int

    # The 6-tuple used for idempotency / matching (mirrors ix_polling_policies_matching).
    @property
    def match_key(self) -> tuple[str, str, str | None, str, str, str | None]:
        return (
            self.provider,
            self.dataset_type,
            self.dataset_variant,
            self.symbol,
            self.exchange,
            self.timeframe,
        )


# --- The canonical per-symbol policy template (verified from live data 2026-06-15) ---
# Each entry: (provider, dataset_type, dataset_variant, timeframe, base_interval_sec,
#              min_interval_sec, jitter_sec, priority).  ``symbol``/``exchange``/``tier``
# are filled per candidate.  ``alpaca`` 1m is the tier-tracked policy.
# Explicit alias keeps the heterogeneous tuple shape consistent (variant + timeframe
# are both ``str | None``) so mypy treats every spec uniformly.
_PolicySpec = tuple[str, str, str | None, str | None, int, int, int, int]

_OHLCV_ALPACA_1M: _PolicySpec = ("alpaca", "ohlcv", None, "1m", 60, 60, 5, 100)
_OHLCV_EODHD: list[_PolicySpec] = [
    ("eodhd", "ohlcv", None, "1d", 21600, 3600, 60, 5),
    ("eodhd", "ohlcv", None, "1w", 43200, 3600, 60, 4),
    ("eodhd", "ohlcv", None, "1mo", 86400, 3600, 60, 3),
]
_FUNDAMENTALS_EODHD: _PolicySpec = ("eodhd", "fundamentals", "General", None, 86400, 3600, 300, 2)


def build_policy_rows(cand: Candidate, *, only_ohlcv: bool) -> list[PolicyRow]:
    """Build the full canonical policy set for one candidate.

    The Alpaca 1m OHLCV policy carries the candidate's tier; all EODHD policies stay
    at tier=2 to mirror the live data exactly.  ``only_ohlcv=True`` drops the EODHD
    fundamentals policy (the heaviest per-symbol EODHD quota cost).
    """
    specs: list[_PolicySpec] = [_OHLCV_ALPACA_1M, *_OHLCV_EODHD]
    if not only_ohlcv:
        specs.append(_FUNDAMENTALS_EODHD)

    rows: list[PolicyRow] = []
    for provider, dataset_type, variant, timeframe, base_int, min_int, jitter, priority in specs:
        # Alpaca 1m is the only tier-tracked policy; EODHD rows stay tier=2.
        row_tier = cand.tier if provider == "alpaca" else 2
        rows.append(
            PolicyRow(
                provider=provider,
                dataset_type=dataset_type,
                dataset_variant=variant,
                symbol=cand.symbol,
                exchange=cand.exchange,
                timeframe=timeframe,
                base_interval_sec=base_int,
                min_interval_sec=min_int,
                jitter_sec=jitter,
                priority=priority,
                tier=row_tier,
            )
        )
    return rows


def _policy_exists(cur: psycopg.Cursor, row: PolicyRow) -> bool:
    """Return True if a policy with the same matching 6-tuple already exists.

    Uses NULL-safe equality (``IS NOT DISTINCT FROM``) because ``dataset_variant``
    and ``timeframe`` are nullable and plain ``=`` would never match a NULL.
    """
    cur.execute(
        """
        SELECT 1 FROM polling_policies
        WHERE provider = %s
          AND dataset_type = %s
          AND dataset_variant IS NOT DISTINCT FROM %s
          AND symbol = %s
          AND exchange = %s
          AND timeframe IS NOT DISTINCT FROM %s
        LIMIT 1
        """,
        (
            row.provider,
            row.dataset_type,
            row.dataset_variant,
            row.symbol,
            row.exchange,
            row.timeframe,
        ),
    )
    return cur.fetchone() is not None


def _insert_policy(cur: psycopg.Cursor, row: PolicyRow) -> None:
    """Insert a single policy row, mirroring the live column defaults."""
    cur.execute(
        """
        INSERT INTO polling_policies (
            id, provider, dataset_type, dataset_variant, symbol, exchange, timeframe,
            base_interval_sec, min_interval_sec, jitter_sec, priority,
            enabled, market_hours_only, post_market_only,
            backfill_enabled, backfill_chunk_days, tier
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            TRUE, FALSE, FALSE,
            FALSE, 30, %s
        )
        """,
        (
            new_ulid(),
            row.provider,
            row.dataset_type,
            row.dataset_variant,
            row.symbol,
            row.exchange,
            row.timeframe,
            row.base_interval_sec,
            row.min_interval_sec,
            row.jitter_sec,
            row.priority,
            row.tier,
        ),
    )


def seed(
    candidates: list[Candidate],
    *,
    apply: bool,
    only_ohlcv: bool,
    dsn: str = _INGESTION_DSN,
) -> tuple[list[PolicyRow], list[PolicyRow]]:
    """Plan (and optionally apply) the policy seed.

    Returns ``(to_insert, skipped_existing)``.  In dry-run mode nothing is written;
    the existence check still runs so the plan reflects true idempotency.
    """
    to_insert: list[PolicyRow] = []
    skipped: list[PolicyRow] = []

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for cand in candidates:
            for row in build_policy_rows(cand, only_ohlcv=only_ohlcv):
                if _policy_exists(cur, row):
                    skipped.append(row)
                    continue
                to_insert.append(row)
                if apply:
                    _insert_policy(cur, row)
        if apply:
            conn.commit()
        else:
            conn.rollback()  # belt-and-suspenders: dry-run writes nothing

    return to_insert, skipped


def _provider_breakdown(rows: list[PolicyRow]) -> Counter[str]:
    """Per-(provider, dataset_type) breakdown — the API-budget impact view."""
    c: Counter[str] = Counter()
    for r in rows:
        c[f"{r.provider}:{r.dataset_type}"] += 1
    return c


def _print_plan(
    to_insert: list[PolicyRow],
    skipped: list[PolicyRow],
    *,
    apply: bool,
) -> None:
    mode = "APPLIED" if apply else "DRY-RUN (no rows written)"
    print(f"=== seed_tier_policies — {mode} ===\n")

    if to_insert:
        print(f"Policies to insert ({len(to_insert)}):")
        for r in sorted(to_insert, key=lambda x: (x.symbol, x.provider, x.dataset_type, x.timeframe or "")):
            tf = r.timeframe or "-"
            print(
                f"  {r.symbol:<8} {r.exchange:<4} {r.provider:<7} {r.dataset_type:<13} "
                f"variant={r.dataset_variant or '-':<8} tf={tf:<4} "
                f"interval={r.base_interval_sec:<6} tier={r.tier}"
            )
    else:
        print("Policies to insert: 0 (all candidates already covered)")

    print(f"\nSkipped (already present): {len(skipped)}")

    bd = _provider_breakdown(to_insert)
    print("\n--- Provider / dataset breakdown (NEW rows = budget impact) ---")
    for key in sorted(bd):
        print(f"  {key:<22} {bd[key]}")
    alpaca_ohlcv = bd.get("alpaca:ohlcv", 0)
    eodhd_ohlcv = bd.get("eodhd:ohlcv", 0)
    eodhd_fund = bd.get("eodhd:fundamentals", 0)
    print(
        f"\n  EODHD impact -> fundamentals(General): {eodhd_fund}  |  "
        f"OHLCV bars: {eodhd_ohlcv}  |  Alpaca OHLCV: {alpaca_ohlcv}"
    )
    print(f"  TOTAL new policy rows: {len(to_insert)}")
    if not apply:
        print("\n(DRY-RUN: pass --apply ONLY after the orchestrator confirms EODHD quota headroom.)")


# ---------------------------------------------------------------------------
# Resolved candidate lists.  See the staging note in docs/audits/ for provenance.
# These are VETTED, high-confidence US-primary-listed common-stock tickers resolved
# by hand from the Tier-1 head of the tickerless-FI mention ranking.  Foreign / ADR-
# ambiguous names (Samsung, Toyota, Alibaba, Roche, Lenovo, Infineon, …) and all of
# Tier-2 are DEFERRED to post-quota EODHD resolution and are NOT included here.
# ---------------------------------------------------------------------------
TIER1_US_CANDIDATES: list[Candidate] = [
    Candidate("MRVL", "US", 1),  # Marvell Technology
    Candidate("NKE", "US", 1),  # NIKE
    Candidate("MU", "US", 1),  # Micron Tech
    Candidate("WDC", "US", 1),  # Western Digital
    Candidate("GFS", "US", 1),  # GLOBALFOUNDRIES Inc.
    Candidate("DECK", "US", 1),  # DECKERS OUTDOOR CORP
    Candidate("NEM", "US", 1),  # Newmont Mining (Newmont Corp)
    Candidate("CTRN", "US", 1),  # Citi Trends Inc
    Candidate("ITIC", "US", 1),  # Investors Title Co.
    Candidate("TMHC", "US", 1),  # Taylor Morrison Home
    Candidate("PINS", "US", 1),  # PINTEREST
    Candidate("RDW", "US", 1),  # Redwire
    Candidate("BF.B", "US", 1),  # Brown-Forman (Class B)
    Candidate("RH", "US", 1),  # RH (Restoration Hardware)
    Candidate("ATI", "US", 1),  # ATI Inc.
    Candidate("SYK", "US", 1),  # Stryker
    Candidate("FLEX", "US", 1),  # Flex Ltd. (US-listed)
    Candidate("SMCI", "US", 1),  # Super Micro
    Candidate("RGTI", "US", 1),  # Rigetti Computing
    Candidate("WHR", "US", 1),  # Whirlpool
    Candidate("TPR", "US", 1),  # Tapestry
    Candidate("PEBO", "US", 1),  # Peoples Bancorp
    Candidate("ALGM", "US", 1),  # Allegro MicroSystems
    Candidate("PLD", "US", 1),  # Prologis
    Candidate("FIBK", "US", 1),  # First Interstate BancSystem
    Candidate("MCK", "US", 1),  # McKesson
    Candidate("SMTC", "US", 1),  # Semtech Corp
    Candidate("PLUS", "US", 1),  # ePlus Inc
    Candidate("BB", "US", 1),  # BlackBerry (US-listed, NYSE)
    Candidate("ROG", "US", 1),  # Rogers Corp
    Candidate("CELH", "US", 1),  # Celsius Holdings
    Candidate("ETN", "US", 1),  # Eaton Corp. Plc (NYSE)
    Candidate("LHX", "US", 1),  # L3Harris
    Candidate("AAOI", "US", 1),  # Applied Optoelectronics
    Candidate("CPA", "US", 1),  # Copa Holdings (NYSE)
    Candidate("IAC", "US", 1),  # IAC Inc.
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="GATED — actually insert policies. Default is DRY-RUN. Do NOT use until EODHD quota has headroom.",
    )
    parser.add_argument(
        "--tier",
        choices=["1", "2", "all"],
        default="all",
        help="Which candidate tier(s) to seed. Currently only Tier-1-US is resolved; "
        "Tier-2 is deferred to post-quota EODHD resolution.",
    )
    parser.add_argument(
        "--only-ohlcv",
        action="store_true",
        help="Skip the EODHD-fundamentals (General) policy — drops the heaviest per-symbol EODHD call.",
    )
    parser.add_argument(
        "--dsn",
        default=_INGESTION_DSN,
        help="ingestion_db DSN (default: local docker-compose Postgres).",
    )
    args = parser.parse_args()

    # Select candidate set by tier.  Only Tier-1-US is resolved today.
    candidates: list[Candidate]
    if args.tier in ("1", "all"):
        candidates = list(TIER1_US_CANDIDATES)
    else:
        candidates = []
    if args.tier in ("2", "all") and args.tier != "1":
        # Tier-2 is intentionally empty (deferred). Kept explicit for future wiring.
        candidates += []

    if not candidates:
        print(f"No resolved candidates for --tier {args.tier} (Tier-2 deferred to EODHD post-quota).")
        return 0

    if args.apply:
        print(
            "WARNING: --apply requested. This is GATED on EODHD quota headroom. " "Proceeding to insert.\n",
            file=sys.stderr,
        )

    to_insert, skipped = seed(
        candidates,
        apply=args.apply,
        only_ohlcv=args.only_ohlcv,
        dsn=args.dsn,
    )
    _print_plan(to_insert, skipped, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
