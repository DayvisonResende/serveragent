"""Identificação de hardware que o psutil não fornece."""

from __future__ import annotations

import logging
import platform
import socket
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def cpu_model() -> str | None:
    """Nome comercial do processador (ex.: 'Intel(R) Core(TM) i5-4590 CPU @ 3.30GHz')."""
    try:
        if sys.platform == "win32":
            import winreg

            key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                return str(value).strip() or None
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip() or None
    except OSError as exc:
        log.warning("Não foi possível identificar o modelo do processador", extra={"error": str(exc)})
    fallback = platform.processor().strip()
    return fallback or None


def hostname() -> str:
    return socket.gethostname()
