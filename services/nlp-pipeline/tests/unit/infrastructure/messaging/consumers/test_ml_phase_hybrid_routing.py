"""run_ml_phase hybrid extraction-model routing + provenance (2026-07-17).

Exercises Block 10 model selection end-to-end through ``run_ml_phase`` with the
novelty/resolution gates patched out, asserting:

  * SEC/long docs route to the high-recall (Qwen) client and disable the max_words cap.
  * Short docs route to the DeepSeek primary client.
  * A high-recall route with NO high-recall client falls back to the primary and
    stamps the primary slug (provenance stays truthful).
  * ``MLPhaseResult.extraction_model_id`` records the ACTUAL model used.
  * The fabrication-guard clients (entailment_client/config) are forwarded on BOTH
    routes — nothing bypasses the guards on the Qwen path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.blocks.suppression import ProcessingPath
from nlp_pipeline.config import Settings
from nlp_pipeline.infrastructure.messaging.consumers.blocks import ml_phase


@pytest.fixture
def _patched_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch Blocks 8/9 gates so only Block 10 (extraction) runs."""

    async def _passthrough_novelty(**kw: Any) -> tuple[Any, None]:
        return kw["routing_decision"], None

    monkeypatch.setattr(ml_phase, "run_novelty_gate", _passthrough_novelty)
    monkeypatch.setattr(ml_phase, "apply_suppression_gate", lambda rd: ProcessingPath.FULL_PIPELINE)
    monkeypatch.setattr(ml_phase, "should_run_entity_resolution", lambda _p: False)
    monkeypatch.setattr(ml_phase, "should_run_deep_extraction", lambda _p: True)
    monkeypatch.setattr(ml_phase, "synthesize_provisional_refs", AsyncMock(return_value=None))


async def _run(
    *,
    source_type: str,
    word_count: int,
    ext_high_recall: Any,
    settings: Settings,
) -> tuple[Any, dict[str, Any]]:
    """Invoke run_ml_phase with a capturing fake extraction fn; return (result, kwargs)."""
    captured: dict[str, Any] = {}

    async def _fake_extract(**kwargs: Any) -> tuple[dict[str, Any], list[Any]]:
        captured.update(kwargs)
        return {"events": [], "claims": [], "relations": []}, []

    primary_client = MagicMock(name="primary")
    entailment_client = MagicMock(name="entailment")
    entailment_config = MagicMock(name="entailment_config")

    result = await ml_phase.run_ml_phase(
        nlp_session=MagicMock(),
        intel_session=MagicMock(),
        doc_id=__import__("uuid").uuid4(),
        chunks=[MagicMock()],
        mentions=[],
        routing_decision=MagicMock(),
        initial_path=ProcessingPath.FULL_PIPELINE,
        published_at=None,
        extracted_at=__import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc),
        settings=settings,
        emb=MagicMock(),
        ext=primary_client,
        watchlist_client=MagicMock(),
        source_type=source_type,
        word_count=word_count,
        ext_model_id=settings.extraction_api_model_id,
        ext_high_recall=ext_high_recall,
        entailment_client=entailment_client,
        entailment_config=entailment_config,
        _deep_extraction_fn=_fake_extract,
    )
    captured["_primary_client"] = primary_client
    captured["_entailment_client"] = entailment_client
    captured["_entailment_config"] = entailment_config
    return result, captured


@pytest.fixture
def settings() -> Settings:
    s = Settings()  # type: ignore[call-arg]
    # Simulate prod: DeepSeek primary, Qwen high-recall, routing ON.
    s.extraction_api_model_id = "deepseek-ai/DeepSeek-V4-Flash"
    s.extraction_high_recall_model_id = "Qwen/Qwen3-235B-A22B-Instruct-2507"
    s.hybrid_extraction_routing_enabled = True
    s.extraction_high_recall_word_count_threshold = 6000
    s.extraction_high_recall_source_types = "sec_edgar"
    s.deep_extraction_max_words = 12000  # a non-zero cap, to prove it's disabled for Qwen
    return s


