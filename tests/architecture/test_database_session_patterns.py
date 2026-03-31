"""
Architecture test: R23 read/write database session split enforcement.

Verifies that every database-owning service follows the dual-session factory
pattern required by RULES.md R23 and STANDARDS.md \u00a715:

1. Config has a read-replica URL field (optional, with default).
2. Session module creates dual factories (write + read) with fallback.
3. All ``create_async_engine()`` calls set ``pool_pre_ping=True`` and
   explicit ``pool_size`` / ``max_overflow``.

Uses R23_BASELINE to allow known non-compliant services while they are
being fixed (Sub-Plan B).  Baselined violations print as warnings; only
un-baselined violations fail the test.

Per RULES.md R23, STANDARDS.md \u00a715.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

from tests.architecture._utils import (
    REPO_ROOT,
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_services,
)

# ---------------------------------------------------------------------------
# Service DB discovery
# ---------------------------------------------------------------------------

# Standard DB directory is ``infrastructure/db/``.  S6 (nlp-pipeline) and
# S7 (knowledge-graph) use ``infrastructure/nlp_db/`` and
# ``infrastructure/intelligence_db/`` respectively.
_DB_DIR_PATTERNS = ("db", "nlp_db", "intelligence_db")


def _discover_db_dirs(svc: ServiceInfo) -> list[Path]:
    """Return all infrastructure/*db*/ directories that contain session.py."""
    infra = svc.pkg_dir / "infrastructure"
    if not infra.is_dir():
        return []
    dirs: list[Path] = []
    for child in sorted(infra.iterdir()):
        if not child.is_dir():
            continue
        if child.name in _DB_DIR_PATTERNS and (child / "session.py").exists():
            dirs.append(child)
    return dirs


def _has_database(svc: ServiceInfo) -> bool:
    """True if the service owns at least one database directory."""
    return len(_discover_db_dirs(svc)) > 0


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


class _SettingsFieldVisitor(ast.NodeVisitor):
    """Extract annotated field names from a Settings class."""

    def __init__(self) -> None:
        self.field_names: set[str] = set()
        self.field_defaults: dict[str, ast.expr | None] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if "Settings" in node.name:
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    self.field_names.add(item.target.id)
                    self.field_defaults[item.target.id] = item.value
        self.generic_visit(node)


class _CreateAsyncEngineVisitor(ast.NodeVisitor):
    """Find all ``create_async_engine(...)`` calls and extract their keyword args."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, bool]]] = []  # (line, {kwarg: present})

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_create_engine = False
        if isinstance(func, ast.Name) and func.id == "create_async_engine":
            is_create_engine = True
        elif isinstance(func, ast.Attribute) and func.attr == "create_async_engine":
            is_create_engine = True

        if is_create_engine:
            kw_names = {kw.arg for kw in node.keywords if kw.arg is not None}
            self.calls.append(
                (
                    node.lineno,
                    {
                        "pool_pre_ping": "pool_pre_ping" in kw_names,
                        "pool_size": "pool_size" in kw_names,
                        "max_overflow": "max_overflow" in kw_names,
                    },
                )
            )
        self.generic_visit(node)


class _DualFactoryVisitor(ast.NodeVisitor):
    """Detect dual engine/factory patterns in session.py.

    Looks for:
    - Number of ``create_async_engine()`` calls (>= 2 means dual, or 1 with fallback)
    - Conditional fallback logic (comparing read URL to write URL)
    """

    def __init__(self) -> None:
        self.engine_call_count: int = 0
        self.has_fallback_conditional: bool = False

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id == "create_async_engine":
            self.engine_call_count += 1
        elif isinstance(func, ast.Attribute) and func.attr == "create_async_engine":
            self.engine_call_count += 1
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        # Detect ``if read_url == settings.db_url:`` style fallback
        test = node.test
        if isinstance(test, ast.Compare):
            source = ast.dump(test)
            if "read" in source.lower() or "replica" in source.lower():
                self.has_fallback_conditional = True
        self.generic_visit(node)


