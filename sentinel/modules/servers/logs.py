"""Leitura do final de arquivos de log de servidores (PRD 6.5).

O conteúdo é tratado como dado não confiável (PRD 17.6): devolvido como texto,
nunca interpretado. Só lê caminhos vindos do cadastro — a API não aceita caminho.
"""

from __future__ import annotations

from pathlib import Path

MAX_TAIL_BYTES = 256 * 1024


def tail_file(path: Path, lines: int = 200, max_bytes: int = MAX_TAIL_BYTES) -> dict[str, object]:
    lines = min(max(lines, 1), 2000)
    if not path.is_file():
        return {"path": str(path), "available": False, "reason": "arquivo não encontrado", "lines": []}
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read(max_bytes)
    except OSError as exc:
        return {"path": str(path), "available": False, "reason": f"não foi possível ler: {exc.strerror or exc}", "lines": []}
    text = data.decode("utf-8", errors="replace")
    all_lines = text.splitlines()
    if size > max_bytes and all_lines:
        all_lines = all_lines[1:]  # primeira linha provavelmente cortada no meio
    return {
        "path": str(path),
        "available": True,
        "size_bytes": size,
        "truncated": size > max_bytes or len(all_lines) > lines,
        "lines": [line[:2000] for line in all_lines[-lines:]],
    }
