"""Value objects for the RAG-Chat service (S8) — immutable, validated."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DateRange:
    """Inclusive date range for temporal filtering in retrieval.

    Both fields are optional; when both are set, start MUST be <= end.
    """

    start: date | None = None
    end: date | None = None

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError(f"DateRange.start ({self.start}) must be <= end ({self.end})")
