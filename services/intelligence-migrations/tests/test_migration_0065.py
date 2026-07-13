"""Unit tests for migration 0065 (seed non-US/private entities) — Area-3 Phase 0+2.

These are DB-free: they import the migration module and assert the shape of the
seed roster + the SQL-building helpers. The integration tests in
test_migration_0038.py already exercise the apply/idempotency/downgrade contract
against a live Postgres for the identical INSERT pattern that 0065 reuses.
"""

from __future__ import annotations

import importlib.util
import os

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="session", autouse=True)
def run_migrations():  # type: ignore[no-untyped-def]
    """Override the conftest autouse fixture — these tests are DB-free.

    The package conftest ships a session-scoped ``autouse`` ``run_migrations``
    fixture that connects to Postgres. This module only inspects the migration
    module's Python constants, so we shadow it with a no-op to avoid requiring a
    live database for the data-shape checks.
    """
    yield


def _load_migration():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "alembic",
        "versions",
        "0065_seed_non_us_private_entities.py",
    )
    spec = importlib.util.spec_from_file_location("mig_0065", os.path.abspath(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Expected (entity_type, ticker, exchange) per canonical name.
_EXPECTED = {
    "Samsung Electronics Co., Ltd.": ("financial_instrument", "005930", "KRX"),
    "Xiaomi Corporation": ("financial_instrument", "1810", "HKEX"),
    "Tencent Holdings Ltd.": ("financial_instrument", "0700", "HKEX"),
    "Huawei Technologies Co., Ltd.": ("organization", None, None),
    "ByteDance Ltd.": ("organization", None, None),
    "Taiwan Semiconductor Manufacturing Company Limited": ("financial_instrument", "TSM", "US"),
}


def test_revision_chains_to_0064() -> None:
    mod = _load_migration()
    assert mod.revision == "0065"
    assert mod.down_revision == "0064"


def test_seed_roster_matches_expected_shape() -> None:
    mod = _load_migration()
    rows = {name: (etype, ticker, exchange) for (name, etype, ticker, exchange, _desc, _aliases) in mod._AREA3_SEEDS}
    assert rows == _EXPECTED


def test_private_orgs_have_no_ticker_or_exchange() -> None:
    """Huawei/ByteDance are ``organization`` with ticker=None AND exchange=None."""
    mod = _load_migration()
    for name, etype, ticker, exchange, _desc, _aliases in mod._AREA3_SEEDS:
        if etype == "organization":
            assert ticker is None, f"{name} organization must have NULL ticker"
            assert exchange is None, f"{name} organization must have NULL exchange"


def test_tsmc_adr_uses_us_exchange() -> None:
    """Phase 0: TSMC seeds with the US ADR ticker 'TSM' on exchange 'US'."""
    mod = _load_migration()
    tsmc = next(r for r in mod._AREA3_SEEDS if r[0].startswith("Taiwan Semiconductor"))
    _name, etype, ticker, exchange, _desc, _aliases = tsmc
    assert (etype, ticker, exchange) == ("financial_instrument", "TSM", "US")


def test_every_seed_has_aliases() -> None:
    mod = _load_migration()
    for name, _etype, _ticker, _exchange, _desc, aliases in mod._AREA3_SEEDS:
        assert aliases, f"{name} must ship at least one alias"


def test_uuid_helper_is_deterministic_and_shaped() -> None:
    mod = _load_migration()
    a = mod._uuid("a003", 1)
    b = mod._uuid("a003", 1)
    assert a == b
    assert a.startswith("0195daad-a003-")
    assert len(a) == 36  # canonical UUID length
