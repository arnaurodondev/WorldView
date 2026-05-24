"""Post-tool numeric-grounding validator (PLAN-0093 Wave E-2 T-E-2-01).

Rejects LLM responses whose numerical claims do not appear in any tool
result. Built to catch the canonical AMD QA failure: the LLM reported
"$34.6B" for Q2 2026 revenue when no tool returned that number and AMD
had not yet reported Q2 2026 — a pure fabrication.

Design choices:

1. **Per-FieldKind tolerances** (Q3 decision): EPS at $0.45 vs $0.50 is
   11% off and absolutely wrong; headcount 161,000 vs 161,400 is 0.25%
   off and acceptable. A single global tolerance cannot serve both.
   Defaults live in ``libs/contracts/numeric_grounding.py``; the
   orchestrator can override per-kind via the
   ``NUMERIC_GROUNDING_TOLERANCES_JSON`` env var (parsed in
   ``rag_chat.config``).

2. **Classifier-first**: each extracted number is classified into a
   ``FieldKind`` from its surrounding context. We then match it against
   tool-result values **of the same kind** first; only if no same-kind
   match exists do we fall back to a loose any-kind match. This keeps
   tolerance enforcement strict per kind while not blowing up on tools
   that don't yet emit per-row kinds.

3. **Sign sensitivity**: a loss reported as a gain is not a tolerance
   issue, it is an outright lie. Sign mismatches always fail regardless
   of tolerance.

4. **Citation markers + dates are skipped**: ``[N1]`` is handled by the
   citation validator (T-E-5-01). Standalone 4-digit years are still
   classified as YEAR but tolerance 0 means they only pass on exact match.

5. **Deterministic**: no LLM call, no I/O. Same inputs → same outputs.
   This is required so the Sub-Plan G G-3 chat regression suite can
   re-run the validator on stored fixtures and get stable results.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from contracts.numeric_grounding import DEFAULT_TOLERANCES, FieldKind  # type: ignore[import-untyped]

# ── Number extraction ────────────────────────────────────────────────────────

# Match any signed/unsigned number with optional thousands separators,
# decimal portion, and a trailing B/M/K/T/% suffix. The suffix is captured
# so we can decode magnitude.
#
# WHY this regex: the LLM emits numbers in many shapes — "$34.6B",
# "10.253B", "$0.45", "161,000", "23.7", "50%", "-1.5B". The single
# unified pattern catches all of them and the post-processing decodes
# the suffix. We do NOT try to match dates here (DTZ regexes are noisy)
# — date detection is done in the classifier from the surrounding context.
_NUM_RE = re.compile(
    r"""
    (?P<full>
        [-+]?                                  # optional sign
        \$?                                    # optional currency
        (?P<digits>\d[\d,]*(?:\.\d+)?)         # mantissa with optional decimal
        (?:                                    # optional magnitude/percent suffix
            (?P<suffix>[BMKTbmkt%])(?![A-Za-z])  # must NOT be followed by a letter
        )?
    )
    """,
    re.VERBOSE,
)

# Magnitude multipliers — case-insensitive. "T" = trillion (used for
# mega-cap market cap quotes).
_SUFFIX_MULT: dict[str, float] = {
    "k": 1e3,
    "K": 1e3,
    "m": 1e6,
    "M": 1e6,
    "b": 1e9,
    "B": 1e9,
    "t": 1e12,
    "T": 1e12,
}

# Citation markers we must ignore so [N7] does not count as the number 7.
_CITATION_RE = re.compile(r"\[N\d+\]")

# Year token recognition — used by the classifier ONLY (the number
# extractor already captured the digits; this is a CONTEXT check).
_YEAR_RANGE = range(1900, 2100)

# Quarter labels — exact-match driven (Q1 2026 etc.). Used by the
# classifier and special-handled by the validator (string equality).
#
# PLAN-0093 Phase 5 QA-2 Gap 2: the original pattern only matched
# 4-digit calendar years. LLMs routinely emit fiscal-year forms
# ("Q1 FY26", "Q1 fiscal 2027", "Q1 of fiscal year 2026") and 2-digit
# years ("Q1 FY26"). The verbose pattern below matches every canonical
# variant; ``_normalize_quarter_label`` then canonicalises the captured
# token to ``Q<n> 20YY`` so set comparisons collapse all forms.
_QUARTER_RE = re.compile(
    r"""
    \bQ([1-4])                                   # Q1..Q4 — capture quarter
    \s*                                          # optional whitespace
    (?:
        (?:of\s+)?fiscal\s+year\s+               # "of fiscal year 2026"
      | (?:of\s+)?fiscal\s+                      # "fiscal 2027"
      | FY\s*                                    # "FY26", "FY 2026"
    )?
    \s*[/-]?\s*                                  # optional separator
    (\d{2}|\d{4})                                # 2-digit or 4-digit year
    \b
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _normalize_quarter_label(match: re.Match[str]) -> str:
    """Canonicalise a ``_QUARTER_RE`` match to ``Q<n> 20YY``.

    Two-digit years are expanded by prefixing ``20`` (so ``FY26`` →
    ``2026``). Four-digit years pass through. Quarter digit is taken
    verbatim from group(1).
    """
    quarter = match.group(1)
    year = match.group(2)
    if len(year) == 2:
        year = f"20{year}"
    return f"Q{quarter} {year}"


