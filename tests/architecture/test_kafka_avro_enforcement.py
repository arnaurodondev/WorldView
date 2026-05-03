"""
Architecture test: Kafka consumers must use Avro for the wire format.

Per platform principle (PLAN-0062 follow-up to PLAN-0061): every Kafka topic's
contract MUST be defined as an Avro schema in ``infra/kafka/schemas/`` AND
deserialized via ``deserialize_confluent_avro`` (or ``deserialize_avro``) in
the consumer's ``deserialize_value`` method.  Pure ``json.loads`` consumers are
forbidden for new code — they bypass schema enforcement, hide forward-compat
violations, and split the platform contract surface across two encodings.

This test scans every ``deserialize_value`` implementation under
``services/*/src/**/consumers/*.py`` and classifies it as one of:

    AVRO_FIRST  — uses deserialize_confluent_avro/deserialize_avro and falls
                  back to json.loads for legacy payloads (the recommended
                  pattern during a migration window)
    AVRO_ONLY   — Avro with no JSON fallback (preferred for new consumers)
    JSON_ONLY   — pure json.loads (forbidden for new consumers)

JSON_ONLY consumers must appear in ``JSON_CONSUMER_BASELINE`` below.  Adding a
new JSON-only consumer (or removing the baseline entry of one that has been
migrated) requires updating this list — that is the migration friction the
test is designed to enforce.

The migration plan for the existing baseline lives in
``docs/plans/0062-kafka-avro-enforcement-migration-plan.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]

# Files that are exempt because their ``deserialize_value`` is pure JSON.
# Keys are repo-relative path strings; values are the migration plan reason.
# Add an entry when you're temporarily landing a JSON consumer; remove it once
# the consumer is migrated to Avro.
JSON_CONSUMER_BASELINE: dict[str, str] = {
    "services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py": (
        "PLAN-0062 migration backlog — convert intelligence.aggregate.v1 to Avro"
    ),
    "services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py": (
        "PLAN-0062 migration backlog — convert nlp.article.enriched.v1 to Avro"
    ),
    "services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/entity_consumer.py": (
        "PLAN-0062 migration backlog — convert nlp.entity.detected.v1 to Avro"
    ),
}


_Style = Literal["AVRO_FIRST", "AVRO_ONLY", "JSON_ONLY", "UNKNOWN"]


def _classify_deserialize_value(file_path: Path) -> _Style:
    """Read *file_path* and classify its ``deserialize_value`` implementation.

    Returns ``UNKNOWN`` if the file does not define ``deserialize_value`` (the
    caller should not pass such files in).
    """
    text = file_path.read_text(encoding="utf-8")
    marker = "def deserialize_value"
    idx = text.find(marker)
    if idx == -1:
        return "UNKNOWN"

    # Take a generous window of the body — up to the next dedent-level def or
    # end-of-file.  We scan ~30 lines, which is more than enough for the
    # short serializer methods used across the codebase.
    body = "\n".join(text[idx:].splitlines()[:30])

    has_json = "json.loads" in body
    has_avro = "deserialize_confluent_avro" in body or "deserialize_avro" in body

    if has_avro and has_json:
        return "AVRO_FIRST"
    if has_avro:
        return "AVRO_ONLY"
    if has_json:
        return "JSON_ONLY"
    return "UNKNOWN"


def _discover_consumer_files() -> list[Path]:
    """Find every ``*.py`` under ``services/*/src/**/consumers/`` that defines ``deserialize_value``."""
    matches: list[Path] = []
    for svc_src in (REPO_ROOT / "services").glob("*/src"):
        for py in svc_src.rglob("consumers/*.py"):
            text = py.read_text(encoding="utf-8")
            if "def deserialize_value" in text:
                matches.append(py)
    return sorted(matches)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestKafkaAvroEnforcement:
    def test_no_unbaselined_json_only_consumers(self) -> None:
        """Every pure-JSON consumer must be listed in JSON_CONSUMER_BASELINE."""
        violations: list[str] = []

        for py in _discover_consumer_files():
            style = _classify_deserialize_value(py)
            if style != "JSON_ONLY":
                continue
            rel = str(py.relative_to(REPO_ROOT))
            if rel not in JSON_CONSUMER_BASELINE:
                violations.append(
                    f"  {rel}\n"
                    "    deserialize_value uses json.loads with no Avro path. "
                    "Migrate to deserialize_confluent_avro or add an entry to "
                    "JSON_CONSUMER_BASELINE with a migration-plan reason."
                )

        assert not violations, (
            "\n[KAFKA-AVRO] Pure-JSON Kafka consumers found outside the baseline "
            f"({len(violations)} file(s)):\n" + "\n".join(violations)
        )

    def test_no_stale_baseline_entries(self) -> None:
        """JSON_CONSUMER_BASELINE entries must point to files that still exist and are still JSON-only.

        Stale entries (file removed or migrated to Avro) accumulate technical
        debt in the baseline itself — this test forces them to be cleaned up
        as part of the migration.
        """
        stale: list[str] = []
        for rel, reason in JSON_CONSUMER_BASELINE.items():
            full = REPO_ROOT / rel
            if not full.exists():
                stale.append(f"  {rel} — file does not exist (was: {reason})")
                continue
            style = _classify_deserialize_value(full)
            if style != "JSON_ONLY":
                stale.append(f"  {rel} — has been migrated (now {style}); remove from baseline. (was: {reason})")

        assert not stale, (
            "\n[KAFKA-AVRO baseline] Stale JSON_CONSUMER_BASELINE entries — "
            "remove them to keep the baseline accurate:\n" + "\n".join(stale)
        )

    def test_at_least_one_consumer_uses_avro(self) -> None:
        """Sanity: the codebase has at least one Avro consumer.

        Detects the pathological case where the discovery glob finds nothing
        (e.g. due to a path refactor) — without this guard
        ``test_no_unbaselined_json_only_consumers`` would trivially pass.
        """
        avro_count = sum(
            1 for py in _discover_consumer_files() if _classify_deserialize_value(py) in {"AVRO_FIRST", "AVRO_ONLY"}
        )
        assert avro_count >= 1, "No Avro consumers discovered — discovery glob may be broken"
