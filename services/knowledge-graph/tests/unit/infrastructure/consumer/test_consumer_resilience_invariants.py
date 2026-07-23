"""Architecture test: every ``BaseKafkaConsumer`` subclass must keep decode-poison
protection (Recurrence-1 structural fix, 2026-07-23 bottleneck audit / BP-736).

Background
----------
``services/knowledge-graph`` has ~20 Kafka consumers. Historically, "skip an
un-decodable/poison record instead of dead-lettering it" (so a single
old-schema Avro record — the routine result of a backward-compatible field
append, R11 — can never trip ``dead_letter_cap`` and crash-loop the
container) was hand-rolled independently on TWO consumers
(``EnrichedArticleConsumer``, ``PredictionEnrichedConsumer``), two months
apart, while 7 comparable consumers stayed exposed. The fix now lives in
``BaseKafkaConsumer._handle_message`` itself
(``libs/messaging/src/messaging/kafka/consumer/base.py``), gated by
``ConsumerConfig.skip_undecodable_records`` (default ``True``), so every
consumer is protected automatically — UNLESS a future consumer either:

  (a) sets ``skip_undecodable_records=False`` at its wiring site (a
      deliberate, reviewed opt-out), or
  (b) overrides ``_handle_message`` WITHOUT calling
      ``super()._handle_message(...)`` — silently bypassing the base
      protection entirely (a genuine regression risk this test guards
      against; see ``StructuredEnrichmentConsumer`` for the correct pattern:
      it overrides ``_handle_message`` for an unrelated concern —
      ``RetryableEnrichmentError`` seek-and-retry — but calls
      ``super()._handle_message(msg)`` first, so it inherits the base skip
      protection transparently).

This test enumerates every concrete ``BaseKafkaConsumer`` subclass under
``knowledge_graph.infrastructure.messaging.consumers`` and every
``ConsumerConfig(...)`` construction site under the same package, and fails
the day either invariant above is violated by a new or modified consumer —
so the fix is structurally hard to "forget" the way it was forgotten the
first two times.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_CONSUMERS_PACKAGE = "knowledge_graph.infrastructure.messaging.consumers"

# ---------------------------------------------------------------------------
# Allowlist for a deliberate ``skip_undecodable_records=False`` opt-out.
#
# Empty today (confirmed by the 2026-07-23 audit: zero occurrences of
# ``skip_undecodable_records=False`` anywhere under
# ``services/knowledge-graph/src``). Add an entry ONLY with a comment
# explaining why that specific consumer must dead-letter poison records
# instead of skipping them (per the base-class docstring's guidance: e.g. a
# consumer whose DLQ contract requires every dropped record to be persisted
# for manual replay).
# ---------------------------------------------------------------------------
_SKIP_OPT_OUT_ALLOWLIST: frozenset[str] = frozenset()


def _consumers_src_root() -> Path:
    """Return the filesystem root of the consumers package (for source scans)."""
    import knowledge_graph.infrastructure.messaging.consumers as pkg

    return Path(pkg.__file__).parent


def _iter_consumer_subclasses() -> list[type]:
    """Import every module in the consumers package and collect BaseKafkaConsumer subclasses.

    Only classes DEFINED in a given module are returned (``cls.__module__ ==
    module.__name__``) — this avoids double-counting a class re-exported by
    another module's ``from x import Y`` and avoids flagging
    ``BaseKafkaConsumer`` itself or any mixin.
    """
    from messaging.kafka.consumer.base import BaseKafkaConsumer  # type: ignore[import-untyped]

    pkg = importlib.import_module(_CONSUMERS_PACKAGE)
    found: list[type] = []
    for module_info in pkgutil.iter_modules(pkg.__path__, prefix=f"{_CONSUMERS_PACKAGE}."):
        # Skip the *_main.py wiring entrypoints — they are DI/bootstrap glue,
        # not consumer class definitions, and some pull in heavy runtime
        # config (env-var validation) that is out of scope for this
        # class-shape invariant check.
        if module_info.name.endswith("_main"):
            continue
        module = importlib.import_module(module_info.name)
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseKafkaConsumer)
                and obj is not BaseKafkaConsumer
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return found


def _overrides_handle_message_without_super(cls: type) -> bool:
    """Return True iff *cls* defines ``_handle_message`` and never calls ``super()._handle_message``.

    A class that does not override ``_handle_message`` at all inherits the
    base protection transparently (returns False — no violation). A class
    that overrides it AND still calls ``super()._handle_message(...)``
    somewhere in its body also inherits the protection (returns False). Only
    a class that overrides it and NEVER delegates to the base is a
    structural regression risk (returns True).
    """
    if "_handle_message" not in vars(cls):
        return False
    source = inspect.getsource(cls.__dict__["_handle_message"])
    return "super()._handle_message" not in source


class TestEveryConsumerSubclassKeepsDecodePoisonProtection:
    """Enumerates every BaseKafkaConsumer subclass; each must be protected."""

    def test_no_subclass_overrides_handle_message_without_calling_super(self) -> None:
        """A subclass override that never delegates to the base loses skip protection.

        This is the exact shape of regression that would silently re-open
        Recurrence-1 for a single consumer even though the base class is
        fixed — e.g. a future author copy-pasting
        ``StructuredEnrichmentConsumer``'s seek-and-retry pattern but
        forgetting the ``await super()._handle_message(msg)`` call at the top.
        """
        subclasses = _iter_consumer_subclasses()
        assert len(subclasses) >= 9, (
            f"Expected at least the 9 comparable consumers from the 2026-07-23 audit, "
            f"found {len(subclasses)}: {[c.__name__ for c in subclasses]}. "
            "If consumers were removed/renamed, update this floor; if the import "
            "enumeration silently found fewer, investigate before lowering it."
        )
        offenders = [cls.__name__ for cls in subclasses if _overrides_handle_message_without_super(cls)]
        assert not offenders, (
            f"The following consumer(s) override _handle_message WITHOUT calling "
            f"super()._handle_message(...), silently bypassing the base class's "
            f"decode-poison skip protection (Recurrence-1, BP-736): {offenders}. "
            "Either call super()._handle_message(msg) first (see "
            "StructuredEnrichmentConsumer for the reference pattern) or add "
            "explicit, reviewed decode-poison handling of your own."
        )

    def test_no_wiring_site_disables_skip_undecodable_records_without_allowlist(self) -> None:
        """``skip_undecodable_records=False`` must be a conscious, reviewed choice.

        Per the base-class fix's structural-fix recommendation: if a
        consumer genuinely needs poison records dead-lettered (not skipped),
        that is a legitimate but RARE choice that must be explicit and
        allow-listed here with a reason — never a silent default flip nobody
        notices in review.
        """
        root = _consumers_src_root()
        offenders: list[str] = []
        for path in sorted(root.glob("*.py")):
            text = path.read_text()
            if re.search(r"skip_undecodable_records\s*=\s*False", text) and path.stem not in _SKIP_OPT_OUT_ALLOWLIST:
                offenders.append(path.name)
        assert not offenders, (
            f"The following file(s) set skip_undecodable_records=False without "
            f"being added to _SKIP_OPT_OUT_ALLOWLIST in this test (with a comment "
            f"explaining why): {offenders}"
        )

    def test_batch_path_consumers_are_exempt_but_documented(self) -> None:
        """Consumers on the batched path (``consume_batch_size > 1``) get their
        own inline poison-skip in ``BaseKafkaConsumer._handle_batch`` (verified
        by the 2026-07-23 audit) and do not need the single-message-path
        protection asserted above. As of the audit, NO knowledge-graph
        consumer opts into batching (``consume_batch_size`` stays at the
        default of 1 everywhere) — this test documents that fact and will
        fail loudly (prompting a human to re-verify the batch path's poison
        handling) the day a consumer's wiring first sets it.
        """
        root = _consumers_src_root()
        batched: list[str] = []
        for path in sorted(root.glob("*_main.py")):
            text = path.read_text()
            match = re.search(r"consume_batch_size\s*=\s*(\d+)", text)
            if match and int(match.group(1)) > 1:
                batched.append(path.name)
        assert not batched, (
            f"New batched-path consumer(s) detected: {batched}. Verify "
            "BaseKafkaConsumer._handle_batch's inline poison-skip still covers "
            "them (it should, per the 2026-07-23 audit), then update this "
            "test's expectations rather than silently passing."
        )


def _all_consumer_config_construction_sites() -> list[Path]:
    """Return every source file under the consumers package that builds a ConsumerConfig."""
    root = _consumers_src_root()
    sites: list[Path] = []
    for path in sorted(root.glob("*_main.py")):
        if "ConsumerConfig(" in path.read_text():
            sites.append(path)
    return sites


class TestConsumerConfigWiringSitesEnumerated:
    """Sanity check that the wiring-site scan above actually finds real files.

    Guards against the regex-based scan in
    ``test_no_wiring_site_disables_skip_undecodable_records_without_allowlist``
    silently scanning zero files (e.g. after a directory rename) and passing
    vacuously.
    """

    def test_at_least_nine_main_files_construct_a_consumer_config(self) -> None:
        sites = _all_consumer_config_construction_sites()
        assert len(sites) >= 9, (
            f"Expected at least 9 *_main.py wiring sites constructing ConsumerConfig, "
            f"found {len(sites)}: {[p.name for p in sites]}"
        )
