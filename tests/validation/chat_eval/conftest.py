"""Pytest fixtures for the chat-eval regression suite (PLAN-0093 Wave G-3).

Provides:
* ``chat_client`` — session-scoped :class:`RagChatClient` (dev JWT cached).
* ``run_ts``      — UTC timestamp string used as the artefact subdir name,
                    so all questions in one ``pytest`` invocation share a dir.
* ``ask``         — function fixture: ``ask(question, slot=...)`` → result
                    AND persists the artefact in one call.

All fixtures degrade to ``pytest.skip`` when ``RAG_CHAT_BASE_URL`` is unset,
so collection always succeeds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest

from tests.validation.chat_eval.harness import (
    ChatRunResult,
    RagChatClient,
    make_client_or_skip,
    save_result,
)

# ---------------------------------------------------------------------------
# Shared session-scoped run-timestamp so artefacts from one ``pytest`` call
# land in the same ``runs/<ts>/`` folder. We compute it once at fixture
# import time (session scope) and pass it into ``save_result`` everywhere.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def run_ts() -> str:
    """UTC timestamp string for the current pytest session — names runs/<ts>/.

    Computed once per session so every per-question test in the run writes
    to the same directory.
    """
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


@pytest.fixture(scope="session")
def chat_client() -> Iterator[RagChatClient]:
    """Session-scoped :class:`RagChatClient` — skips if no base URL is set.

    Reuses one HTTP client (and one dev JWT) across all Q1..Q8 + survey
    tests for the run.
    """
    client = make_client_or_skip()
    try:
        # Eagerly call dev-login so collection-time failures surface as a
        # clean skip rather than mid-test 401s.
        client.login()
        yield client
    finally:
        client.close()


@pytest.fixture
def ask(chat_client: RagChatClient, run_ts: str) -> Callable[..., ChatRunResult]:
    """Function fixture: ``ask(question, slot=...)`` → result + artefact persisted.

    Tests use this instead of calling ``chat_client.ask`` directly so the
    artefact is always saved (debuggability) without per-test boilerplate.
    """

    def _ask(question: str, *, slot: str, entity_ids: list[str] | None = None) -> ChatRunResult:
        result = chat_client.ask(question, entity_ids=entity_ids)
        save_result(result, slot=slot, run_ts=run_ts)
        return result

    return _ask
