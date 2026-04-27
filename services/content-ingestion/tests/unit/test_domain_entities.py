"""Unit tests for prediction market domain entities (Wave A-1, PLAN-0019)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from content_ingestion.domain.entities import OutcomeSnapshot, PredictionMarketFetchResult

pytestmark = pytest.mark.unit


# ── OutcomeSnapshot ────────────────────────────────────────────────────────────


class TestOutcomeSnapshot:
    def _valid(self, **kwargs) -> OutcomeSnapshot:
        defaults = {"name": "Yes", "token_id": "abc123", "price": 0.65}
        return OutcomeSnapshot(**{**defaults, **kwargs})

    def test_outcome_snapshot_price_below_zero(self) -> None:
        with pytest.raises(ValueError, match="price"):
            self._valid(price=-0.01)

    def test_outcome_snapshot_price_above_one(self) -> None:
        with pytest.raises(ValueError, match="price"):
            self._valid(price=1.01)

    def test_outcome_snapshot_price_boundary_zero(self) -> None:
        snap = self._valid(price=0.0)
        assert snap.price == 0.0

    def test_outcome_snapshot_price_boundary_one(self) -> None:
        snap = self._valid(price=1.0)
        assert snap.price == 1.0

    def test_outcome_snapshot_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name"):
            self._valid(name="")

    def test_outcome_snapshot_empty_token_id(self) -> None:
        with pytest.raises(ValueError, match="token_id"):
            self._valid(token_id="")

    def test_outcome_snapshot_is_frozen(self) -> None:
        snap = self._valid()
        with pytest.raises((AttributeError, TypeError)):
            snap.price = 0.5  # type: ignore[misc]


# ── PredictionMarketFetchResult ────────────────────────────────────────────────


def _two_outcomes() -> list[OutcomeSnapshot]:
    return [
        OutcomeSnapshot(name="Yes", token_id="tok_yes", price=0.7),
        OutcomeSnapshot(name="No", token_id="tok_no", price=0.3),
    ]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class TestPredictionMarketFetchResult:
    def _valid(self, **kwargs) -> PredictionMarketFetchResult:
        from contracts.enums import ContentSourceType  # type: ignore[import-untyped]

        defaults = {
            "source_type": ContentSourceType.POLYMARKET,
            "market_id": "cond_abc",
            "question": "Will X happen?",
            "outcomes": _two_outcomes(),
            "raw_bytes": b"{}",
            "fetched_at": _utc_now(),
        }
        return PredictionMarketFetchResult(**{**defaults, **kwargs})

    def test_prediction_market_fetch_result_empty_outcomes(self) -> None:
        with pytest.raises(ValueError, match="outcomes"):
            self._valid(outcomes=[])

    def test_prediction_market_fetch_result_single_outcome(self) -> None:
        with pytest.raises(ValueError, match="outcomes"):
            single = [OutcomeSnapshot(name="Yes", token_id="tok", price=0.9)]
            self._valid(outcomes=single)

    def test_prediction_market_fetch_result_naive_datetime(self) -> None:
        with pytest.raises(ValueError, match="UTC-aware"):
            self._valid(fetched_at=datetime(2026, 1, 1, 12, 0, 0))  # noqa: DTZ001

    def test_prediction_market_fetch_result_happy_path(self) -> None:
        result = self._valid()
        assert result.market_id == "cond_abc"
        assert result.question == "Will X happen?"
        assert len(result.outcomes) == 2
        assert result.resolution_status == "open"
        assert result.minio_bronze_key is None

    def test_prediction_market_fetch_result_is_frozen(self) -> None:
        result = self._valid()
        with pytest.raises((AttributeError, TypeError)):
            result.market_id = "other"  # type: ignore[misc]

    # ── from_gamma_response ────────────────────────────────────────────────────

    def _gamma_raw(self, **overrides) -> dict:
        raw: dict = {
            "conditionId": "cond_xyz",
            "question": "Will it rain tomorrow?",
            "description": "A weather prediction market.",
            "tokens": [
                {"outcome": "Yes", "token_id": "tok_yes", "price": "0.62"},
                {"outcome": "No", "token_id": "tok_no", "price": "0.38"},
            ],
            "volume24hr": "12345.67",
            "liquidity": "5000.0",
            "endDate": "2026-12-31T00:00:00Z",
            "status": "active",
            "resolvedAnswer": None,
            # WHY include slug: Gamma API responses carry event slug for URL construction.
            "slug": "will-it-rain-tomorrow",
        }
        raw.update(overrides)
        return raw

    def test_prediction_market_fetch_result_from_gamma_response_happy(self) -> None:
        raw = self._gamma_raw()
        fetched_at = _utc_now()
        result = PredictionMarketFetchResult.from_gamma_response(raw, fetched_at)

        assert result.market_id == "cond_xyz"
        assert result.question == "Will it rain tomorrow?"
        assert result.description == "A weather prediction market."
        assert len(result.outcomes) == 2
        assert result.outcomes[0].name == "Yes"
        assert result.outcomes[0].price == pytest.approx(0.62)
        assert result.volume_24h == pytest.approx(12345.67)
        assert result.liquidity == pytest.approx(5000.0)
        assert result.close_time is not None
        assert result.close_time.tzinfo is not None
        assert result.resolution_status == "open"
        assert result.resolved_answer is None
        assert result.raw_bytes == json.dumps(raw).encode()
        assert result.fetched_at == fetched_at
        assert result.minio_bronze_key is None
        assert result.market_slug == "will-it-rain-tomorrow"

    def test_prediction_market_fetch_result_from_gamma_response_missing_optional(self) -> None:
        raw = {
            "conditionId": "cond_min",
            "question": "Minimal market?",
            "tokens": [
                {"outcome": "Yes", "token_id": "t1", "price": "0.5"},
                {"outcome": "No", "token_id": "t2", "price": "0.5"},
            ],
        }
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())

        assert result.description is None
        assert result.volume_24h is None
        assert result.liquidity is None
        assert result.close_time is None
        assert result.resolved_answer is None
        assert result.resolution_status == "open"

    def test_from_gamma_response_closed_status_maps_to_cancelled(self) -> None:
        raw = self._gamma_raw(status="closed")
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.resolution_status == "cancelled"

    def test_from_gamma_response_resolved_status(self) -> None:
        raw = self._gamma_raw(status="resolved", resolvedAnswer="Yes")
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.resolution_status == "resolved"
        assert result.resolved_answer == "Yes"

    # ── New Gamma API format (clobTokenIds / outcomes / outcomePrices) ─────────
    # Regression tests for BP-??? — Gamma API dropped the `tokens` list field
    # circa April 2026.  New format uses JSON-encoded strings for outcomes,
    # prices, and token IDs.  Both formats must parse to the same domain entity.

    def test_from_gamma_response_new_api_format_clob_token_ids(self) -> None:
        """New Gamma API format: no tokens list, uses clobTokenIds + outcomes + outcomePrices."""
        raw = {
            "conditionId": "0xnewformat1234",
            "question": "Will it snow this winter?",
            "tokens": [],  # empty in new API format
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.65", "0.35"]',
            "clobTokenIds": '["token_id_yes_abc", "token_id_no_def"]',
            "volume24hr": 9999.99,
            "liquidity": 12345.0,
            "endDate": "2026-12-31T00:00:00Z",
        }
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())

        assert result.market_id == "0xnewformat1234"
        assert len(result.outcomes) == 2  # Passes domain invariant (≥ 2)
        assert result.outcomes[0].name == "Yes"
        assert result.outcomes[0].price == pytest.approx(0.65)
        assert result.outcomes[0].token_id == "token_id_yes_abc"  # noqa: S105
        assert result.outcomes[1].name == "No"
        assert result.outcomes[1].price == pytest.approx(0.35)
        assert result.outcomes[1].token_id == "token_id_no_def"  # noqa: S105
        assert result.volume_24h == pytest.approx(9999.99)

    def test_from_gamma_response_new_api_format_no_tokens_field(self) -> None:
        """New Gamma API format: tokens field absent entirely (not just empty list)."""
        raw = {
            "conditionId": "0xnotokensfield",
            "question": "Will the sun rise tomorrow?",
            # No "tokens" key at all
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.99", "0.01"]',
            "clobTokenIds": '["tokA", "tokB"]',
        }
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert len(result.outcomes) == 2
        assert result.outcomes[0].name == "Yes"
        assert result.outcomes[0].price == pytest.approx(0.99)

    def test_from_gamma_response_old_format_still_works(self) -> None:
        """Old Gamma API format with tokens list still parses correctly."""
        raw = self._gamma_raw()  # has tokens=[{outcome, token_id, price}, ...]
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert len(result.outcomes) == 2
        assert result.outcomes[0].name == "Yes"
        assert result.outcomes[0].price == pytest.approx(0.62)

    def test_from_gamma_response_market_slug_fallback_fields(self) -> None:
        """market_slug falls back to groupItemSlug, then market_slug, then empty."""
        # Primary: "slug" field
        raw_slug = self._gamma_raw(slug="primary-slug")
        assert PredictionMarketFetchResult.from_gamma_response(raw_slug, _utc_now()).market_slug == "primary-slug"

        # Fallback: "groupItemSlug" when "slug" absent
        raw_group = {
            "conditionId": "c1",
            "question": "Q?",
            "tokens": [
                {"outcome": "Yes", "token_id": "t1", "price": "0.5"},
                {"outcome": "No", "token_id": "t2", "price": "0.5"},
            ],
            "groupItemSlug": "group-item-slug",
        }
        assert PredictionMarketFetchResult.from_gamma_response(raw_group, _utc_now()).market_slug == "group-item-slug"

        # Missing: all slug fields absent → empty string
        raw_none = self._gamma_raw()
        raw_none.pop("slug", None)
        result = PredictionMarketFetchResult.from_gamma_response(raw_none, _utc_now())
        assert result.market_slug == ""
