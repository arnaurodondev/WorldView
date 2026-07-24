"""Granular checks for rag-chat (S8) — the grounded-answer golden set.

The chat pipeline is exercised through the in-pod prober (a full non-stream
generation). We assert the answer GROUNDS a real, recent figure and names the
company — deterministic in shape (contains a $ price + the ticker/name), never
in exact value (prices move each session). rag_db persistence tables are checked
for existence (empty is fine on a fresh deploy with no user traffic).
"""

from __future__ import annotations

import re

from .. import harness as H
from .. import thresholds as T
from ..harness import Ctx

SVC = "rag-chat"

_PRICE = re.compile(r"\$\s?\d[\d,]*(\.\d+)?")


def run(ctx: Ctx) -> None:
    R = ctx.report

    row = ctx.api_row("chat")
    if not row:
        R.warn(SVC, "grounded golden answer", "chat not probed")
    elif row.get("status") != 200:
        R.fail(SVC, "grounded golden answer", f"HTTP {row.get('status')} {str(row.get('body', ''))[:140]}")
    else:
        _, parsed = _json(row)
        answer = ""
        if isinstance(parsed, dict):
            answer = str(parsed.get("answer") or parsed.get("message") or "")
        alow = answer.lower()
        long_enough = len(answer) >= T.RAG_MIN_ANSWER_LEN
        names_company = any(k in alow for k in T.RAG_GOLDEN_MUST_CONTAIN_ANY)
        has_price = bool(_PRICE.search(answer))
        R.check(
            SVC, "golden answer names the company", names_company and long_enough, f"{len(answer)}B: {answer[:90]!r}"
        )
        R.check(
            SVC,
            "golden answer grounds a $ price",
            has_price,
            f"price-token present={has_price}; {answer[:90]!r}",
            soft=True,
        )
        # Grounded answers must carry citation URLs, not just titles (F3: every
        # answer returned citations:[] or {title,url:null} — grounding links lost).
        cites = parsed.get("citations") if isinstance(parsed, dict) else None
        cites = cites if isinstance(cites, list) else []
        with_url = [c for c in cites if isinstance(c, dict) and c.get("url")]
        R.check(
            SVC,
            "grounded answer carries citation URLs",
            bool(with_url),
            f"{len(with_url)}/{len(cites)} citations have a url",
            soft=True,
        )

    _golden_no_false_refusal(
        ctx,
        "chat_fund",
        "date-anchored fundamentals returns stored value",
        T.RAG_DATE_ANCHOR_MUST_CONTAIN_ANY,
    )
    _golden_no_false_refusal(
        ctx,
        "chat_pred",
        "prediction-market question invokes the tool",
        T.RAG_PREDICTION_MUST_CONTAIN_ANY,
    )

    # rag_db persistence schema present (tables exist; row counts informational).
    q = H.psql_many(
        "rag_db",
        {
            "threads": "SELECT count(*) FROM threads",
            "messages": "SELECT count(*) FROM messages",
        },
    )
    have_schema = q["threads"] != "" and q["messages"] != ""
    R.check(
        SVC,
        "rag_db persistence schema present",
        have_schema,
        f"threads={q['threads'] or '?'} messages={q['messages'] or '?'}",
    )

    _cost_attribution_null_guard(ctx)


def _classify_null_ratio(
    *, total: int, nulls: int, warn_pct: float, fail_pct: float | None, min_rows: int
) -> tuple[str, str]:
    """Pure decision function for the BP-740-generalization NULL-ratio guard.

    Given the row/NULL counts for one `llm_usage_log` column over the lookback
    window, return `(status, detail)` where `status` is one of
    `H.PASS`/`H.WARN`/`H.FAIL`. Kept dependency-free (no `Ctx`/`Report`/psql) so
    the threshold arithmetic is unit-testable without a live cluster.

    * `total < min_rows`  -> WARN ("too little signal", not a verdict).
    * `fail_pct is None`  -> the column has a legitimate all/near-all-NULL
      population (e.g. `user_id` for system/background calls) — this column
      can only WARN, never FAIL, no matter how high the ratio climbs.
    * `ratio >= fail_pct` -> FAIL (the BP-740 signature: predominantly/entirely
      NULL over the whole window).
    * `ratio >= warn_pct` -> WARN (a partial-NULL band — some legitimate NULLs
      are expected, but this is high enough to flag).
    * otherwise           -> PASS.
    """
    if total < min_rows:
        return H.WARN, f"only {max(total, 0)} rows in window (< {min_rows}) — too little signal, skipped"
    ratio = H.pct(nulls, total)
    detail = f"{nulls}/{total} NULL ({ratio}%)"
    if fail_pct is not None and ratio >= fail_pct:
        return H.FAIL, detail
    if ratio >= warn_pct:
        return H.WARN, detail
    return H.PASS, detail


