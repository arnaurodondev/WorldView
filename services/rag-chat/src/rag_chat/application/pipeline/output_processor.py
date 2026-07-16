"""Output processor - Steps 12-13 of the RAG pipeline (T-F-4-01).

Strips LLM reasoning blocks, detects PII in output,
parses [N] citation markers, and builds the citations list.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

import structlog

from rag_chat.application.metrics.prometheus import rag_pipeline_stage_input_size
from rag_chat.domain.entities.conversation import Citation

if TYPE_CHECKING:
    from rag_chat.domain.entities.chat import RetrievedItem

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Strip <think>, <reasoning>, <scratchpad> blocks (DeepSeek R1 style)
_THINK_RE = re.compile(
    r"<(think|reasoning|scratchpad)>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)

# Match [N] citation markers in the output (e.g. [1], [12])
_CITATION_RE = re.compile(r"\[(\d+)\]")

# Match [NX] style markers — DeepSeek R1 sometimes emits [N6] meaning "citation 6".
# WHY: The model uses the letter N as a prefix for numeric citation references
# (e.g. [N6], [N7]) instead of plain [6].  We normalise these to [6] before
# citation extraction so _CITATION_RE can match them.
# Do NOT strip — convert them to plain [digit] form first.
_CITATION_N_PREFIX_RE = re.compile(r"\[N(\d+)\]")

# Match [N:X] style markers that DeepSeek R1 sometimes emits instead of plain [N].
# These are not part of our citation protocol — always strip them.
_CITATION_N_COLON_RE = re.compile(r"\s*\[N:\d+\]")

# Strip bare citation-reference integers (1-30) NOT wrapped in [N] brackets.
# WHY: Citation discipline rule 5 — the model is instructed that any number it
# emits without [N] wrapping will be stripped.  This enforces that invariant.
# We only target citation-sized integers (1-30) to avoid stripping legitimate
# numeric content: years (4-digit), "Q3", "FY24", "$1.40", "42%", "3B" are
# all protected by the lookahead/lookbehind guards.
# Applied only when retrieved_items is non-empty (no point stripping when the
# coherence guard above already removed all [N] markers).
# BP-673: the stripper is now NON-DESTRUCTIVE by construction — it ONLY removes
# a bare 1-30 integer when that integer is *followed by clause-ending
# punctuation, a bracketed citation, or end-of-text*. An integer immediately
# followed by ``whitespace + a word`` is ALWAYS a quantity / count / date label
# ("4 reported quarters", "14 Days", "1 hop") and is NEVER stripped, regardless
# of the following word or its case. This replaces the BP-672 unit-noun
# allow-list (which silently dropped digits before any word not on the list —
# e.g. "4 reported", capitalised "14 Days") with the inverse, fail-safe rule:
# prefer leaving a stray citation integer in place over deleting a real number.
#
# Round-2 live evidence (run_20260612T041327Z):
#   q_ru_nvda_amd_revenue_4q_run2: "last 4 reported quarters" -> "last  reported
#       quarters" ("4" dropped before the adjective "reported").
#   q_ru_mstr_news_run1: "Last 14 Days" -> "Last  Days" ("14" dropped before the
#       CAPITALISED "Days", which the case-sensitive allow-list missed).
#
# The leading lookbehinds (currency / decimal / digit / hyphen-colon / bold)
# are retained as belt-and-braces so a stray "5." after "$7." or inside a range
# is still never mistaken for a citation.
_BARE_CITATION_INT_RE = re.compile(
    r"(?<!\[)"  # not preceded by [ (not already a citation)
    r"(?<!\$)"  # not preceded by $ (not a currency value)
    r"(?<!\d)"  # not preceded by digit (not mid-number like "2024")
    r"(?<!\.)"  # PLAN-0104 W28-1 / BP-645: not preceded by '.' — guards the
    # post-decimal digits of "$7.14", "0.25%", "1.10x".
    r"(?<![-–—:])"  # BP-670: not preceded by hyphen/en-dash/em-dash/colon —  # noqa: RUF001
    # guards the day half of ISO dates ("2026-06-11"), range tails ("9-13") and
    # minutes ("10:10") from being stripped.
    r"(?<![*_])"  # BP-672: not preceded by markdown bold/italic delimiter — the
    # leading digit of a bolded number ("**8,095 BTC**") sits directly after the
    # ``**``/``*``/``_`` run.
    # BP-672: not preceded by a month name (+ single space) — "May 26", "Jun 1",
    # "September 9" are calendar days, never citation refs, even when followed by
    # a bracketed citation ("September 9 [1]"). ``(?i:...)`` scopes the
    # case-insensitivity to the lookbehind only; covers full + 3-letter forms.
    r"(?<!(?i:jan) )(?<!(?i:feb) )(?<!(?i:mar) )(?<!(?i:apr) )(?<!(?i:may) )"
    r"(?<!(?i:jun) )(?<!(?i:jul) )(?<!(?i:aug) )(?<!(?i:sep) )(?<!(?i:oct) )"
    r"(?<!(?i:nov) )(?<!(?i:dec) )(?<!(?i:january) )(?<!(?i:february) )"
    r"(?<!(?i:march) )(?<!(?i:april) )(?<!(?i:june) )(?<!(?i:july) )"
    r"(?<!(?i:august) )(?<!(?i:september) )(?<!(?i:october) )"
    r"(?<!(?i:november) )(?<!(?i:december) )"
    r"\b([1-9]|[12]\d|30)\b"  # integers 1-30 (citation-range only)
    r"(?!\d)"  # not followed by digit (not a year / larger number)
    r"(?!\.\d)"  # BP-673: not the integer part of a decimal ("1.10x", "5.3%").
    r"(?!,\d)"  # BP-672: not the lead group of a comma number ("8,095").
    # ── BP-673 fail-safe trailing guard ──────────────────────────────────────
    # Strip ONLY when the integer is followed by clause-ending punctuation, a
    # bracketed citation, or end-of-text. NB: ``:`` and ``)`` are intentionally
    # EXCLUDED from the punctuation class — they delimit times ("10:10") and
    # parenthesised dates ("(Jun 9)"), which must survive. Any ``whitespace +
    # word`` continuation (a quantity / count / date) is therefore NOT matched
    # and the digit is preserved. The legacy "Apple grew strongly 12 this
    # quarter [1]" case — where 12 IS a stray citation but is followed by a
    # word — is deliberately KEPT now: deleting a real number is strictly worse
    # than leaving a stray ref, per the round-2 root-cause directive.
    r"(?=[.,;!?]|\s+\[|\s*\n|\s*\$|\Z)"
)

# Basic PII patterns — email, phone, SSN, credit card
_PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),  # email
    re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # phone
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b(?:\d[ -]?){13,16}\b"),  # credit card (rough)
]

# URL spans are EXEMPT from PII redaction (R3, 2026-07-03 root-cause).
# WHY: the phone pattern matches any bare 10-digit run, and a SEC EDGAR
# accession number embedded in a filing index URL — e.g.
# ``…/000119312526286851/0001193125-26-286851-index.htm`` — contains exactly
# such a run (``0001193125`` → ``000-119-3125``). Redacting it rewrites the URL
# to ``…/[REDACTED]-26-286851-index.htm``, silently breaking every clickable
# EDGAR link the model writes inline. A URL is machine-generated structure, not
# user-entered PII, so we exempt whole ``http(s)://…`` spans rather than
# weakening the phone/SSN/card patterns globally (which would let real PII
# through elsewhere). ``\S+`` greedily consumes the URL up to the next
# whitespace; trailing punctuation kept inside the span is harmless because the
# span is preserved verbatim.
_URL_SPAN_RE = re.compile(r"https?://\S+")

# Financial numeric values are EXEMPT from PII redaction (NEW-4, 2026-07-06
# root-cause; docs/audits/2026-07-06-r1-final-exhaustive-qa.md).
# WHY: the phone pattern matches any 10-/11-digit run (incl. a leading ``1``
# country code) and the credit-card pattern matches any 13-16 digit run. A
# screener market-cap value therefore trips them: the float ``10440000000.0``
# was rewritten to ``[REDACTED].0`` (``1``+``044``+``000``+``0000`` = an 11-digit
# "phone"), and a $3.01T cap ``3010000000000`` matches the 13-digit card range.
# These are machine-emitted financial magnitudes, not user PII, so — exactly as
# with URL spans — we exempt whole financial-number spans instead of weakening
# the phone/SSN/card patterns (which must still catch real PII elsewhere).
# Branches (longest-match-first): ``$``-prefixed money (with optional
# comma-groups / decimal), comma-grouped large integers, unit-suffixed values
# (``$3.01T`` / ``10.44 billion``), and bare decimals (``10440000000.0``).
# The bare-decimal branch is boundary-guarded — ``(?<![.\d]) … (?!\.\d)\b`` — so
# it can NEVER start or stop inside a dot-separated phone (``212.555.0147``),
# leaving that run intact for the phone pattern to redact. Genuine phones / SSNs
# / cards carry no ``$``, comma-thousands, unit suffix, or lone decimal, so no
# exempt branch shields them.
_FINANCIAL_NUM_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"  # $-prefixed money: $10,440,000,000 / $10.44
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"  # comma-grouped: 3,010,000,000,000
    r"|\d+(?:\.\d+)?\s?(?:trillion|billion|million|thousand|[TBMK])\b"  # unit-suffixed
    r"|(?<![.\d])\d+\.\d+(?!\.\d)\b",  # bare decimal: 10440000000.0 (not a dotted phone)
    re.IGNORECASE,
)

# Combined exempt-span matcher: any URL OR any financial number is preserved
# verbatim; PII redaction is applied only to the text BETWEEN these spans.
_EXEMPT_SPAN_RE = re.compile(
    _URL_SPAN_RE.pattern + "|" + _FINANCIAL_NUM_RE.pattern,
    re.IGNORECASE,
)


def _clean_optional_str(value: str | None) -> str | None:
    """Collapse empty / whitespace-only strings to ``None``.

    WHY: upstream feeds are inconsistent about "no value". The S6 chunk-search
    adapter maps a missing url/source_name to ``None`` (``meta.get("url")``),
    but the NLP-pipeline ``/briefing-articles`` endpoint coerces them to the
    empty string (``url=row["url"] or ""``). The latter flows verbatim through
    ``get_entity_news`` -> ``CitationMeta(url="")`` -> ``Citation(url="")`` and
    out over SSE. On the frontend an empty-string url is falsy, so the chip
    falls back to a non-link badge — but ``source_name=""`` would still render
    a blank source label, and a stray ``"   "`` url would slip past the JS
    truthiness guard. Normalising here, at the single citation-building choke
    point, guarantees every news/doc citation carries either a real value or a
    clean ``None`` regardless of which upstream produced it.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _clean_citation_url(value: str | None) -> str | None:
    """Normalise a citation URL: strip, drop empties, and HTML-unescape it.

    WHY unescape (2026-07-16 prod-review deep pass): the NLP-pipeline
    ``/briefing-articles`` feed carries source links HTML-ENTITY-ESCAPED — a real
    Apple news citation came through as
    ``...?utm_source=feed_news_all&amp;utm_medium=referral&amp;feed_item_type=news``.
    ``&amp;`` is HTML encoding, NOT part of the actual URL; a raw ``&`` is the
    correct query-parameter separator. Emitting ``&amp;`` on the SSE wire yields a
    subtly wrong link (the ``amp;`` prefixes leak into param names) that some
    targets reject. Unescape at the single citation-emission choke point so every
    citation URL is a clean, clickable link regardless of the upstream's encoding.
    ``html.unescape`` is a no-op on an already-clean URL.
    """
    stripped = _clean_optional_str(value)
    if stripped is None:
        return None
    return html.unescape(stripped)


