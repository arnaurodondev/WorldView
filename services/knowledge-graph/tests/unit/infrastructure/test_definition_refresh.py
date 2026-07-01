"""Unit tests for DefinitionRefreshWorker non-company description enhancement (PRD-0017 §6.5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("01234567-89ab-7def-8012-345678901234")
_ENTITY_TYPE_PERSON = "person"
_ENTITY_TYPE_COUNTRY = "country"
_CANONICAL_NAME = "Jerome Powell"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(due_rows: list[dict]) -> MagicMock:
    """Build a fake async_sessionmaker that yields a session with mocked get_due_for_refresh."""
    session = AsyncMock()
    session.commit = AsyncMock()

    # Make the session work as an async context manager
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = session_cm

    return factory, session


def _make_due_row(
    entity_type: str,
    canonical_name: str = _CANONICAL_NAME,
    source_text: str | None = None,
    source_hash: str | None = None,
    ticker: str | None = None,
    exchange: str | None = None,
    isin: str | None = None,
) -> dict:
    return {
        "entity_id": _ENTITY_ID,
        "entity_type": entity_type,
        "canonical_name": canonical_name,
        "source_text": source_text,
        "source_hash": source_hash,
        "ticker": ticker,
        "exchange": exchange,
        "isin": isin,
    }


def _make_null_description_client() -> AsyncMock:
    """A mock description client that always returns None."""
    client = AsyncMock()
    client.generate_description = AsyncMock(return_value=None)
    return client


def _make_description_client(description: str) -> AsyncMock:
    """A mock description client that returns a specific description."""
    client = AsyncMock()
    client.generate_description = AsyncMock(return_value=description)
    return client


# ---------------------------------------------------------------------------
# _fallback_description helper
# ---------------------------------------------------------------------------


class TestFallbackDescription:
    def test_returns_non_empty_string(self) -> None:
        from knowledge_graph.infrastructure.workers.definition_refresh import _fallback_description

        result = _fallback_description("Jerome Powell", "person")
        assert result
        assert "Jerome Powell" in result
        assert "person" in result

    def test_format(self) -> None:
        from knowledge_graph.infrastructure.workers.definition_refresh import _fallback_description

        result = _fallback_description("Germany", "country")
        assert result == "Germany is a country."


# ---------------------------------------------------------------------------
# NullDescriptionAdapter default
# ---------------------------------------------------------------------------


class TestDefinitionRefreshWorkerDefaults:
    async def test_no_description_client_defaults_to_null(self) -> None:
        """When no description_client is passed, NullDescriptionAdapter is used."""
        session_factory, _ = _make_session_factory([])
        llm_client = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=None)
        # NullDescriptionAdapter always returns None → fallback template will be used
        result = await worker._description_client.generate_description(
            entity_id=str(_ENTITY_ID),
            canonical_name="Test",
            entity_type="person",
            context_hints={},
        )
        assert result is None


# ---------------------------------------------------------------------------
# Non-company entity: description_client used
# ---------------------------------------------------------------------------


class TestNonCompanyDescriptionGeneration:
    async def test_non_company_entity_uses_description_client(self) -> None:
        """For non-financial_instrument entities, generate_description is called."""
        session_factory, _session = _make_session_factory([])
        description_client = _make_description_client("Jerome Powell is the Chair of the Federal Reserve.")
        llm_client = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=description_client)
        row = _make_due_row(entity_type=_ENTITY_TYPE_PERSON)

        result = await worker._resolve_non_company_text(_ENTITY_ID, _ENTITY_TYPE_PERSON, row)

        description_client.generate_description.assert_called_once_with(
            entity_id=str(_ENTITY_ID),
            canonical_name=_CANONICAL_NAME,
            entity_type=_ENTITY_TYPE_PERSON,
            context_hints={},
            # No evidence_provider wired on this worker → news_context degrades to
            # None and the LLM applies its no-news guard.
            news_context=None,
        )
        assert result == "Jerome Powell is the Chair of the Federal Reserve."

    async def test_description_fallback_on_none(self) -> None:
        """When description_client returns None, deterministic fallback template is used.

        This is the PRD-specified test case (PRD-0017 §8, test_description_fallback_on_none).
        """
        session_factory, _ = _make_session_factory([])
        description_client = _make_null_description_client()
        llm_client = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=description_client)
        row = _make_due_row(entity_type=_ENTITY_TYPE_COUNTRY, canonical_name="Germany")

        result = await worker._resolve_non_company_text(_ENTITY_ID, _ENTITY_TYPE_COUNTRY, row)

        # Client was called
        description_client.generate_description.assert_called_once()
        # Fallback template used since client returned None
        assert result == "Germany is a country."

    async def test_context_hints_populated_from_row(self) -> None:
        """Ticker/exchange/isin from the row are passed as context_hints."""
        session_factory, _ = _make_session_factory([])
        description_client = _make_description_client("A description.")
        llm_client = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=description_client)
        row = _make_due_row(
            entity_type="organization",
            canonical_name="Federal Reserve",
            ticker=None,
            exchange="US",
            isin=None,
        )

        await worker._resolve_non_company_text(_ENTITY_ID, "organization", row)

        call_kwargs = description_client.generate_description.call_args.kwargs
        assert call_kwargs["context_hints"] == {"exchange": "US"}

    async def test_description_client_exception_falls_back_to_template(self) -> None:
        """When generate_description raises, fallback template is used (no crash)."""
        session_factory, _ = _make_session_factory([])
        description_client = AsyncMock()
        description_client.generate_description = AsyncMock(side_effect=RuntimeError("API error"))
        llm_client = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=description_client)
        row = _make_due_row(entity_type=_ENTITY_TYPE_PERSON)

        # Should not raise
        result = await worker._resolve_non_company_text(_ENTITY_ID, _ENTITY_TYPE_PERSON, row)
        assert result == f"{_CANONICAL_NAME} is a {_ENTITY_TYPE_PERSON}."


# ---------------------------------------------------------------------------
# News-grounding (description audit 2026-06-17): the worker must fetch the
# entity's own recent evidence via the injected provider and pass it as
# news_context, degrading to None on any read error.
# ---------------------------------------------------------------------------


def _make_evidence_provider(snippets: list[str]) -> AsyncMock:
    """A mock EntityEnrichmentAdapter returning fixed evidence snippets."""
    provider = AsyncMock()
    provider.fetch_recent_evidence = AsyncMock(return_value=snippets)
    return provider


class TestNewsGrounding:
    async def test_non_company_fetches_evidence_and_passes_news_context(self) -> None:
        """The worker calls fetch_recent_evidence and threads the result into news_context."""
        session_factory, _ = _make_session_factory([])
        description_client = _make_description_client("Jerome Powell chairs the Federal Reserve.")
        llm_client = AsyncMock()
        snippets = ["Powell signalled a pause in rate hikes.", "The Fed held rates steady."]
        evidence_provider = _make_evidence_provider(snippets)

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(
            session_factory,
            llm_client,
            description_client=description_client,
            evidence_provider=evidence_provider,
        )
        row = _make_due_row(entity_type=_ENTITY_TYPE_PERSON)

        await worker._resolve_non_company_text(_ENTITY_ID, _ENTITY_TYPE_PERSON, row)

        # Evidence was fetched for THIS entity.
        evidence_provider.fetch_recent_evidence.assert_awaited_once_with(_ENTITY_ID)
        # …and threaded into the LLM call as news_context.
        call_kwargs = description_client.generate_description.call_args.kwargs
        assert call_kwargs["news_context"] == snippets

    async def test_non_company_degrades_to_none_on_evidence_error(self) -> None:
        """A failure in fetch_recent_evidence degrades news_context to None (no crash)."""
        session_factory, _ = _make_session_factory([])
        description_client = _make_description_client("A grounded description.")
        llm_client = AsyncMock()
        evidence_provider = AsyncMock()
        evidence_provider.fetch_recent_evidence = AsyncMock(side_effect=RuntimeError("read replica down"))

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(
            session_factory,
            llm_client,
            description_client=description_client,
            evidence_provider=evidence_provider,
        )
        row = _make_due_row(entity_type=_ENTITY_TYPE_PERSON)

        # Must not raise despite the provider error.
        result = await worker._resolve_non_company_text(_ENTITY_ID, _ENTITY_TYPE_PERSON, row)

        evidence_provider.fetch_recent_evidence.assert_awaited_once()
        call_kwargs = description_client.generate_description.call_args.kwargs
        assert call_kwargs["news_context"] is None
        assert result == "A grounded description."

    async def test_no_provider_passes_none_news_context(self) -> None:
        """With no evidence_provider wired, news_context is None (backward compatible)."""
        session_factory, _ = _make_session_factory([])
        description_client = _make_description_client("An ungrounded description.")
        llm_client = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=description_client)
        row = _make_due_row(entity_type=_ENTITY_TYPE_PERSON)

        await worker._resolve_non_company_text(_ENTITY_ID, _ENTITY_TYPE_PERSON, row)

        call_kwargs = description_client.generate_description.call_args.kwargs
        assert call_kwargs["news_context"] is None

    async def test_null_fi_path_is_grounded(self) -> None:
        """The NULL-source financial_instrument path also fetches + passes news_context.

        This path backs crypto/FX/index instruments; grounding it keeps their
        descriptions honest too.
        """
        session_factory, _ = _make_session_factory([])
        description_client = _make_description_client("Bitcoin is a decentralized digital currency.")
        llm_client = AsyncMock()
        snippets = ["Bitcoin rallied above $70k."]
        evidence_provider = _make_evidence_provider(snippets)

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(
            session_factory,
            llm_client,
            description_client=description_client,
            evidence_provider=evidence_provider,
        )
        row = _make_due_row(
            entity_type="financial_instrument",
            canonical_name="Bitcoin",
            source_text=None,
            ticker="BTC.USD",
        )

        await worker._resolve_definition_text_for_null_fi(_ENTITY_ID, row)

        evidence_provider.fetch_recent_evidence.assert_awaited_once_with(_ENTITY_ID)
        call_kwargs = description_client.generate_description.call_args.kwargs
        assert call_kwargs["news_context"] == snippets

    async def test_manual_trigger_description_path_is_grounded(self) -> None:
        """Regression proof for the manual trigger_entity_refresh(refresh_type='description').

        That endpoint enqueues entity.refresh.v1 → S6 marks the entity_embedding_state
        row due → this worker's run() re-describes it. We drive a full run() with a
        due non-company row and assert the LLM was grounded with the entity's evidence.
        """
        description_client = _make_description_client(
            "Jerome Powell is the Chair of the Federal Reserve, guiding US monetary policy."
        )
        llm_client = AsyncMock()
        llm_client.embed = AsyncMock(return_value=[MagicMock(embedding=[0.1, 0.2, 0.3])])
        snippets = ["Powell testified before Congress on inflation."]
        evidence_provider = _make_evidence_provider(snippets)

        session_factory, _session = _make_session_factory([])

        emb_repo_mock = AsyncMock()
        due_row = _make_due_row(
            entity_type=_ENTITY_TYPE_PERSON,
            canonical_name=_CANONICAL_NAME,
            source_text=None,
            source_hash=None,
        )
        emb_repo_mock.get_due_for_refresh = AsyncMock(return_value=[due_row])
        emb_repo_mock.upsert = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(
            session_factory,
            llm_client,
            description_client=description_client,
            evidence_provider=evidence_provider,
        )

        with patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=emb_repo_mock,
        ):
            await worker.run()

        # The full refresh cycle grounded the LLM with the entity's own evidence.
        evidence_provider.fetch_recent_evidence.assert_awaited_once_with(_ENTITY_ID)
        call_kwargs = description_client.generate_description.call_args.kwargs
        assert call_kwargs["news_context"] == snippets
        # …and the grounded description was embedded + persisted.
        emb_repo_mock.upsert.assert_awaited_once()


# ---------------------------------------------------------------------------
# financial_instrument: description_client NOT used
# ---------------------------------------------------------------------------


class TestFinancialInstrumentSkipsDescriptionClient:
    async def test_financial_instrument_does_not_call_description_client(self) -> None:
        """financial_instrument entities skip _resolve_non_company_text entirely."""
        description_client = _make_description_client("A company description.")
        llm_client = AsyncMock()
        llm_outputs = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        llm_client.embed = AsyncMock(return_value=llm_outputs)

        session_factory, _session = _make_session_factory([])

        # Build emb_repo mock that returns one due row for financial_instrument
        emb_repo_mock = AsyncMock()
        due_row = _make_due_row(
            entity_type="financial_instrument",
            canonical_name="Apple Inc.",
            source_text="Apple Inc. is a consumer electronics company.",
            source_hash="different_hash",  # Force re-embed
        )
        emb_repo_mock.get_due_for_refresh = AsyncMock(return_value=[due_row])
        emb_repo_mock.upsert = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=description_client)

        with patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=emb_repo_mock,
        ):
            await worker.run()

        # description_client must NOT be called for financial_instrument entities
        description_client.generate_description.assert_not_called()
        # But embedding should happen
        llm_client.embed.assert_called_once()


# ---------------------------------------------------------------------------
# 2026-06-14 P1: financial_instrument with NULL source_text (RC2)
# crypto/FX/index instruments EODHD has no description for must be LLM-generated
# ---------------------------------------------------------------------------


class TestFinancialInstrumentNullSourceText:
    async def test_fi_null_source_generates_via_description_client(self) -> None:
        """FI + source_text IS NULL → description client generates text, row gets embedded."""
        description_client = _make_description_client("Bitcoin (BTC.USD) is a decentralized digital currency.")
        llm_client = AsyncMock()
        llm_client.embed = AsyncMock(return_value=[MagicMock(embedding=[0.1, 0.2, 0.3])])

        session_factory, _session = _make_session_factory([])

        emb_repo_mock = AsyncMock()
        due_row = _make_due_row(
            entity_type="financial_instrument",
            canonical_name="Bitcoin",
            source_text=None,  # EODHD has no description for crypto
            source_hash=None,
            ticker="BTC.USD",
        )
        emb_repo_mock.get_due_for_refresh = AsyncMock(return_value=[due_row])
        emb_repo_mock.upsert = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=description_client)

        with patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=emb_repo_mock,
        ):
            await worker.run()

        # The description client WAS called for this FI entity (RC2 fix), with the
        # financial_instrument entity_type and the ticker context hint.
        description_client.generate_description.assert_called_once()
        call_kwargs = description_client.generate_description.call_args.kwargs
        assert call_kwargs["entity_type"] == "financial_instrument"
        assert call_kwargs["context_hints"] == {"ticker": "BTC.USD"}

        # The generated text was embedded and upserted.
        llm_client.embed.assert_called_once()
        emb_repo_mock.upsert.assert_awaited_once()
        upsert_kwargs = emb_repo_mock.upsert.call_args.kwargs
        assert upsert_kwargs["source_text"] == "Bitcoin (BTC.USD) is a decentralized digital currency."

    async def test_fi_null_source_empty_llm_output_is_skipped_not_persisted(self) -> None:
        """BP-114 guard: when the LLM returns '' / whitespace for an FI null-source row,
        the row is SKIPPED (no upsert, no degenerate text persisted)."""
        # Description client returns whitespace — must be treated as failure.
        description_client = AsyncMock()
        description_client.generate_description = AsyncMock(return_value="   ")
        llm_client = AsyncMock()
        llm_client.embed = AsyncMock(return_value=[MagicMock(embedding=[0.1])])

        session_factory, _session = _make_session_factory([])

        emb_repo_mock = AsyncMock()
        due_row = _make_due_row(
            entity_type="financial_instrument",
            canonical_name="Dow Jones",
            source_text=None,
            source_hash=None,
            ticker="DJI",
        )
        emb_repo_mock.get_due_for_refresh = AsyncMock(return_value=[due_row])
        emb_repo_mock.upsert = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=description_client)

        with patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=emb_repo_mock,
        ):
            await worker.run()

        # Client was called, but empty output → nothing embedded or persisted.
        description_client.generate_description.assert_called_once()
        llm_client.embed.assert_not_called()
        emb_repo_mock.upsert.assert_not_awaited()

    async def test_fi_null_source_llm_exception_is_skipped(self) -> None:
        """When generate_description raises for an FI null-source row, the cycle does NOT
        crash and the row is skipped (no upsert)."""
        description_client = AsyncMock()
        description_client.generate_description = AsyncMock(side_effect=RuntimeError("DeepInfra 500"))
        llm_client = AsyncMock()
        llm_client.embed = AsyncMock(return_value=[MagicMock(embedding=[0.1])])

        session_factory, _session = _make_session_factory([])

        emb_repo_mock = AsyncMock()
        due_row = _make_due_row(
            entity_type="financial_instrument",
            canonical_name="GBP/USD",
            source_text=None,
            source_hash=None,
            ticker="GBPUSD",
        )
        emb_repo_mock.get_due_for_refresh = AsyncMock(return_value=[due_row])
        emb_repo_mock.upsert = AsyncMock()

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        worker = DefinitionRefreshWorker(session_factory, llm_client, description_client=description_client)

        with patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=emb_repo_mock,
        ):
            await worker.run()  # must not raise

        llm_client.embed.assert_not_called()
        emb_repo_mock.upsert.assert_not_awaited()


# ---------------------------------------------------------------------------
# scheduler.py — _build_description_client
# ---------------------------------------------------------------------------


class TestDefinitionRefreshWorkerPhasedRun:
    """Tests for the three-phase run() method (Phase Read → Process → Write).

    The key invariant: NO DB session is open during external I/O
    (description generation or embedding calls).
    """

    async def test_run_closes_session_before_embed(self) -> None:
        """Session is closed (Phase 1 done) before _embed is called (Phase 2)."""

        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        # Track whether the session context manager has exited before embed is called
        session_exited: list[bool] = [False]

        session = AsyncMock()
        session.commit = AsyncMock()

        session_cm = AsyncMock()

        async def _cm_enter(_self=None):
            session_exited[0] = False
            return session

        async def _cm_exit(*args):
            session_exited[0] = True
            return False

        session_cm.__aenter__ = _cm_enter
        session_cm.__aexit__ = _cm_exit

        sf = MagicMock()
        sf.return_value = session_cm

        emb_repo_mock = AsyncMock()
        due_row = _make_due_row(
            entity_type="financial_instrument",
            source_text="Apple Inc. is a company.",
            source_hash="different_hash",  # force re-embed
        )
        emb_repo_mock.get_due_for_refresh = AsyncMock(return_value=[due_row])
        emb_repo_mock.upsert = AsyncMock()

        session_open_during_embed_check: list[bool] = []

        llm_client = AsyncMock()

        async def _embed_and_record(inp):
            # Record whether session was open (exited = closed) when embed was called
            # session_exited[0] is True when Phase 1 session context exited
            session_open_during_embed_check.append(session_exited[0])
            return [AsyncMock(embedding=[0.1, 0.2, 0.3])]

        llm_client.embed = _embed_and_record

        worker = DefinitionRefreshWorker(sf, llm_client)

        with patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=emb_repo_mock,
        ):
            await worker.run()

        # Embed must have been called
        assert len(session_open_during_embed_check) == 1
        # When embed was called, the Phase 1 session must have already been closed
        assert (
            session_open_during_embed_check[0] is True
        ), "DB session must be closed before _embed is called (R24 compliance)"

    async def test_run_empty_due_returns_early(self) -> None:
        """When no rows are due, run() returns without opening a write session."""
        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        session = AsyncMock()
        session_cm = AsyncMock()
        session_cm.__aenter__ = AsyncMock(return_value=session)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        open_count = [0]
        sf = MagicMock()

        def _track():
            open_count[0] += 1
            return session_cm

        sf.side_effect = _track

        emb_repo_mock = AsyncMock()
        emb_repo_mock.get_due_for_refresh = AsyncMock(return_value=[])

        llm_client = AsyncMock()
        worker = DefinitionRefreshWorker(sf, llm_client)

        with patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
            return_value=emb_repo_mock,
        ):
            await worker.run()

        # Only 1 session open (Phase 1 read); no Phase 3 write session
        assert open_count[0] == 1


class TestBuildDescriptionClient:
    def test_none_provider_returns_null_adapter(self) -> None:
        """description_provider='none' returns NullDescriptionAdapter."""
        from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client
        from ml_clients.description_client import NullDescriptionAdapter  # type: ignore[import-untyped]

        settings = MagicMock()
        settings.description_provider = "none"

        client = _build_description_client(settings)
        assert isinstance(client, NullDescriptionAdapter)

    def test_gemini_provider_with_empty_key_returns_null_adapter(self) -> None:
        """provider='gemini' with BOTH keys empty falls back to NullDescriptionAdapter.

        PLAN-0095 W4 T-W4-03: gemini-empty + deepinfra-present now uses the
        DeepInfra chain (covered by a separate test). This case keeps the Null
        guard pinned for the all-empty path so an operator who clears every
        key still gets the deterministic stub instead of a crash.
        """
        from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client
        from ml_clients.description_client import NullDescriptionAdapter  # type: ignore[import-untyped]

        settings = MagicMock()
        settings.description_provider = "gemini"
        settings.gemini_api_key.get_secret_value.return_value = ""
        settings.deepinfra_api_key.get_secret_value.return_value = ""  # T-W4-03

        client = _build_description_client(settings)
        assert isinstance(client, NullDescriptionAdapter)

    def test_gemini_provider_with_key_returns_gemini_adapter(self) -> None:
        """description_provider='gemini' with a valid key returns GeminiDescriptionAdapter."""
        from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter  # type: ignore[import-untyped]

        settings = MagicMock()
        settings.description_provider = "gemini"
        settings.gemini_api_key.get_secret_value.return_value = "test-key-123"
        settings.description_gemini_concurrency = 4
        settings.description_max_monthly_usd = 10.0

        client = _build_description_client(settings)
        assert isinstance(client, GeminiDescriptionAdapter)

    def test_unknown_provider_returns_null_adapter(self) -> None:
        """Unknown provider string falls back to NullDescriptionAdapter."""
        from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client
        from ml_clients.description_client import NullDescriptionAdapter  # type: ignore[import-untyped]

        settings = MagicMock()
        settings.description_provider = "anthropic"  # not supported

        client = _build_description_client(settings)
        assert isinstance(client, NullDescriptionAdapter)
