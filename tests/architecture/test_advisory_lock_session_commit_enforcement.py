"""
Architecture test: no ``session.commit()`` inside a session-level
``pg_advisory_lock(...)`` critical section.

Rule: ADVISORY-LOCK-COMMIT-001

Rationale
---------
``libs/messaging/src/messaging/pg/advisory_lock.py`` exposes
``pg_advisory_lock`` — a *session-level* advisory lock taken with
``pg_try_advisory_lock`` and released with ``pg_advisory_unlock`` in the
context manager's ``finally`` clause, on the SAME ``AsyncSession`` object it
was acquired on.

A 2026-07-23/24 investigation found that every existing caller of this
helper (``content-ingestion``'s ``execute_task.py`` / ``worker.py`` and
``market-ingestion``'s backfill scripts) calls ``await session.commit()`` one
or more times *inside* the ``async with pg_advisory_lock(session, ...)``
block, on that same ``session``. This voids the lock's own mutual-exclusion
guarantee two different ways depending on deployment topology:

1. **SQLAlchemy pooled connections**: committing does not itself release the
   underlying physical connection, but if the pool later hands that
   connection back and forward to a different session (e.g. after the
   ``async with`` block's outer session-factory context manager returns and
   checks the connection back in, or under connection-pool churn during a
   long-running critical section), the eventual ``pg_advisory_unlock`` call
   in ``pg_advisory_lock``'s ``finally`` clause is not guaranteed to run on
   the SAME physical backend that took the lock — an advisory lock is
   per-*backend-process*, not per-session-object, so unlocking on the wrong
   backend either fails silently (nothing to unlock) or unlocks nothing
   while the original backend holds the lock until it disconnects.
2. **PgBouncer transaction-mode pooling**: PgBouncer releases a server
   connection back to its pool at the next transaction boundary — i.e. at
   ``COMMIT`` — and runs ``DISCARD ALL`` (or an equivalent reset) on it,
   which drops session-level advisory locks immediately. A mid-block
   ``session.commit()`` therefore releases the lock EARLY, right after the
   first commit, while the rest of the "critical section" still executes
   unprotected — the exact opposite of what the caller believes is
   happening.

Both failure modes have the identical *shape*: the session-level lock helper
is used as if it were transaction-scoped, but at least one ``commit()`` call
happens on the locked session before the ``with`` block exits. The safe
alternatives going forward are ``pg_advisory_xact_lock`` (auto-released at
the enclosing transaction's commit/rollback — safe for a single-commit
critical section) or a dedicated pinned connection that is never returned to
the pool until after the explicit unlock (for a genuinely multi-commit
critical section). Nothing currently stops a NEW caller from reintroducing
the session-level-lock-plus-mid-block-commit shape.

Design choice: AST heuristic scope
-----------------------------------
This test flags a ``with``/``async with`` statement that:

1. Has an item whose context expression is a call to ``pg_advisory_lock``
   (matched by bare name OR attribute access, e.g. ``pg.pg_advisory_lock``),
   AND the file actually imports that name from
   ``messaging.pg.advisory_lock`` or its re-export ``messaging.pg`` (this
   avoids false-flagging an unrelated local function that happens to share
   the name); AND
2. Contains, directly in that ``with`` block's body — recursing through
   ``if``/``try``/``for``/``while``/nested ``with`` statements, but NEVER
   descending into a nested ``def``/``async def``/``lambda``/``class`` body,
   and NEVER descending into a nested ``with`` that REBINDS the same session
   name to a new object — a call shaped ``<session>.commit(...)`` where
   ``<session>`` is the exact same root identifier passed as the locked
   session to ``pg_advisory_lock``.

This intentionally does NOT try to prove a commit happened via a helper
function called from inside the block (e.g. ``execute_task.py``'s
``_write_results_under_lock`` commits on the caller's behalf, several stack
frames down) — that would require call-graph / interprocedural analysis this
AST pass cannot do reliably, and the task's own guidance is explicit that
false negatives here are acceptable while false positives are NOT (a noisy
check gets suppressed, which is worse than no check). The identifier-root
match (rather than "ANY ``.commit()`` anywhere in the block") is what makes
this test trustworthy: it correctly ignores commits on unrelated objects
(e.g. ``enqueue_uow.commit()`` in the market-ingestion backfill scripts,
which use a SEPARATE session from a nested ``_uow()`` context manager) and
commits that are merely passed BY REFERENCE (``commit_fn=session.commit``,
which is an attribute access, not a call).

Allowlist
---------
A call site that intentionally still commits mid-block despite genuinely
being safe (e.g. it has been rewritten to hold a dedicated, never-pooled
connection across the whole critical section) may be exempted via
``tests/architecture/_advisory_lock_session_commit_allowlist.yaml``, keyed by
(file_path, line) — the exact source line of the ``pg_advisory_lock(...)``
call — so an exemption for one lock call site never silently covers a
different one added later in the same file.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from tests.architecture._utils import (
    REPO_ROOT,
    ArchViolation,
    ImportRecord,
    assert_no_violations,
    discover_services,
    iter_py_files,
    scan_imports,
)

_ALLOWLIST_PATH = Path(__file__).resolve().parent / "_advisory_lock_session_commit_allowlist.yaml"

# The session-level lock helper this rule targets. Deliberately NOT
# ``pg_advisory_xact_lock`` (transaction-scoped — safe for single-commit
# critical sections) or any other name — only the session-level variant can
# exhibit this bug shape.
_SESSION_LOCK_NAME = "pg_advisory_lock"

# Modules a file must import ``pg_advisory_lock`` FROM for a call site to
# count. ``messaging.pg`` is the lazy re-export in
# ``libs/messaging/src/messaging/pg/__init__.py``; ``messaging.pg.advisory_lock``
# is the canonical definition module. Any other module defining a same-named
# function is out of scope (avoids false positives on an unrelated helper).
_SESSION_LOCK_MODULES = frozenset({"messaging.pg.advisory_lock", "messaging.pg"})


# ---------------------------------------------------------------------------
# Allowlist loading
# ---------------------------------------------------------------------------


def _load_allowlist() -> set[tuple[str, int]]:
    """Return the set of (file_path, line) pairs exempted from the rule.

    Missing or malformed entries are treated as violations (fail loudly) —
    same policy as ``_dedup_prelookup_allowlist.yaml`` / ``_consumer_dedup_allowlist.yaml``.
    """
    if not _ALLOWLIST_PATH.exists():
        return set()
    data = yaml.safe_load(_ALLOWLIST_PATH.read_text(encoding="utf-8")) or {}
    entries = data.get("allowlist") or []
    allowed: set[tuple[str, int]] = set()
    required_fields = {"file_path", "line", "justification", "granted_at"}
    for entry in entries:
        missing = required_fields - set(entry)
        if missing:
            raise ValueError(f"Allowlist entry is missing required fields {missing}: {entry!r}")
        allowed.add((entry["file_path"], int(entry["line"])))
    return allowed


# ---------------------------------------------------------------------------
# AST scanning
# ---------------------------------------------------------------------------


def _attr_root_name(node: ast.expr) -> str | None:
    """Return the trailing identifier of a Name or Attribute expression.

    For ``lock_session`` (a bare ``Name``) this returns ``'lock_session'``;
    for ``self.session`` (``Attribute(value=Name('self'), attr='session')``)
    it returns ``'session'``. Used so the "same session" match works whether
    the session is a bare local variable or an attribute access, without any
    runtime type information — AST-level only, matching the sibling
    ``test_dedup_prelookup_enforcement.py``'s ``_attr_root_name`` helper.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _file_imports_session_lock_helper(imports: list[ImportRecord]) -> bool:
    """True if the file imports ``pg_advisory_lock`` from a recognised module."""
    for rec in imports:
        if rec.is_from and rec.module in _SESSION_LOCK_MODULES and _SESSION_LOCK_NAME in rec.names:
            return True
    return False


