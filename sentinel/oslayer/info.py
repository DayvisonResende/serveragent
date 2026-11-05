"""Informações do sistema operacional e do nível de privilégio do processo."""

from __future__ import annotations

import logging
import os
import platform
import sys
from dataclasses import asdict, dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlatformInfo:
    system: str
    release: str
    version: str
    machine: str
    python_version: str
    is_admin: bool | None  # None = não foi possível determinar

    @property
    def is_windows(self) -> bool:
        return self.system == "Windows"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_platform_info() -> PlatformInfo:
    return PlatformInfo(
        system=platform.system(),
        release=platform.release(),
        version=platform.version(),
        machine=platform.machine(),
        python_version=platform.python_version(),
        is_admin=_detect_admin(),
    )


def _detect_admin() -> bool | None:
    try:
        if sys.platform == "win32":
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except (AttributeError, OSError) as exc:
        log.warning("Não foi possível determinar o nível de privilégio", extra={"error": str(exc)})
        return None
