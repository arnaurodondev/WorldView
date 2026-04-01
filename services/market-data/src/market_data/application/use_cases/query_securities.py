"""Security query use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork
    from market_data.domain.entities import Security


class GetSecurityUseCase:
    """Return a security by FIGI or ISIN identifier, or ``None``.

    Lookup strategy:
    - 12-char string starting with 2 letters then digits → try ISIN first
    - Otherwise → try FIGI, fall back to ISIN
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, security_id: str) -> Security | None:
        repo = self._uow.securities_read
        security: Security | None = None
        if len(security_id) == 12 and security_id[:2].isalpha() and security_id[2:].isdigit():
            security = await repo.find_by_isin(security_id)
        else:
            security = await repo.find_by_figi(security_id)
            if security is None:
                security = await repo.find_by_isin(security_id)
        return security


class ListSecuritiesUseCase:
    """List securities with optional FIGI/ISIN filter and pagination.

    Returns ``(items, total)`` where total is the count for the given filter.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        figi: str | None = None,
        isin: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Security], int]:
        repo = self._uow.securities_read
        if figi is not None:
            sec = await repo.find_by_figi(figi)
            securities = [sec] if sec is not None else []
            return securities, len(securities)
        if isin is not None:
            sec = await repo.find_by_isin(isin)
            securities = [sec] if sec is not None else []
            return securities, len(securities)
        return await repo.list(limit=limit, offset=offset)
