"""
Unit tests for process topology helpers in tests/architecture/_utils.py.

Tests the utility functions added by PLAN-0011 Wave A-1 (T-A-1-03):
- ProcessType enum
- ProcessEntryPoint dataclass
- CANONICAL_PATHS mapping
- discover_process_entry_points()
- has_background_tasks_in_lifespan()
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tests.architecture._utils import (
    CANONICAL_PATHS,
    ProcessType,
    ServiceInfo,
    discover_process_entry_points,
    has_background_tasks_in_lifespan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_svc(tmp_path: Path, name: str = "test-svc", pkg_name: str = "test_svc") -> ServiceInfo:
    """Create a minimal ServiceInfo rooted at tmp_path."""
    service_dir = tmp_path / name
    src_dir = service_dir / "src"
    pkg_dir = src_dir / pkg_name
    pkg_dir.mkdir(parents=True)
    return ServiceInfo(
        name=name,
        service_dir=service_dir,
        src_dir=src_dir,
        pkg_name=pkg_name,
        pkg_dir=pkg_dir,
    )


def _touch(path: Path) -> Path:
    """Create a file and all parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# stub\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# ProcessType enum
# ---------------------------------------------------------------------------


class TestProcessTypeEnum:
    def test_has_four_values(self) -> None:
        assert len(ProcessType) == 4

    def test_values(self) -> None:
        assert ProcessType.DISPATCHER.value == "dispatcher"
        assert ProcessType.CONSUMER.value == "consumer"
        assert ProcessType.SCHEDULER.value == "scheduler"
        assert ProcessType.WORKER.value == "worker"


# ---------------------------------------------------------------------------
# CANONICAL_PATHS
# ---------------------------------------------------------------------------


class TestCanonicalPaths:
    def test_all_process_types_covered(self) -> None:
        assert set(CANONICAL_PATHS.keys()) == set(ProcessType)

    def test_dispatcher_path(self) -> None:
        assert CANONICAL_PATHS[ProcessType.DISPATCHER] == "infrastructure/messaging/outbox"

    def test_consumer_path(self) -> None:
        assert CANONICAL_PATHS[ProcessType.CONSUMER] == "infrastructure/messaging/consumers"

    def test_scheduler_path(self) -> None:
        assert CANONICAL_PATHS[ProcessType.SCHEDULER] == "infrastructure/scheduler"

    def test_worker_path(self) -> None:
        assert CANONICAL_PATHS[ProcessType.WORKER] == "infrastructure/workers"


# ---------------------------------------------------------------------------
# discover_process_entry_points — dispatchers
# ---------------------------------------------------------------------------


