"""Unit tests for infra/synthetic/synthetic_monitor.py probes.

``synthetic_monitor.py`` is a standalone script (not a packaged library), so
it is loaded here via ``importlib`` from its file path rather than a normal
package import — there is no ``__init__.py``/pyproject for ``infra/synthetic``
to make it importable as ``synthetic_monitor`` on ``sys.path`` otherwise.

Focus: ``probe_eodhd_key`` (new — mirrors ``probe_deepinfra_key``'s pattern for
the shared EODHD_API_KEY, the same single-key fragility class that silently
killed the ML pipeline when the DeepInfra key rotated with no freshness probe).
A couple of ``probe_deepinfra_key`` regression tests are included too since no
test file previously existed for this module.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest

pytestmark = pytest.mark.unit

_MODULE_PATH = Path(__file__).resolve().parent.parent / "synthetic_monitor.py"


def _load_synthetic_monitor() -> ModuleType:
    """Import synthetic_monitor.py by file path (no package on sys.path)."""
    spec = importlib.util.spec_from_file_location("synthetic_monitor_under_test", _MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec so dataclasses/typing introspection
    # inside the module (if any) can resolve it by name.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sm() -> ModuleType:
    """Fresh module instance per test so module-level env-derived globals
    (EODHD_API_KEY, EODHD_USER_URL, ...) can be monkeypatched per test without
    leaking between tests."""
    return _load_synthetic_monitor()


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, handler: object) -> None:
    """Redirect every ``httpx.AsyncClient(...)`` construction to a client
    wired to ``handler`` via ``httpx.MockTransport``, without recursing —
    the replacement closes over the *real* AsyncClient class captured before
    any patching happens (patching ``httpx.AsyncClient`` with a lambda that
    itself calls ``httpx.AsyncClient(...)`` would otherwise self-reference and
    blow the stack)."""
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kw: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)),  # type: ignore[arg-type]
    )


class TestProbeEodhdKeyRegistration:
    def test_probe_eodhd_key_is_registered(self, sm: ModuleType) -> None:
        assert sm.probe_eodhd_key in sm.PROBES


class TestProbeEodhdKeySkip:
    async def test_no_key_configured_skips_as_success(self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty EODHD_API_KEY = probe returns immediately (treated as success)
        so non-ingestion environments don't false-alarm — mirrors
        probe_deepinfra_key's no-key-configured behavior."""
        monkeypatch.setattr(sm, "EODHD_API_KEY", "")

        def handler(_req: httpx.Request) -> httpx.Response:
            raise AssertionError("no HTTP call should be made when EODHD_API_KEY is empty")

        _patch_async_client(monkeypatch, handler)
        await sm.probe_eodhd_key()  # must not raise, must not call out


class TestProbeEodhdKeyDeadKey:
    @pytest.mark.parametrize("status_code", [401, 403])
    async def test_dead_key_raises_runtime_error(
        self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch, status_code: int
    ) -> None:
        """401/403 = the account key has been revoked/rotated — must raise a
        clear, actionable RuntimeError so synthetic_probe_success drops to 0
        and SyntheticProbeDown fires."""
        monkeypatch.setattr(sm, "EODHD_API_KEY", "dead-key-value")

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json={"error": "not authorized"})

        _patch_async_client(monkeypatch, handler)

        with pytest.raises(RuntimeError) as excinfo:
            await sm.probe_eodhd_key()

        message = str(excinfo.value)
        assert str(status_code) in message
        assert "dead/rotated" in message
        # The key value must never leak into the exception message.
        assert "dead-key-value" not in message


class TestProbeEodhdKeyHealthy:
    async def test_2xx_response_does_not_raise(self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sm, "EODHD_API_KEY", "live-key-value")

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"apiRequests": 100, "dailyRateLimit": 100_000})

        _patch_async_client(monkeypatch, handler)

        await sm.probe_eodhd_key()  # must not raise


