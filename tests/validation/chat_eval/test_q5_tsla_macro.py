"""Q5 — TSLA macro events (PLAN-0093 Wave G-3 T-G-3-06).

Pre-remediation symptom: a single failing economic-calendar call surfaced
as 503 without trying ``get_temporal_events`` or
``get_entity_event_exposures`` as alternates.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from tests.validation.chat_eval.grading import USELESS, grade_response

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

_QUESTION = "What macroeconomic events are likely to affect Tesla in the next 30 days?"
_GROUND_TRUTH = {
    "require_http_200": True,
    "required_tools_any_of": [
        "get_economic_calendar",
        "get_temporal_events",
        "get_entity_event_exposures",
    ],
    "min_distinct_tools": 2,
}


def test_q5_tsla_macro_events(ask: Callable[..., ChatRunResult]) -> None:
    """TSLA macro query must succeed and consult ≥ 2 calendar/events tools."""
    result = ask(_QUESTION, slot="q5")
    grade = grade_response(_QUESTION, result, _GROUND_TRUTH)

    assert result.status_code == 200, (
        f"Q5 returned HTTP {result.status_code} — single-tool failure regression. " f"error={result.error!r}"
    )
    assert grade["verdict"] != USELESS, f"Q5 verdict USELESS — reasons={grade['reasons']!r}"
