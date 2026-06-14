"""Unit tests for the learned routing classifier (PLAN-0111 C-2 / C-6).

These tests exercise ``LearnedRouter`` and its ``map_p_yield_to_tier`` mapping
WITHOUT the real sklearn artifact: a tiny stub model (a callable with
``predict_proba``) and a hand-written temp meta JSON let us assert the P→tier cut
points, the feature-order contract, the ambiguous-band flag, and the
never-raises failure policy in isolation.

We also assert the *shadow invariant* at the wiring level: the helper that runs
the shadow comparison only mutates the learned_* fields and never touches
``routing_tier`` / ``processing_path`` (the fields that control processing).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from nlp_pipeline.application.blocks.learned_routing import (
    LearnedRouter,
    map_p_yield_to_tier,
    subtitle_from_lede,
)
from nlp_pipeline.domain.enums import RoutingTier

pytestmark = pytest.mark.unit


# ── Test doubles ──────────────────────────────────────────────────────────────


class _StubModel:
    """Minimal sklearn-like model: returns a fixed P(yield) for the positive class."""

    def __init__(self, p_yield: float) -> None:
        self._p = p_yield

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        # sklearn shape: [[p_neg, p_pos]] per row. We echo back the configured p.
        n = x.shape[0]
        return np.tile([1.0 - self._p, self._p], (n, 1))


class _StubEmbedder:
    """Stub EmbeddingGemma adapter returning a fixed-dim zero vector (or raising)."""

    def __init__(self, dims: int = 4, *, raise_exc: bool = False, wrong_dim: bool = False) -> None:
        self._dims = dims
        self._raise = raise_exc
        self._wrong_dim = wrong_dim
        self.calls: list[tuple[list[str], int | None]] = []

    async def embed_for_classification(self, texts: list[str], *, dimensions: int | None = None) -> list[list[float]]:
        self.calls.append((texts, dimensions))
        if self._raise:
            raise RuntimeError("simulated DeepInfra failure")
        dim = 3 if self._wrong_dim else self._dims
        return [[0.0] * dim for _ in texts]


def _write_meta(tmp_path: Path, *, dims: int = 4, thr_extract: float = 0.55, thr_deep: float = 0.80) -> Path:
    """Write a meta JSON mirroring the production exporter's schema."""
    meta = {
        "embedding_model_id": "google/embeddinggemma-300m",
        "embedding_dims": dims,
        "structured_features": ["source_reliability", "recency", "document_type"],
        "n_structured_features": 3,
        "total_features": 3 + dims,
        "thr_extract": thr_extract,
        "thr_deep": thr_deep,
        "ambiguous_band": {
            "low": thr_extract - 0.10,
            "high": thr_extract + 0.10,
            "half_width": 0.10,
        },
        "training_rows": 100,
        "created_at": "2026-06-12",
    }
    path = tmp_path / "routing_classifier_meta.json"
    path.write_text(json.dumps(meta))
    return path


