"""Static SQL extractor for repository files (PLAN-0093 F-1).

Walks ``services/*/src/*/infrastructure/*/repositories/*.py`` and pulls every
string literal that looks like a SQL statement (``SELECT``, ``INSERT``,
``UPDATE``, ``DELETE``, ``WITH``). The extractor is intentionally conservative:
it only handles **literal** strings reachable via ``ast`` — concatenations,
``str.format`` calls, and f-strings with non-literal substitutions are skipped
(but their presence is recorded so that a follow-up audit can decide whether to
refactor them to use ``:param`` placeholders).

Two patterns are recognised:

1. ``text("…SQL…")`` — SQLAlchemy named-param syntax with ``:param``.
2. Raw asyncpg ``conn.fetch("…SQL…", $1, …)`` — positional ``$1`` syntax.

Both are valid input to Postgres ``PREPARE``, which is the validation engine
used by ``test_repository_sql_prepare.py``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Public dataclass returned by ``extract_sql_from_repositories``.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractedSQL:
    """One SQL literal discovered in a repository file."""

    file_path: Path
    line_number: int
    sql_text: str
    # ``kind`` tells the PREPARE harness which placeholder convention to expect.
    #   - "named"      → ``:param`` (SQLAlchemy)
    #   - "positional" → ``$1`` (asyncpg)
    kind: str


@dataclass(frozen=True)
class SkippedSQL:
    """A non-literal SQL location worth noting (logged, never asserted on)."""

    file_path: Path
    line_number: int
    reason: str


# ---------------------------------------------------------------------------
# Heuristics — what counts as a SQL literal.
# ---------------------------------------------------------------------------

# Match leading whitespace, optional comments, then a SQL verb.
_SQL_VERBS = re.compile(
    r"""^\s*               # leading whitespace
        (?:--[^\n]*\n\s*)* # optional SQL line comments
        (?P<verb>
            SELECT | INSERT | UPDATE | DELETE | WITH | VALUES
        )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _looks_like_sql(s: str) -> bool:
    """Return True if the string starts with a SQL DML/CTE keyword.

    Pure literals like ``"WITH … AS"`` are accepted; anything that does not
    begin with one of the recognised verbs is filtered out so that we don't
    PREPARE comments, log messages, or natural-language strings.
    """
    return bool(_SQL_VERBS.match(s))


# ---------------------------------------------------------------------------
# AST helpers.
# ---------------------------------------------------------------------------


def _str_from_constant(node: ast.AST) -> str | None:
    """Return the literal string from a ``Constant`` node, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # ``ast.JoinedStr`` covers f-strings. If every formatted value is also a
    # constant, we can still concatenate them (rare but useful).
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            inner = _str_from_constant(value)
            if inner is None:
                return None
            parts.append(inner)
        return "".join(parts)
    return None


def _detect_kind(sql: str) -> str:
    """Return "named" if any ``:param`` placeholder appears, else "positional".

    This is best-effort and is only used to inform downstream PREPARE — the
    PREPARE statement itself does not bind values, so either kind will validate
    column existence.
    """
    # Strip string literals like ':status' which are NOT placeholders.
    # Crude but enough for the SQL we own — proper parsing is overkill here.
    sql_no_strings = re.sub(r"'[^']*'", "''", sql)
    if re.search(r"(?<!:):[A-Za-z_][A-Za-z0-9_]*", sql_no_strings):
        return "named"
    if re.search(r"\$\d+", sql_no_strings):
        return "positional"
    return "named"  # default — most worldview repos use SQLAlchemy text()


# ---------------------------------------------------------------------------
# Fragment folding (FIX-LIVE-F / INV-LIVE-B Part 3).
# ---------------------------------------------------------------------------
#
# Why this exists
# ---------------
# Several repositories compose SQL by gluing module-level string constants:
#
#     _SEARCH_CTE   = "WITH ... AS (...)"
#     _COUNT_SELECT = "SELECT count(*) FROM filtered"
#     QUERY         = _SEARCH_CTE + " " + _COUNT_SELECT
#
# The simple ``ast.walk`` extractor below would emit ``_COUNT_SELECT`` as a
# standalone statement and try to PREPARE it — which fails because the CTE
# it references (``filtered``) only exists in the composed ``QUERY``. That
# produced 60+ false-positive PREPARE failures in the Phase 5c live pass.
#
# Fix: walk module-level ``Assign`` / ``AnnAssign`` whose RHS is a
# ``BinOp(Add)`` chain, resolve every leaf via the module's name table, and
# if the whole chain folds into a single SQL string, emit that composed
# statement. Record the names consumed so the second pass can skip them.


def _collect_module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Return ``{NAME: literal_string}`` for module-level ``NAME = "..."``.

    Handles three shapes:
      * ``NAME = "literal"``                             (Assign + Constant)
      * ``NAME: str = "literal"``                        (AnnAssign + Constant)
      * ``NAME = f"…"`` where every formatted value is itself a constant
        (handled via ``_str_from_constant`` for symmetry with the main
        walker).

    Anything more dynamic (function call, attribute, BinOp, …) is left out
    deliberately — fragment folding is a *recursive* operation and the
    recursion bottoms out only on simple constants.
    """
    names: dict[str, str] = {}
    for stmt in tree.body:
        # Plain ``X = "..."`` may bind to a single Name or multiple targets;
        # we only care about single-target assignments at module scope.
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                value = _str_from_constant(stmt.value)
                if value is not None:
                    names[target.id] = value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            value = _str_from_constant(stmt.value)
            if value is not None:
                names[stmt.target.id] = value
    return names


