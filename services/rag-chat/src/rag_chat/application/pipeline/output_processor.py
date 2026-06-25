"""Output processor - Steps 12-13 of the RAG pipeline (T-F-4-01).

Strips LLM reasoning blocks, detects PII in output,
parses [N] citation markers, and builds the citations list.
"""

from __future__ import annotations

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


def _contains_pii(text: str) -> bool:
    return any(p.search(text) for p in _PII_PATTERNS)


def _redact_pii(text: str) -> str:
    for pattern in _PII_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


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
                    title=item.citation_meta.title,
                    url=item.citation_meta.url,
                    source_name=item.citation_meta.source_name,
                    published_at=item.citation_meta.published_at,
                    entity_name=item.citation_meta.entity_name,
                    confidence=item.score,
                    # Persist the full retrieved-chunk text into the Citation
                    # so the citation-judge cron can score grounding against the
                    # actual payload (BP-NEW PLAN-0099 W4). Stripped before SSE
                    # by emit_citations so the frontend wire shape is unchanged.
                    text=item.text,
                )
            )

        return text, citations
