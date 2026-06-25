"""Token-budget-aware text truncation for the BGE-large embedding model.

WHY THIS EXISTS (task #4 — embedding 400 backlog, 2026-06-16)
-------------------------------------------------------------
``BAAI/bge-large-en-v1.5`` is a BERT encoder with a HARD **512-token** context
window.  Historically the embedding adapters truncated input to a flat **1500
characters** on the assumption that 1500 chars ~= 500 tokens (~3 chars/token).
That assumption holds for prose but is badly WRONG for the dense financial /
JSON-envelope text this pipeline embeds: a chunk-0 JSON envelope (task #34)
packs digits, tickers, ISINs and punctuation that each become their OWN
WordPiece token, so 1500 chars routinely exceeds 512 tokens.  DeepInfra then
rejects the request with a *fatal* HTTP 400 ``invalid_request_error``
("513 input tokens > 512"), the retry worker burns all 5 attempts, and the row
is abandoned in ``embedding_pending`` forever.  The 2026-06-16 audit reproduced
this exactly: the same dense text truncated to 1500 chars → 400, to 1100 chars
→ 200.

THE FIX: TOKEN-BUDGET TRUNCATION (not a flat char cap)
------------------------------------------------------
We truncate by an ESTIMATED token count rather than a character count, so that
dense text is cut more aggressively than sparse prose while both stay safely
under 512 tokens.  We deliberately AVOID pulling in a real tokenizer
(``transformers`` / ``tokenizers``) because:
  * it would download model files at runtime (no network in the container),
  * it would add a heavyweight dependency to the ml-clients wheel + Docker image.

Instead we use a CONSERVATIVE pure-Python WordPiece *upper-bound* estimator
(:func:`estimate_bert_tokens`).  "Conservative" means it OVER-counts versus the
real BGE tokenizer — so truncating to an estimated ``MAX_TOKENS`` guarantees the
real token count is comfortably below 512, with no per-char tuning needed.

INGEST vs QUERY PARITY (one vector space)
-----------------------------------------
This helper is the SINGLE source of truth for embedding truncation.  Both the
ingest path (``DeepInfraEmbeddingAdapter`` / ``OllamaEmbeddingAdapter``) and the
query path (nlp-pipeline ``POST /api/v1/embed``) call :func:`truncate_for_bge`
with the SAME defaults, so a chunk stored at ingest time and the query that
retrieves it are pre-processed identically and land in the same semantic space.
"""

from __future__ import annotations

import re

# Maximal runs of ASCII alphanumerics — these become WordPiece SUB-word tokens.
_WORD_RE = re.compile(r"[A-Za-z0-9]+")

# JSON ``\uXXXX`` unicode escapes.  The pipeline stores chunk/section text as a JSON
# envelope with ``ensure_ascii`` ON, so non-Latin content (Hebrew, CJK, accented
# Latin) is serialised as ``ר``-style escapes.  Each such escape DECODES to a
# non-Latin codepoint that the (English-centric) BGE WordPiece tokenizer splits into
# ~2-3 byte/sub-word tokens — far MORE than the ~3-token estimate the 6 ASCII escape
# characters would otherwise contribute via the alnum rule.  Live DeepInfra probing
# of escape-dense Hebrew rows confirmed the naive estimate under-counts ~2x, so we
# score each escape explicitly at _TOKENS_PER_UNICODE_ESCAPE (a conservative upper
# bound) and remove its characters from the cheaper alnum accounting.  Without this,
# escape-dense rows truncated at the token budget still 400'd at 513 tokens (the
# residual failures observed after the initial task #4 deploy, 2026-06-16).
_UNICODE_ESCAPE_RE = re.compile(r"\\u[0-9a-fA-F]{4}")
# Live calibration (2026-06-16): an escape-dense Hebrew row was safe at ~600 chars /
# 75 escapes (~500 real tokens) but 400'd at 650 / 84 escapes, implying each decoded
# non-Latin codepoint costs BGE ~6 tokens.  We charge 6 per escape (conservative
# upper bound) so the budget truncation leaves real headroom under 512 even for
# all-Hebrew/CJK content.  Latin-only text contains no escapes, so it is unaffected.
_TOKENS_PER_UNICODE_ESCAPE = 6