def _fold_addition(node: ast.AST, names: dict[str, str]) -> str | None:
    """Resolve a ``Constant | Name | BinOp(Add)`` tree into a single string.

    Returns ``None`` if any leaf cannot be resolved (e.g. an unknown name,
    a function call, or a non-string constant). The caller treats ``None``
    as "skip — too dynamic for static folding" and the affected SQL goes
    into the ``skipped`` bucket exactly as before.

    The recursion intentionally accepts only ``ast.Add``. Other ops on
    strings (``%``, ``*``) are out of scope.
    """
    # Leaf 1: a literal string (or fold-friendly f-string).
    literal = _str_from_constant(node)
    if literal is not None:
        return literal
    # Leaf 2: a Name reference into the precomputed module table.
    if isinstance(node, ast.Name):
        return names.get(node.id)
    # Branch: Add chain — recurse both sides.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _fold_addition(node.left, names)
        if left is None:
            return None
        right = _fold_addition(node.right, names)
        if right is None:
            return None
        return left + right
    return None


def _collect_consumed_name_constants(
    node: ast.AST,
    names: dict[str, str],
    name_to_constant_id: dict[str, int] | None = None,
) -> set[int]:
    """Return ids of ``ast.Constant`` nodes consumed by an emitted fold.

    The constant-walker pass (see ``extract_sql_from_file``) would otherwise
    re-emit every literal inside the fold as a standalone statement. By
    tracking the ``id(...)`` of the consumed Constant nodes we can suppress
    those duplicates without false-skipping legitimate other statements in
    the same module.

    We collect:
      * Literal Constant / JoinedStr nodes directly reachable from the
        BinOp tree (e.g. the ``" "`` glue strings between two Names).
      * Module-level Constant nodes pointed to by every Name reference in
        the tree, when ``name_to_constant_id`` is supplied. This is what
        prevents ``_SEARCH_CTE = "WITH ..."`` from being re-emitted once
        its composition has been emitted as a single statement.
    """
    consumed: set[int] = set()
    name_to_constant_id = name_to_constant_id or {}

    def _visit(n: ast.AST) -> None:
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            consumed.add(id(n))
            return
        if isinstance(n, ast.JoinedStr):
            # Treat the JoinedStr (and its constant children) as consumed.
            consumed.add(id(n))
            for value in n.values:
                _visit(value)
            return
        if isinstance(n, ast.Name):
            # Mark the module-level constant the Name points to (if any).
            ref = name_to_constant_id.get(n.id)
            if ref is not None:
                consumed.add(ref)
            return
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            _visit(n.left)
            _visit(n.right)

    _visit(node)
    return consumed


# ---------------------------------------------------------------------------
# Main API.
# ---------------------------------------------------------------------------


def repository_files(repo_root: Path) -> list[Path]:
    """Return every ``services/*/src/*/infrastructure/*/repositories/*.py``.

    We exclude ``__init__.py`` because they rarely host SQL, and any path under
    ``__pycache__`` or ``.mypy_cache`` (defensive — those should not be
    walked anyway).
    """
    pattern = "services/*/src/*/infrastructure/*/repositories/*.py"
    out: list[Path] = []
    for path in repo_root.glob(pattern):
        if path.name == "__init__.py":
            continue
        if "__pycache__" in path.parts or ".mypy_cache" in path.parts:
            continue
        out.append(path)
    # Also include repositories nested one level deeper if any exist
    # (defensive — current layout is flat but future-proof).
    deeper = "services/*/src/*/infrastructure/*/*/repositories/*.py"
    for path in repo_root.glob(deeper):
        if path.name == "__init__.py":
            continue
        if "__pycache__" in path.parts or ".mypy_cache" in path.parts:
            continue
        out.append(path)
    return sorted(set(out))


