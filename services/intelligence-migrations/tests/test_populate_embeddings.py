"""Unit tests for scripts/populate_embeddings.py provider selection + parsing.

These are pure-unit tests (no DB, no network): the HTTP round-trip is mocked so
we can assert (a) the correct provider endpoint/payload/headers are built and
(b) each provider's response shape is parsed into a 1024-dim vector.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# The embedding populator lives under scripts/ (not an installed package), so we
# load it by path into a module object we can patch.
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "populate_embeddings.py"
_spec = importlib.util.spec_from_file_location("populate_embeddings", _SCRIPT_PATH)
assert _spec and _spec.loader
populate_embeddings = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(populate_embeddings)


# Override the DB-backed autouse fixture from conftest.py — these are pure unit
# tests that never touch Postgres, so the session-wide alembic upgrade/downgrade
# must be a no-op here (otherwise setup fails with "connection refused").
@pytest.fixture(scope="session", autouse=True)
def run_migrations() -> None:  # type: ignore[override]
    yield


class _FakeResponse(io.BytesIO):
    """Minimal context-manager stand-in for urllib's HTTP response object."""

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _capture_request(response_body: dict) -> tuple[list[Any], Any]:
    """Patch urlopen to record the Request and return a canned JSON body."""
    captured: list[Any] = []

    def _fake_urlopen(req: Any, timeout: int = 0) -> _FakeResponse:
        captured.append(req)
        return _FakeResponse(json.dumps(response_body).encode())

    return captured, _fake_urlopen


def test_deepinfra_path_selected_when_api_key_present() -> None:
    """With an API key, embed_text POSTs the OpenAI /v1/embeddings shape + Bearer auth."""
    body = {"data": [{"embedding": [0.1] * populate_embeddings.EXPECTED_DIM, "index": 0}]}
    captured, fake = _capture_request(body)

    with (
        patch.object(populate_embeddings, "EMBEDDING_API_KEY", "sk-test"),
        patch.object(populate_embeddings, "EMBEDDING_BASE_URL", "https://api.deepinfra.com/v1/openai"),
        patch.object(populate_embeddings, "EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5"),
        patch("urllib.request.urlopen", fake),
    ):
        result = populate_embeddings.embed_text("owns: ownership relation")

    assert result is not None
    assert len(result) == populate_embeddings.EXPECTED_DIM

    req = captured[0]
    assert req.full_url == "https://api.deepinfra.com/v1/openai/v1/embeddings"
    assert req.headers["Authorization"] == "Bearer sk-test"
    payload = json.loads(req.data)
    assert payload == {"model": "BAAI/bge-large-en-v1.5", "input": ["owns: ownership relation"]}


def test_ollama_fallback_when_no_api_key() -> None:
    """Without an API key, embed_text POSTs the legacy Ollama /api/embeddings shape (no auth)."""
    body = {"embedding": [0.2] * populate_embeddings.EXPECTED_DIM}
    captured, fake = _capture_request(body)

    with (
        patch.object(populate_embeddings, "EMBEDDING_API_KEY", ""),
        patch.object(populate_embeddings, "EMBEDDING_BASE_URL", "http://ollama:11434"),
        patch.object(populate_embeddings, "EMBEDDING_MODEL", "bge-large:latest"),
        patch("urllib.request.urlopen", fake),
    ):
        result = populate_embeddings.embed_text("owns: ownership relation")

    assert result is not None
    assert len(result) == populate_embeddings.EXPECTED_DIM

    req = captured[0]
    assert req.full_url == "http://ollama:11434/api/embeddings"
    assert "Authorization" not in req.headers
    payload = json.loads(req.data)
    assert payload == {"model": "bge-large:latest", "prompt": "owns: ownership relation"}


@pytest.mark.parametrize(
    "body",
    [
        {"data": [{"embedding": [0.1] * 512, "index": 0}]},  # DeepInfra, wrong dim
        {"embedding": [0.1] * 512},  # Ollama, wrong dim
        {"data": []},  # DeepInfra, empty
        {},  # neither shape
    ],
)
def test_bad_dimension_or_shape_returns_none(body: dict) -> None:
    """Non-1024-dim or malformed responses yield None (non-blocking by design)."""
    _, fake = _capture_request(body)
    with (
        patch.object(populate_embeddings, "EMBEDDING_API_KEY", "sk-test"),
        patch("urllib.request.urlopen", fake),
    ):
        assert populate_embeddings.embed_text("x") is None


def test_network_failure_returns_none() -> None:
    """A network error is swallowed (returns None) so the init container never blocks."""

    def _boom(*_: object, **__: object) -> None:
        raise OSError("name or service not known")

    with (
        patch.object(populate_embeddings, "EMBEDDING_API_KEY", "sk-test"),
        patch("urllib.request.urlopen", _boom),
    ):
        assert populate_embeddings.embed_text("x") is None
