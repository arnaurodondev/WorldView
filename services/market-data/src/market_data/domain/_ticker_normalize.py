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

Crypto exemption (BP class: ``BTC-USD`` -> ``BTC.USD`` duplication)
-------------------------------------------------------------------
Crypto pairs are the one canonical form that DOES contain a hyphen:
``BTC-USD``, ``ETH-USD``, …  The Alpaca adapter detects crypto via
``endswith("-USD")`` and EODHD uses ``-USD.CC``, so the hyphenated pair IS
the canonical symbol.  Before this exemption the blanket ``-`` -> ``.``
rewrite turned ``BTC-USD`` into ``BTC.USD``; the OHLCV consumer then missed
the existing ``-USD`` instrument and auto-created a ``.USD`` duplicate
(one phantom instrument per crypto symbol).  Symbols matching
``^[A-Z0-9]+-USD$`` (after strip/uppercase) are therefore returned as-is.
"""

from __future__ import annotations

import re

# Canonical crypto pair, e.g. "BTC-USD", "SHIB-USD". Matched AFTER
# strip()+upper() so lowercase inputs like "btc-usd" are also exempted.
_CRYPTO_USD_PAIR_RE = re.compile(r"^[A-Z0-9]+-USD$")


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
    >>> _normalize_ticker("BTC-USD")
    'BTC-USD'

    Behaviour
    ---------
    * Strips surrounding whitespace.
    * Uppercases.
    * Crypto pairs (``^[A-Z0-9]+-USD$``) keep their hyphen — the hyphenated
      pair is the canonical crypto symbol (Alpaca/EODHD), see module docstring.
    * Otherwise replaces ``-`` and ``/`` with ``.`` so that the three common
      multi-class spellings collapse to one form.
    * An empty / whitespace-only input returns the empty string — callers
      that need a non-empty contract should validate separately.
    """
    cleaned = raw.strip().upper()
    if _CRYPTO_USD_PAIR_RE.match(cleaned):
        # Canonical crypto pair (e.g. BTC-USD) — the hyphen is load-bearing.
        return cleaned
    return cleaned.replace("-", ".").replace("/", ".")