def _make_router(
    tmp_path: Path,
    *,
    p_yield: float,
    dims: int = 4,
    thr_extract: float = 0.55,
    thr_deep: float = 0.80,
    embedder: Any | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[LearnedRouter, _StubEmbedder]:
    """Construct a LearnedRouter with a stub model + meta + (stub) embedder.

    We patch ``joblib.load`` to return the stub model so no real artifact is read,
    and pass an explicit meta path.
    """
    meta_path = _write_meta(tmp_path, dims=dims, thr_extract=thr_extract, thr_deep=thr_deep)
    stub_embedder = embedder if embedder is not None else _StubEmbedder(dims=dims)

    import joblib  # type: ignore[import-untyped]

    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(joblib, "load", lambda _path: _StubModel(p_yield))
    # model_path is never actually read (joblib.load is patched), but must be a Path.
    router = LearnedRouter(stub_embedder, model_path=tmp_path / "x.joblib", meta_path=meta_path)
    return router, stub_embedder


# ── map_p_yield_to_tier ──────────────────────────────────────────────────────


def test_map_p_yield_to_tier_cut_points() -> None:
    """P→tier mapping: >= thr_deep → DEEP, >= thr_extract → MEDIUM, else LIGHT."""
    thr_extract, thr_deep = 0.55, 0.80
    assert map_p_yield_to_tier(0.95, thr_extract, thr_deep) == RoutingTier.DEEP
    assert map_p_yield_to_tier(0.80, thr_extract, thr_deep) == RoutingTier.DEEP  # boundary inclusive
    assert map_p_yield_to_tier(0.70, thr_extract, thr_deep) == RoutingTier.MEDIUM
    assert map_p_yield_to_tier(0.55, thr_extract, thr_deep) == RoutingTier.MEDIUM  # boundary inclusive
    assert map_p_yield_to_tier(0.40, thr_extract, thr_deep) == RoutingTier.LIGHT
    # SUPPRESS is never produced by the mapping.
    assert map_p_yield_to_tier(0.0, thr_extract, thr_deep) == RoutingTier.LIGHT


# ── propose: tier mapping end-to-end ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_maps_high_p_to_deep(tmp_path: Path) -> None:
    router, embedder = _make_router(tmp_path, p_yield=0.92)
    result = await router.propose(
        title="Apple beats earnings",
        subtitle="Record iPhone sales",
        structured_features={"source_reliability": 0.9, "recency": 0.8, "document_type": 0.7},
    )
    assert result is not None
    assert result.proposed_tier == RoutingTier.DEEP
    assert result.p_yield == pytest.approx(0.92)
    # 0.92 is above the band high (0.65) → not ambiguous.
    assert result.in_ambiguous_band is False
    # The embedder was called once with the dims from the meta.
    assert len(embedder.calls) == 1
    assert embedder.calls[0][1] == 4


@pytest.mark.asyncio
async def test_propose_maps_mid_p_to_medium_and_ambiguous(tmp_path: Path) -> None:
    router, _ = _make_router(tmp_path, p_yield=0.60, thr_extract=0.55, thr_deep=0.80)
    result = await router.propose(
        title="Some company news",
        subtitle=None,
        structured_features={"source_reliability": 0.5, "recency": 0.5, "document_type": 0.5},
    )
    assert result is not None
    assert result.proposed_tier == RoutingTier.MEDIUM
    # 0.60 is within band [0.45, 0.65] → ambiguous.
    assert result.in_ambiguous_band is True


@pytest.mark.asyncio
async def test_propose_maps_low_p_to_light(tmp_path: Path) -> None:
    router, _ = _make_router(tmp_path, p_yield=0.10)
    result = await router.propose(
        title="Trivial headline",
        subtitle=None,
        structured_features={"source_reliability": 0.2, "recency": 0.1, "document_type": 0.3},
    )
    assert result is not None
    assert result.proposed_tier == RoutingTier.LIGHT
    assert result.in_ambiguous_band is False


# ── propose: failure policy (never raises) ───────────────────────────────────


@pytest.mark.asyncio
async def test_propose_returns_none_on_embedding_failure(tmp_path: Path) -> None:
    """An embedding exception is swallowed and propose returns None (shadow safe)."""
    embedder = _StubEmbedder(raise_exc=True)
    router, _ = _make_router(tmp_path, p_yield=0.9, embedder=embedder)
    result = await router.propose(
        title="x",
        subtitle="y",
        structured_features={"source_reliability": 0.5, "recency": 0.5, "document_type": 0.5},
    )
    assert result is None


@pytest.mark.asyncio
async def test_propose_returns_none_on_dim_mismatch(tmp_path: Path) -> None:
    """A wrong embedding dimension is detected and returns None, not a bad row."""
    embedder = _StubEmbedder(dims=4, wrong_dim=True)  # returns 3-d, meta expects 4-d
    router, _ = _make_router(tmp_path, p_yield=0.9, embedder=embedder)
    result = await router.propose(
        title="x",
        subtitle="y",
        structured_features={"source_reliability": 0.5, "recency": 0.5, "document_type": 0.5},
    )
    assert result is None


# ── feature-order contract ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_builds_features_in_trained_order(tmp_path: Path) -> None:
    """The feature row is [structured in meta order..., embedding...].

    We capture the matrix passed to predict_proba by wrapping the stub model.
    """
    captured: dict[str, np.ndarray] = {}

    class _CapturingModel(_StubModel):
        def predict_proba(self, x: np.ndarray) -> np.ndarray:
            captured["x"] = x
            return super().predict_proba(x)

    meta_path = _write_meta(tmp_path, dims=4)
    import joblib  # type: ignore[import-untyped]

    mp = pytest.MonkeyPatch()
    mp.setattr(joblib, "load", lambda _p: _CapturingModel(0.9))
    router = LearnedRouter(_StubEmbedder(dims=4), model_path=tmp_path / "x.joblib", meta_path=meta_path)

    await router.propose(
        title="t",
        subtitle="s",
        structured_features={"document_type": 0.3, "source_reliability": 0.9, "recency": 0.6},
    )
    x = captured["x"]
    # 3 structured + 4 embedding = 7 columns.
    assert x.shape == (1, 7)
    # Structured features must appear in the meta's order:
    # [source_reliability, recency, document_type] = [0.9, 0.6, 0.3].
    assert list(x[0, :3]) == [0.9, 0.6, 0.3]
    mp.undo()


# ── config flag parsing ──────────────────────────────────────────────────────


def test_learned_router_mode_flag_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """NLP_PIPELINE_LEARNED_ROUTER_MODE parses off/shadow/live; default is off."""
    from nlp_pipeline.config import Settings

    # Required DB URLs so Settings() validates.
    monkeypatch.setenv("NLP_PIPELINE_DATABASE_URL", "postgresql+asyncpg://x/y")
    monkeypatch.setenv("NLP_PIPELINE_INTELLIGENCE_DATABASE_URL", "postgresql+asyncpg://x/y")

    monkeypatch.delenv("NLP_PIPELINE_LEARNED_ROUTER_MODE", raising=False)
    assert Settings().learned_router_mode == "off"

    monkeypatch.setenv("NLP_PIPELINE_LEARNED_ROUTER_MODE", "shadow")
    assert Settings().learned_router_mode == "shadow"

    monkeypatch.setenv("NLP_PIPELINE_LEARNED_ROUTER_MODE", "live")
    assert Settings().learned_router_mode == "live"

    monkeypatch.setenv("NLP_PIPELINE_LEARNED_ROUTER_MODE", "bogus")
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        Settings()


# ── shadow invariant: actual tier is NEVER changed ───────────────────────────


@pytest.mark.asyncio
async def test_shadow_path_leaves_actual_tier_unchanged(tmp_path: Path) -> None:
    """_run_learned_router_shadow only stamps learned_* — never routing_tier."""
    from types import SimpleNamespace
    from uuid import UUID

    from nlp_pipeline.domain.models import RoutingDecision
    from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
        ArticleProcessingConsumer,
    )

    router, _ = _make_router(tmp_path, p_yield=0.95)  # would map to DEEP

    # The static router put this article in MEDIUM — that MUST remain MEDIUM.
    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-000000000030"),
        doc_id=UUID("00000000-0000-0000-0000-000000000031"),
        routing_tier=RoutingTier.MEDIUM,
        composite_score=0.5,
        feature_scores={"source_reliability": 0.8, "recency": 0.6, "document_type": 0.7},
    )

    # Build a bare consumer instance (no __init__) and inject only what the
    # shadow helper needs. This isolates the method from Kafka/DB wiring.
    consumer = ArticleProcessingConsumer.__new__(ArticleProcessingConsumer)
    consumer._settings = SimpleNamespace(learned_router_mode="shadow")  # type: ignore[attr-defined]
    consumer._learned_router = router  # type: ignore[attr-defined]

    await consumer._run_learned_router_shadow(
        routing_decision=decision, doc_title="Some title", lede="Some lede sentence."
    )

    # The actual tier (controls processing) is UNCHANGED.
    assert decision.routing_tier == RoutingTier.MEDIUM
    assert decision.processing_path is None
    # The learned proposal (DEEP) is recorded on the separate shadow fields only.
    assert decision.learned_tier == RoutingTier.DEEP
    assert decision.learned_p_yield == pytest.approx(0.95)
    assert decision.learned_router_mode == "shadow"


