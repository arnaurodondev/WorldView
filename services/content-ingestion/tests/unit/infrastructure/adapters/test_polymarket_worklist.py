"""Unit tests for the shared Polymarket ``markets`` work-list parser (PLAN-0056 B4)."""

from __future__ import annotations

import pytest
from content_ingestion.infrastructure.adapters.polymarket_worklist import MarketWorkItem, parse_markets

pytestmark = pytest.mark.unit


class TestParseMarkets:
    def test_parses_condition_id_and_token_ids(self) -> None:
        items = parse_markets({"markets": [{"condition_id": "cond_1", "token_ids": ["tok_a", "tok_b"]}]})
        assert items == [MarketWorkItem(condition_id="cond_1", token_ids=["tok_a", "tok_b"])]

    def test_accepts_camelcase_aliases(self) -> None:
        # Raw Gamma /markets uses camelCase (conditionId / clobTokenIds).
        items = parse_markets({"markets": [{"conditionId": "cond_2", "clobTokenIds": ["tok_x"]}]})
        assert items == [MarketWorkItem(condition_id="cond_2", token_ids=["tok_x"])]

    def test_multiple_markets_preserved(self) -> None:
        items = parse_markets(
            {
                "markets": [
                    {"condition_id": "cond_a", "token_ids": ["t1", "t2"]},
                    {"condition_id": "cond_b", "token_ids": ["t3"]},
                ]
            }
        )
        assert [i.condition_id for i in items] == ["cond_a", "cond_b"]
        assert [len(i.token_ids) for i in items] == [2, 1]

    def test_missing_markets_key_returns_empty(self) -> None:
        assert parse_markets({}) == []
        assert parse_markets({"token_ids": ["tok_a"]}) == []

    def test_malformed_entries_skipped_and_empty_token_ids_tolerated(self) -> None:
        items = parse_markets({"markets": ["not_a_dict", {"condition_id": "cond_only"}]})
        # The string entry is skipped; the dict with no token_ids yields an empty list.
        assert items == [MarketWorkItem(condition_id="cond_only", token_ids=[])]

    def test_missing_condition_id_yields_none(self) -> None:
        items = parse_markets({"markets": [{"token_ids": ["tok_a"]}]})
        assert items == [MarketWorkItem(condition_id=None, token_ids=["tok_a"])]
