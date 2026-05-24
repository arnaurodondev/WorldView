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

    # We walk every node. For ``text("…")`` calls we look at Call → args[0].
    # For raw asyncpg ``conn.fetch("…", …)`` we also look at Call → args[0].
    # Standalone string literals (e.g. ``SQL_FOO = "SELECT …"``) are caught by
    # walking every Constant/JoinedStr — but we filter with ``_looks_like_sql``
    # so log strings don't pollute the result.
    for node in ast.walk(tree):
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
