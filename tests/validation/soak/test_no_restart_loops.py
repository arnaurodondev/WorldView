"""T-G-2-05: No-restart-loop soak test (24h nightly).

PLAN-0093 Wave G-2 / audit refs F-LOG-002, F-NPL-002, F-REF-006.

Why this test exists
--------------------
After Sub-Plan A added health-gated ``depends_on`` clauses and ``restart``
policies, no worldview container should enter a sustained ``Restarting``
state — AND no container that was Up at soak start should silently slide
into an ``Exited``/``Dead``/``Created`` state and stay there.

PLAN-0093 Phase 5 QA-3 P1 — dual-streak detector
-------------------------------------------------
The original implementation grep'd ``"restarting"`` only.  That misses the
nastier silent-failure mode: a container that crashes hard, exhausts its
restart-policy retries (e.g. ``restart: on-failure:3`` workers) and ends up
``Exited`` while the rest of the platform keeps running.  ``Up X minutes
(unhealthy)`` is similarly hidden — the container is "running" but failing
liveness probes.

This refactor introduces a four-way classification (``up``, ``restarting``,
``down``, ``unknown``) and tracks two independent streaks per container:

1. ``consecutive_restarts`` — container is currently ``Restarting``.
2. ``consecutive_down``     — container *was* in the ``expected_up`` baseline
   at soak start but is now classified ``down`` (Exited / Dead / Created
   / Paused / unhealthy).

Either streak crossing ``_FAILURE_THRESHOLD`` fails the soak — both fast
crashloops and slow silent dropouts surface in the same run.

One-shot ``*-init`` and ``*-migrate`` containers are correctly EXCLUDED from
``expected_up`` because they are already ``Exited (0)`` at baseline.

Invocation
----------
Default ``pytest`` runs SKIP this test (``SOAK_TEST_ENABLED`` unset).  The
nightly CI cron should set:

    SOAK_TEST_ENABLED=1 \\
    WORLDVIEW_DOCKER_TEST_ALLOWED=1 \\
    SOAK_DURATION_MINUTES=1440 \\
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

# Consecutive failing samples that constitute a failure (applied independently
# to both the restart streak and the down streak).  3 x 5min = 15 minutes;
# legitimate transients (e.g. OOM kill recovery) resolve well inside that
# window.
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

# Substrings (lower-cased) that classify a container as "down" — i.e. it was
# Up at baseline but has now silently dropped off the running set.  Each
# entry maps to a real docker ``Status`` value seen in production:
#   * ``exited``  — container finished and was NOT restarted (policy=on-failure
#                   exhausted, or no policy + crashed)
#   * ``dead``    — daemon could not stop the container; broken state
#   * ``created`` — container exists but never started (image pull race)
#   * ``paused``  — explicitly paused via ``docker pause`` (unusual)
#   * ``unhealthy`` — substring appears in ``Up 5 minutes (unhealthy)``;
#                     liveness/readiness probes failing
_DOWN_STATUS_SUBSTRINGS: tuple[str, ...] = (
    "exited",
    "dead",
    "created",
    "paused",
    "unhealthy",
)


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


def _classify_status(status: str) -> str:
    """Bucket a docker Status string into ``up``/``restarting``/``down``/``unknown``.

    The classification order matters: we check ``restarting`` and ``down``
    substrings BEFORE accepting an ``Up`` prefix, because ``Up 5 minutes
    (unhealthy)`` should classify as ``down`` not ``up``.
    """
    lower = status.lower()
    if "restarting" in lower:
        return "restarting"
    # Check "down" substrings first so "(unhealthy)" wins over "Up".
    for needle in _DOWN_STATUS_SUBSTRINGS:
        if needle in lower:
            return "down"
    if lower.startswith("up"):
        return "up"
    return "unknown"


def _snapshot_container_states() -> dict[str, str]:
    """Return ``{container_name: classification}`` for every worldview container.

    Uses ``docker ps -a --format`` so we get a stable tab-separated output
    regardless of the operator's docker version.  Filters to the worldview
    prefix to avoid false positives from unrelated containers on the host.

    Replaces the old ``_list_restarting_containers()`` helper.  The richer
    return type lets the caller track both restart streaks AND silent-down
    streaks against the baseline (see ``test_no_container_in_sustained...``).
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

    states: dict[str, str] = {}
    for line in result.stdout.splitlines():
        # Expected format: "<status>\t<name>".  Split once on tab so a status
        # field with whitespace (which is common) doesn't break parsing.
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, name = parts
        if not name.startswith(_CONTAINER_PREFIX):
            continue
        states[name] = _classify_status(status)
    return states


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
    """No worldview container should be Restarting *or* silently Down for the threshold window.

    Walks the full soak duration polling every ``_POLL_INTERVAL_S`` seconds.
    Maintains two per-container streak counters:

    * ``consecutive_restarts[name]`` — currently in ``restarting`` state.
    * ``consecutive_down[name]``     — was Up at baseline but is now in
      ``down`` (Exited / unhealthy / dead / paused / created).

    Either streak crossing ``_FAILURE_THRESHOLD`` fails the test with the
    container name + log tail.  Reset on first sample where the container
    returns to ``up`` so transient blips do not accumulate.
    """
    _require_soak_enabled()
    _require_docker_destructive_allowed()

    duration_s = _soak_duration_s()
    deadline = time.monotonic() + duration_s

    # Take the baseline at soak start.  One-shot ``*-init`` and ``*-migrate``
    # containers are already ``Exited (0)`` here, so they are CORRECTLY
    # excluded from ``expected_up`` — they will never appear in the
    # ``consecutive_down`` map even when they remain Exited for hours.
    baseline_states = _snapshot_container_states()
    expected_up: frozenset[str] = frozenset(name for name, cls in baseline_states.items() if cls == "up")
    print(
        f"[soak baseline] total_containers={len(baseline_states)} "
        f"expected_up={len(expected_up)} "
        f"(baseline excludes init/migrate one-shots)"
    )

    consecutive_restarts: dict[str, int] = {}
    consecutive_down: dict[str, int] = {}

    sample = 0
    while time.monotonic() < deadline:
        sample += 1
        states = _snapshot_container_states()

        # ── Restart streak (every container, not just baseline) ──────────────
        currently_restarting = {name for name, cls in states.items() if cls == "restarting"}
        for name in currently_restarting:
            consecutive_restarts[name] = consecutive_restarts.get(name, 0) + 1
        for name in list(consecutive_restarts):
            if name not in currently_restarting:
                consecutive_restarts[name] = 0

        # ── Down streak (only baseline-Up containers) ────────────────────────
        # A baseline-Up container is "down" this sample if it is now classified
        # as ``down`` OR is missing from the snapshot entirely (the container
        # was removed by `docker rm` while soak was running — also a violation).
        currently_down: set[str] = set()
        for name in expected_up:
            cls = states.get(name, "down")  # missing = down
            if cls == "down" or cls == "unknown":
                currently_down.add(name)
        for name in currently_down:
            consecutive_down[name] = consecutive_down.get(name, 0) + 1
        for name in list(consecutive_down):
            if name not in currently_down:
                consecutive_down[name] = 0

        # ── Per-sample progress line — visible with pytest -s ────────────────
        restart_offenders = sorted(
            ((n, s) for n, s in consecutive_restarts.items() if s > 0),
            key=lambda x: -x[1],
        )
        down_offenders = sorted(
            ((n, s) for n, s in consecutive_down.items() if s > 0),
            key=lambda x: -x[1],
        )
        restart_str = ", ".join(f"{n}(streak={s})" for n, s in restart_offenders[:5]) or "none"
        down_str = ", ".join(f"{n}(streak={s})" for n, s in down_offenders[:5]) or "none"
        print(
            f"[soak sample {sample}] "
            f"restarting={len(currently_restarting)} restart_offenders=[{restart_str}] "
            f"down={len(currently_down)} down_offenders=[{down_str}]"
        )

        # ── Threshold check (either streak type fails the soak) ──────────────
        # Restart streak first — usually the louder failure mode.
        for name, streak in restart_offenders:
            if streak >= _FAILURE_THRESHOLD:
                logs = _tail_logs(name)
                pytest.fail(
                    f"Container {name!r} has been Restarting for {streak} consecutive "
                    f"samples ({streak * _POLL_INTERVAL_S / 60:.0f} minutes). "
                    f"This violates the F-LOG-002 / F-NPL-002 / F-REF-006 SLO.\n\n"
                    f"Last {_LOG_TAIL_LINES} log lines:\n{logs}"
                )
        for name, streak in down_offenders:
            if streak >= _FAILURE_THRESHOLD:
                logs = _tail_logs(name)
                pytest.fail(
                    f"Container {name!r} was Up at soak baseline but has been "
                    f"classified Down (Exited/unhealthy/dead/missing) for "
                    f"{streak} consecutive samples "
                    f"({streak * _POLL_INTERVAL_S / 60:.0f} minutes). "
                    f"This is the PLAN-0093 QA-3 silent-dropout failure mode "
                    f"(restart policy missing or restart-retries exhausted).\n\n"
                    f"Last {_LOG_TAIL_LINES} log lines:\n{logs}"
                )

        # Sleep until the next poll, unless we'd cross the deadline first.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_POLL_INTERVAL_S, remaining))

    # If we got here, no container crossed the threshold — soak passed.
    # Emit a final summary line so nightly logs always have a clear marker.
    trailing_restart = sum(1 for s in consecutive_restarts.values() if s > 0)
    trailing_down = sum(1 for s in consecutive_down.values() if s > 0)
    print(
        f"[soak complete] samples={sample} duration={duration_s / 60:.1f}min "
        f"trailing_restart_offenders={trailing_restart} "
        f"trailing_down_offenders={trailing_down}"
    )
