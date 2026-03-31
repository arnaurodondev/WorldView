"""
Architecture test: outbox/dispatcher contract invariants.

Verifies that outbox-pattern implementations in mature services adhere to
the canonical contract defined in docs/libs/messaging.md:

1. Dispatcher modules inherit from or instantiate BaseOutboxDispatcher.
2. Avro schema files are .avsc files (no inline Python dicts).
3. Dispatcher entry-point (dispatcher_main.py) exists for services with an outbox.

Per docs/STANDARDS.md §3 and docs/libs/messaging.md.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_mature_services,
)

# ---------------------------------------------------------------------------
# Baseline — dispatcher.py at non-canonical paths awaiting migration
# ---------------------------------------------------------------------------
# Key: service_name → reason
#
# Remove an entry once the dispatcher is moved to infrastructure/messaging/outbox/.
_CANONICAL_PATH_BASELINE: dict[str, str] = {
    # market-ingestion: dispatcher class lives at infrastructure/messaging/dispatcher.py
    # (not inside outbox/).  Moving it requires updating dispatcher_main.py imports.
    # Scheduled for a follow-up cleanup — not in scope for PLAN-0011.
    "market-ingestion": "Dispatcher class at infrastructure/messaging/dispatcher.py — migrate in follow-up plan",
    # Scaffolded services: dispatcher at infrastructure/outbox/ — fix in PLAN-0011 Sub-Plan C
    "knowledge-graph": "Move dispatcher to messaging/outbox/ in PLAN-0011 Wave C-3",
}

# Baseline — services whose dispatchers intentionally do NOT extend BaseOutboxDispatcher.
# Key: service_name → reason for the exception.
_INHERITANCE_BASELINE: dict[str, str] = {
    # nlp-pipeline: dispatcher stores pre-serialized bytes (not dict payloads),
    # which is incompatible with BaseOutboxDispatcher's lease-based protocol.
    "nlp-pipeline": "Custom dispatcher — stores pre-serialized Avro bytes, not dict payloads",
    # alert: custom dispatcher stores pre-serialized Avro bytes in payload_avro column,
    # uses raw Confluent Producer — incompatible with BaseOutboxDispatcher's lease-based protocol.
    "alert": "Custom dispatcher — stores pre-serialized Avro bytes, not dict payloads",
}


def _find_dispatcher_files(svc: ServiceInfo) -> list[Path]:
    """Locate dispatcher.py files in the service."""
    candidates = []
    for d in [
        svc.pkg_dir / "infrastructure" / "messaging" / "outbox" / "dispatcher.py",
        svc.pkg_dir / "messaging" / "dispatcher.py",
        svc.pkg_dir / "infrastructure" / "messaging" / "dispatcher.py",
    ]:
        if d.exists():
            candidates.append(d)
    return candidates


def _find_schema_dirs(svc: ServiceInfo) -> list[Path]:
    """Locate schema directories containing Avro files."""
    candidates = []
    for d in [
        svc.pkg_dir / "infrastructure" / "messaging" / "schemas",
        svc.pkg_dir / "messaging" / "schemas",
    ]:
        if d.is_dir():
            candidates.append(d)
    return candidates


class _BaseClassVisitor(ast.NodeVisitor):
    """Check whether a class definition uses BaseOutboxDispatcher as a base."""

    def __init__(self) -> None:
        self.inherits_base: bool = False
        self.class_names: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_names.append(node.name)
        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if "OutboxDispatcher" in base_name or "BaseOutbox" in base_name:
                self.inherits_base = True
        self.generic_visit(node)


class TestDispatcherContracts:
    def test_dispatcher_inherits_base_class(self) -> None:
        """Outbox dispatcher classes must inherit from BaseOutboxDispatcher."""
        violations = []
        for svc in discover_mature_services():
            if svc.name in _INHERITANCE_BASELINE:
                continue
            for dispatcher_file in _find_dispatcher_files(svc):
                try:
                    source = dispatcher_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source)
                except (SyntaxError, OSError):
                    continue

                visitor = _BaseClassVisitor()
                visitor.visit(tree)

                if visitor.class_names and not visitor.inherits_base:
                    rel = str(dispatcher_file.relative_to(svc.service_dir.parent.parent))
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=rel,
                            line=0,
                            rule="OUTBOX-BASE-CLASS",
                            detail=(
                                f"Dispatcher class(es) {visitor.class_names} do not inherit "
                                "BaseOutboxDispatcher. Subclass messaging.kafka.dispatcher.BaseOutboxDispatcher."
                            ),
                        )
                    )
        assert_no_violations(violations, rule="OUTBOX-BASE-CLASS")

    def test_avro_schemas_are_files_not_dicts(self) -> None:
        """Avro schemas must be .avsc files, not inline Python dicts."""
        violations = []
        for svc in discover_mature_services():
            for schema_dir in _find_schema_dirs(svc):
                # Check that .py files in schema dirs don't define schema dicts
                for py_file in schema_dir.glob("*.py"):
                    if py_file.name == "__init__.py":
                        continue
                    rel = str(py_file.relative_to(svc.service_dir.parent.parent))
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=rel,
                            line=0,
                            rule="AVRO-FILE-ONLY",
                            detail=(
                                f"Python file found in schemas/ directory: {py_file.name}. "
                                "Avro schemas must be .avsc files only — no inline Python dicts."
                            ),
                        )
                    )
        assert_no_violations(violations, rule="AVRO-FILE-ONLY")

    def test_dispatcher_at_canonical_path(self) -> None:
        """Dispatcher files must live under infrastructure/messaging/outbox/ (STANDARDS.md §1.1).

        Uses ``_CANONICAL_PATH_BASELINE`` to allow known non-canonical placements
        in services undergoing migration.  Baselined violations emit warnings only.
        """
        violations = []
        warned: set[str] = set()
        for svc in discover_mature_services():
            # Non-canonical locations: infrastructure/outbox/ or infrastructure/messaging/ (flat)
            legacy_locations = [
                svc.pkg_dir / "infrastructure" / "outbox" / "dispatcher.py",
                svc.pkg_dir / "infrastructure" / "messaging" / "dispatcher.py",
                svc.pkg_dir / "messaging" / "dispatcher.py",
            ]
            for legacy in legacy_locations:
                if not legacy.exists():
                    continue
                rel = str(legacy.relative_to(svc.service_dir.parent.parent))
                if svc.name in _CANONICAL_PATH_BASELINE:
                    if svc.name not in warned:
                        warnings.warn(
                            f"[OUTBOX-CANONICAL-PATH baseline] {svc.name}: "
                            f"dispatcher.py at non-canonical path {rel}. "
                            f"Reason: {_CANONICAL_PATH_BASELINE[svc.name]}",
                            stacklevel=2,
                        )
                        warned.add(svc.name)
                else:
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=rel,
                            line=0,
                            rule="OUTBOX-CANONICAL-PATH",
                            detail=(
                                f"dispatcher.py found at non-canonical path: {rel}. "
                                "Expected location: infrastructure/messaging/outbox/dispatcher.py "
                                "(per STANDARDS.md §1.1)."
                            ),
                        )
                    )
        assert_no_violations(violations, rule="OUTBOX-CANONICAL-PATH")

    def test_dispatcher_main_exists_for_outbox_services(self) -> None:
        """Services with an outbox dispatcher must have a dispatcher_main.py entry point."""
        violations = []
        for svc in discover_mature_services():
            dispatchers = _find_dispatcher_files(svc)
            if not dispatchers:
                continue

            # Look for dispatcher_main.py in multiple locations
            main_candidates = [
                svc.pkg_dir / "infrastructure" / "messaging" / "outbox" / "dispatcher_main.py",
                svc.pkg_dir / "messaging" / "dispatcher_main.py",
                svc.pkg_dir / "infrastructure" / "messaging" / "dispatcher_main.py",
            ]
            # Also check parent dirs (portfolio has it at messaging/dispatcher_main.py)
            if not any(m.exists() for m in main_candidates):
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=f"services/{svc.name}/src/{svc.pkg_name}",
                        line=0,
                        rule="OUTBOX-MAIN",
                        detail=(
                            "Service has outbox dispatcher.py but no dispatcher_main.py entry point. "
                            "Expected at infrastructure/messaging/outbox/dispatcher_main.py "
                            "or messaging/dispatcher_main.py."
                        ),
                    )
                )
        assert_no_violations(violations, rule="OUTBOX-MAIN")
