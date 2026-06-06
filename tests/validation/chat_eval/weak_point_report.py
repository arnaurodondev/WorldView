"""Markdown report generator for the 75-query weak-point survey.

Reads the in-memory list of (query_meta, ChatRunResult, grade) tuples that
the survey test accumulates, and emits a single markdown file under
``tests/validation/chat_eval/runs/<run_ts>/weak_point_report.md``.

The report has four sections:

1. Headline numbers — total queries, verdict breakdown, refusal rate,
   ungrounded-numbers rate, invented-quarter count.
2. Per-ticker breakdown — USEFUL / MARGINAL / USELESS / HARMFUL counts.
3. Per-metric-family breakdown — same counts, plus the "systematic
   failure" indicator (> 50% non-USEFUL across all tickers for one
   family is a P0 finding).
4. Failure log — the full list of HARMFUL + USELESS queries with
   reasons, latency, status code.

Pure function; tests import the entrypoint and pass the data in.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from tests.validation.chat_eval.grading import HARMFUL, MARGINAL, USEFUL, USELESS

# Type alias for one survey row.
SurveyRow = tuple[dict[str, Any], dict[str, Any]]
# meta = {ticker, metric_family, variant, question}; grade = grade_response dict.


def render_report(rows: Sequence[SurveyRow], *, out_path: Path) -> Path:
    """Write the markdown report and return the path written to.

    Caller passes the raw rows list — we own the format.
    """
    total = len(rows)
    verdicts = Counter(g.get("verdict") for _, g in rows)

    refusals = sum(1 for _, g in rows if g.get("verdict") == USELESS and any("refus" in r for r in g["reasons"]))
    ungrounded = sum(1 for _, g in rows if g.get("hallucination") == "YES")
    invented_quarters = sum(1 for _, g in rows if any("quarter" in r.lower() for r in g.get("reasons", [])))

    lines: list[str] = []
    lines.append("# Weak-Point Survey Report (PLAN-0093 Wave G-3 T-G-3-11)")
    lines.append("")
    lines.append(f"Total queries: **{total}**")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| Metric | Count | Rate |")
    lines.append("|---|---:|---:|")
    for v in (USEFUL, MARGINAL, USELESS, HARMFUL):
        c = verdicts.get(v, 0)
        rate = (c / total * 100) if total else 0.0
        lines.append(f"| {v} | {c} | {rate:.1f}% |")
    lines.append(f"| Refusals | {refusals} | {(refusals / total * 100 if total else 0):.1f}% |")
    lines.append(f"| Ungrounded numbers | {ungrounded} | {(ungrounded / total * 100 if total else 0):.1f}% |")
    lines.append(f"| Invented quarter labels | {invented_quarters} | — |")
    lines.append("")

    # ── Per-ticker breakdown ─────────────────────────────────────────────
    lines.append("## Per-Ticker Breakdown")
    lines.append("")
    lines.append("| Ticker | USEFUL | MARGINAL | USELESS | HARMFUL | Total |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    by_ticker: dict[str, Counter[str]] = defaultdict(Counter)
    for meta, grade in rows:
        by_ticker[meta["ticker"]][grade["verdict"]] += 1
    for ticker in sorted(by_ticker):
        tc: Counter[str] = by_ticker[ticker]
        ttot = sum(tc.values())
        lines.append(
            f"| {ticker} | {tc.get(USEFUL, 0)} | {tc.get(MARGINAL, 0)} | "
            f"{tc.get(USELESS, 0)} | {tc.get(HARMFUL, 0)} | {ttot} |"
        )
    lines.append("")

    # ── Per-metric-family breakdown ──────────────────────────────────────
    lines.append("## Per-Metric-Family Breakdown")
    lines.append("")
    lines.append("| Metric Family | USEFUL | MARGINAL | USELESS | HARMFUL | Total | Systematic-Failure? |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    by_metric: dict[str, Counter[str]] = defaultdict(Counter)
    for meta, grade in rows:
        by_metric[meta["metric_family"]][grade["verdict"]] += 1
    for mf in sorted(by_metric):
        mc: Counter[str] = by_metric[mf]
        mtot = sum(mc.values())
        non_useful = mtot - mc.get(USEFUL, 0)
        systematic = "**YES**" if mtot > 0 and (non_useful / mtot) > 0.5 else "no"
        lines.append(
            f"| {mf} | {mc.get(USEFUL, 0)} | {mc.get(MARGINAL, 0)} | "
            f"{mc.get(USELESS, 0)} | {mc.get(HARMFUL, 0)} | {mtot} | {systematic} |"
        )
    lines.append("")

    # ── Failure log ──────────────────────────────────────────────────────
    failures = [(m, g) for m, g in rows if g["verdict"] in (HARMFUL, USELESS)]
    lines.append(f"## Failure Log ({len(failures)})")
    lines.append("")
    if not failures:
        lines.append("_No HARMFUL or USELESS responses — the model held the line._")
    else:
        for meta, grade in failures:
            lines.append(
                f"- **{grade['verdict']}** "
                f"`{meta['ticker']}/{meta['metric_family']}/{meta['variant']}` "
                f"latency={grade.get('latency_s', 0):.2f}s "
                f"status={grade.get('status_code')}"
            )
            lines.append(f"  - Q: {meta['question']!r}")
            for r in grade["reasons"]:
                lines.append(f"  - reason: {r}")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    return out_path


# ---------------------------------------------------------------------------
# Aggregation helpers — used by the gate assertions in the test file.
# ---------------------------------------------------------------------------


def aggregate_stats(rows: Iterable[SurveyRow]) -> dict[str, Any]:
    """Return the summary stats the gate asserts on."""
    rows_list = list(rows)
    total = len(rows_list)
    if total == 0:
        return {
            "total": 0,
            "verdicts": Counter(),
            "refusal_rate": 0.0,
            "ungrounded_rate": 0.0,
            "invented_quarter_count": 0,
            "per_metric_non_useful_rate": {},
        }

    verdicts = Counter(g["verdict"] for _, g in rows_list)
    refusals = sum(1 for _, g in rows_list if g["verdict"] == USELESS and any("refus" in r for r in g["reasons"]))
    ungrounded = sum(1 for _, g in rows_list if g["hallucination"] == "YES")
    invented = sum(1 for _, g in rows_list if any("quarter" in r.lower() for r in g.get("reasons", [])))

    per_metric: dict[str, float] = {}
    by_metric: dict[str, Counter[str]] = defaultdict(Counter)
    for meta, grade in rows_list:
        by_metric[meta["metric_family"]][grade["verdict"]] += 1
    for mf, c in by_metric.items():
        tot = sum(c.values())
        per_metric[mf] = (tot - c.get(USEFUL, 0)) / tot if tot else 0.0

    return {
        "total": total,
        "verdicts": verdicts,
        "refusal_rate": refusals / total,
        "ungrounded_rate": ungrounded / total,
        "invented_quarter_count": invented,
        "per_metric_non_useful_rate": per_metric,
    }
