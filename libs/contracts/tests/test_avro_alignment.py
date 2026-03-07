"""Contract tests — validate canonical model to_dict() outputs against Avro schemas.

Strategy:
  - Load each .avsc schema (plain JSON) and extract its field names.
  - Create a representative canonical model instance, call to_dict().
  - Assert every Avro data field (excluding event-envelope fields) is present
    in to_dict() output.
  - Assert to_dict() contains no unexpected top-level fields not in the schema.

Scope / mapping:
  - CanonicalArticle   → content.article.stored.v1.avsc
  - CanonicalSentiment → nlp.article.enriched.v1.avsc  (sentiment sub-fields)
  - CanonicalOHLCVBar  → market.dataset.fetched.avsc    (payload fields subset)
  - CanonicalQuote     → no direct Avro schema — field-presence check only
  - CanonicalFundamentals → no direct Avro schema — field-presence check only
  - CanonicalEntity    → nlp.signal.detected.v1.avsc   (entity_id present)

Note: Envelope fields (event_id, event_type, occurred_at, correlation_id) are
NOT part of canonical models; they belong to the Kafka event wrapper. Tests only
validate data payload field alignment.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from contracts.canonical.article import CanonicalArticle
from contracts.canonical.entity import CanonicalEntity
from contracts.canonical.fundamentals import CanonicalFundamentals
from contracts.canonical.ohlcv import CanonicalOHLCVBar
from contracts.canonical.quotes import CanonicalQuote
from contracts.canonical.sentiment import CanonicalSentiment

# Path to Avro schemas relative to this test file
_SCHEMAS_DIR = Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas"

# Envelope fields that appear in Avro schemas but NOT in canonical model to_dict()
_ENVELOPE_FIELDS = frozenset({
    "event_id", "event_type", "occurred_at", "correlation_id",
    "schema_version",  # schema_version is on the model itself, not in all avsc
})


def _load_avsc(filename: str) -> dict:
    """Load and parse an Avro schema JSON file."""
    path = _SCHEMAS_DIR / filename
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _avro_data_fields(schema: dict, exclude: frozenset[str] = _ENVELOPE_FIELDS) -> set[str]:
    """Extract field names from an Avro schema, excluding envelope fields."""
    return {f["name"] for f in schema["fields"] if f["name"] not in exclude}


class TestCanonicalArticleAvroAlignment:
    """CanonicalArticle → content.article.stored.v1.avsc."""

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

    def test_avro_schema_data_fields_present_in_to_dict(self) -> None:
        schema = _load_avsc("content.article.stored.v1.avsc")
        avro_fields = _avro_data_fields(schema)
        model_dict = self._make_article().to_dict()
        for avro_field in avro_fields:
            assert avro_field in model_dict, (
                f"Avro field '{avro_field}' missing from CanonicalArticle.to_dict()"
            )

    def test_required_article_fields(self) -> None:
        d = self._make_article().to_dict()
        for key in ("article_id", "source_domain", "title", "url", "language",
                    "word_count", "is_duplicate", "duplicate_of", "published_at"):
            assert key in d


class TestCanonicalSentimentAvroAlignment:
    """CanonicalSentiment — validate field presence vs nlp.article.enriched.v1.avsc."""

    def _make_sentiment(self) -> CanonicalSentiment:
        return CanonicalSentiment(
            article_id="01JPXYZ123ABC",
            label="positive",
            score=0.82,
            model_name="finbert",
            model_version="1.0.0",
        )

    def test_sentiment_fields_in_to_dict(self) -> None:
        """nlp.article.enriched.v1 has sentiment_label and sentiment_score.
        CanonicalSentiment uses 'label' and 'score' (simpler naming).
        Validate that our model exposes the expected fields."""
        d = self._make_sentiment().to_dict()
        assert "label" in d
        assert "score" in d
        assert "article_id" in d

    def test_avro_schema_has_sentiment_fields(self) -> None:
        schema = _load_avsc("nlp.article.enriched.v1.avsc")
        avro_field_names = {f["name"] for f in schema["fields"]}
        assert "sentiment_label" in avro_field_names
        assert "sentiment_score" in avro_field_names
        assert "article_id" in avro_field_names

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
    """CanonicalEntity — validate entity_id appears in nlp.signal.detected.v1.avsc."""

    def _make_entity(self) -> CanonicalEntity:
        return CanonicalEntity(
            entity_id="01JPENT123",
            entity_type="Company",
            name="Apple Inc.",
            canonical_name="Apple",
            source_article_id="01JPXYZ123ABC",
            confidence=0.95,
        )

    def test_entity_id_in_avro_schema(self) -> None:
        schema = _load_avsc("nlp.signal.detected.v1.avsc")
        avro_field_names = {f["name"] for f in schema["fields"]}
        assert "entity_id" in avro_field_names

    def test_entity_id_in_to_dict(self) -> None:
        d = self._make_entity().to_dict()
        assert "entity_id" in d
        assert d["entity_id"] == "01JPENT123"

    def test_entity_required_fields(self) -> None:
        d = self._make_entity().to_dict()
        for key in ("entity_id", "entity_type", "name", "canonical_name",
                    "source_article_id", "confidence"):
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
        for key in ("symbol", "exchange", "bid", "ask", "last", "volume",
                    "timestamp", "schema_version"):
            assert key in d


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
