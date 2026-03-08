"""Tests for observability.logging."""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog

from observability.logging import configure_logging, get_logger


class TestConfigureLogging:
    def test_json_output_produces_valid_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging("test-service", level="INFO", json=True)
        log = get_logger("test")
        log.info("hello_world", key="value")
        captured = capsys.readouterr()
        # At least one line must be valid JSON
        lines = [ln for ln in captured.out.strip().splitlines() if ln.strip()]
        assert lines, "expected at least one log line"
        record = json.loads(lines[-1])
        assert record["event"] == "hello_world"
        assert record["key"] == "value"
        assert "timestamp" in record
        assert record["level"] == "info"

    def test_console_output_is_not_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging("test-service", level="INFO", json=False)
        log = get_logger("test")
        log.info("plain_event")
        captured = capsys.readouterr()
        out = captured.out
        assert out, "expected some output"
        # Console renderer uses coloured key=value format, not JSON braces
        with pytest.raises((json.JSONDecodeError, ValueError)):
            json.loads(out.strip().splitlines()[-1])

    def test_service_name_bound_in_context(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging("my-svc", level="INFO", json=True)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(service="my-svc")
        log = get_logger("test")
        log.info("ctx_event")
        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.strip().splitlines() if ln.strip()]
        record = json.loads(lines[-1])
        assert record.get("service") == "my-svc"

    def test_debug_messages_suppressed_at_info_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging("test-service", level="INFO", json=True)
        log = get_logger("test")
        log.debug("should_not_appear")
        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.strip().splitlines() if ln.strip()]
        for line in lines:
            rec = json.loads(line)
            assert rec.get("event") != "should_not_appear"

    def test_debug_messages_visible_at_debug_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging("test-service", level="DEBUG", json=True)
        log = get_logger("test")
        log.debug("debug_visible")
        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.strip().splitlines() if ln.strip()]
        events = [json.loads(ln)["event"] for ln in lines]
        assert "debug_visible" in events

    def test_stdlib_root_handler_replaced(self) -> None:
        configure_logging("test-service", level="INFO", json=True)
        root = logging.getLogger()
        assert len(root.handlers) == 1

    def test_root_log_level_set(self) -> None:
        configure_logging("test-service", level="WARNING", json=True)
        root = logging.getLogger()
        assert root.level == logging.WARNING


class TestGetLogger:
    def test_returns_bound_logger(self) -> None:
        logger = get_logger("mymodule")
        assert logger is not None

    def test_logger_has_info_method(self) -> None:
        logger = get_logger("mymodule")
        assert callable(logger.info)

    def test_different_names_return_different_loggers(self) -> None:
        l1 = get_logger("module.a")
        l2 = get_logger("module.b")
        # structlog binds the name; loggers are not the same object
        assert l1 is not l2

    def test_capsys_capture_with_io(self) -> None:
        """Ensure log output can be captured via a StringIO handler for assertions."""
        configure_logging("capture-test", level="INFO", json=True)
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.root.handlers[0].formatter)
        logging.getLogger().addHandler(handler)

        log = get_logger("test")
        log.info("io_capture_event", x=1)

        output = buf.getvalue()
        lines = [ln for ln in output.strip().splitlines() if ln.strip()]
        assert any(
            json.loads(ln)["event"] == "io_capture_event" for ln in lines
        )
