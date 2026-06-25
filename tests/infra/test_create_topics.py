"""Test: dev Kafka topics declare reduced partition counts.

PLAN-0113 Wave 1 T-A-1-04 (PRD-0113 FR-1, §14 OQ-1, §11 Infra Tests).

Background
----------
The single-node KRaft dev broker previously carried ~212 app partitions (counts
inherited from PRD §7's multi-broker production sizing).  On one host this
inflates controller metadata/replica load and consumer-group rebalance cost for
no throughput benefit.  Wave 1 cut dev counts to <= ~40 app partitions:

  - 3 partitions for the genuinely-parallel pipeline topics
    (content.article.raw.v1, content.article.stored.v1,
    nlp.article.enriched.v1, nlp.signal.detected.v1);
  - 1 partition for every other app topic (incl. all DLQs and the compacted
    entity.dirtied.v1).

These tests parse ``create-topics.sh`` directly (no Kafka required) and pin that
contract.  The enumerated topic set is the same one W5's FR-3 parity test will
reuse.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TOPICS_SCRIPT = _REPO_ROOT / "infra" / "kafka" / "init" / "create-topics.sh"

# Max partitions any single dev app topic may declare (the 4 pipeline topics).
_MAX_PER_TOPIC = 3
# Hard ceiling on the sum of all declared app partitions in dev.
_MAX_TOTAL = 40

# Topics expected to carry the higher (3) partition count in dev.
_PIPELINE_TOPICS: frozenset[str] = frozenset(
    {
        "content.article.raw.v1",
        "content.article.stored.v1",
        "nlp.article.enriched.v1",
        "nlp.signal.detected.v1",
    }
)

# Matches an array entry like:  "topic.name:3:1"  (name:partitions:rf)
_ARRAY_ENTRY = re.compile(r'"([A-Za-z0-9._-]+):(\d+):(\d+)"')
# Matches the compacted topic's --partitions flag in its standalone create block.
_COMPACTED_PARTITIONS = re.compile(r"--topic\s+entity\.dirtied\.v1\s+\\\s*\n\s*--partitions\s+(\d+)")


def _parse_topics() -> dict[str, int]:
    """Return ``{topic_name: partitions}`` for all declared dev app topics.

    Parses BOTH the ``TOPICS=( ... )`` array AND the standalone compacted
    ``entity.dirtied.v1`` create block so the partition ceiling covers the full
    app topic set.
    """
    assert _TOPICS_SCRIPT.exists(), f"create-topics.sh missing at {_TOPICS_SCRIPT}"
    text = _TOPICS_SCRIPT.read_text()

    # Isolate the TOPICS array body so we do not accidentally match unrelated
    # quoted "name:n:n" strings elsewhere in the script.
    array_match = re.search(r"TOPICS=\(\s*(.*?)\)", text, re.DOTALL)
    assert array_match, "could not locate TOPICS=( ... ) array in create-topics.sh"
    array_body = array_match.group(1)

    topics: dict[str, int] = {}
    for name, partitions, _rf in _ARRAY_ENTRY.findall(array_body):
        topics[name] = int(partitions)

    assert topics, "no topics parsed from TOPICS array"

    # Add the compacted topic from its separate create block.
    compacted = _COMPACTED_PARTITIONS.search(text)
    assert compacted, "could not locate entity.dirtied.v1 --partitions in create-topics.sh"
    topics["entity.dirtied.v1"] = int(compacted.group(1))

    return topics


@pytest.mark.unit
def test_create_topics_partition_counts() -> None:
    """Every app topic <= 3 partitions; pipeline topics == 3, others == 1."""
    topics = _parse_topics()

    errors: list[str] = []
    for name, partitions in topics.items():
        if partitions > _MAX_PER_TOPIC:
            errors.append(f"{name}: {partitions} > {_MAX_PER_TOPIC} partitions")
        expected = 3 if name in _PIPELINE_TOPICS else 1
        if partitions != expected:
            errors.append(f"{name}: expected {expected} partitions, got {partitions}")

    # Sanity: every expected pipeline topic must actually be present.
    for name in _PIPELINE_TOPICS:
        if name not in topics:
            errors.append(f"pipeline topic '{name}' missing from create-topics.sh")

    assert not errors, "\n".join(errors)


@pytest.mark.unit
def test_create_topics_total_le_40() -> None:
    """Sum of all declared app partitions (incl. compacted) <= 40."""
    topics = _parse_topics()
    total = sum(topics.values())
    assert total <= _MAX_TOTAL, f"total dev app partitions {total} exceeds ceiling {_MAX_TOTAL}"


# ── FR-3 cross-env topic-name parity (PLAN-0113 W5 / T-B-5-01) ────────────────────
# The dev topic SET (create-topics.sh) and the PROD declarative provisioning SET
# (worldview-gitops apps/infra-kafka.yaml -> spec.source.helm.valuesObject.
# provisioning.topics) MUST contain the SAME topic NAMES. Only the per-env partition
# counts diverge (FR-1 dev reduction vs PRD §7 prod sizing); the name set is the
# single source of truth and must stay in lock-step across both repos.
#
# The gitops repo is a SEPARATE checkout that is not guaranteed present in this
# repo's CI, so we embed the canonical 23-name list here rather than parse the
# cross-repo file. If you add/remove a topic in worldview-gitops
# apps/infra-kafka.yaml provisioning.topics, mirror the change in BOTH
# infra/kafka/init/create-topics.sh AND this list (and vice-versa).
_CANONICAL_PROVISIONING_TOPICS: frozenset[str] = frozenset(
    {
        "portfolio.events.v1",
        "portfolio.watchlist.updated.v1",
        "market.dataset.fetched",
        "market.instrument.created",
        "market.instrument.updated",
        "market.instrument.discovered.v1",
        "content.article.raw.v1",
        "content.article.stored.v1",
        "nlp.article.enriched.v1",
        "nlp.signal.detected.v1",
        "graph.state.changed.v1",
        "intelligence.contradiction.v1",
        "relation.type.proposed.v1",
        "entity.canonical.created.v1",
        "entity.refresh.v1",
        "alert.delivered.v1",
        "market.prediction.v1",
        "kg.dead-letter.v1",
        "alert.dead-letter.v1",
        "nlp.dead-letter.v1",
        "content.dead-letter.v1",
        "market.dead-letter.v1",
        # Compacted topic (key = entity_id). Created in its own block in
        # create-topics.sh; carried in provisioning.topics with cleanup.policy=compact.
        "entity.dirtied.v1",
    }
)


@pytest.mark.unit
def test_topic_set_parity_dev_vs_prod() -> None:
    """Dev create-topics.sh topic NAMES == canonical prod provisioning NAMES (FR-3).

    Asserts set EQUALITY (no extras, no omissions) so a topic added to only one of
    the two declarative records is caught. ``_parse_topics`` already includes the
    compacted ``entity.dirtied.v1`` from its standalone create block.
    """
    dev_names = frozenset(_parse_topics().keys())

    missing_in_dev = _CANONICAL_PROVISIONING_TOPICS - dev_names
    extra_in_dev = dev_names - _CANONICAL_PROVISIONING_TOPICS

    errors: list[str] = []
    if missing_in_dev:
        errors.append(f"topics in prod provisioning but MISSING from create-topics.sh: {sorted(missing_in_dev)}")
    if extra_in_dev:
        errors.append(f"topics in create-topics.sh but NOT in prod provisioning: {sorted(extra_in_dev)}")

    assert not errors, "\n".join(errors)
