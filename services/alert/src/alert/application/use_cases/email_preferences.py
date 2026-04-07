"""Use cases for email preference management (S10).

R25: uses only port ABCs -- no infrastructure imports.
R27: GetEmailPreferencesUseCase reads via a read-only session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alert.domain.entities import EmailPreference

if TYPE_CHECKING:
    from uuid import UUID

    from alert.application.ports.repositories import EmailPreferenceRepositoryPort


# ---------------------------------------------------------------------------
# Sentinel for distinguishing "not provided" from explicit None
# ---------------------------------------------------------------------------


class _Unset:
    """Sentinel: distinguishes *not supplied* from explicit ``None``."""

    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _Unset()


# ---------------------------------------------------------------------------
# Use cases
# ---------------------------------------------------------------------------


class GetEmailPreferencesUseCase:
    """Return a user's email preferences, creating defaults if none exist.

    Always returns an ``EmailPreference`` -- never raises 404.  When no row
    exists in the DB the default-constructed entity is upserted and returned.

    Args:
    ----
        repo: EmailPreferenceRepositoryPort (pass the write repo so that
              first-access defaults are persisted).

    """

    def __init__(self, repo: EmailPreferenceRepositoryPort) -> None:
        self._repo = repo

    async def execute(self, user_id: UUID, tenant_id: UUID) -> EmailPreference:
        """Return preferences, upsert defaults if the row is absent."""
        result = await self._repo.get_by_user(user_id, tenant_id)
        if result is None:
            result = EmailPreference(user_id=user_id, tenant_id=tenant_id)
            await self._repo.upsert(result)
            await self._repo.commit()
        return result


class UpdateEmailPreferencesUseCase:
    """Validate and persist email preference changes.

    Validates ownership: the supplied *user_id* and *tenant_id* must match
    any existing row.  Also enforces domain invariants:
    ``send_day_of_week`` 0-6, ``send_hour_utc`` 0-23.
    Raises :class:`ValueError` for bad values (converted to 400 in the API
    layer).
    """

    def __init__(self, repo: EmailPreferenceRepositoryPort) -> None:
        self._repo = repo

    async def execute(
        self,
        user_id: UUID,
        tenant_id: UUID,
        *,
        weekly_digest_enabled: bool | None = None,
        send_day_of_week: int | None = None,
        send_hour_utc: int | None = None,
        email_address: str | None | _Unset = _UNSET,
    ) -> EmailPreference:
        """Apply partial updates and upsert.

        Only supplied (non-``_UNSET``) fields are updated.  ``email_address``
        may be explicitly set to ``None`` to clear the override address.
        """
        pref = await self._repo.get_by_user(user_id, tenant_id)
        if pref is None:
            pref = EmailPreference(user_id=user_id, tenant_id=tenant_id)

        # EmailPreference is a frozen dataclass -- rebuild with updates applied
        new_addr = pref.email_address if isinstance(email_address, _Unset) else email_address
        updated = EmailPreference(
            user_id=pref.user_id,
            tenant_id=pref.tenant_id,
            weekly_digest_enabled=(
                weekly_digest_enabled if weekly_digest_enabled is not None else pref.weekly_digest_enabled
            ),
            send_day_of_week=send_day_of_week if send_day_of_week is not None else pref.send_day_of_week,
            send_hour_utc=send_hour_utc if send_hour_utc is not None else pref.send_hour_utc,
            email_address=new_addr,
            last_digest_sent_at=pref.last_digest_sent_at,
            created_at=pref.created_at,
        )
        await self._repo.upsert(updated)
        await self._repo.commit()
        return updated
