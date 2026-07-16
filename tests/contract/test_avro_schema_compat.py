"""Forward + backward Avro compatibility gate for every ``infra/kafka/schemas/*.avsc``.

WHY THIS EXISTS (the incident it prevents)
-------------------------------------------
``content.article.stored.v1.avsc`` gained a trailing ``external_id`` field. The
NEW consumer (17-field reader) could not decode OLD 16-field bytes still sitting
on the topic during a rolling deploy: fastavro's *single-schema* positional
``schemaless_reader(buf, NEW)`` reads 17 fields, runs off the end of the 16-field
buffer, and raises ``EOFError`` → ~82 % of docs dead-lettered silently for hours.

The ``.avsc`` doc-strings WRONGLY claimed "trailing additive fields are always
safe". That is only true for the **old-reader / new-data** direction (an old
positional reader stops after its own field count and ignores trailing bytes).
It is NOT true for the **new-reader / old-data** direction, which is exactly the
one a rolling deploy hits first.

WHAT THIS GATE CHECKS (per schema changed vs the git base ref)
--------------------------------------------------------------
1. RESOLUTION, both directions — using fastavro schema *resolution* (writer and
   reader schema both supplied, matching by field name, the correct way to read
   across a schema change):
     - OLD writer → NEW reader  (the direction that broke prod)
     - NEW writer → OLD reader
   This deterministically fails a trailing append that has **no default**
   (Avro resolution cannot fill the reader's extra field) and fails removed /
   type-changed required fields.

2. STATIC POSITIONAL LINT — because the deployed consumers decode *positionally*
   (single schema, no registry), name-based resolution is not enough. Every
   field added in NEW must be:
     - TRAILING  (appended after every field that already existed in OLD — a
       mid-record insert shifts every following field's byte position and
       corrupts positional decode even though Avro *resolution* would accept it),
       AND
     - carry a ``default``  (so an old-writer/new-reader resolution can fill it,
       and R11 forward-compat holds).
   It also fails removed / reordered / retyped fields for the same positional
   reason.

Together (1)+(2) enforce the ONLY safe evolution for a positional, registry-less
wire: append-only, defaulted, non-breaking. The remaining residual risk (a NEW
reader positional-decoding OLD bytes still fails on *any* addition) is a
deploy-ordering / consumer-code concern documented in the audit — the structural
lesson here is "additive-trailing is not unconditionally safe", which this gate
now encodes.

DETERMINISTIC + OFFLINE: uses only ``git show`` (local object store) and
``fastavro``. No broker, no network. Records are synthesised from the schema
itself (unions prefer ``null``; scalars get type defaults; records recurse).

BASE REF: OLD = ``$SCHEMA_BASE_REF`` (default ``HEAD~1``); NEW = the file on disk.
CI sets ``SCHEMA_BASE_REF=origin/main`` so a PR is diffed against the merge base;
locally ``HEAD~1`` catches a just-committed change and a dirty working tree.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import fastavro
import pytest

pytestmark = pytest.mark.contract

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_DIR = _REPO_ROOT / "infra" / "kafka" / "schemas"

# Base git ref that holds the PREVIOUS (writer) version of each schema.
_BASE_REF = os.environ.get("SCHEMA_BASE_REF", "HEAD~1")


def _schema_paths() -> list[Path]:
    return sorted(_SCHEMA_DIR.glob("*.avsc"))


def _git_show(ref: str, rel_path: str) -> str | None:
    """Return the file content at ``ref`` or ``None`` if it does not exist there.

    Offline: reads the local git object store only. A missing file (new schema)
    or a missing ref (shallow clone without ``HEAD~1``) yields ``None`` → skip.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "show", f"{ref}:{rel_path}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:  # pragma: no cover - git absent
        return None
    if out.returncode != 0:
        return None
    return out.stdout


# ── Minimal record synthesis ────────────────────────────────────────────────
# Build a value that is valid under a RAW (unparsed) Avro type node. We prefer
# ``null`` for nullable unions and cheap type defaults otherwise; the only
# requirement is that the record encodes cleanly under its writer schema.


def _synth_value(type_node: Any, named: dict[str, Any]) -> Any:
    """Synthesise a minimal encodable value for a raw Avro type node."""
    # Union: list of branches. Prefer null, else synthesise the first branch.
    if isinstance(type_node, list):
        if "null" in type_node:
            return None
        return _synth_value(type_node[0], named)

    # Named-type reference (a bare string that isn't a primitive).
    if isinstance(type_node, str):
        primitives = {
            "null": None,
            "boolean": False,
            "int": 0,
            "long": 0,
            "float": 0.0,
            "double": 0.0,
            "bytes": b"",
            "string": "x",
        }
        if type_node in primitives:
            return primitives[type_node]
        if type_node in named:
            return _synth_value(named[type_node], named)
        raise AssertionError(f"Unknown named type reference: {type_node!r}")

    # Complex type: a dict with a "type" key.
    if isinstance(type_node, dict):
        t = type_node["type"]
        if t == "record":
            named[type_node["name"]] = type_node
            return {f["name"]: _synth_field(f, named) for f in type_node["fields"]}
        if t == "enum":
            named[type_node["name"]] = type_node
            return type_node["symbols"][0]
        if t == "array":
            return []
        if t == "map":
            return {}
        if t == "fixed":
            named[type_node["name"]] = type_node
            return b"\x00" * int(type_node["size"])
        # Logical / annotated primitive (e.g. {"type": "string", "logicalType": ...}).
        return _synth_value(t, named)

    raise AssertionError(f"Unhandled Avro type node: {type_node!r}")


