"""Granular functional checks for market-data (S3) — quotes, OHLCV, fundamentals,
intraday resampling, prediction-market deeper streams.

DB floors calibrated against live `market_data_db`; API assertions drive the
real read routes via the in-pod prober and check response SHAPE + sane values so
a small regression (e.g. a null close, a dropped timeframe, an empty screener)
is caught, not just a 500.
"""

from __future__ import annotations

from .. import harness as H
from .. import thresholds as T
from ..harness import Ctx
from . import assert_api_ok

SVC = "market-data"


def run(ctx: Ctx) -> None:
    _db(ctx)
    _api(ctx)


def _db(ctx: Ctx) -> None:
    R = ctx.report
    q = H.psql_many(
        "market_data_db",
        {
            "instruments": "SELECT count(*) FROM instruments",
            "has_fund": "SELECT count(*) FILTER (WHERE has_fundamentals) FROM instruments",
            "fund_snap": "SELECT count(*) FROM instrument_fundamentals_snapshot",
            "bars": "SELECT count(*) FROM ohlcv_bars",
            "bars_fresh_h": "SELECT round(extract(epoch from now()-max(bar_date))/3600,1) FROM ohlcv_bars",
            "derived": "SELECT count(*) FILTER (WHERE is_derived) FROM ohlcv_bars",
            "timeframes": "SELECT string_agg(DISTINCT timeframe,',') FROM ohlcv_bars",
            "partial_invariant": "SELECT count(*) FROM ohlcv_bars WHERE is_partial AND NOT is_derived",
            "pred_markets": "SELECT count(*) FROM prediction_markets",
            "pred_snaps": "SELECT count(*) FROM prediction_market_snapshots",
            "pred_snap_fresh_h": "SELECT round(extract(epoch from now()-max(snapshot_at))/3600,1) FROM prediction_market_snapshots",
            "pred_prices": "SELECT count(*) FROM prediction_market_prices",
            "pred_trades": "SELECT count(*) FROM prediction_market_trades",
            "pred_oi": "SELECT count(*) FROM prediction_market_oi",
            "pred_events": "SELECT count(*) FROM prediction_events",
            "insider": "SELECT count(*) FROM insider_transactions",
            "earnings_cal": "SELECT count(*) FROM earnings_calendar",
        },
    )
    R.floor(SVC, "instruments row count", H.as_int(q["instruments"]), T.MD_INSTRUMENTS_FLOOR)
    R.floor(SVC, "instruments w/ fundamentals", H.as_int(q["has_fund"]), T.MD_HAS_FUNDAMENTALS_FLOOR)
    R.floor(SVC, "fundamentals snapshots", H.as_int(q["fund_snap"]), T.MD_FUND_SNAPSHOT_FLOOR)
    R.floor(SVC, "ohlcv_bars row count", H.as_int(q["bars"]), T.MD_OHLCV_BARS_FLOOR)

    fresh = H.as_float(q["bars_fresh_h"])
    if fresh != fresh:  # NaN → no rows
        R.warn(SVC, "OHLCV freshness", "no bars")
    else:
        st = H.FAIL if fresh > T.MD_OHLCV_FRESH_FAIL_H else H.WARN if fresh > T.MD_OHLCV_FRESH_WARN_H else H.PASS
        R.add(SVC, "OHLCV freshness (Alpaca feed alive)", st, f"newest bar {fresh}h old")

    R.floor(SVC, "intraday-resampling derived bars", H.as_int(q["derived"]), T.MD_DERIVED_BARS_FLOOR)
    tfs = set((q["timeframes"] or "").split(","))
    missing_tf = T.MD_EXPECTED_TIMEFRAMES - tfs
    R.check(
        SVC,
        "all OHLCV timeframes present",
        not missing_tf,
        f"missing {missing_tf}" if missing_tf else f"{len(T.MD_EXPECTED_TIMEFRAMES)} timeframes",
        soft=True,
    )
    R.check(
        SVC,
        "is_partial⇒is_derived invariant",
        H.as_int(q["partial_invariant"], 0) == 0,
        f"{q['partial_invariant']} violating rows",
    )

    # Prediction-market deeper streams (PLAN-0056 A1-A4).
    R.floor(SVC, "prediction_markets", H.as_int(q["pred_markets"]), T.MD_PRED_MARKETS_FLOOR)
    R.floor(SVC, "prediction snapshots", H.as_int(q["pred_snaps"]), T.MD_PRED_SNAPSHOTS_FLOOR)
    R.floor(SVC, "prediction CLOB prices (history consumer)", H.as_int(q["pred_prices"]), T.MD_PRED_PRICES_FLOOR)
    R.floor(SVC, "prediction trades (trades consumer)", H.as_int(q["pred_trades"]), T.MD_PRED_TRADES_FLOOR)
    R.check(SVC, "prediction OI rows present", H.as_int(q["pred_oi"], 0) > 0, f"{q['pred_oi']} rows", soft=True)
    R.check(
        SVC, "prediction events rows present", H.as_int(q["pred_events"], 0) > 0, f"{q['pred_events']} rows", soft=True
    )

    snap_fresh = H.as_float(q["pred_snap_fresh_h"])
    if snap_fresh == snap_fresh:
        st = (
            H.FAIL if snap_fresh > T.MD_PRED_FRESH_FAIL_H else H.WARN if snap_fresh > T.MD_PRED_FRESH_WARN_H else H.PASS
        )
        R.add(SVC, "prediction snapshot freshness (Polymarket)", st, f"newest {snap_fresh}h old")

    R.floor(SVC, "insider_transactions", H.as_int(q["insider"]), T.MD_INSIDER_FLOOR)
    # earnings_calendar is populated by the S2 L-5b sync worker — 0 is a known gap on a fresh deploy.
    R.check(
        SVC,
        "earnings_calendar populated (L-5b sync)",
        H.as_int(q["earnings_cal"], 0) > 0,
        f"{q['earnings_cal']} rows",
        soft=True,
    )