def _cost_attribution_null_guard(ctx: Ctx) -> None:
    """Generic NULL-ratio guard over `llm_usage_log`'s cost-attribution columns.

    BP-740: `chat_thread_id` was NULL on 100% of `llm_usage_log` rows for 7
    days in prod before anyone noticed — found only by a one-off manual audit
    query, never by an automated check. The specific bug (a persist-time UUID
    minted too late to reach the LLM calls made earlier in the same turn) now
    has solid unit + integration regression coverage in
    `chat_orchestrator.py` / `test_thread_user_attribution_e2e.py`. What was
    still missing is a check that would catch the NEXT similarly-shaped
    attribution bug — a different late-minted id, or a brand-new cost-bearing
    column that ships NULL-by-default — rather than only re-verifying the two
    fields this particular incident happened to hit.

    This check is deliberately generic: it walks `T.RAG_COST_ATTR_NULL_COLUMNS`
    (a list of `(column, warn_pct, fail_pct)` tuples), so extending coverage to
    a future column is a one-line threshold addition, not a new check
    function. Per-column thresholds are NOT uniform zero-tolerance — some
    columns (`user_id`) are nullable BY DESIGN for legitimate cases (system /
    background calls, per migration 0010's own docstring), so those columns
    are WARN-only (`fail_pct=None`) regardless of ratio; `chat_thread_id` and
    the token/cost columns, which should be populated on very nearly every row
    once BP-740's fix is in place, get both a WARN band and a hard FAIL floor
    that reproduces the exact "predominantly/entirely NULL" BP-740 signature.
    """
    R = ctx.report
    queries = {
        col: (
            f"SELECT count(*) || ':' || count(*) FILTER (WHERE {col} IS NULL) "
            f"FROM llm_usage_log WHERE created_at >= now() - interval '{T.RAG_COST_ATTR_WINDOW_HOURS} hours'"
        )
        for col, _, _ in T.RAG_COST_ATTR_NULL_COLUMNS
    }
    rows = H.psql_many("rag_db", queries)
    for col, warn_pct, fail_pct in T.RAG_COST_ATTR_NULL_COLUMNS:
        total_s, _, null_s = rows.get(col, "").partition(":")
        total, nulls = H.as_int(total_s), H.as_int(null_s)
        status, detail = _classify_null_ratio(
            total=total,
            nulls=nulls,
            warn_pct=warn_pct,
            fail_pct=fail_pct,
            min_rows=T.RAG_COST_ATTR_MIN_ROWS,
        )
        name = f"llm_usage_log.{col} not predominantly NULL ({T.RAG_COST_ATTR_WINDOW_HOURS:.0f}h window)"
        R.add(SVC, name, status, detail)


def _golden_no_false_refusal(ctx: Ctx, key: str, name: str, must_contain_any: list[str]) -> None:
    """Assert a chat answer whose ground truth IS in the store did not falsely
    refuse (audit FAIL class) and engages the subject.

    A refusal-template phrase + no expected keyword = a false "not available" or
    an un-routed tool (both FAILs in the 2026-07-15 chat-quality audit). A -1 /
    timeout status → WARN (cold-start hang, not a correctness verdict).
    """
    R = ctx.report
    row = ctx.api_row(key)
    if not row:
        R.warn(SVC, name, "not probed")
        return
    status = row.get("status")
    if status != 200:
        # -1 (timeout/cold-hang) is a known latency hazard, not a correctness FAIL.
        R.warn(SVC, name, f"HTTP {status} {str(row.get('error') or row.get('body', ''))[:80]}")
        return
    _, parsed = _json(row)
    answer = str(parsed.get("answer") or parsed.get("message") or "") if isinstance(parsed, dict) else ""
    alow = answer.lower()
    refused = any(p in alow for p in T.RAG_REFUSAL_PATTERNS)
    engaged = any(k.lower() in alow for k in must_contain_any)
    R.check(
        SVC,
        name,
        engaged and not refused,
        f"engaged={engaged} refused={refused}: {answer[:110]!r}",
    )


def _json(row: dict) -> tuple[int, object]:
    import json

    try:
        return row.get("status", 0), json.loads(row.get("body", ""))
    except ValueError:
        return row.get("status", 0), None
