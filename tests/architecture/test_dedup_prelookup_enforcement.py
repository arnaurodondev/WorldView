"""
Architecture test: resolve-or-create call sites on identity/dedup-prone tables
must reference an identity-only pre-lookup helper in the same file.

Rule: DEDUP-PRELOOKUP-001

Rationale
---------
This platform has hit the SAME bug shape twice in two different services:

  * BP-459 (2026-06-12, knowledge-graph): two independent minting pipelines
    (the market-data instrument-seed path and the news/provisional-enrichment
    path) each created a `canonical_entities` row for the same ticker without
    consulting the other — an EXACT-match unique index
    (`WHERE entity_type != 'financial_instrument'`) never fired because
    neither path's insert matched its predicate the same way, and no code
    path did a broader *ticker-only* pre-lookup before minting.
  * BP-743 (2026-07-15, market-data): a `(symbol, exchange)` exact-match
    unique constraint let a placeholder `exchange=''` row and a later
    real-exchange row coexist for the same symbol (NFLX) — because
    `FundamentalsRefreshWorker` could enqueue a bare symbol with no exchange
    known, and the resolve-or-create step only tried an EXACT composite-key
    match before creating.

Both fixes took the identical shape: a *narrower-key* pre-lookup helper
(`find_symbol_match_ignoring_exchange`, `find_by_ticker`) consulted BEFORE
the create/insert call, so a placeholder-vs-real or independent-pipeline
duplicate is caught and reused instead of re-minted. Nothing currently stops
a THIRD service from reintroducing this shape (a new resolve-or-create path
on instruments/canonical_entities, or an equivalent identity-prone table,
that only checks an exact composite key before inserting).

Design choice: AST-based heuristic vs. simpler grep-based enumeration
----------------------------------------------------------------------
The task spec offered two implementation options. This test uses the
**simpler, enumerated, per-target AST scan** (closer to option (b): "does
this file call the established shared dedup helper before create"), NOT a
fully general "any repository .create() without a preceding broader lookup"
heuristic (option (a)). Reasoning:

1. A fully general heuristic (flag ANY `.create()`/insert call on ANY
   repository-shaped object unless a "broader lookup" precedes it) requires
   inferring, from AST alone, (a) which repositories are genuinely
   identity/dedup-prone (most are not — `failed_tasks.create()`,
   `outbox_events.create()`, `idempotency.create_if_not_exists()` are all
   safe-by-construction and would be false positives), and (b) whether a
   given lookup call actually widens the key (vs. just being AN exact-match
   lookup that has the exact same gap). Both of these require semantic
   knowledge no AST pass can recover reliably, and per the task brief false
   positives here are NOT acceptable — a noisy check gets suppressed, which
   is worse than no check.
2. The two known-vulnerable tables (`instruments`, `canonical_entities`) and
   their two known-safe helpers (`find_symbol_match_ignoring_exchange`,
   `find_by_ticker`) are explicit, small, and unlikely to grow quickly — a
   table-driven enumeration is trustworthy today and cheap to extend when a
   THIRD table/helper pair is added (BP-count permitting).
3. This still generalizes usefully: it does not hardcode "market-data" or
   "knowledge-graph" as the scanned services — it AST-scans EVERY service's
   `infrastructure/` tree for the two (object-attribute-name, method-name)
   shapes, so a NEW service introducing e.g. `uow.instruments.upsert(...)`
   without also referencing `find_symbol_match_ignoring_exchange` anywhere
   in that file is caught automatically, even though it was never
   specifically told about that service.

False negatives are accepted (a table not yet in `DEDUP_PRONE_TARGETS`, or a
guard call spelled under a wrapper name, will not be caught) — per the task
brief, that tradeoff is explicitly preferred over false positives.

Allowlist
---------
A call site that intentionally does not need the pre-lookup (e.g. it upserts
by a stable ID rather than by a human-readable identity key, so it is not the
BP-459/BP-743 "independent resolve-or-create pipelines" shape at all) may be
exempted via ``tests/architecture/_dedup_prelookup_allowlist.yaml``, keyed by
(file_path, target_label) so an exemption for one target never silently
covers a different target in the same file.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from tests.architecture._utils import (
    REPO_ROOT,
    ArchViolation,
    assert_no_violations,
    discover_services,
    iter_py_files,
)

_ALLOWLIST_PATH = Path(__file__).resolve().parent / "_dedup_prelookup_allowlist.yaml"


@dataclass(frozen=True)
class DedupProneTarget:
    """One (table, creation-call shape, required guard) triple to scan for."""

    label: str  # human-readable identity for reports + allowlist matching
    table: str  # the underlying DB table this call site writes to
    object_attr_names: frozenset[str]  # e.g. {"instruments"} in `uow.instruments.upsert(...)`
    method_names: frozenset[str]  # e.g. {"upsert", "create"}
    required_helper_names: frozenset[str]  # any ONE of these must be referenced in the same file


# The two known-vulnerable (table, creation-shape) pairs — see module docstring
# for why this is enumerated rather than fully general. Extend this list the
# next time this bug shape fires in a third table.
DEDUP_PRONE_TARGETS: list[DedupProneTarget] = [
    DedupProneTarget(
        label="instruments (symbol/exchange resolve-or-create)",
        table="instruments",
        object_attr_names=frozenset({"instruments"}),
        method_names=frozenset({"upsert", "create", "create_if_not_exists"}),
        required_helper_names=frozenset({"find_symbol_match_ignoring_exchange"}),
    ),
    DedupProneTarget(
        label="canonical_entities (ticker/name resolve-or-create)",
        table="canonical_entities",
        object_attr_names=frozenset({"entity_repo", "canonical_entities", "canon_repo"}),
        method_names=frozenset({"create", "create_or_get"}),
        required_helper_names=frozenset({"find_by_ticker"}),
    ),
]


# ---------------------------------------------------------------------------
# Allowlist loading
# ---------------------------------------------------------------------------


def _load_allowlist() -> set[tuple[str, str]]:
    """Return the set of (file_path, target_label) pairs exempted from the rule.

    Missing or malformed entries are treated as violations (fail loudly) —
    same policy as `_consumer_dedup_allowlist.yaml`.
    """
    if not _ALLOWLIST_PATH.exists():
        return set()
    data = yaml.safe_load(_ALLOWLIST_PATH.read_text(encoding="utf-8")) or {}
    entries = data.get("allowlist") or []
    allowed: set[tuple[str, str]] = set()
    required_fields = {"file_path", "target_label", "justification", "granted_at"}
    for entry in entries:
        missing = required_fields - set(entry)
        if missing:
            raise ValueError(f"Allowlist entry is missing required fields {missing}: {entry!r}")
        allowed.add((entry["file_path"], entry["target_label"]))
    return allowed


# ---------------------------------------------------------------------------
# AST scanning
# ---------------------------------------------------------------------------


def _attr_root_name(node: ast.expr) -> str | None:
    """Return the trailing identifier of a Name or Attribute expression.

    For ``uow.instruments`` (Attribute(value=Name('uow'), attr='instruments'))
    this returns ``'instruments'``; for a bare ``entity_repo`` (Name) it
    returns ``'entity_repo'``. Used to match the object an identity-prone
    method is called on, independent of what it's accessed through (``uow.``,
    ``self.``, a bare local variable, etc.) — AST-level, not runtime MRO.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _collect_referenced_identifiers(tree: ast.AST) -> set[str]:
    """Collect every bare-name and attribute identifier referenced in a module.

    A helper like ``find_by_ticker`` may be referenced either as a bare
    ``Name`` (imported directly: ``from ... import find_by_ticker``) or as an
    ``Attribute`` (``CanonicalEntityRepository(session).find_by_ticker(...)``).
    We check both forms so the "guard is present somewhere in this file" test
    doesn't false-positive-violate on the attribute-access spelling.
    """
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
    return identifiers


