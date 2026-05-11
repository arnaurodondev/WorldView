"""Snippet post-processing helper for FTS results (PLAN-0064 W6).

Converts ts_headline sentinel-byte markers (\\x02 start, \\x03 end) into
plain text plus a list of (start, end) character offset pairs.

The sentinel bytes are configured via ts_headline's StartSel/StopSel options
because they are guaranteed not to appear in any UTF-8 text corpus — control
characters U+0002 and U+0003 are not valid in HTML or prose. This avoids the
HTML-injection risk of using ``<b>``/``</b>`` wrappers (AD-W6-3 snippet
contract). The use case calls this function before returning to the API layer,
so the API response always contains clean plain text + structured offsets.
"""

from __future__ import annotations


def _strip_markers(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Convert ts_headline sentinel markers \\x02/\\x03 to (plain_text, offsets).

    ts_headline returns text like "foo \\x02bar\\x03 baz" where \\x02 marks
    start and \\x03 marks end of each match. This function strips the markers
    and returns the plain text + list of (start, end) char offsets.

    Example:
        >>> _strip_markers("foo \\x02bar\\x03 baz")
        ("foo bar baz", [(4, 7)])

    Orphaned end markers (\\x03 without a preceding \\x02) are silently
    skipped. This can happen if ts_headline truncates in the middle of a
    highlighted span.

    Args:
        text: Raw snippet string from ts_headline with \\x02/\\x03 markers.

    Returns:
        A tuple of (plain_text, offsets) where offsets is a list of
        (start, end) half-open character intervals in the plain text where
        the query matched.
    """
    # Sentinel byte constants — consistent with AsyncpgDocumentSearchRepository
    # which passes chr(2)/chr(3) as ts_headline StartSel/StopSel options.
    start = chr(2)  # \x02 — marks start of a matched fragment
    end = chr(3)  # \x03 — marks end of a matched fragment

    result: list[str] = []  # accumulates plain-text characters
    offsets: list[tuple[int, int]] = []  # (start_char, end_char) pairs

    i = 0
    while i < len(text):
        if text[i] == start:
            # Find the closing end marker, or use end of string if absent.
            # text.index() raises ValueError when not found — use find() with
            # fallback instead to handle orphaned start markers gracefully.
            end_pos = text.find(end, i + 1)
            if end_pos == -1:
                # Orphaned start marker — treat rest of string as a match.
                end_pos = len(text)

            # Record the offset relative to the plain-text result so far.
            start_offset = len("".join(result))
            inner = text[i + 1 : end_pos]  # the matched text between markers
            result.append(inner)
            end_offset = start_offset + len(inner)
            offsets.append((start_offset, end_offset))

            # Advance past the end marker (or to end of string).
            i = end_pos + 1
        elif text[i] == end:
            # Orphaned end marker — skip it without emitting to output.
            i += 1
        else:
            # Regular character — emit as-is.
            result.append(text[i])
            i += 1

    return "".join(result), offsets
