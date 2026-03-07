"""Canonical article model — aligned with content.article.stored.v1.avsc."""

from __future__ import annotations

from dataclasses import dataclass, field

from contracts.versions import ARTICLE_SCHEMA_VERSION


@dataclass(frozen=True)
class CanonicalArticle:
    """Normalised news/content article for the Content pipeline (S4/S5).

    Fields align with content.article.stored.v1.avsc for consumer compatibility.
    body_text carries the full article body (stored separately from the Avro event
    that uses a MinIO claim-check pointer).
    """

    article_id: str
    source_domain: str
    title: str
    url: str
    language: str = "en"
    word_count: int = 0
    is_duplicate: bool = False
    duplicate_of: str | None = None
    published_at: str | None = None
    body_text: str = ""
    schema_version: int = field(default=ARTICLE_SCHEMA_VERSION, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalArticle:
        return cls(
            article_id=d["article_id"],
            source_domain=d["source_domain"],
            title=d["title"],
            url=d["url"],
            language=d.get("language", "en"),
            word_count=int(d.get("word_count", 0)),
            is_duplicate=bool(d.get("is_duplicate", False)),
            duplicate_of=d.get("duplicate_of"),
            published_at=d.get("published_at"),
            body_text=d.get("body_text", ""),
        )

    def to_dict(self) -> dict:
        return {
            "article_id": self.article_id,
            "source_domain": self.source_domain,
            "title": self.title,
            "url": self.url,
            "language": self.language,
            "word_count": self.word_count,
            "is_duplicate": self.is_duplicate,
            "duplicate_of": self.duplicate_of,
            "published_at": self.published_at,
            "body_text": self.body_text,
            "schema_version": self.schema_version,
        }