def _parse_file(path: Path) -> ast.Module | None:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        return ast.parse(source, filename=str(path))
    except (SyntaxError, OSError):
        return None


# ---------------------------------------------------------------------------
# R23 Baseline — known non-compliant services (fixed in Sub-Plan B)
# ---------------------------------------------------------------------------

R23_BASELINE: dict[tuple[str, str], str] = {
    # S1: portfolio — DONE (PLAN-0012 Wave B-1)
    # --- S5: content-store — fix in PLAN-0012 Wave B-2 ---
    ("content-store", "R23-CONFIG-READ-URL"): "Fix in PLAN-0012 Wave B-2",
    ("content-store", "R23-CONFIG-POOL-FIELDS"): "Fix in PLAN-0012 Wave B-2",
    ("content-store", "R23-DUAL-FACTORY"): "Fix in PLAN-0012 Wave B-2",
    ("content-store", "R23-POOL-PRE-PING"): "Fix in PLAN-0012 Wave B-2",
    ("content-store", "R23-POOL-SIZE"): "Fix in PLAN-0012 Wave B-2",
    ("content-store", "R23-POOL-MAX-OVERFLOW"): "Fix in PLAN-0012 Wave B-2",
    # --- S10: alert — fix in PLAN-0012 Wave B-2 ---
    ("alert", "R23-CONFIG-READ-URL"): "Fix in PLAN-0012 Wave B-2",
    ("alert", "R23-CONFIG-POOL-FIELDS"): "Fix in PLAN-0012 Wave B-2",
    ("alert", "R23-DUAL-FACTORY"): "Fix in PLAN-0012 Wave B-2",
    ("alert", "R23-POOL-PRE-PING"): "Fix in PLAN-0012 Wave B-2",
    ("alert", "R23-POOL-SIZE"): "Fix in PLAN-0012 Wave B-2",
    ("alert", "R23-POOL-MAX-OVERFLOW"): "Fix in PLAN-0012 Wave B-2",
    # --- S6: nlp-pipeline — fix in PLAN-0012 Wave B-3 ---
    ("nlp-pipeline", "R23-CONFIG-READ-URL"): "Fix in PLAN-0012 Wave B-3",
    ("nlp-pipeline", "R23-CONFIG-POOL-FIELDS"): "Fix in PLAN-0012 Wave B-3",
    ("nlp-pipeline", "R23-DUAL-FACTORY"): "Fix in PLAN-0012 Wave B-3",
    ("nlp-pipeline", "R23-POOL-PRE-PING"): "Fix in PLAN-0012 Wave B-3",
    ("nlp-pipeline", "R23-POOL-SIZE"): "Fix in PLAN-0012 Wave B-3",
    ("nlp-pipeline", "R23-POOL-MAX-OVERFLOW"): "Fix in PLAN-0012 Wave B-3",
    # --- S7: knowledge-graph — fix in PLAN-0012 Wave B-3 ---
    ("knowledge-graph", "R23-CONFIG-READ-URL"): "Fix in PLAN-0012 Wave B-3",
    ("knowledge-graph", "R23-CONFIG-POOL-FIELDS"): "Fix in PLAN-0012 Wave B-3",
    # knowledge-graph already has dual factory in session.py — no R23-DUAL-FACTORY baseline needed
    ("knowledge-graph", "R23-POOL-PRE-PING"): "Fix in PLAN-0012 Wave B-3",
    ("knowledge-graph", "R23-POOL-SIZE"): "Fix in PLAN-0012 Wave B-3",
    ("knowledge-graph", "R23-POOL-MAX-OVERFLOW"): "Fix in PLAN-0012 Wave B-3",
}

