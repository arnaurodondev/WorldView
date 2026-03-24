#!/usr/bin/env python3
"""
Canonical service structure validator.

Discovers all services under services/* and validates that each follows
the canonical hexagonal layout defined in docs/STANDARDS.md §1.

Exit codes:
  0 — all checks pass (or all violations are in non-expired exceptions)
  1 — violations found in strict mode
  2 — usage / configuration error
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

RULE_DEFINITIONS: dict[str, str] = {
    "STR-001": "src/<package>/__init__.py must exist",
    "STR-002": "src/<package>/app.py must exist",
    "STR-003": "src/<package>/config.py must exist",
    "STR-004": "src/<package>/domain/ layer must exist",
    "STR-005": "src/<package>/application/ layer must exist",
    "STR-006": "src/<package>/api/ layer must exist",
    "STR-007": "src/<package>/infrastructure/ layer must exist",
    "STR-008": "infrastructure/messaging/schemas/ must exist for Kafka-enabled services",
    "STR-009": "tests/unit/ directory must exist",
    "STR-010": "tests/integration/ directory must exist",
    "STR-011": "tests/contract/ directory must exist",
    "STR-012": "alembic/versions/ directory must exist for DB-owning services",
    "STR-013": "infrastructure/messaging/kafka/ nested subtree is forbidden unless explicitly excepted",
}

# Services that are scaffolded stubs — many structure rules are relaxed.
# A service is considered "scaffolded" if it only has app.py/config.py/__init__.py.
# The validator detects this automatically; exceptions.yaml is used for specific overrides.


def _find_package_name(service_src: Path) -> str | None:
    """Return the Python package name under src/, or None if not found."""
    if not service_src.is_dir():
        return None
    candidates = [p for p in service_src.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if len(candidates) == 1:
        return candidates[0].name
    # Prefer the one with __init__.py
    for c in candidates:
        if (c / "__init__.py").exists():
            return c.name
    return None


def _is_scaffolded_service(pkg_dir: Path) -> bool:
    """Return True if the service is a minimal scaffold (no domain/application layers)."""
    has_domain = (pkg_dir / "domain").is_dir()
    has_application = (pkg_dir / "application").is_dir()
    has_api = (pkg_dir / "api").is_dir()
    has_infrastructure = (pkg_dir / "infrastructure").is_dir()
    return not (has_domain or has_application or has_api or has_infrastructure)


def _is_kafka_enabled(service_dir: Path, pkg_dir: Path) -> bool:
    """Heuristic: true if service has any messaging/outbox/consumer code."""
    messaging_paths = [
        pkg_dir / "infrastructure" / "messaging",
        pkg_dir / "messaging",
    ]
    for p in messaging_paths:
        if p.is_dir():
            return True
    return False


# ---------------------------------------------------------------------------
# Violation data class
# ---------------------------------------------------------------------------


class Violation:
    def __init__(self, service: str, rule_id: str, detail: str) -> None:
        self.service = service
        self.rule_id = rule_id
        self.detail = detail
        self.description = RULE_DEFINITIONS.get(rule_id, rule_id)

    def to_dict(self) -> dict[str, str]:
        return {
            "service": self.service,
            "rule_id": self.rule_id,
            "description": self.description,
            "detail": self.detail,
        }

    def __str__(self) -> str:
        return f"  [{self.rule_id}] {self.service}: {self.detail}"


# ---------------------------------------------------------------------------
# Exception loading
# ---------------------------------------------------------------------------


def _load_exceptions(exceptions_file: Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    """Load exceptions registry. Returns mapping of (service, rule_id) → record."""
    if not exceptions_file or not exceptions_file.exists():
        return {}

    try:
        import yaml  # type: ignore[import-untyped]

        with exceptions_file.open() as f:
            data = yaml.safe_load(f) or {}
    except ImportError:
        # Fallback: try simple JSON
        try:
            with exceptions_file.open() as f:
                data = json.load(f)
        except Exception as exc:
            print(f"WARNING: Could not load exceptions file {exceptions_file}: {exc}", file=sys.stderr)
            return {}
    except Exception as exc:
        print(f"WARNING: Could not load exceptions file {exceptions_file}: {exc}", file=sys.stderr)
        return {}

    result: dict[tuple[str, str], dict[str, Any]] = {}
    exceptions_list = data if isinstance(data, list) else data.get("exceptions", [])
    for entry in exceptions_list:
        key = (entry.get("service", ""), entry.get("rule_id", ""))
        result[key] = entry
    return result


def _is_excepted(
    service: str,
    rule_id: str,
    exceptions: dict[tuple[str, str], dict[str, Any]],
) -> tuple[bool, str]:
    """Return (is_excepted, reason_or_error)."""
    record = exceptions.get((service, rule_id))
    if record is None:
        return False, ""

    expires_on_raw = record.get("expires_on")
    if expires_on_raw:
        try:
            expires_on = date.fromisoformat(str(expires_on_raw))
            if date.today() > expires_on:
                return False, f"Exception expired on {expires_on_raw} (owner: {record.get('owner', '?')})"
        except ValueError:
            return False, f"Invalid expires_on date: {expires_on_raw!r}"

    return True, record.get("reason", "no reason given")


# ---------------------------------------------------------------------------
# Per-service validation
# ---------------------------------------------------------------------------


def validate_service(
    service_dir: Path,
    exceptions: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[Violation], list[str]]:
    """
    Validate one service directory.
    Returns (violations, expired_exception_errors).
    """
    violations: list[Violation] = []
    expired_errors: list[str] = []
    service_name = service_dir.name

    src_dir = service_dir / "src"
    pkg_name = _find_package_name(src_dir)
    if pkg_name is None:
        is_exc, exc_info = _is_excepted(service_name, "STR-001", exceptions)
        if not is_exc and exc_info:
            expired_errors.append(f"[STR-001] {service_name}: {exc_info}")
        if not is_exc:
            violations.append(Violation(service_name, "STR-001", "Cannot determine package name under src/"))
        return violations, expired_errors

    pkg_dir = src_dir / pkg_name

    def check(rule_id: str, condition: bool, detail: str) -> None:
        is_exc, exc_info = _is_excepted(service_name, rule_id, exceptions)
        if is_exc:
            return
        if not is_exc and exc_info:  # expired exception message
            expired_errors.append(f"[{rule_id}] {service_name}: {exc_info}")
        if not condition:
            violations.append(Violation(service_name, rule_id, detail))

    # Core entry files
    check("STR-001", (pkg_dir / "__init__.py").exists(), f"Missing {pkg_dir}/__init__.py")
    check("STR-002", (pkg_dir / "app.py").exists(), f"Missing {pkg_dir}/app.py")
    check("STR-003", (pkg_dir / "config.py").exists(), f"Missing {pkg_dir}/config.py")

    scaffolded = _is_scaffolded_service(pkg_dir)
    kafka_enabled = _is_kafka_enabled(service_dir, pkg_dir)

    # Layer folders — only required for non-scaffolded services
    if not scaffolded:
        check("STR-004", (pkg_dir / "domain").is_dir(), f"Missing domain/ layer in {pkg_dir}")
        check("STR-005", (pkg_dir / "application").is_dir(), f"Missing application/ layer in {pkg_dir}")
        check("STR-006", (pkg_dir / "api").is_dir(), f"Missing api/ layer in {pkg_dir}")
        check("STR-007", (pkg_dir / "infrastructure").is_dir(), f"Missing infrastructure/ layer in {pkg_dir}")

        # Messaging schemas folder for Kafka-enabled services
        if kafka_enabled:
            schemas_path = pkg_dir / "infrastructure" / "messaging" / "schemas"
            check(
                "STR-008",
                schemas_path.is_dir(),
                f"Missing infrastructure/messaging/schemas/ in {pkg_dir}",
            )

            nested_kafka_path = pkg_dir / "infrastructure" / "messaging" / "kafka"
            check(
                "STR-013",
                not nested_kafka_path.exists(),
                f"Forbidden nested messaging subtree: {nested_kafka_path} (move helpers to infrastructure/messaging/)",
            )

    # Test directories
    tests_dir = service_dir / "tests"
    check("STR-009", (tests_dir / "unit").is_dir(), f"Missing tests/unit/ in {service_dir}")
    check("STR-010", (tests_dir / "integration").is_dir(), f"Missing tests/integration/ in {service_dir}")
    check("STR-011", (tests_dir / "contract").is_dir(), f"Missing tests/contract/ in {service_dir}")

    # Alembic versions (only for services with a DB — all current services have alembic)
    alembic_versions = service_dir / "alembic" / "versions"
    if (service_dir / "alembic.ini").exists():
        check("STR-012", alembic_versions.is_dir(), f"Missing alembic/versions/ in {service_dir}")

    return violations, expired_errors


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_services(root: Path, service_filter: list[str] | None = None) -> list[Path]:
    services_dir = root / "services"
    if not services_dir.is_dir():
        return []
    result = []
    for p in sorted(services_dir.iterdir()):
        if not p.is_dir():
            continue
        if service_filter and p.name not in service_filter:
            continue
        result.append(p)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate canonical service structure per docs/STANDARDS.md §1.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any violation.",
    )
    parser.add_argument(
        "--report-json",
        metavar="PATH",
        help="Write machine-readable JSON report to PATH.",
    )
    parser.add_argument(
        "--services",
        metavar="CSV",
        help="Comma-separated list of service names to check (default: all).",
    )
    parser.add_argument(
        "--allow-exceptions-file",
        metavar="PATH",
        help="Path to exceptions YAML file (default: scripts/structure_checks/exceptions.yaml).",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    root = script_dir.parent.parent  # worldview/

    # Exceptions file
    if args.allow_exceptions_file:
        exceptions_file = Path(args.allow_exceptions_file)
    else:
        exceptions_file = script_dir / "exceptions.yaml"

    exceptions = _load_exceptions(exceptions_file)

    # Service filter
    service_filter = [s.strip() for s in args.services.split(",")] if args.services else None

    services = discover_services(root, service_filter)
    if not services:
        print("No services found under services/.", file=sys.stderr)
        return 2

    all_violations: list[Violation] = []
    all_expired_errors: list[str] = []

    for svc_dir in services:
        violations, expired_errors = validate_service(svc_dir, exceptions)
        all_violations.extend(violations)
        all_expired_errors.extend(expired_errors)

    # Build summary
    total = len(all_violations)
    expired_count = len(all_expired_errors)

    print(f"\n=== Service Structure Report ({len(services)} services checked) ===\n")

    if all_expired_errors:
        print(f"EXPIRED EXCEPTIONS ({expired_count}):")
        for e in all_expired_errors:
            print(f"  {e}")
        print()

    if all_violations:
        print(f"VIOLATIONS ({total}):")
        for v in all_violations:
            print(v)
        print()
    else:
        print("No violations found.\n")

    # JSON report
    report: dict[str, Any] = {
        "services_checked": len(services),
        "total_violations": total,
        "expired_exceptions": expired_count,
        "violations": [v.to_dict() for v in all_violations],
        "expired_exception_errors": all_expired_errors,
    }

    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))
        print(f"JSON report written to {report_path}")

    if args.strict and (total > 0 or expired_count > 0):
        print("=== FAILED (strict mode) ===")
        return 1

    if total > 0:
        print(f"=== {total} violation(s) found (run with --strict to fail CI) ===")
    else:
        print("=== PASSED ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
