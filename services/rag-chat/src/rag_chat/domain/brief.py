"""Domain value objects for structured AI briefings (PLAN-0062-W4).

WHY IN DOMAIN: BriefCitation, BriefBullet, BriefSection are constructed and
manipulated by the application-layer use case (generate_briefing.py) and also
appear in API response schemas. Placing them in domain lets application code
import them without crossing the LAYER-APP-ISOLATION boundary (application must
not import from api).

The api/schemas.py re-exports these classes so existing API callers are unaffected.

PLAN-0083 Wave A: migrated from `pydantic.BaseModel` to
`@dataclass(frozen=True, kw_only=True)` to align with the worldview domain
convention (frozen dataclasses everywhere — see PLAN-0074 §9.1, BP-405). The
public field set, validation rules, and `populate_by_name`/`source_id` legacy
alias semantics are preserved exactly. Validation now raises ``ValueError`` from
``__post_init__`` instead of ``pydantic.ValidationError`` from a ``Field(...)``
constraint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# WHY no pydantic import: PLAN-0083 hard constraint — domain layer must not
# import from pydantic. The api/schemas.py wrappers handle JSON serialization
# via the to_dict() round-trip (Pattern 1 in PLAN-0083 §3).

_VALID_SOURCE_TYPES: frozenset[str] = frozenset({"article", "event", "alert"})


@dataclass(frozen=True, kw_only=True)
class BriefCitation:
    """One source-document reference attached to a bullet (PLAN-0062-W4).

    WHY document_id (not source_id): the new bullet-level citation model uses
    'document_id' as the primary key to align with S6/S7 internal naming.
    The 'source_id' alias is accepted by ``from_dict`` for back-compat with
    legacy callers that still send the old field name (R11: never break wire
    format on the read path). ``to_dict`` always emits ``document_id`` only.

    WHY Literal source_type: strongly typed so the frontend can branch on
    source_type to decide which deep-link route to construct. Adding new
    source types requires a schema bump, which is correct behaviour.
    """

    document_id: str
    snippet: str
    url: str | None = None
    # WHY Literal[...]: source_type is enforced at __post_init__ time against
    # the _VALID_SOURCE_TYPES frozenset. Static type-checkers see the Literal.
    source_type: Literal["article", "event", "alert"] = "article"
    title: str | None = None

    def __post_init__(self) -> None:
        # WHY explicit ValueError: ports the Pydantic Field(..., max_length=400)
        # constraint to runtime guards. Same boundary (≤400 chars), but raised
        # as the canonical Python error rather than a pydantic.ValidationError.
        if len(self.snippet) > 400:
            raise ValueError(f"BriefCitation.snippet too long: {len(self.snippet)} > 400")
        if self.source_type not in _VALID_SOURCE_TYPES:
            # WHY runtime check: the Literal annotation is only enforced by mypy.
            # We need a runtime guard so callers passing a stray string fail fast
            # (mirrors Pydantic's ValidationError on Literal mismatch).
            raise ValueError(
                f"BriefCitation.source_type must be one of {sorted(_VALID_SOURCE_TYPES)}, got {self.source_type!r}"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BriefCitation:
        """Construct from a plain dict.

        WHY accept ``source_id`` as alias: the previous Pydantic model had
        ``model_config = ConfigDict(populate_by_name=True)`` which let callers
        send either ``document_id`` or the legacy ``source_id``. We preserve
        that read-path tolerance here so older cached payloads keep deserialising.
        """
        document_id = data.get("document_id") or data.get("source_id")
        if document_id is None:
            raise ValueError("BriefCitation requires document_id (or legacy source_id)")
        return cls(
            document_id=str(document_id),
            snippet=data["snippet"],
            url=data.get("url"),
            source_type=data.get("source_type", "article"),
            title=data.get("title"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict.

        WHY only ``document_id``: the legacy ``source_id`` alias is read-only —
        we never emit it on the write path so callers migrate cleanly.
        """
        return {
            "document_id": self.document_id,
            "snippet": self.snippet,
            "url": self.url,
            "source_type": self.source_type,
            "title": self.title,
        }