_KNOWN_RULE_IDS: frozenset[str] = frozenset(
    {
        "R23-CONFIG-WRITE-URL",
        "R23-CONFIG-READ-URL",
        "R23-CONFIG-READ-URL-DEFAULT",
        "R23-CONFIG-POOL-FIELDS",
        "R23-SESSION-MODULE",
        "R23-DUAL-FACTORY",
        "R23-POOL-PRE-PING",
        "R23-POOL-SIZE",
        "R23-POOL-MAX-OVERFLOW",
    }
)


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
        if key in R23_BASELINE:
            violated_services.add(v.service)
            print(f"\n  [R23 BASELINE] [{rule_id}] {v.service}: {v.detail}\n    \u2192 {R23_BASELINE[key]}")
        else:
            real.append(v)

    # Warn about stale entries (violation no longer detected for this rule).
    for (svc_name, base_rule), reason in R23_BASELINE.items():
        if base_rule != rule_id:
            continue
        if svc_name not in violated_services:
            warnings.warn(
                f"Stale R23_BASELINE entry ({svc_name!r}, {rule_id!r}) \u2014 "
                f"violation no longer found; remove this entry. Planned fix: {reason}",
                UserWarning,
                stacklevel=3,
            )

    return real


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def _check_config_write_url(svc: ServiceInfo) -> list[ArchViolation]:
    """Every DB-owning service Settings must have a database URL field."""
    if not _has_database(svc):
        return []
    config_py = svc.pkg_dir / "config.py"
    if not config_py.exists():
        return []
    tree = _parse_file(config_py)
    if tree is None:
        return []

    visitor = _SettingsFieldVisitor()
    visitor.visit(tree)

    # Accept any field containing "url" and ("db" or "database")
    has_write_url = any(
        ("url" in f.lower() or "dsn" in f.lower())
        and ("db" in f.lower() or "database" in f.lower())
        and "read" not in f.lower()
        and "replica" not in f.lower()
        for f in visitor.field_names
    )
    if not has_write_url:
        rel = str(config_py.relative_to(REPO_ROOT))
        return [
            ArchViolation(
                service=svc.name,
                file=rel,
                line=0,
                rule="R23-CONFIG-WRITE-URL",
                detail="Settings missing a write database URL field (e.g. db_url, database_url)",
            )
        ]
    return []


def _check_config_read_url(svc: ServiceInfo) -> list[ArchViolation]:
    """Every DB-owning service Settings must have an optional read-replica URL field."""
    if not _has_database(svc):
        return []
    config_py = svc.pkg_dir / "config.py"
    if not config_py.exists():
        return []
    tree = _parse_file(config_py)
    if tree is None:
        return []

    visitor = _SettingsFieldVisitor()
    visitor.visit(tree)

    # For S6 (nlp-pipeline) with two DBs, check for read URL fields for each
    db_dirs = _discover_db_dirs(svc)
    violations: list[ArchViolation] = []
    rel = str(config_py.relative_to(REPO_ROOT))

    # Must have at least one field with "read" AND ("url" or "replica" or "dsn")
    read_url_fields = [
        f
        for f in visitor.field_names
        if "read" in f.lower() and ("url" in f.lower() or "replica" in f.lower() or "dsn" in f.lower())
    ]

    if not read_url_fields:
        violations.append(
            ArchViolation(
                service=svc.name,
                file=rel,
                line=0,
                rule="R23-CONFIG-READ-URL",
                detail=(
                    "Settings missing a read-replica URL field "
                    "(e.g. db_url_read, database_url_read). "
                    "R23 requires an optional read URL with fallback to the write URL."
                ),
            )
        )

    # For multi-DB services (e.g. S6 with nlp_db + intelligence_db),
    # check we have a read URL for each database
    if len(db_dirs) > 1 and len(read_url_fields) < len(db_dirs):
        violations.append(
            ArchViolation(
                service=svc.name,
                file=rel,
                line=0,
                rule="R23-CONFIG-READ-URL",
                detail=(
                    f"Service has {len(db_dirs)} databases but only {len(read_url_fields)} "
                    f"read-replica URL fields. Each database needs its own read URL field."
                ),
            )
        )

    return violations


