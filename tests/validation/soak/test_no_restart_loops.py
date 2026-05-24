"""T-G-2-05: No-restart-loop soak test (24h nightly).

PLAN-0093 Wave G-2 / audit refs F-LOG-002, F-NPL-002, F-REF-006.

Why this test exists
--------------------
After Sub-Plan A added health-gated ``depends_on`` clauses and ``restart``
policies, no worldview container should enter a sustained ``Restarting``
state.  ``Restarting`` is a classic silent-failure mode: ``docker ps`` shows
the container "exists" but it's actually crashlooping every 60 seconds.

This soak test polls ``docker ps -a`` every 5 minutes and fails the run if
any container shows ``Restarting`` for 3 consecutive samples (= ~10-15
minutes of crashlooping, well above any legitimate transient).  On failure
it dumps the container name and the last 50 log lines so the operator can
diagnose without re-running.

Invocation
----------
Default ``pytest`` runs SKIP this test (``SOAK_TEST_ENABLED`` unset).  The
nightly CI cron should set:

    SOAK_TEST_ENABLED=1 \
    WORLDVIEW_DOCKER_TEST_ALLOWED=1 \
    SOAK_DURATION_MINUTES=1440 \
    pytest tests/validation/soak/test_no_restart_loops.py -v -s

The ``-s`` flag preserves stdout so the per-poll progress lines surface in
real time.  For a quick smoke (15 minutes), set ``SOAK_DURATION_MINUTES=15``.

Why ``docker ps`` subprocess (not docker-py SDK)
------------------------------------------------
Keeping the dep surface minimal — the platform doesn't pin ``docker-py`` and
adding it just for this one test would be overkill.  The ``--format`` flag
gives us a clean tab-separated string that's trivial to parse.
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest

# ---------------------------------------------------------------------------
# Tunables.
# ---------------------------------------------------------------------------

# Poll cadence — every 5 minutes per the plan spec.  Container restarts have
# a default ``restart-delay-ms`` of 100ms and most workers set a
# 30-second healthcheck interval, so 5 minutes is fine-grained enough to
# catch sustained crashloops without spamming the docker daemon.
_POLL_INTERVAL_S = 5 * 60.0

# Consecutive ``Restarting`` samples that constitute a failure.  3 x 5min =
# 15 minutes of crashlooping; legitimate transients (e.g. OOM kill recovery)
# resolve well inside that window.
_FAILURE_THRESHOLD = 3

# How many tail lines of container logs to dump on failure.  50 is enough
# context for most crashloops without producing wall-of-text reports.
_LOG_TAIL_LINES = 50

# Default soak duration if ``SOAK_DURATION_MINUTES`` is unset.  24 hours
# matches the F-LOG-002 SLO requirement.
_DEFAULT_DURATION_MINUTES = 1440

# Substring filter for worldview containers.  All compose-managed containers
# share the ``worldview-`` prefix (the default ``COMPOSE_PROJECT_NAME``).
_CONTAINER_PREFIX = os.environ.get("WORLDVIEW_CONTAINER_PREFIX", "worldview-")


# ---------------------------------------------------------------------------
# Gating.
# ---------------------------------------------------------------------------


def _require_soak_enabled() -> None:
    """Skip unless the operator explicitly opted in to a soak run."""
    if os.environ.get("SOAK_TEST_ENABLED") != "1":
        pytest.skip("SOAK_TEST_ENABLED!=1 — skipping nightly soak (set =1 to enable)")


def _require_docker_destructive_allowed() -> None:
    """Skip unless the operator opted in to docker subprocess calls.

    Reading ``docker ps`` is read-only, but we use the same opt-in env var
    as the destructive tests for consistency — the soak runner has docker
    access by definition.
    """
    if os.environ.get("WORLDVIEW_DOCKER_TEST_ALLOWED") != "1":
        pytest.skip("WORLDVIEW_DOCKER_TEST_ALLOWED!=1 — skipping docker poll test")


def _soak_duration_s() -> float:
    """Return the configured soak duration in seconds."""
    raw = os.environ.get("SOAK_DURATION_MINUTES", str(_DEFAULT_DURATION_MINUTES))
    try:
        minutes = float(raw)
    except ValueError:
        pytest.fail(f"SOAK_DURATION_MINUTES={raw!r} is not a number")
    if minutes <= 0:
        pytest.fail(f"SOAK_DURATION_MINUTES={minutes} must be positive")
    return minutes * 60.0


# ---------------------------------------------------------------------------
# Docker subprocess helpers.
# ---------------------------------------------------------------------------


def _list_restarting_containers() -> list[str]:
    """Return the names of worldview containers currently in ``Restarting`` state.

    Uses ``docker ps -a --format`` so we get a stable tab-separated output
    regardless of the operator's docker version.  Filters to the worldview
    prefix to avoid false positives from unrelated containers on the host.
    """
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Status}}\t{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"docker ps failed (rc={result.returncode}): stderr={result.stderr!r}")

    restarting: list[str] = []
    for line in result.stdout.splitlines():
        # ``{{.Status}}`` looks like "Restarting (1) 5 seconds ago" or
        # "Up 3 minutes (healthy)".  Case-insensitive substring match catches
        # both "Restarting" and any future docker variants.
        if "restarting" not in line.lower():
            continue
        # Expected format: "<status>\t<name>".  Split once on tab so a status
        # field with whitespace (which is common) doesn't break parsing.
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        _, name = parts
        if name.startswith(_CONTAINER_PREFIX):
            restarting.append(name)
    return restarting


def _tail_logs(container: str) -> str:
    """Return the last ``_LOG_TAIL_LINES`` of *container*'s logs (best effort)."""
    result = subprocess.run(
        ["docker", "logs", "--tail", str(_LOG_TAIL_LINES), container],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    # Combine stdout + stderr because many services log to stderr.  Even on
    # non-zero return we surface whatever we got.
    return f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"


# ---------------------------------------------------------------------------
# The actual soak.
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_no_container_in_sustained_restart_loop() -> None:
    """No worldview container should ``Restarting`` for ``_FAILURE_THRESHOLD`` consecutive samples.

    Walks the full soak duration polling every ``_POLL_INTERVAL_S`` seconds.
    Maintains a per-container consecutive-strikes counter; when any container
    hits the threshold we fail the test with its name + log tail and abort
    the loop early.
    """
    _require_soak_enabled()
    _require_docker_destructive_allowed()

    duration_s = _soak_duration_s()
    deadline = time.monotonic() + duration_s

    # consecutive_restarts[name] = current streak length.  Reset to 0 the
    # moment a container leaves the Restarting state — only sustained loops
    # are failures.
    consecutive_restarts: dict[str, int] = {}

    sample = 0
    while time.monotonic() < deadline:
        sample += 1
        restarting = _list_restarting_containers()
        currently_restarting = set(restarting)

        # Increment streak for everyone currently restarting; reset everyone else.
        for name in currently_restarting:
            consecutive_restarts[name] = consecutive_restarts.get(name, 0) + 1
        for name in list(consecutive_restarts):
            if name not in currently_restarting:
                consecutive_restarts[name] = 0

        # Per-sample progress line — visible with pytest -s.
        # Format: ``[soak sample N] restarting=K offenders=[name(streak=M), ...]``
        offenders = [(n, s) for n, s in consecutive_restarts.items() if s > 0]
        offenders.sort(key=lambda x: -x[1])  # Worst-first.
        offender_str = ", ".join(f"{n}(streak={s})" for n, s in offenders[:5]) or "none"
        print(f"[soak sample {sample}] restarting={len(currently_restarting)} offenders=[{offender_str}]")

        # Check for any container that has crossed the failure threshold.
        # Sorting by streak (desc) ensures we surface the worst offender first.
        for name, streak in sorted(consecutive_restarts.items(), key=lambda x: -x[1]):
            if streak >= _FAILURE_THRESHOLD:
                logs = _tail_logs(name)
                pytest.fail(
                    f"Container {name!r} has been Restarting for {streak} consecutive "
                    f"samples ({streak * _POLL_INTERVAL_S / 60:.0f} minutes). "
                    f"This violates the F-LOG-002 / F-NPL-002 / F-REF-006 SLO.\n\n"
                    f"Last {_LOG_TAIL_LINES} log lines:\n{logs}"
                )

        # Sleep until the next poll, unless we'd cross the deadline first.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_POLL_INTERVAL_S, remaining))

    # If we got here, no container crossed the threshold — soak passed.
    # Emit a final summary line so nightly logs always have a clear marker.
    total_offenders = sum(1 for s in consecutive_restarts.values() if s > 0)
    print(
        f"[soak complete] samples={sample} duration={duration_s / 60:.1f}min " f"trailing_offenders={total_offenders}"
    )
