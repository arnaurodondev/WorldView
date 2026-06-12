"""Post-tool entity-name grounding validator (F-LIVE-NEW-002).

Detects proper-noun entity names in the LLM response that were NOT in
the grounded set (resolved entities + tool-result citation metadata).
Sibling to :mod:`numeric_grounding` — same shape, same conventions, same
re-prompt + banner flow — but for *names* instead of *numbers*.

The canonical failure this guards against (F-LIVE-NEW-002): the empty-
result synthesis branch in ``chat_orchestrator`` previously prompted the
LLM with a generic "no data was found" instruction WITHOUT naming the
resolved entity. With no anchor the LLM frequently substituted a
plausible alternative — e.g. a Tesla question answered with
"ServiceNow is a leading provider..." That hallucination is now caught
here even when the entity-anchored prompt fix (Fix 1) doesn't prevent
it.

Design choices:

1. **Fail-safe**: tuned to false-positive-OK / false-negative-NEVER.
   When in doubt, flag — the rewrite + banner cost less than a confident
   wrong answer. The orchestrator runs ONE rewrite; if it still fails we
   append a banner rather than refuse outright.

2. **Stop-noun list** for everyday Title-Cased prose: countries, days,
   months, currencies, common English titles. These should never be
   flagged as ungrounded "entities" because they aren't company-like
   references the user could verify.

3. **Per-NameKind disposition**: COMPANY / TICKER fail closed (must be in
   the grounded set). PERSON / PLACE are soft — surfaced as warnings
   but never block. This is the same pattern as numeric_grounding's
   FieldKind tolerances.

4. **Ticker normalisation**: ``$AAPL`` ≡ ``AAPL`` ≡ ``aapl`` for set
   comparisons. Cashtags and bare 2-5-letter all-caps tokens both
   collapse to a single normalised form.

5. **Deterministic**: no LLM call, no I/O. Same inputs → same outputs.
   Reproducible from stored fixtures so the chat-eval harness can run
   the validator on prior transcripts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

# ── Public taxonomy ──────────────────────────────────────────────────────────


class NameKind(str, Enum):
    """Coarse classification for an extracted proper-noun candidate.

    Mirrors ``FieldKind`` from libs/contracts.numeric_grounding. The
    orchestrator uses ``COMPANY`` / ``TICKER`` for fail-closed checks
    (the response named an entity that does not appear anywhere in our
    grounded set or tool results) and ``PERSON`` / ``PLACE`` as soft
    signals (logged but never blocking).
    """

    COMPANY = "company"
    TICKER = "ticker"
    PERSON = "person"
    PLACE = "place"
    UNKNOWN = "unknown"


# Disposition table — which NameKinds are fail-closed vs soft.
# COMPANY / TICKER are user-verifiable factual claims; PERSON / PLACE
# are common in synthesis prose ("United States", "Tim Cook") and would
# trigger floods of false positives if blocked. The orchestrator can
# override via ``strict_kinds``.
FAIL_CLOSED_KINDS: frozenset[NameKind] = frozenset({NameKind.COMPANY, NameKind.TICKER})

# ── Stop-noun list ───────────────────────────────────────────────────────────
#
# Title-Cased prose tokens that LOOK like proper nouns but are not
# entity references. Anything in this set is silently ignored by the
# extractor.
#
# Coverage:
#   - Countries (United States, China, Germany, ...)
#   - Days of the week / months (Monday, January, ...)
#   - Currencies / financial unit nouns (USD, Dollar, ...)
#   - Generic English Title-Cased tokens (The, This, In, ...)
#   - Common cardinal directions and continents
#
# Tuning rule: when adding entries, prefer over-listing — a false
# negative here means an actual entity slips through (BAD). A false
# positive simply means we don't flag a benign word (FINE).
_STOP_NOUNS: frozenset[str] = frozenset(
    s.lower()
    for s in (
        # ── Pronouns / determiners / prepositions ────────────────
        "The",
        "A",
        "An",
        "This",
        "That",
        "These",
        "Those",
        "It",
        "He",
        "She",
        "They",
        "We",
        "You",
        "I",
        "In",
        "On",
        "At",
        "By",
        "For",
        "With",
        "From",
        "To",
        "Of",
        "As",
        "And",
        "Or",
        "But",
        "If",
        "When",
        "Where",
        "How",
        "Why",
        "What",
        "Which",
        "Who",
        # ── Days of the week ─────────────────────────────────────
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        # ── Months ───────────────────────────────────────────────
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
        # BP-670: month ABBREVIATIONS — live failure: the single candidate
        # "Jun" (from "*(Jun 10)*" date stamps) cost an 11.7s rewrite of a
        # correct Apple-news answer.
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Sept",
        "Oct",
        "Nov",
        "Dec",
        # ── Countries (most common in financial prose) ───────────
        "United States",
        "United Kingdom",
        "China",
        "Japan",
        "Germany",
        "France",
        "Italy",
        "Spain",
        "Canada",
        "Mexico",
        "Brazil",
        "India",
        "Russia",
        "Australia",
        "South Korea",
        "North Korea",
        "Taiwan",
        "Singapore",
        "Hong Kong",
        "Switzerland",
        "Netherlands",
        "Belgium",
        "Sweden",
        "Norway",
        "Denmark",
        "Finland",
        "Ireland",
        "Poland",
        "Turkey",
        "Saudi Arabia",
        "Israel",
        "Egypt",
        "South Africa",
        "Argentina",
        "Chile",
        "Colombia",
        "Vietnam",
        "Thailand",
        "Indonesia",
        "Malaysia",
        "Philippines",
        "America",
        "Europe",
        "Asia",
        "Africa",
        # ── Currencies / units ───────────────────────────────────
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CNY",
        "Dollar",
        "Euro",
        "Yen",
        "Pound",
        "Yuan",
        # ── Common acronyms (already in numeric_grounding's
        # non-ticker list — duplicated here for self-containment) ─
        "GAAP",
        "EPS",
        "EBIT",
        "EBITDA",
        "FCF",
        "ROE",
        "ROA",
        "SEC",
        "FED",
        "ETF",
        "REIT",
        "IPO",
        "CEO",
        "CFO",
        "COO",
        "CTO",
        "P/E",
        "GDP",
        "CPI",
        "API",
        "CAGR",
        "VAR",
        "AI",
        "ML",
        "LLM",
        # BP-670: tech acronyms observed as live false positives — flagged
        # as TICKER/COMPANY in the Apple-news turn ("LLMs", "WWDC") and
        # adjacent hardware acronyms of the same shape.
        "LLMs",
        "WWDC",
        "GPU",
        "GPUs",
        "CPU",
        "CPUs",
        "EV",
        "IT",
        "IP",
        "IR",
        "PR",
        "HR",
        "US",
        "UK",
        "UN",
        "EU",
        "NA",
        "OS",
        "ID",
        "OK",
        "TV",
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "FY",
        "YOY",
        "YTD",
        "MOM",
        # ── Quarters / generic time tokens ───────────────────────
        "Today",
        "Yesterday",
        "Tomorrow",
        "Quarter",
        "Year",
        "Annual",
        # ── PLAN-0104 W47: discourse / framing tokens that appear ─
        # Title-cased at sentence start and have been observed to
        # falsely trip the COMPANY regex (Round 7 v2 TSLA — "Here"
        # was extracted from the sentence "Here is the quarterly
        # progression" and routed into the refusal text as an
        # unresolved entity). Each token below MUST be a word that
        # has no business being a company reference in financial
        # prose. Over-listing is preferred (BAD = false negative).
        "Here",
        "There",
        "Now",
        "Then",
        "Thus",
        "However",
        "Therefore",
        "Meanwhile",
        "Overall",
        "Based",
        "Additionally",
        "Furthermore",
        "Finally",
        "Notably",
        "Specifically",
        "Indeed",
        "Indeed",
        "First",
        "Second",
        "Third",
        "Next",
        "Last",
        "Latest",
        "Recent",
        "Recently",
        "Previously",
        "Currently",
        # ── BP-670: sentence-start prose words observed live (2026-06-11)
        # "Multiple analyst notes..." and "Would you like me to..." were
        # extracted as COMPANY candidates and triggered a 12s fabricating
        # rewrite of a correct Apple-news answer. Modals / quantifiers /
        # discourse openers have no business being company references.
        "Would",
        "Could",
        "Should",
        "Multiple",
        "Several",
        "Many",
        "Some",
        "Both",
        "Each",
        "Every",
        "While",
        "Although",
        "Despite",
        "Whether",
        "Also",
        "Please",
        "Note",
        "Given",
        "Following",
        "Regarding",
        "Looking",
        "Key",
        "Top",
        "Summary",
        # Finance prose nouns that open sentences ("Options-market
        # commentary...", "Shares rallied...", "Analysts expect...").
        "Options",
        "Shares",
        "Stocks",
        "Markets",
        "Investors",
        "Analysts",
        "Traders",
        "Sources",
        "Reports",
        # ── Financial nouns that are commonly Title-Cased ────────
        "Revenue",
        "Earnings",
        "Profit",
        "Loss",
        "Income",
        "Cash",
        "Debt",
        "Margin",
        "Growth",
        # ── Generic descriptors ──────────────────────────────────
        "Company",
        "Inc",
        "Corp",
        "Corporation",
        "Ltd",
        "Limited",
        "LLC",
        "Group",
        "Holdings",
        "Industries",
        "International",
        "Global",
        "Worldwide",
    )
)


# ── Public result types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class UngroundedName:
    """A proper-noun candidate that did not match the grounded entity set."""

    name: str  # the verbatim token as it appeared in the response
    normalized: str  # lower-cased + stripped (used for set membership)
    kind: NameKind


@dataclass(frozen=True)
class EntityGroundingResult:
    """Outcome of one validation pass over (response, grounded_set)."""

    passed: bool
    total_candidates: int
    unsupported: tuple[UngroundedName, ...]
    # All NameKinds touched in this pass — useful for metrics/logging.
    per_kind_counts: dict[NameKind, int] = field(default_factory=dict)


# ── Extraction regex ─────────────────────────────────────────────────────────
#
# Cashtags + bare tickers: ``$AAPL`` or 2-5-letter all-caps tokens.  We
# match cashtags AND bare uppercase tokens because the LLM uses both
# forms. ``\b`` boundaries keep ``$AA`` from matching inside ``aaa``.
_TICKER_RE = re.compile(r"(?:\$([A-Z]{1,5})|\b([A-Z]{2,5})\b)")

# Title-cased multi-word company-name candidates. Anchored to require at
# least one capital letter and allow internal hyphens / apostrophes (so
# "ServiceNow", "Berkshire Hathaway", "Macy's" all match).  We capture
# up to four words to bound regex complexity; the validator joins them
# with a space.
#
# WHY this regex: we WANT to over-extract. The stop-noun filter trims
# obvious non-entities; the grounded-set membership check trims the
# rest. False positives become "[unverified]" — never confident wrong
# answers (F-LIVE-NEW-002 fail-safe principle).
_COMPANY_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9&'\-]+)(?:\s+(?:[A-Z][a-zA-Z0-9&'\-]+|of|and|the|for)){0,3}\b")


# Citation markers ``[N7]`` — strip BEFORE extraction so the bracketed
# token isn't misread as a company name.
_CITATION_RE = re.compile(r"\[N\d+\]")

# BP-670: markdown section headings — ``### Recent News`` and standalone
# bold-only lines (``**Recent Headlines & Developments**`` / ``**Key
# Catalysts to Watch:**``). These are structural prose, not entity claims,
# yet their Title-Case phrasing matches _COMPANY_RE and produced live false
# positives ("Recent Headlines", "Developments", "Siri Overhaul", "Product
# Launches" all flagged as ungrounded COMPANYs → 15s rewrite timeout).
# Stripped line-wise BEFORE candidate extraction. Inline bold spans inside
# normal sentences are NOT touched (the line must contain nothing but the
# heading).
_HEADING_LINE_RE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t].*|\*\*[^*\n]+\*\*:?[ \t]*)$",
    re.MULTILINE,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _normalize(token: str) -> str:
    """Canonical form used for set comparisons.

    Cashtag prefix stripped, lower-cased, whitespace collapsed. We do
    NOT strip suffix corporate descriptors (``Inc``, ``Corp``) — those
    are kept so ``Apple Inc`` and ``Apple Inc.`` both match if either
    form appears in the grounded set. The grounded-set builder is
    expected to add multiple variants.

    PLAN-0104 W47: trailing English possessive ``'s`` (e.g. "Tesla's",
    "Apple's") is stripped so the possessive form matches the canonical
    grounded entry. Without this, the COMPANY regex captures "Tesla's"
    verbatim and the post-strip lookup against {"tesla", "tsla"} misses,
    routing a normal possessive into the rewrite refusal payload as if it
    were a hallucinated entity (Round 7 v2 TSLA failure mode).
    """
    t = token.strip().lstrip("$")
    t = re.sub(r"\s+", " ", t).lower()
    # Drop English possessive suffix — both the curly and straight apostrophe
    # forms appear in LLM output.
    for suf in ("’s", "'s"):  # noqa: RUF001 — curly + straight apostrophe
        if t.endswith(suf):
            t = t[: -len(suf)]
            break
    return t


def _build_normalized_grounded_set(grounded_entity_names: Iterable[str]) -> set[str]:
    """Lower-case + suffix-strip every name in the grounded set.

    Suffix-stripping covers the common corporate descriptors so e.g.
    ``Apple Inc.`` in tool results matches ``Apple`` in the response.
    """
    out: set[str] = set()
    suffixes = (
        " inc",
        " inc.",
        " corp",
        " corp.",
        " corporation",
        " ltd",
        " ltd.",
        " limited",
        " llc",
        " plc",
        " group",
        " holdings",
        " co",
        " co.",
        " company",
        ",",
        ".",
    )
    for raw in grounded_entity_names:
        if not raw:
            continue
        n = _normalize(raw)
        out.add(n)
        # Strip trailing corporate suffixes recursively so all common
        # variants collapse to one form.
        changed = True
        while changed:
            changed = False
            for suf in suffixes:
                if n.endswith(suf):
                    n = n[: -len(suf)].rstrip()
                    changed = True
            out.add(n)
    return out


def _classify_kind(token: str) -> NameKind:
    """Heuristic NameKind classification for a candidate.

    Priority:
      1. Cashtag or 2-5-letter all-caps → TICKER.
      2. Single Title-Cased token preceded by ``Mr.``/``Ms.``/``Dr.``
         pattern handling lives in the extractor; here we only see the
         token itself, so we use a coarse heuristic:
         - 2-word Title-Case with no corporate-suffix tokens → defaults
           to COMPANY (the fail-safe direction).
      3. Multi-word with company suffix → COMPANY.
      4. Otherwise → UNKNOWN.

    PERSON detection is intentionally weak — we'd rather call "Tim Cook"
    a COMPANY (and fail closed if absent from the grounded set) than
    silently pass a hallucinated CEO name.  The orchestrator can
    downgrade PERSON to soft via ``strict_kinds`` if needed.
    """
    stripped = token.strip().lstrip("$")
    if re.fullmatch(r"[A-Z]{1,5}", stripped):
        return NameKind.TICKER
    if re.search(r"\b(?:Inc|Corp|Corporation|Ltd|LLC|PLC|Group|Holdings)\b", token, re.IGNORECASE):
        return NameKind.COMPANY
    # Multi-word Title-Cased → company-shaped by default.
    if " " in token.strip():
        return NameKind.COMPANY
    # Single Title-Cased token — could be company OR person; we default
    # to COMPANY (fail-closed) per the F-LIVE-NEW-002 design rule.
    return NameKind.COMPANY


def _all_stopnoun_phrases(words: list[str]) -> bool:
    """Return True if *words* can be tiled by 1- or 2-word stop-noun phrases.

    Greedy left-to-right: at each position consume the longest matching
    stop-noun phrase (2-word window preferred). If the whole list is
    consumed, every component was a stop-noun and the candidate should
    be dropped. If any position fails to match, return False — the
    candidate contains at least one non-stop-noun word and must go to
    membership check.
    """
    i = 0
    while i < len(words):
        # Prefer the 2-word window.
        if i + 1 < len(words):
            bigram = f"{words[i]} {words[i + 1]}"
            if bigram in _STOP_NOUNS:
                i += 2
                continue
        if words[i] in _STOP_NOUNS:
            i += 1
            continue
        return False
    return True


def _extract_candidates(text: str) -> list[tuple[str, NameKind]]:
    """Extract (token, NameKind) candidates from *text*.

    Pipeline:
      1. Strip citation markers ``[N\\d+]`` so they don't pollute.
      1b. Strip markdown heading / standalone-bold lines (BP-670) — section
          titles are structural prose, not entity claims.
      2. Walk ticker regex → each match yields a (token, TICKER) row.
      3. Walk company regex → each match yields a (token, COMPANY) row.
      4. Drop any candidate whose normalised form is in the stop-noun
         list.
      5. Drop duplicates (keep first-seen casing).

    Returns the list in insertion order so the orchestrator's re-prompt
    bullet list reads top-to-bottom.
    """
    cleaned = _CITATION_RE.sub("", text)
    cleaned = _HEADING_LINE_RE.sub("", cleaned)
    seen: set[str] = set()
    out: list[tuple[str, NameKind]] = []

    # Tickers — both cashtag and bare-all-caps forms.
    for m in _TICKER_RE.finditer(cleaned):
        token = m.group(1) or m.group(2) or ""
        if not token:
            continue
        norm = _normalize(token)
        if norm in _STOP_NOUNS or norm in seen:
            continue
        seen.add(norm)
        out.append((token, NameKind.TICKER))

    # Companies / multi-word Title-Cased candidates.
    for m in _COMPANY_RE.finditer(cleaned):
        token = m.group(0)
        # Skip if this is a bare all-caps token already captured as TICKER.
        if re.fullmatch(r"[A-Z]{1,5}", token):
            continue
        norm = _normalize(token)
        if norm in _STOP_NOUNS or norm in seen:
            continue
        # Drop multi-word candidates that are entirely composed of
        # stop-noun words joined by connectors. Example: "United States
        # and China" — both "united states" and "china" are stop-nouns,
        # but the greedy regex captures them as a single 4-word span.
        # We split on whitespace + recognised connectors ("and", "of",
        # "the", "for") and check if every word-cluster is a stop-noun.
        _words = re.split(r"\s+(?:and|of|the|for)\s+|\s+", norm)
        _words = [w for w in _words if w]
        if _words and all(w in _STOP_NOUNS for w in _words):
            continue
        # Try two-word window: "United States" inside a longer span
        # should still be recognised. We check every contiguous 1- and
        # 2-word slice; if the WHOLE candidate decomposes into
        # stop-noun phrases, drop it.
        if _words and _all_stopnoun_phrases(_words):
            continue
        seen.add(norm)
        out.append((token, _classify_kind(token)))

    return out


# ── Validator ────────────────────────────────────────────────────────────────


class EntityNameGroundingValidator:
    """Validate that every entity name in *response* appears in the grounded set.

    Stateless. Construct once, reuse across requests.

    Usage::

        validator = EntityNameGroundingValidator()
        result = validator.validate(
            response=full_text,
            grounded_entity_names={"Tesla Inc", "Tesla", "TSLA"},
            tool_result_entity_refs={"tesla"},
        )
        if not result.passed:
            # Re-prompt LLM with result.unsupported.
            ...
    """

    def __init__(
        self,
        *,
        strict_kinds: Iterable[NameKind] = FAIL_CLOSED_KINDS,
    ) -> None:
        # Capture which NameKinds are fail-closed (mismatch ⇒ unsupported)
        # vs soft (recorded in per_kind_counts but never blocks).
        self._strict_kinds = frozenset(strict_kinds)

    @property
    def strict_kinds(self) -> frozenset[NameKind]:
        return self._strict_kinds

    def validate(
        self,
        response: str,
        grounded_entity_names: set[str],
        tool_result_entity_refs: set[str] | None = None,
        tool_text: str | None = None,
    ) -> EntityGroundingResult:
        """Return an :class:`EntityGroundingResult` for *response*.

        Algorithm:
          1. Extract proper-noun candidates (ticker + multi-word Title).
          2. Apply stop-noun filter (countries, days, currencies, etc.).
          3. Build the normalised grounded set:
             ``grounded_entity_names`` union ``tool_result_entity_refs`` with
             suffix-stripping so "Apple Inc." matches "Apple".
          4. For each candidate whose NameKind is in ``strict_kinds``,
             check membership. Misses → UngroundedName entry.
          5. Soft kinds (PERSON / PLACE / UNKNOWN by default) are
             counted in ``per_kind_counts`` but never block.

        BP-670 — ``tool_text``: optional raw retrieval payload (tool result
        bodies joined). A candidate whose normalised form appears verbatim
        (case-insensitive) inside the retrieved text IS grounded — the LLM
        copied it from retrieval, it did not invent it. Without this, every
        mixed-case proper noun that only exists in an article title/body
        ("Morgan Stanley", "Siri", "Google Cloud") was flagged because the
        structured grounded set carries only entity names / item ids /
        UPPERCASE ticker tokens.
        """
        candidates = _extract_candidates(response)
        normalized_grounded = _build_normalized_grounded_set(
            list(grounded_entity_names) + list(tool_result_entity_refs or set())
        )
        tool_text_lower = tool_text.lower() if tool_text else ""

        unsupported: list[UngroundedName] = []
        per_kind_counts: dict[NameKind, int] = {}

        for token, kind in candidates:
            per_kind_counts[kind] = per_kind_counts.get(kind, 0) + 1
            norm = _normalize(token)
            if norm in normalized_grounded:
                continue
            # Partial match: if any grounded name contains this token as
            # a whole word (or vice versa), accept. Covers "Tesla" in
            # response vs "Tesla Motors" in grounded — the latter is an
            # alias of the former. This is the loosest acceptable check
            # before the fail-closed branch.
            if any(norm in g or g in norm for g in normalized_grounded if g):
                continue
            # BP-670: verbatim retrieval-payload grounding — see docstring.
            # Substring (not whole-word) on purpose: the candidate is a
            # multi-char normalised phrase; an accidental hit requires the
            # exact phrase to appear in retrieved data, in which case the
            # LLM legitimately read it there.
            if tool_text_lower and norm and norm in tool_text_lower:
                continue
            if kind not in self._strict_kinds:
                continue
            unsupported.append(
                UngroundedName(
                    name=token,
                    normalized=norm,
                    kind=kind,
                )
            )

        return EntityGroundingResult(
            passed=not unsupported,
            total_candidates=len(candidates),
            unsupported=tuple(unsupported),
            per_kind_counts=per_kind_counts,
        )


__all__ = [
    "EntityGroundingResult",
    "EntityNameGroundingValidator",
    "FAIL_CLOSED_KINDS",
    "NameKind",
    "UngroundedName",
]