def _synth_field(field: dict[str, Any], named: dict[str, Any]) -> Any:
    """Synthesise a value for a record field, honouring an explicit default."""
    if "default" in field:
        # A concrete default is always valid under the writer schema.
        return field["default"]
    return _synth_value(field["type"], named)


def _synth_record(record_schema: dict[str, Any]) -> dict[str, Any]:
    named: dict[str, Any] = {record_schema["name"]: record_schema}
    return {f["name"]: _synth_field(f, named) for f in record_schema["fields"]}


# ── Compatibility primitives ────────────────────────────────────────────────


def _resolve_roundtrip(writer_raw: dict[str, Any], reader_raw: dict[str, Any]) -> None:
    """Write a minimal record under ``writer`` and read it back under ``reader``.

    Uses fastavro schema RESOLUTION (both schemas supplied) — this is how a
    correct consumer reads bytes produced by a different schema version. Raises
    if the pair is not resolution-compatible.
    """
    record = _synth_record(writer_raw)
    writer_parsed = fastavro.parse_schema(json.loads(json.dumps(writer_raw)))
    reader_parsed = fastavro.parse_schema(json.loads(json.dumps(reader_raw)))
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, writer_parsed, record)
    buf.seek(0)
    # writer != reader → fastavro performs schema resolution (match by name).
    fastavro.schemaless_reader(buf, writer_parsed, reader_parsed)


def _records_by_name(schema: Any) -> dict[str, dict[str, Any]]:
    """Index a schema file's record(s) by name (handles single record or a union list)."""
    if isinstance(schema, list):
        return {r["name"]: r for r in schema}
    return {schema["name"]: schema}


def _field_names(record_raw: dict[str, Any]) -> list[str]:
    return [f["name"] for f in record_raw["fields"]]


def _fields_by_name(record_raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["name"]: f for f in record_raw["fields"]}


def _static_positional_lint(old_raw: dict[str, Any], new_raw: dict[str, Any]) -> list[str]:
    """Return a list of positional-decode violations between OLD and NEW records.

    Empty list == safe. Enforces append-only, defaulted, non-breaking evolution.
    """
    problems: list[str] = []
    old_names = _field_names(old_raw)
    new_names = _field_names(new_raw)
    old_by = _fields_by_name(old_raw)
    new_by = _fields_by_name(new_raw)

    # 1. OLD fields must remain a same-order PREFIX of NEW (no removal, no
    #    reorder, no mid-record insert — all of which shift byte positions).
    prefix = new_names[: len(old_names)]
    if prefix != old_names:
        removed = [n for n in old_names if n not in new_names]
        if removed:
            problems.append(f"removed field(s) {removed} — breaks positional decode")
        reordered = [n for n in old_names if n in new_names] != [n for n in new_names if n in old_names]
        if reordered:
            problems.append("existing fields reordered or a new field inserted mid-record")
        else:
            # A new name landed before the end of the old block → mid-insert.
            problems.append(
                f"new field inserted before the end of the pre-existing block "
                f"(old order={old_names}, new prefix={prefix})"
            )

    # 2. Shared fields must keep the SAME type (a type change re-encodes bytes).
    for name in old_names:
        if name in new_by and old_by[name].get("type") != new_by[name].get("type"):
            problems.append(f"field {name!r} changed type {old_by[name].get('type')!r} → {new_by[name].get('type')!r}")

    # 3. Every ADDED field must be trailing (guaranteed by 1 if prefix matched)
    #    AND declare a default (forward-compat + resolvable by an old writer).
    added = [n for n in new_names if n not in old_names]
    for name in added:
        if "default" not in new_by[name]:
            problems.append(f"added field {name!r} has NO default — breaks old-writer/new-reader resolution")

    return problems


# ── The parametrised gate ───────────────────────────────────────────────────


@pytest.mark.parametrize("schema_path", _schema_paths(), ids=lambda p: p.name)
def test_avro_schema_forward_backward_compatible(schema_path: Path) -> None:
    rel = schema_path.relative_to(_REPO_ROOT).as_posix()

    old_text = _git_show(_BASE_REF, rel)
    if old_text is None:
        pytest.skip(f"{rel}: no base version at {_BASE_REF} (new file or shallow clone)")

    new_text = schema_path.read_text()
    if json.loads(old_text) == json.loads(new_text):
        pytest.skip(f"{rel}: unchanged vs {_BASE_REF}")

    old_schema = json.loads(old_text)
    new_schema = json.loads(new_text)

    # Multi-record union files (e.g. portfolio.events.v1) are a JSON array of
    # named records. Binary round-trip of a top-level union needs the tagged
    # form; we run the field-level positional lint per matching record instead,
    # which is where the real breakage lives.
    if isinstance(old_schema, list) or isinstance(new_schema, list):
        old_recs = _records_by_name(old_schema)
        new_recs = _records_by_name(new_schema)
        all_problems: list[str] = []
        for name, old_rec in old_recs.items():
            if name in new_recs:
                all_problems += [f"[{name}] {p}" for p in _static_positional_lint(old_rec, new_recs[name])]
        assert not all_problems, f"{rel}: positional-compat violations:\n  - " + "\n  - ".join(all_problems)
        return

    # Single-record schema: full resolution round-trip in BOTH directions …
    _resolve_roundtrip(writer_raw=old_schema, reader_raw=new_schema)  # OLD writer → NEW reader (broke prod)
    _resolve_roundtrip(writer_raw=new_schema, reader_raw=old_schema)  # NEW writer → OLD reader

    # … plus the positional lint that resolution alone cannot see.
    problems = _static_positional_lint(old_schema, new_schema)
    assert not problems, f"{rel}: positional-compat violations:\n  - " + "\n  - ".join(problems)
