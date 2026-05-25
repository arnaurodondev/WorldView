"""Security regression tests for DeepInfra + OpenRouter adapters (PLAN-0093 QA-7).

F3: the `tool_call_bad_json` warning previously logged the first 100 chars of
the raw arguments string. That string can carry user-entered text from
LLM-generated tool arguments (e.g. `search_documents.query`), so it must not
appear in any structured log field. We now log only `raw_length` and `name`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
import structlog
from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter
from rag_chat.infrastructure.llm.openrouter_adapter import OpenRouterCompletionAdapter

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _structlog_to_stdlib() -> Iterator[None]:
    """Route structlog through stdlib so pytest's `caplog` can capture events.

    Same redirect pattern as test_tool_executor.py. Critical because the
    `tool_call_bad_json` warning is emitted via structlog; without this,
    caplog never sees the record and the redaction assertion is vacuous.

    WHY restore: ``structlog.configure`` mutates a process-global. Without a
    restore step, every subsequent test in the pytest session inherits the
    stdlib-routed config — including tests that rely on structlog's default
    stdout renderer (``capsys`` assertions in test_chat_orchestrator_tool_loop.py).
    """
    prior_config = structlog.get_config()
    structlog.configure(
        processors=[structlog.processors.KeyValueRenderer(key_order=["event"])],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    try:
        yield
    finally:
        structlog.reset_defaults()
        structlog.configure(**prior_config)


# Sentinel string we feed in as malformed arguments. The 20-char length is what
# the test asserts via raw_length; the substring "sensitive" is what the test
# asserts is NOT present anywhere in the captured log record.
_SENSITIVE_ARGS = "sensitive user query"  # 20 chars exactly


def _assert_redacted(caplog_records: list[logging.LogRecord]) -> None:
    """Assert that no captured record exposes the sensitive payload string.

    Under the test's structlog configuration (KeyValueRenderer + stdlib logging),
    every structured field is rendered into the LogRecord's message as
    ``key=value`` pairs. We therefore search:

    1. ``record.getMessage()`` — primary surface area;
    2. every string value in ``record.__dict__`` — defensive against renderers
       that stash fields as record attributes.

    We also assert that at least one record carries the ``tool_call_bad_json``
    event marker AND ``raw_length=20`` — confirming the diagnostic was emitted
    without the underlying payload.
    """
    saw_event = False
    saw_raw_length_20 = False
    for record in caplog_records:
        message = record.getMessage()
        # 1. Message must not leak the payload.
        assert "sensitive" not in message.lower(), f"message leaked: {message}"
        # 2. Walk every string attribute as well (some renderers stash fields here).
        for attr_name, attr_value in record.__dict__.items():
            if isinstance(attr_value, str):
                assert (
                    "sensitive" not in attr_value.lower()
                ), f"structured field '{attr_name}' leaked sensitive payload: {attr_value!r}"
        if "tool_call_bad_json" in message:
            saw_event = True
        # KeyValueRenderer writes `raw_length=20` into the message text.
        if "raw_length=20" in message:
            saw_raw_length_20 = True

    assert saw_event, "tool_call_bad_json event was not emitted"
    assert saw_raw_length_20, "expected `raw_length=20` on the warning record"


def test_deepinfra_tool_call_bad_json_redacts_raw_arguments(caplog) -> None:
    """Malformed JSON args -> log carries raw_length + name only, never the payload."""
    adapter = DeepInfraCompletionAdapter(api_key="x", http_client=AsyncMock())
    raw_calls = [
        {
            "id": "call_1",
            "function": {
                "name": "search_documents",
                # Invalid JSON (no quotes) so _parse_tool_calls hits the warning branch.
                "arguments": _SENSITIVE_ARGS,
            },
        }
    ]
    with caplog.at_level(logging.WARNING):
        result = adapter._parse_tool_calls(raw_calls)
    # Function still returns a ToolUseBlock with empty input (graceful degradation).
    assert len(result) == 1
    assert result[0].input == {}
    _assert_redacted(caplog.records)


def test_openrouter_tool_call_bad_json_redacts_raw_arguments(caplog) -> None:
    """Same redaction contract as DeepInfra — OpenRouter must not leak either."""
    adapter = OpenRouterCompletionAdapter(api_key="x", http_client=AsyncMock())
    raw_calls = [
        {
            "id": "call_1",
            "function": {
                "name": "search_documents",
                "arguments": _SENSITIVE_ARGS,
            },
        }
    ]
    with caplog.at_level(logging.WARNING):
        result = adapter._parse_tool_calls(raw_calls)
    assert len(result) == 1
    assert result[0].input == {}
    _assert_redacted(caplog.records)
