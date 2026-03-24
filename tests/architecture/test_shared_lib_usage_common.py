"""
Architecture test: libs/common usage patterns.

Verifies that service source code uses common.ids and common.time helpers
instead of raw uuid/datetime calls. Per docs/STANDARDS.md §2.

Only service src/ code is checked (not test files, which may use raw uuid
for fixture data — see scripts/import_guards/allowlist.yaml).
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_services,
    iter_py_files,
)


def _src_files_only(svc: ServiceInfo) -> list[Path]:
    """Return only source files (not test files) for a service."""
    return [f for f in iter_py_files(svc.pkg_dir) if "tests" not in f.parts and ".venv" not in f.parts]


class _CallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.uuid4_calls: list[int] = []
        self.utcnow_calls: list[int] = []
        self.naive_now_calls: list[int] = []  # datetime.now() without tz arg

    def visit_Call(self, node: ast.Call) -> None:
        # uuid.uuid4() and uuid4()
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "uuid4":
                self.uuid4_calls.append(node.lineno)
            elif node.func.attr == "utcnow":
                self.utcnow_calls.append(node.lineno)
            elif node.func.attr == "now":
                # datetime.now() without tz= argument is naive
                has_tz = any(
                    (isinstance(kw.value, ast.Name) and kw.value.id != "None") or (isinstance(kw.value, ast.Attribute))
                    for kw in node.keywords
                    if kw.arg == "tz"
                )
                if not has_tz and not node.args:
                    # no positional tz arg, no tz= kwarg → naive
                    self.naive_now_calls.append(node.lineno)
        elif isinstance(node.func, ast.Name):
            if node.func.id == "uuid4":
                self.uuid4_calls.append(node.lineno)

        self.generic_visit(node)


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.uuid4_imports: list[int] = []  # from uuid import uuid4

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "uuid":
            for alias in node.names:
                if alias.name == "uuid4":
                    self.uuid4_imports.append(node.lineno)
        self.generic_visit(node)


def _check_uuid_usage(svc: ServiceInfo) -> list[ArchViolation]:
    violations = []
    for py_file in _src_files_only(svc):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue

        call_visitor = _CallVisitor()
        call_visitor.visit(tree)
        imp_visitor = _ImportVisitor()
        imp_visitor.visit(tree)

        rel = str(py_file.relative_to(svc.service_dir.parent.parent))

        for line in call_visitor.uuid4_calls:
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=rel,
                    line=line,
                    rule="IG-COMMON-001",
                    detail="uuid.uuid4() in src/ code — use common.ids.new_uuid7() or common.ids.new_uuid()",
                )
            )
        for line in imp_visitor.uuid4_imports:
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=rel,
                    line=line,
                    rule="IG-COMMON-001",
                    detail="'from uuid import uuid4' in src/ code — use common.ids.*",
                )
            )
        for line in call_visitor.utcnow_calls:
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=rel,
                    line=line,
                    rule="IG-COMMON-002",
                    detail="datetime.utcnow() produces a naive datetime — use common.time.utc_now()",
                )
            )

    return violations


class TestCommonLibUsage:
    def test_no_raw_uuid4_in_service_src(self) -> None:
        """Service src/ code must not call uuid.uuid4() or import uuid4 directly."""
        violations = []
        for svc in discover_services():
            violations.extend(_check_uuid_usage(svc))
        assert_no_violations(violations, rule="IG-COMMON-001")

    def test_no_utcnow_in_service_src(self) -> None:
        """Service src/ code must not call datetime.utcnow() (deprecated, naive)."""
        violations = []
        for svc in discover_services():
            for py_file in _src_files_only(svc):
                try:
                    source = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source)
                except (SyntaxError, OSError):
                    continue
                v = _CallVisitor()
                v.visit(tree)
                rel = str(py_file.relative_to(svc.service_dir.parent.parent))
                for line in v.utcnow_calls:
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=rel,
                            line=line,
                            rule="IG-COMMON-002",
                            detail="datetime.utcnow() produces naive datetime — use common.time.utc_now()",
                        )
                    )
        assert_no_violations(violations, rule="IG-COMMON-002")