def _check_config_read_url_default(svc: ServiceInfo) -> list[ArchViolation]:
    """The read-replica URL field must have a default (empty string or None)."""
    if not _has_database(svc):
        return []
    config_py = svc.pkg_dir / "config.py"
    if not config_py.exists():
        return []
    tree = _parse_file(config_py)
    if tree is None:
        return []

    visitor = _SettingsFieldVisitor()
    visitor.visit(tree)

    violations: list[ArchViolation] = []
    rel = str(config_py.relative_to(REPO_ROOT))

    for fname in visitor.field_names:
        if "read" not in fname.lower():
            continue
        if not ("url" in fname.lower() or "replica" in fname.lower() or "dsn" in fname.lower()):
            continue

        default = visitor.field_defaults.get(fname)
        # Must have a default value (empty string or None)
        if default is None:
            # No default at all — field is required, which violates R23 optionality
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=rel,
                    line=0,
                    rule="R23-CONFIG-READ-URL-DEFAULT",
                    detail=(
                        f"Read URL field '{fname}' has no default value. "
                        "It must default to '' or None so read/write split is optional."
                    ),
                )
            )

    return violations


def _check_config_pool_fields(svc: ServiceInfo) -> list[ArchViolation]:
    """Pool sizing must be configured — either via Settings fields or hardcoded in session.py.

    Checks config.py for ``pool_size``/``max_overflow`` fields first.  If absent,
    falls back to checking that session.py passes these kwargs to
    ``create_async_engine()``.  Services that hardcode pool sizing in session.py
    (e.g. S2, S3, S4) are considered compliant.
    """
    if not _has_database(svc):
        return []

    # 1) Check config.py for pool fields
    config_py = svc.pkg_dir / "config.py"
    if config_py.exists():
        tree = _parse_file(config_py)
        if tree is not None:
            visitor = _SettingsFieldVisitor()
            visitor.visit(tree)
            has_pool_size = any("pool_size" in f.lower() for f in visitor.field_names)
            has_max_overflow = any("max_overflow" in f.lower() or "overflow" in f.lower() for f in visitor.field_names)
            if has_pool_size and has_max_overflow:
                return []

    # 2) Fallback: check session.py engine calls for explicit pool kwargs
    db_dirs = _discover_db_dirs(svc)
    for db_dir in db_dirs:
        session_py = db_dir / "session.py"
        if not session_py.exists():
            continue
        tree = _parse_file(session_py)
        if tree is None:
            continue
        engine_visitor = _CreateAsyncEngineVisitor()
        engine_visitor.visit(tree)
        if engine_visitor.calls and all(kw["pool_size"] and kw["max_overflow"] for _, kw in engine_visitor.calls):
            return []

    rel = str(config_py.relative_to(REPO_ROOT)) if config_py.exists() else f"services/{svc.name}/"
    return [
        ArchViolation(
            service=svc.name,
            file=rel,
            line=0,
            rule="R23-CONFIG-POOL-FIELDS",
            detail=(
                "No pool sizing found in config.py fields or session.py engine calls. Add db_pool_size/db_max_overflow."
            ),
        )
    ]


def _check_session_module_exists(svc: ServiceInfo) -> list[ArchViolation]:
    """Every DB-owning service must have infrastructure/db/session.py (or equivalent)."""
    db_dirs = _discover_db_dirs(svc)
    if not db_dirs:
        # Service has no DB directory — not a DB-owning service, skip
        return []
    violations: list[ArchViolation] = []
    for db_dir in db_dirs:
        session_py = db_dir / "session.py"
        if not session_py.exists():
            rel = str(db_dir.relative_to(REPO_ROOT))
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=rel,
                    line=0,
                    rule="R23-SESSION-MODULE",
                    detail=f"Missing session.py in {db_dir.name}/ directory",
                )
            )
    return violations


