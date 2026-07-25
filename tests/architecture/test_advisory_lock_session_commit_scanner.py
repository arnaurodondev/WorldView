"""
Unit tests for the AST scanner helpers in
``tests/architecture/test_advisory_lock_session_commit_enforcement.py``
(rule ADVISORY-LOCK-COMMIT-001).

These exercise the scanner against synthetic, hand-written source samples —
independent of the real repo scan — so the heuristic's precision (no false
positives) and its documented false-negative tradeoffs (cross-function
commits are NOT caught) are both pinned down and regression-tested in
isolation. Mirrors the style of ``test_utils_process_topology.py`` (synthetic
``tmp_path`` files + ``textwrap.dedent`` samples) rather than
``test_dedup_prelookup_enforcement.py`` (which has no standalone unit suite
for its own AST helpers).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tests.architecture._utils import scan_imports
from tests.architecture.test_advisory_lock_session_commit_enforcement import (
    _file_imports_session_lock_helper,
    _scan_file,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, source: str, name: str = "sample.py") -> Path:
    """Write a dedented source sample to tmp_path and return its Path."""
    py_file = tmp_path / name
    py_file.write_text(textwrap.dedent(source), encoding="utf-8")
    return py_file


# ---------------------------------------------------------------------------
# _file_imports_session_lock_helper
# ---------------------------------------------------------------------------


class TestFileImportsSessionLockHelper:
    def test_true_for_canonical_module_import(self, tmp_path: Path) -> None:
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock
            """,
        )
        assert _file_imports_session_lock_helper(scan_imports(py_file)) is True

    def test_true_for_reexport_module_import(self, tmp_path: Path) -> None:
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg import pg_advisory_lock
            """,
        )
        assert _file_imports_session_lock_helper(scan_imports(py_file)) is True

    def test_false_when_not_imported(self, tmp_path: Path) -> None:
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import advisory_lock_id
            """,
        )
        assert _file_imports_session_lock_helper(scan_imports(py_file)) is False

    def test_false_for_unrelated_module_same_name(self, tmp_path: Path) -> None:
        """A local/unrelated function named `pg_advisory_lock` is NOT in scope.

        Guards against false-positive matches on a same-named helper that has
        nothing to do with the real session-level advisory lock.
        """
        py_file = _write(
            tmp_path,
            """\
            from some_other_module import pg_advisory_lock
            """,
        )
        assert _file_imports_session_lock_helper(scan_imports(py_file)) is False


# ---------------------------------------------------------------------------
# _scan_file — positive cases (the exact anti-pattern)
# ---------------------------------------------------------------------------