@pytest.mark.asyncio
async def test_sec_filing_routes_to_high_recall_client_and_disables_max_words(
    _patched_gates: None, settings: Settings
) -> None:
    high_recall = MagicMock(name="high_recall")
    result, cap = await _run(source_type="sec_edgar", word_count=100, ext_high_recall=high_recall, settings=settings)

    assert cap["extraction_client"] is high_recall
    assert cap["model_id"] == "Qwen/Qwen3-235B-A22B-Instruct-2507"
    assert cap["max_words"] == 0  # recall tax disabled on the Qwen filing path
    assert result.extraction_model_id == "Qwen/Qwen3-235B-A22B-Instruct-2507"


@pytest.mark.asyncio
async def test_large_article_routes_to_high_recall_via_word_count(_patched_gates: None, settings: Settings) -> None:
    high_recall = MagicMock(name="high_recall")
    result, cap = await _run(source_type="eodhd", word_count=8000, ext_high_recall=high_recall, settings=settings)

    assert cap["extraction_client"] is high_recall
    assert cap["model_id"] == "Qwen/Qwen3-235B-A22B-Instruct-2507"
    assert cap["max_words"] == 0
    assert result.extraction_model_id == "Qwen/Qwen3-235B-A22B-Instruct-2507"


@pytest.mark.asyncio
async def test_short_doc_routes_to_deepseek_primary_and_keeps_max_words(
    _patched_gates: None, settings: Settings
) -> None:
    high_recall = MagicMock(name="high_recall")
    result, cap = await _run(source_type="eodhd", word_count=300, ext_high_recall=high_recall, settings=settings)

    assert cap["extraction_client"] is cap["_primary_client"]
    assert cap["model_id"] == "deepseek-ai/DeepSeek-V4-Flash"
    assert cap["max_words"] == 12000  # short docs keep the configured cap
    assert result.extraction_model_id == "deepseek-ai/DeepSeek-V4-Flash"


@pytest.mark.asyncio
async def test_high_recall_route_without_client_falls_back_to_primary_and_stamps_primary(
    _patched_gates: None, settings: Settings
) -> None:
    # Routing WOULD pick high-recall (a filing), but no high-recall client is wired.
    result, cap = await _run(source_type="sec_edgar", word_count=100, ext_high_recall=None, settings=settings)

    assert cap["extraction_client"] is cap["_primary_client"]
    assert cap["model_id"] == "deepseek-ai/DeepSeek-V4-Flash"
    # max_words NOT force-disabled since the recall model did not actually serve it.
    assert cap["max_words"] == 12000
    assert result.extraction_model_id == "deepseek-ai/DeepSeek-V4-Flash"


@pytest.mark.asyncio
async def test_routing_disabled_forces_primary(_patched_gates: None, settings: Settings) -> None:
    settings.hybrid_extraction_routing_enabled = False
    high_recall = MagicMock(name="high_recall")
    result, cap = await _run(source_type="sec_edgar", word_count=100000, ext_high_recall=high_recall, settings=settings)

    assert cap["extraction_client"] is cap["_primary_client"]
    assert cap["model_id"] == "deepseek-ai/DeepSeek-V4-Flash"
    assert result.extraction_model_id == "deepseek-ai/DeepSeek-V4-Flash"


@pytest.mark.asyncio
async def test_guards_forwarded_on_both_routes(_patched_gates: None, settings: Settings) -> None:
    high_recall = MagicMock(name="high_recall")
    # Qwen (filing) path
    _, cap_hr = await _run(source_type="sec_edgar", word_count=100, ext_high_recall=high_recall, settings=settings)
    assert cap_hr["entailment_client"] is cap_hr["_entailment_client"]
    assert cap_hr["entailment_config"] is cap_hr["_entailment_config"]
    # DeepSeek (short) path
    _, cap_ds = await _run(source_type="eodhd", word_count=100, ext_high_recall=high_recall, settings=settings)
    assert cap_ds["entailment_client"] is cap_ds["_entailment_client"]
    assert cap_ds["entailment_config"] is cap_ds["_entailment_config"]