def _redact_pii_outside_exempt_spans(text: str) -> str:
    """Apply the PII patterns to ``text`` but keep any exempt span verbatim.

    Exempt spans are URLs (EDGAR accession numbers look like phone numbers,
    ``_URL_SPAN_RE``) and financial numbers (market caps / prices look like
    phone/card numbers, ``_FINANCIAL_NUM_RE`` — NEW-4). We redact only the gaps
    BETWEEN exempt spans and stitch each original span back in untouched.
    """
    out: list[str] = []
    last = 0
    for m in _EXEMPT_SPAN_RE.finditer(text):
        gap = text[last : m.start()]
        for pattern in _PII_PATTERNS:
            gap = pattern.sub("[REDACTED]", gap)
        out.append(gap)
        out.append(m.group(0))  # URL / financial value kept verbatim
        last = m.end()
    tail = text[last:]
    for pattern in _PII_PATTERNS:
        tail = pattern.sub("[REDACTED]", tail)
    out.append(tail)
    return "".join(out)


def _contains_pii(text: str) -> bool:
    # Scan with exempt spans blanked so a URL-embedded digit run (EDGAR
    # accession) or a financial magnitude (market cap / price — NEW-4) does not
    # trigger a spurious PII warning + redaction pass on every filings/screener
    # answer. Real PII outside exempt spans is still detected.
    scan = _EXEMPT_SPAN_RE.sub(" ", text)
    return any(p.search(scan) for p in _PII_PATTERNS)