class TestDiscoverFindsDispatcher:
    def test_dispatcher_class_and_main_found(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        outbox_dir = svc.pkg_dir / "infrastructure" / "messaging" / "outbox"
        _touch(outbox_dir / "dispatcher.py")
        _touch(outbox_dir / "dispatcher_main.py")

        entries = discover_process_entry_points(svc)
        dispatchers = [e for e in entries if e.process_type == ProcessType.DISPATCHER]

        assert len(dispatchers) == 1
        ep = dispatchers[0]
        assert ep.class_file is not None
        assert ep.main_file is not None
        assert not ep.missing_main

    def test_dispatcher_class_without_main(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        outbox_dir = svc.pkg_dir / "infrastructure" / "messaging" / "outbox"
        _touch(outbox_dir / "dispatcher.py")

        entries = discover_process_entry_points(svc)
        dispatchers = [e for e in entries if e.process_type == ProcessType.DISPATCHER]

        assert len(dispatchers) == 1
        ep = dispatchers[0]
        assert ep.class_file is not None
        assert ep.main_file is None
        assert ep.missing_main

    def test_no_outbox_dir_returns_no_dispatcher(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        # No infrastructure dir at all
        entries = discover_process_entry_points(svc)
        dispatchers = [e for e in entries if e.process_type == ProcessType.DISPATCHER]
        assert len(dispatchers) == 0

    def test_dispatcher_canonical_path_flag(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        outbox_dir = svc.pkg_dir / "infrastructure" / "messaging" / "outbox"
        _touch(outbox_dir / "dispatcher.py")
        _touch(outbox_dir / "dispatcher_main.py")

        entries = discover_process_entry_points(svc)
        ep = next(e for e in entries if e.process_type == ProcessType.DISPATCHER)
        assert ep.is_canonical_path


# ---------------------------------------------------------------------------
# discover_process_entry_points — consumers
# ---------------------------------------------------------------------------


class TestDiscoverFindsConsumers:
    def test_canonical_consumer_with_main(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        consumers_dir = svc.pkg_dir / "infrastructure" / "messaging" / "consumers"
        _touch(consumers_dir / "article_consumer.py")
        _touch(consumers_dir / "article_consumer_main.py")

        entries = discover_process_entry_points(svc)
        consumers = [e for e in entries if e.process_type == ProcessType.CONSUMER]

        assert len(consumers) == 1
        ep = consumers[0]
        assert ep.class_file is not None
        assert ep.main_file is not None
        assert not ep.missing_main

    def test_multiple_consumers(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        consumers_dir = svc.pkg_dir / "infrastructure" / "messaging" / "consumers"
        for name in ("article_consumer", "watchlist_consumer"):
            _touch(consumers_dir / f"{name}.py")

        entries = discover_process_entry_points(svc)
        consumers = [e for e in entries if e.process_type == ProcessType.CONSUMER]

        assert len(consumers) == 2
        assert all(ep.missing_main for ep in consumers)

    def test_legacy_consumer_dir_is_found(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        # Legacy singular 'consumer/' directory (scaffolded services)
        legacy_dir = svc.pkg_dir / "infrastructure" / "consumer"
        _touch(legacy_dir / "article_consumer.py")

        entries = discover_process_entry_points(svc)
        consumers = [e for e in entries if e.process_type == ProcessType.CONSUMER]

        assert len(consumers) == 1
        assert consumers[0].missing_main

    def test_canonical_path_flag_for_consumers(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        consumers_dir = svc.pkg_dir / "infrastructure" / "messaging" / "consumers"
        _touch(consumers_dir / "article_consumer.py")

        entries = discover_process_entry_points(svc)
        ep = next(e for e in entries if e.process_type == ProcessType.CONSUMER)
        assert ep.is_canonical_path


# ---------------------------------------------------------------------------
# discover_process_entry_points — scheduler
# ---------------------------------------------------------------------------


class TestDiscoverFindsScheduler:
    def test_canonical_scheduler_dir(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        sched_dir = svc.pkg_dir / "infrastructure" / "scheduler"
        _touch(sched_dir / "scheduler.py")
        _touch(sched_dir / "scheduler_main.py")

        entries = discover_process_entry_points(svc)
        schedulers = [e for e in entries if e.process_type == ProcessType.SCHEDULER]

        assert len(schedulers) == 1
        ep = schedulers[0]
        assert ep.class_file is not None
        assert ep.main_file is not None
        assert not ep.missing_main

    def test_legacy_schedulers_plural_dir(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        # Legacy plural 'schedulers/' directory
        sched_dir = svc.pkg_dir / "infrastructure" / "schedulers"
        _touch(sched_dir / "scheduler.py")

        entries = discover_process_entry_points(svc)
        schedulers = [e for e in entries if e.process_type == ProcessType.SCHEDULER]

        assert len(schedulers) == 1
        assert schedulers[0].missing_main

    def test_stale_scheduler_process_name_treated_as_class(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        sched_dir = svc.pkg_dir / "infrastructure" / "scheduler"
        # Old naming: scheduler_process.py (stale)
        _touch(sched_dir / "scheduler_process.py")

        entries = discover_process_entry_points(svc)
        schedulers = [e for e in entries if e.process_type == ProcessType.SCHEDULER]

        assert len(schedulers) == 1
        assert schedulers[0].class_file is not None
        assert schedulers[0].missing_main


# ---------------------------------------------------------------------------
# discover_process_entry_points — workers
# ---------------------------------------------------------------------------


class TestDiscoverFindsWorkers:
    def test_worker_with_main(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        workers_dir = svc.pkg_dir / "infrastructure" / "workers"
        _touch(workers_dir / "worker.py")
        _touch(workers_dir / "worker_main.py")

        entries = discover_process_entry_points(svc)
        workers = [e for e in entries if e.process_type == ProcessType.WORKER]

        assert len(workers) == 1
        ep = workers[0]
        assert not ep.missing_main

    def test_worker_missing_main(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        workers_dir = svc.pkg_dir / "infrastructure" / "workers"
        _touch(workers_dir / "worker.py")

        entries = discover_process_entry_points(svc)
        workers = [e for e in entries if e.process_type == ProcessType.WORKER]

        assert len(workers) == 1
        assert workers[0].missing_main

    def test_no_workers_dir_returns_no_worker(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        # No infrastructure dir
        entries = discover_process_entry_points(svc)
        workers = [e for e in entries if e.process_type == ProcessType.WORKER]
        assert len(workers) == 0


# ---------------------------------------------------------------------------
# discover_process_entry_points — no infrastructure dir
# ---------------------------------------------------------------------------


class TestDiscoverNoInfrastructure:
    def test_service_without_infra_dir(self, tmp_path: Path) -> None:
        svc = _make_svc(tmp_path)
        # pkg_dir exists but has no infrastructure/ subdirectory
        entries = discover_process_entry_points(svc)
        assert entries == []


# ---------------------------------------------------------------------------
# has_background_tasks_in_lifespan
# ---------------------------------------------------------------------------


class TestLifespanDetectionPositive:
    def test_detects_create_task_in_lifespan(self, tmp_path: Path) -> None:
        app_py = tmp_path / "app.py"
        app_py.write_text(
            textwrap.dedent("""\
                import asyncio

                async def lifespan(app):
                    task = asyncio.create_task(some_consumer.run())
                    yield
                    task.cancel()
            """),
            encoding="utf-8",
        )

        violations = has_background_tasks_in_lifespan(app_py)

        assert len(violations) == 1
        line, desc = violations[0]
        assert line > 0
        assert "create_task" in desc

    def test_detects_multiple_create_task_calls(self, tmp_path: Path) -> None:
        app_py = tmp_path / "app.py"
        app_py.write_text(
            textwrap.dedent("""\
                import asyncio

                async def lifespan(app):
                    t1 = asyncio.create_task(consumer.run())
                    t2 = asyncio.create_task(dispatcher.run())
                    t3 = asyncio.create_task(_run_metrics())
                    yield
            """),
            encoding="utf-8",
        )

        violations = has_background_tasks_in_lifespan(app_py)
        assert len(violations) == 3

    def test_detects_asynccontextmanager_decorated_lifespan(self, tmp_path: Path) -> None:
        app_py = tmp_path / "app.py"
        app_py.write_text(
            textwrap.dedent("""\
                import asyncio
                from contextlib import asynccontextmanager

                @asynccontextmanager
                async def lifespan(app):
                    task = asyncio.create_task(worker.run())
                    yield
            """),
            encoding="utf-8",
        )

        violations = has_background_tasks_in_lifespan(app_py)
        assert len(violations) == 1

    def test_does_not_flag_create_task_outside_lifespan(self, tmp_path: Path) -> None:
        app_py = tmp_path / "app.py"
        app_py.write_text(
            textwrap.dedent("""\
                import asyncio

                async def some_route_handler():
                    task = asyncio.create_task(do_background_work())
                    return {"ok": True}

                async def lifespan(app):
                    yield
            """),
            encoding="utf-8",
        )

        violations = has_background_tasks_in_lifespan(app_py)
        assert violations == []


class TestLifespanDetectionNegative:
    def test_clean_app_py_returns_empty(self, tmp_path: Path) -> None:
        app_py = tmp_path / "app.py"
        app_py.write_text(
            textwrap.dedent("""\
                from fastapi import FastAPI

                async def lifespan(app):
                    # Connect to DB only — no background tasks
                    yield

                def create_app() -> FastAPI:
                    return FastAPI(lifespan=lifespan)
            """),
            encoding="utf-8",
        )

        violations = has_background_tasks_in_lifespan(app_py)
        assert violations == []

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        app_py = tmp_path / "nonexistent_app.py"
        violations = has_background_tasks_in_lifespan(app_py)
        assert violations == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        app_py = tmp_path / "app.py"
        app_py.write_text("", encoding="utf-8")
        violations = has_background_tasks_in_lifespan(app_py)
        assert violations == []