def _check_dual_factory(svc: ServiceInfo) -> list[ArchViolation]:
    """session.py must create dual engine/factory (write + read) with fallback."""
    db_dirs = _discover_db_dirs(svc)
    violations: list[ArchViolation] = []

    for db_dir in db_dirs:
        session_py = db_dir / "session.py"
        if not session_py.exists():
            continue
        tree = _parse_file(session_py)
        if tree is None:
            continue

        visitor = _DualFactoryVisitor()
        visitor.visit(tree)
        rel = str(session_py.relative_to(REPO_ROOT))

        # Compliant: >= 2 engine calls, OR 1 engine call with fallback conditional
        is_dual = visitor.engine_call_count >= 2 or (
            visitor.engine_call_count >= 1 and visitor.has_fallback_conditional
        )
        if not is_dual:
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=rel,
                    line=0,
                    rule="R23-DUAL-FACTORY",
                    detail=(
                        f"session.py has {visitor.engine_call_count} create_async_engine() call(s) "
                        f"and {'has' if visitor.has_fallback_conditional else 'no'} fallback conditional. "
                        "R23 requires dual factories (write + read) with fallback logic."
                    ),
                )
            )
    return violations


def _check_pool_pre_ping(svc: ServiceInfo) -> list[ArchViolation]:
    """Every create_async_engine() call must set pool_pre_ping=True."""
    db_dirs = _discover_db_dirs(svc)
    violations: list[ArchViolation] = []

    for db_dir in db_dirs:
        session_py = db_dir / "session.py"
        if not session_py.exists():
            continue
        tree = _parse_file(session_py)
        if tree is None:
            continue

        visitor = _CreateAsyncEngineVisitor()
        visitor.visit(tree)
        rel = str(session_py.relative_to(REPO_ROOT))

        for line, kw_info in visitor.calls:
            if not kw_info["pool_pre_ping"]:
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=rel,
                        line=line,
                        rule="R23-POOL-PRE-PING",
                        detail="create_async_engine() missing pool_pre_ping=True",
                    )
                )
    return violations


def _check_pool_size(svc: ServiceInfo) -> list[ArchViolation]:
    """Every create_async_engine() call must specify pool_size."""
    db_dirs = _discover_db_dirs(svc)
    violations: list[ArchViolation] = []

    for db_dir in db_dirs:
        session_py = db_dir / "session.py"
        if not session_py.exists():
            continue
        tree = _parse_file(session_py)
        if tree is None:
            continue

        visitor = _CreateAsyncEngineVisitor()
        visitor.visit(tree)
        rel = str(session_py.relative_to(REPO_ROOT))

        for line, kw_info in visitor.calls:
            if not kw_info["pool_size"]:
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=rel,
                        line=line,
                        rule="R23-POOL-SIZE",
                        detail="create_async_engine() missing explicit pool_size parameter",
                    )
                )
    return violations


def _check_pool_max_overflow(svc: ServiceInfo) -> list[ArchViolation]:
    """Every create_async_engine() call must specify max_overflow."""
    db_dirs = _discover_db_dirs(svc)
    violations: list[ArchViolation] = []

    for db_dir in db_dirs:
        session_py = db_dir / "session.py"
        if not session_py.exists():
            continue
        tree = _parse_file(session_py)
        if tree is None:
            continue

        visitor = _CreateAsyncEngineVisitor()
        visitor.visit(tree)
        rel = str(session_py.relative_to(REPO_ROOT))

        for line, kw_info in visitor.calls:
            if not kw_info["max_overflow"]:
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=rel,
                        line=line,
                        rule="R23-POOL-MAX-OVERFLOW",
                        detail="create_async_engine() missing explicit max_overflow parameter",
                    )
                )
    return violations


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestR23ConfigFields:
    """T-A-1-01: Verify R23 config field compliance."""

    def test_settings_has_write_db_url(self) -> None:
        """Every DB-owning service Settings has a database URL field."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            if _has_database(svc):
                violations.extend(_check_config_write_url(svc))
        real = _filter_violations(violations, "R23-CONFIG-WRITE-URL")
        assert_no_violations(real, rule="R23-CONFIG-WRITE-URL")

    def test_settings_has_read_db_url(self) -> None:
        """Every DB-owning service Settings has an optional read-replica URL field."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            if _has_database(svc):
                violations.extend(_check_config_read_url(svc))
        real = _filter_violations(violations, "R23-CONFIG-READ-URL")
        assert_no_violations(real, rule="R23-CONFIG-READ-URL")

    def test_read_url_has_default(self) -> None:
        """The read-replica URL field has a default (empty or None)."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            if _has_database(svc):
                violations.extend(_check_config_read_url_default(svc))
        real = _filter_violations(violations, "R23-CONFIG-READ-URL-DEFAULT")
        assert_no_violations(real, rule="R23-CONFIG-READ-URL-DEFAULT")

    def test_settings_has_pool_size_fields(self) -> None:
        """Settings has pool sizing configuration fields."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            if _has_database(svc):
                violations.extend(_check_config_pool_fields(svc))
        real = _filter_violations(violations, "R23-CONFIG-POOL-FIELDS")
        assert_no_violations(real, rule="R23-CONFIG-POOL-FIELDS")


