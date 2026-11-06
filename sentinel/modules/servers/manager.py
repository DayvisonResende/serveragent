"""Módulo de servidores: verificações periódicas, estados, incidentes e operações.

Operações (iniciar/parar/reiniciar) formam um conjunto fechado (PRD 11.5): não
existe execução genérica de comandos. Só servidores *gerenciados* aceitam
operações; *observados* (ex.: banco rodando como serviço do Windows) são apenas
monitorados. Paradas e reinícios pedidos pelo usuário não abrem incidente.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil

from sentinel.core.clock import to_iso, utc_now
from sentinel.core.event_bus import Event, Severity
from sentinel.core.exceptions import SentinelError
from sentinel.core.module_registry import Module, ModuleHealth
from sentinel.database.repositories.audit import AuditRepository
from sentinel.database.repositories.servers import ServerRepository
from sentinel.modules.monitor.processes import ProcessCollector, ProcessInfo
from sentinel.modules.monitor.store import MetricsStore, epoch_iso
from sentinel.modules.servers.health import HealthResult, Observation, check_health, evaluate
from sentinel.modules.servers.logs import tail_file
from sentinel.modules.servers.matching import MatchResult, confirm_alive, find_server_processes
from sentinel.modules.servers.models import BAD_STATES, ServerRecord, ServerState, validate_executable
from sentinel.oslayer.process_control import launch_detached, listening_ports, protection_reason, terminate_tree

if TYPE_CHECKING:
    from sentinel.core.context import AgentContext

log = logging.getLogger(__name__)

SOURCE = "servers"
ALLOWED_OPERATIONS = frozenset({"server_start", "server_stop", "server_restart"})
EVENT_STATE = "server.state_changed"
EVENT_RECOVERED = "server.recovered"
EVENT_OPERATION = "server.operation"

STATE_LABELS = {
    ServerState.ONLINE: "online",
    ServerState.OFFLINE: "offline",
    ServerState.STARTING: "inicializando",
    ServerState.RESTARTING: "reiniciando",
    ServerState.DEGRADED: "com problemas",
    ServerState.UNRESPONSIVE: "sem resposta",
    ServerState.UNKNOWN: "desconhecido",
    ServerState.DISABLED: "desativado",
}


class OperationError(SentinelError):
    """Operação recusada ou malsucedida, com motivo legível."""


class ServerNotFound(SentinelError):
    """Servidor inexistente."""


@dataclass
class ServerStatus:
    state: ServerState = ServerState.UNKNOWN
    since: float = field(default_factory=time.time)
    failures: int = 0
    health_verified: bool = False
    last_check: dict[str, Any] | None = None
    pids: list[int] = field(default_factory=list)
    main_pid: int | None = None
    process_started_at: str | None = None
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    incident_id: int | None = None
    operation: str | None = None
    planned_down: bool = False  # parado pelo usuário: não é incidente
    last_operation: dict[str, Any] | None = None
    warning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["state_label"] = STATE_LABELS[self.state]
        data["since"] = epoch_iso(self.since)
        return data


class ServersModule(Module):
    name = "servers"
    depends_on = ("monitor",)

    def __init__(self, store: MetricsStore) -> None:
        self._store = store
        self._ctx: AgentContext | None = None
        self._repo: ServerRepository | None = None
        self._audit: AuditRepository | None = None
        self._servers: dict[int, ServerRecord] = {}
        self._status: dict[int, ServerStatus] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._recent_ops: dict[int, deque[float]] = {}
        self._fresh = ProcessCollector()
        self._children: dict[int, Any] = {}  # PID → Popen dos servidores iniciados por nós
        self._jobs: list[str] = []

    # ------------------------------------------------------------ ciclo de vida

    async def start(self, context: AgentContext) -> None:
        self._ctx = context
        self._repo = ServerRepository(context.database)
        self._audit = AuditRepository(context.database)
        await self.reload()
        s = context.settings.servers
        context.scheduler.add_job("servers.check", self._check_all, s.check_interval_seconds, essential=True, run_immediately=True, timeout=60)
        context.scheduler.add_job("servers.retention", self._retention, 86_400, timeout=300)
        self._jobs = ["servers.check", "servers.retention"]

    async def stop(self) -> None:
        # Encerrar o Sentinel NUNCA encerra servidores (PRD 2.4): apenas paramos de observar.
        if self._ctx is None:
            return
        for name in self._jobs:
            try:
                await self._ctx.scheduler.remove_job(name)
            except SentinelError:
                log.warning("Tarefa já removida", extra={"job": name})

    def health(self) -> ModuleHealth:
        bad = [r.name for i, r in self._servers.items() if self._status[i].state in BAD_STATES]
        if bad:
            return ModuleHealth(True, f"{len(self._servers)} servidor(es); com problema: {', '.join(bad)}")
        return ModuleHealth(True, f"{len(self._servers)} servidor(es) cadastrado(s)")

    async def reload(self) -> None:
        """Relê o cadastro (após criar/alterar/excluir)."""
        assert self._repo is not None
        records = await self._repo.list()
        self._servers = {r.id: r for r in records}
        for rid in list(self._status):
            if rid not in self._servers:
                del self._status[rid]
        for record in records:
            if record.id not in self._status:
                status = ServerStatus()
                # Continuidade após reinício do agente: retoma o último estado e o incidente aberto,
                # para que um servidor parado de propósito não vire um "novo" incidente.
                last = await self._repo.recent_checks(record.id, 1)
                if last and last[0]["state"] in {s.value for s in (*BAD_STATES, ServerState.ONLINE)}:
                    status.state = ServerState(last[0]["state"])
                    status.since = last[0]["ts_epoch"]
                open_incident = await self._repo.open_incident_for(record.id)
                if open_incident:
                    status.incident_id = open_incident["id"]
                elif status.state is ServerState.OFFLINE:
                    status.planned_down = True  # offline sem incidente aberto = parado pelo usuário
                self._status[record.id] = status
                self._locks.setdefault(record.id, asyncio.Lock())

    # ------------------------------------------------------------- consultas

    def snapshot(self) -> list[dict[str, Any]]:
        return [self.describe(rid) for rid in sorted(self._servers, key=lambda i: self._servers[i].name.lower())]

    def describe(self, server_id: int) -> dict[str, Any]:
        record = self._servers.get(server_id)
        if record is None:
            raise ServerNotFound(f"Servidor {server_id} não encontrado")
        status = self._status[server_id]
        data = {"server": record.summary(), "status": status.as_dict()}
        if status.process_started_at and status.state not in (ServerState.OFFLINE, ServerState.DISABLED):
            data["status"]["uptime_seconds"] = round(time.time() - _parse_epoch(status.process_started_at))
        return data

    def counts(self) -> dict[str, int]:
        states = [self._status[i].state for i in self._servers]
        return {
            "total": len(states),
            "online": sum(s is ServerState.ONLINE for s in states),
            "offline": sum(s is ServerState.OFFLINE for s in states),
            "problems": sum(s in (ServerState.DEGRADED, ServerState.UNRESPONSIVE) for s in states),
        }

    def logs(self, server_id: int, source: str, lines: int) -> dict[str, Any]:
        record = self._servers.get(server_id)
        if record is None:
            raise ServerNotFound(f"Servidor {server_id} não encontrado")
        if source == "sentinel":
            return tail_file(self._capture_log(record), lines)
        if not record.log_path:
            return {"available": False, "reason": "nenhum arquivo de log configurado", "lines": []}
        return tail_file(Path(record.log_path), lines)

    # ----------------------------------------------------------- verificações

    async def _check_all(self) -> None:
        assert self._ctx is not None
        self._reap_children()
        if not self._servers:
            return
        listeners = await asyncio.to_thread(listening_ports)
        if self._store.processes_at is None:
            # Logo após iniciar, o monitor ainda não leu os processos: lê-se diretamente,
            # senão servidores em execução pareceriam ausentes.
            processes = await asyncio.to_thread(self._fresh.collect)
        else:
            processes = list(self._store.processes)
        sem = asyncio.Semaphore(self._ctx.settings.servers.check_concurrency)

        async def one(record: ServerRecord) -> None:
            async with sem:
                try:
                    await self._check_one(record, processes, listeners)
                except Exception:
                    log.exception("Falha ao verificar servidor", extra={"server": record.name})

        await asyncio.gather(*(one(r) for r in list(self._servers.values())))

    async def _check_one(self, record: ServerRecord, processes: list[ProcessInfo], listeners: dict[int, set[int | None]]) -> None:
        assert self._ctx is not None and self._repo is not None
        status = self._status[record.id]
        if status.operation:  # a operação em andamento controla o estado
            return
        if not record.enabled:
            await self._transition(record, status, ServerState.DISABLED, None)
            return
        match = await asyncio.to_thread(confirm_alive, find_server_processes(processes, record.effective_match(), record.port, listeners))
        health = await check_health(record.health_check, record.port, listeners) if match.alive else HealthResult("skipped")
        result = evaluate(status.state, status.failures, Observation(match.alive, health), self._ctx.settings.servers.failure_threshold)
        self._apply_match(status, match)
        status.failures = result.failures
        status.health_verified = result.health_verified
        if result.state is ServerState.ONLINE:
            status.planned_down = False
        error = health.error if match.alive else "nenhum processo do servidor encontrado"
        threshold = self._ctx.settings.servers.failure_threshold
        if error and result.state not in BAD_STATES and result.failures:
            error = f"{error} (falha {result.failures}/{threshold}, aguardando confirmação)"
        status.last_check = {
            "timestamp": to_iso(utc_now()),
            "ts_epoch": time.time(),
            "state": result.state.value,
            "process_alive": match.alive,
            "pid": match.main_pid,
            "port_listening": health.port_listening,
            "health_status": health.status,
            "response_time_ms": health.response_time_ms,
            "error": error,
        }
        await self._transition(record, status, result.state, status.last_check["error"])
        await self._repo.add_check(record.id, status.last_check)

    def _apply_match(self, status: ServerStatus, match: MatchResult) -> None:
        status.pids, status.main_pid = match.pids, match.main_pid
        cpus = [p.cpu_percent for p in match.processes if p.cpu_percent is not None]
        mems = [p.memory_bytes for p in match.processes if p.memory_bytes is not None]
        status.cpu_percent = round(sum(cpus), 1) if cpus else None
        status.memory_bytes = sum(mems) if mems else None
        main = next((p for p in match.processes if p.pid == match.main_pid), None)
        status.process_started_at = main.started_at if main else None

    async def _transition(self, record: ServerRecord, status: ServerStatus, new: ServerState, error: str | None, planned: bool = False) -> None:
        assert self._repo is not None
        old = status.state
        if new is old:
            return
        status.state, status.since = new, time.time()
        entry = {"at": to_iso(utc_now()), "state": new.value, "detail": error}
        log.info("Estado do servidor alterado", extra={"server": record.name, "from": old.value, "to": new.value})

        if planned or (status.planned_down and new is ServerState.OFFLINE):
            return  # mudança pedida pelo usuário: registrada pela própria operação

        if new in BAD_STATES:
            severity = _severity(record, new)
            title = f"Servidor '{record.name}' {STATE_LABELS[new]}"
            if status.incident_id is None:
                status.incident_id = await self._repo.open_incident(record, new.value, severity.value, title, entry)
            else:
                await self._repo.append_incident(status.incident_id, entry)
            self._publish(EVENT_STATE, severity, title, error or "", record, {"from": old.value, "to": new.value, "incident_id": status.incident_id})
        elif new is ServerState.ONLINE and status.incident_id is not None:
            duration = await self._repo.close_incident(status.incident_id, "recuperado", entry)
            incident, status.incident_id = status.incident_id, None
            self._publish(
                EVENT_RECOVERED, Severity.INFO, f"Servidor '{record.name}' voltou a responder",
                f"Indisponível por {_duration(duration)}." if duration else "", record, {"incident_id": incident},
            )
        elif new is ServerState.DISABLED and status.incident_id is not None:
            await self._repo.close_incident(status.incident_id, "monitoramento desativado", entry)
            status.incident_id = None

    # -------------------------------------------------------------- operações

    async def execute(self, operation: str, server_id: int, actor: str, reason: str | None = None) -> dict[str, Any]:
        """Executa uma operação permitida, com validação, limite de frequência e auditoria."""
        assert self._ctx is not None and self._audit is not None
        if operation not in ALLOWED_OPERATIONS:
            raise OperationError(f"Operação não permitida: {operation}")
        record = self._servers.get(server_id)
        if record is None:
            raise ServerNotFound(f"Servidor {server_id} não encontrado")
        status = self._status[server_id]
        lock = self._locks[server_id]
        if lock.locked():
            raise OperationError(f"Já existe uma operação em andamento para '{record.name}'")

        try:
            self._check_allowed(record)
            self._check_rate(record)
        except OperationError as exc:
            # Recusa antes de qualquer ação: auditada, e devolvida como erro ao solicitante.
            await self._audit.record(actor=actor, operation=operation, target=record.name, reason=reason,
                                     result="refused", details={"message": str(exc)})
            raise

        async with lock:
            started = time.time()
            try:
                handler = {"server_start": self._start, "server_stop": self._stop, "server_restart": self._restart}[operation]
                message, details = await handler(record, status)
                ok = True
            except OperationError as exc:
                message, details, ok = str(exc), {}, False
            except Exception as exc:
                log.exception("Erro inesperado na operação", extra={"server": record.name, "operation": operation})
                message, details, ok = f"Erro inesperado: {type(exc).__name__}: {exc}", {}, False
            finally:
                status.operation = None

            result = {
                "ok": ok,
                "operation": operation,
                "server": record.name,
                "message": message,
                "state": status.state.value,
                "pid": status.main_pid,
                "duration_seconds": round(time.time() - started, 1),
                "warning": details.get("warning"),
            }
            status.last_operation = {**result, "at": to_iso(utc_now()), "actor": actor}
            await self._audit.record(
                actor=actor, operation=operation, target=record.name, reason=reason,
                result="success" if ok else "failed", details={**details, "message": message},
            )
            self._publish(
                EVENT_OPERATION, Severity.INFO if ok else Severity.HIGH,
                f"{_OP_LABELS[operation]} '{record.name}': {'concluído' if ok else 'falhou'}", message, record,
                {"operation": operation, "ok": ok, "actor": actor},
            )
            return result

    def _check_allowed(self, record: ServerRecord) -> None:
        if record.management != "managed":
            raise OperationError(f"'{record.name}' é apenas observado; o Sentinel não o inicia nem o encerra")
        if not record.enabled:
            raise OperationError(f"'{record.name}' está desativado")

    def _check_rate(self, record: ServerRecord) -> None:
        assert self._ctx is not None
        s = self._ctx.settings.servers
        recent = self._recent_ops.setdefault(record.id, deque())
        now = time.monotonic()
        while recent and now - recent[0] > s.operations_window_seconds:
            recent.popleft()
        if len(recent) >= s.operations_per_window:
            raise OperationError(
                f"Limite de {s.operations_per_window} operações em {s.operations_window_seconds / 60:.0f} min atingido "
                f"para '{record.name}' (proteção contra ciclos de reinício)"
            )
        recent.append(now)

    async def _start(self, record: ServerRecord, status: ServerStatus) -> tuple[str, dict[str, Any]]:
        match = await self._fresh_match(record)
        if match.alive:
            raise OperationError(f"'{record.name}' já está em execução (PID {match.main_pid})")
        try:
            validate_executable(record.executable or "", check_exists=True)
        except ValueError as exc:
            raise OperationError(str(exc)) from exc
        if record.working_directory and not Path(record.working_directory).is_dir():
            raise OperationError(f"Diretório de trabalho não encontrado: {record.working_directory}")

        status.operation = "server_start"
        if status.state is not ServerState.RESTARTING:
            await self._transition(record, status, ServerState.STARTING, None, planned=True)
        status.planned_down = False
        launch = await asyncio.to_thread(
            launch_detached, record.executable or "", record.arguments, record.working_directory, self._capture_log(record)
        )
        status.warning = launch.warning
        if launch.popen is not None:
            self._children[launch.pid] = launch.popen
        log.info("Servidor iniciado", extra={"server": record.name, "pid": launch.pid, "detached": launch.detached_from_job})
        healthy, detail = await self._wait_healthy(record, status, launch.pid, record.startup_grace_seconds)
        details = {"pid": launch.pid, "detached_from_job": launch.detached_from_job, "warning": launch.warning}
        if not healthy:
            raise OperationError(detail)
        return f"'{record.name}' iniciado e respondendo (PID {status.main_pid})", details

    async def _stop(self, record: ServerRecord, status: ServerStatus, planned_state: ServerState = ServerState.OFFLINE) -> tuple[str, dict[str, Any]]:
        assert self._ctx is not None
        match = await self._fresh_match(record)
        if not match.alive:
            raise OperationError(f"'{record.name}' não está em execução")
        if match.too_broad:
            raise OperationError(f"O critério de reconhecimento de '{record.name}' encontrou {len(match.pids)} processos; refine-o antes de parar")
        roots = [p for p in match.processes if p.ppid not in set(match.pids)]
        for proc in roots:
            try:
                reason = protection_reason(psutil.Process(proc.pid), record.executable if record.is_script else None)
            except psutil.NoSuchProcess:
                continue
            if reason:
                raise OperationError(f"Recusado: PID {proc.pid} — {reason}")
        status.operation = status.operation or "server_stop"
        status.planned_down = True
        stopped, forced = [], []
        for proc in roots:
            try:
                res = await asyncio.to_thread(
                    terminate_tree, proc.pid, self._ctx.settings.servers.stop_timeout_seconds,
                    record.executable if record.is_script else None,
                )
            except psutil.NoSuchProcess:
                continue
            except PermissionError as exc:
                raise OperationError(str(exc)) from exc
            if res.still_alive:
                raise OperationError(f"Processos não encerraram: {res.still_alive}")
            stopped += res.stopped
            forced += res.forced
        after = await self._fresh_match(record)
        if after.alive:
            raise OperationError(f"'{record.name}' continua em execução (PID {after.main_pid})")
        self._apply_match(status, after)
        await self._transition(record, status, planned_state, "parado pelo usuário", planned=True)
        if planned_state is ServerState.OFFLINE and status.incident_id is not None:
            assert self._repo is not None
            await self._repo.close_incident(status.incident_id, "parado pelo usuário", {"at": to_iso(utc_now()), "state": "offline", "detail": "parado pelo usuário"})
            status.incident_id = None
        details = {"stopped_pids": stopped, "forced_pids": forced}
        return f"'{record.name}' parado" + (f" (encerramento forçado: {forced})" if forced else ""), details

    async def _restart(self, record: ServerRecord, status: ServerStatus) -> tuple[str, dict[str, Any]]:
        status.operation = "server_restart"
        await self._transition(record, status, ServerState.RESTARTING, None, planned=True)
        details: dict[str, Any] = {}
        if (await self._fresh_match(record)).alive:
            _, stop_details = await self._stop(record, status, planned_state=ServerState.RESTARTING)
            details.update(stop_details)
        message, start_details = await self._start(record, status)
        details.update(start_details)
        return message.replace("iniciado", "reiniciado"), details

    async def _wait_healthy(self, record: ServerRecord, status: ServerStatus, launched_pid: int, grace: float) -> tuple[bool, str]:
        deadline = time.monotonic() + grace
        last_error = "sem resposta"
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            listeners = await asyncio.to_thread(listening_ports)
            match = await self._fresh_match(record, listeners)
            launched_alive = psutil.pid_exists(launched_pid)
            if not match.alive and not launched_alive:
                await self._transition(record, status, ServerState.OFFLINE, "encerrou logo após iniciar")
                tail = tail_file(self._capture_log(record), 5)
                lines = " | ".join(tail.get("lines", [])[-5:])  # type: ignore[arg-type]
                return False, f"'{record.name}' encerrou logo após iniciar. Últimas linhas do log: {lines or '(vazio)'}"
            if not match.alive:
                continue
            health = await check_health(record.health_check, record.port, listeners)
            self._apply_match(status, match)
            if health.status in ("ok", "skipped"):
                status.failures = 0
                status.health_verified = health.status == "ok"
                await self._transition(record, status, ServerState.ONLINE, None)
                return True, ""
            last_error = health.error or health.status
        await self._transition(record, status, ServerState.UNRESPONSIVE, last_error)
        return False, f"'{record.name}' não ficou saudável em {grace:.0f}s ({last_error})"

    def _reap_children(self) -> None:
        """Recolhe servidores iniciados por nós que já terminaram (evita zumbis em POSIX)."""
        for pid, popen in list(self._children.items()):
            if popen.poll() is not None:
                del self._children[pid]

    async def _fresh_match(self, record: ServerRecord, listeners: dict[int, set[int | None]] | None = None) -> MatchResult:
        """Leitura imediata dos processos (o store pode estar até 15 s atrasado)."""
        self._reap_children()
        processes = await asyncio.to_thread(self._fresh.collect)
        if listeners is None:
            listeners = await asyncio.to_thread(listening_ports) if record.port else {}
        return find_server_processes(processes, record.effective_match(), record.port, listeners)

    def _capture_log(self, record: ServerRecord) -> Path:
        assert self._ctx is not None
        return self._ctx.settings.paths.log_dir / "servers" / f"server-{record.id}.log"

    async def _retention(self) -> None:
        assert self._repo is not None and self._ctx is not None
        removed = await self._repo.purge_checks(time.time() - self._ctx.settings.retention.server_checks_days * 86_400)
        log.info("Retenção de verificações de servidores aplicada", extra={"removed": removed})

    def _publish(self, event_type: str, severity: Severity, title: str, description: str, record: ServerRecord, meta: dict[str, Any]) -> None:
        assert self._ctx is not None
        self._ctx.event_bus.publish(
            Event(event_type=event_type, source=SOURCE, severity=severity, title=title, description=description,
                  metadata={"server_id": record.id, "server": record.name, **meta})
        )


_OP_LABELS = {"server_start": "Iniciar", "server_stop": "Parar", "server_restart": "Reiniciar"}


def _severity(record: ServerRecord, state: ServerState) -> Severity:
    if state is ServerState.DEGRADED:
        return Severity.WARNING
    return {"critical": Severity.CRITICAL, "high": Severity.HIGH}.get(record.criticality, Severity.WARNING)


def _duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def _parse_epoch(iso: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(iso).timestamp()
