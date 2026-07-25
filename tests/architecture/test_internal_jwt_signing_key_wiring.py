"""Internal-JWT signing-key wiring completeness (BP-752, 2026-07-25).

BACKGROUND: a live-cluster audit found ``portfolio`` and ``market-ingestion``
silently signing HS256 "dev fallback" internal JWTs in production because
their ``internal_jwt_private_key`` config value was empty/unset, while the
internal APIs they call (e.g. ``market-data``) verify RS256 and reject
HS256 — 24h+ of 100% silent auth failure per call site, invisible because
each caller degrades gracefully (portfolio falls back to cost-basis
pricing, market-ingestion falls back to a static symbol universe) rather
than crashing or alerting.

Two DISTINCT gaps share this symptom and need two DISTINCT gates:

1. A service's code never wires up RS256 signing AT ALL (no
   ``internal_jwt_private_key``-shaped field in its own ``config.py``,
   despite minting outbound internal JWTs) — this is a static, source-only
   fact this test (``tests/architecture/``) can catch.
2. A service's code DOES declare the field, but the LIVE deployed k8s
   Secret never actually populates it — a runtime/ops fact that can only
   be checked against the live cluster, not source. That is
   ``scripts/prod_qa/checks/internal_jwt_signing.py`` (see its module
   docstring), the sibling check this test does not duplicate.

Following the BP-750 registry-completeness philosophy (see
``docs/BUG_PATTERNS.md`` BP-750 and this test's sibling
``test_model_registry_completeness.py``): do NOT trust a hand-maintained
list of "services that call out internally" — independently RE-DERIVE the
"makes outbound signed internal calls" set by AST-scanning every service's
own source for an import of the shared
``observability.internal_jwt.mint_internal_jwt`` helper (the single,
consistent minting path every current caller in this codebase already
uses — confirmed by investigation: ``content-ingestion``, ``knowledge-graph``,
``market-data``, ``market-ingestion``, and ``portfolio`` all import it),
then cross-check that set against a from-scratch AST scan of every
service's ``config.py`` for the ``internal_jwt_private_key`` field, rather
than iterating only the services the auditor happened to already know
about.

Known scope limitation (documented, not an oversight): a service that
mints outbound internal JWTs via some OTHER helper (i.e. never imports
``mint_internal_jwt``) would not be caught by this heuristic. No such
service exists in this codebase today (verified by grep across
``services/*/src`` during the BP-752 investigation); if one is added in
the future without going through the shared helper, extend
``_MINT_HELPER_MODULE``/``_MINT_HELPER_NAME`` detection accordingly rather
than silently trusting this test's current coverage.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_services,
    iter_py_files,
    scan_imports,
)

pytestmark = pytest.mark.unit

# The exact field name observed across every service that already wires this
# up correctly (market-ingestion, market-data, content-ingestion,
# knowledge-graph, api-gateway) — see each service's config.py.
_SIGNING_KEY_FIELD = "internal_jwt_private_key"

# The shared minting helper every current outbound caller in this codebase
# imports to sign its own X-Internal-JWT (see libs/observability/src/observability/internal_jwt.py).
_MINT_HELPER_MODULE = "observability.internal_jwt"
_MINT_HELPER_NAME = "mint_internal_jwt"


@dataclass(frozen=True)
class _ConfigFieldResult:
    present: bool
    file: str
    line: int | None


def _scan_config_for_signing_key_field(config_py: Path) -> _ConfigFieldResult:
    """AST-scan a service's config.py for a `Settings` class field named
    exactly ``internal_jwt_private_key`` (any type annotation/default —
    presence is what this test checks; the LIVE prod_qa check verifies the
    deployed value is actually populated).
    """
    if not config_py.exists():
        return _ConfigFieldResult(present=False, file=str(config_py), line=None)
    try:
        source = config_py.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return _ConfigFieldResult(present=False, file=str(config_py), line=None)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or "Settings" not in node.name:
            continue
        for item in node.body:
            if (
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and item.target.id == _SIGNING_KEY_FIELD
            ):
                return _ConfigFieldResult(present=True, file=str(config_py), line=item.lineno)
    return _ConfigFieldResult(present=False, file=str(config_py), line=None)


def _mints_outbound_internal_jwt(svc: ServiceInfo) -> tuple[bool, str, int]:
    """True if any non-test .py file under the service's package imports the
    shared ``mint_internal_jwt`` helper — i.e. this service signs its OWN
    outbound ``X-Internal-JWT`` tokens to call another service's internal
    endpoint (as opposed to only ever verifying incoming tokens, or
    forwarding an already-verified token it received).

    Returns (found, file, line) — file/line of the first match, for a
    readable violation message.
    """
    for py_file in iter_py_files(svc.pkg_dir):
        for rec in scan_imports(py_file):
            if rec.is_from and rec.module == _MINT_HELPER_MODULE and _MINT_HELPER_NAME in rec.names:
                return True, str(py_file.relative_to(svc.service_dir)), rec.line
    return False, "", 0


class TestInternalJwtSigningKeyWiring:
    def test_every_outbound_jwt_minting_service_declares_signing_key_field(self) -> None:
        """REG-CALLER-NO-KEY: a service that mints its own outbound internal
        JWTs must declare an ``internal_jwt_private_key`` field in its own
        config.py — otherwise its outbound calls have NO code path to ever
        sign a real RS256 token, and are permanently stuck on the HS256 dev
        fallback (which every RS256-verifying production callee rejects).

        This is exactly the "never wired up in code at all" class BP-752
        found in ``portfolio`` (fixed in the same change that added this
        test — see ``services/portfolio/src/portfolio/config.py``): four
        call sites (``current_price_client.py``, ``recent_prices_client.py``,
        ``brokerage_sync_worker.py``, ``portfolio_snapshot_worker.py``) each
        minted an HS256-only token via a hardcoded dev secret, with no
        ``private_key_pem`` parameter ever threaded through, because the
        config field to hold one didn't exist.
        """
        violations: list[ArchViolation] = []
        for svc in discover_services():
            mints, mint_file, mint_line = _mints_outbound_internal_jwt(svc)
            if not mints:
                continue
            config_py = svc.pkg_dir / "config.py"
            result = _scan_config_for_signing_key_field(config_py)
            if not result.present:
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=mint_file,
                        line=mint_line,
                        rule="REG-CALLER-NO-KEY",
                        detail=(
                            f"{svc.name} mints outbound internal JWTs (imports {_MINT_HELPER_NAME} "
                            f"at {mint_file}:{mint_line}) but its config.py "
                            f"({config_py.relative_to(svc.service_dir.parent.parent)}) has no "
                            f"`{_SIGNING_KEY_FIELD}` field — this service's outbound calls have NO "
                            f"code path to ever sign an RS256 token (BP-752)."
                        ),
                    )
                )
        assert_no_violations(violations, rule="REG-CALLER-NO-KEY")

    def test_signing_key_field_scan_finds_the_known_five_callers(self) -> None:
        """Sanity guard on the scanner itself (not a completeness assertion):
        confirms the AST scan actually detects the five services the BP-752
        investigation found minting outbound internal JWTs
        (content-ingestion, knowledge-graph, market-data, market-ingestion,
        portfolio) — so a scanner regression (e.g. a refactor that changes
        the import shape and silently breaks detection) fails loudly here
        rather than by this test suite quietly asserting nothing over an
        empty set. Extend this set if a new service starts minting outbound
        internal JWTs — do not delete entries just to make this pass; that
        would defeat its purpose as a scanner-health guard.
        """
        expected_minters = {
            "content-ingestion",
            "knowledge-graph",
            "market-data",
            "market-ingestion",
            "portfolio",
        }
        found_minters = {svc.name for svc in discover_services() if _mints_outbound_internal_jwt(svc)[0]}
        missing = expected_minters - found_minters
        assert not missing, (
            f"Scanner regression: expected {sorted(expected_minters)} to be detected as outbound "
            f"internal-JWT minters, but {sorted(missing)} were NOT found. Either the import shape "
            f"changed (update `_MINT_HELPER_MODULE`/`_MINT_HELPER_NAME` detection) or these "
            f"services genuinely stopped minting outbound JWTs (update this set, with a comment "
            f"citing the change)."
        )
        extra = found_minters - expected_minters
        assert not extra, (
            f"New outbound internal-JWT minter(s) detected: {sorted(extra)} — not a failure, but "
            f"this fixed expected-set MUST be updated (not silently ignored) so this sanity guard "
            f"keeps tracking reality. Add the new service to `expected_minters` above."
        )
