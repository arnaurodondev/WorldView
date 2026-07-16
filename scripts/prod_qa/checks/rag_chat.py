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


def _json(row: dict) -> tuple[int, object]:
    import json

    try:
        return row.get("status", 0), json.loads(row.get("body", ""))
    except ValueError:
        return row.get("status", 0), None
