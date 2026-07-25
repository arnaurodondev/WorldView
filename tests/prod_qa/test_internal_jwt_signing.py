"""Unit tests for ``scripts/prod_qa/checks/internal_jwt_signing.py`` (BP-752).

Validates, without a live cluster:

1. The filesystem-scan-derived "should be configured" set (via the real repo
   tree checked out for this test run) matches the five services the BP-752
   investigation found — the same sanity-guard shape as
   ``tests/architecture/test_internal_jwt_signing_key_wiring.py``'s scanner
   regression test.
2. The Secret env-var naming convention helper produces the exact key names
   observed live during the investigation.
3. The PASS/FAIL decision logic in ``run()`` correctly classifies a
   populated key (long base64), an absent key (empty jsonpath result), and
   an empty-but-present key (short base64) — with ``H.kubectl`` mocked so no
   real cluster access is required.
"""

from __future__ import annotations

import pytest

from scripts.prod_qa import harness as H  # noqa: N812 (H is the harness module's own idiom — see harness.py callers)
from scripts.prod_qa.checks import internal_jwt_signing as ijs

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. Filesystem-scan sanity guard (real repo tree — no mocking)
# ---------------------------------------------------------------------------


def test_services_with_signing_key_field_finds_the_known_five() -> None:
    """The five services confirmed (via grep during the BP-752 investigation)
    to declare `internal_jwt_private_key` in their own config.py must all be
    found by the scanner. A regression here (e.g. a repo-layout change that
    breaks the `services/*/src/*/config.py` glob) would silently make every
    downstream check in this module a no-op — this test fails loudly instead.
    """
    expected = {
        "api-gateway",
        "content-ingestion",
        "knowledge-graph",
        "market-data",
        "market-ingestion",
        "portfolio",
    }
    found = set(ijs._services_with_signing_key_field())
    missing = expected - found
    assert not missing, f"scanner regression: expected {sorted(expected)} but missing {sorted(missing)}"


# ---------------------------------------------------------------------------
# 2. Secret env-var naming convention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("service", "expected_key"),
    [
        ("knowledge-graph", "KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY"),
        ("api-gateway", "API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY"),
        ("portfolio", "PORTFOLIO_INTERNAL_JWT_PRIVATE_KEY"),
        ("market-ingestion", "MARKET_INGESTION_INTERNAL_JWT_PRIVATE_KEY"),
    ],
)
def test_secret_env_var_name_matches_live_naming_convention(service: str, expected_key: str) -> None:
    """These exact key names were confirmed present/absent against the live
    cluster during the BP-752 investigation (`kubectl get secret ... -o
    jsonpath='{.data}'`) — a naming-convention typo here would make every
    check below silently query the wrong (always-empty) key and false-FAIL
    every service, including ones that are actually fine.
    """
    assert ijs._secret_env_var_name(service) == expected_key


# ---------------------------------------------------------------------------
# 3. PASS/FAIL decision logic (mocked H.kubectl — no cluster required)
# ---------------------------------------------------------------------------


def _ctx() -> H.Ctx:
    return H.Ctx(report=H.Report(quiet=True))


def test_run_passes_when_key_is_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    """A long base64 payload (real RS256 PEM shape) → PASS."""
    monkeypatch.setattr(ijs, "_services_with_signing_key_field", lambda: ["knowledge-graph"])
    monkeypatch.setattr(H, "kubectl", lambda args, timeout=60: (0, "x" * 2272))
    ctx = _ctx()
    ijs.run(ctx)
    assert ctx.report.rows[-1][2] == H.PASS


def test_run_fails_when_key_absent_from_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent key (jsonpath resolves to an empty string, exit code 0 —
    matches kubectl's actual observed behaviour for a missing data key, not
    an error) → hard FAIL. This is the exact BP-752 shape: portfolio and
    market-ingestion's secrets have NO INTERNAL_JWT_PRIVATE_KEY entry at all.
    """
    monkeypatch.setattr(ijs, "_services_with_signing_key_field", lambda: ["portfolio"])
    monkeypatch.setattr(H, "kubectl", lambda args, timeout=60: (0, ""))
    ctx = _ctx()
    ijs.run(ctx)
    assert ctx.report.rows[-1][2] == H.FAIL
    assert "ABSENT" in ctx.report.rows[-1][3]


def test_run_fails_when_key_present_but_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key that IS present in the Secret but holds an empty/short value
    (e.g. base64 of `SecretStr("")`) must ALSO fail — the zero-tolerance
    floor is deliberately conservative (a plausible RS256 PEM is always well
    over 1500 base64 chars), since both shapes reproduce the identical
    production bug (no usable signing key).
    """
    monkeypatch.setattr(ijs, "_services_with_signing_key_field", lambda: ["market-data"])
    monkeypatch.setattr(H, "kubectl", lambda args, timeout=60: (0, "'YQ=='"))  # base64("a"), quoted like real output
    ctx = _ctx()
    ijs.run(ctx)
    assert ctx.report.rows[-1][2] == H.FAIL


def test_run_warns_when_scanner_finds_no_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty scan result (repo layout changed, or run from the wrong cwd)
    must WARN — not silently report zero checks as if everything passed.
    """
    monkeypatch.setattr(ijs, "_services_with_signing_key_field", lambda: [])
    ctx = _ctx()
    ijs.run(ctx)
    assert ctx.report.rows[-1][2] == H.WARN


def test_run_checks_every_scanned_service_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mixed batch (one populated, one absent) must produce one row per
    service with the correct independent verdict — a shared-state bug could
    otherwise let one service's PASS mask another's FAIL.
    """
    monkeypatch.setattr(ijs, "_services_with_signing_key_field", lambda: ["knowledge-graph", "portfolio"])

    def fake_kubectl(args: str, timeout: int = 60) -> tuple[int, str]:
        if "KNOWLEDGE_GRAPH" in args:
            return 0, "x" * 2272
        return 0, ""

    monkeypatch.setattr(H, "kubectl", fake_kubectl)
    ctx = _ctx()
    ijs.run(ctx)
    statuses = {name.split(":")[0]: status for _, name, status, _ in ctx.report.rows}
    assert statuses["knowledge-graph"] == H.PASS
    assert statuses["portfolio"] == H.FAIL
