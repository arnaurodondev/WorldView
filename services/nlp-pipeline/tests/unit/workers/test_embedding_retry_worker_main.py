"""Construction tests for ``embedding_retry_worker_main`` (PLAN-0057 Wave C T-001).

Coverage targets:
  1. ``_build_embedding_client(settings)`` — provider selection + key fallback
     for ``deepinfra`` (with key), ``deepinfra`` (no key → ollama), ``jina``
     (with key), and the default ``ollama`` branch.
  2. ``main()`` emits the ``embedding_retry_abandoned_at_startup`` warning when
     ``EmbeddingPendingRepository.count_abandoned`` returns >0.
  3. ``main()`` emits NO warning when count_abandoned returns 0.
  4. ``main()`` exits with code 1 when ``_build_nlp_factories`` raises.
  5. ``main()`` awaits ``nlp_engine.dispose()`` on clean shutdown.

structlog is not bound to stdlib logging in unit-test runs so we monkey-patch
the local ``log = get_logger(...)`` reference by intercepting ``get_logger``
itself — the module rebinds it inside ``main()``.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_settings(
    *,
    provider: str = "ollama",
    embedding_api_key: str = "",
    jina_api_key: str = "",
) -> MagicMock:
    """Build a Settings stub carrying the fields ``main()`` reads."""
    s = MagicMock(name="Settings")
    s.log_level = "INFO"
    s.log_json = False
    s.embedding_provider = provider
    s.embedding_api_key = SecretStr(embedding_api_key)
    s.embedding_api_base_url = "https://api.deepinfra.com/v1/openai"
    s.embedding_api_model_id = "BAAI/bge-large-en-v1.5"
    s.jina_api_key = SecretStr(jina_api_key)
    s.ollama_base_url = "http://ollama:11434"
    s.embedding_model_id = "bge-large"
    s.embedding_instruction_prefix = "Represent this passage: "
    return s


def _make_session_factory(*, abandoned_count: int = 0) -> MagicMock:
    """Async-context-manager session factory whose repo returns *abandoned_count*."""

    @asynccontextmanager
    async def _ctx():
        yield AsyncMock(name="session")

    return MagicMock(side_effect=_ctx)


# ── _build_embedding_client provider matrix ──────────────────────────────────


class TestBuildEmbeddingClient:
    """Each branch of the provider/key dispatch must pick the right adapter."""

    def test_deepinfra_with_key_returns_deepinfra_adapter(self) -> None:
        from nlp_pipeline.workers import embedding_retry_worker_main as mod

        settings = _make_settings(provider="deepinfra", embedding_api_key="dk-test")
        adapter_cls = MagicMock(name="DeepInfraEmbeddingAdapter")
        adapter_cls.return_value = MagicMock(name="deepinfra_adapter")

        with patch.dict(
            "sys.modules",
            {
                "ml_clients.adapters.deepinfra_embedding": MagicMock(
                    DeepInfraEmbeddingAdapter=adapter_cls,
                ),
            },
        ):
            result = mod._build_embedding_client(settings)

        adapter_cls.assert_called_once_with(
            api_key="dk-test",
            model_id="BAAI/bge-large-en-v1.5",
            base_url="https://api.deepinfra.com/v1/openai",
        )
        assert result is adapter_cls.return_value

    def test_deepinfra_without_key_falls_back_to_ollama(self) -> None:
        """provider="deepinfra" + empty api_key must NOT call the DeepInfra
        adapter — it must fall through to the default Ollama branch."""
        from nlp_pipeline.workers import embedding_retry_worker_main as mod

        settings = _make_settings(provider="deepinfra", embedding_api_key="")
        deepinfra_cls = MagicMock(name="DeepInfraEmbeddingAdapter")
        ollama_cls = MagicMock(name="OllamaEmbeddingAdapter")
        ollama_cls.return_value = MagicMock(name="ollama_adapter")

        with patch.dict(
            "sys.modules",
            {
                "ml_clients.adapters.deepinfra_embedding": MagicMock(
                    DeepInfraEmbeddingAdapter=deepinfra_cls,
                ),
                "ml_clients.adapters.ollama_embedding": MagicMock(
                    OllamaEmbeddingAdapter=ollama_cls,
                ),
            },
        ):
            result = mod._build_embedding_client(settings)

        deepinfra_cls.assert_not_called()
        ollama_cls.assert_called_once()
        kwargs = ollama_cls.call_args.kwargs
        # base_url + model_id must be sourced from the ollama-side settings,
        # not the deepinfra-side ones — this is the contract that makes the
        # fallback safe (the API process applies the same logic).
        assert kwargs["base_url"] == "http://ollama:11434"
        assert kwargs["model_id"] == "bge-large"
        assert isinstance(kwargs["semaphore"], asyncio.Semaphore)
        assert result is ollama_cls.return_value

    def test_jina_with_key_returns_jina_adapter(self) -> None:
        from nlp_pipeline.workers import embedding_retry_worker_main as mod

        settings = _make_settings(provider="jina", jina_api_key="jk-test")
        jina_cls = MagicMock(name="JinaEmbeddingAdapter")
        jina_cls.return_value = MagicMock(name="jina_adapter")

        with patch.dict(
            "sys.modules",
            {
                "ml_clients.adapters.jina_embedding": MagicMock(
                    JinaEmbeddingAdapter=jina_cls,
                ),
            },
        ):
            result = mod._build_embedding_client(settings)

        jina_cls.assert_called_once_with(api_key="jk-test")
        assert result is jina_cls.return_value

    def test_default_ollama_branch(self) -> None:
        """provider="ollama" (or anything not deepinfra/jina) must build an
        OllamaEmbeddingAdapter wired to a fresh single-slot semaphore."""
        from nlp_pipeline.workers import embedding_retry_worker_main as mod

        settings = _make_settings(provider="ollama")
        ollama_cls = MagicMock(name="OllamaEmbeddingAdapter")
        ollama_cls.return_value = MagicMock(name="ollama_adapter")

        with patch.dict(
            "sys.modules",
            {
                "ml_clients.adapters.ollama_embedding": MagicMock(
                    OllamaEmbeddingAdapter=ollama_cls,
                ),
            },
        ):
            result = mod._build_embedding_client(settings)

        ollama_cls.assert_called_once()
        kwargs = ollama_cls.call_args.kwargs
        assert kwargs["base_url"] == "http://ollama:11434"
        assert kwargs["model_id"] == "bge-large"
        # Single-slot semaphore is the documented "don't contend with the API
        # process" contract — assert the value to lock that in.
        sem = kwargs["semaphore"]
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 1  # type: ignore[attr-defined]
        assert result is ollama_cls.return_value


# ── main() abandoned-count + lifecycle tests ─────────────────────────────────


@asynccontextmanager
async def _captured_log_calls():
    """Yield a (info_calls, warning_calls) pair to be used inside `main()` patch."""
    info: list[tuple[str, dict]] = []
    warning: list[tuple[str, dict]] = []
    yield info, warning


def _patch_main_dependencies(
    *,
    settings: MagicMock,
    nlp_engine: MagicMock,
    nlp_sf: MagicMock,
    abandoned_count: int,
    worker_cls: MagicMock,
    embedding_client: MagicMock,
    log_capture: MagicMock,
    factories_raise: bool = False,
):
    """Build the chain of patches main() relies on.

    Returns a list of context managers so the caller can ``ExitStack`` them.
    """
    repo_instance = MagicMock(name="EmbeddingPendingRepository_instance")
    repo_instance.count_abandoned = AsyncMock(return_value=abandoned_count)
    repo_cls = MagicMock(return_value=repo_instance)

    if factories_raise:
        factories_mock = MagicMock(side_effect=RuntimeError("boom"))
    else:
        factories_mock = MagicMock(
            return_value=(nlp_engine, MagicMock(), nlp_sf, MagicMock()),
        )

    return [
        patch("nlp_pipeline.config.Settings", return_value=settings, create=True),
        patch(
            "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
            factories_mock,
        ),
        patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ),
        patch(
            "nlp_pipeline.infrastructure.workers.embedding_retry_worker.EmbeddingRetryWorker",
            worker_cls,
        ),
        patch(
            "nlp_pipeline.workers.embedding_retry_worker_main._build_embedding_client",
            return_value=embedding_client,
        ),
        patch(
            "nlp_pipeline.workers.embedding_retry_worker_main.configure_logging",
            create=True,
        ),
        patch(
            "nlp_pipeline.workers.embedding_retry_worker_main.get_logger",
            return_value=log_capture,
        ),
    ]


def _make_log_capture(info: list, warning: list, error: list) -> MagicMock:
    log = MagicMock(name="logger")
    log.info = lambda event, **kw: info.append((event, kw))
    log.warning = lambda event, **kw: warning.append((event, kw))
    log.error = lambda event, **kw: error.append((event, kw))
    return log


def _make_worker_class(*, run_forever_side_effect=None) -> tuple[MagicMock, MagicMock]:
    worker_instance = MagicMock(name="EmbeddingRetryWorker_instance")
    if run_forever_side_effect is None:
        # Default: run_forever blocks until cancelled — mimic the real worker.
        async def _run(stop):
            await stop.wait()

        worker_instance.run_forever = AsyncMock(side_effect=_run)
    else:
        worker_instance.run_forever = AsyncMock(side_effect=run_forever_side_effect)
    worker_cls = MagicMock(return_value=worker_instance)
    return worker_cls, worker_instance


@pytest.mark.asyncio
async def test_main_emits_abandoned_warning_when_count_positive() -> None:
    """count_abandoned=7 must surface the operations warning at startup."""
    from nlp_pipeline.workers import embedding_retry_worker_main as mod

    settings = _make_settings()
    nlp_engine = MagicMock()
    nlp_engine.dispose = AsyncMock()
    nlp_sf = _make_session_factory()
    embedding_client = MagicMock(name="embedding_client")
    info: list[tuple[str, dict]] = []
    warning: list[tuple[str, dict]] = []
    error: list[tuple[str, dict]] = []
    log_capture = _make_log_capture(info, warning, error)
    worker_cls, _worker = _make_worker_class()

    # add_signal_handler is unsupported on pytest-asyncio's loop on macOS — stub it.
    loop = asyncio.get_running_loop()
    patches = _patch_main_dependencies(
        settings=settings,
        nlp_engine=nlp_engine,
        nlp_sf=nlp_sf,
        abandoned_count=7,
        worker_cls=worker_cls,
        embedding_client=embedding_client,
        log_capture=log_capture,
    )

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(patch.object(loop, "add_signal_handler", lambda *a, **k: None))

        # Schedule a stop_event.set() shortly after main() boots so it returns.
        async def _stop_after_boot():
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            # Find the stop event by reaching into the worker mock's last call.
            run_forever_call = worker_cls.return_value.run_forever.call_args
            if run_forever_call is not None:
                stop_event = run_forever_call.args[0]
                stop_event.set()

        stopper = asyncio.create_task(_stop_after_boot())
        try:
            await asyncio.wait_for(mod.main(), timeout=5.0)
        finally:
            stopper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stopper

    warning_events = [e for e, _ in warning]
    assert "embedding_retry_abandoned_at_startup" in warning_events
    abandoned_kw = next(kw for e, kw in warning if e == "embedding_retry_abandoned_at_startup")
    assert abandoned_kw["count"] == 7


@pytest.mark.asyncio
async def test_main_does_not_emit_warning_when_count_zero() -> None:
    """count_abandoned=0 must NOT emit the abandoned warning."""
    from nlp_pipeline.workers import embedding_retry_worker_main as mod

    settings = _make_settings()
    nlp_engine = MagicMock()
    nlp_engine.dispose = AsyncMock()
    nlp_sf = _make_session_factory()
    embedding_client = MagicMock(name="embedding_client")
    info: list[tuple[str, dict]] = []
    warning: list[tuple[str, dict]] = []
    error: list[tuple[str, dict]] = []
    log_capture = _make_log_capture(info, warning, error)
    worker_cls, _worker = _make_worker_class()

    loop = asyncio.get_running_loop()
    patches = _patch_main_dependencies(
        settings=settings,
        nlp_engine=nlp_engine,
        nlp_sf=nlp_sf,
        abandoned_count=0,
        worker_cls=worker_cls,
        embedding_client=embedding_client,
        log_capture=log_capture,
    )

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(patch.object(loop, "add_signal_handler", lambda *a, **k: None))

        async def _stop_after_boot():
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            run_forever_call = worker_cls.return_value.run_forever.call_args
            if run_forever_call is not None:
                stop_event = run_forever_call.args[0]
                stop_event.set()

        stopper = asyncio.create_task(_stop_after_boot())
        try:
            await asyncio.wait_for(mod.main(), timeout=5.0)
        finally:
            stopper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stopper

    warning_events = [e for e, _ in warning]
    assert "embedding_retry_abandoned_at_startup" not in warning_events


@pytest.mark.asyncio
async def test_main_exits_when_factories_raise() -> None:
    """A failure to build session factories must terminate with sys.exit(1)."""
    from nlp_pipeline.workers import embedding_retry_worker_main as mod

    settings = _make_settings()
    nlp_engine = MagicMock()
    nlp_engine.dispose = AsyncMock()
    nlp_sf = _make_session_factory()
    embedding_client = MagicMock(name="embedding_client")
    info: list[tuple[str, dict]] = []
    warning: list[tuple[str, dict]] = []
    error: list[tuple[str, dict]] = []
    log_capture = _make_log_capture(info, warning, error)
    worker_cls, _worker = _make_worker_class()

    loop = asyncio.get_running_loop()
    patches = _patch_main_dependencies(
        settings=settings,
        nlp_engine=nlp_engine,
        nlp_sf=nlp_sf,
        abandoned_count=0,
        worker_cls=worker_cls,
        embedding_client=embedding_client,
        log_capture=log_capture,
        factories_raise=True,
    )

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(patch.object(loop, "add_signal_handler", lambda *a, **k: None))

        with pytest.raises(SystemExit) as excinfo:
            await mod.main()

    assert excinfo.value.code == 1
    error_events = [e for e, _ in error]
    assert "embedding_retry_worker_startup_failed" in error_events


@pytest.mark.asyncio
async def test_main_disposes_engine_on_clean_shutdown() -> None:
    """nlp_engine.dispose() must be awaited as part of the shutdown sequence."""
    from nlp_pipeline.workers import embedding_retry_worker_main as mod

    settings = _make_settings()
    nlp_engine = MagicMock()
    nlp_engine.dispose = AsyncMock()
    nlp_sf = _make_session_factory()
    embedding_client = MagicMock(name="embedding_client")
    info: list[tuple[str, dict]] = []
    warning: list[tuple[str, dict]] = []
    error: list[tuple[str, dict]] = []
    log_capture = _make_log_capture(info, warning, error)
    worker_cls, _worker = _make_worker_class()

    loop = asyncio.get_running_loop()
    patches = _patch_main_dependencies(
        settings=settings,
        nlp_engine=nlp_engine,
        nlp_sf=nlp_sf,
        abandoned_count=0,
        worker_cls=worker_cls,
        embedding_client=embedding_client,
        log_capture=log_capture,
    )

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(patch.object(loop, "add_signal_handler", lambda *a, **k: None))

        async def _stop_after_boot():
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            run_forever_call = worker_cls.return_value.run_forever.call_args
            if run_forever_call is not None:
                stop_event = run_forever_call.args[0]
                stop_event.set()

        stopper = asyncio.create_task(_stop_after_boot())
        try:
            await asyncio.wait_for(mod.main(), timeout=5.0)
        finally:
            stopper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stopper

    nlp_engine.dispose.assert_awaited_once()
    info_events = [e for e, _ in info]
    assert "embedding_retry_worker_stopped" in info_events
