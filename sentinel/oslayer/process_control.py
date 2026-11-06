"""Controle de processos de servidores, isolado por plataforma.

Iniciar: o servidor nasce **desacoplado** do Sentinel (PRD 2.4 e critério 12 do
MVP). No Windows o agente roda dentro do *job object* da tarefa agendada; um
filho comum morreria junto com ele. Usamos DETACHED_PROCESS +
CREATE_NEW_PROCESS_GROUP + CREATE_BREAKAWAY_FROM_JOB. Se o job não permitir
sair (ERROR_ACCESS_DENIED), iniciamos sem o breakaway e avisamos que o servidor
pode não sobreviver ao encerramento do Sentinel — nunca silenciosamente.

Encerrar: apenas a árvore de um processo já reconhecido como servidor, nunca
processos protegidos do sistema nem o próprio Sentinel.
"""

from __future__ import annotations

import logging
import ntpath
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psutil

log = logging.getLogger(__name__)

PROTECTED_NAMES = frozenset(
    {
        "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe",
        "lsaiso.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe", "memcompression",
        "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe", "spoolsv.exe", "taskhostw.exe", "sihost.exe",
        "systemd", "init", "launchd", "kthreadd", "sshd", "login",
    }
)


@dataclass(frozen=True, slots=True)
class LaunchResult:
    pid: int
    detached_from_job: bool  # False: pode encerrar junto com o Sentinel (Windows)
    warning: str | None = None
    # Em POSIX o servidor é filho do agente: se morrer, precisa ser "recolhido" (poll)
    # ou fica como zumbi. O gerente guarda o Popen para isso.
    popen: subprocess.Popen | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class StopResult:
    stopped: list[int]
    forced: list[int]
    still_alive: list[int]


def _windows_dir() -> str:
    return os.environ.get("SystemRoot", r"C:\Windows").lower()


def protection_reason(proc: psutil.Process) -> str | None:
    """Motivo pelo qual o processo não pode ser encerrado pelo Sentinel, ou None."""
    try:
        if proc.pid in (0, 4) or proc.pid == os.getpid() or proc.pid == os.getppid():
            return "processo do sistema ou do próprio Sentinel"
        name = (proc.name() or "").lower()
        if name in PROTECTED_NAMES:
            return f"'{name}' é um processo essencial do sistema"
        if not _alive(proc):
            return None  # zumbi: já terminou, nada a proteger
        try:
            exe = (proc.exe() or "").lower()
        except psutil.ZombieProcess:
            return None
        except psutil.AccessDenied:
            return "sem permissão para identificar o executável"
        if sys.platform == "win32" and exe.startswith(_windows_dir() + "\\"):
            return "executável dentro da pasta do Windows"
    except psutil.NoSuchProcess:
        return None
    return None


def launch_detached(executable: str, arguments: list[str], working_directory: str | None, log_file: Path) -> LaunchResult:
    """Inicia o servidor sem shell, com saída redirecionada para ``log_file``."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    _rotate(log_file)
    cwd = working_directory or str(Path(executable).parent)
    with open(log_file, "ab") as out:
        out.write(f"\n===== Iniciado pelo Sentinel ({executable}) =====\n".encode("utf-8", "replace"))
        out.flush()
        common = dict(
            args=[executable, *arguments],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            close_fds=True,
            shell=False,
        )
        if sys.platform == "win32":
            base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            breakaway = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
            try:
                proc = subprocess.Popen(creationflags=base | breakaway, **common)  # type: ignore[call-overload]
                return LaunchResult(proc.pid, True, popen=proc)
            except OSError as exc:
                if getattr(exc, "winerror", None) != 5:
                    raise
                proc = subprocess.Popen(creationflags=base, **common)  # type: ignore[call-overload]
                warning = (
                    "O Windows não permitiu desvincular o servidor do Sentinel (job object). "
                    "Ele pode ser encerrado se o Sentinel for encerrado à força."
                )
                log.warning(warning, extra={"pid": proc.pid})
                return LaunchResult(proc.pid, False, warning, popen=proc)
        proc = subprocess.Popen(start_new_session=True, **common)  # type: ignore[call-overload]
        return LaunchResult(proc.pid, True, popen=proc)


def terminate_tree(pid: int, timeout: float = 10.0) -> StopResult:
    """Encerra o processo e seus filhos (filhos primeiro). Força o que não sair no prazo.

    No Windows, processos sem console não recebem um pedido de encerramento
    "educado": terminate() equivale a encerrar imediatamente.
    """
    root = psutil.Process(pid)
    reason = protection_reason(root)
    if reason:
        raise PermissionError(f"Processo {pid} protegido: {reason}")
    try:
        children = root.children(recursive=True)
    except psutil.NoSuchProcess:
        return StopResult([], [], [])
    targets = [c for c in children if _alive(c) and protection_reason(c) is None] + [root]
    for proc in targets:
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            pass
    gone, alive = psutil.wait_procs(targets, timeout=timeout)
    forced: list[int] = []
    for proc in alive:
        try:
            proc.kill()
            forced.append(proc.pid)
        except psutil.NoSuchProcess:
            pass
    _, still = psutil.wait_procs(alive, timeout=5)
    return StopResult([p.pid for p in gone], forced, [p.pid for p in still])


def _alive(proc: psutil.Process) -> bool:
    try:
        return proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def listening_ports() -> dict[int, set[int | None]]:
    """Porta → PIDs escutando (TCP LISTEN e UDP). PID None quando o SO não informa."""
    result: dict[int, set[int | None]] = {}
    try:
        connections = psutil.net_connections(kind="inet")
    except psutil.AccessDenied:
        log.warning("Sem permissão para listar conexões de rede")
        return result
    for c in connections:
        if not c.laddr:
            continue
        if c.type == 1 and c.status != psutil.CONN_LISTEN:  # SOCK_STREAM sem LISTEN
            continue
        if c.type == 2 and c.raddr:  # UDP conectado não é "escutando"
            continue
        result.setdefault(c.laddr.port, set()).add(c.pid)
    return result


def normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    return ntpath.normcase(ntpath.normpath(path)) if sys.platform == "win32" else os.path.normpath(path)


def _rotate(log_file: Path, max_bytes: int = 10 * 1024 * 1024) -> None:
    """Rotação simples a cada início (o processo desacoplado mantém o arquivo aberto)."""
    try:
        if log_file.exists() and log_file.stat().st_size > max_bytes:
            backup = log_file.with_suffix(log_file.suffix + ".1")
            backup.unlink(missing_ok=True)
            log_file.rename(backup)
    except OSError as exc:
        log.warning("Não foi possível rotacionar o log do servidor", extra={"file": str(log_file), "error": str(exc)})