@pytest.mark.asyncio
async def test_shadow_noop_when_mode_off(tmp_path: Path) -> None:
    """With mode=off the helper does nothing (no learned fields, no router call)."""
    from types import SimpleNamespace
    from uuid import UUID

    from nlp_pipeline.domain.models import RoutingDecision
    from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
        ArticleProcessingConsumer,
    )

    router, embedder = _make_router(tmp_path, p_yield=0.95)
    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-000000000032"),
        doc_id=UUID("00000000-0000-0000-0000-000000000033"),
        routing_tier=RoutingTier.LIGHT,
        composite_score=0.2,
        feature_scores={},
    )

    consumer = ArticleProcessingConsumer.__new__(ArticleProcessingConsumer)
    consumer._settings = SimpleNamespace(learned_router_mode="off")  # type: ignore[attr-defined]
    consumer._learned_router = router  # type: ignore[attr-defined]

    await consumer._run_learned_router_shadow(routing_decision=decision, doc_title="t", lede="l")

    assert decision.learned_tier is None
    assert decision.learned_router_mode is None
    # Router was never invoked.
    assert embedder.calls == []


# ── subtitle_from_lede parity (PLAN-0111 #33) ─────────────────────────────────
# These cases pin the runtime replica to the dataset definition in
# scripts/eval/routing_classifier_dataset.py::_subtitle_from_lede. If that
# function ever changes, BOTH must change together — a divergence reintroduces
# the train/serve skew documented in the 2026-06-13 audit.


