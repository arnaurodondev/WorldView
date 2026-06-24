"""Test: every consumer entry point wires Kafka static-membership identity.

PLAN-0113 QA L1 (regression lock for PRD-0113 FR-9 / BP-703).

Background
----------
PRD-0113 adopted Kafka static membership (KIP-345): every consumer process must
pass a ``group_instance_id`` to the transport-level ``ConsumerConfig`` so a
restarting replica rejoins with its stable identity instead of triggering a full
group rebalance (the controller-overload storm of BP-703). A ``*_main.py`` that
silently drops the ``group_instance_id=`` kwarg would regress that protection
without any runtime error — the consumer would just fall back to dynamic
membership.

This static test greps every consumer ``*_main.py`` that directly constructs a
transport-level ``ConsumerConfig(...)`` and asserts it passes a
``group_instance_id=`` kwarg. It needs no Kafka and no imports of the services.

Scope note
----------
We deliberately match the BARE ``ConsumerConfig(`` constructor (not suffixed
wrapper classes such as ``ArticleConsumerConfig``). Services that wrap the
transport config in their own dataclass (content-store) set the kwarg INSIDE the
consumer class, not in ``*_main.py``, so their ``*_main.py`` correctly does not
construct ``ConsumerConfig`` directly and is not in scope here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SERVICES_DIR = _REPO_ROOT / "services"

# Matches the BARE transport ConsumerConfig constructor only — a preceding
# letter/digit/underscore (e.g. the "Article" in ArticleConsumerConfig) excludes
# wrapper classes.
_BARE_CONSUMER_CONFIG_CALL = re.compile(r"(?<![A-Za-z0-9_])ConsumerConfig\(")
_GROUP_INSTANCE_ID_KWARG = re.compile(r"\bgroup_instance_id\s*=")


def _consumer_main_files() -> list[Path]:
    """Return every ``*_consumer_main.py`` under services/ that builds ConsumerConfig.

    We restrict to files that actually construct the bare ``ConsumerConfig`` so the
    parametrization documents exactly the entry points the contract binds.
    """
    files: list[Path] = []
    for path in sorted(_SERVICES_DIR.glob("*/src/**/*_main.py")):
        text = path.read_text()
        if _BARE_CONSUMER_CONFIG_CALL.search(text):
            files.append(path)
    return files


_MAIN_FILES = _consumer_main_files()


@pytest.mark.unit
def test_consumer_main_files_discovered() -> None:
    """Sanity: the glob actually finds the consumer entry points.

    Guards against a future refactor silently emptying the parametrization (which
    would make the per-file test below vacuously pass).
    """
    assert _MAIN_FILES, "no *_main.py constructing ConsumerConfig found under services/"


@pytest.mark.unit
@pytest.mark.parametrize("main_file", _MAIN_FILES, ids=lambda p: p.relative_to(_SERVICES_DIR).as_posix())
def test_consumer_main_passes_group_instance_id(main_file: Path) -> None:
    """Every bare ConsumerConfig(...) site must pass group_instance_id= (BP-703)."""
    text = main_file.read_text()
    assert _GROUP_INSTANCE_ID_KWARG.search(text), (
        f"{main_file.relative_to(_REPO_ROOT)} constructs ConsumerConfig(...) but does "
        "NOT pass group_instance_id= — static-membership identity (KIP-345/BP-703) "
        "would silently regress to dynamic membership."
    )
