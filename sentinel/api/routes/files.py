"""Navegação de pastas para escolher executáveis, scripts, diretórios e logs no cadastro.

O seletor de arquivos do navegador não revela o caminho completo (por segurança
ele devolve "C:\\fakepath\\..."), então o dashboard navega pelas pastas através
desta rota. Somente leitura: lista nomes, tamanhos e datas — nunca conteúdo — e
apenas pastas e os tipos de arquivo pedidos.
"""

from __future__ import annotations

import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import psutil
from fastapi import APIRouter, HTTPException, Query

from sentinel.core.clock import to_iso

router = APIRouter(prefix="/api/v1/files")

MAX_ENTRIES = 2000
KINDS = {
    "executable": {".exe", ".bat", ".cmd", ".com"} if sys.platform == "win32" else None,  # None: bit de execução
    "log": {".log", ".txt", ".out", ".err"},
    "directory": set(),
}


def _is_hidden(entry: os.DirEntry[str]) -> bool:
    if entry.name.startswith("."):
        return True
    if sys.platform == "win32":
        try:
            attrs = entry.stat(follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
            return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))  # type: ignore[attr-defined]
        except OSError:
            return True
    return False


def _wanted(entry: os.DirEntry[str], kind: str) -> bool:
    if kind == "directory":
        return False
    exts = KINDS[kind]
    if exts is None:  # POSIX: arquivos executáveis
        try:
            return entry.is_file() and os.access(entry.path, os.X_OK)
        except OSError:
            return False
    return os.path.splitext(entry.name)[1].lower() in exts


def _shortcuts() -> list[dict[str, str]]:
    home = Path.home()
    candidates: list[tuple[str, Path]] = [
        ("Pasta pessoal", home),
        ("Área de Trabalho", home / "Desktop"),
        ("Documentos", home / "Documents"),
        ("Downloads", home / "Downloads"),
    ]
    if sys.platform == "win32":
        for var, label in (("ProgramFiles", "Arquivos de Programas"), ("ProgramFiles(x86)", "Arquivos de Programas (x86)")):
            if os.environ.get(var):
                candidates.append((label, Path(os.environ[var])))
    return [{"label": label, "path": str(p)} for label, p in candidates if p.is_dir()]


def _roots() -> list[dict[str, str]]:
    if sys.platform != "win32":
        return [{"label": "/", "path": "/"}]
    roots = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        roots.append({"label": part.mountpoint.rstrip("\\"), "path": part.mountpoint})
    return roots


@router.get("/browse")
async def browse(
    path: str | None = Query(None, max_length=1000),
    kind: Literal["executable", "log", "directory"] = "executable",
    show_hidden: bool = False,
) -> dict[str, Any]:
    if not path:
        return {"path": None, "parent": None, "roots": _roots(), "shortcuts": _shortcuts(), "entries": []}
    if "\x00" in path or not os.path.isabs(path):
        raise HTTPException(422, "Informe um caminho absoluto")
    folder = os.path.normpath(path)
    if not os.path.isdir(folder):
        raise HTTPException(404, f"Pasta não encontrada: {folder}")

    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if not show_hidden and _is_hidden(entry):
                    continue
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    continue
                if not is_dir and not _wanted(entry, kind):
                    continue
                if len(entries) >= MAX_ENTRIES:
                    truncated = True
                    break
                info: dict[str, Any] = {"name": entry.name, "path": entry.path, "type": "directory" if is_dir else "file"}
                if not is_dir:
                    try:
                        st = entry.stat()
                        info["size"] = st.st_size
                        info["modified"] = to_iso(datetime.fromtimestamp(st.st_mtime, timezone.utc))
                    except OSError:
                        pass
                entries.append(info)
    except PermissionError as exc:
        raise HTTPException(403, f"Sem permissão para abrir {folder}") from exc
    except OSError as exc:
        raise HTTPException(400, f"Não foi possível abrir {folder}: {exc.strerror or exc}") from exc

    entries.sort(key=lambda e: (e["type"] != "directory", e["name"].lower()))
    parent = os.path.dirname(folder.rstrip("\\/")) or None
    if parent == folder or (sys.platform == "win32" and len(folder) <= 3):
        parent = None  # raiz de unidade: volta para a lista de unidades
    return {"path": folder, "parent": parent, "entries": entries, "truncated": truncated}