@dataclass(frozen=True, kw_only=True)
class BriefBullet:
    """One bullet inside a section (PLAN-0062-W4).

    WHY citations min_length=1: this is the 100% citation gate. Every bullet
    that reaches the response MUST have at least one citation. Bullets without
    citations are filtered out by ``_backfill_uncited_bullets()`` before
    construction, so a BriefBullet with citations=[] should never be created.

    WHY text max_length=400: generous cap that covers the longest real brief
    bullets (140 chars target, 400 hard cap to tolerate LLM verbosity).
    """

    text: str
    citations: list[BriefCitation]

    def __post_init__(self) -> None:
        # Port Pydantic Field(..., min_length=1, max_length=400) on text.
        if len(self.text) < 1:
            raise ValueError("BriefBullet.text must be non-empty (min_length=1)")
        if len(self.text) > 400:
            raise ValueError(f"BriefBullet.text too long: {len(self.text)} > 400")
        # Port Pydantic Field(..., min_length=1) on citations (the 100% gate).
        if len(self.citations) < 1:
            raise ValueError("BriefBullet.citations must contain at least one citation (min_length=1)")
        # WHY runtime type guard: the type hint is list[BriefCitation] but
        # callers using ** unpacking from raw dicts (e.g. cached payloads) would
        # silently bypass dataclass typing. Reject non-BriefCitation entries
        # explicitly so the legacy v1 cache shape is rejected cleanly (matches
        # the prior Pydantic ValidationError path).
        for c in self.citations:
            if not isinstance(c, BriefCitation):
                raise ValueError(
                    f"BriefBullet.citations entries must be BriefCitation instances, got {type(c).__name__}"
                )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BriefBullet:
        raw_cits = data.get("citations") or []
        cits = [c if isinstance(c, BriefCitation) else BriefCitation.from_dict(c) for c in raw_cits]
        return cls(text=data["text"], citations=cits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass(frozen=True, kw_only=True)
class BriefSection:
    """One section of a structured AI brief (PLAN-0049 T-A-1-04, F-D-001).

    Renders as a heading followed by a bullet list. The frontend
    ``<MorningBriefCard>`` and ``<InstrumentAISubheader>`` prefer this
    structured shape when ``sections`` is non-empty; otherwise both fall
    back to rendering ``narrative`` through ``<MarkdownContent>``.

    PLAN-0062-W4: bullets changed from list[str] to list[BriefBullet] so
    each bullet carries citations. min_length=0 enables the backfill pattern
    where sections with zero remaining bullets are dropped rather than crashing.
    """

    title: str
    # WHY default_factory=list: lets callers omit ``bullets`` for empty sections
    # (the backfill pass routinely creates ``BriefSection(title=..., bullets=[])``
    # which is then dropped by ``_backfill_uncited_bullets``).
    bullets: list[BriefBullet] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Port Pydantic Field(..., max_length=120) on title.
        if len(self.title) > 120:
            raise ValueError(f"BriefSection.title too long: {len(self.title)} > 120")
        # Port Pydantic Field(..., min_length=0, max_length=8) on bullets.
        if len(self.bullets) > 8:
            raise ValueError(f"BriefSection.bullets too many: {len(self.bullets)} > 8")
        # WHY runtime type guard: parallels BriefBullet — reject the legacy v1
        # cache shape (string bullets) explicitly so callers fail loudly rather
        # than silently producing an invalid object that breaks downstream JSON.
        for b in self.bullets:
            if not isinstance(b, BriefBullet):
                raise ValueError(f"BriefSection.bullets entries must be BriefBullet instances, got {type(b).__name__}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BriefSection:
        raw_bullets = data.get("bullets") or []
        bullets = [b if isinstance(b, BriefBullet) else BriefBullet.from_dict(b) for b in raw_bullets]
        return cls(title=data["title"], bullets=bullets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "bullets": [b.to_dict() for b in self.bullets],
        }