# Bare quarters (no year at all) appearing near financial keywords are a
# common hallucination shape: "Q3 revenue was $X". Without a year the
# claim cannot be tool-verified, so the validator surfaces them as
# ungrounded with snippet ``"Q<n> (no year)"``.
_BARE_QUARTER_RE = re.compile(r"\bQ([1-4])\b(?!\s*(?:of\s+)?(?:fiscal|FY|/|-|\s*\d))", re.IGNORECASE)

# Financial-context keywords that elevate a bare-quarter mention from
# harmless prose ("Q4 chip launch") to a numeric-grounding concern
# ("Q3 revenue"). Kept short to avoid false positives.
_FINANCIAL_KW_RE = re.compile(
    r"\b(revenue|earnings|eps|net\s+income|sales|guidance|profit|margin|ebit|ebitda|fcf|free\s+cash\s+flow)\b",
    re.IGNORECASE,
)


# ── Public result types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class UnsupportedNumber:
    """A response number that no tool result can support within tolerance."""

    value: float
    field_kind: FieldKind
    tolerance_used: float
    closest_tool_value: float | None
    # The verbatim text snippet from the response (helpful for re-prompt).
    snippet: str


@dataclass(frozen=True)
class GroundingResult:
    """Outcome of one validation pass over (response, tool_results)."""

    passed: bool
    total_numbers: int
    unsupported: tuple[UnsupportedNumber, ...]
    # Per-FieldKind (passed, failed) counts — surfaced by metrics.
    per_kind_stats: Mapping[FieldKind, tuple[int, int]] = field(default_factory=dict)


# ── Classifier ───────────────────────────────────────────────────────────────


def _context_around(text: str, start: int, end: int, radius: int = 50) -> str:
    """Return up to ``radius`` chars on each side of [start:end]."""
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    return text[lo:hi].lower()


