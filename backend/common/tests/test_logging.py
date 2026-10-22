"""Logging layer tests."""
import json


def test_get_logger_returns_structlog_logger():
    """get_logger should return a structlog BoundLogger."""
    from common.logging import get_logger

    log = get_logger("test")
    assert hasattr(log, "info")
    assert hasattr(log, "bind")


def test_configure_logging_outputs_json(capsys):
    """configure_logging should emit JSON lines."""
    from common.logging import configure_logging, get_logger

    configure_logging(level="INFO", json_output=True)
    log = get_logger("test")
    log.info("test_event", key1="value1", count=42)

    captured = capsys.readouterr()
    line = captured.out.strip().split("\n")[-1]
    parsed = json.loads(line)
    assert parsed["event"] == "test_event"
    assert parsed["key1"] == "value1"
    assert parsed["count"] == 42


def test_bind_carries_context(capsys):
    """bind() should add persistent context to all subsequent logs."""
    from common.logging import configure_logging, get_logger

    configure_logging(level="INFO", json_output=True)
    log = get_logger("test").bind(request_id="abc123")
    log.info("event_a")
    log.info("event_b")

    captured = capsys.readouterr()
    lines = [json.loads(line) for line in captured.out.strip().split("\n") if line]
    request_lines = [line for line in lines if line.get("event") in ("event_a", "event_b")]
    assert len(request_lines) == 2
    assert all(line["request_id"] == "abc123" for line in request_lines)
