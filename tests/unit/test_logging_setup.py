import json
import logging

from sentinel.agent.config import LoggingSettings
from sentinel.agent.logging_setup import LOG_FILE_NAME, configure_logging, redact


def test_redact_masks_sensitive_keys_recursively():
    data = {"user": "ana", "password": "x", "nested": {"api_key": "k", "items": [{"Token": "t", "ok": 1}]}}
    assert redact(data) == {
        "user": "ana",
        "password": "***",
        "nested": {"api_key": "***", "items": [{"Token": "***", "ok": 1}]},
    }


def test_json_log_lines_include_extra_and_mask_secrets(tmp_path):
    configure_logging(LoggingSettings(console=False, level="DEBUG"), tmp_path)
    logger = logging.getLogger("sentinel.test")
    logger.info("login", extra={"user": "ana", "password": "segredo"})
    try:
        raise ValueError("ruim")
    except ValueError:
        logger.exception("falhou")
    for handler in logging.getLogger("sentinel").handlers:
        handler.flush()

    lines = [json.loads(line) for line in (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").splitlines()]
    assert lines[0]["msg"] == "login"
    assert lines[0]["extra"] == {"user": "ana", "password": "***"}
    assert "segredo" not in (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "ValueError: ruim" in lines[1]["exc"]


def test_reconfiguring_replaces_handlers(tmp_path):
    configure_logging(LoggingSettings(console=False), tmp_path / "a")
    configure_logging(LoggingSettings(console=False), tmp_path / "b")
    assert len(logging.getLogger("sentinel").handlers) == 1
