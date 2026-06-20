"""IActiveInstrumentsPort — application-layer interface for the "recently viewed instruments" lookup.

AI-brief-flag fix (2026-06-19).

WHY a port:
    The :class:`~rag_chat.application.workers.instrument_brief_pregeneration_worker.InstrumentBriefPregenerationWorker`
    needs the set of "instruments someone has looked at recently" so it can
    proactively pre-generate (and persist) their entity briefs — populating the
    screener ``has_ai_brief`` flag without waiting for the next on-demand view.

    In production this is backed by a Valkey sorted-set (``active_instruments``)
    populated by the on-demand instrument-brief route each time a brief is
    requested — exactly mirroring how S9 populates ``active_users`` for the
    morning-brief pre-gen worker. In tests we substitute a deterministic
    in-memory implementation. The port keeps the worker free of any
    Valkey-specific code (R25 — dependency rule).

WHY entity_id (the route param) and not instrument_id:
    The worker drives ``GenerateBriefingUseCase.execute_public_instrument``,
    which takes the KG ``entity_id`` route param and resolves the market-data
    instrument_id internally. So the active set stores the SAME id the route was
    called with (the entity_id), and the use case handles the id mapping.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IActiveInstrumentsPort(ABC):
    """Abstract port for "list instruments viewed in the last K days".

    The port is read-only: it never mutates the underlying source. Writes to the
    active set happen on the on-demand instrument-brief route, not here.
    """

    @abstractmethod
    async def list_active(self) -> list[str]:
        """Return the entity_ids whose instrument brief was requested in the window.

        Returns:
            A list of entity_id strings (the route param). Order is unspecified.
            On an empty source the list is empty (never ``None``).

        Implementations MUST be resilient to malformed entries — log a warning
        and skip the bad entry rather than raising, so one bad row never breaks
        the whole pre-generation pass.
        """
        ...


__all__ = ["IActiveInstrumentsPort"]
