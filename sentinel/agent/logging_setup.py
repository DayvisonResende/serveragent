"""Logs estruturados (JSON por linha) com rotação e mascaramento de segredos."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinel.agent.config import LoggingSettings

LOG_FILE_NAME = "sentinel.log"
REDACTED = "***"
SENSITIVE_KEYS = frozenset(
    {"password", "passwd", "secret", "token", "api_key", "apikey", "authorization", "cookie", "session"}
)

_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


def redact(value: Any) -> Any:
    """Mascara recursivamente valores de chaves sensíveis (PRD 17.5)."""
    if isinstance(value, dict):
        return {k: (REDACTED if _is_sensitive(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def _is_sensitive(key: Any) -> bool:
    lowered = str(key).lower()
    return any(s in lowered for s in SENSITIVE_KEYS)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = {k: v for k, v in vars(record).items() if k not in _RESERVED and not k.startswith("_")}
        if extra:
            payload["extra"] = redact(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: LoggingSettings, log_dir: Path) -> None:
    """Configura o logger ``sentinel``. Pode ser chamada novamente (substitui handlers)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sentinel")
    logger.setLevel(settings.level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / LOG_FILE_NAME,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    # Sob pythonw.exe (tarefa agendada, sem console) sys.stderr é None.
    if settings.console and sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        logger.addHandler(console)

    # Servidor HTTP embutido: só avisos e erros, nos mesmos destinos.
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.setLevel(logging.WARNING)
    uvicorn_logger.propagate = False
    for handler in list(uvicorn_logger.handlers):
        uvicorn_logger.removeHandler(handler)
    for handler in logger.handlers:
        uvicorn_logger.addHandler(handler)
