"""BriefDiffUseCase — text-normalised bullet diff between two consecutive morning briefs.

PLAN-0066 Wave C T-W10-C-01.

WHY frozen dataclasses (not Pydantic): the domain/application convention throughout
worldview is frozen dataclasses for domain DTOs. Pydantic is strictly an API-layer
tool (PLAN-0083). BriefDiffResult and DiffBullet are application-layer DTOs — they
belong here, not in the API schemas.

WHY BriefArchivePort (not BriefArchiveRepository): R25 mandates that use cases depend
on ports (Protocols), never concrete infrastructure adapters. This lets us substitute
NullBriefArchive in tests without any real DB.

WHY text normalisation (lowercase + strip): bullet text is free-form LLM output.
Two semantically identical bullets may differ only in leading/trailing whitespace or
capitalisation. Normalising before comparison avoids spurious diff noise.

WHY status enum as str (not Enum): keeps the DTO forward-compatible — adding a new
status value does not require a schema migration or Enum change. The API schema
enforces the allowed values via Literal annotation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from uuid import UUID

    from rag_chat.application.ports.brief_archive import BriefArchivePort, UserBriefRecord

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class DiffBullet:
    """A single bullet that is new or removed between two briefs.

    section_title — the section the bullet belongs to (e.g. "Market Movers")
    text          — raw bullet text as it appears in the brief
    citations     — optional list of citation dicts (only present on new_bullets
                    where the source brief has citation data; removed bullets
                    are serialised without citations to keep the diff payload lean)
    """

    section_title: str
    text: str
    citations: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class BriefDiffResult:
    """Diff between today's and yesterday's morning brief.

    status:
      "diff_available"     — two briefs exist; new/removed bullets computed
      "no_diff_available"  — fewer than 2 briefs; diff cannot be computed

    today_generated_at / yesterday_generated_at:
      ISO-8601 strings (UTC-aware), or None when the corresponding brief is absent.

    new_bullets:     bullets in today's brief that were not in yesterday's
    removed_bullets: bullets in yesterday's brief that are not in today's
    changed_sections: section titles where the bullet set changed
    delta_summary:   human-readable one-liner summarising the diff
    """

    status: str  # "diff_available" | "no_diff_available"
    today_generated_at: str | None
    yesterday_generated_at: str | None
    new_bullets: list[DiffBullet]
    removed_bullets: list[DiffBullet]
    changed_sections: list[str]
    delta_summary: str


class BriefDiffUseCase:
    """Compare the two most-recent morning briefs for a user and return a structured diff.

    WHY limit=2: we only need the last two briefs for the diff. Using get_latest()
    with limit=2 keeps the query to an index-only scan on
    (user_id, tenant_id, brief_type, generated_at DESC). Fetching more rows
    would add unnecessary DB load for a diff operation.

    WHY text normalisation: LLM output for the same bullet may have inconsistent
    casing or surrounding whitespace across runs. We normalise to lowercase + stripped
    text before building comparison sets to avoid false "new" / "removed" bullets.
    """

    def __init__(self, archive: BriefArchivePort) -> None:
        # WHY BriefArchivePort (not BriefArchiveRepository): R25 — use cases must
        # depend on ports (Protocols), never concrete infrastructure adapters.
        self._archive = archive

    async def execute(self, user_id: UUID, tenant_id: UUID) -> BriefDiffResult:
        """Fetch the two most-recent briefs and compute a bullet-level diff.

        Returns BriefDiffResult with status="no_diff_available" when fewer than
        two briefs exist (first-time users, or users with only one brief in the
        archive). The caller should surface delta_summary to the frontend.
        """
        # get_latest returns newest-first (DESC generated_at)
        briefs: list[UserBriefRecord] = await self._archive.get_latest(
            user_id=user_id,
            tenant_id=tenant_id,
            brief_type="morning",
            limit=2,
        )

        if len(briefs) < 2:
            # Not enough history to compute a diff — return a safe "no diff" result.
            today_ts = briefs[0].generated_at.isoformat() if briefs else None
            log.info(  # type: ignore[no-any-return]
                "brief_diff_insufficient_history",
                user_id=str(user_id),
                brief_count=len(briefs),
            )
            return BriefDiffResult(
                status="no_diff_available",
                today_generated_at=today_ts,
                yesterday_generated_at=None,
                new_bullets=[],
                removed_bullets=[],
                changed_sections=[],
                delta_summary="Not enough brief history to diff.",
            )

        today = briefs[0]  # most recent
        yesterday = briefs[1]  # second most recent

        # ── Extract bullets by section ────────────────────────────────────────
        today_bullets = _extract_bullets(today)
        yesterday_bullets = _extract_bullets(yesterday)

        # ── Compare section by section ────────────────────────────────────────
        new_bullets: list[DiffBullet] = []
        removed_bullets: list[DiffBullet] = []
        changed_sections: list[str] = []

        all_sections = sorted(set(today_bullets.keys()) | set(yesterday_bullets.keys()))

        for section in all_sections:
            t_bullets = today_bullets.get(section, [])
            y_bullets = yesterday_bullets.get(section, [])

            # Build normalised text sets for O(1) membership tests
            t_texts = {_normalise(b.get("text", "")) for b in t_bullets}
            y_texts = {_normalise(b.get("text", "")) for b in y_bullets}

            for b in t_bullets:
                if _normalise(b.get("text", "")) not in y_texts:
                    new_bullets.append(
                        DiffBullet(
                            section_title=section,
                            text=b.get("text", ""),
                            citations=b.get("citations", []),
                        )
                    )

            for b in y_bullets:
                if _normalise(b.get("text", "")) not in t_texts:
                    # WHY no citations on removed_bullets: removed bullets belong to
                    # yesterday's brief; surfacing citations for removed content would
                    # be confusing (the source articles may have been superseded).
                    removed_bullets.append(
                        DiffBullet(
                            section_title=section,
                            text=b.get("text", ""),
                        )
                    )

            # Mark section as changed if the normalised bullet sets differ
            if t_texts != y_texts:
                changed_sections.append(section)

        n_new = len(new_bullets)
        n_removed = len(removed_bullets)
        yesterday_date = yesterday.generated_at.strftime("%Y-%m-%d")
        delta = f"{n_new} new bullet{'s' if n_new != 1 else ''}, {n_removed} removed since {yesterday_date}"

        log.info(  # type: ignore[no-any-return]
            "brief_diff_computed",
            user_id=str(user_id),
            today_generated_at=today.generated_at.isoformat(),
            yesterday_generated_at=yesterday.generated_at.isoformat(),
            new_count=n_new,
            removed_count=n_removed,
            changed_sections=len(changed_sections),
        )

        return BriefDiffResult(
            status="diff_available",
            today_generated_at=today.generated_at.isoformat(),
            yesterday_generated_at=yesterday.generated_at.isoformat(),
            new_bullets=new_bullets,
            removed_bullets=removed_bullets,
            changed_sections=changed_sections,
            delta_summary=delta,
        )


# ── Module-level helpers ──────────────────────────────────────────────────────


def _extract_bullets(brief: UserBriefRecord) -> dict[str, list[dict]]:
    """Extract bullets keyed by section title from a UserBriefRecord.

    sections_json is list[dict] where each dict has:
      "title"   — section heading string
      "bullets" — list[dict] with at minimum {"text": str}

    WHY defensive: sections_json is a free-form JSONB field; malformed records
    (missing "title" or "bullets") are skipped silently rather than crashing
    the diff computation. Each bullet dict is included as-is for citation access.
    """
    result: dict[str, list[dict]] = {}
    for section in brief.sections_json:
        if not isinstance(section, dict):
            continue
        title = section.get("title", "")
        if not title:
            continue
        bullets = section.get("bullets", [])
        if not isinstance(bullets, list):
            continue
        # Normalise bullet entries: accept both plain strings (legacy format) and
        # dicts with a "text" key (current BriefBullet format).
        parsed: list[dict] = []
        for b in bullets:
            if isinstance(b, str):
                parsed.append({"text": b})
            elif isinstance(b, dict):
                parsed.append(b)
        result[title] = parsed
    return result


def _normalise(text: str) -> str:
    """Normalise bullet text for comparison: lowercase + strip whitespace.

    WHY lowercase: LLM output for the same concept may differ in capitalisation
    between runs (e.g. "Fed rate decision" vs "fed rate decision").
    WHY strip: leading/trailing whitespace is an artefact of LLM formatting;
    it carries no semantic meaning for the diff.
    """
    return text.lower().strip()
