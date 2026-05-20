"""Canonical ticker normalization helper (PLAN-0089 F2 step 7).

Multi-class equity tickers arrive from upstream sources (EODHD, Alpaca, Yahoo,
Polygon, …) in three interchangeable separators:

    BRK.B   (EODHD / canonical dot form)
    BRK-B   (Yahoo / IB / most US data feeds)
    BRK/B   (Bloomberg legacy / a few REST APIs)

If the DB stores all three forms for the same underlying security, downstream
joins (entity → instrument → ohlcv → fundamentals) silently fragment.  We
therefore canonicalise at the *adapter boundary* — i.e. the single point in
each ingestion path where a raw external symbol is about to be persisted (or
used as a lookup key for an existing row written under the canonical form).

Canonical form (this module's output):
    * uppercase
    * separator is ``.``  (``-`` and ``/`` both map to ``.``)
    * surrounding whitespace stripped
    * leading ``^`` preserved (index tickers like ``^GSPC``) — the frontend, not
      the normalizer, is responsible for any index-specific UI stripping.

Tickers that legitimately contain ``-`` in some markets (e.g. ``BABA-N`` on
some Polish/NYSE-overlay feeds) are NOT special-cased here.  Reasoning: every
real-world equity adapter we currently ingest from emits dot-form for
multi-class tickers, and ``-`` always means class-share separator in the
sources we touch.  If a future adapter introduces a hyphen-bearing primary
ticker, the fix is to special-case it in that adapter's mapping table BEFORE
calling ``_normalize_ticker`` (so the hyphen never reaches this helper).
"""

from __future__ import annotations


def _normalize_ticker(raw: str) -> str:
    """Return the canonical dot-form, uppercase ticker for ``raw``.

    Examples
    --------
    >>> _normalize_ticker("brk.b")
    'BRK.B'
    >>> _normalize_ticker("BRK-B")
    'BRK.B'
    >>> _normalize_ticker("BRK/B")
    'BRK.B'
    >>> _normalize_ticker("  aapl  ")
    'AAPL'
    >>> _normalize_ticker("^GSPC")
    '^GSPC'

    Behaviour
    ---------
    * Strips surrounding whitespace.
    * Uppercases.
    * Replaces ``-`` and ``/`` with ``.`` so that the three common
      multi-class spellings collapse to one form.
    * An empty / whitespace-only input returns the empty string — callers
      that need a non-empty contract should validate separately.
    """
    return raw.strip().upper().replace("-", ".").replace("/", ".")
