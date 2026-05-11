"""Unit tests for S5 application port ABCs.

Verifies:
- No infrastructure imports exist in the application layer.
- Infrastructure classes structurally satisfy port ABCs.
- SilverStorageAdapter explicitly extends SilverStoragePort.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# Root of the content-store application source (relative to this test file)
_APP_DIR = Path(__file__).parents[3] / "src" / "content_store" / "application"


class TestNoInfraImportsInApplication:
    def test_no_infrastructure_imports_in_use_cases(self) -> None:
        """application/use_cases/ must not import from content_store.infrastructure."""
        target = _APP_DIR / "use_cases"
        violations = []
        for py_file in target.rglob("*.py"):
            if "from content_store.infrastructure" in py_file.read_text():
                violations.append(str(py_file))
        assert not violations, f"Infrastructure imports found in use_cases: {violations}"

    def test_no_infrastructure_imports_in_deduplication(self) -> None:
        """application/deduplication/ must not import from content_store.infrastructure."""
        target = _APP_DIR / "deduplication"
        violations = []
        for py_file in target.rglob("*.py"):
            if "from content_store.infrastructure" in py_file.read_text():
                violations.append(str(py_file))
        assert not violations, f"Infrastructure imports found in deduplication: {violations}"


class TestRepositoriesImplementPorts:
    def test_document_repository_satisfies_port(self) -> None:
        from content_store.application.ports.repositories import DocumentRepositoryPort
        from content_store.infrastructure.db.repositories.document import DocumentRepository

        for method in DocumentRepositoryPort.__abstractmethods__:
            assert hasattr(DocumentRepository, method), f"DocumentRepository missing abstract method: {method}"

    def test_dedup_hash_repository_satisfies_port(self) -> None:
        from content_store.application.ports.repositories import DedupHashRepositoryPort
        from content_store.infrastructure.db.repositories.dedup import DedupHashRepository

        for method in DedupHashRepositoryPort.__abstractmethods__:
            assert hasattr(DedupHashRepository, method), f"DedupHashRepository missing abstract method: {method}"

    def test_minhash_repository_satisfies_port(self) -> None:
        from content_store.application.ports.repositories import MinHashRepositoryPort
        from content_store.infrastructure.db.repositories.minhash import MinHashRepository

        for method in MinHashRepositoryPort.__abstractmethods__:
            assert hasattr(MinHashRepository, method), f"MinHashRepository missing abstract method: {method}"

    def test_outbox_repository_satisfies_port(self) -> None:
        from content_store.application.ports.repositories import OutboxPort
        from content_store.infrastructure.db.repositories.outbox import OutboxRepository

        for method in OutboxPort.__abstractmethods__:
            assert hasattr(OutboxRepository, method), f"OutboxRepository missing abstract method: {method}"

    def test_silver_storage_adapter_is_subclass_of_port(self) -> None:
        from content_store.application.ports.storage import SilverStoragePort
        from content_store.infrastructure.storage.minio_silver import SilverStorageAdapter

        assert issubclass(SilverStorageAdapter, SilverStoragePort), "SilverStorageAdapter must extend SilverStoragePort"

    def test_bronze_storage_adapter_is_subclass_of_port(self) -> None:
        """D-2: BronzeStorageAdapter must implement BronzeStoragePort (R25 compliance)."""
        from content_store.application.ports.storage import BronzeStoragePort
        from content_store.infrastructure.storage.minio_bronze import BronzeStorageAdapter

        assert issubclass(BronzeStorageAdapter, BronzeStoragePort), "BronzeStorageAdapter must extend BronzeStoragePort"

    def test_bronze_storage_port_is_abstract(self) -> None:
        """BronzeStoragePort is an ABC — callers depend on the abstraction, not the concrete class."""
        from content_store.application.ports.storage import BronzeStoragePort

        assert hasattr(BronzeStoragePort, "__abstractmethods__")
        assert "get_bytes" in BronzeStoragePort.__abstractmethods__

    def test_lsh_client_satisfies_port(self) -> None:
        from content_store.application.ports.lsh import LSHClientPort
        from content_store.infrastructure.valkey.lsh_client import ValkeyLSHClient

        for method in LSHClientPort.__abstractmethods__:
            assert hasattr(ValkeyLSHClient, method), f"ValkeyLSHClient missing abstract method: {method}"
