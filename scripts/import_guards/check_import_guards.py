#!/usr/bin/env python3
"""
Import Guard Engine — AST-based anti-pattern detector.

Scans Python files under services/ for forbidden import patterns defined in
rules.yaml.  Supports a baseline file for managing pre-existing violations and
an allowlist for approved exceptions.

Exit codes:
  0 — no violations (or all covered by baseline / allowlist)
  1 — violations found in strict mode
  2 — usage / configuration error
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# YAML loader (stdlib-only fallback)
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> Any:
    """Load a YAML file, falling back to json if yaml is unavailable."""
    try:
        import yaml  # type: ignore[import-untyped]

        with path.open() as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass
    # Minimal YAML fallback: only works for simple key-value and list structures.
    # For the real thing, install PyYAML.
    raise RuntimeError(f"PyYAML is not installed. Install it with: pip install pyyaml\n" f"Cannot load {path}")


# ---------------------------------------------------------------------------
# Violation dataclass
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    file: str
    line: int
    rule_id: str
    rule_description: str
    detail: str
    remediation: str

    def key(self) -> str:
        """Stable key for baseline deduplication."""
        return f"{self.file}:{self.line}:{self.rule_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "rule_id": self.rule_id,
            "rule_description": self.rule_description,
            "detail": self.detail,
            "remediation": self.remediation,
        }

    def __str__(self) -> str:
        return (
            f"  [{self.rule_id}] {self.file}:{self.line}\n"
            f"    {self.detail}\n"
            f"    Remediation: {self.remediation}"
        )


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


@dataclass
class Rule:
    id: str
    description: str
    message: str
    remediation: str
    forbidden_imports: list[str] = field(default_factory=list)
    # list of [module, name] pairs
    forbidden_from_imports: list[list[str]] = field(default_factory=list)
    # list of [module, attr] call patterns (module.attr(...))
    check_calls: list[list[str]] = field(default_factory=list)
    check_print: bool = False
    layer_rule: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Rule:
        return cls(
            id=d["id"],
            description=d.get("description", ""),
            message=d.get("message", ""),
            remediation=d.get("remediation", ""),
            forbidden_imports=d.get("forbidden_imports", []),
            forbidden_from_imports=d.get("forbidden_from_imports", []),
            check_calls=d.get("check_calls", []),
            check_print=d.get("check_print", False),
            layer_rule=d.get("layer_rule"),
        )


def load_rules(rules_file: Path) -> list[Rule]:
    data = _load_yaml(rules_file)
    return [Rule.from_dict(r) for r in data.get("rules", [])]


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


@dataclass
class AllowlistEntry:
    rule_id: str  # "*" means all rules
    path_pattern: str
    reason: str


def load_allowlist(allowlist_file: Path) -> list[AllowlistEntry]:
    if not allowlist_file.exists():
        return []
    data = _load_yaml(allowlist_file)
    return [
        AllowlistEntry(
            rule_id=e.get("rule_id", "*"),
            path_pattern=e.get("path", ""),
            reason=e.get("reason", ""),
        )
        for e in data.get("allowlist", [])
    ]


def is_allowlisted(
    rel_path: str,
    rule_id: str,
    allowlist: list[AllowlistEntry],
) -> bool:
    for entry in allowlist:
        if entry.rule_id not in ("*", rule_id):
            continue
        if fnmatch.fnmatch(rel_path, entry.path_pattern):
            return True
    return False


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


def load_baseline(baseline_file: Path) -> set[str]:
    """Return set of violation keys present in the baseline."""
    if not baseline_file.exists():
        return set()
    with baseline_file.open() as f:
        data = json.load(f)
    if isinstance(data, list):
        return set(data)
    return set(data.get("violations", []))


def save_baseline(baseline_file: Path, violations: list[Violation]) -> None:
    keys = sorted(v.key() for v in violations)
    baseline_file.parent.mkdir(parents=True, exist_ok=True)
    baseline_file.write_text(json.dumps({"violations": keys}, indent=2))


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------


class ImportVisitor(ast.NodeVisitor):
    """Walk an AST and collect all import statements and call sites."""

    def __init__(self) -> None:
        self.imports: list[tuple[int, str]] = []  # (line, module)
        self.from_imports: list[tuple[int, str, str]] = []  # (line, module, name)
        self.calls: list[tuple[int, str, str]] = []  # (line, module/attr, method)
        self.print_calls: list[int] = []  # lines with print()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append((node.lineno, alias.name))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self.from_imports.append((node.lineno, module, alias.name))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Pattern: module.attr() — e.g. uuid.uuid4(), datetime.utcnow()
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if isinstance(node.func.value, ast.Name):
                obj = node.func.value.id
                self.calls.append((node.lineno, obj, attr))
            elif isinstance(node.func.value, ast.Attribute):
                # e.g. datetime.datetime.utcnow()
                inner = node.func.value
                if isinstance(inner.value, ast.Name):
                    self.calls.append((node.lineno, f"{inner.value.id}.{inner.attr}", attr))
        # Pattern: bare print()
        elif isinstance(node.func, ast.Name) and node.func.id == "print":
            self.print_calls.append(node.lineno)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Single-file checker
# ---------------------------------------------------------------------------


def check_file(
    file_path: Path,
    rel_path: str,
    rules: list[Rule],
    allowlist: list[AllowlistEntry],
) -> list[Violation]:
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        return [
            Violation(
                file=rel_path,
                line=e.lineno or 0,
                rule_id="PARSE-ERROR",
                rule_description="Python syntax error",
                detail=str(e),
                remediation="Fix the syntax error first.",
            )
        ]

    visitor = ImportVisitor()
    visitor.visit(tree)

    violations: list[Violation] = []

    for rule in rules:
        # Skip rules with only layer_rule (handled by arch tests)
        if (
            not rule.forbidden_imports
            and not rule.forbidden_from_imports
            and not rule.check_calls
            and not rule.check_print
        ):
            continue

        if is_allowlisted(rel_path, rule.id, allowlist):
            continue

        def add(line: int, detail: str) -> None:
            violations.append(
                Violation(
                    file=rel_path,
                    line=line,
                    rule_id=rule.id,
                    rule_description=rule.description,
                    detail=detail,
                    remediation=rule.remediation.strip(),
                )
            )

        # Check forbidden bare imports: `import <module>`
        for line, module in visitor.imports:
            for forbidden in rule.forbidden_imports:
                if module == forbidden or module.startswith(forbidden + "."):
                    add(line, f"Forbidden import: `import {module}` (rule {rule.id})")

        # Check forbidden from-imports: `from <module> import <name>`
        for line, module, name in visitor.from_imports:
            for forbidden_mod, forbidden_name in rule.forbidden_from_imports:
                if module == forbidden_mod and (forbidden_name == "*" or name == forbidden_name):
                    add(line, f"Forbidden import: `from {module} import {name}` (rule {rule.id})")

        # Check forbidden call patterns: module.method(...)
        for line, obj, attr in visitor.calls:
            for call_mod, call_attr in rule.check_calls:
                if obj == call_mod and attr == call_attr:
                    add(line, f"Forbidden call: `{obj}.{attr}()` (rule {rule.id})")

        # Check print() calls
        if rule.check_print:
            for line in visitor.print_calls:
                add(line, f"Forbidden print() call (rule {rule.id}) — use structlog")

    return violations


# ---------------------------------------------------------------------------
# Directory scanner
# ---------------------------------------------------------------------------


def scan_services(
    root: Path,
    rules: list[Rule],
    allowlist: list[AllowlistEntry],
    service_filter: list[str] | None = None,
) -> list[Violation]:
    services_dir = root / "services"
    if not services_dir.is_dir():
        return []

    all_violations: list[Violation] = []

    # Directories to skip when walking service trees
    SKIP_DIRS = {".venv", "venv", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules", ".git"}

    for svc_dir in sorted(services_dir.iterdir()):
        if not svc_dir.is_dir():
            continue
        if service_filter and svc_dir.name not in service_filter:
            continue

        for py_file in sorted(svc_dir.rglob("*.py")):
            # Skip virtual environments, caches, etc.
            if any(part in SKIP_DIRS for part in py_file.parts):
                continue
            rel_path = str(py_file.relative_to(root))
            violations = check_file(py_file, rel_path, rules, allowlist)
            all_violations.extend(violations)

    return all_violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="AST-based import guard checker for shared library anti-patterns.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any violation not covered by baseline.",
    )
    parser.add_argument(
        "--baseline",
        metavar="PATH",
        help="Path to baseline JSON file (default: scripts/import_guards/baseline.json).",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Update (overwrite) the baseline with current violations.",
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
        "--rules",
        metavar="PATH",
        help="Path to rules YAML file (default: scripts/import_guards/rules.yaml).",
    )
    parser.add_argument(
        "--allowlist",
        metavar="PATH",
        help="Path to allowlist YAML file (default: scripts/import_guards/allowlist.yaml).",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    root = script_dir.parent.parent  # worldview/

    rules_file = Path(args.rules) if args.rules else script_dir / "rules.yaml"
    allowlist_file = Path(args.allowlist) if args.allowlist else script_dir / "allowlist.yaml"
    baseline_file = Path(args.baseline) if args.baseline else script_dir / "baseline.json"

    try:
        rules = load_rules(rules_file)
    except Exception as e:
        print(f"ERROR loading rules: {e}", file=sys.stderr)
        return 2

    try:
        allowlist = load_allowlist(allowlist_file)
    except Exception as e:
        print(f"ERROR loading allowlist: {e}", file=sys.stderr)
        return 2

    baseline = load_baseline(baseline_file)

    service_filter = [s.strip() for s in args.services.split(",")] if args.services else None

    all_violations = scan_services(root, rules, allowlist, service_filter)

    # Partition into: covered by baseline vs net-new
    baselined: list[Violation] = []
    net_new: list[Violation] = []
    for v in all_violations:
        if v.key() in baseline:
            baselined.append(v)
        else:
            net_new.append(v)

    print(f"\n=== Import Guard Report ({len(all_violations)} total violations) ===\n")

    if net_new:
        print(f"NET-NEW VIOLATIONS ({len(net_new)}) — these must be fixed:")
        for v in net_new:
            print(v)
            print()

    if baselined:
        print(f"BASELINED VIOLATIONS ({len(baselined)}) — tracked, must reduce to zero:")
        for v in baselined:
            print(f"  [{v.rule_id}] {v.file}:{v.line} — {v.detail[:80]}")
        print()

    if not all_violations:
        print("No violations found.\n")

    # Update baseline
    if args.update_baseline:
        save_baseline(baseline_file, all_violations)
        print(f"Baseline updated: {len(all_violations)} violations written to {baseline_file}")

    # JSON report
    report: dict[str, Any] = {
        "total_violations": len(all_violations),
        "net_new_violations": len(net_new),
        "baselined_violations": len(baselined),
        "violations": [v.to_dict() for v in all_violations],
        "net_new": [v.to_dict() for v in net_new],
    }

    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))
        print(f"JSON report written to {report_path}")

    if args.strict:
        if net_new:
            print(f"=== FAILED (strict mode): {len(net_new)} net-new violation(s) ===")
            return 1
        if baselined:
            # In strict mode, baselined violations are allowed (they must be fixed over time)
            # but we warn
            print(f"=== WARNING: {len(baselined)} baselined violation(s) remain — baseline must reach zero ===")

    if all_violations:
        print(f"=== {len(net_new)} net-new, {len(baselined)} baselined ===")
    else:
        print("=== PASSED ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
