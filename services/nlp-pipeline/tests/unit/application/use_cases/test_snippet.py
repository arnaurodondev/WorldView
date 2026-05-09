"""Unit tests for _strip_markers() snippet helper (PLAN-0064 W6 T-W6-2-03).

Verifies the conversion of ts_headline sentinel bytes (\\x02 start, \\x03 end)
into plain text plus (start, end) character offset pairs.
"""

from __future__ import annotations

import pytest
from nlp_pipeline.application.use_cases._snippet import _strip_markers

pytestmark = pytest.mark.unit

# Sentinel constants — must match those in _snippet.py
_S = chr(2)  # \x02 start marker
_E = chr(3)  # \x03 end marker


class TestStripMarkers:
    def test_single_match(self) -> None:
        """'foo \\x02bar\\x03 baz' → ('foo bar baz', [(4, 7)])."""
        plain, offsets = _strip_markers(f"foo {_S}bar{_E} baz")
        assert plain == "foo bar baz"
        assert offsets == [(4, 7)]

    def test_multiple_matches(self) -> None:
        """Two highlighted spans produce two offset pairs."""
        text = f"The {_S}quick{_E} brown {_S}fox{_E} jumps"
        plain, offsets = _strip_markers(text)
        assert plain == "The quick brown fox jumps"
        # "quick" starts at index 4, ends at 9 (len 5)
        assert offsets[0] == (4, 9)
        # "fox" starts at index 16, ends at 19 (len 3)
        assert offsets[1] == (16, 19)
        assert len(offsets) == 2

    def test_no_markers_returns_empty_offsets(self) -> None:
        """A snippet with no sentinel markers returns (text, [])."""
        plain, offsets = _strip_markers("no markers here")
        assert plain == "no markers here"
        assert offsets == []

    def test_empty_string(self) -> None:
        """Empty input produces empty output and empty offset list."""
        plain, offsets = _strip_markers("")
        assert plain == ""
        assert offsets == []

    def test_adjacent_markers(self) -> None:
        """Two back-to-back highlighted spans with no gap between them."""
        # e.g. "\\x02foo\\x03\\x02bar\\x03"
        text = f"{_S}foo{_E}{_S}bar{_E}"
        plain, offsets = _strip_markers(text)
        assert plain == "foobar"
        assert offsets[0] == (0, 3)  # "foo" at [0, 3)
        assert offsets[1] == (3, 6)  # "bar" at [3, 6)

    def test_orphaned_start_marker(self) -> None:
        """An orphaned start marker (no closing \\x03) consumes rest of string."""
        text = f"before {_S}match"
        plain, offsets = _strip_markers(text)
        # Everything from the start marker onwards is treated as a match
        assert plain == "before match"
        assert offsets == [(7, 12)]  # "match" at [7, 12)

    def test_orphaned_end_marker(self) -> None:
        """An orphaned end marker (no preceding \\x02) is silently skipped."""
        text = f"before{_E}after"
        plain, offsets = _strip_markers(text)
        assert plain == "beforeafter"
        assert offsets == []

    def test_match_at_start(self) -> None:
        """Highlighted span starting at position 0 produces offset (0, N)."""
        plain, offsets = _strip_markers(f"{_S}hello{_E} world")
        assert plain == "hello world"
        assert offsets == [(0, 5)]

    def test_match_at_end(self) -> None:
        """Highlighted span at the very end of the string."""
        plain, offsets = _strip_markers(f"some text {_S}end{_E}")
        assert plain == "some text end"
        assert offsets == [(10, 13)]

    def test_unicode_characters(self) -> None:
        """Offset positions are measured in Unicode code-points, not bytes."""
        # "café" is 4 code-points; "au" is 2
        plain, offsets = _strip_markers(f"café {_S}au{_E} lait")
        assert plain == "café au lait"
        # "au" starts at position 5 (after "café ")
        assert offsets == [(5, 7)]
