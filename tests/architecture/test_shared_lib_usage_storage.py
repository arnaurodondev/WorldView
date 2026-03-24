"""
Architecture test: libs/storage usage patterns.

Verifies that service src/ code does not directly instantiate minio.Minio
or use boto3, but goes through the storage library adapter.

Per docs/libs/storage.md and docs/STANDARDS.md §4.
"""

from __future__ import annotations

from pathlib import Path

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_services,
    iter_py_files,
    scan_imports,
)


def _src_files(svc: ServiceInfo) -> list[Path]:
    return [f for f in iter_py_files(svc.pkg_dir) if "tests" not in f.parts]


class TestNoDirectStorageImports:
    def test_no_direct_minio_in_service_src(self) -> None:
        """Service src/ must not import minio directly."""
        violations = []
        for svc in discover_services():
            for py_file in _src_files(svc):
                rel = str(py_file.relative_to(svc.service_dir.parent.parent))
                for imp in scan_imports(py_file):
                    if imp.module == "minio" or imp.module.startswith("minio."):
                        violations.append(
                            ArchViolation(
                                service=svc.name,
                                file=rel,
                                line=imp.line,
                                rule="IG-STORAGE-001",
                                detail=f"Direct minio import: `{imp.module}` — use storage.ObjectStorageClient",
                            )
                        )
        assert_no_violations(violations, rule="IG-STORAGE-001")

    def test_no_direct_boto3_in_service_src(self) -> None:
        """Service src/ must not import boto3 directly."""
        violations = []
        for svc in discover_services():
            for py_file in _src_files(svc):
                rel = str(py_file.relative_to(svc.service_dir.parent.parent))
                for imp in scan_imports(py_file):
                    if imp.module == "boto3" or imp.module.startswith("boto3."):
                        violations.append(
                            ArchViolation(
                                service=svc.name,
                                file=rel,
                                line=imp.line,
                                rule="IG-STORAGE-002",
                                detail=f"Direct boto3 import: `{imp.module}` — use storage.ObjectStorageClient",
                            )
                        )
        assert_no_violations(violations, rule="IG-STORAGE-002")