def classify_number(
    value: float,
    raw_token: str,
    context: str,
) -> FieldKind:
    """Heuristically classify a number into a FieldKind.

    Priority order:
      1. Currency-with-suffix ($XB/M/K) → REVENUE-family (then refined by
         magnitude — > 1e11 with cap context → MARKET_CAP).
      2. Percentage → RATIO or RETURN_PCT (context-disambiguated).
      3. Standalone 4-digit number in [1900,2100] with no decimal →
         YEAR. (Quarter labels are matched at the response-scan level —
         see classify_response_quarter_labels.)
      4. Context keywords: "EPS"|"earnings per share" → EPS; "P/E"|
         "ratio" → RATIO; "revenue"|"sales" → REVENUE; "cap" → MARKET_CAP;
         "employees"|"headcount" → HEADCOUNT; "share"|"diluted" → SHARES.
      5. Numeric magnitude heuristics for unclassified-but-large values.
      6. UNKNOWN otherwise.
    """
    has_currency = "$" in raw_token
    has_pct = "%" in raw_token
    suffix = raw_token.strip().lower()[-1] if raw_token and raw_token.strip()[-1].lower() in "bmkt" else ""

    # ── Percentage handling ────────────────────────────────────────────
    # We check context to differentiate RATIO (margins, P/E expressed %)
    # from RETURN_PCT (period returns).
    if has_pct:
        _return_keywords = (
            "return",
            "ytd",
            "month-over-month",
            "mom",
            "yoy",
            "year-over-year",
            "gain",
            "loss",
        )
        if any(k in context for k in _return_keywords):
            return FieldKind.RETURN_PCT
        return FieldKind.RATIO

    # ── Currency + suffix → revenue-family ─────────────────────────────
    if has_currency and suffix in ("b", "m", "k", "t"):
        # > 100B with "cap"/"valuation" → MARKET_CAP, else REVENUE.
        if any(k in context for k in ("market cap", "market-cap", "valuation", "enterprise value", "capitalization")):
            return FieldKind.MARKET_CAP
        return FieldKind.REVENUE

    # ── Year detection ─────────────────────────────────────────────────
    # Only standalone 4-digit integers in the year range, no currency,
    # no suffix.
    if not has_currency and not suffix and value == int(value) and int(value) in _YEAR_RANGE:
        return FieldKind.YEAR

    # ── Context keyword routing ────────────────────────────────────────
    # Order matters — "P/E ratio" beats "ratio" alone, "EPS" beats
    # "earnings" so EPS doesn't get classified as REVENUE.
    if "eps" in context or "earnings per share" in context or "diluted earnings" in context:
        return FieldKind.EPS
    if "p/e" in context or "pe ratio" in context or "price-to-earnings" in context:
        return FieldKind.RATIO
    if "ratio" in context or "margin" in context or "roe" in context or "roa" in context or "p/b" in context:
        return FieldKind.RATIO
    if "revenue" in context or "sales" in context or "net income" in context or "ebit" in context or "fcf" in context:
        return FieldKind.REVENUE
    if "market cap" in context or "market-cap" in context or "valuation" in context:
        return FieldKind.MARKET_CAP
    if "employee" in context or "headcount" in context or "workforce" in context or "staff" in context:
        return FieldKind.HEADCOUNT
    if "share" in context or "diluted" in context or "outstanding" in context:
        return FieldKind.SHARES
    if "price" in context or "quote" in context or "trading at" in context or "$" in raw_token:
        # Bare $X — likely a price quote.
        return FieldKind.PRICE

    # ── Magnitude fallbacks ────────────────────────────────────────────
    if value >= 1e11:
        return FieldKind.MARKET_CAP
    if value >= 1e9:
        return FieldKind.REVENUE

    return FieldKind.UNKNOWN


def _decode_token(raw_full: str, digits: str, suffix: str | None) -> float:
    """Convert a captured number token to a float in base units."""
    # Strip thousands separators and currency.
    cleaned = digits.replace(",", "")
    base = float(cleaned)
    # Apply sign.
    if raw_full.strip().startswith("-"):
        base = -base
    # Apply magnitude suffix.
    if suffix and suffix in _SUFFIX_MULT:
        base *= _SUFFIX_MULT[suffix]
    # Percent normalisation: "50%" → 0.5 so fraction tools (0.5) match.
    if raw_full.strip().endswith("%"):
        base = base / 100.0
    return base