class TestProbeEodhdKeyTransientError:
    async def test_5xx_raises_but_redacts_query_string(self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 5xx is a transient failure (self-heals next tick) — it must still
        raise so the probe is marked failed, but httpx's default
        HTTPStatusError message embeds the full request URL including the
        api_token query param, so the raised error must redact it."""
        monkeypatch.setattr(sm, "EODHD_API_KEY", "super-secret-token")

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        _patch_async_client(monkeypatch, handler)

        with pytest.raises(RuntimeError) as excinfo:
            await sm.probe_eodhd_key()

        message = str(excinfo.value)
        assert "500" in message
        # Key must never appear in the raised message (this is what a naive
        # `resp.raise_for_status()` without the redaction wrapper would leak,
        # since EODHD's auth scheme puts api_token in the query string).
        assert "super-secret-token" not in message
        # The raised RuntimeError must sever __cause__ (`from None`), not chain
        # the original httpx.HTTPStatusError (`from exc`) — that original
        # exception's `.request.url` DOES contain the live api_token, and this
        # RuntimeError is cached in module state for up to
        # EODHD_PROBE_MIN_INTERVAL_S. If some future log call ever serializes
        # the full exception chain (traceback, repr, APM integration) rather
        # than just str(exc), a chained __cause__ would still leak the key.
        assert excinfo.value.__cause__ is None


class TestProbeEodhdKeyHttpxLoggerSuppressed:
    """BP-728: httpx's own client logs every request at INFO —
    `logger.info('HTTP Request: %s %s ...', request.method, request.url, ...)`
    — and request.url's str() includes the full query string. Since
    probe_eodhd_key's EODHD auth scheme puts api_token in the query string
    (unlike probe_deepinfra_key's Authorization-header key), this log line
    would leak the live key to stdout/Loki on every real probe tick unless
    the "httpx" logger's level is raised above INFO. This must hold
    regardless of which outcome the probe check has (2xx, 401/403, or 5xx)."""

    async def test_no_log_record_anywhere_contains_the_key(
        self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(sm, "EODHD_API_KEY", "caplog-secret-token")

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"apiRequests": 1})

        _patch_async_client(monkeypatch, handler)

        # Capture every log record (this repo's root logger + the real
        # "httpx" logger, which basicConfig's handler would otherwise pass
        # through at INFO) at DEBUG so the assertion would actually catch a
        # regression if the level-raise in synthetic_monitor.py were removed.
        with caplog.at_level(0):
            await sm.probe_eodhd_key()

        for record in caplog.records:
            assert "caplog-secret-token" not in record.getMessage()

        # Confirm the specific mitigation is actually in place, not just that
        # this particular MockTransport-backed call happened not to log
        # (httpx's real client only logs via the "httpx" logger's effective
        # level, and synthetic_monitor.py explicitly raises it to WARNING).
        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


class TestProbeEodhdKeyThrottle:
    """EODHD bills 1 API call per request (unlike DeepInfra's free GET
    /models), so probe_eodhd_key throttles its own real HTTP calls to at most
    once per EODHD_PROBE_MIN_INTERVAL_S and replays the last outcome on ticks
    that fall inside that window."""

    async def test_second_call_within_interval_replays_cached_failure_without_new_request(
        self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sm, "EODHD_API_KEY", "dead-key")
        monkeypatch.setattr(sm, "EODHD_PROBE_MIN_INTERVAL_S", 900.0)
        call_count = 0

        def handler(_req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(403, json={"error": "forbidden"})

        _patch_async_client(monkeypatch, handler)

        with pytest.raises(RuntimeError):
            await sm.probe_eodhd_key()
        assert call_count == 1

        # Immediately calling again (well inside the 900s window) must NOT
        # trigger a second billed HTTP request — it replays the cached
        # RuntimeError instead.
        with pytest.raises(RuntimeError):
            await sm.probe_eodhd_key()
        assert call_count == 1

    async def test_call_after_interval_elapses_performs_new_request(
        self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sm, "EODHD_API_KEY", "live-key")
        monkeypatch.setattr(sm, "EODHD_PROBE_MIN_INTERVAL_S", 900.0)
        call_count = 0

        def handler(_req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={})

        _patch_async_client(monkeypatch, handler)

        await sm.probe_eodhd_key()
        assert call_count == 1

        # Force the throttle window to have elapsed by rewinding the
        # recorded last-check timestamp rather than sleeping in the test.
        monkeypatch.setattr(sm, "_eodhd_last_check_monotonic", sm._eodhd_last_check_monotonic - 1000.0)

        await sm.probe_eodhd_key()
        assert call_count == 2

    async def test_successful_recheck_clears_cached_error(
        self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A key that was dead and gets rotated back to life must stop
        raising once a real (post-throttle) check observes 2xx — the cached
        failure must not be replayed forever."""
        monkeypatch.setattr(sm, "EODHD_API_KEY", "was-dead-now-live")
        monkeypatch.setattr(sm, "EODHD_PROBE_MIN_INTERVAL_S", 900.0)
        status_to_return = 403

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(status_to_return, json={})

        _patch_async_client(monkeypatch, handler)

        with pytest.raises(RuntimeError):
            await sm.probe_eodhd_key()

        # Simulate the interval elapsing and the key having been fixed.
        monkeypatch.setattr(sm, "_eodhd_last_check_monotonic", sm._eodhd_last_check_monotonic - 1000.0)
        status_to_return = 200

        await sm.probe_eodhd_key()  # must not raise: cached error is cleared

    async def test_key_rotation_mid_window_bypasses_throttle(
        self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A live key rotation must never hide behind a stale cached success
        from the OLD key — changing EODHD_API_KEY's value forces an immediate
        real check even though the throttle window (900s) hasn't elapsed."""
        monkeypatch.setattr(sm, "EODHD_API_KEY", "old-healthy-key")
        monkeypatch.setattr(sm, "EODHD_PROBE_MIN_INTERVAL_S", 900.0)
        call_count = 0

        def handler(_req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(403, json={"error": "forbidden"})

        _patch_async_client(monkeypatch, handler)

        # First check with the (about to be rotated) old key succeeds.
        def ok_handler(_req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={})

        _patch_async_client(monkeypatch, ok_handler)
        await sm.probe_eodhd_key()
        assert call_count == 1

        # Rotate to a new (broken) key WITHOUT letting the throttle window
        # elapse. The bad key must be detected on the very next tick, not
        # masked by the old key's cached success for up to 15 more minutes.
        monkeypatch.setattr(sm, "EODHD_API_KEY", "new-broken-key")
        _patch_async_client(monkeypatch, handler)

        with pytest.raises(RuntimeError):
            await sm.probe_eodhd_key()
        assert call_count == 2  # a real check happened despite being inside the window


class TestProbeDeepinfraKeyRegression:
    """No test file previously existed for this module; a couple of
    regression tests for the pre-existing probe_deepinfra_key are included so
    this new test file gives the whole freshness-probe pattern coverage."""

    async def test_no_key_configured_skips_as_success(self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sm, "DEEPINFRA_API_KEY", "")

        def handler(_req: httpx.Request) -> httpx.Response:
            raise AssertionError("no HTTP call should be made when DEEPINFRA_API_KEY is empty")

        _patch_async_client(monkeypatch, handler)
        await sm.probe_deepinfra_key()

    @pytest.mark.parametrize("status_code", [401, 403])
    async def test_dead_key_raises_runtime_error(
        self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch, status_code: int
    ) -> None:
        monkeypatch.setattr(sm, "DEEPINFRA_API_KEY", "dead-key")

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json={"error": "unauthorized"})

        _patch_async_client(monkeypatch, handler)

        with pytest.raises(RuntimeError) as excinfo:
            await sm.probe_deepinfra_key()
        assert str(status_code) in str(excinfo.value)


class TestRunProbesIntegratesEodhd:
    async def test_run_probes_records_eodhd_failure_metric(
        self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end through run_probes(): a dead EODHD key must set the
        synthetic_probe_success{probe_name="probe_eodhd_key"} gauge to 0.0,
        which is exactly what SyntheticProbeDown's generic
        `synthetic_probe_success == 0` expression keys off of (no probe-name
        allowlist to update — confirmed generic)."""
        monkeypatch.setattr(sm, "EODHD_API_KEY", "dead-key")
        monkeypatch.setattr(sm, "DEEPINFRA_API_KEY", "")  # skip, keep this test isolated to EODHD
        monkeypatch.setattr(sm, "SYNTHETIC_JWT", "")
        monkeypatch.setattr(sm, "SYNTHETIC_PORTFOLIO_ID", "")

        def handler(req: httpx.Request) -> httpx.Response:
            if "internal-user" in str(req.url):
                return httpx.Response(403, json={"error": "forbidden"})
            # api_gateway_health / market_data_quote probes: return a benign
            # 5xx-free response so this test isolates the EODHD assertion.
            return httpx.Response(200, json={})

        _patch_async_client(monkeypatch, handler)
        # run_probes() pushes to the Pushgateway at the end — point it at an
        # address nothing is listening on and swallow the (logged) failure,
        # matching the module's own try/except around push_to_gateway.
        monkeypatch.setattr(sm, "PUSHGATEWAY_URL", "http://127.0.0.1:1")

        await sm.run_probes()

        value = sm.probe_success.labels(probe_name="probe_eodhd_key")._value.get()
        assert value == 0.0


class TestProbeEodhdKeyNetworkError:
    async def test_connect_error_propagates_without_leaking_key(
        self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A network-level failure (DNS, connection refused, timeout) is not
        an httpx.HTTPStatusError, so it bypasses the redaction wrapper
        entirely and propagates as-is into run_probes()'s log.error(...).
        httpx's transport-error exceptions do not embed the request URL/query
        string in their message (unlike HTTPStatusError), so no separate
        redaction is needed here — this test pins that assumption so a future
        httpx upgrade that changes this can't silently start leaking the key."""
        monkeypatch.setattr(sm, "EODHD_API_KEY", "network-error-secret-token")

        def handler(_req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        _patch_async_client(monkeypatch, handler)

        with pytest.raises(httpx.ConnectError) as excinfo:
            await sm.probe_eodhd_key()

        assert "network-error-secret-token" not in str(excinfo.value)


class TestProbeEodhdKeyRateLimit:
    async def test_429_raises_and_redacts_query_string(self, sm: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        """429 (EODHD quota/rate-limit exhaustion) falls through the same
        generic raise_for_status()-redaction path as any other non-401/403
        4xx/5xx — it must still raise (so the probe is marked failed) and
        still redact the query string."""
        monkeypatch.setattr(sm, "EODHD_API_KEY", "rate-limited-secret-token")

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        _patch_async_client(monkeypatch, handler)

        with pytest.raises(RuntimeError) as excinfo:
            await sm.probe_eodhd_key()

        message = str(excinfo.value)
        assert "429" in message
        assert "rate-limited-secret-token" not in message


class TestEodhdUserUrlEnvOverride:
    def test_env_override_is_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EODHD_USER_URL is read from the environment at import time
        (mirroring DEEPINFRA_MODELS_URL's existing pattern) so the probe
        target can be redirected per-environment without a code change."""
        monkeypatch.setenv("EODHD_USER_URL", "https://example.invalid/custom-user-endpoint")
        module = _load_synthetic_monitor()
        assert module.EODHD_USER_URL == "https://example.invalid/custom-user-endpoint"