def _api(ctx: Ctx) -> None:
    R = ctx.report
    ok, body = assert_api_ok(ctx, SVC, "OHLCV bars (AAPL/1d)", "md_ohlcv")
    if ok and isinstance(body, dict):
        bars = body.get("bars") or []
        R.check(
            SVC,
            "OHLCV bars have sane closes",
            bool(bars) and all(isinstance(b.get("close"), (int, float)) and b["close"] > 0 for b in bars[:5]),
            f"{len(bars)} bars, closes>0",
        )

    ok, body = assert_api_ok(ctx, SVC, "quotes latest (AAPL)", "md_quotes")
    if ok and isinstance(body, dict):
        quotes = body.get("quotes") or {}
        one = next(iter(quotes.values()), {}) if isinstance(quotes, dict) else {}
        R.check(
            SVC,
            "quote carries last/volume",
            one.get("last") is not None or one.get("volume") is not None,
            f"last={one.get('last')} vol={one.get('volume')}",
            soft=True,
        )

    ok, body = assert_api_ok(ctx, SVC, "fundamentals snapshot (AAPL)", "md_fund_snap")
    if ok and isinstance(body, dict):
        keys = [k for k in ("eps_ttm", "beta", "avg_volume_30d", "operating_cash_flow") if body.get(k) is not None]
        R.check(SVC, "fundamentals snapshot has metrics", len(keys) >= 2, f"non-null: {keys}")

    ok, body = assert_api_ok(ctx, SVC, "screener POST (mktcap≥1e11)", "md_screen")
    if ok and isinstance(body, dict):
        items = body.get("items") or body.get("results") or []
        R.check(SVC, "screener returns matches", len(items) > 0, f"{len(items)} rows")

    assert_api_ok(ctx, SVC, "sector-returns", "md_sector")
    assert_api_ok(ctx, SVC, "period-movers (1W gainers)", "md_movers")
    assert_api_ok(ctx, SVC, "timeframes list (AAPL)", "md_timeframes")

    ok, body = assert_api_ok(ctx, SVC, "prediction-markets list", "md_predlist")
    if ok and isinstance(body, dict):
        items = body.get("items") or []
        R.check(
            SVC,
            "prediction list items well-formed",
            bool(items) and all(i.get("market_id") and i.get("question") for i in items[:3]),
            f"{len(items)} markets",
        )
    assert_api_ok(ctx, SVC, "prediction categories", "md_predcats")
    assert_api_ok(ctx, SVC, "prediction events", "md_predevents", soft_on_missing=True)
    assert_api_ok(ctx, SVC, "prediction market detail", "md_pred_detail", soft_on_missing=True)
    assert_api_ok(ctx, SVC, "prediction price history (1h)", "md_pred_history", min_len=2, soft_on_missing=True)
