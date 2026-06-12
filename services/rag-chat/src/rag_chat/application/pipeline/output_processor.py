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
_BARE_CITATION_INT_RE = re.compile(
    r"(?<!\[)"  # not preceded by [ (not already a citation)
    r"(?<!\$)"  # not preceded by $ (not a currency value)
    r"(?<!\d)"  # not preceded by digit (not mid-number like "2024")
    r"(?<!\.)"  # PLAN-0104 W28-1 / BP-645: not preceded by '.' — guards the
    # post-decimal digits of "$7.14", "0.25%", "1.10x" so we don't strip
    # the "14"/"11" half of a decimal as a phantom bare citation.
    r"(?<![-–—:])"  # BP-670: not preceded by hyphen/en-dash/em-dash/colon —  # noqa: RUF001
    # guards the day half of ISO dates ("2026-06-11"), range tails
    # ("9-13", "9-13" with en dash) and minutes ("10:10") from being stripped.
    r"(?<![*_])"  # BP-672: not preceded by markdown bold/italic delimiter — the
    # leading digit of a bolded number ("**8,095 BTC**", "**4** quarters") sits
    # directly after the ``**``/``*``/``_`` run; without this guard the "8" of
    # "**8,095**" rendered as "**,095**" in the live MSTR-news answer.
    # BP-672: not preceded by a month name (+ single space) — "May 26",
    # "Jun 1", "September 9" are calendar days, never citation refs. The live
    # MSTR price table rendered "| May 26 |" as "| May  |" because the day was
    # stripped. ``(?i:...)`` scopes case-insensitivity to the lookbehind only
    # (the global pattern stays case-sensitive); covers full + 3-letter forms.
    r"(?<!(?i:jan) )(?<!(?i:feb) )(?<!(?i:mar) )(?<!(?i:apr) )(?<!(?i:may) )"
    r"(?<!(?i:jun) )(?<!(?i:jul) )(?<!(?i:aug) )(?<!(?i:sep) )(?<!(?i:oct) )"
    r"(?<!(?i:nov) )(?<!(?i:dec) )(?<!(?i:january) )(?<!(?i:february) )"
    r"(?<!(?i:march) )(?<!(?i:april) )(?<!(?i:june) )(?<!(?i:july) )"
    r"(?<!(?i:august) )(?<!(?i:september) )(?<!(?i:october) )"
    r"(?<!(?i:november) )(?<!(?i:december) )"
    r"\b([1-9]|[12]\d|30)\b"  # integers 1-30 (citation-range only)
    r"(?!\])"  # not followed by ] (not an existing citation)
    r"(?!\d)"  # not followed by digit (not a year)
    r"(?!,\d)"  # BP-672: not followed by ",digit" — the leading group of a
    # comma-grouped number ("8,095", "26,500"). Without this the "8" of
    # "8,095 BTC" was stripped, yielding the live "**,095 BTC**" artifact.
    r"(?![×xX])"  # noqa: RUF001 — BP-672: not followed by a multiplier sign (U+00D7 or
    # ASCII x) — "2x" / "2 times" is a multiple ("nearly 2x the revenue"),
    # never a citation. The live answer dropped the "2" leaving "nearly the
    # revenue" with a stray multiplier sign.
    r"(?![%./\w:)–—-])"  # not followed by unit / word char / decimal point /  # noqa: RUF001
    # BP-670: compound joiners and closing paren — "1-minute", "10:10",
    # "9-13", en-dash ranges and parenthesised dates "(Jun 9)" are time/date
    # fragments, never bare citation refs ("(Jun 9)" used to render as
    # "(Jun )" and "1-minute bar" as "-minute bar" in the final answer).
    r"(?!\s+(?:hop|hops|quarter|quarters|million|billion|trillion|thousand|"  # BP-672:
    r"shares|days?|weeks?|months?|years?|hours?|minutes?|times?|x\b|bps|"
    # not a bare citation when immediately followed by a unit / quantity noun.
    # The live MSTR answer dropped the count digit from "4 quarters", "1 hop",
    # "26 close" and "nearly 2x the revenue" because the stripper treated the
    # quantity as a citation ref. A genuine bare citation ref is never followed
    # by a counting noun. Kept as an explicit allow-list (not a generic
    # ``\s+\w`` guard) so we still strip the legacy "grew strongly 12 [1]" form.
    r"bn|mn|k\b|BTC|ETH|USD|EUR|GBP|%|percent))"
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