class TestScanFileDetectsMidBlockCommit:
    def test_direct_commit_in_with_body(self, tmp_path: Path) -> None:
        """The base case: commit() called directly inside the lock block."""
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            async def run(write_factory, name):
                async with (
                    write_factory() as session,
                    pg_advisory_lock(session, name) as acquired,
                ):
                    await do_write(session)
                    await session.commit()
            """,
        )
        violations = _scan_file(py_file)
        assert len(violations) == 1
        assert violations[0].session_root == "session"
        assert violations[0].commit_line == 9

    def test_commit_nested_in_if_branch(self, tmp_path: Path) -> None:
        """Real worker.py shape: commit() inside an `if not acquired:` branch."""
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            async def run(write_factory, name):
                async with (
                    write_factory() as session,
                    pg_advisory_lock(session, name) as acquired,
                ):
                    if not acquired:
                        await task_repo.update_status(task.id, "RETRY")
                        await session.commit()
                        return
            """,
        )
        violations = _scan_file(py_file)
        assert len(violations) == 1

    def test_commit_nested_in_try_except(self, tmp_path: Path) -> None:
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            async def run(write_factory, name):
                async with (
                    write_factory() as session,
                    pg_advisory_lock(session, name) as acquired,
                ):
                    try:
                        await do_write(session)
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise
            """,
        )
        violations = _scan_file(py_file)
        assert len(violations) == 1

    def test_attribute_session_matched(self, tmp_path: Path) -> None:
        """`self.session` (Attribute) resolves to root `session`, same as a bare Name."""
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            class Worker:
                async def run(self, name):
                    async with pg_advisory_lock(self.session, name) as acquired:
                        await self.session.commit()
            """,
        )
        violations = _scan_file(py_file)
        assert len(violations) == 1

    def test_multiple_lock_blocks_both_flagged(self, tmp_path: Path) -> None:
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            async def run_a(write_factory, name):
                async with write_factory() as session, pg_advisory_lock(session, name) as acquired:
                    await session.commit()

            async def run_b(write_factory, name):
                async with write_factory() as session, pg_advisory_lock(session, name) as acquired:
                    await session.commit()
            """,
        )
        violations = _scan_file(py_file)
        assert len(violations) == 2


# ---------------------------------------------------------------------------
# _scan_file — negative cases (must NOT be flagged)
# ---------------------------------------------------------------------------


class TestScanFileIgnoresSafePatterns:
    def test_no_import_means_no_scan(self, tmp_path: Path) -> None:
        """Without the recognised import, even a literal commit-in-block is ignored.

        This is the cheap short-circuit guard: a local function also named
        `pg_advisory_lock` (unrelated to the real helper) must never trigger
        a false positive.
        """
        py_file = _write(
            tmp_path,
            """\
            def pg_advisory_lock(session, name):
                ...

            async def run(write_factory, name):
                async with write_factory() as session, pg_advisory_lock(session, name) as acquired:
                    await session.commit()
            """,
        )
        assert _scan_file(py_file) == []

    def test_commit_via_helper_function_not_caught(self, tmp_path: Path) -> None:
        """Cross-function commit (execute_task.py's real shape) is a documented
        false negative — this AST pass does not do call-graph analysis.
        """
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            async def run(write_factory, name):
                async with (
                    write_factory() as session,
                    pg_advisory_lock(session, name) as acquired,
                ):
                    return await _write_results_under_lock(session, acquired)

            async def _write_results_under_lock(session, acquired):
                await session.commit()
            """,
        )
        assert _scan_file(py_file) == []

    def test_commit_on_different_session_object_not_caught(self, tmp_path: Path) -> None:
        """A DIFFERENT session (e.g. a nested `_uow()` enqueue session) committing
        inside the block must not be flagged — it is not the locked session.
        Matches the real market-ingestion backfill scripts' `enqueue_uow.commit()`.
        """
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            async def run(write_factory, uow_factory, name):
                async with write_factory() as lock_session, pg_advisory_lock(lock_session, name) as acquired:
                    async with uow_factory() as enqueue_uow:
                        await do_enqueue(enqueue_uow)
                        await enqueue_uow.commit()
            """,
        )
        assert _scan_file(py_file) == []

    def test_commit_passed_by_reference_not_a_call(self, tmp_path: Path) -> None:
        """`commit_fn=session.commit` is an attribute access, not a Call node —
        must not be mistaken for an actual commit invocation.
        """
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            async def run(write_factory, name):
                async with write_factory() as session, pg_advisory_lock(session, name) as acquired:
                    use_case = UseCase(commit_fn=session.commit, rollback_fn=session.rollback)
                    await use_case.execute()
            """,
        )
        assert _scan_file(py_file) == []

    def test_shadowed_session_name_in_nested_with_not_caught(self, tmp_path: Path) -> None:
        """A nested `with ... as session:` that REBINDS the same name to a new
        object must be treated as opaque — its commit() is on a DIFFERENT
        object even though the identifier is spelled the same.
        """
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            async def run(write_factory, other_factory, name):
                async with write_factory() as session, pg_advisory_lock(session, name) as acquired:
                    async with other_factory() as session:
                        await session.commit()
            """,
        )
        assert _scan_file(py_file) == []

    def test_xact_lock_helper_out_of_scope(self, tmp_path: Path) -> None:
        """`pg_advisory_xact_lock` (transaction-scoped, safe) is a DIFFERENT name
        and must never be matched by this session-level-only rule.
        """
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_xact_lock

            async def run(write_factory, name):
                async with write_factory() as session, pg_advisory_xact_lock(session, name) as acquired:
                    await do_write(session)
                    await session.commit()
            """,
        )
        assert _scan_file(py_file) == []

    def test_no_commit_at_all_is_clean(self, tmp_path: Path) -> None:
        py_file = _write(
            tmp_path,
            """\
            from messaging.pg.advisory_lock import pg_advisory_lock

            async def run(write_factory, name):
                async with write_factory() as session, pg_advisory_lock(session, name) as acquired:
                    if acquired:
                        await do_write(session)
            """,
        )
        assert _scan_file(py_file) == []

    def test_syntax_error_file_returns_empty(self, tmp_path: Path) -> None:
        py_file = _write(tmp_path, "def broken(:\n    pass\n")
        assert _scan_file(py_file) == []

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        assert _scan_file(tmp_path / "missing.py") == []


# ---------------------------------------------------------------------------
# _load_allowlist
# ---------------------------------------------------------------------------


class TestLoadAllowlist:
    def test_missing_file_returns_empty_set(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import tests.architecture.test_advisory_lock_session_commit_enforcement as mod

        monkeypatch.setattr(mod, "_ALLOWLIST_PATH", tmp_path / "does_not_exist.yaml")
        assert mod._load_allowlist() == set()

    def test_valid_entry_parsed(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import tests.architecture.test_advisory_lock_session_commit_enforcement as mod

        allowlist_path = tmp_path / "allowlist.yaml"
        allowlist_path.write_text(
            textwrap.dedent("""\
                allowlist:
                  - file_path: services/example/src/example/scripts/backfill.py
                    line: 42
                    justification: "Uses a dedicated pinned connection across the whole block."
                    granted_at: "2026-07-25"
            """),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_ALLOWLIST_PATH", allowlist_path)
        allowed = mod._load_allowlist()
        assert allowed == {("services/example/src/example/scripts/backfill.py", 42)}

    def test_entry_missing_required_field_raises(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import pytest

        import tests.architecture.test_advisory_lock_session_commit_enforcement as mod

        allowlist_path = tmp_path / "allowlist.yaml"
        allowlist_path.write_text(
            textwrap.dedent("""\
                allowlist:
                  - file_path: services/example/src/example/scripts/backfill.py
                    line: 42
                    # missing justification and granted_at
            """),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_ALLOWLIST_PATH", allowlist_path)
        with pytest.raises(ValueError, match="missing required fields"):
            mod._load_allowlist()

    def test_empty_allowlist_key_returns_empty_set(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import tests.architecture.test_advisory_lock_session_commit_enforcement as mod

        allowlist_path = tmp_path / "allowlist.yaml"
        allowlist_path.write_text("allowlist: []\n", encoding="utf-8")
        monkeypatch.setattr(mod, "_ALLOWLIST_PATH", allowlist_path)
        assert mod._load_allowlist() == set()
