"""Análise de armazenamento (PRD 8.2, 8.3) — somente leitura.

Uma única passada pelas pastas:
- **visão do disco** (opcional): tamanho das pastas até 3 níveis abaixo da raiz de
  cada disco e os maiores arquivos — só para informar;
- **pastas autorizadas**: temporários antigos, logs antigos e candidatos a
  duplicados, que podem virar um plano de limpeza.

Cuidados com o computador (PRD 8.3, 19):
- duplicados em três etapas: mesmo tamanho → mesmo começo e fim (128 KB lidos) →
  hash completo, com um limite de leitura de disco por análise;
- arquivos "na nuvem" (OneDrive) nunca são lidos, para não serem baixados;
- links e junções nunca são seguidos;
- pausa enquanto o computador está sob pressão severa e pequenas folgas para
  não monopolizar a CPU.
"""

from __future__ import annotations

import hashlib
import heapq
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from sentinel.modules.cleaner import scope
from sentinel.modules.cleaner.scope import Protection

LOG_NAME = re.compile(r"\.(log|log\.\d+|old)$", re.IGNORECASE)
TRACK_DEPTH = 3
TOP_LARGE = 50
TOP_DIRS = 30
PARTIAL_BYTES = 64 * 1024
CHUNK = 1024 * 1024


class AnalysisCancelled(Exception):
    pass


@dataclass(frozen=True)
class Options:
    large_bytes: int
    temp_age_seconds: float
    log_age_seconds: float
    duplicate_min_bytes: int
    max_hash_bytes: int
    disk_roots: tuple[str, ...] = ()  # vazio = sem visão do disco


@dataclass
class Finding:
    category: str  # temp | old_log | large | duplicate
    path: str
    size: int
    mtime: float
    group_key: str | None = None
    keep: bool = False
    cleanable: bool = True
    note: str | None = None


@dataclass
class Throttle:
    """Ritmo da análise: folga periódica, pausa sob pressão e cancelamento."""

    should_pause: Callable[[], bool] = lambda: False
    cancel: threading.Event = field(default_factory=threading.Event)
    every: int = 500
    nap: float = 0.01
    _count: int = 0

    def tick(self, progress: Callable[[], None] | None = None) -> None:
        self._count += 1
        if self._count % self.every:
            return
        if progress:
            progress()
        while self.should_pause() and not self.cancel.is_set():
            time.sleep(2)
        if self.cancel.is_set():
            raise AnalysisCancelled()
        time.sleep(self.nap)


@dataclass
class AnalysisResult:
    findings: list[Finding]
    summary: dict[str, Any]


class _State:
    def __init__(self) -> None:
        self.files = 0
        self.dirs = 0
        self.inaccessible = 0
        self.bytes_seen = 0
        self.dir_sizes: dict[str, int] = {}
        self.large: list[tuple[int, str, float]] = []  # heap mínima dos maiores
        self.by_size: dict[int, list[tuple[str, float]]] = {}
        self.findings: list[Finding] = []
        self.current = ""
        self.cloud_skipped = 0


def default_disk_roots() -> tuple[str, ...]:
    import psutil

    roots = []
    for part in psutil.disk_partitions(all=False):
        if scope.IS_WINDOWS and "fixed" not in part.opts:
            continue
        roots.append(part.mountpoint)
    return tuple(roots) if scope.IS_WINDOWS else ("/",)


def analyze(authorized: Iterable[str], protection: Protection, options: Options, throttle: Throttle | None = None,
            progress: Callable[[dict[str, Any]], None] | None = None, now: float | None = None) -> AnalysisResult:
    throttle = throttle or Throttle()
    now = time.time() if now is None else now
    started = time.monotonic()
    authorized = [scope.clean(a) for a in authorized if os.path.isdir(a)]
    temp_roots = scope.temp_dirs()
    st = _State()

    def report() -> None:
        if progress:
            progress({"files": st.files, "dirs": st.dirs, "bytes": st.bytes_seen, "current": st.current})

    def in_authorized(path: str) -> str | None:
        return next((a for a in authorized if scope.is_within(path, a)), None)

    def on_file(path: str, size: int, mtime: float, attrs: int, cloud: bool) -> None:
        st.files += 1
        st.bytes_seen += size
        protected = protection.reason(path, attrs)
        cleanable = in_authorized(path) is not None and protected is None
        categorized = False
        if cleanable:
            age = now - mtime
            if any(scope.is_within(path, t) for t in temp_roots) and age >= options.temp_age_seconds:
                st.findings.append(Finding("temp", path, size, mtime))
                categorized = True
            elif LOG_NAME.search(path) and age >= options.log_age_seconds:
                st.findings.append(Finding("old_log", path, size, mtime))
                categorized = True
            elif size >= options.duplicate_min_bytes and not cloud:
                st.by_size.setdefault(size, []).append((path, mtime))
        if size >= options.large_bytes and not categorized:
            item = (size, path, mtime)
            if len(st.large) < TOP_LARGE:
                heapq.heappush(st.large, item)
            elif size > st.large[0][0]:
                heapq.heapreplace(st.large, item)

    roots: list[str] = list(options.disk_roots)
    roots += [a for a in authorized if not any(scope.is_within(a, r) for r in roots)]
    for root in roots:
        _walk(root, on_file, st, throttle, report)

    for size, path, mtime in sorted(st.large, reverse=True):
        reason = protection.reason(path)
        cleanable = in_authorized(path) is not None and reason is None
        note = None if cleanable else (f"protegido: {reason}" if reason else "fora das pastas autorizadas")
        st.findings.append(Finding("large", path, size, mtime, cleanable=cleanable, note=note))

    hashed, budget_hit = _duplicates(st, options.max_hash_bytes, throttle, report)

    summary = _summary(st, roots, authorized, hashed, budget_hit, time.monotonic() - started)
    return AnalysisResult(st.findings, summary)


