"""Unit tests for the GLiNER server bounded-memory guards (gliner OOM fix).

These cover the pure/isolatable helpers introduced to stop the anon-rss ramp
(glibc arena fragmentation) that OOMKilled the pod ~2.7×/hour:
  - input char-cap truncation (bounds peak activation, prefix-preserving so
    entity offsets stay valid),
  - malloc_trim best-effort no-crash contract,
  - single-thread inference executor (one glibc arena).

Run: python -m pytest infra/gliner/test_memory_bounds.py
"""

from __future__ import annotations

import importlib
import os
import sys
import types

import pytest


def _load_server(monkeypatch: pytest.MonkeyPatch, **env: str):  # type: ignore[no-untyped-def]
    """Import server.py with a stubbed torch/gliner/fastapi/pydantic so the
    module loads without the heavy ML deps present."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    # Minimal stubs for the import-time dependencies.
    torch_stub = types.ModuleType("torch")
    torch_stub.set_num_threads = lambda n: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch_stub)

    for name in ("fastapi", "pydantic"):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            if name == "fastapi":
                mod.FastAPI = lambda *a, **k: types.SimpleNamespace(  # type: ignore[attr-defined]
                    get=lambda *a, **k: (lambda f: f), post=lambda *a, **k: (lambda f: f)
                )
                mod.Response = object  # type: ignore[attr-defined]
            if name == "pydantic":
                mod.BaseModel = object  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, name, mod)

    sys.path.insert(0, os.path.dirname(__file__))
    if "server" in sys.modules:
        del sys.modules["server"]
    return importlib.import_module("server")


def test_truncate_input_caps_length(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch, GLINER_MAX_INPUT_CHARS="10")
    long = "abcdefghijklmnopqrst"
    out = srv._truncate_input(long)
    assert out == "abcdefghij"
    # Prefix-preserving: the kept portion is identical, so char offsets align.
    assert long.startswith(out)


def test_truncate_input_passthrough_when_short(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch, GLINER_MAX_INPUT_CHARS="4000")
    assert srv._truncate_input("short text") == "short text"


def test_truncate_input_disabled_when_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch, GLINER_MAX_INPUT_CHARS="0")
    big = "x" * 100_000
    assert srv._truncate_input(big) == big


def test_malloc_trim_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch)
    # Must be a no-op-safe call regardless of libc availability.
    srv._malloc_trim()
    # Also safe when libc is unresolved.
    monkeypatch.setattr(srv, "_LIBC", None)
    srv._malloc_trim()


def test_single_thread_inference_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch)
    # One worker => one glibc arena for tensor allocations (fragmentation bound).
    assert srv._INFERENCE_EXECUTOR._max_workers == 1
