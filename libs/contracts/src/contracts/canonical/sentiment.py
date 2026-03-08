"""Canonical sentiment analysis result model."""

from __future__ import annotations

from dataclasses import dataclass, field

from contracts.versions import SENTIMENT_SCHEMA_VERSION


@dataclass(frozen=True)
class CanonicalSentiment:
    """Sentiment analysis result for an article (output of S6 Intelligence service).

    label: "positive" | "negative" | "neutral"
    score: probability of the label in [0.0, 1.0]
    """

    article_id: str
    label: str
    score: float
    model_name: str
    model_version: str
    schema_version: int = field(default=SENTIMENT_SCHEMA_VERSION, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalSentiment:
        return cls(
            article_id=d["article_id"],
            label=d["label"],
            score=float(d["score"]),
            model_name=d["model_name"],
            model_version=d["model_version"],
        )

    def to_dict(self) -> dict:
        return {
            "article_id": self.article_id,
            "label": self.label,
            "score": self.score,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "schema_version": self.schema_version,
        }