def _extract_numbers(text: str) -> list[tuple[float, str, str]]:
    """Yield (value, raw_token, surrounding_context) for every number in *text*.

    Citation markers are stripped first so [N7] does not surface as 7.
    """
    cleaned = _CITATION_RE.sub("", text)
    out: list[tuple[float, str, str]] = []
    for m in _NUM_RE.finditer(cleaned):
        digits = m.group("digits") or ""
        if not digits or digits == ".":
            continue
        suffix = m.group("suffix")
        # Skip 1-character matches like a bare "$" that captured nothing.
        if not any(ch.isdigit() for ch in digits):
            continue
        try:
            value = _decode_token(m.group("full"), digits, suffix)
        except ValueError:
            continue
        ctx = _context_around(cleaned, m.start(), m.end())
        out.append((value, m.group("full").strip(), ctx))
    return out


# ── Tool result flattening ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolValue:
    """A numeric value extracted from a tool result, tagged with entity scope.

    PLAN-0093 Phase 5 QA-2 Gap 3: the previous flat ``(value, kind)``
    tuple let validator candidate pools mix entities — e.g. an AMD vs
    NVDA comparison query had both vendors' revenue numbers in one pool,
    so an LLM could write "AMD Q4 revenue $68B" and pass validation
    because $68B existed in NVDA's tool corpus. Tagging each value with
    an ``entity_tag`` (ticker or UUID short-prefix) lets the validator
    restrict the candidate pool to the entity actually mentioned near
    the response number.

    ``entity_tag`` is best-effort:
      - ``""`` (empty) when no entity could be inferred from the row.
      - A short ticker string when ``item_id`` matches ``<ticker>_<...>``.
      - The first 8 chars of ``entity_id`` UUID when only the ID is known.
      - ``citation_meta.entity_name`` lower-cased when present.
    """

    value: float
    field_kind: FieldKind
    entity_tag: str  # may be "" when no entity is known


# Matches the leading ticker portion of an ``item_id`` like
# ``AAPL_2026Q1`` or ``NVDA-fundamentals-0``. Captures 1-5 uppercase
# letters, optionally followed by a dot+letter exchange suffix.
_ITEM_ID_TICKER_RE = re.compile(r"^([A-Z]{1,5}(?:\.[A-Z]{1,2})?)[_\-]")


def _entity_tag_for(raw: Any) -> str:
    """Extract an entity tag from a tool-result row, best-effort.

    Resolution order (each step is wrapped in ``getattr`` so duck-typed
    mocks and dicts both work):

      1. ``raw.entity_id`` — first 8 chars of UUID string.
      2. ``raw.item_id`` — strip a leading ``<TICKER>_`` if present.
      3. ``raw.citation_meta.entity_name`` — lower-cased.
      4. ``""`` when nothing matches.

    Returns a lower-cased string so comparisons are case-insensitive.
    """
    # 1. entity_id (UUID) — preferred when present.
    entity_id = getattr(raw, "entity_id", None)
    if entity_id is None and isinstance(raw, dict):
        entity_id = raw.get("entity_id")
    if entity_id:
        return str(entity_id)[:8].lower()
    # 2. item_id (often "<TICKER>_<period>").
    item_id = getattr(raw, "item_id", None)
    if item_id is None and isinstance(raw, dict):
        item_id = raw.get("item_id")
    if isinstance(item_id, str) and item_id:
        m = _ITEM_ID_TICKER_RE.match(item_id)
        if m:
            return m.group(1).lower()
    # 3. citation_meta.entity_name.
    citation_meta = getattr(raw, "citation_meta", None)
    if citation_meta is None and isinstance(raw, dict):
        citation_meta = raw.get("citation_meta")
    if citation_meta is not None:
        ent_name = getattr(citation_meta, "entity_name", None)
        if ent_name is None and isinstance(citation_meta, dict):
            ent_name = citation_meta.get("entity_name")
        if isinstance(ent_name, str) and ent_name:
            return ent_name.lower()
    return ""


def _flatten_tool_values(tool_results: Iterable[Any]) -> list[ToolValue]:
    """Extract ``ToolValue`` rows from tool results, entity-tagged.

    Each tool result is duck-typed. We look for:
      - ``.value`` + ``.field_kind`` (structured row — preferred path).
      - dict rows with ``value`` and optional ``field_kind`` keys.
      - ``.text`` (string) — scan it with the same number extractor +
        classifier as the response so we have a uniform pipeline.

    Every emitted ``ToolValue`` carries the same ``entity_tag`` derived
    from the source row via :func:`_entity_tag_for`. Values are in base
    units (same scale as the response extractor).
    """
    out: list[ToolValue] = []
    for raw in tool_results:
        if raw is None:
            continue
        entity_tag = _entity_tag_for(raw)
        # Structured row with explicit field_kind — preferred path.
        explicit_value = getattr(raw, "value", None)
        explicit_kind_obj = getattr(raw, "field_kind", None)
        if explicit_value is not None and explicit_kind_obj is not None:
            try:
                fv = float(explicit_value)
                kind = (
                    explicit_kind_obj if isinstance(explicit_kind_obj, FieldKind) else FieldKind(str(explicit_kind_obj))
                )
                out.append(ToolValue(value=fv, field_kind=kind, entity_tag=entity_tag))
                continue
            except (ValueError, TypeError):
                pass
        # Dict row.
        if isinstance(raw, dict) and "value" in raw:
            try:
                fv = float(raw["value"])
                kind_v = raw.get("field_kind", FieldKind.UNKNOWN)
                kind = kind_v if isinstance(kind_v, FieldKind) else FieldKind(str(kind_v))
                out.append(ToolValue(value=fv, field_kind=kind, entity_tag=entity_tag))
                continue
            except (ValueError, TypeError):
                pass
        # Text fallback — extract numbers + classify from context. We
        # only scan when .text is a real str (mocks in unit tests may
        # leave it as a MagicMock attribute; ignore those).
        if isinstance(raw, str):
            for value, raw_tok, ctx in _extract_numbers(raw):
                kind = classify_number(value, raw_tok, ctx)
                out.append(ToolValue(value=value, field_kind=kind, entity_tag=entity_tag))
        else:
            text = getattr(raw, "text", None)
            if isinstance(text, str) and text:
                for value, raw_tok, ctx in _extract_numbers(text):
                    kind = classify_number(value, raw_tok, ctx)
                    out.append(ToolValue(value=value, field_kind=kind, entity_tag=entity_tag))
    return out


def _extract_quarter_labels(text: str) -> set[str]:
    """Return the set of canonical ``Q<n> 20YY`` labels appearing in *text*.

    Used to enforce exact-label match for quarter references. All
    canonical variants — ``Q1 2026``, ``Q1 FY26``, ``Q1 fiscal 2027``,
    ``Q1 FY 2026``, ``Q1 of fiscal year 2026``, two-digit years — are
    collapsed to ``Q<n> 20YY`` via :func:`_normalize_quarter_label` so
    set comparisons treat all forms as equivalent.
    """
    return {_normalize_quarter_label(m) for m in _QUARTER_RE.finditer(text)}


def _extract_bare_quarters(text: str) -> set[str]:
    """Return bare-quarter mentions (``Q<n>`` with no year) near financial keywords.

    A bare quarter on its own ("Q4 chip launch") is harmless prose, but
    one within close proximity of a financial keyword ("Q3 revenue") is
    an ungroundable numeric claim — the validator surfaces it with the
    snippet ``"Q<n> (no year)"`` so the rewrite prompt can ask the LLM
    to either add the year or remove the claim.

    Proximity window: 60 chars on either side of the bare-quarter match
    (matches the ``_context_around`` radius used elsewhere).
    """
    out: set[str] = set()
    for m in _BARE_QUARTER_RE.finditer(text):
        lo = max(0, m.start() - 60)
        hi = min(len(text), m.end() + 60)
        window = text[lo:hi]
        if _FINANCIAL_KW_RE.search(window):
            out.add(f"Q{m.group(1)} (no year)")
    return out