def _session_root_from_lock_call(call: ast.Call) -> str | None:
    """Extract the locked-session identifier from a ``pg_advisory_lock(...)`` call.

    Supports both the positional-first-arg spelling
    (``pg_advisory_lock(session, name)``) and the keyword spelling
    (``pg_advisory_lock(session=session, name=...)``). Returns ``None`` (no
    match — conservative, avoids a false positive) if the session argument is
    a more complex expression this heuristic cannot resolve to a stable root
    identifier (e.g. a function call or subscript).
    """
    if call.args:
        return _attr_root_name(call.args[0])
    for kw in call.keywords:
        if kw.arg == "session":
            return _attr_root_name(kw.value)
    return None


def _is_session_lock_call(node: ast.expr) -> bool:
    """True if ``node`` is a call to ``pg_advisory_lock`` (name or attribute form)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == _SESSION_LOCK_NAME
    if isinstance(func, ast.Attribute):
        return func.attr == _SESSION_LOCK_NAME
    return False


class _ScopedCommitScanner(ast.NodeVisitor):
    """Find a ``<session_root>.commit(...)`` call within a bounded scope.

    Recurses through ordinary control-flow statements (``if``, ``try``,
    ``for``, ``while``, nested ``with``) so a commit nested inside e.g. an
    ``if not acquired:`` branch is still caught (this is the exact shape of
    the real ``worker.py`` violations found in the 2026-07-23/24
    investigation). Never descends into a nested ``def``/``async
    def``/``lambda``/``class`` body — a commit inside a helper function
    called from the block is a DIFFERENT (cross-function) case this AST pass
    intentionally does not attempt to prove, per the module docstring.

    Also treats a nested ``with``/``async with`` that REBINDS the same
    session name to a NEW object as opaque and does not descend into it —
    without this guard, a common variable name like ``session`` reused for
    an unrelated nested session would produce a false positive.
    """

    def __init__(self, session_root: str) -> None:
        self.session_root = session_root
        self.commit_line: int | None = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return  # do not descend

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return  # do not descend

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return  # do not descend

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return  # do not descend

    def _rebinds_session_root(self, node: ast.With | ast.AsyncWith) -> bool:
        for item in node.items:
            target = item.optional_vars
            if isinstance(target, ast.Name) and target.id == self.session_root:
                return True
        return False

    def visit_With(self, node: ast.With) -> None:
        if self._rebinds_session_root(node):
            return  # shadowed — opaque, do not descend (avoid false positive)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        if self._rebinds_session_root(node):
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self.commit_line is None and isinstance(node.func, ast.Attribute) and node.func.attr == "commit":
            root = _attr_root_name(node.func.value)
            if root == self.session_root:
                self.commit_line = node.lineno
        self.generic_visit(node)


@dataclass
class _LockCommitViolation:
    file: Path
    lock_line: int
    commit_line: int
    session_root: str


def _find_violations_in_tree(tree: ast.AST, imports: list[ImportRecord]) -> list[tuple[int, int, str]]:
    """Return ``(lock_line, commit_line, session_root)`` for every violating with-block.

    Only inspects files that actually import ``pg_advisory_lock`` from a
    recognised module (see ``_file_imports_session_lock_helper``) — cheap
    short-circuit and a false-positive guard against unrelated same-named
    helpers.
    """
    if not _file_imports_session_lock_helper(imports):
        return []

    results: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With | ast.AsyncWith):
            continue

        session_root: str | None = None
        lock_line: int | None = None
        for item in node.items:
            if _is_session_lock_call(item.context_expr):
                assert isinstance(item.context_expr, ast.Call)
                session_root = _session_root_from_lock_call(item.context_expr)
                lock_line = item.context_expr.lineno
                break
        if session_root is None or lock_line is None:
            continue

        scanner = _ScopedCommitScanner(session_root)
        for stmt in node.body:
            scanner.visit(stmt)
            if scanner.commit_line is not None:
                break

        if scanner.commit_line is not None:
            results.append((lock_line, scanner.commit_line, session_root))

    return results


def _scan_file(py_file: Path) -> list[_LockCommitViolation]:
    """Parse ``py_file`` and return every session-lock-plus-mid-block-commit violation."""
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, OSError):
        return []

    imports = scan_imports(py_file)
    return [
        _LockCommitViolation(file=py_file, lock_line=lock_line, commit_line=commit_line, session_root=root)
        for lock_line, commit_line, root in _find_violations_in_tree(tree, imports)
    ]


# ---------------------------------------------------------------------------
# Architecture test
# ---------------------------------------------------------------------------


class TestAdvisoryLockSessionCommitEnforcement:
    """No ``<session>.commit()`` inside a ``pg_advisory_lock(<session>, ...)`` block.

    Discovery strategy: AST-scan every ``.py`` file under each service's
    ``src/<pkg>/`` tree (not just ``infrastructure/`` — known call sites also
    live in ``application/use_cases/`` and ``scripts/``) for the pattern
    described in the module docstring.

    Compliance check: the (file, lock-call line) pair must not appear in
    ``_advisory_lock_session_commit_allowlist.yaml``.
    """

    def test_no_commit_inside_session_advisory_lock_block(self) -> None:
        """See module docstring for the bug shape this guards (ADVISORY-LOCK-COMMIT-001).

        Allowlist path: tests/architecture/_advisory_lock_session_commit_allowlist.yaml
        """
        allowed = _load_allowlist()
        violations: list[ArchViolation] = []

        for svc in discover_services(include_scaffolded=True):
            if not svc.pkg_dir.is_dir():
                continue

            for py_file in iter_py_files(svc.pkg_dir):
                for site in _scan_file(py_file):
                    rel_path = site.file.relative_to(REPO_ROOT).as_posix()
                    if (rel_path, site.lock_line) in allowed:
                        continue

                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=f"{rel_path}:{site.lock_line}",
                            line=site.lock_line,
                            rule="ADVISORY-LOCK-COMMIT-001",
                            detail=(
                                f"`pg_advisory_lock({site.session_root}, ...)` at line "
                                f"{site.lock_line} has `{site.session_root}.commit()` at line "
                                f"{site.commit_line} inside its critical section. A session-level "
                                "advisory lock does not survive a mid-block commit under pooled "
                                "connections (SQLAlchemy pool churn) or PgBouncer transaction-mode "
                                "pooling (DISCARD ALL on COMMIT releases it early) — either use "
                                "`pg_advisory_xact_lock` for a single-commit critical section, or a "
                                "dedicated pinned connection that is never returned to the pool "
                                "until after the explicit unlock for a multi-commit one. If this "
                                "call site is provably safe, add an allowlist entry with "
                                "justification in "
                                "tests/architecture/_advisory_lock_session_commit_allowlist.yaml."
                            ),
                        )
                    )

        assert_no_violations(violations, rule="ADVISORY-LOCK-COMMIT-001")
