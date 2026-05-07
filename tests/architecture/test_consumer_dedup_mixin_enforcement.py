"""
Architecture test: every BaseKafkaConsumer subclass must use ValkeyDedupMixin.

Rule: CONSUMER-DEDUP-001
Standard: STANDARDS.md §3.11

Rationale
---------
``ValkeyDedupMixin`` is the canonical idempotency implementation for all Kafka
consumers in this platform.  Hand-rolling ``is_duplicate`` / ``mark_processed``
inside individual consumer classes leads to:

1. Divergent dedup behaviours (some use Valkey, some use the DB, some use nothing).
2. Missing at-least-once fallback — Valkey failures can cause consumer crashes
   instead of graceful degradation.
3. Inconsistent TTL policies — some consumers had 24h, others had no expiry.

The mixin codifies these invariants once and enforces them platform-wide.

Allowlist
---------
Consumers that genuinely cannot use the mixin (e.g., they use DB advisory locks
for exactly-once guarantees and have no at-least-once fallback path) may be
exempted by adding an entry to
``tests/architecture/_consumer_dedup_allowlist.yaml``.

Each allowlist entry requires:
- ``class_name``    — exact Python class name
- ``module_path``   — dotted module path
- ``justification`` — explanation approved by the architecture team
- ``granted_at``    — ISO-8601 date the exemption was approved

"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import yaml  # type: ignore[import-untyped]

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_services,
    iter_py_files,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ALLOWLIST_PATH = Path(__file__).resolve().parent / "_consumer_dedup_allowlist.yaml"

# ---------------------------------------------------------------------------
# Allowlist loading
# ---------------------------------------------------------------------------


def _load_allowlist() -> set[str]:
    """Return the set of class names on the exemption allowlist.

    Each allowlist entry must have ``class_name``, ``module_path``,
    ``justification``, and ``granted_at`` to be valid.  Missing or
    malformed entries are treated as violations (fail loudly).

    Returns:
        Set of ``class_name`` strings that are exempt from the mixin requirement.
    """
    if not _ALLOWLIST_PATH.exists():
        return set()
    data = yaml.safe_load(_ALLOWLIST_PATH.read_text(encoding="utf-8")) or {}
    entries = data.get("allowlist") or []
    allowed: set[str] = set()
    required_fields = {"class_name", "module_path", "justification", "granted_at"}
    for entry in entries:
        missing = required_fields - set(entry)
        if missing:
            raise ValueError(f"Allowlist entry is missing required fields {missing}: {entry!r}")
        allowed.add(entry["class_name"])
    return allowed


# ---------------------------------------------------------------------------
# Consumer class discovery (AST-based — no import of service code required)
# ---------------------------------------------------------------------------


class _ConsumerClassInfo(NamedTuple):
    service_name: str
    file: Path
    class_name: str
    bases: list[str]  # direct base class names (not full MRO)


def _find_base_kafka_consumer_subclasses(svc: ServiceInfo) -> list[_ConsumerClassInfo]:
    """AST-scan every .py file in the service for BaseKafkaConsumer subclasses.

    We only look inside ``infrastructure/`` — the canonical location per §1.4.
    Top-level and test files are excluded.

    Returns classes whose direct bases include ``BaseKafkaConsumer``.
    """
    infra_dir = svc.pkg_dir / "infrastructure"
    if not infra_dir.is_dir():
        return []

    result: list[_ConsumerClassInfo] = []
    for py_file in iter_py_files(infra_dir):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, OSError):
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # Collect direct base names (handles Name, Attribute, Subscript[T])
            bases: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
                elif isinstance(base, ast.Subscript):
                    # e.g. BaseKafkaConsumer[dict]
                    val = base.value
                    if isinstance(val, ast.Name):
                        bases.append(val.id)
                    elif isinstance(val, ast.Attribute):
                        bases.append(val.attr)

            if "BaseKafkaConsumer" in bases:
                result.append(
                    _ConsumerClassInfo(
                        service_name=svc.name,
                        file=py_file,
                        class_name=node.name,
                        bases=bases,
                    )
                )

    return result


def _has_valkey_dedup_mixin_in_bases(info: _ConsumerClassInfo) -> bool:
    """Return True if ``ValkeyDedupMixin`` appears in the direct bases list.

    This is an AST-level check — it inspects what the source code declares,
    not the runtime MRO.  That is intentional: we want subclasses to be
    explicit about their dedup strategy, not rely on inheritance depth hiding it.
    """
    return "ValkeyDedupMixin" in info.bases


# ---------------------------------------------------------------------------
# Architecture test
# ---------------------------------------------------------------------------


class TestConsumerDedupMixinEnforcement:
    """Every BaseKafkaConsumer subclass must use ValkeyDedupMixin.

    Discovery strategy: AST-scan every .py file under
    ``services/<svc>/src/<pkg>/infrastructure/`` looking for classes that
    declare ``BaseKafkaConsumer`` (optionally subscripted) as a direct base.

    Compliance check: each found class must ALSO declare ``ValkeyDedupMixin``
    as a direct base, OR be on the allowlist in
    ``_consumer_dedup_allowlist.yaml``.
    """

    def test_all_consumers_use_valkey_dedup_mixin(self) -> None:
        """Every BaseKafkaConsumer subclass must declare ValkeyDedupMixin.

        xfail until PLAN-0084 Wave B-3: remove the xfail decorator from this
        class once all 8 consumers have been migrated and this test passes
        cleanly.

        Allowlist path: tests/architecture/_consumer_dedup_allowlist.yaml
        Rule: CONSUMER-DEDUP-001
        """
        allowed = _load_allowlist()
        violations: list[ArchViolation] = []

        for svc in discover_services(include_scaffolded=True):
            for info in _find_base_kafka_consumer_subclasses(svc):
                if info.class_name in allowed:
                    # Explicitly exempted with documented justification.
                    continue
                if not _has_valkey_dedup_mixin_in_bases(info):
                    rel_path = info.file.relative_to(REPO_ROOT)
                    violations.append(
                        ArchViolation(
                            service=info.service_name,
                            file=str(rel_path),
                            line=0,
                            rule="CONSUMER-DEDUP-001",
                            detail=(
                                f"Class `{info.class_name}` in {info.file.name} extends "
                                "BaseKafkaConsumer but does not declare ValkeyDedupMixin as a "
                                "direct base. Add `ValkeyDedupMixin` to the class bases or add "
                                "an allowlist entry with justification in "
                                "tests/architecture/_consumer_dedup_allowlist.yaml. "
                                "See STANDARDS.md §3.11 and PLAN-0084 Wave B-2/B-3."
                            ),
                        )
                    )

        assert_no_violations(violations, rule="CONSUMER-DEDUP-001")
