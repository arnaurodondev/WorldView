"""Regression test — DB session-parity gate is STRICT, not advisory (BP-732).

Context: ``scripts/check_db_session_parity.py`` (BP-732's automated backstop
for the "every pooled session file must set command_timeout +
statement_timeout" hardening lesson) supports a ``--strict`` flag that turns a
detected parity gap into a non-zero exit code. Until 2026-07-24, the CI job
(``.github/workflows/ci.yml`` ``db-session-parity``) ran it WITHOUT
``--strict`` — a warn-only mode kept in place solely because market-data had
one known, real gap (missing ``command_timeout``) that nobody had gotten
around to fixing. A parity gap in a pooled service's Postgres connection
hardening is exactly the class of regression that caused the 2026-07-19/22
postgres OOM incidents (BP-730/BP-732) — advisory-only CI meant a NEW gap
(e.g. a freshly scaffolded pooled service that forgets both timeout knobs)
would never fail a PR.

This test closes that loop two ways:
  1. Asserts the CI workflow actually invokes the script with ``--strict``
     (guards against a future silent revert to warn-only).
  2. Runs the real ``check_db_session_parity.main(["--strict"])`` against
     THIS repo's actual `services/` tree and asserts it exits 0 — i.e. no
     pooled session file currently has a parity gap. This is what
     ``services/market-data/src/market_data/infrastructure/db/session.py``
     was fixed for (it added ``command_timeout`` to close the one
     documented gap the warn-only comment referenced) — if a future change
     reintroduces a gap in ANY service, this test fails locally/in CI
     exactly like the (now strict) CI job would.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_parity_module() -> Any:
    path = _REPO_ROOT / "scripts" / "check_db_session_parity.py"
    spec = importlib.util.spec_from_file_location("_check_db_session_parity_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_ci_workflow_runs_the_check_in_strict_mode() -> None:
    """`.github/workflows/ci.yml`'s db-session-parity job must pass --strict.

    A regression here (dropping the flag, e.g. during an unrelated CI-file
    edit) would silently downgrade a real, currently-fixed parity gap class
    back to warn-only — exactly the gap this whole test module exists to
    close.
    """
    ci_yaml = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    match = re.search(r"run:\s*python\s+scripts/check_db_session_parity\.py(\s+--strict)?", ci_yaml)
    assert match is not None, "db-session-parity CI step not found (or its `run:` line changed shape)"
    assert match.group(1), "CI must invoke check_db_session_parity.py with --strict, not warn-only"


def test_no_parity_gaps_in_strict_mode_against_the_real_services_tree() -> None:
    """The real check, run --strict against this repo's actual services/,
    must currently exit 0 — i.e. every pooled session file sets BOTH
    command_timeout and statement_timeout (the market-data gap referenced by
    the old warn-only CI comment has been fixed)."""
    mod = _load_parity_module()
    original_argv = sys.argv
    sys.argv = ["check_db_session_parity.py", "--strict"]
    try:
        exit_code = mod.main()
    finally:
        sys.argv = original_argv
    assert exit_code == 0, f"strict run exited {exit_code} — a pooled session file has a parity gap"

    session_files = mod._find_session_files()
    assert session_files, "no session.py files found — path glob likely stale, cannot validate strict mode"
    statuses = [mod._classify(service, path) for service, paths in session_files.items() for path in paths]
    pooled_gaps = [s for s in statuses if s.pooled and s.missing]
    assert not pooled_gaps, (
        "pooled session file(s) missing a hardening knob — this is exactly what --strict now fails CI on: "
        + "; ".join(f"{s.label} missing {s.missing}" for s in pooled_gaps)
    )
