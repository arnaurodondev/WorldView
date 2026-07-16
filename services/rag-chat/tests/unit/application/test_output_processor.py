"""Unit tests for OutputProcessor (T-F-4-01)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rag_chat.application.pipeline.output_processor import OutputProcessor
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

pytestmark = pytest.mark.unit


def _item(item_id: str = "chunk-1", score: float = 0.85) -> RetrievedItem:
    return RetrievedItem.create(
        item_id=item_id,
        item_type=ItemType.chunk,
        text="Apple reported record revenue of $120B.",
        score=score,
        trust_weight=0.90,
        citation_meta=CitationMeta(
            title="Apple 10-K 2024",
            url="https://sec.gov/apple",
            source_name="SEC",
            published_at=datetime(2024, 1, 15, tzinfo=UTC),
            entity_name="Apple Inc",
        ),
    )


@pytest.fixture
def processor() -> OutputProcessor:
    return OutputProcessor()


@pytest.mark.unit
def test_output_strips_think_tags(processor: OutputProcessor) -> None:
    """<think>...</think> block is removed from output."""
    raw = "<think>Internal reasoning here</think>The answer is [1]."
    items = [_item()]

    answer, _ = processor.process(raw, items)
    assert "<think>" not in answer
    assert "Internal reasoning" not in answer
    assert "The answer is" in answer


@pytest.mark.unit
def test_output_strips_reasoning_tags(processor: OutputProcessor) -> None:
    """<reasoning> block is removed from output."""
    raw = "<reasoning>Some reasoning</reasoning>Clean answer [1]."
    items = [_item()]

    answer, _ = processor.process(raw, items)
    assert "<reasoning>" not in answer
    assert "Clean answer" in answer


@pytest.mark.unit
def test_output_parses_citation_markers(processor: OutputProcessor) -> None:
    """[1] in answer -> citations[0] populated."""
    raw = "Apple revenue grew [1]."
    items = [_item("chunk-1")]

    _answer, citations = processor.process(raw, items)
    assert len(citations) == 1
    assert citations[0].ref == 1
    assert citations[0].title == "Apple 10-K 2024"
    assert citations[0].id == "chunk-1"


@pytest.mark.unit
def test_output_news_citation_carries_url_source_published(processor: OutputProcessor) -> None:
    """A well-formed news/doc item surfaces url + source_name + published_at.

    Guards the happy path: when the upstream gives us real values they must
    reach the Citation verbatim (this is what powers the frontend "Read ↗"
    link and the source/date labels).
    """
    raw = "Apple beat estimates [1]."
    _, citations = processor.process(raw, [_item("chunk-1")])

    assert len(citations) == 1
    assert citations[0].url == "https://sec.gov/apple"
    assert citations[0].source_name == "SEC"
    assert citations[0].published_at == datetime(2024, 1, 15, tzinfo=UTC)


@pytest.mark.unit
def test_grounded_prediction_and_news_answer_carries_clickable_urls(processor: OutputProcessor) -> None:
    """2026-07-15 prod-review (empty source-links): a grounded news + prediction-
    market answer must ship citations that carry real, clickable source URLs.

    Fundamentals legitimately have no url, but news (article link), SEC filings
    (EDGAR link), and prediction markets (Polymarket event link) DO. This guards
    the end-to-end path: when the handler set a url on the item, it must survive
    into the Citation both tools' answers cite.
    """
    prediction_item = RetrievedItem.create(
        item_id="tool:prediction_market:trump-2028",
        item_type=ItemType.financial,
        text="Will Donald Trump win the 2028 US Presidential Election? — 28%",
        score=0.8,
        trust_weight=0.85,
        citation_meta=CitationMeta(
            title="Will Donald Trump win the 2028 US Presidential Election?",
            url="https://polymarket.com/event/trump-2028-president",
            source_name="Polymarket",
            published_at=datetime(2026, 7, 14, tzinfo=UTC),
            entity_name="Donald Trump",
        ),
    )
    news_item = RetrievedItem.create(
        item_id="tool:entity_news:abc",
        item_type=ItemType.chunk,
        text="Apple unveils new chip",
        score=0.7,
        trust_weight=0.85,
        citation_meta=CitationMeta(
            title="Apple unveils new chip",
            url="https://news.example.com/apple-chip",
            source_name="eodhd_news",
            published_at=datetime(2026, 7, 10, tzinfo=UTC),
            entity_name="AAPL",
        ),
    )

    raw = "Markets give Trump 28% [1]. Separately, Apple unveiled a new chip [2]."
    _, citations = processor.process(raw, [prediction_item, news_item])

    assert len(citations) == 2
    by_ref = {c.ref: c for c in citations}
    assert by_ref[1].url == "https://polymarket.com/event/trump-2028-president"
    assert by_ref[2].url == "https://news.example.com/apple-chip"
    # Every grounded citation is clickable — no null urls on a linkable source.
    assert all(c.url for c in citations)


@pytest.mark.unit
def test_output_empty_string_url_source_normalised_to_none(processor: OutputProcessor) -> None:
    """Empty-string url/source_name/title from upstream collapse to None.

    The /briefing-articles feed behind get_entity_news coerces a missing
    url/source_name to "" (``row["url"] or ""``). Without normalisation the
    Citation would carry url="" and the frontend would either render a broken
    "Read ↗" link or a blank source label. We assert the choke point cleans it.
    """
    item = RetrievedItem.create(
        item_id="news-1",
        item_type=ItemType.chunk,
        text="Some news body.",
        score=0.5,
        trust_weight=0.85,
        citation_meta=CitationMeta(
            title="   ",  # whitespace-only -> None
            url="",  # empty -> None (no broken link)
            source_name="",  # empty -> None (no blank label)
            published_at=datetime(2026, 6, 30, tzinfo=UTC),
            entity_name="",  # empty -> None
        ),
    )

    _, citations = processor.process("Headline [1].", [item])

    assert len(citations) == 1
    assert citations[0].url is None
    assert citations[0].source_name is None
    assert citations[0].title is None
    assert citations[0].entity_name is None
    # published_at is a real value and must survive untouched.
    assert citations[0].published_at == datetime(2026, 6, 30, tzinfo=UTC)


@pytest.mark.unit
def test_output_citation_out_of_range_ignored(processor: OutputProcessor) -> None:
    """[99] when only 5 items -> citation 99 not in list."""
    raw = "Some answer with [99] invalid reference."
    items = [_item(f"item-{i}") for i in range(5)]

    _, citations = processor.process(raw, items)
    refs = [c.ref for c in citations]
    assert 99 not in refs


@pytest.mark.unit
def test_output_multiple_citations(processor: OutputProcessor) -> None:
    """Multiple [N] references in answer -> multiple citations."""
    raw = "Apple [1] compared to Google [2]."
    items = [_item("apple-chunk"), _item("google-chunk")]

    _, citations = processor.process(raw, items)
    assert len(citations) == 2
    refs = sorted(c.ref for c in citations)
    assert refs == [1, 2]


@pytest.mark.unit
def test_output_no_citations_in_text(processor: OutputProcessor) -> None:
    """Answer with no [N] markers -> empty citations list."""
    raw = "The stock market is volatile."
    items = [_item()]

    answer, citations = processor.process(raw, items)
    assert citations == []
    assert "volatile" in answer


@pytest.mark.unit
def test_output_empty_input(processor: OutputProcessor) -> None:
    """Empty raw output -> empty answer and no citations."""
    answer, citations = processor.process("", [])
    assert answer == ""
    assert citations == []


# ── PLAN-0104 W28-1 / BP-645 regression tests ────────────────────────────────
#
# The bare-citation stripper used to swallow the post-decimal digits of
# values like $7.14 (matching "14" as a citation), turning "$7.14" into
# "$7.". The (?<!\.) lookbehind below guards every numeric form that has
# a decimal in front of a 1-30 integer.


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "EPS was $7.14 this quarter [1].",
        "EPS was $5.11 this quarter [1].",
        "Price was $1.10 [1].",
        "Margin grew 0.25% [1].",
        "Multiple expanded to 1.10x [1].",
        "In Q3 2026 revenue rose [1].",
    ],
)
def test_output_preserves_decimal_values(processor: OutputProcessor, raw: str) -> None:
    """Decimal-fragment digits (e.g. the .14 in $7.14) must not be stripped."""
    items = [_item()]
    answer, _ = processor.process(raw, items)
    # Identify the literal numeric token we want preserved.
    for token in ("$7.14", "$5.11", "$1.10", "0.25%", "1.10x", "Q3 2026"):
        if token in raw:
            assert token in answer, f"Token {token!r} was stripped from {answer!r}"
            break


@pytest.mark.unit
@pytest.mark.parametrize("bare", ["1", "12", "30"])
def test_output_strips_bare_citation_integers(processor: OutputProcessor, bare: str) -> None:
    """Bare citation-range integers NOT wrapped in [N] are still stripped.

    BP-673: a genuinely STRAY citation integer is one that is followed by
    clause-ending punctuation (or end-of-text / a bracketed cite), e.g.
    "Apple grew strongly 12." — the model meant "[12]". Those are still
    stripped. (An integer followed by ``whitespace + a word`` — "12 this
    quarter" — is now PRESERVED as a quantity; see
    ``test_output_preserves_integer_before_any_word``.)
    """
    items = [_item()]
    raw = f"Apple grew strongly this quarter {bare}. See [1]."
    answer, _ = processor.process(raw, items)
    # The bare digit should be gone; the bracketed [1] citation survives.
    assert f" {bare}." not in answer
    assert "[1]" in answer


# ── BP-670 regression — date/time fragments must survive the bare-int strip ──
#
# Live BTC-USD verification (2026-06-11): the final answer rendered as
# "the most recent -minute bar (2026-06- :)" — the stripper swallowed the
# "1" of "1-minute", the "11" day of "2026-06-11" and both halves of
# "10:10". The Apple-news trace showed the same with "(June 9-13)" →
# "(June -)". Hyphen/colon-adjacent integers are date/time fragments,
# never bare citation refs.


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "token"),
    [
        ("Trading at $62,836 as of the most recent 1-minute bar [1].", "1-minute"),
        ("Latest bar timestamp 2026-06-11 10:10 [1].", "2026-06-11 10:10"),
        ("WWDC runs June 9-13 this year [1].", "9-13"),
        ("The 5-day window shows gains [1].", "5-day"),
    ],
)
def test_output_preserves_date_time_fragments(processor: OutputProcessor, raw: str, token: str) -> None:
    items = [_item()]
    answer, _ = processor.process(raw, items)
    assert token in answer, f"Token {token!r} was stripped from {answer!r}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "token"),
    [
        ("Apple EU AI delay drew attention *(Jun 9)* [1].", "(Jun 9)"),
        ("WWDC runs June 9–13, 2026 [1].", "9–13"),  # noqa: RUF001 — en dash
    ],
)
def test_output_preserves_paren_dates_and_endash_ranges(processor: OutputProcessor, raw: str, token: str) -> None:
    """BP-670 follow-up: '(Jun 9)' rendered as '(Jun )' in the live Apple run."""
    items = [_item()]
    answer, _ = processor.process(raw, items)
    assert token in answer, f"Token {token!r} was stripped from {answer!r}"


# ── BP-672 regression — leading-digit deletion adjacent to bold / commas / ────
#    units / multipliers / month-day dates.
#
# Live MSTR-news run (run_20260609T175104Z/q_ru_mstr_news_run2.json): the
# bare-citation stripper ate the leading digit of legitimate quantities,
# yielding artifacts such as:
#   "**8,095 BTC**"           -> "**,095 BTC**"   (comma-grouped number)
#   "last 4 quarters"         -> "last  quarters" (count + unit noun)
#   "nearly 2x the revenue"   -> "nearly x the ..." (multiplier sign U+00D7/x)
#   "Direct Partnership (1 hop)" -> "( hop)"       (graph-hop count)
#   "| May 26 | $165.38 |"    -> "| May  | …"      (month-day date in a table)
# Each shape is now guarded by _BARE_CITATION_INT_RE so the digit survives.


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "token"),
    [
        # Comma-grouped number — leading group must survive.
        ("It purchased an additional **8,095 BTC** at auction [1].", "8,095"),
        ("Total holdings reached 26,500 BTC this year [1].", "26,500"),
        # Count + unit noun.
        ("Revenue rose over the last 4 quarters [1].", "4 quarters"),
        ("The path is just 1 hop away [1].", "1 hop"),
        ("Volume hit 4 million shares [1].", "4 million"),
        ("Shares fell over 2 weeks [1].", "2 weeks"),
        # Multiplier sign (U+00D7 and ASCII x).
        ("It traded at nearly 2× the revenue [1].", "2×"),  # noqa: RUF001 — U+00D7 multiplication sign
        ("Roughly 3x the prior level [1].", "3x"),
        # Month-day calendar dates (full + abbreviated month names).
        ("Closed on May 26 at the high [1].", "May 26"),
        ("Reported Jun 1 results [1].", "Jun 1"),
        ("Scheduled for September 9 [1].", "September 9"),
    ],
)
def test_output_preserves_leading_digit_of_quantities(processor: OutputProcessor, raw: str, token: str) -> None:
    """BP-672: leading digits of bold/comma/unit/multiplier/date numbers survive."""
    items = [_item()]
    answer, _ = processor.process(raw, items)
    assert token in answer, f"Token {token!r} was stripped from {answer!r}"


@pytest.mark.unit
def test_output_bug_a_mstr_btc_acquisition_line(processor: OutputProcessor) -> None:
    """BP-672 end-to-end: the exact MSTR sentence no longer loses the '8'."""
    items = [_item()]
    raw = "The company recently purchased an additional **8,095 BTC** for " "approximately **$271.47 million** [1]."
    answer, _ = processor.process(raw, items)
    assert "**,095 BTC**" not in answer, f"Leading digit lost: {answer!r}"
    assert "**8,095 BTC**" in answer


# ── BP-673 regression — integer-before-ANY-word must survive ──────────────────
#
# Round-2 live evidence (run_20260612T041327Z) — the BP-672 unit-noun allow-list
# still dropped the count digit when the following word was NOT on the list or
# was capitalised:
#   q_ru_nvda_amd_revenue_4q_run2: stream "over the last 4 reported quarters" ->
#       final "over the last  reported quarters" ("reported" is an adjective,
#       not a unit noun → "4" deleted).
#   q_ru_mstr_news_run1: stream "Latest Headlines (Last 14 Days)" -> final
#       "(Last  Days)" ("Days" is capitalised → allow-list missed it).
# The fail-safe rule (strip only before punctuation / cite / EOS) preserves both.


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "token"),
    [
        # Verbatim round-2 residuals.
        ("Revenue grew over the last 4 reported quarters [1].", "4 reported quarters"),
        ("## Latest Headlines (Last 14 Days)\n\nNews here [1].", "Last 14 Days"),
        # The general principle: a digit before ANY word (any case, any word).
        ("It rose 5 percent overall [1].", "5 percent"),
        ("There were 12 analysts covering it [1].", "12 analysts"),
        ("Spanning 7 trading sessions [1].", "7 trading"),
        ("A 3 standard-deviation move [1].", "3 standard"),
        ("Up 9 consecutive days [1].", "9 consecutive"),
        ("Within 2 Business Days [1].", "2 Business"),
    ],
)
def test_output_preserves_integer_before_any_word(processor: OutputProcessor, raw: str, token: str) -> None:
    """BP-673: an integer followed by whitespace+word is a quantity, never stripped."""
    items = [_item()]
    answer, _ = processor.process(raw, items)
    assert token in answer, f"Token {token!r} was stripped from {answer!r}"


@pytest.mark.unit
def test_output_bug_a_nvda_amd_revenue_4q_verbatim(processor: OutputProcessor) -> None:
    """BP-673 end-to-end: round-2 q_ru_nvda_amd_revenue_4q_run2 residual.

    Streamed "over the last 4 reported quarters"; the final answer used to read
    "over the last  reported quarters".
    """
    items = [_item()]
    raw = "Both companies reported revenue growth over the last 4 reported quarters [1]."
    answer, _ = processor.process(raw, items)
    assert "last  reported quarters" not in answer, f"'4' was deleted: {answer!r}"
    assert "last 4 reported quarters" in answer


@pytest.mark.unit
def test_output_bug_a_mstr_news_last_14_days_verbatim(processor: OutputProcessor) -> None:
    """BP-673 end-to-end: round-2 q_ru_mstr_news_run1 residual.

    Streamed "Latest Headlines (Last 14 Days)"; the final answer used to read
    "(Last  Days)" because "Days" is capitalised and missed the allow-list.
    """
    items = [_item()]
    raw = "### Latest Headlines (Last 14 Days)\n\nA recent piece [1]."
    answer, _ = processor.process(raw, items)
    assert "(Last  Days)" not in answer, f"'14' was deleted: {answer!r}"
    assert "(Last 14 Days)" in answer


# ── R3 (2026-07-03): PII redaction must NOT corrupt inline EDGAR URLs ──────────
# Root cause: docs/audits/2026-07-03-chat-bug2-bug4-rootcause.md §R3. The phone
# regex matched the 10-digit SEC accession prefix embedded in a filing index URL
# and redacted it to [REDACTED], breaking the clickable link in the answer prose.


@pytest.mark.unit
def test_redact_pii_preserves_edgar_accession_url() -> None:
    """A SEC EDGAR index URL survives PII redaction verbatim (R3)."""
    from rag_chat.application.pipeline.output_processor import _redact_pii

    url = "https://www.sec.gov/Archives/edgar/data/1498547/000119312526286851/0001193125-26-286851-index.htm"
    text = f"Apple's 10-K is filed here: {url}"
    out = _redact_pii(text)
    assert "[REDACTED]" not in out, f"URL accession was redacted: {out!r}"
    assert url in out, f"EDGAR URL not preserved verbatim: {out!r}"


@pytest.mark.unit
def test_contains_pii_ignores_url_embedded_digit_runs() -> None:
    """URL-embedded accession runs do not trip the PII detector (no false log)."""
    from rag_chat.application.pipeline.output_processor import _contains_pii

    url = "https://www.sec.gov/Archives/edgar/data/1498547/000119312526286851/0001193125-26-286851-index.htm"
    assert _contains_pii(f"Filing: {url}") is False


@pytest.mark.unit
def test_redact_pii_still_redacts_real_phone_outside_url() -> None:
    """Genuine PII outside a URL is still redacted (guard not weakened)."""
    from rag_chat.application.pipeline.output_processor import _contains_pii, _redact_pii

    text = "Call investor relations at 415-555-0198 for details."
    assert _contains_pii(text) is True
    assert "[REDACTED]" in _redact_pii(text)
    assert "415-555-0198" not in _redact_pii(text)


@pytest.mark.unit
def test_redact_pii_mixed_url_and_phone() -> None:
    """PII outside the URL is redacted while the URL span is preserved."""
    from rag_chat.application.pipeline.output_processor import _redact_pii

    url = "https://www.sec.gov/Archives/edgar/data/1498547/000119312526286851/0001193125-26-286851-index.htm"
    text = f"See {url} or call 212-555-0147."
    out = _redact_pii(text)
    assert url in out
    assert "212-555-0147" not in out
    assert "[REDACTED]" in out


@pytest.mark.unit
def test_output_process_keeps_edgar_url_in_answer(processor: OutputProcessor) -> None:
    """End-to-end through process(): EDGAR link in prose stays intact (R3)."""
    url = "https://www.sec.gov/Archives/edgar/data/1498547/000119312526286851/0001193125-26-286851-index.htm"
    items = [_item()]
    raw = f"Apple's most recent filing is available at {url} [1]."
    answer, _ = processor.process(raw, items)
    assert url in answer, f"EDGAR URL mangled by output pipeline: {answer!r}"
    assert "[REDACTED]" not in answer


# ── NEW-4 (2026-07-06): PII redaction must NOT mask financial magnitudes ───────
# Root cause: docs/audits/2026-07-06-r1-final-exhaustive-qa.md NEW-4. The phone
# regex matched the 11-digit integer part of a screener market-cap float
# (``10440000000.0`` -> ``[REDACTED].0``) and the credit-card regex matched
# 13-16 digit caps (``3010000000000``). These are financial values, not PII.


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "10440000000.0",  # the exact NEW-4 repro: 11-digit float integer part
        "3010000000000.0",  # ~$3.01T market-cap raw float (13-digit integer part)
        "$10.44 B",  # unit-suffixed cap
        "$3.01T",  # unit-suffixed cap, no space
        "10.44 billion",  # spelled-out unit suffix
        "3,010,000,000,000",  # comma-grouped large integer
        "$3,010,000,000,000",  # $-prefixed comma-grouped
        "$391.02",  # share price
        "up 42% to $150.25",  # price in prose
        "revenue of 97,690,000,000",  # comma-grouped revenue
    ],
)
def test_redact_pii_preserves_financial_values(value: str) -> None:
    """Legitimate financial magnitudes pass through PII redaction unredacted."""
    from rag_chat.application.pipeline.output_processor import _contains_pii, _redact_pii

    text = f"Market data: {value}."
    assert _redact_pii(text) == text, f"financial value redacted: {_redact_pii(text)!r}"
    assert _contains_pii(text) is False, f"financial value tripped PII detector: {value!r}"


@pytest.mark.unit
def test_output_process_keeps_market_cap_raw_value(processor: OutputProcessor) -> None:
    """End-to-end NEW-4: screener market-cap raw float survives the pipeline."""
    items = [_item()]
    raw = "JKHY market cap $10.44 B (raw: 10440000000.0) [1]."
    answer, _ = processor.process(raw, items)
    assert "[REDACTED]" not in answer, f"market cap redacted: {answer!r}"
    assert "10440000000.0" in answer
    assert "$10.44 B" in answer


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        # R19: genuine PII must STILL be redacted — the fix must not weaken it.
        ("Call investor relations at 415-555-0198 today.", "415-555-0198"),
        ("Dotted phone 212.555.0147 here.", "212.555.0147"),
        ("Spaced phone +1 415 555 0198 here.", "415 555 0198"),
        ("Bare phone 4155550198 here.", "4155550198"),
        ("SSN on file 123-45-6789 redact me.", "123-45-6789"),
        ("Card number 4111 1111 1111 1111 charged.", "4111 1111 1111 1111"),
        ("Reach me at jane.doe@example.com please.", "jane.doe@example.com"),
    ],
)
def test_redact_pii_still_redacts_real_pii_after_financial_exemption(text: str, leaked: str) -> None:
    """Real phone / SSN / card / email is still redacted (R19 — no weakening)."""
    from rag_chat.application.pipeline.output_processor import _contains_pii, _redact_pii

    assert _contains_pii(text) is True, f"PII no longer detected: {text!r}"
    out = _redact_pii(text)
    assert "[REDACTED]" in out
    assert leaked not in out, f"PII leaked through: {out!r}"


@pytest.mark.unit
def test_redact_pii_mixed_financial_and_phone() -> None:
    """A market cap survives while a real phone in the same sentence is redacted."""
    from rag_chat.application.pipeline.output_processor import _redact_pii

    text = "Cap $3.01T — call 415-555-0198 for the deck."
    out = _redact_pii(text)
    assert "$3.01T" in out
    assert "415-555-0198" not in out
    assert "[REDACTED]" in out
