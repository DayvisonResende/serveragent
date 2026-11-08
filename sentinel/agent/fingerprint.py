"""Impressão digital do código instalado.

Os arquivos chegam ao Windows copiados à mão; quando algum fica para trás, o
relatório mostra comportamento antigo sem dizer por quê. Este código curto, igual
ao que o desenvolvedor vê na mesma versão, denuncia na hora a cópia incompleta.
Finais de linha são normalizados (CRLF = LF) para a cópia não alterar o resultado.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PATTERNS = ("sentinel/**/*.py", "dashboard/**/*.html", "dashboard/**/*.css", "dashboard/**/*.js",
            "scripts/*.ps1", "tests/**/*.py", "*.bat", "config/settings.yaml", "requirements*.txt")


def code_files(root: Path) -> list[Path]:
    files = {p for pattern in PATTERNS for p in root.glob(pattern) if p.is_file() and "__pycache__" not in p.parts}
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def fingerprint(root: Path) -> tuple[str, list[tuple[str, str]]]:
    """(código curto do conjunto, [(caminho, hash curto do arquivo)])."""
    rows = [(p.relative_to(root).as_posix(), file_digest(p)[:10]) for p in code_files(root)]
    total = hashlib.sha256("\n".join(f"{name} {digest}" for name, digest in rows).encode()).hexdigest()
    return total[:8], rows
