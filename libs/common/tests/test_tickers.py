"""Tests for common.tickers.strip_exchange_qualifier.

These pin the two behaviours that matter for entity dedup:
  1. Recognised exchange suffixes collapse to the bare symbol (the fix).
  2. Share classes and preferred-share notations are NEVER stripped (the guard).
"""

from __future__ import annotations

import pytest

from common.tickers import strip_exchange_qualifier


class TestStripsExchangeSuffix:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("AAPL.MX", "AAPL"),  # Apple on Mexico's BMV
            ("NVDA.US", "NVDA"),  # EODHD US-composite form
            ("AVGO.US", "AVGO"),
            ("BABA.US", "BABA"),
            ("VALE.SA", "VALE"),  # Brazil
            ("GGAL.BA", "GGAL"),  # Argentina
            ("SQM.SN", "SQM"),  # Chile
            ("0700.HK", "0700"),  # Hong Kong
            ("SAP.XETRA", "SAP"),  # Deutsche Börse
            ("aapl.us", "aapl"),  # suffix match is case-insensitive
            ("  AAPL.MX  ", "AAPL"),  # surrounding whitespace tolerated
        ],
    )
    def test_known_suffix_is_stripped(self, raw: str, expected: str) -> None:
        assert strip_exchange_qualifier(raw) == expected


class TestPreservesNonExchangeDotted:
    @pytest.mark.parametrize(
        "raw",
        [
            "BRK.A",  # single-letter share class — must survive
            "BRK.B",
            "JPM.PRM",  # preferred-share notation — distinct instrument
            "BAC.PRK",
            "AAPL",  # no dot at all
            "GOOG",
        ],
    )
    def test_non_exchange_symbol_is_unchanged(self, raw: str) -> None:
        assert strip_exchange_qualifier(raw) == raw


class TestEdgeCases:
    def test_none_passes_through(self) -> None:
        assert strip_exchange_qualifier(None) is None

    def test_empty_passes_through(self) -> None:
        assert strip_exchange_qualifier("") == ""

    def test_only_suffix_with_empty_base_is_not_stripped(self) -> None:
        # Pathological ".US" has an empty base; leave it untouched.
        assert strip_exchange_qualifier(".US") == ".US"

    def test_only_last_dot_is_split(self) -> None:
        # A dotted base with a trailing exchange code strips just the code.
        assert strip_exchange_qualifier("BRK.A.US") == "BRK.A"

    def test_unknown_suffix_is_unchanged(self) -> None:
        # ".XYZ" is not a known exchange code.
        assert strip_exchange_qualifier("FOO.XYZ") == "FOO.XYZ"
