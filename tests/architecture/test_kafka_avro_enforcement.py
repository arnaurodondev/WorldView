"""Architecture test: Kafka consumers must use Avro for the wire format.

Per platform principle (PLAN-0062, Hard Rule R28): every Kafka topic's contract
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


_JSON_LOADS_PATTERNS = (
    "json.loads",
    "orjson.loads",
    "ujson.loads",
    "simplejson.loads",
    "from json import loads",
)
_FORBIDDEN_DESERIALIZERS = ("pickle.loads", "marshal.loads", "yaml.load(", "yaml.unsafe_load")
_AVRO_PATTERNS = ("deserialize_confluent_avro", "deserialize_avro")


def _classify_deserialize_value(file_path: Path) -> _Style:
    """Read *file_path* and classify its ``deserialize_value`` implementation.

    Returns ``UNKNOWN`` if the file does not define ``deserialize_value`` (the
    caller should not pass such files in).

    QA-iter1 (PLAN-0062): widened the JSON detector to cover ``orjson``,
    ``ujson``, ``simplejson``, and the ``from json import loads`` aliasing
    pattern — the prior substring scan only matched ``json.loads`` and could
    be circumvented by either alternative module imports or a renamed import.
    """
    text = file_path.read_text(encoding="utf-8")
    marker = "def deserialize_value"
    idx = text.find(marker)
    if idx == -1:
        return "UNKNOWN"

    # Generous body window — up to 60 lines or the next dedented `def`.  60
    # accommodates verbose docstrings (which the previous 30-line cap could
    # push the actual deserialise call out of view).
    body = "\n".join(text[idx:].splitlines()[:60])
    # File-level imports are needed too: ``from json import loads`` lives at
    # the top of the file, not inside the function body.
    file_head = "\n".join(text.splitlines()[:80])

    has_json = any(p in body for p in _JSON_LOADS_PATTERNS) or any(p in file_head for p in _JSON_LOADS_PATTERNS)
    has_avro = any(p in body for p in _AVRO_PATTERNS)

    if has_avro and has_json:
        return "AVRO_FIRST"
    if has_avro:
        return "AVRO_ONLY"
    if has_json:
        return "JSON_ONLY"
    return "UNKNOWN"


def _has_forbidden_deserializer(file_path: Path) -> str | None:
    """Return the offending pattern if a deserialize_value uses pickle/yaml/marshal.

    Pickle and unsafe YAML deserialisation are blanket-forbidden in any
    Kafka consumer (RCE risk on attacker-controlled broker payloads).
    """
    text = file_path.read_text(encoding="utf-8")
    marker = "def deserialize_value"
    idx = text.find(marker)
    if idx == -1:
        return None
    body = "\n".join(text[idx:].splitlines()[:60])
    for pat in _FORBIDDEN_DESERIALIZERS:
        if pat in body:
            return pat
    return None


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
        """Hard Rule R28: pure-JSON Kafka consumers are forbidden.

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
                    "Hard Rule R28 forbids pure-JSON Kafka consumers — switch to "
                    "deserialize_confluent_avro (Avro on the wire) with an "
                    "optional JSON fallback for legacy payloads."
                )

        assert not violations, (
            "\n[KAFKA-AVRO] Pure-JSON Kafka consumers are forbidden under Hard Rule R28 "
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

    def test_no_forbidden_deserializers(self) -> None:
        """No consumer may use pickle/yaml/marshal in deserialize_value.

        QA-iter1 (PLAN-0062): pickle.loads on attacker-controlled bytes is
        an RCE vector; unsafe yaml.load is the same class of bug.  Marshal
        is even worse (Python-version dependent).  Block all three
        unconditionally.
        """
        violations: list[str] = []
        for py in _discover_consumer_files():
            offender = _has_forbidden_deserializer(py)
            if offender is not None:
                rel = str(py.relative_to(REPO_ROOT))
                violations.append(f"  {rel} — uses {offender}")
        assert not violations, "\n[KAFKA-AVRO] Forbidden deserialiser detected (RCE risk):\n" + "\n".join(violations)

    def test_classifier_self_test_for_synthetic_inputs(self, tmp_path: Path) -> None:
        """Smoke-test the classifier against synthetic inputs.

        QA-iter1 (PLAN-0062 cross-agent F-005): without this, a regression in
        ``_classify_deserialize_value`` (e.g. body window too short, marker
        typo) silently turns the architecture test into a no-op — a future
        JSON-only consumer would slip through as ``UNKNOWN``.
        """
        json_only = tmp_path / "json_only.py"
        json_only.write_text(
            "import json\nclass C:\n    def deserialize_value(self, raw):\n        return json.loads(raw)\n",
            encoding="utf-8",
        )
        avro_only = tmp_path / "avro_only.py"
        avro_only.write_text(
            "from messaging.kafka.serialization_utils import deserialize_confluent_avro\n"
            "class C:\n"
            "    def deserialize_value(self, raw, schema_path):\n"
            "        return deserialize_confluent_avro(schema_path, raw)\n",
            encoding="utf-8",
        )
        avro_first = tmp_path / "avro_first.py"
        avro_first.write_text(
            "import json\n"
            "from messaging.kafka.serialization_utils import deserialize_confluent_avro\n"
            "class C:\n"
            "    def deserialize_value(self, raw, schema_path):\n"
            "        if raw[:1] == b'\\x00':\n"
            "            return deserialize_confluent_avro(schema_path, raw)\n"
            "        return json.loads(raw)\n",
            encoding="utf-8",
        )
        json_aliased = tmp_path / "json_aliased.py"
        json_aliased.write_text(
            "from json import loads\nclass C:\n    def deserialize_value(self, raw):\n        return loads(raw)\n",
            encoding="utf-8",
        )

        assert _classify_deserialize_value(json_only) == "JSON_ONLY"
        assert _classify_deserialize_value(avro_only) == "AVRO_ONLY"
        assert _classify_deserialize_value(avro_first) == "AVRO_FIRST"
        # ``from json import loads`` alias must still classify as JSON_ONLY.
        assert _classify_deserialize_value(json_aliased) == "JSON_ONLY"
