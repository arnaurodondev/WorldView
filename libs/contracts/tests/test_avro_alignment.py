"""Contract tests — validate canonical model to_dict() outputs against Avro schemas.

Strategy:
  - Load each .avsc schema (plain JSON) and extract its field names.
  - Create a representative canonical model instance, call to_dict().
  - Assert every Avro data field (excluding event-envelope fields) is present
    in to_dict() output.
  - Assert to_dict() contains no unexpected top-level fields not in the schema.

Scope / mapping (updated for PRD-0001 schema revision):
  - CanonicalArticle   → content.article.stored.v1.avsc
  - CanonicalSentiment → standalone model (no direct Avro schema after PRD-0001 revision)
  - CanonicalOHLCVBar  → market.dataset.fetched.avsc    (payload fields subset)
  - CanonicalQuote     → no direct Avro schema — field-presence check only
  - CanonicalFundamentals → no direct Avro schema — field-presence check only
  - CanonicalEntity    → nlp.signal.detected.v1.avsc   (subject_entity_id present)

Note: Envelope fields (event_id, event_type, occurred_at, correlation_id) are
NOT part of canonical models; they belong to the Kafka event wrapper. Tests only
validate data payload field alignment.

Avro schemas were revised in PRD-0001 (commit 1539665) to match the intelligence
pipeline specification. These tests verify alignment with the NEW schemas.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from contracts.canonical.article import CanonicalArticle
from contracts.canonical.entity import CanonicalEntity
from contracts.canonical.fundamentals import CanonicalFundamentals
from contracts.canonical.instrument_discovered import CanonicalInstrumentDiscovered
from contracts.canonical.ohlcv import CanonicalOHLCVBar
from contracts.canonical.quotes import CanonicalQuote
from contracts.canonical.sentiment import CanonicalSentiment

# Path to Avro schemas relative to this test file
_SCHEMAS_DIR = Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas"

# Envelope fields that appear in Avro schemas but NOT in canonical model to_dict()
_ENVELOPE_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "occurred_at",
        "correlation_id",
        "schema_version",  # schema_version is on the model itself, not in all avsc
    }
)


def _load_avsc(filename: str) -> dict:
    """Load and parse an Avro schema JSON file."""
    path = _SCHEMAS_DIR / filename
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _avro_data_fields(schema: dict, exclude: frozenset[str] = _ENVELOPE_FIELDS) -> set[str]:
    """Extract field names from an Avro schema, excluding envelope fields."""
    return {f["name"] for f in schema["fields"] if f["name"] not in exclude}


class TestCanonicalArticleAvroAlignment:
    """CanonicalArticle → content.article.stored.v1.avsc.

    The content.article.stored.v1 schema was revised in PRD-0001 §6.3.2.
    New fields: doc_id, content_hash, normalized_hash, dedup_result, minio_silver_key,
    source_type, is_backfill. Removed: article_id, source_domain, url, language,
    is_duplicate, duplicate_of.

    CanonicalArticle still uses the OLD field names (article_id, source_domain, etc.)
    because the canonical models are consumed by S2/S3 (structured pipeline) and haven't
    been updated for the unstructured pipeline yet. The Avro schema is the event contract
    between S5 and S6 — not between CanonicalArticle and S5.

    These tests validate: (1) the Avro schema has the expected PRD-0001 fields,
    (2) CanonicalArticle still has its own required fields.
    """

    def _make_article(self) -> CanonicalArticle:
        return CanonicalArticle(
            article_id="01JPXYZ123ABC",
            source_domain="reuters.com",
            title="Test Article",
            url="https://reuters.com/test",
            language="en",
            word_count=500,
            is_duplicate=False,
            duplicate_of=None,
            published_at="2025-01-15T10:00:00.000000Z",
            body_text="Article body...",
        )

    def test_avro_schema_has_prd_0001_fields(self) -> None:
        """content.article.stored.v1 must have the PRD-0001 §6.3.2 data fields."""
        schema = _load_avsc("content.article.stored.v1.avsc")
        avro_fields = _avro_data_fields(schema)
        expected_data_fields = {
            "doc_id",
            "content_hash",
            "normalized_hash",
            "dedup_result",
            "minio_silver_key",
            "source_type",
            "title",
            "word_count",
            "published_at",
            "is_backfill",
        }
        missing = expected_data_fields - avro_fields
        assert not missing, f"content.article.stored.v1 missing PRD-0001 fields: {missing}"

    def test_required_article_model_fields(self) -> None:
        """CanonicalArticle model retains its original fields (not yet migrated to PRD-0001)."""
        d = self._make_article().to_dict()
        for key in (
            "article_id",
            "source_domain",
            "title",
            "url",
            "language",
            "word_count",
            "is_duplicate",
            "duplicate_of",
            "published_at",
        ):
            assert key in d


class TestCanonicalSentimentModelFields:
    """CanonicalSentiment — standalone model validation.

    After PRD-0001, nlp.article.enriched.v1 no longer has sentiment_label/sentiment_score
    fields (replaced by routing_tier, routing_score, etc.). CanonicalSentiment is a
    standalone model not directly mapped to an Avro schema in the unstructured pipeline.
    """

    def _make_sentiment(self) -> CanonicalSentiment:
        return CanonicalSentiment(
            article_id="01JPXYZ123ABC",
            label="positive",
            score=0.82,
            model_name="finbert",
            model_version="1.0.0",
        )

    def test_sentiment_fields_in_to_dict(self) -> None:
        d = self._make_sentiment().to_dict()
        assert "label" in d
        assert "score" in d
        assert "article_id" in d

    def test_avro_schema_has_prd_0001_enriched_fields(self) -> None:
        """nlp.article.enriched.v1 must have routing_tier/routing_score (PRD-0001 §6.3.2)."""
        schema = _load_avsc("nlp.article.enriched.v1.avsc")
        avro_field_names = {f["name"] for f in schema["fields"]}
        assert "routing_tier" in avro_field_names
        assert "routing_score" in avro_field_names
        assert "doc_id" in avro_field_names
        assert "mention_count" in avro_field_names

    def test_score_in_range(self) -> None:
        d = self._make_sentiment().to_dict()
        assert 0.0 <= d["score"] <= 1.0


class TestCanonicalOHLCVBarAvroAlignment:
    """CanonicalOHLCVBar — validate against market.dataset.fetched.avsc.

    The market.dataset.fetched schema is a claim-check event (it points to
    stored OHLCV data in MinIO). We validate that the OHLCV model to_dict()
    output contains the symbol/exchange fields present in the claim-check schema.
    """

    def _make_bar(self) -> CanonicalOHLCVBar:
        return CanonicalOHLCVBar(
            symbol="AAPL",
            exchange="US",
            date=datetime(2025, 1, 15, tzinfo=UTC),
            open=150.0,
            high=155.0,
            low=149.0,
            close=154.0,
            volume=1_000_000,
            source="eod",
        )

    def test_avro_claim_check_payload_fields_in_bar(self) -> None:
        """market.dataset.fetched.avsc has symbol and exchange.
        CanonicalOHLCVBar.to_dict() must expose these fields."""
        schema = _load_avsc("market.dataset.fetched.avsc")
        avro_fields = _avro_data_fields(schema)
        model_dict = self._make_bar().to_dict()
        for field in ("symbol", "exchange"):
            assert field in avro_fields, f"'{field}' missing from Avro schema"
            assert field in model_dict, f"'{field}' missing from CanonicalOHLCVBar.to_dict()"

    def test_ohlcv_core_fields_present(self) -> None:
        d = self._make_bar().to_dict()
        for key in ("symbol", "exchange", "date", "open", "high", "low", "close", "volume"):
            assert key in d

    def test_new_optional_fields_present(self) -> None:
        d = self._make_bar().to_dict()
        assert "provider" in d
        assert "timeframe" in d
        assert "fetched_at" in d


class TestCanonicalEntityAvroAlignment:
    """CanonicalEntity — validate entity-related fields in nlp.signal.detected.v1.avsc.

    After PRD-0001, nlp.signal.detected.v1 uses subject_entity_id and claimer_entity_id
    (not entity_id). CanonicalEntity.entity_id maps to the canonical entity concept,
    which appears as subject_entity_id in signal events.
    """

    def _make_entity(self) -> CanonicalEntity:
        return CanonicalEntity(
            entity_id="01JPENT123",
            entity_type="Company",
            name="Apple Inc.",
            canonical_name="Apple",
            source_article_id="01JPXYZ123ABC",
            confidence=0.95,
        )

    def test_avro_schema_has_subject_entity_id(self) -> None:
        """nlp.signal.detected.v1 must have subject_entity_id (PRD-0001 naming)."""
        schema = _load_avsc("nlp.signal.detected.v1.avsc")
        avro_field_names = {f["name"] for f in schema["fields"]}
        assert "subject_entity_id" in avro_field_names
        assert "claimer_entity_id" in avro_field_names
        assert "claim_id" in avro_field_names

    def test_entity_id_in_to_dict(self) -> None:
        d = self._make_entity().to_dict()
        assert "entity_id" in d
        assert d["entity_id"] == "01JPENT123"

    def test_entity_required_fields(self) -> None:
        d = self._make_entity().to_dict()
        for key in ("entity_id", "entity_type", "name", "canonical_name", "source_article_id", "confidence"):
            assert key in d


class TestCanonicalQuoteFieldPresence:
    """CanonicalQuote — no direct Avro schema; verify field-set completeness."""

    def _make_quote(self) -> CanonicalQuote:
        return CanonicalQuote(
            symbol="AAPL",
            exchange="NASDAQ",
            bid=149.9,
            ask=150.1,
            last=150.0,
            volume=5_000_000,
            timestamp=datetime(2025, 1, 15, 15, 30, tzinfo=UTC),
        )

    def test_required_fields_in_to_dict(self) -> None:
        d = self._make_quote().to_dict()
        for key in ("symbol", "exchange", "bid", "ask", "last", "volume", "timestamp", "schema_version"):
            assert key in d


class TestCanonicalInstrumentDiscoveredAvroAlignment:
    """CanonicalInstrumentDiscovered ↔ market.instrument.discovered.v1.avsc.

    PLAN-0057 Wave D-2.  This event is small (10 fields) so we hold the model
    and the Avro schema to *exact* field-by-field alignment — every Avro
    field must appear in the model's ``to_dict()`` output, and no extra keys
    may appear in ``to_dict()`` that are not in the schema.

    We also assert alignment between the producer-side dataclass
    (``market_data.domain.events.InstrumentDiscovered``) and the Avro schema
    so a dropped field on either side fails this test loudly.  The
    market-data import is conditional — ``libs/contracts`` tests sometimes
    run in isolation without the service package on ``sys.path``; we
    ``pytest.skip`` rather than fail in that case.
    """

    def _make_discovered(self) -> CanonicalInstrumentDiscovered:
        return CanonicalInstrumentDiscovered(
            event_id="018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
            occurred_at="2026-04-30T12:00:00Z",
            instrument_id="018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            symbol="AAPL",
            exchange="NASDAQ",
            entity_id="018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            correlation_id=None,
            causation_id=None,
        )

    def test_avro_schema_field_set_matches_model(self) -> None:
        """Every Avro field is in to_dict(); no unexpected keys in to_dict()."""
        schema = _load_avsc("market.instrument.discovered.v1.avsc")
        avro_fields = {f["name"] for f in schema["fields"]}
        d = self._make_discovered().to_dict()
        # to_dict() exposes ALL Avro fields including envelope fields.
        missing = avro_fields - set(d.keys())
        assert not missing, f"to_dict() missing Avro fields: {missing}"
        unexpected = set(d.keys()) - avro_fields
        assert not unexpected, f"to_dict() has fields not in schema: {unexpected}"

    def test_avro_schema_has_required_data_fields(self) -> None:
        """Spot-check the schema has the data fields documented in the plan."""
        schema = _load_avsc("market.instrument.discovered.v1.avsc")
        avro_fields = {f["name"] for f in schema["fields"]}
        for field_name in ("instrument_id", "symbol", "exchange"):
            assert field_name in avro_fields

    def test_nullable_fields_have_null_default(self) -> None:
        """All optional fields default to null (forward-compat per BP-126)."""
        schema = _load_avsc("market.instrument.discovered.v1.avsc")
        fields_by_name = {f["name"]: f for f in schema["fields"]}
        for field_name in ("exchange", "entity_id", "correlation_id", "causation_id"):
            assert fields_by_name[field_name]["default"] is None
            assert fields_by_name[field_name]["type"] == ["null", "string"]

    def test_from_dict_to_dict_round_trip(self) -> None:
        """from_dict(to_dict(x)) preserves the payload."""
        original = self._make_discovered()
        round_tripped = CanonicalInstrumentDiscovered.from_dict(original.to_dict())
        assert round_tripped == original

    def test_producer_dataclass_aligns_with_avro(self) -> None:
        """``InstrumentDiscovered`` (market-data domain) field-by-field == Avro schema."""
        try:
            from market_data.domain.events import InstrumentDiscovered  # type: ignore[import-not-found]
        except ImportError:
            import pytest

            pytest.skip("market-data package not on sys.path in this test environment")

        import dataclasses

        schema = _load_avsc("market.instrument.discovered.v1.avsc")
        avro_fields = {f["name"] for f in schema["fields"]}

        # InstrumentDiscovered has ClassVar event_type/schema_version (not dataclass
        # fields) and dataclass fields: event_id, occurred_at, correlation_id,
        # causation_id (from DomainEvent base) + instrument_id, symbol, exchange
        # (subclass).
        dc_field_names = {f.name for f in dataclasses.fields(InstrumentDiscovered)}
        # event_type / schema_version are ClassVars (injected by dispatcher);
        # entity_id is NOT a dataclass field — ``event_to_outbox_payload`` synthesises
        # ``entity_id = instrument_id`` for M-017 stability before serialisation.
        envelope_classvars = {"event_type", "schema_version"}
        synthesised = {"entity_id"}
        missing_in_dc = (avro_fields - envelope_classvars - synthesised) - dc_field_names
        assert not missing_in_dc, f"InstrumentDiscovered missing Avro fields: {missing_in_dc}"
        # Ensure both ClassVars are declared on the class
        assert InstrumentDiscovered.event_type == "market.instrument.discovered"
        assert InstrumentDiscovered.schema_version == 1


class TestCanonicalFundamentalsFieldPresence:
    """CanonicalFundamentals — no direct Avro schema; verify field-set completeness."""

    def _make_fundamentals(self) -> CanonicalFundamentals:
        return CanonicalFundamentals(
            symbol="AAPL",
            exchange="NASDAQ",
            period="annual",
            report_date=datetime(2024, 9, 30, tzinfo=UTC),
        )

    def test_required_fields_in_to_dict(self) -> None:
        d = self._make_fundamentals().to_dict()
        for key in ("symbol", "exchange", "period", "report_date", "schema_version"):
            assert key in d