class TestR23DualFactory:
    """T-A-1-02: Verify dual factory pattern in session modules."""

    def test_session_module_exists(self) -> None:
        """Every DB-owning service has infrastructure/db/session.py (or equivalent)."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            violations.extend(_check_session_module_exists(svc))
        real = _filter_violations(violations, "R23-SESSION-MODULE")
        assert_no_violations(real, rule="R23-SESSION-MODULE")

    def test_dual_engine_creation(self) -> None:
        """session.py creates dual engines (write + read) or has fallback logic."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            if _has_database(svc):
                violations.extend(_check_dual_factory(svc))
        real = _filter_violations(violations, "R23-DUAL-FACTORY")
        assert_no_violations(real, rule="R23-DUAL-FACTORY")


class TestR23PoolSizing:
    """T-A-1-03: Verify pool sizing parameters on all engine calls."""

    def test_pool_pre_ping_enabled(self) -> None:
        """Every create_async_engine call has pool_pre_ping=True."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            if _has_database(svc):
                violations.extend(_check_pool_pre_ping(svc))
        real = _filter_violations(violations, "R23-POOL-PRE-PING")
        assert_no_violations(real, rule="R23-POOL-PRE-PING")

    def test_explicit_pool_size(self) -> None:
        """Every create_async_engine call specifies pool_size."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            if _has_database(svc):
                violations.extend(_check_pool_size(svc))
        real = _filter_violations(violations, "R23-POOL-SIZE")
        assert_no_violations(real, rule="R23-POOL-SIZE")

    def test_explicit_max_overflow(self) -> None:
        """Every create_async_engine call specifies max_overflow."""
        violations: list[ArchViolation] = []
        for svc in discover_services():
            if _has_database(svc):
                violations.extend(_check_pool_max_overflow(svc))
        real = _filter_violations(violations, "R23-POOL-MAX-OVERFLOW")
        assert_no_violations(real, rule="R23-POOL-MAX-OVERFLOW")


class TestR23BaselineIntegrity:
    """T-A-1-04: Verify R23_BASELINE is well-formed."""

    def test_baseline_rule_ids_are_known(self) -> None:
        """All rule IDs in R23_BASELINE must be in _KNOWN_RULE_IDS."""
        unknown = {rule_id for (_, rule_id) in R23_BASELINE if rule_id not in _KNOWN_RULE_IDS}
        assert not unknown, f"Unknown rule IDs in R23_BASELINE: {unknown}. Add them to _KNOWN_RULE_IDS or fix the typo."

    def test_baseline_services_exist_in_repo(self) -> None:
        """All services in R23_BASELINE must exist under services/."""
        all_svc_names = {svc.name for svc in discover_services()}
        missing = {svc_name for (svc_name, _) in R23_BASELINE if svc_name not in all_svc_names}
        assert (
            not missing
        ), f"R23_BASELINE references non-existent service(s): {missing}. Remove or update the baseline entries."
