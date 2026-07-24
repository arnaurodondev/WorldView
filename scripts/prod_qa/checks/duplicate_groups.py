"""Duplicate-group scanner — `GROUP BY <normalized-key> HAVING count(*) > 1`
across every identity/dedup-prone table this platform has burned itself on.

WHY THIS EXISTS: the platform has hit the same bug shape THREE times now, each
time only discovered by hand-running a duplicate-group query after a support
ticket / data-quality audit:

  * BP-459 (2026-06-12, knowledge-graph): two independent minting pipelines
    each created a `canonical_entities` row for the same ticker — an
    exact-match unique index never fired because neither insert's predicate
    matched the other's shape.
  * BP-743 (2026-07-15, market-data): a placeholder `exchange=''` `instruments`
    row and a later real-exchange row for the same `symbol` coexisted — an
    exact-match `(symbol, exchange)` constraint doesn't catch a placeholder
    vs. real duplicate.
  * BP-700 (2026-06-15, KG + NLP): exchange-suffixed tickers (`AAPL.MX`) never
    matched the bare-ticker canonical because no normalizer stripped the venue
    qualifier before the ticker lookup, minting a duplicate tickerless
    canonical — and separately produced junk `"NYSE: BCS"`-shaped canonical
    names when an exchange-prefixed string was used as-is.

Nothing before this check ran these queries on a schedule — each incident was
caught by a human ad hoc. This module makes the query set a standing,
repeatable prod-QA layer so a FOURTH occurrence (in these tables, or a new one
added to `DUP_GROUP_CHECKS`) surfaces on the next run instead of waiting for
another audit.

THRESHOLD POLICY: every hard duplicate-group check here is a **completeness
scanner, not a coverage floor** — FAIL on any count > 0. This is deliberately
zero-tolerance: every single historical nonzero reading on one of these
queries corresponded to a real, confirmed bug (BP-459/BP-743/BP-700), never a
false alarm from normal backfill/coverage churn. The one exception is the
prediction-market `event_id IS NULL` floor-check, which is a SOFT regression
guard (a few freshly-discovered, not-yet-linked markets is normal — the
BP-743-sibling regression class is ALL markets losing their link, not a
nonzero count).
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import harness as H
from ..harness import Ctx

SVC = "duplicate_groups"


@dataclass(frozen=True)
class DupGroupCheck:
    """One `GROUP BY <key> HAVING count(*) > 1` duplicate-group query.

    `sql` MUST resolve to a single scalar: the number of DUPLICATE GROUPS
    (i.e. distinct key values with count(*) > 1), not the number of excess
    rows — so the reported number is directly "N tickers/symbols/names are
    duplicated", matching the `docs/BUG_PATTERNS.md` detection queries this
    check operationalizes.
    """

    name: str
    db: str
    sql: str
    guard: str  # BP-xxx reference shown in the report detail


# Table-driven duplicate-group checks. Extend this list the next time this bug
# shape fires against a new table — see module docstring for the pattern.
DUP_GROUP_CHECKS: list[DupGroupCheck] = [
    DupGroupCheck(
        name="instruments duplicate symbol (case-insensitive)",
        db="market_data_db",
        sql="SELECT count(*) FROM (SELECT upper(symbol) FROM instruments GROUP BY upper(symbol) HAVING count(*) > 1) t",
        guard="BP-743",
    ),
    DupGroupCheck(
        name="canonical_entities duplicate ticker",
        db="intelligence_db",
        sql=(
            "SELECT count(*) FROM (SELECT ticker FROM canonical_entities "
            "WHERE ticker IS NOT NULL GROUP BY ticker HAVING count(*) > 1) t"
        ),
        guard="BP-459",
    ),
    DupGroupCheck(
        name="canonical_entities duplicate name+type (secondary check)",
        db="intelligence_db",
        sql=(
            "SELECT count(*) FROM (SELECT lower(canonical_name), entity_type FROM canonical_entities "
            "GROUP BY lower(canonical_name), entity_type HAVING count(*) > 1) t"
        ),
        guard="BP-459",
    ),
    DupGroupCheck(
        name="prediction_markets duplicate market_id (should be structurally impossible — upsert key)",
        db="market_data_db",
        sql=(
            "SELECT count(*) FROM (SELECT market_id FROM prediction_markets GROUP BY market_id HAVING count(*) > 1) t"
        ),
        guard="BP-743 (sibling class)",
    ),
    DupGroupCheck(
        name="prediction_markets duplicate market_slug (case-insensitive, non-null)",
        db="market_data_db",
        sql=(
            "SELECT count(*) FROM (SELECT lower(market_slug) FROM prediction_markets "
            "WHERE market_slug IS NOT NULL GROUP BY lower(market_slug) HAVING count(*) > 1) t"
        ),
        guard="BP-743 (sibling class)",
    ),
]


def run(ctx: Ctx) -> None:
    _duplicate_groups(ctx)
    _junk_canonical_names(ctx)
    _prediction_market_event_link_floor(ctx)


def _duplicate_groups(ctx: Ctx) -> None:
    """Run every table-driven duplicate-group query; FAIL on any count > 0.

    Queries are grouped per-DB so each DB gets exactly one `kubectl exec`
    round-trip (`psql_many` batches all queries against one database).
    """
    R = ctx.report
    by_db: dict[str, list[DupGroupCheck]] = {}
    for c in DUP_GROUP_CHECKS:
        by_db.setdefault(c.db, []).append(c)

    for db, checks in by_db.items():
        q = H.psql_many(db, {c.name: c.sql for c in checks})
        for c in checks:
            n = H.as_int(q[c.name], -1)
            if n < 0:
                # Table absent / query error — WARN rather than crash the run
                # (mirrors psql_many's documented "missing table → ''" contract).
                R.warn(SVC, c.name, f"query failed / table absent ({c.guard})")
                continue
            R.check(
                SVC,
                c.name,
                n == 0,
                f"{n} duplicate group(s) ({c.guard})" if n else f"0 duplicate groups ({c.guard} regression guard)",
            )


def _junk_canonical_names(ctx: Ctx) -> None:
    """Flag exchange-prefixed junk canonical names (BP-700's other symptom).

    A canonical_entities row whose `canonical_name` looks like `"NYSE: BCS"` —
    an un-normalized exchange-prefixed string used verbatim as the entity name
    — is the shape-of-junk BP-700 also produced alongside the tickerless
    duplicate. Zero-tolerance: a real canonical name never legitimately takes
    this `EXCHANGE: ...` form.
    """
    R = ctx.report
    n = H.as_int(
        H.psql_scalar(
            "intelligence_db",
            r"SELECT count(*) FROM canonical_entities WHERE canonical_name ~ '^[A-Z]+:\s'",
        ),
        -1,
    )
    if n < 0:
        R.warn(SVC, "junk exchange-prefixed canonical names", "query failed (BP-700)")
        return
    R.check(
        SVC,
        "junk exchange-prefixed canonical names (e.g. 'NYSE: BCS')",
        n == 0,
        f"{n} junk-shaped name(s) (BP-700)" if n else "0 junk-shaped names (BP-700 regression guard)",
    )


def _prediction_market_event_link_floor(ctx: Ctx) -> None:
    """SOFT floor-check regression guard: prediction_markets.event_id IS NULL.

    Mirrors the BP-743-sibling regression this check family guards against:
    the market_data.py `market→event linkage %` check already asserts a WARN
    floor on the LINKED percentage; this is the same signal read from the
    unlinked side, kept here so a duplicate-groups-focused run (`--only
    duplicate_groups`) still catches the "every market lost its event_id"
    total-regression shape without needing the full market_data layer.
    """
    R = ctx.report
    q = H.psql_many(
        "market_data_db",
        {
            "total": "SELECT count(*) FROM prediction_markets",
            "null_event": "SELECT count(*) FROM prediction_markets WHERE event_id IS NULL",
        },
    )
    total = H.as_int(q["total"], 0)
    null_event = H.as_int(q["null_event"], -1)
    if total == 0 or null_event < 0:
        R.warn(SVC, "prediction_markets event_id NULL floor", "no rows / query failed — skipped")
        return
    # Total regression (every market unlinked) is the historical BP-743-sibling
    # shape; a handful of freshly-discovered not-yet-linked markets is normal
    # backfill lag, not a regression — so this is a SOFT check on the total
    # collapse, not a hard zero-tolerance count.
    R.check(
        SVC,
        "prediction_markets event_id NULL floor (BP-743 sibling regression guard)",
        null_event < total,
        f"{null_event}/{total} markets have NULL event_id",
        soft=True,
    )