def _walk(root: str, on_file: Callable[[str, int, float, int, bool], None], st: _State, throttle: Throttle,
          report: Callable[[], None]) -> None:
    root_depth = len(Path(root).parts)
    stack: list[tuple[str, tuple[str, ...]]] = [(root, (root,))]
    while stack:
        folder, tracked = stack.pop()
        st.current = folder
        try:
            it = os.scandir(folder)
        except OSError:
            st.inaccessible += 1
            continue
        st.dirs += 1
        with it:
            for entry in it:
                throttle.tick(report)
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if scope.is_link_like(entry):
                            continue
                        depth = len(Path(entry.path).parts) - root_depth
                        stack.append((entry.path, tracked + (entry.path,) if depth <= TRACK_DEPTH else tracked))
                        continue
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        continue
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    st.inaccessible += 1
                    continue
                attrs = scope.file_attributes(info)
                cloud = scope.is_cloud_placeholder(info)
                if cloud:
                    st.cloud_skipped += 1
                    continue  # ocupa pouco ou nada localmente e ler baixaria da nuvem
                size = info.st_size
                for d in tracked:
                    st.dir_sizes[d] = st.dir_sizes.get(d, 0) + size
                on_file(entry.path, size, info.st_mtime, attrs, cloud)


def _read_partial(path: str, size: int) -> bytes:
    with open(path, "rb") as f:
        head = f.read(PARTIAL_BYTES)
        if size > 2 * PARTIAL_BYTES:
            f.seek(-PARTIAL_BYTES, os.SEEK_END)
            head += f.read(PARTIAL_BYTES)
    return head


def file_sha256(path: str, throttle: Throttle | None = None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for i, chunk in enumerate(iter(lambda: f.read(CHUNK), b"")):
            digest.update(chunk)
            if throttle and i % 32 == 31:
                throttle.tick()
    return digest.hexdigest()


def _duplicates(st: _State, max_bytes: int, throttle: Throttle, report: Callable[[], None]) -> tuple[int, bool]:
    """Agrupa conteúdos idênticos; o maior ganho primeiro, até o limite de leitura."""
    read = 0
    budget_hit = False
    for size in sorted((s for s, items in st.by_size.items() if len(items) > 1), reverse=True):
        candidates = st.by_size[size]
        partial: dict[bytes, list[tuple[str, float]]] = {}
        for path, mtime in candidates:
            try:
                key = hashlib.sha256(_read_partial(path, size)).digest()
            except OSError:
                continue
            read += min(size, 2 * PARTIAL_BYTES)
            partial.setdefault(key, []).append((path, mtime))
        for group in (g for g in partial.values() if len(g) > 1):
            if read + size * len(group) > max_bytes:
                budget_hit = True
                continue
            full: dict[str, list[tuple[str, float]]] = {}
            for path, mtime in group:
                st.current = path
                try:
                    digest = file_sha256(path, throttle) if size > 2 * PARTIAL_BYTES else hashlib.sha256(Path(path).read_bytes()).hexdigest()
                except OSError:
                    continue
                read += size
                full.setdefault(digest, []).append((path, mtime))
                throttle.tick(report)
            for digest, same in full.items():
                if len(same) < 2:
                    continue
                same.sort(key=lambda item: (item[1], len(item[0])))  # fica a cópia mais antiga
                for i, (path, mtime) in enumerate(same):
                    st.findings.append(Finding("duplicate", path, size, mtime, group_key=digest, keep=i == 0,
                                               cleanable=i != 0, note="cópia mantida (a mais antiga)" if i == 0 else None))
    return read, budget_hit


def _summary(st: _State, roots: list[str], authorized: list[str], hashed: int, budget_hit: bool, seconds: float) -> dict[str, Any]:
    categories: dict[str, dict[str, int]] = {}
    for f in st.findings:
        c = categories.setdefault(f.category, {"files": 0, "bytes": 0, "cleanable_files": 0, "cleanable_bytes": 0})
        c["files"] += 1
        c["bytes"] += f.size
        if f.cleanable:
            c["cleanable_files"] += 1
            c["cleanable_bytes"] += f.size
    top = sorted(((p, s) for p, s in st.dir_sizes.items() if p not in roots), key=lambda x: x[1], reverse=True)[:TOP_DIRS]
    warnings = []
    if budget_hit:
        warnings.append("limite de leitura para duplicados atingido: alguns grupos não foram comparados")
    if st.cloud_skipped:
        warnings.append(f"{st.cloud_skipped} arquivo(s) na nuvem (OneDrive) não foram lidos")
    if st.inaccessible:
        warnings.append(f"{st.inaccessible} pasta(s)/arquivo(s) sem permissão de leitura (normal em pastas do sistema)")
    return {
        "roots": [{"path": r, "bytes": st.dir_sizes.get(r, 0)} for r in roots],
        "authorized": authorized,
        "top_dirs": [{"path": p, "bytes": s} for p, s in top],
        "categories": categories,
        "recoverable_bytes": sum(c["cleanable_bytes"] for c in categories.values()),
        "files": st.files, "dirs": st.dirs, "bytes_seen": st.bytes_seen, "inaccessible": st.inaccessible,
        "hashed_bytes": hashed, "seconds": round(seconds, 1), "warnings": warnings,
    }
