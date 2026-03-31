"""
Architecture test: process topology conventions (R22, STANDARDS.md §14).

Verifies that all services comply with the canonical background-process topology:

1. Entry point conventions — every *_main.py exists for each class file (T-A-2-01)
2. No background-task embedding in app.py lifespan (T-A-2-02, R22)
3. Directory naming conventions — singular scheduler/, plural workers/, etc. (T-A-2-03)
4. Baseline integrity — TOPOLOGY_BASELINE is well-formed (T-A-2-04)

Uses TOPOLOGY_BASELINE to allow known violations in services undergoing
migration (Sub-Plans B and C). Each baseline entry includes the fix wave.
Baselined violations are printed as warnings; un-baselined violations fail
the test. When a baseline entry has no matching violation it emits a
UserWarning (stale entry that should be removed once the fix lands).

Per RULES.md R22, docs/STANDARDS.md §1.1 and §14.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

from tests.architecture._utils import (
    REPO_ROOT,
    ArchViolation,
    ProcessType,
    assert_no_violations,
    discover_process_entry_points,
    discover_services,
    has_background_tasks_in_lifespan,
    scan_imports,
)

# ---------------------------------------------------------------------------
# Baseline — known violations awaiting migration
# ---------------------------------------------------------------------------
# Key: (service_name, rule_id)  →  reason / planned fix wave.
#
# Rule IDs used in this module:
#   TOPO-MAIN-DISPATCHER   — class file exists but dispatcher_main.py missing
#   TOPO-MAIN-CONSUMER     — class file exists but *_consumer_main.py missing
#   TOPO-MAIN-SCHEDULER    — class file exists but scheduler_main.py missing
#   TOPO-MAIN-WORKER       — class file exists but worker_main.py missing
#   TOPO-MAIN-GUARD        — *_main.py lacks `if __name__ == '__main__':` guard
#   TOPO-SIGNAL            — *_main.py does not import the `signal` module
#   TOPO-LIFESPAN          — asyncio.create_task() found inside app.py lifespan
#   TOPO-LIFESPAN-BLOCKING — await X.run() called directly inside app.py lifespan
#   TOPO-DIR-SCHEDULER     — infrastructure/schedulers/ (plural) should be scheduler/
#   TOPO-DIR-WORKER        — infrastructure/worker/ (singular) should be workers/
#   TOPO-DIR-CONSUMER      — infrastructure/consumer/ outside messaging/consumers/
#   TOPO-DIR-OUTBOX        — infrastructure/outbox/ outside messaging/outbox/
#   TOPO-STALE-OUTBOX      — infrastructure/outbox/ co-exists with messaging/outbox/ (stale)

TOPOLOGY_BASELINE: dict[tuple[str, str], str] = {
    # --- S3: market-data — consumers extracted (Wave B-2); lifespan cleanup deferred ---
    # TOPO-LIFESPAN: consumers still embedded pending compose containers for standalone processes.
    (
        "market-data",
        "TOPO-LIFESPAN",
    ): "Remove create_task calls once consumer containers are added to compose (PLAN-0011 post-B-2)",
    # --- S7: knowledge-graph — fix in PLAN-0011 Wave C-3 ---
    # Note: TOPO-MAIN-DISPATCHER not needed (same reason as content-store above).
    ("knowledge-graph", "TOPO-MAIN-CONSUMER"): "Create consumer_main.py files in Wave C-3",
    ("knowledge-graph", "TOPO-MAIN-SCHEDULER"): "Create scheduler_main.py in Wave C-3",
    ("knowledge-graph", "TOPO-LIFESPAN"): "Remove background tasks from lifespan in Wave C-3",
    ("knowledge-graph", "TOPO-DIR-OUTBOX"): "Move outbox to messaging/outbox/ in Wave C-3",
    ("knowledge-graph", "TOPO-DIR-CONSUMER"): "Move consumer to messaging/consumers/ in Wave C-3",
}

# All rule IDs this module uses — used for baseline integrity checks.
_KNOWN_RULE_IDS: frozenset[str] = frozenset(
    {
        "TOPO-MAIN-DISPATCHER",
        "TOPO-MAIN-CONSUMER",
        "TOPO-MAIN-SCHEDULER",
        "TOPO-MAIN-WORKER",
        "TOPO-MAIN-GUARD",
        "TOPO-SIGNAL",
        "TOPO-LIFESPAN",
        "TOPO-LIFESPAN-BLOCKING",
        "TOPO-DIR-SCHEDULER",
        "TOPO-DIR-WORKER",
        "TOPO-DIR-CONSUMER",
        "TOPO-DIR-OUTBOX",
        "TOPO-STALE-OUTBOX",
    }
)


# ---------------------------------------------------------------------------
# Baseline helper
# ---------------------------------------------------------------------------


def _filter_violations(
    violations: list[ArchViolation],
    rule_id: str,
) -> list[ArchViolation]:
    """Separate violations into real failures and baselined warnings.

    Baselined violations are printed to stdout (visible in ``pytest -v``).
    Baseline entries with no matching violation emit a ``UserWarning``
    (the violation was fixed; the entry should be removed from the baseline).
    """
    real: list[ArchViolation] = []
    violated_services: set[str] = set()

    for v in violations:
        key = (v.service, rule_id)
        if key in TOPOLOGY_BASELINE:
            violated_services.add(v.service)
            print(f"\n  [TOPOLOGY BASELINE] [{rule_id}] {v.service}: {v.detail}\n    → {TOPOLOGY_BASELINE[key]}")
        else:
            real.append(v)

    # Warn about stale entries (violation no longer detected for this rule).
    for (svc_name, base_rule), reason in TOPOLOGY_BASELINE.items():
        if base_rule != rule_id:
            continue
        if svc_name not in violated_services:
            warnings.warn(
                f"Stale TOPOLOGY_BASELINE entry ({svc_name!r}, {rule_id!r}) — "
                f"violation no longer found; remove this entry. Planned fix: {reason}",
                UserWarning,
                stacklevel=3,
            )

    return real


# ---------------------------------------------------------------------------
# AST scanner: await X.run() inside lifespan (blocking-run anti-pattern)
# ---------------------------------------------------------------------------


class _AwaitRunInLifespanScanner(ast.NodeVisitor):
    """Detect ``await X.run(...)`` calls directly inside lifespan functions.

    This catches the anti-pattern of calling a long-running process
    synchronously in lifespan, which blocks the event loop until exit.

    Does NOT flag ``asyncio.create_task(X.run())``; there the outer
    ``await`` wraps ``create_task``, not ``.run()``, and is covered by
    ``has_background_tasks_in_lifespan``.
    """

    _LIFESPAN_NAMES = frozenset({"lifespan", "_lifespan", "startup"})

    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []
        self._in_lifespan: bool = False

    @staticmethod
    def _has_asynccontextmanager(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "asynccontextmanager":
                return True
            if isinstance(dec, ast.Attribute) and dec.attr == "asynccontextmanager":
                return True
        return False

    def _visit_function(self, node: ast.AsyncFunctionDef | ast.FunctionDef) -> None:
        is_lifespan = node.name in self._LIFESPAN_NAMES or self._has_asynccontextmanager(node)
        old = self._in_lifespan
        if is_lifespan:
            self._in_lifespan = True
        self.generic_visit(node)
        self._in_lifespan = old

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_Await(self, node: ast.Await) -> None:
        if self._in_lifespan:
            value = node.value
            if isinstance(value, ast.Call):
                func = value.func
                if isinstance(func, ast.Attribute) and func.attr == "run":
                    obj_name = ""
                    if isinstance(func.value, ast.Name):
                        obj_name = func.value.id
                    elif isinstance(func.value, ast.Attribute):
                        obj_name = func.value.attr
                    self.violations.append((node.lineno, f"await {obj_name}.run(...)"))
        self.generic_visit(node)


def _has_blocking_run_in_lifespan(app_py: Path) -> list[tuple[int, str]]:
    """Return ``(line, description)`` for every ``await X.run()`` in lifespan."""
    try:
        source = app_py.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(app_py))
    except (SyntaxError, OSError):
        return []
    scanner = _AwaitRunInLifespanScanner()
    scanner.visit(tree)
    return scanner.violations


# ---------------------------------------------------------------------------
# TestEntryPointConventions (T-A-2-01)
# ---------------------------------------------------------------------------


class TestEntryPointConventions:
    """Every background process class file must have a sibling *_main.py entry point."""

    def test_dispatcher_has_main_entry_point(self) -> None:
        """Every service with dispatcher.py must have a dispatcher_main.py sibling."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            for ep in discover_process_entry_points(svc):
                if ep.process_type != ProcessType.DISPATCHER:
                    continue
                if ep.missing_main:
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=str(ep.dir_path.relative_to(REPO_ROOT)),
                            line=0,
                            rule="TOPO-MAIN-DISPATCHER",
                            detail=(
                                f"dispatcher.py found at …/{ep.dir_path.name}/ "
                                "but dispatcher_main.py is missing. "
                                "Add a standalone entry point (STANDARDS.md §14)."
                            ),
                        )
                    )
        real = _filter_violations(violations, "TOPO-MAIN-DISPATCHER")
        assert_no_violations(real, rule="TOPO-MAIN-DISPATCHER")

    def test_consumer_has_main_entry_point(self) -> None:
        """Every *_consumer.py class file must have a sibling *_consumer_main.py."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            for ep in discover_process_entry_points(svc):
                if ep.process_type != ProcessType.CONSUMER:
                    continue
                if ep.missing_main:
                    class_name = ep.class_file.name if ep.class_file else "unknown"
                    main_name = class_name.replace(".py", "_main.py")
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=str(ep.dir_path.relative_to(REPO_ROOT)),
                            line=0,
                            rule="TOPO-MAIN-CONSUMER",
                            detail=(
                                f"{class_name} found at …/{ep.dir_path.name}/ "
                                f"but {main_name} is missing. "
                                "Add a standalone entry point (STANDARDS.md §14)."
                            ),
                        )
                    )
        real = _filter_violations(violations, "TOPO-MAIN-CONSUMER")
        assert_no_violations(real, rule="TOPO-MAIN-CONSUMER")

    def test_scheduler_has_main_entry_point(self) -> None:
        """Every service with a scheduler class must have scheduler_main.py."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            for ep in discover_process_entry_points(svc):
                if ep.process_type != ProcessType.SCHEDULER:
                    continue
                if ep.missing_main:
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=str(ep.dir_path.relative_to(REPO_ROOT)),
                            line=0,
                            rule="TOPO-MAIN-SCHEDULER",
                            detail=(
                                f"Scheduler class found at …/{ep.dir_path.name}/ "
                                "but scheduler_main.py is missing. "
                                "Add a standalone entry point (STANDARDS.md §14)."
                            ),
                        )
                    )
        real = _filter_violations(violations, "TOPO-MAIN-SCHEDULER")
        assert_no_violations(real, rule="TOPO-MAIN-SCHEDULER")

    def test_worker_has_main_entry_point(self) -> None:
        """Every service with worker.py must have a worker_main.py sibling."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            for ep in discover_process_entry_points(svc):
                if ep.process_type != ProcessType.WORKER:
                    continue
                if ep.missing_main:
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=str(ep.dir_path.relative_to(REPO_ROOT)),
                            line=0,
                            rule="TOPO-MAIN-WORKER",
                            detail=(
                                f"worker.py found at …/{ep.dir_path.name}/ "
                                "but worker_main.py is missing. "
                                "Add a standalone entry point (STANDARDS.md §14)."
                            ),
                        )
                    )
        real = _filter_violations(violations, "TOPO-MAIN-WORKER")
        assert_no_violations(real, rule="TOPO-MAIN-WORKER")

    def test_entry_points_have_main_guard(self) -> None:
        """Every *_main.py file must contain an ``if __name__ == '__main__':`` block."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            for ep in discover_process_entry_points(svc):
                if ep.main_file is None:
                    continue
                try:
                    source = ep.main_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                has_guard = '__name__ == "__main__"' in source or "__name__ == '__main__'" in source
                if not has_guard:
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=str(ep.main_file.relative_to(REPO_ROOT)),
                            line=0,
                            rule="TOPO-MAIN-GUARD",
                            detail=(
                                f"{ep.main_file.name} is missing "
                                "`if __name__ == '__main__':` block. "
                                "Entry point files must be executable as scripts."
                            ),
                        )
                    )
        # No baseline — every existing *_main.py already has the guard.
        assert_no_violations(violations, rule="TOPO-MAIN-GUARD")

    def test_entry_points_have_signal_handling(self) -> None:
        """Every *_main.py file must import the ``signal`` module (R22 §14.5)."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            for ep in discover_process_entry_points(svc):
                if ep.main_file is None:
                    continue
                imports = scan_imports(ep.main_file)
                has_signal = any(imp.module == "signal" or "signal" in imp.names for imp in imports)
                if not has_signal:
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=str(ep.main_file.relative_to(REPO_ROOT)),
                            line=0,
                            rule="TOPO-SIGNAL",
                            detail=(
                                f"{ep.main_file.name} does not import `signal`. "
                                "Entry points must handle SIGTERM/SIGINT for graceful "
                                "shutdown (R22 §14.5)."
                            ),
                        )
                    )
        # No baseline — every existing *_main.py already imports signal.
        assert_no_violations(violations, rule="TOPO-SIGNAL")


# ---------------------------------------------------------------------------
# TestNoLifespanEmbedding (T-A-2-02)
# ---------------------------------------------------------------------------


class TestNoLifespanEmbedding:
    """app.py must not start background processing loops inside lifespan (R22)."""

    def test_app_lifespan_has_no_background_tasks(self) -> None:
        """No asyncio.create_task() calls must appear inside app.py lifespan."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            app_py = svc.pkg_dir / "app.py"
            if not app_py.exists():
                continue
            hits = has_background_tasks_in_lifespan(app_py)
            if hits:
                first_line, _first_desc = hits[0]
                extra = f" (+{len(hits) - 3} more)" if len(hits) > 3 else ""
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=f"services/{svc.name}/src/{svc.pkg_name}/app.py",
                        line=first_line,
                        rule="TOPO-LIFESPAN",
                        detail=(
                            f"app.py lifespan embeds {len(hits)} background task(s): "
                            + ", ".join(d for _, d in hits[:3])
                            + extra
                            + ". Background processes must run as standalone entry "
                            "points, not in-process tasks (R22)."
                        ),
                    )
                )
        real = _filter_violations(violations, "TOPO-LIFESPAN")
        assert_no_violations(real, rule="TOPO-LIFESPAN")

    def test_app_lifespan_no_blocking_run_call(self) -> None:
        """app.py must not call ``await X.run()`` directly inside lifespan.

        A direct ``await dispatcher.run()`` (or similar) blocks the event loop
        for the lifetime of the process.  Use ``asyncio.create_task(X.run())``
        instead — or, better, a standalone entry point (R22).
        """
        violations: list[ArchViolation] = []
        for svc in discover_services():
            app_py = svc.pkg_dir / "app.py"
            if not app_py.exists():
                continue
            hits = _has_blocking_run_in_lifespan(app_py)
            if hits:
                first_line, first_desc = hits[0]
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=f"services/{svc.name}/src/{svc.pkg_name}/app.py",
                        line=first_line,
                        rule="TOPO-LIFESPAN-BLOCKING",
                        detail=(
                            f"app.py lifespan calls {first_desc} directly — "
                            "this blocks the event loop until the process exits. "
                            "Use asyncio.create_task() or a standalone entry point (R22)."
                        ),
                    )
                )
        # No baseline needed — no service currently has this anti-pattern.
        assert_no_violations(violations, rule="TOPO-LIFESPAN-BLOCKING")


