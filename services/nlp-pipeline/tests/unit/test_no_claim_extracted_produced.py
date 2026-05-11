"""Regression tests for PLAN-0057 D-1 (F-CRIT-08).

The legacy ``claim.extracted`` outbox topic was an orphan: 141+ messages
dispatched on ``nlp_db.outbox_events`` but ZERO consumer groups ever
subscribed to it (verified via ``kafka-consumer-groups --describe``).
The actual claims path goes through ``nlp.article.enriched.v1.raw_claims``,
which KG's ``enriched_consumer`` reads.

These tests pin that removal so a future refactor cannot silently
re-introduce the dead producer:

1. The ``claims`` repository module file no longer exists.
2. Importing it raises ``ModuleNotFoundError``.
3. The ``deep_extraction`` block module exposes no ``ClaimsRepository``
   attribute (module-level name was deleted).
4. The article consumer module's source contains no executable reference
   to ``ClaimsRepository(`` or ``claim.extracted`` topic enqueue.
5. The ``Settings`` config no longer carries a ``topic_claim_extracted``
   attribute.

If you want to re-introduce a real claims topic in the future, build a
new producer with a known consumer group and update / delete these tests
deliberately.
"""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.unit
class TestClaimExtractedProducerRemoved:
    def test_claims_repository_module_file_does_not_exist(self) -> None:
        """The repo file was deleted in PLAN-0057 D-1."""
        # Path is computed relative to this test's project structure so the
        # check is independent of the test runner CWD.
        project_root = Path(__file__).resolve().parents[2]
        claims_module_path = (
            project_root / "src" / "nlp_pipeline" / "infrastructure" / "intelligence_db" / "repositories" / "claims.py"
        )
        assert (
            not claims_module_path.exists()
        ), f"claims.py must not exist (PLAN-0057 D-1 removed it). Found at: {claims_module_path}"

    def test_claims_repository_module_is_not_importable(self) -> None:
        """``import nlp_pipeline...claims`` must raise ModuleNotFoundError.

        We catch ``ImportError`` because ``ModuleNotFoundError`` is a subclass —
        a stale __pycache__ entry could surface as plain ImportError.
        """
        with pytest.raises(ImportError):
            importlib.import_module(
                "nlp_pipeline.infrastructure.intelligence_db.repositories.claims",
            )

    def test_deep_extraction_block_does_not_expose_claims_repository(self) -> None:
        """Module-level attribute lookup must fail."""
        block_mod = importlib.import_module("nlp_pipeline.application.blocks.deep_extraction")
        assert not hasattr(block_mod, "ClaimsRepository"), (
            "deep_extraction must not re-import ClaimsRepository — the orphan "
            "claim.extracted producer was removed in PLAN-0057 D-1."
        )

    def test_run_deep_extraction_block_signature_has_no_claims_repo_param(self) -> None:
        """Function signature regression: no ``claims_repo`` keyword."""
        block_mod = importlib.import_module("nlp_pipeline.application.blocks.deep_extraction")
        sig = inspect.signature(block_mod.run_deep_extraction_block)
        assert "claims_repo" not in sig.parameters, (
            "run_deep_extraction_block must not accept a ``claims_repo`` parameter "
            "(PLAN-0057 D-1: orphan ``claim.extracted`` producer removed)."
        )

    def test_article_consumer_source_has_no_executable_claim_extracted_enqueue(self) -> None:
        """Static source scan: no live import / instantiation of ClaimsRepository.

        Comments documenting the removal are allowed (and welcomed — they
        anti-regress future refactors). What we forbid is any executable
        Python statement that mentions ``ClaimsRepository`` or enqueues to
        a ``claim.extracted`` topic.
        """
        project_root = Path(__file__).resolve().parents[2]
        consumer_path = (
            project_root / "src" / "nlp_pipeline" / "infrastructure" / "messaging" / "consumers" / "article_consumer.py"
        )
        source = consumer_path.read_text(encoding="utf-8")

        # Strip comment lines (whitespace + #...) and triple-quoted blocks
        # so we only inspect executable code.
        source_no_block_strings = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
        executable_lines = [line for line in source_no_block_strings.splitlines() if not re.match(r"^\s*#", line)]
        executable_source = "\n".join(executable_lines)

        assert "ClaimsRepository" not in executable_source, (
            "article_consumer must not reference ClaimsRepository in executable code. "
            "Found a non-comment line mentioning it. PLAN-0057 D-1: producer was deleted."
        )
        # The consumer used to call ``outbox_repo.add(topic="claim.extracted", ...)``
        # via the ClaimsRepository wrapper — verify no quoted topic literal sneaks in.
        assert (
            '"claim.extracted"' not in executable_source
        ), "article_consumer must not enqueue to ``claim.extracted`` (orphan topic, removed)."
        assert (
            '"claim.extracted.v1"' not in executable_source
        ), "article_consumer must not enqueue to ``claim.extracted.v1`` (orphan topic, removed)."

    def test_settings_has_no_topic_claim_extracted(self) -> None:
        """Pydantic settings must not carry the dead ``topic_claim_extracted``."""
        from nlp_pipeline.config import Settings

        # Pydantic v2 exposes declared fields via ``model_fields`` (mapping
        # of name → FieldInfo). Anything else is a runtime attribute.
        assert (
            "topic_claim_extracted" not in Settings.model_fields
        ), "Settings must not declare ``topic_claim_extracted`` — removed in PLAN-0057 D-1."
