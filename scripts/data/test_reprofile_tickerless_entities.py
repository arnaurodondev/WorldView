"""Unit tests for the FR-12 tickerless-FI reprofile script.

Covers the three pure cores — the deterministic classifier, the LLM-type
normaliser, and the LLM-result parser — plus the dry-run / apply orchestration
against a minimal fake psycopg connection and a stubbed LLM stage.  No live DB
and no live LLM calls.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import reprofile_tickerless_entities as mod
from reprofile_tickerless_entities import (
    Candidate,
    Retype,
    classify_deterministic,
    normalize_llm_type,
    parse_llm_retype,
)

pytestmark = pytest.mark.unit


# ── Deterministic classifier ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "expected_type", "expected_rule"),
    [
        # pure phrases -> unknown
        ("shares", "unknown", "pure_phrase"),
        ("common stock", "unknown", "pure_phrase"),
        ("Class A shares", "unknown", "pure_phrase"),
        ("Stock futures", "unknown", "pure_phrase"),
        # price literals -> unknown
        ("$135", "unknown", "price_literal"),
        ("RMB49", "unknown", "price_literal"),
        ("US$15.20", "unknown", "price_literal"),
        ("$0.0732", "unknown", "price_literal"),
        # funds / ETFs -> index
        ("Schwab U.S. Dividend Equity ETF", "index", "fund"),
        ("Roundhill Memory ETF", "index", "fund"),
        # index baskets -> index
        ("S&P 500", "index", "index"),
        ("Nasdaq Composite", "index", "index"),
        ("Dow Jones Industrial Average Index", "index", "index"),
        # "<X> shares" / "<X> stock" phrases -> unknown
        ("Apple shares", "unknown", "phrase_suffix"),
        ("Microsoft Stock", "unknown", "phrase_suffix"),
        ("Nvidia equity", "unknown", "phrase_suffix"),
        # FR-12: high-confidence org markers -> organization
        ("Duke Energy Foundation", "organization", "organization"),
        ("MIT Media Institute", "organization", "organization"),
        ("Stanford University", "organization", "organization"),
        ("Andreessen Horowitz Ventures", "organization", "organization"),
        ("Sequoia Capital Partners", "organization", "organization"),
        ("Acme Buyout LLC", "organization", "organization"),
        ("Foobar GmbH", "organization", "organization"),
        ("Securities and Exchange Commission", "organization", "organization"),
        ("World Wildlife Charity", "organization", "organization"),
    ],
)
def test_deterministic_hits(name: str, expected_type: str, expected_rule: str) -> None:
    r = classify_deterministic("e1", name)
    assert r is not None, f"expected a deterministic hit for {name!r}"
    assert r.new_type == expected_type
    assert r.rule == expected_rule
    assert r.old_type == "financial_instrument"


@pytest.mark.parametrize(
    "name",
    [
        # Private companies / orgs with NO high-confidence marker — these carry no
        # Foundation/Institute/LLC/agency token, so the deterministic pass cannot
        # safely re-type them and MUST defer to the LLM stage.
        "SpaceX",
        "Anthropic",
        "Zacks",
        "Hankook Tire",
        "Y Combinator",
        "Federal Reserve Bank of Dallas",
        "Etihad Airways",
        "Stripe",
        "OpenAI",
    ],
)
def test_deterministic_defers_ambiguous(name: str) -> None:
    """Private companies / orgs with no clear marker are deferred to the LLM stage."""
    assert classify_deterministic("e1", name) is None


def test_deterministic_empty_name_is_none() -> None:
    assert classify_deterministic("e1", "") is None
    assert classify_deterministic("e1", "   ") is None


def test_deterministic_whitespace_collapsed() -> None:
    """Internal whitespace is collapsed before matching."""
    r = classify_deterministic("e1", "  Apple   shares  ")
    assert r is not None and r.rule == "phrase_suffix"


def test_fund_beats_phrase_suffix() -> None:
    """An ETF whose name ends in 'equity' must land as index (fund), not unknown."""
    r = classify_deterministic("e1", "Some Dividend Equity ETF")
    assert r is not None and r.new_type == "index" and r.rule == "fund"


# ── LLM-type normaliser ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("person", "person"),
        ("Place", "place"),
        ("macro indicator", "macro_indicator"),
        ("company", "financial_instrument"),  # alias
        ("organization", "organization"),  # FR-12 / migration 0055: now canonical
        ("organisation", "organization"),  # alias
        ("regulator", "organization"),  # alias (SEC, Fed)
        ("country", "place"),  # alias
        ("commodity", "product"),  # alias
        ("ETF", "index"),  # alias
        ("foundation", "organization"),  # FR-12 alias
        ("university", "organization"),  # FR-12 alias
        ("nonprofit", "organization"),  # FR-12 alias
    ],
)
def test_normalize_llm_type_valid(raw: str, expected: str) -> None:
    assert normalize_llm_type(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "banana", "not_a_type", 123])
def test_normalize_llm_type_invalid_returns_none(raw: object) -> None:
    assert normalize_llm_type(raw) is None  # type: ignore[arg-type]


# ── LLM-result parser ─────────────────────────────────────────────────────────


def test_parse_llm_retype_valid() -> None:
    r = parse_llm_retype("e1", "SpaceX", {"entity_type": "unknown"})
    assert r is not None and r.new_type == "unknown" and r.rule == "llm"


def test_parse_llm_retype_alias_mapped() -> None:
    r = parse_llm_retype("e1", "Apple River", {"entity_type": "country"})
    assert r is not None and r.new_type == "place"


def test_parse_llm_retype_none_result_unchanged() -> None:
    assert parse_llm_retype("e1", "X", None) is None


def test_parse_llm_retype_invalid_type_unchanged() -> None:
    """An unmappable type leaves the row unchanged (never writes invalid type)."""
    assert parse_llm_retype("e1", "X", {"entity_type": "spaceship"}) is None


def test_parse_llm_retype_confirms_instrument_is_noop() -> None:
    """If the LLM agrees it's a financial_instrument, no re-type is planned."""
    assert parse_llm_retype("e1", "Real Co", {"entity_type": "financial_instrument"}) is None


