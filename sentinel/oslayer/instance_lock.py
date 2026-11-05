"""Trava de instância única.

Impede dois agentes simultâneos (por exemplo, a tarefa agendada reiniciando o
agente enquanto uma cópia manual ainda roda). O sistema operacional libera a
trava automaticamente se o processo morrer, então não há arquivo "preso".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType

from sentinel.core.exceptions import InstanceLockError


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock(fd)
        except OSError as exc:
            os.close(fd)
            holder = _read_pid(self.path)
            detail = f" (PID {holder})" if holder else ""
            raise InstanceLockError(f"Outra instância do Sentinel já está em execução{detail}") from exc
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, str(os.getpid()).encode("ascii"))
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            _unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.release()


if sys.platform == "win32":
    import msvcrt

    def _lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_pid(path: Path) -> str | None:
    """Melhor esforço: no Windows o byte travado não pode ser lido por outro processo."""
    try:
        content = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return content if content.isdigit() else None
