"""Unit tests for the GLiNER server bounded-memory guards (gliner OOM fix).

These cover the pure/isolatable helpers introduced to stop the anon-rss ramp
(glibc arena fragmentation) that OOMKilled the pod ~2.7x/hour:
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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
                    get=lambda *a, **k: lambda f: f, post=lambda *a, **k: lambda f: f
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


def test_batch_chars_guard_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch)
    # 0 (default) => pure count batching, guard never fires regardless of size.
    assert srv.GLINER_MAX_BATCH_CHARS == 0
    assert srv._would_exceed_batch_chars(7, 100_000, 100_000) is False


def test_batch_chars_guard_bounds_padded_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    # Budget is the padded-activation proxy = batch_size x longest-text-chars.
    srv = _load_server(monkeypatch, GLINER_MAX_BATCH_CHARS="20000")
    # Short texts: a full count batch fits (8 x 2000 = 16000 <= 20000).
    assert srv._would_exceed_batch_chars(7, 2000, 2000) is False
    # One long (4000-char) text pads the WHOLE batch to 4000: the 5th item
    # (group_size=4) makes 5 x 4000 = 20000 (ok), the 6th would make 24000 (over).
    assert srv._would_exceed_batch_chars(4, 4000, 4000) is False
    assert srv._would_exceed_batch_chars(5, 4000, 4000) is True


def test_batch_chars_guard_uses_max_not_sum(monkeypatch: pytest.MonkeyPatch) -> None:
    # A single long text among short ones must be modelled by the MAX (padding),
    # not the sum: seed short, adding one 4000-char text to a 6-item group makes
    # 7 x 4000 = 28000 > 20000 even though the char SUM is tiny.
    srv = _load_server(monkeypatch, GLINER_MAX_BATCH_CHARS="20000")
    assert srv._would_exceed_batch_chars(6, 10, 4000) is True


# ── Token-based activation budget (gliner OOM residual #2, 2026-07-25) ────────
# The chars proxy assumes chars-per-subword-token is ~constant, but financial
# text (tickers, EPS figures, filing IDs) subword-tokenizes ~3x denser than
# plain English for the SAME char count (measured live on the deployed
# tokenizer) — self-attention memory scales with subword tokens, not chars, so
# a batch can stay under GLINER_MAX_BATCH_CHARS yet still spike memory via
# token-dense text. GLINER_MAX_BATCH_TOKENS closes that gap.


def test_batch_tokens_guard_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch)
    assert srv.GLINER_MAX_BATCH_TOKENS == 0
    assert srv._would_exceed_batch_tokens(7, 100_000, 100_000) is False


def test_batch_tokens_guard_bounds_padded_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same shape as the chars guard, but in tokens: budget 2000, batch of 5 at
    # 400 tokens/text = 2000 (fits), the 6th would make 2400 (over).
    srv = _load_server(monkeypatch, GLINER_MAX_BATCH_TOKENS="2000")
    assert srv._would_exceed_batch_tokens(4, 400, 400) is False
    assert srv._would_exceed_batch_tokens(5, 400, 400) is True


def test_batch_tokens_guard_uses_max_not_sum(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch, GLINER_MAX_BATCH_TOKENS="2000")
    # One token-dense (1000-token) text among short ones pads the WHOLE batch:
    # adding it to a 6-item group makes 7 x 1000 = 7000 > 2000.
    assert srv._would_exceed_batch_tokens(6, 10, 1000) is True


def test_count_tokens_falls_back_to_chars_heuristic_without_tokenizer(monkeypatch: pytest.MonkeyPatch) -> None:
    # Before the model loads (or if the tokenizer attribute path ever breaks),
    # _count_tokens must still return a conservative (non-zero, bounded) estimate
    # rather than silently disabling the guard — chars // 3 matches the measured
    # worst-case dense-financial-text ratio (~3 chars/token).
    srv = _load_server(monkeypatch)
    assert srv._tokenizer is None
    assert srv._count_tokens("x" * 300) == 100
    assert srv._count_tokens("") == 1  # never zero — a zero max would defeat the guard


def test_count_tokens_uses_live_tokenizer_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch)

    class _FakeTokenizer:
        def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
            # Simulate token-dense financial text: ~1 token per 2 chars.
            return list(range(max(1, len(text) // 2)))

    monkeypatch.setattr(srv, "_tokenizer", _FakeTokenizer())
    assert srv._count_tokens("financial-dense-text") == len("financial-dense-text") // 2


def test_count_tokens_never_raises_on_tokenizer_error(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _load_server(monkeypatch)

    class _BrokenTokenizer:
        def encode(self, *a: object, **k: object) -> list[int]:
            raise RuntimeError("boom")

    monkeypatch.setattr(srv, "_tokenizer", _BrokenTokenizer())
    # Falls back to the chars heuristic instead of propagating the exception.
    assert srv._count_tokens("x" * 30) == 10


def test_queue_item_precomputes_token_len(monkeypatch: pytest.MonkeyPatch) -> None:
    # token_len is computed once at construction (post-truncation text), not
    # recomputed on every collector-loop scan of the deferred buffer.
    srv = _load_server(monkeypatch)
    fut: object = object()  # placeholder; token_len must not touch future
    item = srv._QueueItem("x" * 30, ["ORG"], 0.35, fut)  # type: ignore[arg-type]
    assert item.token_len == 10
