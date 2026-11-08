"""Quarentena (PRD 8.5): mover em vez de apagar, com volta possível.

Os arquivos ficam em ``data/quarantine/limpeza-<id>/``. No mesmo disco a mudança é
um "renomear" (instantâneo, sem ocupar espaço extra); entre discos é cópia +
remoção, e se a remoção falhar (arquivo em uso) a cópia é desfeita — o original
nunca some sem que a cópia esteja completa.

Atenção ao comunicar: mover para a quarentena no mesmo disco NÃO libera espaço.
O espaço volta quando o item é excluído definitivamente (pelo usuário ou pela
política de retenção).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sentinel.modules.cleaner.analyzer import Throttle, file_sha256


class QuarantineError(Exception):
    pass


def _same_device(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _move(src: str, dest: Path) -> None:
    if _same_device(src, str(dest.parent)):
        os.replace(src, dest)
        return
    shutil.copy2(src, dest)
    try:
        os.remove(src)
    except OSError:
        dest.unlink(missing_ok=True)  # original em uso: desfaz a cópia, nada muda
        raise


class QuarantineStore:
    def __init__(self, base: Path) -> None:
        self.base = base

    def move_in(self, path: str, report_id: int, index: int, throttle: Throttle | None = None) -> tuple[str, str]:
        """Move o arquivo; devolve (caminho na quarentena, sha256)."""
        folder = self.base / f"limpeza-{report_id}"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{index:05d}_{os.path.basename(path)}"
        if dest.exists():
            raise QuarantineError(f"destino já existe na quarentena: {dest}")
        _move(path, dest)
        return str(dest), file_sha256(str(dest), throttle)

    def restore(self, stored: str, original: str) -> None:
        if not os.path.isfile(stored):
            raise QuarantineError("o arquivo não está mais na quarentena")
        if os.path.lexists(original):
            raise QuarantineError("já existe um arquivo com esse nome no local original; nada foi sobrescrito")
        os.makedirs(os.path.dirname(original), exist_ok=True)
        _move(stored, Path(original))
        self._drop_empty(Path(stored).parent)

    def delete(self, stored: str) -> None:
        path = Path(stored)
        if not self._inside(path):
            raise QuarantineError("caminho fora da quarentena")  # defesa: só apaga o que está lá dentro
        path.unlink(missing_ok=True)
        self._drop_empty(path.parent)

    def _inside(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.base.resolve())
            return True
        except ValueError:
            return False

    def _drop_empty(self, folder: Path) -> None:
        try:
            if self._inside(folder) and folder != self.base and not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            pass