def _redact_pii(text: str) -> str:
    return _redact_pii_outside_exempt_spans(text)


class OutputProcessor:
    """Process raw LLM output into a clean answer with citations.

    Pipeline:
    1. Strip <think>/<reasoning>/<scratchpad> blocks.
    2. PII scan on output (log warning + redact if detected).
    3. Parse [N] citation markers.
    4. Build citations[] array from retrieved items.
    """

    def process(
        self,
        raw_output: str,
        retrieved_items: list[RetrievedItem],
    ) -> tuple[str, list[Citation]]:
        """Return ``(clean_answer, citations)`` from raw LLM output.

        Args:
            raw_output:       Raw streaming output accumulated from LLM.
            retrieved_items:  Items in the order they were presented in the prompt (index 0 = [1]).
        """
        rag_pipeline_stage_input_size.labels(stage="output_processor").observe(len(retrieved_items))

        # 1. Strip reasoning blocks
        text = _THINK_RE.sub("", raw_output).strip()

        # 1b. Normalise [NX] markers → [X] so _CITATION_RE can extract them.
        # WHY: DeepSeek R1 often emits [N6] meaning "citation 6" rather than [6].
        # Converting them first lets the standard regex handle all citation styles.
        text = _CITATION_N_PREFIX_RE.sub(r"[\1]", text)

        # 1c. Strip [N:X] markers — DeepSeek R1 occasionally emits these instead of
        # the standard [N] format. They are never part of our citation protocol and
        # have no corresponding citation entry in retrieved_items (F-CH-009 fix).
        text = _CITATION_N_COLON_RE.sub("", text)

        # 1d. Strip bare citation-range integers NOT wrapped in [N] brackets.
        # Enforces citation discipline rule 5: numbers without [N] are treated as
        # fabricated. Only applied when retrieved_items exist (the coherence guard
        # above handles the empty-context case separately).
        if retrieved_items:
            text = _BARE_CITATION_INT_RE.sub("", text)

        # 2. PII scan on output
        if _contains_pii(text):
            log.warning("pii_in_llm_output", text_len=len(text))  # type: ignore[no-any-return]
            text = _redact_pii(text)

        # 3. Parse [N] citation markers (1-based)
        refs: set[int] = {int(m) for m in _CITATION_RE.findall(text)}

        # Coherence guard: if no retrieved items were provided (citations will be empty)
        # but the LLM still emitted [N] markers, strip those orphaned markers from the
        # text.  Without this, the user sees "[1] [2]" inline references that point to
        # nothing — worse than having no citations at all.
        if not retrieved_items:
            text = re.sub(r"\s*\[\d+\]", "", text)

        # 4. Build citations list
        citations: list[Citation] = []
        for ref in sorted(refs):
            idx = ref - 1
            if idx < 0 or idx >= len(retrieved_items):
                continue
            item = retrieved_items[idx]
            citations.append(
                Citation(
                    ref=ref,
                    item_type=item.item_type.value,
                    id=item.item_id,
                    title=_clean_optional_str(item.citation_meta.title),
                    # Normalise url/source_name/entity_name so an empty-string
                    # value from an upstream that coerces "missing" to "" (e.g.
                    # the /briefing-articles feed behind get_entity_news) never
                    # reaches the SSE wire as url="" — which the frontend would
                    # have to special-case as a broken "Read ↗" link.
                    url=_clean_citation_url(item.citation_meta.url),
                    source_name=_clean_optional_str(item.citation_meta.source_name),
                    published_at=item.citation_meta.published_at,
                    entity_name=_clean_optional_str(item.citation_meta.entity_name),
                    confidence=item.score,
                    # Persist the full retrieved-chunk text into the Citation
                    # so the citation-judge cron can score grounding against the
                    # actual payload (BP-NEW PLAN-0099 W4). Stripped before SSE
                    # by emit_citations so the frontend wire shape is unchanged.
                    text=item.text,
                )
            )

        return text, citations
