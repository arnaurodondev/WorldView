"""Unit tests for ``scripts/prod_qa/checks/internal_auth.py``.

VALIDATION NOTE: this module WAS additionally validated live against the real
Hetzner cluster (KUBECONFIG=~/.kube/config-worldview was available in the
authoring environment) — all three probes in ``INTERNAL_AUTH_PROBES``
correctly returned FAIL (401) against the live, currently-broken
market-ingestion-scheduler / portfolio-snapshot-worker / content-ingestion
signers on 2026-07-25 (see the README "Internal-auth signer probes" section
for the transcript). These unit tests additionally pin the PASS/WARN/FAIL
decision logic and the probe-script templating with mocked `kubectl exec`
output, so the harness's behavior is covered without requiring a live cluster
on every CI run.
"""

from __future__ import annotations

import pytest

from scripts.prod_qa import harness as H  # noqa: N812 (H is the harness module's own idiom)
from scripts.prod_qa import thresholds as T  # noqa: N812 (matches the sibling test_duplicate_groups.py idiom)
from scripts.prod_qa.checks import internal_auth as ia
from scripts.prod_qa.harness import Ctx

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. INTERNAL_AUTH_PROBES shape validation (static — no cluster required)
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {
    "name",
    "caller_label",
    "key_env_var",
    "target_env_var",
    "target_default",
    "dev_secret",
    "sub",
    "path",
}


@pytest.mark.parametrize("probe", T.INTERNAL_AUTH_PROBES, ids=lambda p: p["name"])
def test_probe_spec_has_all_required_fields(probe: dict[str, str]) -> None:
    assert _REQUIRED_KEYS <= probe.keys()
    assert probe["caller_label"].startswith("app.kubernetes.io/name=")
    assert probe["target_default"].startswith("http://")
    assert probe["path"].startswith("/")


def test_probe_specs_cover_the_2026_07_23_incident_pair() -> None:
    """market-ingestion→market-data and portfolio→market-data (the two
    services confirmed 100%-401 for 24h+) MUST both be present — a probe list
    that silently dropped the incident pair would defeat the whole point.
    """
    names = {p["name"] for p in T.INTERNAL_AUTH_PROBES}
    assert "market-ingestion → market-data" in names
    assert "portfolio → market-data" in names


def test_probe_template_renders_without_placeholder_braces_left_over() -> None:
    """Every ``{...}`` field in the template must be consumed by .format() —
    a leftover placeholder would ship broken Python into the target pod.
    """
    probe = T.INTERNAL_AUTH_PROBES[0]
    rendered = ia._PROBE_TEMPLATE.format(
        key_env_var=probe["key_env_var"],
        target_env_var=probe["target_env_var"],
        target_default=probe["target_default"],
        sub=probe["sub"],
        dev_secret=probe["dev_secret"],
        path=probe["path"],
    )
    # No unresolved named placeholders (e.g. a literal "{key_env_var" left over
    # from a typo'd format spec) should survive .format() — the dict-literal
    # braces in the rendered script itself (`headers={...}`) are expected and
    # are not named placeholders, so we check for the field NAMES instead.
    for field in ("key_env_var", "target_env_var", "target_default", "sub", "dev_secret", "path"):
        assert f"{{{field}" not in rendered
    assert "mint_internal_jwt" in rendered
    assert probe["path"] in rendered


# ---------------------------------------------------------------------------
# 2. PASS/WARN/FAIL decision logic (mocked kubectl exec)
# ---------------------------------------------------------------------------


def _ctx() -> Ctx:
    return Ctx(report=H.Report(quiet=True))


def test_probe_200_is_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "running_pod", lambda label: "market-ingestion-scheduler-abc123")
    monkeypatch.setattr(H, "sh", lambda cmd, timeout=45: (0, "PQA_IA 200 True"))
    ctx = _ctx()
    ia._run_probe(ctx, T.INTERNAL_AUTH_PROBES[0])
    assert len(ctx.report.rows) == 1
    _, _name, status, detail = ctx.report.rows[0]
    assert status == H.PASS
    assert "200" in detail


@pytest.mark.parametrize("code", [401, 403])
def test_probe_401_403_is_fail(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    """This is the exact signature of the 2026-07-23 incident: the signer's
    own token is rejected by the target. Must FAIL, never WARN/PASS — a
    downgrade here would silently defeat the entire point of this check.
    """
    monkeypatch.setattr(H, "running_pod", lambda label: "portfolio-snapshot-worker-xyz")
    monkeypatch.setattr(
        H, "sh", lambda cmd, timeout=45: (0, f'PQA_IA {code} False {{"detail":"Invalid internal JWT"}}')
    )
    ctx = _ctx()
    ia._run_probe(ctx, T.INTERNAL_AUTH_PROBES[1])
    _, _name, status, detail = ctx.report.rows[0]
    assert status == H.FAIL
    assert str(code) in detail
    assert "REJECTED" in detail


def test_probe_no_pod_found_is_warn_not_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing pod (scaled to 0, mid-rollout) is inconclusive, not a proven
    auth break — must WARN, not FAIL (would false-page on a routine rollout).
    """
    monkeypatch.setattr(H, "running_pod", lambda label: "")
    ctx = _ctx()
    ia._run_probe(ctx, T.INTERNAL_AUTH_PROBES[0])
    _, _name, status, detail = ctx.report.rows[0]
    assert status == H.WARN
    assert "no Running pod" in detail


def test_probe_5xx_or_network_error_is_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "running_pod", lambda label: "content-ingestion-abc")
    monkeypatch.setattr(H, "sh", lambda cmd, timeout=45: (0, "PQA_IA 503 True"))
    ctx = _ctx()
    ia._run_probe(ctx, T.INTERNAL_AUTH_PROBES[2])
    _, _name, status, _detail = ctx.report.rows[0]
    assert status == H.WARN


def test_probe_unparseable_output_is_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "running_pod", lambda label: "market-ingestion-scheduler-abc123")
    monkeypatch.setattr(H, "sh", lambda cmd, timeout=45: (1, "Traceback: ModuleNotFoundError"))
    ctx = _ctx()
    ia._run_probe(ctx, T.INTERNAL_AUTH_PROBES[0])
    _, _name, status, detail = ctx.report.rows[0]
    assert status == H.WARN
    assert "inconclusive" in detail


def test_run_executes_every_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H, "running_pod", lambda label: "some-pod")
    monkeypatch.setattr(H, "sh", lambda cmd, timeout=45: (0, "PQA_IA 200 True"))
    ctx = _ctx()
    ia.run(ctx)
    assert len(ctx.report.rows) == len(T.INTERNAL_AUTH_PROBES)
    assert all(row[2] == H.PASS for row in ctx.report.rows)
