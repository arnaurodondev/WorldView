"""Unit tests for GenerateNarrativeUseCase (T-C-04).

Uses AsyncMock session factories — no live DB or LLM required.

Covered behaviours
------------------
- test_narrative_idempotency_same_snapshot: same snapshot → returns False, no write
- test_narrative_version_insert_sets_is_current: new snapshot → insert_and_promote called
- test_narrative_generation_publishes_outbox_event: outbox.append called with correct topic
- test_narrative_generation_emits_metrics: Prometheus labels increment on success
- test_health_score_formula_completeness_40_freshness_30_density_30: formula coefficients
- test_narrative_llm_failure_falls_back_to_template_v1: LLM exception → template-v1 path
- test_narrative_inputs_sanitized_before_llm_call: sanitize_description called for name+type
- test_narrative_concurrent_insert_handles_partial_unique_violation: DB error propagates
- test_narrative_word_count_set_correctly: word_count matches split() length
- test_narrative_input_snapshot_deterministic: same ctx → same hash (deterministic)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# ── Test fixtures ─────────────────────────────────────────────────────────────

_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000011")
_ENTITY_NAME = "Apple Inc."
_ENTITY_TYPE = "financial_instrument"
_NARRATIVE_TEXT = "A" * 100  # 100 chars — above minimum

_AVSC_PATH = "/fake/entity.narrative.generated.v1.avsc"


def _make_entity_ctx(
    entity_name: str = _ENTITY_NAME,
    entity_type: str = _ENTITY_TYPE,
    relations: list | None = None,
    contradictions: list | None = None,
) -> dict:
    return {
        "entity": {
            "entity_id": str(_ENTITY_ID),
            "canonical_name": entity_name,
            "entity_type": entity_type,
            "metadata": {},
        },
        "relations": relations or [],
        "articles": [],
        "contradictions": contradictions or [],
    }


def _make_session_factory(entity_ctx: dict | None = None, existing_version=None) -> MagicMock:
    """Mock async_sessionmaker.

    The returned factory's sessions emit the entity_ctx via execute().
    NarrativeRepository methods are patched separately.
    """
    session = AsyncMock()
    session.commit = AsyncMock()

    if entity_ctx is not None:
        entity = entity_ctx["entity"]
        # Mock execute to return entity row + empty relations + empty contradictions
        entity_row = MagicMock()
        entity_row.__getitem__ = lambda self_, k: [
            entity["entity_id"],
            entity["canonical_name"],
            entity["entity_type"],
            entity["metadata"],
        ][k]

        entity_result = MagicMock()
        entity_result.fetchone.return_value = entity_row

        relations_result = MagicMock()
        relations_result.fetchall.return_value = []

        contra_result = MagicMock()
        contra_result.fetchall.return_value = []

        call_counter = {"n": 0}

        async def _execute(*args, **kwargs):
            n = call_counter["n"]
            call_counter["n"] += 1
            if n == 0:
                return entity_result
            if n == 1:
                return relations_result
            return contra_result

        session.execute = AsyncMock(side_effect=_execute)
    else:
        # Entity not found
        empty_result = MagicMock()
        empty_result.fetchone.return_value = None
        session.execute = AsyncMock(return_value=empty_result)

    sf = MagicMock()
    sf.return_value.__aenter__ = AsyncMock(return_value=session)
    sf.return_value.__aexit__ = AsyncMock(return_value=False)
    return sf


def _make_use_case(
    entity_ctx: dict | None = None,
    existing_version=None,
    llm_text: str | None = None,
    llm_error: Exception | None = None,
    outbox_schema_path: str = _AVSC_PATH,
) -> tuple:
    """Construct a GenerateNarrativeUseCase with all externals mocked.

    Returns (use_case, write_sf, read_sf, narrative_repo_mock, outbox_repo_mock)

    retry_delays:
      - LLM success path (llm_text set): (0.0,) — one attempt, no sleep
      - LLM failure path (llm_error set): (0.0,) — one attempt raises immediately
      - No LLM (both None): () — forces template-v1 without any LLM attempt
    """
    from knowledge_graph.application.use_cases.generate_narrative import GenerateNarrativeUseCase

    read_sf = _make_session_factory(entity_ctx)
    write_sf = _make_session_factory(entity_ctx)

    narrative_repo_mock = AsyncMock()
    narrative_repo_mock.find_by_input_snapshot = AsyncMock(return_value=existing_version)
    narrative_repo_mock.insert_and_promote = AsyncMock()

    outbox_repo_mock = AsyncMock()
    outbox_repo_mock.append = AsyncMock()

    if llm_text is not None:
        llm = AsyncMock()
        llm_result = MagicMock()
        # PLAN-0087 D-R3-NARR (2026-05-09): the use case reads
        # ``ExtractionOutput.raw_response`` (the actual dataclass field).
        # Earlier tests set ``.output`` which silently wrote to a MagicMock
        # attribute that didn't exist on the real dataclass, masking the
        # bug for weeks (see commit 1ef95ee9). Pin to the real field name.
        llm_result.raw_response = llm_text
        llm.extract = AsyncMock(return_value=llm_result)
        retry_delays: tuple[float, ...] = (0.0,)  # one attempt, zero sleep
    elif llm_error is not None:
        llm = AsyncMock()
        llm.extract = AsyncMock(side_effect=llm_error)
        retry_delays = (0.0,)  # one attempt, raises → template fallback
    else:
        llm = None  # forces template-v1 path — no retry loop needed
        retry_delays = ()

    # Build mock repo *classes* (callables that return the mock instances).
    # Pass them as narrative_repo_class / outbox_repo_class so the use case
    # never imports from infrastructure/ (R12 / LAYER-BOUNDARY rule).
    # Using MagicMock(return_value=...) lets the use case call the class with
    # a session arg and get back the pre-built mock repo instance.
    narr_repo_cls = MagicMock(return_value=narrative_repo_mock)
    outbox_repo_cls = MagicMock(return_value=outbox_repo_mock)

    uc = GenerateNarrativeUseCase(
        write_session_factory=write_sf,
        read_session_factory=read_sf,
        narrative_llm_model_id="meta-llama/Meta-Llama-3.1-8B-Instruct",
        outbox_schema_path=outbox_schema_path,
        retry_delays=retry_delays,
        llm_client=llm,
        narrative_repo_class=narr_repo_cls,
        outbox_repo_class=outbox_repo_cls,
    )
    return uc, write_sf, read_sf, narrative_repo_mock, outbox_repo_mock


# ── Tests ──────────────────────────────────────────────────────────────────────

_SANITIZE = "prompts.knowledge.alias.sanitize_description"
_SERIALIZE = "messaging.kafka.serialization_utils.serialize_confluent_avro"


class TestNarrativeIdempotency:
    def test_narrative_idempotency_same_snapshot(self) -> None:
        """Same input_snapshot → returns False and never calls insert_and_promote."""
        from knowledge_graph.domain.narrative import EntityNarrativeVersion, NarrativeGenerationReason

        existing = EntityNarrativeVersion(
            version_id=UUID("00000000-0000-0000-0000-000000000001"),
            entity_id=_ENTITY_ID,
            narrative_text=_NARRATIVE_TEXT,
            model_id="meta-llama/Meta-Llama-3.1-8B-Instruct",
            generation_reason=NarrativeGenerationReason.INITIAL,
            input_snapshot={"_hash": "abc"},
            generated_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

        ctx = _make_entity_ctx()
        uc, _write_sf, _read_sf, narr_repo, outbox_repo = _make_use_case(
            entity_ctx=ctx,
            existing_version=existing,
        )

        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            result = asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))

        assert result is False
        narr_repo.insert_and_promote.assert_not_awaited()
        outbox_repo.append.assert_not_awaited()

    def test_narrative_template_v1_existing_does_not_skip(self) -> None:
        """Existing version with model_id='template-v1' must NOT trigger idempotent skip.

        SA-2 regression test (2026-05-10): entities with no relations produce an
        identical snapshot on every run.  Before this fix, ``find_by_input_snapshot``
        returning a template-v1 row caused the use case to skip LLM generation
        permanently — these entities were stuck on the placeholder forever.
        """
        from knowledge_graph.domain.narrative import EntityNarrativeVersion, NarrativeGenerationReason

        # Simulate a prior template-v1 version with the same snapshot hash.
        existing_template = EntityNarrativeVersion(
            version_id=UUID("00000000-0000-0000-0000-000000000002"),
            entity_id=_ENTITY_ID,
            narrative_text="[template-v1] SomeEntity: financial_instrument with 0 known relations.",
            model_id="template-v1",
            generation_reason=NarrativeGenerationReason.INITIAL,
            input_snapshot={"_hash": "abc"},
            generated_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

        ctx = _make_entity_ctx()
        # Provide a valid LLM response so the use case can produce a real narrative.
        uc, _write_sf, _read_sf, narr_repo, outbox_repo = _make_use_case(
            entity_ctx=ctx,
            llm_text="A" * 100,  # valid LLM narrative
            existing_version=existing_template,
        )

        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            result = asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="PERIODIC_REFRESH"))

        # Must proceed to LLM — template-v1 prior does NOT count as idempotent hit.
        assert result is True
        narr_repo.insert_and_promote.assert_awaited_once()
        outbox_repo.append.assert_awaited_once()
        # Verify the generated version uses the LLM model, not template fallback.
        generated_version = narr_repo.insert_and_promote.call_args.args[0]
        assert generated_version.model_id != "template-v1"

    def test_narrative_input_snapshot_deterministic(self) -> None:
        """Same entity context always produces the same snapshot hash (deterministic)."""
        from knowledge_graph.application.use_cases.generate_narrative import GenerateNarrativeUseCase

        ctx = _make_entity_ctx()
        uc = GenerateNarrativeUseCase.__new__(GenerateNarrativeUseCase)

        snap1, hash1 = uc._build_snapshot(ctx)
        snap2, hash2 = uc._build_snapshot(ctx)

        assert hash1 == hash2
        assert snap1["_hash"] == snap2["_hash"]
        assert snap1["_hash"] == hash1


class TestNarrativePersistence:
    def test_narrative_version_insert_sets_is_current(self) -> None:
        """New snapshot → insert_and_promote called exactly once."""
        ctx = _make_entity_ctx()
        uc, _write_sf, _read_sf, narr_repo, _outbox_repo = _make_use_case(entity_ctx=ctx)

        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            result = asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))

        assert result is True
        narr_repo.insert_and_promote.assert_awaited_once()
        # The version passed to insert_and_promote should have entity_id set
        call_args = narr_repo.insert_and_promote.call_args
        version = call_args.args[0]
        assert version.entity_id == _ENTITY_ID

    def test_narrative_generation_publishes_outbox_event(self) -> None:
        """outbox.append must be called with the narrative topic."""
        ctx = _make_entity_ctx()
        uc, _write_sf, _read_sf, _narr_repo, outbox_repo = _make_use_case(entity_ctx=ctx)

        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))

        outbox_repo.append.assert_awaited_once()
        call_kwargs = outbox_repo.append.call_args.kwargs
        assert call_kwargs["topic"] == "entity.narrative.generated.v1"
        assert call_kwargs["partition_key"] == str(_ENTITY_ID)
        # Regression for Final-QA-NEW: outbox.append requires keyword-only
        # event_id (R6 idempotency). Worker crashed 73x per 15-min window
        # before this kwarg was wired through.
        assert "event_id" in call_kwargs, "outbox.append must receive event_id kwarg"
        assert isinstance(call_kwargs["event_id"], UUID)

    def test_narrative_word_count_set_correctly(self) -> None:
        """word_count on the persisted EntityNarrativeVersion matches len(text.split())."""
        ctx = _make_entity_ctx()
        # LLM returns a text with a known word count
        llm_text = "This is a test narrative with exactly eight words here."  # 10 words
        uc, _write_sf, _read_sf, narr_repo, _outbox_repo = _make_use_case(
            entity_ctx=ctx,
            llm_text=llm_text,
        )

        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))

        version = narr_repo.insert_and_promote.call_args.args[0]
        assert version.word_count == len(llm_text.split())


class TestNarrativeMetrics:
    def test_narrative_generation_emits_metrics(self) -> None:
        """Prometheus counter and histogram are incremented on success."""
        from knowledge_graph.application.use_cases import generate_narrative as _mod

        ctx = _make_entity_ctx()
        uc, _write_sf, _read_sf, _narr_repo, _outbox_repo = _make_use_case(entity_ctx=ctx)

        counter_mock = MagicMock()
        histogram_mock = MagicMock()

        with (
            patch.object(_mod, "_narrative_total", counter_mock),
            patch.object(_mod, "_narrative_duration", histogram_mock),
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))

        # Counter labelled with reason + model_id + "success" must be incremented
        counter_mock.labels.assert_called()
        histogram_mock.observe.assert_called()


class TestNarrativeHealthScore:
    def test_health_score_formula_completeness_40_freshness_30_density_30(self) -> None:
        """Health score = completeness*0.4 + freshness*0.3 + density*0.3."""
        from knowledge_graph.application.use_cases.generate_narrative import GenerateNarrativeUseCase

        uc = GenerateNarrativeUseCase.__new__(GenerateNarrativeUseCase)

        # completeness = 1.0 (both name and type present)
        # freshness = 0.0 (no evidence timestamps)
        # density = 0.0 (0 relations)
        ctx_no_rels = _make_entity_ctx()
        score = uc._compute_health_score(ctx_no_rels)
        expected = 1.0 * 0.4 + 0.0 * 0.3 + 0.0 * 0.3
        assert abs(score - expected) < 1e-9, f"Expected {expected}, got {score}"

    def test_health_score_density_component_caps_at_one(self) -> None:
        """density = min(len(relations)/20, 1.0) — capped at 1.0 for 20+ relations."""
        from knowledge_graph.application.use_cases.generate_narrative import GenerateNarrativeUseCase

        uc = GenerateNarrativeUseCase.__new__(GenerateNarrativeUseCase)

        # 25 relations → density = 1.0 (capped)
        relations = [
            {
                "relation_id": f"r{i}",
                "canonical_type": "mentions",
                "confidence": 0.8,
                "evidence_count": 1,
                "latest_evidence_at": None,
                "object_name": "Other",
                "top_snippet": "",
            }
            for i in range(25)
        ]
        ctx = _make_entity_ctx(relations=relations)
        score = uc._compute_health_score(ctx)
        # density = min(25/20, 1.0) = 1.0
        expected_density = 1.0
        # freshness = 0 (no timestamps), completeness = 1.0
        expected = 1.0 * 0.4 + 0.0 * 0.3 + expected_density * 0.3
        assert abs(score - expected) < 1e-9


class TestNarrativeLLMFallback:
    def test_narrative_llm_failure_falls_back_to_template_v1(self) -> None:
        """LLM raising an exception on all retries → model_id becomes 'template-v1'."""
        ctx = _make_entity_ctx()
        uc, _write_sf, _read_sf, narr_repo, _outbox_repo = _make_use_case(
            entity_ctx=ctx,
            llm_error=RuntimeError("LLM provider unavailable"),
        )

        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            result = asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))

        assert result is True
        version = narr_repo.insert_and_promote.call_args.args[0]
        assert version.model_id == "template-v1"

    def test_narrative_no_llm_client_uses_template_v1(self) -> None:
        """llm_client=None (no LLM configured) → always uses template-v1."""
        ctx = _make_entity_ctx()
        # _make_use_case passes llm=None when llm_text and llm_error are both None
        uc, _write_sf, _read_sf, narr_repo, _outbox_repo = _make_use_case(entity_ctx=ctx)

        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            result = asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))

        assert result is True
        version = narr_repo.insert_and_promote.call_args.args[0]
        assert version.model_id == "template-v1"
        assert "[template-v1]" in version.narrative_text

    def test_narrative_reads_raw_response_field_d_r3_narr(self) -> None:
        """D-R3-NARR (PLAN-0087): use case must read ExtractionOutput.raw_response.

        Pre-fix the use case read ``result.output`` which doesn't exist on
        the real ExtractionOutput dataclass, so every LLM call raised
        AttributeError on every retry → every narrative collapsed to the
        template-v1 fallback. This test pins the field name and asserts
        the LLM-text path runs to completion (model_id matches the
        configured LLM model_id, narrative_text equals the LLM output).
        """
        ctx = _make_entity_ctx()
        llm_text = "x" * 200  # well above _MIN_NARRATIVE_LEN (50)
        uc, _write_sf, _read_sf, narr_repo, _outbox_repo = _make_use_case(
            entity_ctx=ctx,
            llm_text=llm_text,
        )
        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            result = asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))
        assert result is True
        version = narr_repo.insert_and_promote.call_args.args[0]
        # Must be the configured LLM model id, NOT the template fallback.
        assert version.model_id != "template-v1"
        assert version.narrative_text.startswith("x" * 50)

    def test_narrative_rejects_json_error_envelopes_d_r3_narr_followup(self) -> None:
        """D-R3-NARR followup: JSON-error envelopes must NOT be stored as narratives.

        Some LLM providers return JSON error bodies as ``raw_response`` when
        the prompt is empty or the model alias is wrong. Pre-followup the
        use case happily stored the JSON verbatim, leaking error text into
        the Intelligence tab. The followup raises ValueError on detection so
        the caller exhausts retries and falls back to template-v1.
        """
        ctx = _make_entity_ctx()
        json_error = '{"error":{"message":"No entity provided","type":"invalid_request_error"}}'
        # Provide enough retries for the loop to exhaust.
        uc, _write_sf, _read_sf, narr_repo, _outbox_repo = _make_use_case(
            entity_ctx=ctx,
            llm_text=json_error,  # populates raw_response with the error JSON
        )
        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            result = asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))
        # Must fall back to template — never store the JSON error as narrative.
        assert result is True
        version = narr_repo.insert_and_promote.call_args.args[0]
        assert version.model_id == "template-v1"
        assert '"error"' not in version.narrative_text


class TestNarrativeSanitization:
    def test_narrative_inputs_sanitized_before_llm_call(self) -> None:
        """sanitize_description is called for entity name and entity type."""
        ctx = _make_entity_ctx()
        llm_text = "B" * 100  # valid LLM response
        uc, _write_sf, _read_sf, _narr_repo, _outbox_repo = _make_use_case(
            entity_ctx=ctx,
            llm_text=llm_text,
        )

        sanitize_calls: list[str] = []

        def _track_sanitize(val: str) -> str:
            sanitize_calls.append(val)
            return val

        with (
            patch(_SANITIZE, side_effect=_track_sanitize),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))

        assert _ENTITY_NAME in sanitize_calls, "canonical_name must be sanitized"
        assert _ENTITY_TYPE in sanitize_calls, "entity_type must be sanitized"


class TestNarrativeConcurrentInsert:
    def test_narrative_concurrent_insert_handles_partial_unique_violation(self) -> None:
        """DB unique constraint violation from insert_and_promote propagates to caller."""
        ctx = _make_entity_ctx()
        uc, _write_sf, _read_sf, narr_repo, _outbox_repo = _make_use_case(entity_ctx=ctx)

        narr_repo.insert_and_promote = AsyncMock(side_effect=Exception("UniqueViolation: entity_id already current"))

        with (
            patch(_SANITIZE, side_effect=lambda x: x),
            patch(_SERIALIZE, return_value=b"avro_bytes"),
        ):
            with pytest.raises(Exception, match="UniqueViolation"):
                asyncio.run(uc.execute(entity_id=_ENTITY_ID, tenant_id=None, reason="INITIAL"))