# Common all-caps tokens that LOOK like tickers but aren't — we must
# not treat these as entity scope. EPS, P/E, GAAP, USD, etc.
_NON_TICKER_TOKENS = frozenset(
    {
        "EPS",
        "GAAP",
        "USD",
        "EUR",
        "GBP",
        "ETF",
        "REIT",
        "IPO",
        "CEO",
        "CFO",
        "COO",
        "CTO",
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "FY",
        "YOY",
        "YTD",
        "MOM",
        "ROE",
        "ROA",
        "EBIT",
        "EBITDA",
        "FCF",
        "SEC",
        "NYSE",
        "NASDAQ",
        "S&P",
        "GDP",
        "CPI",
        "API",
        "CAGR",
        "VAR",
    }
)


def _nearest_entity_tag(response: str, raw_token: str) -> str:
    """Return the entity tag (ticker) mentioned within 100 chars BEFORE *raw_token*.

    Used by the validator to entity-scope the candidate pool. We scan
    backwards from the response number for any 2-5 uppercase-letter
    ticker token, skipping known non-ticker acronyms (EPS, USD, GAAP,
    etc.). If found, return it lower-cased; otherwise ``""``.

    A 100-char window is wide enough to catch "AMD's Q4 revenue was
    $68B" patterns and narrow enough to avoid bleeding into the
    previous entity in a comparison response.
    """
    idx = response.find(raw_token)
    if idx == -1:
        return ""
    lo = max(0, idx - 100)
    window = response[lo:idx]
    # Last occurrence is closest — search from the right.
    candidates = list(re.finditer(r"\b([A-Z]{2,5})\b", window))
    for m in reversed(candidates):
        tok = m.group(1)
        if tok in _NON_TICKER_TOKENS:
            continue
        return tok.lower()
    return ""


# ── Validator ────────────────────────────────────────────────────────────────


