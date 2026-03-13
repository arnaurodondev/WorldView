"""Canonical insider transaction model (EXT-06)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalInsiderTransaction:
    """A single Form 4 insider transaction record."""

    symbol: str
    exchange: str
    owner_name: str
    owner_title: str
    transaction_date: str  # YYYY-MM-DD
    transaction_code: str  # "P" | "S" | "A" | "D" | etc.
    shares: float | None
    price_per_share: float | None
    acquired_disposed: str  # "A" | "D"
    total_shares_owned: float | None
    source: str
    fetched_at: str

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalInsiderTransaction:
        def _f(v: object) -> float | None:
            if v is None or v == "":
                return None
            try:
                return float(v)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                return None

        return cls(
            symbol=d.get("symbol", ""),
            exchange=d.get("exchange", ""),
            owner_name=d.get("ownerName") or d.get("owner_name", ""),
            owner_title=d.get("ownerTitle") or d.get("owner_title", ""),
            transaction_date=d.get("transactionDate") or d.get("transaction_date", ""),
            transaction_code=d.get("transactionCode") or d.get("transaction_code", ""),
            shares=_f(d.get("transactionAmount") or d.get("shares")),
            price_per_share=_f(d.get("transactionPrice") or d.get("price_per_share")),
            acquired_disposed=d.get("transactionAcquiredDisposed") or d.get("acquired_disposed", ""),
            total_shares_owned=_f(d.get("ownershipType") or d.get("total_shares_owned")),
            source=d.get("source", "eodhd"),
            fetched_at=d.get("fetched_at", ""),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "owner_name": self.owner_name,
            "owner_title": self.owner_title,
            "transaction_date": self.transaction_date,
            "transaction_code": self.transaction_code,
            "shares": self.shares,
            "price_per_share": self.price_per_share,
            "acquired_disposed": self.acquired_disposed,
            "total_shares_owned": self.total_shares_owned,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }
