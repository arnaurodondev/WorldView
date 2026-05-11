"""
Architecture test utilities.

Provides helpers for service discovery, AST import scanning, path normalization,
and rich assertion wrappers used by all architecture test modules.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
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
    """A service is scaffolded if it lacks domain, application, or ports.

    A fully mature service has all three layers:
    - domain/      — pure domain logic
    - application/ — use cases and port ABCs
    - application/ports/ — abstract interfaces (required for hexagonal compliance)

    Services with domain + application but no ports are in-progress and treated
    as scaffolded until they complete the full hexagonal structure.
    """
    has_domain = (pkg_dir / "domain").is_dir()
    has_app = (pkg_dir / "application").is_dir()
    has_ports = (pkg_dir / "application" / "ports").is_dir() if has_app else False
    return not (has_domain and has_app and has_ports)


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


# ---------------------------------------------------------------------------
# Process topology helpers (STANDARDS.md §14, RULES.md R22)
# ---------------------------------------------------------------------------


class ProcessType(Enum):
    """Background process types recognised by the process topology standard."""

    DISPATCHER = "dispatcher"
    CONSUMER = "consumer"
    SCHEDULER = "scheduler"
    WORKER = "worker"


# Canonical directory paths relative to the service's pkg_dir.
CANONICAL_PATHS: dict[ProcessType, str] = {
    ProcessType.DISPATCHER: "infrastructure/messaging/outbox",
    ProcessType.CONSUMER: "infrastructure/messaging/consumers",
    ProcessType.SCHEDULER: "infrastructure/scheduler",
    ProcessType.WORKER: "infrastructure/workers",
}


@dataclass
class ProcessEntryPoint:
    """Represents a discovered background process entry point for a service."""

    service: str
    process_type: ProcessType
    class_file: Path | None  # e.g. dispatcher.py / worker.py
    main_file: Path | None  # e.g. dispatcher_main.py / worker_main.py
    dir_path: Path  # directory where the files were found

    @property
    def is_canonical_path(self) -> bool:
        """True if dir_path matches the canonical path for this process type."""
        expected = CANONICAL_PATHS[self.process_type]
        # dir_path is absolute; check whether it ends with the canonical suffix
        return str(self.dir_path).endswith(expected.replace("/", _SEP))

    @property
    def missing_main(self) -> bool:
        """True when a class file exists but the standalone entry point does not."""
        return self.class_file is not None and self.main_file is None


_SEP = "/"


def discover_process_entry_points(svc: ServiceInfo) -> list[ProcessEntryPoint]:
    """Scan a service's infrastructure/ directory for known background process files.

    Recognises:
    - Dispatchers:  ``messaging/outbox/dispatcher*.py``
    - Consumers:    ``messaging/consumers/*_consumer*.py``  (canonical)
                    ``consumer/*_consumer*.py``              (legacy / scaffolded)
    - Schedulers:   ``scheduler/*.py``  or  ``schedulers/*.py``
    - Workers:      ``workers/*.py``

    Returns one ``ProcessEntryPoint`` per logical process, pairing the class
    file with its ``*_main.py`` sibling when found.
    """
    infra_dir = svc.pkg_dir / "infrastructure"
    if not infra_dir.is_dir():
        return []

    results: list[ProcessEntryPoint] = []

    # --- Dispatchers --------------------------------------------------------
    for outbox_dir in [
        infra_dir / "messaging" / "outbox",
    ]:
        if not outbox_dir.is_dir():
            continue
        class_file = outbox_dir / "dispatcher.py"
        main_file = outbox_dir / "dispatcher_main.py"
        results.append(
            ProcessEntryPoint(
                service=svc.name,
                process_type=ProcessType.DISPATCHER,
                class_file=class_file if class_file.exists() else None,
                main_file=main_file if main_file.exists() else None,
                dir_path=outbox_dir,
            )
        )

    # --- Consumers ----------------------------------------------------------
    # Canonical path first, then legacy singular directory
    consumer_dirs: list[tuple[Path, bool]] = []
    canonical_consumers = infra_dir / "messaging" / "consumers"
    if canonical_consumers.is_dir():
        consumer_dirs.append((canonical_consumers, True))
    legacy_consumer = infra_dir / "consumer"
    if legacy_consumer.is_dir():
        consumer_dirs.append((legacy_consumer, False))

    for consumers_dir, _is_canonical in consumer_dirs:
        # Group files by base name (strip _main suffix)
        seen: dict[str, dict[str, Path]] = {}
        for py_file in sorted(consumers_dir.glob("*.py")):
            stem = py_file.stem
            if stem.startswith("_"):
                continue
            base = stem.removesuffix("_main")
            if base not in seen:
                seen[base] = {}
            if stem.endswith("_main"):
                seen[base]["main"] = py_file
            else:
                seen[base]["class"] = py_file

        for _base, files in seen.items():
            results.append(
                ProcessEntryPoint(
                    service=svc.name,
                    process_type=ProcessType.CONSUMER,
                    class_file=files.get("class"),
                    main_file=files.get("main"),
                    dir_path=consumers_dir,
                )
            )

    # --- Schedulers ---------------------------------------------------------
    for sched_dir in [
        infra_dir / "scheduler",  # canonical (singular)
        infra_dir / "schedulers",  # legacy (plural)
    ]:
        if not sched_dir.is_dir():
            continue
        # Look for scheduler.py / scheduler_main.py
        sched_class: Path | None = None
        sched_main: Path | None = None
        for py_file in sched_dir.glob("*.py"):
            stem = py_file.stem
            if stem.startswith("_"):
                continue
            if stem.endswith("_main"):
                sched_main = py_file
            elif stem in ("scheduler", "scheduler_process"):
                # scheduler_process.py is the stale naming variant
                sched_class = py_file
        results.append(
            ProcessEntryPoint(
                service=svc.name,
                process_type=ProcessType.SCHEDULER,
                class_file=sched_class,
                main_file=sched_main,
                dir_path=sched_dir,
            )
        )

    # --- Workers ------------------------------------------------------------
    workers_dir = infra_dir / "workers"
    if workers_dir.is_dir():
        class_file = workers_dir / "worker.py"
        main_file = workers_dir / "worker_main.py"
        results.append(
            ProcessEntryPoint(
                service=svc.name,
                process_type=ProcessType.WORKER,
                class_file=class_file if class_file.exists() else None,
                main_file=main_file if main_file.exists() else None,
                dir_path=workers_dir,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Lifespan background-task scanner
# ---------------------------------------------------------------------------


class _LifespanCreateTaskScanner(ast.NodeVisitor):
    """AST visitor that finds asyncio.create_task() calls inside lifespan functions.

    Only flags tasks whose coroutine names contain a consumer or dispatcher
    keyword.  Lightweight, read-only in-process tasks (e.g. cache-warmer
    refresh loops) are deliberately excluded — R22 targets Kafka consumers
    and outbox dispatchers, not cache utilities (see PRD-0017 §6.2 and the
    service-level test guard in test_app_lifespan.py for full rationale).
    """

    _LIFESPAN_NAMES = frozenset({"lifespan", "_lifespan", "startup"})

    # Function-name substrings that indicate a consumer or dispatcher task.
    # Cache-warmers, refresh loops, and other lightweight in-process helpers
    # are intentionally NOT in this list.
    _PROHIBITED_TASK_NAMES: frozenset[str] = frozenset(
        {
            "run",  # SchedulerProcess.run / ConsumerProcess.run
            "consume",
            "dispatch",
            "outbox",
            "kafka",
            "consumer",
        }
    )

    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []
        self._in_lifespan: bool = False

    # ------------------------------------------------------------------
    # Detect lifespan function boundaries

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        is_lifespan = node.name in self._LIFESPAN_NAMES or self._has_asynccontextmanager(node)
        if is_lifespan:
            old = self._in_lifespan
            self._in_lifespan = True
            self.generic_visit(node)
            self._in_lifespan = old
        else:
            self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        is_lifespan = node.name in self._LIFESPAN_NAMES or self._has_asynccontextmanager(node)
        if is_lifespan:
            old = self._in_lifespan
            self._in_lifespan = True
            self.generic_visit(node)
            self._in_lifespan = old
        else:
            self.generic_visit(node)

    @staticmethod
    def _has_asynccontextmanager(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "asynccontextmanager":
                return True
            if isinstance(dec, ast.Attribute) and dec.attr == "asynccontextmanager":
                return True
        return False

    # ------------------------------------------------------------------
    # Detect asyncio.create_task() calls

    def visit_Call(self, node: ast.Call) -> None:
        if self._in_lifespan and self._is_create_task(node):
            task_desc = self._describe_call_arg(node)
            # Only flag tasks whose coroutine name contains a prohibited keyword.
            # This mirrors the service-level guard: cache-warmers are allowed;
            # only consumers and dispatchers must be standalone processes (R22).
            task_name = task_desc.lower()
            if any(prohibited in task_name for prohibited in self._PROHIBITED_TASK_NAMES):
                self.violations.append((node.lineno, task_desc))
        self.generic_visit(node)

    @staticmethod
    def _is_create_task(node: ast.Call) -> bool:
        func = node.func
        # asyncio.create_task(...)
        if isinstance(func, ast.Attribute) and func.attr == "create_task":
            return True
        # create_task(...)  — after `from asyncio import create_task`
        if isinstance(func, ast.Name) and func.id == "create_task":
            return True
        return False

    @staticmethod
    def _describe_call_arg(node: ast.Call) -> str:
        if not node.args:
            return "create_task(?)"
        arg = node.args[0]
        if isinstance(arg, ast.Call):
            func = arg.func
            if isinstance(func, ast.Name):
                return f"create_task({func.id}(...))"
            if isinstance(func, ast.Attribute):
                return f"create_task({func.attr}(...))"
        if isinstance(arg, ast.Name):
            return f"create_task({arg.id})"
        return "create_task(?)"


def has_background_tasks_in_lifespan(app_py: Path) -> list[tuple[int, str]]:
    """Return a list of (line_number, description) for every asyncio.create_task()
    call found inside a lifespan or @asynccontextmanager-decorated function in
    the given ``app.py`` file.

    Returns an empty list if the file is clean or cannot be parsed.
    """
    try:
        source = app_py.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(app_py))
    except (SyntaxError, OSError):
        return []

    scanner = _LifespanCreateTaskScanner()
    scanner.visit(tree)
    return scanner.violations
