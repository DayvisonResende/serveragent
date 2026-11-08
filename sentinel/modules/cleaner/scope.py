"""Onde o Sentinel pode limpar e o que nunca toca (PRD 8.6).

Duas listas, com papéis diferentes:

- **pastas autorizadas**: as únicas de onde algo pode ir para a quarentena. Padrão:
  a pasta de temporários do usuário e Downloads. O usuário acrescenta outras no
  dashboard; raiz de disco, perfil inteiro e pastas protegidas são recusadas.
- **proteções**: valem mesmo dentro das pastas autorizadas — Windows, Arquivos de
  Programas, ProgramData, pastas Inicializar, o próprio Sentinel, as pastas dos
  servidores cadastrados, arquivos de sistema e bancos de dados.

A leitura de tamanhos (visão do disco) pode passar por qualquer lugar acessível;
estas regras decidem apenas o que é limpável.
"""

from __future__ import annotations

import ntpath
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

IS_WINDOWS = sys.platform == "win32"

DATABASE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".mdf", ".ldf", ".ndf", ".accdb", ".mdb")
# Atributos do Windows: arquivo de sistema; e arquivos "na nuvem" (OneDrive) que seriam baixados ao serem lidos.
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ATTRIBUTES = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


def norm(path: str | os.PathLike[str]) -> str:
    """Forma canônica para comparar caminhos (no Windows: sem diferença de maiúsculas)."""
    text = os.path.abspath(os.fspath(path))
    return os.path.normcase(os.path.normpath(text))


def clean(path: str | os.PathLike[str]) -> str:
    """Caminho absoluto e limpo, com as maiúsculas originais (para mostrar e guardar)."""
    return os.path.normpath(os.path.abspath(os.fspath(path)))


def unique(paths: Iterable[str]) -> list[str]:
    seen: dict[str, str] = {}
    for p in paths:
        seen.setdefault(norm(p), clean(p))
    return sorted(seen.values(), key=str.lower)


def is_within(path: str, root: str) -> bool:
    p, r = norm(path), norm(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def temp_dirs() -> list[str]:
    dirs = {tempfile.gettempdir()}
    if IS_WINDOWS and os.environ.get("LOCALAPPDATA"):
        dirs.add(os.path.join(os.environ["LOCALAPPDATA"], "Temp"))
    return unique(d for d in dirs if os.path.isdir(d))


def default_authorized() -> list[str]:
    downloads = Path.home() / "Downloads"
    return unique([*temp_dirs(), *([str(downloads)] if downloads.is_dir() else [])])


def _env_dirs(*names: str) -> list[str]:
    return [os.environ[n] for n in names if os.environ.get(n)]


@dataclass
class Protection:
    """Regras de proteção montadas uma vez por análise/limpeza."""

    roots: list[tuple[str, str]]  # (pasta, motivo)

    def reason(self, path: str, attributes: int = 0) -> str | None:
        for root, why in self.roots:
            if is_within(path, root):
                return why
        if attributes & FILE_ATTRIBUTE_SYSTEM:
            return "arquivo de sistema"
        if path.lower().endswith(DATABASE_SUFFIXES):
            return "banco de dados"
        return None


def build_protection(project_root: Path, data_dir: Path, server_dirs: Iterable[str]) -> Protection:
    roots: list[tuple[str, str]] = []
    if IS_WINDOWS:
        for d in _env_dirs("SystemRoot", "windir"):
            roots.append((d, "pasta do Windows"))
        for d in _env_dirs("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            roots.append((d, "programas instalados"))
        for d in _env_dirs("ProgramData"):
            roots.append((d, "dados de programas (ProgramData)"))
        for base in _env_dirs("APPDATA", "ProgramData"):
            roots.append((os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"), "pasta Inicializar"))
    else:
        for d in ("/bin", "/boot", "/etc", "/lib", "/lib64", "/opt", "/sbin", "/usr", "/var/lib", "/snap"):
            roots.append((d, "sistema"))
        roots.append((str(Path.home() / ".config" / "autostart"), "pasta Inicializar"))
    roots.append((str(project_root), "o próprio Sentinel"))
    roots.append((str(data_dir), "dados do Sentinel"))
    for d in server_dirs:
        if d:
            roots.append((d, "pasta de servidor cadastrado"))
    return Protection([(norm(r), why) for r, why in roots])


def server_directories(records: Iterable[object]) -> list[str]:
    """Pasta de trabalho, pasta do executável e pasta do log de cada servidor cadastrado."""
    dirname = ntpath.dirname if IS_WINDOWS else os.path.dirname
    out: list[str] = []
    for r in records:
        if getattr(r, "working_directory", None):
            out.append(r.working_directory)  # type: ignore[attr-defined]
        for file_path in (getattr(r, "executable", None), getattr(r, "log_path", None)):
            if file_path and dirname(file_path):
                out.append(dirname(file_path))
    return out


def check_authorizable(folder: str, protection: Protection) -> str | None:
    """Motivo para recusar uma pasta como autorizada (None = pode)."""
    path = norm(folder)
    if not os.path.isdir(path):
        return "pasta não encontrada"
    if os.path.dirname(path.rstrip(os.sep)) == path.rstrip(os.sep) or len(Path(path).parts) <= 1:
        return "não é permitido autorizar um disco inteiro"
    if norm(Path.home()) == path or norm(Path.home().parent) == path:
        return "não é permitido autorizar a pasta pessoal inteira; escolha uma subpasta"
    why = protection.reason(path)
    if why:
        return f"pasta protegida ({why})"
    # Subpastas protegidas dentro dela (ex.: um servidor em Downloads\\MeuServidor) continuam
    # intocáveis: a proteção é conferida arquivo a arquivo, na análise e de novo antes de mover.
    return None


def is_cloud_placeholder(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & CLOUD_ATTRIBUTES)


def file_attributes(st: os.stat_result) -> int:
    return int(getattr(st, "st_file_attributes", 0))


def is_link_like(entry: os.DirEntry[str]) -> bool:
    """Links, junções e pontos de nova análise: nunca seguidos (evita laços e saídas do escopo)."""
    try:
        if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
            return True
        st = entry.stat(follow_symlinks=False)
        return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT) or stat.S_ISLNK(st.st_mode)
    except OSError:
        return True