@dataclass
class _CreateCallSite:
    file: Path
    line: int
    target: DedupProneTarget


def _find_create_call_sites(py_file: Path, tree: ast.AST) -> list[_CreateCallSite]:
    """Find every Call node matching one of DEDUP_PRONE_TARGETS' shapes."""
    sites: list[_CreateCallSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method_name = node.func.attr
        object_root = _attr_root_name(node.func.value)
        if object_root is None:
            continue
        for target in DEDUP_PRONE_TARGETS:
            if method_name in target.method_names and object_root in target.object_attr_names:
                sites.append(_CreateCallSite(file=py_file, line=node.lineno, target=target))
    return sites


# ---------------------------------------------------------------------------
# Architecture test
# ---------------------------------------------------------------------------


class TestDedupPrelookupEnforcement:
    """Every resolve-or-create call on a dedup-prone table must reference its
    identity-only pre-lookup helper somewhere in the same file.

    Discovery strategy: AST-scan every ``.py`` file under
    ``services/<svc>/src/<pkg>/infrastructure/`` (the canonical location for
    consumers and workers, per §1.4 — the same scope
    `test_consumer_dedup_mixin_enforcement.py` uses) for Call nodes shaped
    like ``<obj>.<create_method>(...)`` where ``<obj>``'s trailing identifier
    and ``<create_method>`` match a `DedupProneTarget`.

    Compliance check: the required guard helper name for that target must
    appear ANYWHERE in the same file (as a bare Name or an attribute access),
    OR the (file, target) pair must be on the allowlist in
    ``_dedup_prelookup_allowlist.yaml``.
    """

    def test_all_dedup_prone_creates_reference_prelookup_helper(self) -> None:
        """See module docstring for the BP-459 / BP-743 bug shape this guards.

        Allowlist path: tests/architecture/_dedup_prelookup_allowlist.yaml
        Rule: DEDUP-PRELOOKUP-001
        """
        allowed = _load_allowlist()
        violations: list[ArchViolation] = []

        for svc in discover_services(include_scaffolded=True):
            infra_dir = svc.pkg_dir / "infrastructure"
            if not infra_dir.is_dir():
                continue

            for py_file in iter_py_files(infra_dir):
                try:
                    source = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source, filename=str(py_file))
                except (SyntaxError, OSError):
                    continue

                sites = _find_create_call_sites(py_file, tree)
                if not sites:
                    continue

                identifiers = _collect_referenced_identifiers(tree)
                rel_path = py_file.relative_to(REPO_ROOT).as_posix()

                # De-dupe by target: multiple call sites for the same target in
                # one file share one guard requirement, so report once per target.
                seen_targets: set[str] = set()
                for site in sites:
                    if site.target.label in seen_targets:
                        continue
                    seen_targets.add(site.target.label)

                    has_guard = any(h in identifiers for h in site.target.required_helper_names)
                    if has_guard:
                        continue
                    if (rel_path, site.target.label) in allowed:
                        continue

                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=f"{rel_path}:{site.line}",
                            line=site.line,
                            rule="DEDUP-PRELOOKUP-001",
                            detail=(
                                f"Calls `.{'/'.join(sorted(site.target.method_names))}(...)` on "
                                f"`{'/'.join(sorted(site.target.object_attr_names))}` (table "
                                f"`{site.target.table}`) but does not reference any of "
                                f"{sorted(site.target.required_helper_names)} anywhere in this "
                                "file. An exact-composite-key create/upsert on an identity-prone "
                                "table is a silent-duplicate factory for placeholder-vs-real or "
                                "independent-minting-pipeline races (BP-459, BP-743) — add the "
                                "identity-only pre-lookup, or add an allowlist entry with "
                                "justification in tests/architecture/_dedup_prelookup_allowlist.yaml."
                            ),
                        )
                    )

        assert_no_violations(violations, rule="DEDUP-PRELOOKUP-001")