def test_subtitle_from_lede_none_and_empty() -> None:
    """None / empty / blank ledes collapse to the empty string."""
    assert subtitle_from_lede(None) == ""
    assert subtitle_from_lede("") == ""


def test_subtitle_from_lede_collapses_whitespace_short() -> None:
    """A short lede is returned with all whitespace runs collapsed to single spaces."""
    assert subtitle_from_lede("  Apple   beat\n\tearnings.  ") == "Apple beat earnings."


def test_subtitle_from_lede_long_cuts_at_sentence_boundary() -> None:
    """Over 300 chars: cut at the last '. ' found in head[:300] when that index > 60."""
    # A first sentence that lands its ". " well past char 60 (so the > 60 guard
    # passes), followed by a long tail that pushes the total over 300 chars.
    first = "Lam Research raised its full-year revenue and margin target after the strong quarter. "
    assert first.index(". ") > 60  # guard: boundary must be beyond char 60
    long = first + ("filler word " * 40)  # well over 300 chars total
    out = subtitle_from_lede(long)
    # Cut at the last ". " within the first 300 chars -> keeps the first sentence.
    assert out == "Lam Research raised its full-year revenue and margin target after the strong quarter."
    assert out.endswith(".")
    assert len(out) <= 300


def test_subtitle_from_lede_long_hard_cut_when_no_early_boundary() -> None:
    """Over 300 chars with no '. ' boundary beyond char 60: hard-cut at 300."""
    long = "x" * 500  # no sentence boundary at all
    out = subtitle_from_lede(long)
    assert out == "x" * 300
    assert len(out) == 300


def test_subtitle_from_lede_json_envelope_passes_through_collapsed() -> None:
    """A JSON-envelope chunk-0 (the ~71% case) is NOT parsed/cleaned — only whitespace-collapsed.

    Faithful reproduction: training used the raw first-chunk envelope as the
    lede, so the runtime path must too (cleaning it would create a NEW skew).
    """
    envelope = '{"date": "2026-06-01",\n  "title": "Acme beats",\n  "body": "..."}'
    out = subtitle_from_lede(envelope)
    # Whitespace collapsed, braces/quotes/keys untouched (short -> returned as-is).
    assert out == '{"date": "2026-06-01", "title": "Acme beats", "body": "..."}'


@pytest.mark.asyncio
async def test_shadow_passes_nonempty_subtitle_when_lede_present(tmp_path: Path) -> None:
    """When a lede is supplied, the shadow router embeds 'title\\nsubtitle' (not title-only).

    This is the core train/serve-parity assertion: the embedder must receive the
    lede-derived subtitle appended to the title.
    """
    from types import SimpleNamespace
    from uuid import UUID

    from nlp_pipeline.domain.models import RoutingDecision
    from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
        ArticleProcessingConsumer,
    )

    router, embedder = _make_router(tmp_path, p_yield=0.70)
    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-000000000040"),
        doc_id=UUID("00000000-0000-0000-0000-000000000041"),
        routing_tier=RoutingTier.LIGHT,
        composite_score=0.3,
        feature_scores={"source_reliability": 0.8, "recency": 0.6, "document_type": 0.7},
    )

    consumer = ArticleProcessingConsumer.__new__(ArticleProcessingConsumer)
    consumer._settings = SimpleNamespace(learned_router_mode="shadow")  # type: ignore[attr-defined]
    consumer._learned_router = router  # type: ignore[attr-defined]

    await consumer._run_learned_router_shadow(
        routing_decision=decision,
        doc_title="Lam Research analyst target",
        lede="  Analysts raised the price target on strong demand.  ",
    )

    # Exactly one embed call; the text is 'title\nsubtitle' with the lede
    # whitespace-collapsed (NOT title-only). This proves the skew is closed.
    assert len(embedder.calls) == 1
    embedded_texts, _dims = embedder.calls[0]
    assert embedded_texts == ["Lam Research analyst target\nAnalysts raised the price target on strong demand."]
    # And the proposal was stamped (mid p_yield -> MEDIUM here).
    assert decision.learned_p_yield == pytest.approx(0.70)