class NumericGroundingValidator:
    """Validate that every number in *response* appears in *tool_results*.

    Stateless — one validator instance can serve many requests. The
    ``tolerances`` mapping is captured at construction so a hot config
    reload (in a long-running worker) requires building a new validator.

    Usage::

        validator = NumericGroundingValidator()
        result = validator.validate(response_text, tool_results)
        if not result.passed:
            # Re-prompt the LLM with result.unsupported.
            ...
    """

    def __init__(
        self,
        tolerances: Mapping[FieldKind, float] | None = None,
        *,
        skip_kinds: Iterable[FieldKind] = (),
    ) -> None:
        self._tolerances: dict[FieldKind, float] = dict(tolerances) if tolerances else dict(DEFAULT_TOLERANCES)
        # Backfill any missing kinds with the default to keep look-up safe.
        for kind, tol in DEFAULT_TOLERANCES.items():
            self._tolerances.setdefault(kind, tol)
        self._skip_kinds = frozenset(skip_kinds)

    # Property accessor for tests + config inspection.
    @property
    def tolerances(self) -> Mapping[FieldKind, float]:
        return self._tolerances

    def validate(
        self,
        response: str,
        tool_results: Iterable[Any],
    ) -> GroundingResult:
        """Return a ``GroundingResult`` for *response* against *tool_results*.

        Algorithm:
          1. Extract every number from *response*.
          2. Flatten every tool result into (value, kind) pairs.
          3. Special-case quarter labels: each "Q<n> <yyyy>" mentioned
             in the response must also appear verbatim in at least one
             tool result's text (or in a flattened structured row tagged
             QUARTER). Mismatch → UnsupportedNumber with FieldKind.QUARTER.
          4. For each response number, find the best same-kind match;
             if none, try any-kind. Pass if rel_diff ≤ tolerance AND
             sign matches.
        """
        response_numbers = _extract_numbers(response)
        tool_results_list = list(tool_results)
        tool_values = _flatten_tool_values(tool_results_list)
        # Materialise the source tool texts for quarter-label matching.
        # We coerce the .text attribute to str defensively — production
        # RetrievedItem has a str ``text`` field, but unit-test mocks can
        # leave ``text`` as a default MagicMock. A non-str here would crash
        # the validator and silently disable grounding.
        tool_text_parts: list[str] = []
        for r in tool_results_list:
            if r is None:
                continue
            if isinstance(r, str):
                tool_text_parts.append(r)
            elif isinstance(r, dict):
                # dict rows are handled by _flatten_tool_values; skip.
                continue
            else:
                t = getattr(r, "text", "")
                if isinstance(t, str):
                    tool_text_parts.append(t)
        tool_text_blob = " ".join(tool_text_parts)

        unsupported: list[UnsupportedNumber] = []
        per_kind_passed: Counter[FieldKind] = Counter()
        per_kind_failed: Counter[FieldKind] = Counter()

        # ── Step 3: Quarter labels — exact match required ──────────────
        # We surface unsupported quarter labels as synthetic
        # UnsupportedNumber entries with value=0.0 so the orchestrator's
        # rewrite prompt can list them like any other failure.
        response_quarters = _extract_quarter_labels(response)
        tool_quarters = _extract_quarter_labels(tool_text_blob)
        if FieldKind.QUARTER not in self._skip_kinds:
            for q_label in response_quarters - tool_quarters:
                unsupported.append(
                    UnsupportedNumber(
                        value=0.0,
                        field_kind=FieldKind.QUARTER,
                        tolerance_used=0.0,
                        closest_tool_value=None,
                        snippet=q_label,
                    )
                )
                per_kind_failed[FieldKind.QUARTER] += 1

            # ── PLAN-0093 Phase 5 QA-2 Gap 2 bare-quarter check ─────────
            # A bare "Q3 revenue" with no year is ungroundable. Surface
            # any bare-quarter mention near a financial keyword that is
            # NOT supported by:
            #   (a) a year-bearing quarter for the same digit in the
            #       response (already validated against tool_quarters), OR
            #   (b) the same bare-quarter+financial-keyword pattern in
            #       the tool corpus (tool itself says "Q3 revenue"), OR
            #   (c) any explicit "Q<digit> <year>" in the tool corpus
            #       (tool talks about Q3 by name).
            response_bare = _extract_bare_quarters(response)
            tool_bare = _extract_bare_quarters(tool_text_blob)
            response_quarter_digits = {q.split()[0] for q in response_quarters}
            tool_quarter_digits = {q.split()[0] for q in tool_quarters}
            for bare in response_bare:
                digit = bare.split()[0]  # "Q3"
                if digit in response_quarter_digits:
                    continue
                if bare in tool_bare:
                    continue
                if digit in tool_quarter_digits:
                    continue
                unsupported.append(
                    UnsupportedNumber(
                        value=0.0,
                        field_kind=FieldKind.QUARTER,
                        tolerance_used=0.0,
                        closest_tool_value=None,
                        snippet=bare,
                    )
                )
                per_kind_failed[FieldKind.QUARTER] += 1

        # ── Step 4: Per-number validation ──────────────────────────────
        # PLAN-0093 Phase 5 QA-2 Gap 3: entity-scope the candidate pool
        # so AMD's tool values can't ground an NVDA-attributed number.
        # When the response mentions a ticker within 100 chars BEFORE the
        # number, restrict candidates to tool values tagged with the same
        # entity. When no entity can be inferred, fall back to the legacy
        # any-kind pool — but the legacy fall-back is exact-match only
        # (tol=0) so we don't silently accept cross-entity collisions.
        total_numbers = len(response_numbers)
        for value, raw_tok, ctx in response_numbers:
            kind = classify_number(value, raw_tok, ctx)
            if kind in self._skip_kinds:
                continue
            tol = self._tolerances.get(kind, DEFAULT_TOLERANCES[FieldKind.UNKNOWN])

            # Find entity nearest to this number in the response.
            entity_tag = _nearest_entity_tag(response, raw_tok)

            # Pool selection:
            #  1. Entity-scoped + same-kind  (strictest, preferred)
            #  2. Entity-scoped + any-kind   (fallback if no same-kind hit)
            #  3. Any-entity + same-kind     (last resort when entity_tag="")
            if entity_tag:
                scoped = [tv for tv in tool_values if tv.entity_tag and entity_tag in tv.entity_tag]
                scoped_same = [tv.value for tv in scoped if tv.field_kind is kind]
                scoped_any = [tv.value for tv in scoped]
                candidate_pool = scoped_same or scoped_any
                effective_tol = tol
            else:
                # No entity context — keep legacy same-kind > any-kind
                # ordering, but tighten tolerance for any-kind fallback
                # to exact match (tol=0) to prevent cross-entity leakage.
                same_kind = [tv.value for tv in tool_values if tv.field_kind is kind]
                if same_kind:
                    candidate_pool = same_kind
                    effective_tol = tol
                else:
                    candidate_pool = [tv.value for tv in tool_values]
                    effective_tol = 0.0

            matched, closest = _matches_any(value, candidate_pool, effective_tol)
            if matched:
                per_kind_passed[kind] += 1
            else:
                per_kind_failed[kind] += 1
                unsupported.append(
                    UnsupportedNumber(
                        value=value,
                        field_kind=kind,
                        tolerance_used=tol,
                        closest_tool_value=closest,
                        snippet=raw_tok,
                    )
                )

        # Build per-kind stats dict — only kinds touched in this pass.
        per_kind_stats: dict[FieldKind, tuple[int, int]] = {}
        for kind in set(per_kind_passed) | set(per_kind_failed):
            per_kind_stats[kind] = (per_kind_passed[kind], per_kind_failed[kind])

        # Quarter mismatches count toward total_numbers for stats purposes
        # so the metric reflects the real number of items we judged. Bare
        # quarters near financial keywords are counted alongside year-bearing
        # mismatches (PLAN-0093 Phase 5 QA-2 Gap 2).
        if FieldKind.QUARTER not in self._skip_kinds:
            _quarter_misses = len(response_quarters - tool_quarters)
            _response_quarter_digits = {q.split()[0] for q in response_quarters}
            _tool_quarter_digits = {q.split()[0] for q in tool_quarters}
            _tool_bare = _extract_bare_quarters(tool_text_blob)
            _bare_misses = sum(
                1
                for bare in _extract_bare_quarters(response)
                if bare.split()[0] not in _response_quarter_digits
                and bare not in _tool_bare
                and bare.split()[0] not in _tool_quarter_digits
            )
        else:
            _quarter_misses = 0
            _bare_misses = 0
        total_numbers_with_quarters = total_numbers + _quarter_misses + _bare_misses

        return GroundingResult(
            passed=not unsupported,
            total_numbers=total_numbers_with_quarters,
            unsupported=tuple(unsupported),
            per_kind_stats=per_kind_stats,
        )


def _matches_any(
    value: float,
    candidates: list[float],
    tolerance: float,
) -> tuple[bool, float | None]:
    """Return (matched, closest_candidate_or_None) for *value* in *candidates*.

    Match rule:
      - Sign must match (loss vs gain is never a tolerance issue).
      - If tolerance == 0.0 → exact match required.
      - Else → ``abs(value - cand) / abs(cand) <= tolerance``.

    The closest candidate (by absolute diff) is always returned so the
    caller can show "you said X, the data has Y" in the re-prompt.
    """
    if not candidates:
        return False, None
    closest = min(candidates, key=lambda c: abs(c - value))
    if tolerance == 0.0:
        return (math.isclose(value, closest, rel_tol=0.0, abs_tol=1e-9), closest)
    for cand in candidates:
        # Sign check first — silent sign flip is never a rounding issue.
        if (cand >= 0) != (value >= 0):
            continue
        denom = abs(cand) if cand != 0 else 1.0
        if abs(value - cand) / denom <= tolerance:
            return True, closest
    return False, closest


__all__ = [
    "GroundingResult",
    "NumericGroundingValidator",
    "ToolValue",
    "UnsupportedNumber",
    "classify_number",
]
