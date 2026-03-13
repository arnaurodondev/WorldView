"""Canonical daily sentiment model (EXT-05)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalDailySentiment:
    """Aggregated daily sentiment signal for a single instrument."""

    symbol: str
    exchange: str
    date: str  # YYYY-MM-DD
    polarity_mean: float  # mean across articles that day (-1..1)
    pos_mean: float
    neu_mean: float
    neg_mean: float
    article_count: int
    source: str
    fetched_at: str

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalDailySentiment:
        return cls(
            symbol=d.get("symbol", ""),
            exchange=d.get("exchange", ""),
            date=d.get("date", ""),
            polarity_mean=float(d.get("polarity_mean", 0)),
            pos_mean=float(d.get("pos_mean", 0)),
            neu_mean=float(d.get("neu_mean", 0)),
            neg_mean=float(d.get("neg_mean", 0)),
            article_count=int(d.get("article_count", 0)),
            source=d.get("source", "eodhd"),
            fetched_at=d.get("fetched_at", ""),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "date": self.date,
            "polarity_mean": self.polarity_mean,
            "pos_mean": self.pos_mean,
            "neu_mean": self.neu_mean,
            "neg_mean": self.neg_mean,
            "article_count": self.article_count,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }
