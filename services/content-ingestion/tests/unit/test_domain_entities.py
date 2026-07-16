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

    def test_from_gamma_response_truncates_long_question(self) -> None:
        # PLAN-0056 QA FIX 5: untrusted free-text question is bounded to <=500 chars.
        long_q = "Will " + "x" * 1000 + "?"
        raw = self._gamma_raw(question=long_q)
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert len(result.question) == 500

    def test_from_gamma_response_truncates_long_category(self) -> None:
        raw = self._gamma_raw(category="c" * 900)
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.category is not None
        assert len(result.category) == 500

    def test_from_gamma_response_short_question_unchanged(self) -> None:
        raw = self._gamma_raw(question="Short?")
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.question == "Short?"

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

    # ── F-DP1-06 regression: category extraction ──────────────────────────────
    # Polymarket Gamma API surfaces category via either a top-level "category"
    # string or via a "tags" list (strings or {"label": "..."} dicts).  The
    # adapter must canonicalise to lower-case and fall back across the variants.

    def test_from_gamma_response_category_top_level_string(self) -> None:
        """Top-level "category" field is canonicalised to lower-case."""
        raw = self._gamma_raw(category="Politics")
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.category == "politics"

    def test_from_gamma_response_category_falls_back_to_tag_string(self) -> None:
        """When ``category`` is absent, the first non-empty ``tags`` string is used."""
        raw = self._gamma_raw()
        raw.pop("category", None)
        raw["tags"] = ["", "Crypto", "AI"]
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.category == "crypto"

    def test_from_gamma_response_category_falls_back_to_tag_dict(self) -> None:
        """``tags`` list of {"label": "..."} dicts also works."""
        raw = self._gamma_raw()
        raw.pop("category", None)
        raw["tags"] = [{"label": "Sports"}, {"label": "Olympics"}]
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.category == "sports"

    def test_from_gamma_response_category_absent(self) -> None:
        """No category and no tags → category is None (preserves DB on consumer side)."""
        raw = self._gamma_raw()
        raw.pop("category", None)
        raw.pop("tags", None)
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.category is None

    # ── PLAN-0053 T-C-3-04 regression: extended category normalization ────────

    def test_from_gamma_response_category_normalized_top_level(self) -> None:
        """Top-level category like "Cryptocurrency" normalizes to canonical "crypto"."""
        raw = self._gamma_raw(category="Cryptocurrency")
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.category == "crypto"

    def test_from_gamma_response_category_walks_entire_tag_list(self) -> None:
        """When the FIRST tag is unmapped but a LATER tag matches the map, use the later tag.

        Pre-T-C-3-04 behaviour took only the first tag verbatim, producing "other"
        buckets when Polymarket put a fine-grained tag (e.g. "FOMC") before a
        coarse one. Now the walker scans every tag for a known mapping.
        """
        raw = self._gamma_raw()
        raw.pop("category", None)
        # First tag has no map entry; second tag normalizes to "macro".
        raw["tags"] = ["XYZUnknownTag", "FOMC"]
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.category == "macro"

    def test_from_gamma_response_category_title_keyword_fallback(self) -> None:
        """No tag map hit → title-keyword heuristic picks up "Fed" → "macro"."""
        raw = self._gamma_raw(question="Will the Fed cut rates by 50bps in March?")
        raw.pop("category", None)
        raw["tags"] = ["XYZ", "ABC"]  # neither maps; not in title heuristics
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        assert result.category == "macro"

    def test_from_gamma_response_category_fallback_keeps_raw_first_tag(self) -> None:
        """Final fallback: when nothing maps and title has no keywords, keep raw first tag.

        This preserves backward-compat for callers querying by raw category strings
        (e.g. niche topics like "Awards") while still benefiting from the
        normalization map for the canonical 4 buckets.
        """
        raw = self._gamma_raw(question="Sphere question without finance words")
        raw.pop("category", None)
        raw["tags"] = ["RandomTopic", "Other"]
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        # First tag, lower-cased, preserved as the raw category.
        assert result.category == "randomtopic"

    def test_from_gamma_response_category_dict_tags_walked(self) -> None:
        """Dict-shaped tags also walked entirely, not just the first."""
        raw = self._gamma_raw()
        raw.pop("category", None)
        raw["tags"] = [{"label": "ZZZUnmapped"}, {"label": "DeFi"}]
        result = PredictionMarketFetchResult.from_gamma_response(raw, _utc_now())
        # "DeFi" maps to crypto in the normalization table.
        assert result.category == "crypto"


# ── PredictionEventFetchResult — free-text truncation (PLAN-0056 QA FIX 5) ──────


class TestPredictionEventFetchResultTruncation:
    def test_from_gamma_response_truncates_long_title(self) -> None:
        from content_ingestion.domain.entities import PredictionEventFetchResult

        raw = {"id": "evt_1", "title": "T" * 900, "category": "Politics"}
        result = PredictionEventFetchResult.from_gamma_response(raw, _utc_now())
        assert len(result.title) == 500

    def test_from_gamma_response_truncates_long_category(self) -> None:
        from content_ingestion.domain.entities import PredictionEventFetchResult

        raw = {"id": "evt_2", "title": "Election", "category": "c" * 800}
        result = PredictionEventFetchResult.from_gamma_response(raw, _utc_now())
        assert result.category is not None
        assert len(result.category) == 500

    def test_from_gamma_response_short_title_unchanged(self) -> None:
        from content_ingestion.domain.entities import PredictionEventFetchResult

        raw = {"id": "evt_3", "name": "2028 Election", "category": "Politics"}
        result = PredictionEventFetchResult.from_gamma_response(raw, _utc_now())
        assert result.title == "2028 Election"


# ── PredictionEventFetchResult — market->event linkage (PLAN-0056 Wave A3) ──────


class TestPredictionEventFetchResultMemberConditionIds:
    def test_extracts_member_condition_ids_from_child_markets(self) -> None:
        from content_ingestion.domain.entities import PredictionEventFetchResult

        raw = {
            "id": "evt_10",
            "title": "2028 Election",
            "markets": [
                {"conditionId": "0xaaa", "question": "Cand A wins?"},
                {"conditionId": "0xbbb", "question": "Cand B wins?"},
            ],
        }
        result = PredictionEventFetchResult.from_gamma_response(raw, _utc_now())
        assert result.member_condition_ids == ("0xaaa", "0xbbb")
        assert result.market_count == 2

    def test_dedupes_and_skips_blank_condition_ids(self) -> None:
        from content_ingestion.domain.entities import PredictionEventFetchResult

        raw = {
            "id": "evt_11",
            "title": "E",
            "markets": [
                {"conditionId": "0xaaa"},
                {"conditionId": "0xaaa"},  # duplicate
                {"conditionId": "  "},  # blank
                {"question": "no condition id"},  # missing
                {"conditionId": "0xccc"},
            ],
        }
        result = PredictionEventFetchResult.from_gamma_response(raw, _utc_now())
        assert result.member_condition_ids == ("0xaaa", "0xccc")

    def test_no_markets_field_yields_empty_tuple(self) -> None:
        from content_ingestion.domain.entities import PredictionEventFetchResult

        raw = {"id": "evt_12", "title": "E"}
        result = PredictionEventFetchResult.from_gamma_response(raw, _utc_now())
        assert result.member_condition_ids == ()
        assert result.market_count == 0
