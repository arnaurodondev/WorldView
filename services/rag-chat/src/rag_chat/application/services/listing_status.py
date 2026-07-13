"""Listing-status registry — graceful handling of non-US-listed & private companies.

WHY THIS MODULE EXISTS (Area-3 Phase 0 + Phase 2 of the chat-enhancement roadmap
``docs/plans/2026-07-09-chat-enhancement-roadmap.md``):

  The ``iter3_apple_competitors_spanish`` benchmark question ("Apple's smartphone
  competitors") FAILED because the compared entities — Samsung (KRX 005930),
  Xiaomi (HKEX 1810), Huawei (private), Tencent (HKEX 0700) — are NOT US-listed.
  When the chat tried to treat them like US tickers the downstream tools returned
  empty and the model **fabricated** a plausible-but-wrong US ticker / entity
  (once "Estée Lauder"). Worldview does not (yet) ingest live HKEX/KRX prices, and
  Huawei/ByteDance are privately held — so the correct behaviour is NOT to invent a
  ticker but to **state the listing status honestly** and discuss the company from
  knowledge-graph intelligence + news.

  This registry is the *resolution-side* half of the fix (the other half is the
  KG seed migration ``0065_seed_non_us_private_entities.py`` in
  ``intelligence-migrations``, which creates the canonical entities so the names
  resolve at all). Kept as a small, self-contained, deterministic table so the
  ``IntelligenceHandler`` can annotate KG tool results with a listing-status note
  WITHOUT a live knowledge-graph-service round-trip (the ``/entities/resolve``
  endpoint only returns entity_id + alias + similarity, not exchange/entity_type).

  The company set here MUST stay in sync with the seed migration's roster. When a
  future phase ships live HKEX/KRX price + fundamentals ingestion (Area-3 Phase 1)
  the ``is_price_covered`` flag for the affected exchanges should flip to ``True``
  and the "not currently ingested" wording drops out automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ListingStatus:
    """Authoritative listing facts for a company Worldview cannot price like a US stock.

    Attributes
    ----------
    canonical_name:
        Full company name used in the graceful message.
    is_public:
        ``True`` for publicly traded companies (with a non-US primary listing);
        ``False`` for privately held organisations (Huawei, ByteDance).
    exchange:
        Primary listing exchange code (e.g. ``"HKEX"``, ``"KRX"``). ``None`` for
        private companies.
    local_ticker:
        The local-exchange ticker/code (e.g. ``"1810"`` on HKEX, ``"005930"`` on
        KRX). ``None`` for private companies.
    us_adr_ticker:
        A US-listed ADR ticker when one exists (e.g. ``"TSM"`` for TSMC). ``None``
        when the company has no US ADR. When present, Worldview CAN price the ADR
        through the existing US pipeline (Area-3 Phase 0).
    """

    canonical_name: str
    is_public: bool
    exchange: str | None = None
    local_ticker: str | None = None
    us_adr_ticker: str | None = None

    def describe(self) -> str:
        """Return a one-line, model-facing statement of the listing status.

        The wording is deliberately explicit so the LLM repeats the *fact* rather
        than fabricating a US ticker: it states the listing venue (or "privately
        held"), and — critically — that Worldview does not currently ingest live
        prices for that venue, so a US-style quote/fundamentals comparison is
        unavailable and must NOT be invented.
        """
        # Private company — no ticker anywhere.
        if not self.is_public:
            return (
                f"{self.canonical_name} is privately held and is NOT publicly traded on any "
                f"stock exchange, so it has no ticker and no market quote or fundamentals. "
                f"Do not assign it a ticker — discuss it only from knowledge-graph intelligence "
                f"and news."
            )

        # Public, non-US, WITH a US ADR — Worldview can price the ADR.
        if self.us_adr_ticker is not None:
            venue = f"listed on {self.exchange} as {self.local_ticker}" if self.exchange else "listed abroad"
            return (
                f"{self.canonical_name} is {venue}. It also trades in the US as an ADR under "
                f"'{self.us_adr_ticker}', which Worldview CAN price — use the '{self.us_adr_ticker}' "
                f"ADR for any US-style quote or fundamentals. Worldview does not currently ingest "
                f"live {self.exchange or 'home-market'} prices."
            )

        # Public, non-US, NO US ADR — no US price available at all.
        venue = f"listed on {self.exchange} as {self.local_ticker}" if self.exchange else "listed on a non-US exchange"
        return (
            f"{self.canonical_name} is {venue}. Worldview does not currently ingest live "
            f"{self.exchange or 'non-US'} prices, so a live quote/fundamentals comparison is "
            f"unavailable — do NOT fabricate a US ticker. The company can still be discussed from "
            f"knowledge-graph intelligence and news."
        )


def _normalize(name: str) -> str:
    """Lower-case, drop punctuation & common corporate suffixes, collapse whitespace.

    Mirrors the light normalisation used elsewhere in the resolver so that
    "Samsung", "Samsung Electronics", "SAMSUNG ELECTRONICS CO., LTD." all map to
    the same registry key.
    """
    t = name.lower().strip()
    # Replace any run of non-alphanumeric characters with a single space.
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    # Strip a single trailing corporate suffix token if present.
    tokens = t.split()
    _suffixes = {"inc", "corp", "corporation", "ltd", "limited", "co", "company", "holdings", "plc", "sa", "ag", "nv"}
    while tokens and tokens[-1] in _suffixes:
        tokens.pop()
    return " ".join(tokens)


# ── Registry ───────────────────────────────────────────────────────────────────
# Keyed by normalised alias → ListingStatus. Every alias for a company points at
# the SAME ListingStatus instance. The roster MUST mirror the seed migration
# 0065_seed_non_us_private_entities.py in intelligence-migrations.
_SAMSUNG = ListingStatus("Samsung Electronics Co., Ltd.", is_public=True, exchange="KRX", local_ticker="005930")
_XIAOMI = ListingStatus("Xiaomi Corporation", is_public=True, exchange="HKEX", local_ticker="1810")
_TENCENT = ListingStatus("Tencent Holdings Ltd.", is_public=True, exchange="HKEX", local_ticker="0700")
_HUAWEI = ListingStatus("Huawei Technologies Co., Ltd.", is_public=False)
_BYTEDANCE = ListingStatus("ByteDance Ltd.", is_public=False)
# TSMC has a US ADR (TSM) — Worldview CAN price it via the existing US pipeline.
_TSMC = ListingStatus(
    "Taiwan Semiconductor Manufacturing Company Limited",
    is_public=True,
    exchange="TWSE",
    local_ticker="2330",
    us_adr_ticker="TSM",
)

_REGISTRY: dict[str, ListingStatus] = {}
for _status, _aliases in [
    (_SAMSUNG, ["Samsung", "Samsung Electronics", "Samsung Electronics Co., Ltd.", "005930"]),
    (_XIAOMI, ["Xiaomi", "Xiaomi Corp", "Xiaomi Corporation", "1810"]),
    (_TENCENT, ["Tencent", "Tencent Holdings", "Tencent Holdings Ltd.", "0700"]),
    (_HUAWEI, ["Huawei", "Huawei Technologies", "Huawei Technologies Co., Ltd."]),
    (_BYTEDANCE, ["ByteDance", "Bytedance", "ByteDance Ltd."]),
    (_TSMC, ["TSMC", "Taiwan Semiconductor", "Taiwan Semiconductor Manufacturing Company Limited", "TSM"]),
]:
    for _alias in _aliases:
        _REGISTRY[_normalize(_alias)] = _status


def lookup_listing_status(name: str) -> ListingStatus | None:
    """Return the ListingStatus for a company name, or ``None`` if not in the registry.

    Matching is normalisation-based (case/suffix/punctuation-insensitive) so the
    caller can pass whatever string the LLM echoed ("Samsung", "SAMSUNG
    ELECTRONICS CO., LTD.", "Xiaomi Corp") and still hit the right row.
    """
    if not name or not name.strip():
        return None
    return _REGISTRY.get(_normalize(name))