# ---------------------------------------------------------------------------
# TestDirectoryNamingConventions (T-A-2-03)
# ---------------------------------------------------------------------------


class TestDirectoryNamingConventions:
    """Infrastructure directory names must follow STANDARDS.md §1.1 conventions."""

    def test_scheduler_dir_is_singular(self) -> None:
        """Scheduler directory must be infrastructure/scheduler/ (singular)."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            infra_dir = svc.pkg_dir / "infrastructure"
            if not infra_dir.is_dir():
                continue
            plural_dir = infra_dir / "schedulers"
            if plural_dir.is_dir():
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=str(plural_dir.relative_to(REPO_ROOT)),
                        line=0,
                        rule="TOPO-DIR-SCHEDULER",
                        detail=(
                            "infrastructure/schedulers/ uses plural naming. "
                            "Rename to infrastructure/scheduler/ (STANDARDS.md §1.1)."
                        ),
                    )
                )
        real = _filter_violations(violations, "TOPO-DIR-SCHEDULER")
        assert_no_violations(real, rule="TOPO-DIR-SCHEDULER")

    def test_workers_dir_is_plural(self) -> None:
        """Workers directory must be infrastructure/workers/ (plural)."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            infra_dir = svc.pkg_dir / "infrastructure"
            if not infra_dir.is_dir():
                continue
            singular_dir = infra_dir / "worker"
            if singular_dir.is_dir():
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=str(singular_dir.relative_to(REPO_ROOT)),
                        line=0,
                        rule="TOPO-DIR-WORKER",
                        detail=(
                            "infrastructure/worker/ uses singular naming. "
                            "Rename to infrastructure/workers/ (STANDARDS.md §1.1)."
                        ),
                    )
                )
        # No baseline needed — no service currently has this pattern.
        assert_no_violations(violations, rule="TOPO-DIR-WORKER")

    def test_consumers_dir_under_messaging(self) -> None:
        """Consumer classes must live in infrastructure/messaging/consumers/, not infrastructure/consumer/."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            infra_dir = svc.pkg_dir / "infrastructure"
            if not infra_dir.is_dir():
                continue
            legacy_dir = infra_dir / "consumer"
            if legacy_dir.is_dir():
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=str(legacy_dir.relative_to(REPO_ROOT)),
                        line=0,
                        rule="TOPO-DIR-CONSUMER",
                        detail=(
                            "infrastructure/consumer/ is outside messaging/. "
                            "Move to infrastructure/messaging/consumers/ (STANDARDS.md §1.1)."
                        ),
                    )
                )
        real = _filter_violations(violations, "TOPO-DIR-CONSUMER")
        assert_no_violations(real, rule="TOPO-DIR-CONSUMER")

    def test_outbox_dir_under_messaging(self) -> None:
        """Outbox must live in infrastructure/messaging/outbox/, not infrastructure/outbox/."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            infra_dir = svc.pkg_dir / "infrastructure"
            if not infra_dir.is_dir():
                continue
            legacy_dir = infra_dir / "outbox"
            if legacy_dir.is_dir():
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=str(legacy_dir.relative_to(REPO_ROOT)),
                        line=0,
                        rule="TOPO-DIR-OUTBOX",
                        detail=(
                            "infrastructure/outbox/ is outside messaging/. "
                            "Move to infrastructure/messaging/outbox/ (STANDARDS.md §1.1)."
                        ),
                    )
                )
        real = _filter_violations(violations, "TOPO-DIR-OUTBOX")
        assert_no_violations(real, rule="TOPO-DIR-OUTBOX")

    def test_no_stale_outbox_outside_messaging(self) -> None:
        """No infrastructure/outbox/ may exist alongside infrastructure/messaging/outbox/."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            infra_dir = svc.pkg_dir / "infrastructure"
            if not infra_dir.is_dir():
                continue
            stale_dir = infra_dir / "outbox"
            canonical_dir = infra_dir / "messaging" / "outbox"
            if stale_dir.is_dir() and canonical_dir.is_dir():
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=str(stale_dir.relative_to(REPO_ROOT)),
                        line=0,
                        rule="TOPO-STALE-OUTBOX",
                        detail=(
                            "Stale infrastructure/outbox/ co-exists with canonical "
                            "infrastructure/messaging/outbox/. "
                            "Remove the stale directory (STANDARDS.md §1.1)."
                        ),
                    )
                )
        real = _filter_violations(violations, "TOPO-STALE-OUTBOX")
        assert_no_violations(real, rule="TOPO-STALE-OUTBOX")


# ---------------------------------------------------------------------------
# TestBaselineIntegrity (T-A-2-04)
# ---------------------------------------------------------------------------


class TestBaselineIntegrity:
    """Verify TOPOLOGY_BASELINE is well-formed and references real services/rules."""

    def test_baseline_rule_ids_are_known(self) -> None:
        """All rule IDs in TOPOLOGY_BASELINE must be in _KNOWN_RULE_IDS."""
        unknown = {rule_id for (_, rule_id) in TOPOLOGY_BASELINE if rule_id not in _KNOWN_RULE_IDS}
        assert (
            not unknown
        ), f"Unknown rule IDs in TOPOLOGY_BASELINE: {unknown}. Add them to _KNOWN_RULE_IDS or fix the typo."

    def test_baseline_services_exist_in_repo(self) -> None:
        """All services in TOPOLOGY_BASELINE must exist under services/."""
        all_svc_names = {svc.name for svc in discover_services()}
        missing = {svc_name for (svc_name, _) in TOPOLOGY_BASELINE if svc_name not in all_svc_names}
        assert (
            not missing
        ), f"TOPOLOGY_BASELINE references non-existent service(s): {missing}. Remove or update the baseline entries."