def extract_sql_from_file(path: Path) -> tuple[list[ExtractedSQL], list[SkippedSQL]]:
    """Parse ``path`` with ast and return (extracted, skipped) SQL strings."""
    extracted: list[ExtractedSQL] = []
    skipped: list[SkippedSQL] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        # If a repository file fails to parse, surface it — but as a "skipped"
        # rather than a hard failure (the test loop will flag it separately).
        skipped.append(SkippedSQL(path, getattr(exc, "lineno", 0) or 0, f"SyntaxError: {exc.msg}"))
        return extracted, skipped

    # ── PRE-PASS: collect module-level NAME → "literal" bindings ────────────
    # FIX-LIVE-F: needed by the fragment-folding first pass below.
    module_names = _collect_module_string_constants(tree)
    # Reverse index: NAME → id(Constant node) defining it. Used to suppress
    # standalone re-emission of fragment literals once their composition has
    # been emitted.
    name_to_constant_id: dict[str, int] = {}
    for stmt in tree.body:
        rhs: ast.AST | None = None
        target_name: str | None = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            target_name = stmt.targets[0].id
            rhs = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            target_name = stmt.target.id
            rhs = stmt.value
        if target_name is None or rhs is None:
            continue
        # Only register pure-Constant RHS (the fragment literals themselves).
        if isinstance(rhs, ast.Constant) and isinstance(rhs.value, str):
            name_to_constant_id[target_name] = id(rhs)
        elif isinstance(rhs, ast.JoinedStr) and _str_from_constant(rhs) is not None:
            name_to_constant_id[target_name] = id(rhs)

    # ── FIRST PASS: fold module-level ``NAME = lhs + rhs + …`` chains ──────
    # When the chain resolves to a SQL statement, emit the composed query as
    # a single ExtractedSQL and record the consumed Constant node ids so the
    # second pass can suppress duplicate emissions.
    consumed_constant_ids: set[int] = set()
    for stmt in tree.body:
        # Target a single Name = BinOp(Add) or Name: Ann = BinOp(Add).
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            rhs = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            rhs = stmt.value
        else:
            continue
        if not (isinstance(rhs, ast.BinOp) and isinstance(rhs.op, ast.Add)):
            continue
        folded = _fold_addition(rhs, module_names)
        if folded is None or not _looks_like_sql(folded):
            continue
        extracted.append(
            ExtractedSQL(
                file_path=path,
                line_number=stmt.lineno,
                sql_text=folded,
                kind=_detect_kind(folded),
            )
        )
        consumed_constant_ids |= _collect_consumed_name_constants(rhs, module_names, name_to_constant_id)

    # ── SECOND PASS: existing walker (skips consumed constants) ────────────
    # We walk every node. For ``text("…")`` calls we look at Call → args[0].
    # For raw asyncpg ``conn.fetch("…", …)`` we also look at Call → args[0].
    # Standalone string literals (e.g. ``SQL_FOO = "SELECT …"``) are caught by
    # walking every Constant/JoinedStr — but we filter with ``_looks_like_sql``
    # so log strings don't pollute the result.
    for node in ast.walk(tree):
        # FIX-LIVE-F: if this Constant/JoinedStr was already consumed by an
        # emitted fold, skip — don't double-emit.
        if id(node) in consumed_constant_ids:
            continue
        # 1) Standalone string constants assigned to a name or used inline.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if _looks_like_sql(value):
                extracted.append(
                    ExtractedSQL(
                        file_path=path,
                        line_number=node.lineno,
                        sql_text=value,
                        kind=_detect_kind(value),
                    )
                )
            continue

        # 2) f-strings whose pieces are all literal — concatenate them.
        if isinstance(node, ast.JoinedStr):
            joined = _str_from_constant(node)
            if joined is None:
                # f-string with dynamic interpolation — record as skipped so
                # the author knows it isn't PREPARE-validated.
                skipped.append(
                    SkippedSQL(path, node.lineno, "dynamic f-string SQL (skipped from PREPARE pass)"),
                )
                continue
            if _looks_like_sql(joined):
                extracted.append(
                    ExtractedSQL(
                        file_path=path,
                        line_number=node.lineno,
                        sql_text=joined,
                        kind=_detect_kind(joined),
                    )
                )
            continue

        # 3) String concatenation with ``+`` (e.g. "SELECT ..." + " FROM ...").
        # We do not attempt to fold these — they are nearly always dynamic.
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = _str_from_constant(node.left)
            right = _str_from_constant(node.right)
            if left is not None and right is not None:
                merged = left + right
                if _looks_like_sql(merged):
                    extracted.append(
                        ExtractedSQL(
                            file_path=path,
                            line_number=node.lineno,
                            sql_text=merged,
                            kind=_detect_kind(merged),
                        )
                    )
            else:
                # Only flag if at least one side looks SQL-y; otherwise this
                # is just regular string maths.
                for side in (left, right):
                    if side is not None and _looks_like_sql(side):
                        skipped.append(
                            SkippedSQL(
                                path,
                                node.lineno,
                                "string-concatenated SQL (skipped from PREPARE pass)",
                            )
                        )
                        break

    # Dedupe (file, line, sql) — multiple walkers can hit the same constant.
    seen: set[tuple[Path, int, str]] = set()
    unique: list[ExtractedSQL] = []
    for item in extracted:
        key = (item.file_path, item.line_number, item.sql_text)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique, skipped


def extract_sql_from_repositories(repo_root: Path) -> tuple[list[ExtractedSQL], list[SkippedSQL]]:
    """Walk every repository file under ``repo_root`` and aggregate results."""
    all_extracted: list[ExtractedSQL] = []
    all_skipped: list[SkippedSQL] = []
    for path in repository_files(repo_root):
        extracted, skipped = extract_sql_from_file(path)
        all_extracted.extend(extracted)
        all_skipped.extend(skipped)
    return all_extracted, all_skipped
