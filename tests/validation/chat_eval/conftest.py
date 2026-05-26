"""Pytest fixtures for the chat-eval regression suite (PLAN-0093 Wave G-3).

Provides:
* ``chat_client`` — session-scoped :class:`RagChatClient` (dev JWT cached).
* ``run_ts``      — UTC timestamp string used as the artefact subdir name,
                    so all questions in one ``pytest`` invocation share a dir.
* ``ask``         — function fixture: ``ask(question, slot=...)`` → result
                    AND persists the artefact in one call.

All fixtures degrade to ``pytest.skip`` when ``RAG_CHAT_BASE_URL`` is unset,
so collection always succeeds.

----------------------------------------------------------------------------
Eval-harness invariants (PLAN-0093 compounding — DO NOT REGRESS)
----------------------------------------------------------------------------
Three rules learned the hard way during PLAN-0093 ITER 2-5 (4+ false-fail
debug cycles, ~6 hours wasted):

1. Use a fresh ``thread_id`` per test, OR set ``RAG_COMPLETION_CACHE_DISABLED=true``.
   The rag-chat completion cache keys by ``thread_id`` (and prompt-version hash
   after FIX-LIVE-A / BP-559). A module-scoped ``thread_id`` will serve a
   cached answer from an earlier run, masking regressions for days. See
   ``ChatRunResult.thread_id`` — it MUST be a per-test ``uuid4()``.

2. Refresh the JWT on 401. Gateway user JWTs have a 5-minute TTL; a harness
   that caches the JWT in a module/session scope will start to fail with 401
   ~5 minutes into any run, and every chat-eval test will appear to fail with
   an infra artefact. ``RagChatClient`` MUST retry once with a freshly minted
   dev-JWT on any 401 response (commit ``ac444369``).

3. Re-run on known-transient terminal errors. DeepInfra occasionally returns
   5xx / first-turn-failed on iteration-0; treating these as hard test
   failures wastes hours of triage. The harness SHOULD wrap the grader
   verdict with a 2-retry decorator for the transient set:
       {llm_first_turn_failed, provider_chat_with_tools_failed, HTTP 502/503/504}
   See BP-561 (still OPEN — queued for PLAN-0094 harness work). Until that
   lands, any single-shot failure with one of these terminal codes should
   be re-run manually before declaring a regression.

If you change the cache key, the JWT TTL, or the transient-error set, also
update BP-559 / BP-560 / BP-561 in ``docs/BUG_PATTERNS.md``.
"""

from __future__ import annotations

import os
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


# ---------------------------------------------------------------------------
# Cache-disable fixture (PLAN-0095 W3 T-W3-04).
#
# The completion cache is a production latency optimisation; eval runs must
# measure cold-path behaviour so regressions surface immediately rather than
# the day after the TTL expires. We export ``RAG_COMPLETION_CACHE_DISABLED=
# true`` for the whole session, and restore the prior value on teardown so a
# parent pytest invocation that intentionally set the env keeps its state.
#
# Combined with the per-call ``thread_id`` invariant (harness.py T-W3-03),
# the eval session is now belt-and-suspenders cache-isolated.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _disable_completion_cache() -> Iterator[None]:
    """Force ``RAG_COMPLETION_CACHE_DISABLED=true`` for the chat-eval session."""

    key = "RAG_COMPLETION_CACHE_DISABLED"
    prior = os.environ.get(key)
    os.environ[key] = "true"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior


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
