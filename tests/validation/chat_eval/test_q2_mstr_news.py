"""Q2 — MSTR news multi-tool fallback (PLAN-0093 Wave G-3 T-G-3-03).

Pre-remediation symptom: a single failing news-search call returned 503
``PROVIDER_UNAVAILABLE`` with no fallback. The fix (Wave E-3) added name
resolution + multi-tool fallback so the orchestrator can compose news
search with entity-intelligence + price-news cross-reference.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from tests.validation.chat_eval.grading import USELESS, grade_response

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

_QUESTION = "Show me the latest news on MSTR — what should I know?"
_GROUND_TRUTH = {
    "require_http_200": True,
    "min_distinct_tools": 2,
    "must_mention_any_of": ["Bitcoin", "BTC"],
}


def test_q2_mstr_news(ask: Callable[..., ChatRunResult]) -> None:
    """MSTR news query must succeed (no 503), use ≥ 2 tools, mention BTC."""
    result = ask(_QUESTION, slot="q2")
    grade = grade_response(_QUESTION, result, _GROUND_TRUTH)

    # Hard gate on the 503 regression — the bug was a single-tool failure
    # cascading to a fatal response.
    assert result.status_code == 200, (
        f"Q2 returned HTTP {result.status_code} — multi-tool fallback regressed; " f"error={result.error!r}"
    )
    assert grade["verdict"] != USELESS, f"Q2 verdict USELESS — reasons={grade['reasons']!r}"