# Conservative token budget for BAAI/bge-large-en-v1.5 (hard limit 512).
# 480 leaves >=32 tokens of headroom below the model's 512-token ceiling so that
# the estimator's residual error (it under-counts only for exotic Unicode, which
# our financial corpus barely contains) can never push the REAL count over 512.
# The audit proved 1100 dense chars (real ~<512 tokens) returns 200; our 480-token
# budget truncates dense text well below that boundary (~870 chars) — strictly safer.
MAX_TOKENS = 480

# Hard character backstop applied IN ADDITION to the token budget.  Even though
# the token budget is the binding constraint for dense text, a char cap bounds the
# pathological case of a very long run of whitespace/exotic chars the estimator
# treats as ~0 tokens, and keeps the request body small.  2000 is generous: any
# realistic >=480-token text is shorter than this, so for normal input the token
# budget — not this cap — decides the cut.
MAX_CHARS = 2000


def estimate_bert_tokens(text: str) -> int:
    """Conservatively UPPER-BOUND the WordPiece token count for BERT/BGE.

    The real ``bert-base`` WordPiece tokenizer (which BGE uses) splits on
    whitespace, then breaks each chunk into sub-word pieces and emits every
    punctuation character as its own token, plus 2 special tokens
    (``[CLS]`` / ``[SEP]``).  We approximate an *over-estimate* of that count
    without loading the tokenizer:

      * +2 for the ``[CLS]`` / ``[SEP]`` special tokens.
      * Each maximal alphanumeric run of length ``L`` contributes
        ``ceil(L / 3)`` sub-word tokens.  Real WordPiece averages ~3-4 chars per
        sub-word for English, so dividing by 3 (and rounding UP) over-counts —
        exactly the safe direction.
      * Every non-alphanumeric, non-whitespace character (``{ } " : , .`` digits
        separators, etc.) counts as 1 token — this is what makes JSON-envelope
        text correctly score as token-dense.

    Because every rule rounds toward MORE tokens, the result is >= the real
    tokenizer's output for our corpus, so a truncation that keeps this estimate
    under :data:`MAX_TOKENS` keeps the real count under 512.

    Special-cases JSON ``\\uXXXX`` escapes (see ``_UNICODE_ESCAPE_RE``): each is
    charged ``_TOKENS_PER_UNICODE_ESCAPE`` rather than the ~3 cheap tokens its 6
    ASCII chars would otherwise score, because the decoded non-Latin codepoint costs
    BGE more.  Escapes are blanked out FIRST so the alnum/punctuation rules below do
    not double-count their characters.
    """
    # Count + neutralise \uXXXX escapes so they don't leak into the cheap alnum rule.
    escape_count = 0

    def _blank(_m: re.Match[str]) -> str:
        nonlocal escape_count
        escape_count += 1
        return " " * 6  # same length (keeps positions stable; spaces are free)

    scrubbed = _UNICODE_ESCAPE_RE.sub(_blank, text)

    n = 2  # [CLS] + [SEP]
    n += escape_count * _TOKENS_PER_UNICODE_ESCAPE
    pos = 0
    for m in _WORD_RE.finditer(scrubbed):
        # Punctuation/symbols sitting BEFORE this word run → 1 token each.
        n += sum(1 for c in scrubbed[pos : m.start()] if not c.isspace())
        # Alphanumeric run → ceil(len / 3) sub-word tokens (over-estimate).
        word_len = len(m.group())
        n += -(-word_len // 3)  # ceil division
        pos = m.end()
    # Trailing punctuation/symbols after the last word run.
    n += sum(1 for c in scrubbed[pos:] if not c.isspace())
    return n


def truncate_for_bge(
    text: str,
    *,
    max_tokens: int = MAX_TOKENS,
    max_chars: int = MAX_CHARS,
) -> str:
    """Return ``text`` truncated to stay under the BGE 512-token context window.

    Truncates to the longest prefix whose :func:`estimate_bert_tokens` is
    ``<= max_tokens`` AND whose length is ``<= max_chars``.  Short inputs that
    already satisfy both bounds are returned unchanged (cheap fast-path).

    Uses a binary search over the prefix length so the (cheap, linear)
    estimator runs O(log n) times rather than re-scanning on every candidate.
    """
    # Fast path: most chunks/sections/queries are already within budget.
    if len(text) <= max_chars and estimate_bert_tokens(text) <= max_tokens:
        return text

    # Binary-search the largest prefix length that fits the token budget, never
    # exceeding the hard character backstop.
    lo, hi = 0, min(len(text), max_chars)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_bert_tokens(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]
