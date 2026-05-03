"""Architecture test: Kafka consumers must use Avro for the wire format.

Per platform principle (PLAN-0062, Hard Rule 18): every Kafka topic's contract
MUST be defined as an Avro schema in ``infra/kafka/schemas/`` AND deserialized
via ``deserialize_confluent_avro`` (or ``deserialize_avro``) in the consumer's
``deserialize_value`` method.  Pure ``json.loads`` consumers are forbidden —
they bypass schema enforcement, hide forward-compat violations, and split the
platform contract surface across two encodings.

This test scans every ``deserialize_value`` implementation under
``services/*/src/**/consumers/*.py`` and classifies it as one of:

    AVRO_FIRST  — uses deserialize_confluent_avro/deserialize_avro and falls
                  back to json.loads for legacy payloads (the recommended
                  pattern during a migration window)
    AVRO_ONLY   — Avro with no JSON fallback (preferred for new consumers)
    JSON_ONLY   — pure json.loads (forbidden — build failure)

Wave D-1 (PLAN-0062) removed the JSON_CONSUMER_BASELINE escape hatch — the
test is now unconditional.  Any new pure-JSON consumer is a build failure
that must be fixed in the same PR by switching to AVRO_FIRST/AVRO_ONLY.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    def test_no_json_only_consumers(self) -> None:
        """Hard Rule 18: pure-JSON Kafka consumers are forbidden.

        Wave D-1 removed the baseline escape hatch — every consumer must
        decode via Avro (with optional JSON fallback for legacy messages).
        """
        violations: list[str] = []

        for py in _discover_consumer_files():
            style = _classify_deserialize_value(py)
            if style == "JSON_ONLY":
                rel = str(py.relative_to(REPO_ROOT))
                violations.append(
                    f"  {rel}\n"
                    "    deserialize_value uses json.loads with no Avro path. "
                    "Hard Rule 18 forbids pure-JSON Kafka consumers — switch to "
                    "deserialize_confluent_avro (Avro on the wire) with an "
                    "optional JSON fallback for legacy payloads."
                )

        assert not violations, (
            "\n[KAFKA-AVRO] Pure-JSON Kafka consumers are forbidden under Hard Rule 18 "
            f"({len(violations)} file(s)):\n" + "\n".join(violations)
        )

    def test_at_least_one_consumer_uses_avro(self) -> None:
        """Sanity: the codebase has at least one Avro consumer.

        Detects the pathological case where the discovery glob finds nothing
        (e.g. due to a path refactor) — without this guard
        ``test_no_json_only_consumers`` would trivially pass.
        """
        avro_count = sum(
            1 for py in _discover_consumer_files() if _classify_deserialize_value(py) in {"AVRO_FIRST", "AVRO_ONLY"}
        )
        assert avro_count >= 1, "No Avro consumers discovered — discovery glob may be broken"
