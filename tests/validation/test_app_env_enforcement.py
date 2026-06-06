"""T-G-2-04: APP_ENV enforcement integration test.

PLAN-0093 Wave G-2 / audit ref F-LOG-JWT-001.

Why this test exists
--------------------
``observability.startup_assert.assert_app_env_or_die`` was added in Sub-Plan A
to refuse to start any service when ``internal_jwt_skip_verification=True``
AND ``APP_ENV`` is unset.  The library-level behaviour is covered by
``libs/observability/tests/test_startup_assert.py``.

This test is the **service-level belt-and-braces**: it asserts that an actual
service process, when invoked with the unsafe combination, exits with a
non-zero code AND emits the structured log event ``startup_security_check_failed``
before dying.  Catches drift like a future refactor that swallows the
``RuntimeError`` or forgets to wire the helper into ``lifespan``.

Two execution paths
-------------------
1. **Process-level test (preferred, always runs)** — spawns a Python
   subprocess that imports the helper, calls it with the dangerous
   combination, and asserts the process exits with non-zero code and stderr
   contains the security event name.  Has no external dependencies.
2. **Docker-level test (opt-in)** — spins up the actual rag-chat container
   and asserts it exits with non-zero code.  Gated on
   ``WORLDVIEW_DOCKER_TEST_ALLOWED=1`` because it requires a built image
   and ~20 seconds of container boot time.

The two halves complement each other: the process-level test runs in CI on
every PR; the docker-level test runs in nightly soak / pre-release.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time

import pytest

# ---------------------------------------------------------------------------
# Tunables.
# ---------------------------------------------------------------------------

# How long we wait for the subprocess (or container) to die.  The startup
# assertion is synchronous and runs before FastAPI binds the port, so a
# clean exit should be near-instant; 30s is the SLO threshold from F-LOG-JWT-001.
_EXIT_BUDGET_S = 30.0

# The stable structured-log event name that the security alert pipeline
# matches on (defined in ``libs/observability/src/observability/startup_assert.py``).
_EXPECTED_LOG_EVENT = "startup_security_check_failed"

# The rag-chat docker image name (matches ``services/rag-chat/Dockerfile``
# build target).  Override for non-default compose project layouts.
_RAG_CHAT_IMAGE = os.environ.get("RAG_CHAT_IMAGE", "worldview-rag-chat")


# ---------------------------------------------------------------------------
# Gating helpers.
# ---------------------------------------------------------------------------


def _require_docker_destructive_allowed() -> None:
    """Skip unless the operator has explicitly enabled docker subprocess calls."""
    if os.environ.get("WORLDVIEW_DOCKER_TEST_ALLOWED") != "1":
        pytest.skip("WORLDVIEW_DOCKER_TEST_ALLOWED!=1 — skipping docker-level enforcement test")


# ---------------------------------------------------------------------------
# Process-level test — always runs.
# ---------------------------------------------------------------------------


def test_assert_app_env_or_die_exits_subprocess() -> None:
    """A Python subprocess invoking the helper with the unsafe combo must die.

    We invoke a tiny inline script that:
    1. Clears ``APP_ENV`` from the environment (so the helper sees it unset).
    2. Calls ``assert_app_env_or_die`` with ``internal_jwt_skip_verification=True``.
    3. Expects the helper to raise ``RuntimeError`` and the process to exit
       non-zero.

    Asserts:
    * Process exit code != 0 within ``_EXIT_BUDGET_S``.
    * stderr (where structlog writes by default in subprocess context) contains
      the security event name ``startup_security_check_failed``.

    This is the cheaper half of the test pair — it doesn't need Docker and
    runs in <2s on a warm Python.
    """
    # Inline script: kept tiny so failures are easy to diagnose.  ``textwrap.dedent``
    # keeps the literal readable here without leaking leading whitespace into
    # the Python source the subprocess executes.
    script = textwrap.dedent(
        """
        # The helper reads APP_ENV from os.environ directly, so we don't need
        # to import settings or touch any service config.
        from observability.startup_assert import assert_app_env_or_die

        # Trigger the dangerous combination.  The helper logs CRITICAL first
        # and THEN raises — the structured event must already be on stderr
        # by the time the traceback is written.
        assert_app_env_or_die(
            service_name="t-g-2-04-test",
            internal_jwt_skip_verification=True,
        )
        """
    ).strip()

    # Build an environment with APP_ENV stripped.  Inherit PYTHONPATH and the
    # rest of os.environ so the subprocess can find ``observability`` (which
    # is editable-installed in the dev venv).
    env = {k: v for k, v in os.environ.items() if k != "APP_ENV"}

    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=_EXIT_BUDGET_S,
        env=env,
        check=False,
    )
    elapsed = time.monotonic() - start

    # 1. Process must die within budget.
    assert elapsed < _EXIT_BUDGET_S, f"subprocess took {elapsed:.1f}s to exit (budget {_EXIT_BUDGET_S}s)"

    # 2. Exit code must be non-zero.  RuntimeError from main propagates to
    #    exit code 1 in CPython.
    assert result.returncode != 0, (
        "subprocess exited 0 — startup security check did NOT abort. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    # 3. The structured event must appear in stderr.  structlog writes JSON
    #    to stderr by default in a subprocess (no TTY) — we search both
    #    streams to be robust to log routing changes.
    combined_output = result.stdout + result.stderr
    assert _EXPECTED_LOG_EVENT in combined_output, (
        f"expected log event {_EXPECTED_LOG_EVENT!r} not found in subprocess output. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Docker-level test — opt-in.
# ---------------------------------------------------------------------------


def test_rag_chat_container_refuses_unsafe_boot() -> None:
    """The rag-chat container must exit non-zero when started with the unsafe combo.

    Mirrors the subprocess test but validates the end-to-end lifespan wiring
    in the actual service image.  Catches drift like a future refactor that
    silently skips the helper call.

    Gated on ``WORLDVIEW_DOCKER_TEST_ALLOWED=1`` because:
    * Requires the rag-chat image to be built (``make build`` or compose).
    * Pulls/runs a docker container, which is destructive on a shared host.
    """
    _require_docker_destructive_allowed()

    # We deliberately use ``docker run --rm`` (not ``compose up``) so the
    # test is self-contained and doesn't leave a stopped container behind
    # if it fails mid-flight.  ``--name`` is unique per test run to avoid
    # collisions with any compose-managed instance.
    container_name = f"worldview-rag-chat-g24-{int(time.monotonic())}"

    # Environment: explicitly clear APP_ENV and set the skip flag.  We do NOT
    # pass --env-file because the docker.env file sets APP_ENV=development,
    # which would mask the bug we're testing.
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "-e",
        "INTERNAL_JWT_SKIP_VERIFICATION=true",
        # APP_ENV is intentionally absent — that is the dangerous condition.
        _RAG_CHAT_IMAGE,
    ]

    start = time.monotonic()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_EXIT_BUDGET_S + 15.0,  # +15s for image pull / container init
        check=False,
    )
    elapsed = time.monotonic() - start

    # The startup assertion runs BEFORE FastAPI binds, so the container should
    # exit well within the budget.  We give a 10s grace for container boot
    # overhead on top of the 30s SLO.
    boot_grace = 10.0
    assert (
        elapsed < _EXIT_BUDGET_S + boot_grace
    ), f"container took {elapsed:.1f}s to exit (budget {_EXIT_BUDGET_S + boot_grace}s)"

    assert result.returncode != 0, (
        "rag-chat container exited 0 — APP_ENV enforcement bypassed. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    combined_output = result.stdout + result.stderr
    assert _EXPECTED_LOG_EVENT in combined_output, (
        f"expected log event {_EXPECTED_LOG_EVENT!r} not found in container output. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