def test_parse_llm_retype_missing_type_unchanged() -> None:
    assert parse_llm_retype("e1", "X", {"canonical_name": "X"}) is None


def test_parse_llm_retype_organization() -> None:
    """FR-12: the LLM may now return 'organization' for a tickerless private co."""
    r = parse_llm_retype("e1", "SpaceX", {"entity_type": "organization"})
    assert r is not None and r.new_type == "organization" and r.rule == "llm"


# ── Valid-type set (must mirror DB CHECK post migration 0055) ─────────────────


def test_valid_entity_types_has_organization_and_13_values() -> None:
    """The script's valid-type set must match the 13-value DB CHECK (migration 0055)."""
    assert "organization" in mod._VALID_ENTITY_TYPES
    assert "exchange" in mod._VALID_ENTITY_TYPES
    assert len(mod._VALID_ENTITY_TYPES) == 13


# ── LLM stage rework — production request shape ───────────────────────────────


def test_run_llm_stage_uses_full_production_output_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reworked LLM stage must mirror the production extract_entity_profile shape.

    The original mis-wiring passed a truncated ``{"entity_type": "string"}``
    output_schema (which did not match what ENTITY_PROFILE asks the model to
    return, so entity_type came back missing → 0 re-types).  The rework must pass
    the FULL profile schema, the full prompt, and the injection-safe context, and
    parse entity_type from the returned dict.  We stub the DeepSeek adapter so no
    network call happens.
    """
    import asyncio as _asyncio

    captured: dict[str, object] = {}

    class _FakeOutput:
        def __init__(self, result: dict[str, object]) -> None:
            self.result = result

    class _FakeAdapter:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        async def extract(self, inp: object):  # type: ignore[no-untyped-def]
            captured["output_schema"] = inp.output_schema  # type: ignore[attr-defined]
            captured["prompt"] = inp.prompt  # type: ignore[attr-defined]
            captured["context"] = inp.context  # type: ignore[attr-defined]
            return _FakeOutput({"entity_type": "organization"})

        async def aclose(self) -> None:
            return None

    # Provide an API key so the stage proceeds, and stub the adapter + the heavy
    # ml_clients / prompts imports the stage performs lazily.
    monkeypatch.setenv("DEEPINFRA_API_KEY", "test-key")

    import types as _types

    fake_adapters = _types.ModuleType("ml_clients.adapters.deepseek_extraction")
    fake_adapters.DeepSeekExtractionAdapter = _FakeAdapter  # type: ignore[attr-defined]

    @dataclass
    class _ExtractionInput:
        prompt: str
        context: str
        output_schema: dict[str, str]
        model_id: str

    fake_dc = _types.ModuleType("ml_clients.dataclasses")
    fake_dc.ExtractionInput = _ExtractionInput  # type: ignore[attr-defined]

    class _FakePrompt:
        def render(self, *, name: str, entity_class: str) -> str:
            return f"PROMPT for {name} ({entity_class})"

    fake_prompt_mod = _types.ModuleType("prompts.knowledge.entity_profile")
    fake_prompt_mod.ENTITY_PROFILE = _FakePrompt()  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "ml_clients.adapters.deepseek_extraction", fake_adapters)
    monkeypatch.setitem(sys.modules, "ml_clients.dataclasses", fake_dc)
    monkeypatch.setitem(sys.modules, "prompts.knowledge.entity_profile", fake_prompt_mod)

    cand = Candidate("a1", "SpaceX", "Rocket company")
    planned = _asyncio.run(mod._run_llm_stage([cand], batch_size=1))

    # The reworked stage produced a re-type from the parsed entity_type.
    assert len(planned) == 1 and planned[0].new_type == "organization"
    # It sent the FULL production output_schema (not the truncated single-field one).
    assert captured["output_schema"] == {
        "canonical_name": "string",
        "entity_type": "string",
        "ticker": "string|null",
        "isin": "string|null",
        "aliases": "list[string]",
    }
    # Injection-safe context wrapping mirrors the production path.
    assert captured["context"] == "<article_context>Rocket company</article_context>"


# ── DB plumbing against a fake connection ─────────────────────────────────────


@dataclass
class _FakeResult:
    rowcount: int

    def fetchall(self) -> list[tuple[str, str, str | None]]:
        return self._rows  # type: ignore[attr-defined]


class _FakeConn:
    """Minimal psycopg-connection stand-in supporting the context-manager protocol."""

    def __init__(self, rows: list[tuple[str, str, str | None]]) -> None:
        self._rows = rows
        self.updates: list[dict[str, str]] = []
        self.commits = 0

    def execute(self, sql: str, params: dict[str, object] | None = None):  # type: ignore[no-untyped-def]
        if sql.strip().upper().startswith("SELECT"):
            res = _FakeResult(rowcount=len(self._rows))
            res._rows = self._rows  # type: ignore[attr-defined]
            return res
        assert params is not None
        self.updates.append(params)  # type: ignore[arg-type]
        return _FakeResult(rowcount=1)

    def commit(self) -> None:
        self.commits += 1

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


# (entity_id, canonical_name, description)
_CANDS: list[tuple[str, str, str | None]] = [
    ("p1", "Apple shares", None),  # deterministic -> unknown
    ("p2", "$135", None),  # deterministic -> unknown
    ("p3", "Schwab U.S. Dividend Equity ETF", None),  # deterministic -> index
    ("a1", "SpaceX", "Rocket company"),  # ambiguous -> LLM
    ("a2", "Anthropic", "AI lab"),  # ambiguous -> LLM
]


def test_main_dry_run_no_writes_no_llm(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _FakeConn(_CANDS)
    monkeypatch.setattr(mod.psycopg, "connect", lambda _dsn: fake)
    # Make the LLM stage explode if it's ever called during a dry run.
    monkeypatch.setattr(
        mod,
        "_run_llm_stage",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not run in dry-run")),
    )

    rc = mod.main([])
    assert rc == 0
    assert fake.updates == [], "dry run must not write"
    assert fake.commits == 0

    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "deterministic re-types planned: 3" in out
    assert "rows that WOULD hit the LLM: 2" in out
    assert "estimated LLM calls (full): 2" in out


def test_main_deterministic_only_apply(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _FakeConn(_CANDS)
    monkeypatch.setattr(mod.psycopg, "connect", lambda _dsn: fake)

    rc = mod.main(["--deterministic-only", "--apply"])
    assert rc == 0
    # 3 deterministic re-types applied; no LLM stage.
    assert len(fake.updates) == 3
    assert fake.commits == 1
    new_types = {u["eid"]: u["new"] for u in fake.updates}
    assert new_types == {"p1": "unknown", "p2": "unknown", "p3": "index"}

    out = capsys.readouterr().out
    assert "APPLIED deterministic — 3 row(s)" in out
    assert "LLM stage SKIPPED" in out


def test_main_apply_runs_llm_and_applies(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _FakeConn(_CANDS)
    monkeypatch.setattr(mod.psycopg, "connect", lambda _dsn: fake)

    # Stub the LLM stage as an async coroutine that classifies both ambiguous
    # rows as unknown, and make asyncio.run drive it synchronously so no real
    # event loop / network is involved.
    captured: dict[str, object] = {}

    async def _capture_stage(cands: list[Candidate], batch_size: int) -> list[Retype]:
        captured["cands"] = cands
        captured["batch_size"] = batch_size
        return [Retype(c.entity_id, c.canonical_name, "financial_instrument", "unknown", "llm") for c in cands]

    monkeypatch.setattr(mod, "_run_llm_stage", _capture_stage)
    monkeypatch.setattr(mod.asyncio, "run", _drive)

    rc = mod.main(["--apply", "--batch-size", "3"])
    assert rc == 0
    # 3 deterministic + 2 LLM = 5 updates, committed in 2 batches.
    assert len(fake.updates) == 5
    assert fake.commits == 2
    assert captured["batch_size"] == 3
    assert {c.entity_id for c in captured["cands"]} == {"a1", "a2"}  # type: ignore[union-attr]

    out = capsys.readouterr().out
    assert "APPLIED deterministic — 3 row(s)" in out
    assert "APPLIED LLM — 2 row(s)" in out
    assert "TOTAL re-typed: 5" in out


def _drive(coro: object):  # type: ignore[no-untyped-def]
    """Synchronously drive a coroutine to completion for the test (no event loop)."""
    try:
        coro.send(None)  # type: ignore[attr-defined]
    except StopIteration as stop:
        return stop.value
    raise AssertionError("coroutine did not complete synchronously")


def test_main_limit_caps_candidates(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """--limit is passed through to the SELECT (verified via fetch params)."""
    seen: dict[str, object] = {}

    class _LimitConn(_FakeConn):
        def execute(self, sql: str, params: dict[str, object] | None = None):  # type: ignore[no-untyped-def]
            if sql.strip().upper().startswith("SELECT") and params:
                seen["limit"] = params.get("limit")
            return super().execute(sql, params)

    fake = _LimitConn(_CANDS[:2])
    monkeypatch.setattr(mod.psycopg, "connect", lambda _dsn: fake)

    rc = mod.main(["--limit", "2"])
    assert rc == 0
    assert seen["limit"] == 2
