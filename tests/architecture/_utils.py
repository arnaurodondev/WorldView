"""
Architecture test utilities.

Provides helpers for service discovery, AST import scanning, path normalization,
and rich assertion wrappers used by all architecture test modules.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # worldview/
SERVICES_DIR = REPO_ROOT / "services"
LIBS_DIR = REPO_ROOT / "libs"

# Services that are infrastructure-only (no FastAPI package).
# These are excluded from service-code architecture checks.
NON_SERVICE_DIRS: set[str] = {
    "intelligence-migrations",
}

# Scaffolded services: minimal stubs with no domain/application layers yet.
# Structure checks are relaxed; import-level checks still apply to what exists.
SCAFFOLDED_SERVICES: set[str] = {
    "content-store",
    "nlp-pipeline",
    "knowledge-graph",
    "rag-chat",
    "alert",
}


# ---------------------------------------------------------------------------
# Service discovery
# ---------------------------------------------------------------------------


@dataclass
class ServiceInfo:
    name: str  # e.g. "portfolio"
    service_dir: Path  # services/portfolio/
    src_dir: Path  # services/portfolio/src/
    pkg_name: str  # "portfolio"
    pkg_dir: Path  # services/portfolio/src/portfolio/
    is_scaffolded: bool = False


def _find_pkg_name(src_dir: Path) -> str | None:
    if not src_dir.is_dir():
        return None
    for p in src_dir.iterdir():
        if p.is_dir() and (p / "__init__.py").exists():
            return p.name
    return None


def _is_scaffolded(pkg_dir: Path) -> bool:
    has_domain = (pkg_dir / "domain").is_dir()
    has_app = (pkg_dir / "application").is_dir()
    return not (has_domain or has_app)


def discover_services(
    *,
    include_scaffolded: bool = True,
    only: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[ServiceInfo]:
    """Discover all FastAPI services under services/."""
    services = []
    for svc_dir in sorted(SERVICES_DIR.iterdir()):
        if not svc_dir.is_dir():
            continue
        if svc_dir.name in NON_SERVICE_DIRS:
            continue
        if only and svc_dir.name not in only:
            continue
        if exclude and svc_dir.name in exclude:
            continue

        src_dir = svc_dir / "src"
        pkg_name = _find_pkg_name(src_dir)
        if pkg_name is None:
            continue

        pkg_dir = src_dir / pkg_name
        scaffolded = _is_scaffolded(pkg_dir)

        if not include_scaffolded and scaffolded:
            continue

        services.append(
            ServiceInfo(
                name=svc_dir.name,
                service_dir=svc_dir,
                src_dir=src_dir,
                pkg_name=pkg_name,
                pkg_dir=pkg_dir,
                is_scaffolded=scaffolded,
            )
        )
    return services


def discover_mature_services() -> list[ServiceInfo]:
    """Services with full hexagonal architecture (non-scaffolded)."""
    return discover_services(include_scaffolded=False)


# ---------------------------------------------------------------------------
# AST import scanning
# ---------------------------------------------------------------------------


@dataclass
class ImportRecord:
    file: Path
    line: int
    module: str  # For "import X": X; for "from X import Y": X
    names: list[str]  # For "import X": [X]; for "from X import Y": [Y]
    is_from: bool  # True = from-import
    is_type_checking: bool = False  # True = inside `if TYPE_CHECKING:` block


class _ImportScanner(ast.NodeVisitor):
    """AST visitor that records imports, tracking TYPE_CHECKING context."""

    def __init__(self, file: Path) -> None:
        self.file = file
        self.records: list[ImportRecord] = []
        self._in_type_checking: bool = False

    def _is_type_checking_test(self, node: ast.If) -> bool:
        test = node.test
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            return True
        if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
            return True
        return False

    def visit_If(self, node: ast.If) -> None:
        if self._is_type_checking_test(node):
            old = self._in_type_checking
            self._in_type_checking = True
            for child in node.body:
                self.visit(child)
            self._in_type_checking = old
            # Don't visit the else branch under TYPE_CHECKING
        else:
            self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.records.append(
                ImportRecord(
                    file=self.file,
                    line=node.lineno,
                    module=alias.name,
                    names=[alias.name],
                    is_from=False,
                    is_type_checking=self._in_type_checking,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        names = [alias.name for alias in node.names]
        self.records.append(
            ImportRecord(
                file=self.file,
                line=node.lineno,
                module=module,
                names=names,
                is_from=True,
                is_type_checking=self._in_type_checking,
            )
        )


def scan_imports(py_file: Path) -> list[ImportRecord]:
    """Parse a Python file and return all import statements."""
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, OSError):
        return []

    scanner = _ImportScanner(py_file)
    scanner.visit(tree)
    return scanner.records


def iter_py_files(directory: Path, skip_dirs: set[str] | None = None) -> Iterator[Path]:
    """Yield all .py files under directory, skipping common non-source dirs."""
    _skip = skip_dirs or {".venv", "venv", "__pycache__", ".mypy_cache", ".ruff_cache"}
    for py_file in directory.rglob("*.py"):
        if any(part in _skip for part in py_file.parts):
            continue
        yield py_file


# ---------------------------------------------------------------------------
# Layer helpers
# ---------------------------------------------------------------------------

LAYER_NAMES = ("domain", "application", "api", "infrastructure")


def layer_of(py_file: Path, pkg_dir: Path) -> str | None:
    """Return the layer name for a file, or None if not in a layer directory."""
    try:
        rel = py_file.relative_to(pkg_dir)
    except ValueError:
        return None
    parts = rel.parts
    if parts and parts[0] in LAYER_NAMES:
        return parts[0]
    return None


def module_path_from_file(py_file: Path, src_dir: Path) -> str:
    """Convert a file path to a dotted module path."""
    try:
        rel = py_file.relative_to(src_dir)
    except ValueError:
        return str(py_file)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Rich assertion wrappers
# ---------------------------------------------------------------------------


@dataclass
class ArchViolation:
    service: str
    file: str
    line: int
    rule: str
    detail: str


def assert_no_violations(violations: list[ArchViolation], *, rule: str = "") -> None:
    """Raise AssertionError with rich context if violations list is non-empty."""
    if not violations:
        return

    prefix = f"[{rule}] " if rule else ""
    lines = [f"\n{prefix}Architecture violations ({len(violations)}):\n"]

    for v in violations:
        lines.append(f"  Service:  {v.service}")
        lines.append(f"  File:     {v.file}:{v.line}")
        lines.append(f"  Rule:     {v.rule}")
        lines.append(f"  Detail:   {v.detail}")
        lines.append("")

    raise AssertionError("\n".join(lines))


def collect_violations(
    services: list[ServiceInfo],
    check_fn: Callable[[ServiceInfo], list[ArchViolation]],  # type: ignore[name-defined]
) -> list[ArchViolation]:
    """Run check_fn over all services and aggregate violations."""
    all_violations: list[ArchViolation] = []
    for svc in services:
        all_violations.extend(check_fn(svc))
    return all_violations
