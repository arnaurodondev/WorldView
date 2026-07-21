"""Tests for common.tickers.strip_exchange_qualifier.

These pin the two behaviours that matter for entity dedup:
  1. Recognised exchange suffixes collapse to the bare symbol (the fix).
  2. Share classes and preferred-share notations are NEVER stripped (the guard).
"""

from __future__ import annotations

import pytest

from common.tickers import strip_exchange_prefix, strip_exchange_qualifier


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


class TestStripsExchangePrefix:
    """R2: a leading ``EXCHANGE:`` prefix must never become a canonical_name.

    docs/audits/2026-07-16-kg-data-quality-eval.md flagged 87 junk canonical
    entities (``NYSE: BCS``, ``NASDAQ:GDDY`` …) minted from raw GLiNER spans.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("NYSE: BCS", "BCS"),
            ("NASDAQ:AAPL", "AAPL"),
            ("NASDAQ: AAPL", "AAPL"),
            ("LSE: TSCO", "TSCO"),
            ("NSE: INFY", "INFY"),
            ("NYSE:GDDY", "GDDY"),
            ("  NYSE: BCS  ", "BCS"),  # surrounding whitespace tolerated
        ],
    )
    def test_leading_exchange_prefix_is_stripped(self, raw: str, expected: str) -> None:
        assert strip_exchange_prefix(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "Apple Inc.",  # ordinary company name
            "Vroom: The Car Company",  # colon but leading token is not all-caps
            "British Land",
            "AXA SA",
            "BCS",  # already bare
            "S&P Global",
        ],
    )
    def test_non_prefixed_name_is_unchanged(self, raw: str) -> None:
        assert strip_exchange_prefix(raw) == raw

    @pytest.mark.parametrize(
        "raw",
        [
            # ADVERSARIAL: the ``TOKEN: REST`` shape shared by financial ratios and
            # shorthand labels. These WOULD be mangled by a naive ``^[A-Z]{2,6}:``
            # rule (EV:EBITDA -> "EBITDA", AI: Foundry -> "Foundry"). The venue
            # allowlist makes the strip intentional: EV / AI / P / ROIC are NOT
            # exchange codes, so the value must survive verbatim.
            "EV:EBITDA",
            "EV: EBITDA",
            "EV:Sales",
            "AI: Foundry",
            "AI:Foundry",
            "ROIC: Analysis",
            "TAM: Overview",
        ],
    )
    def test_ratio_and_label_shapes_are_not_stripped(self, raw: str) -> None:
        # Documented behavior: a leading TOKEN that is not a recognised securities
        # venue is left in place (fail-safe: an honest name, never a corrupted one).
        assert strip_exchange_prefix(raw) == raw

    def test_none_and_empty_pass_through(self) -> None:
        assert strip_exchange_prefix(None) is None
        assert strip_exchange_prefix("") == ""

    def test_prefix_only_does_not_manufacture_blank(self) -> None:
        # "NYSE:" (recognised venue) with nothing after would strip to "" — keep
        # the original instead so we never write a blank canonical name.
        assert strip_exchange_prefix("NYSE:") == "NYSE:"

    def test_unrecognised_venue_prefix_is_left_in_place(self) -> None:
        # Fail-safe residual: an obscure venue not in _EXCHANGE_PREFIX_CODES keeps
        # its prefix rather than risk mangling a legitimate name. "ZZZ" is not a
        # known code, so the value is returned verbatim.
        assert strip_exchange_prefix("ZZZ: FOO") == "ZZZ: FOO"
