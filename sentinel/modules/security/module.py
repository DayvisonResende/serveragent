"""Módulo de segurança (PRD 11): executor de ações com aprovações, propostas de
recuperação e vigilância da inicialização automática."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Callable

from sentinel.core.event_bus import Event, Severity
from sentinel.core.module_registry import Module, ModuleHealth
from sentinel.database.repositories.autostart import AutostartRepository
from sentinel.modules.security.actions import ActionService
from sentinel.modules.security.operations import ActionError, server_operations
from sentinel.oslayer import autostart

if TYPE_CHECKING:
    from sentinel.core.context import AgentContext
    from sentinel.modules.servers.manager import ServersModule

log = logging.getLogger(__name__)

PROPOSER = "sentinel:servidores"
EVENT_AUTOSTART = "security.autostart_changed"
EVENT_AUTOSTART_BASELINE = "security.autostart_baseline"
STATE_LABEL = {"offline": "offline", "unresponsive": "sem resposta"}


class SecurityModule(Module):
    name = "security"
    depends_on = ("servers",)

    def __init__(self, servers: ServersModule) -> None:
        self._servers = servers
        self._ctx: AgentContext | None = None
        self.actions: ActionService | None = None
        self._unsubscribe: list[Callable[[], None]] = []
        self._autostart_repo: AutostartRepository | None = None
        self.autostart_status: dict[str, Any] = {"last_scan": None, "errors": [], "entries": 0, "suspicious": 0}
        self._scan_lock = asyncio.Lock()

    async def start(self, context: AgentContext) -> None:
        self._ctx = context
        s = context.settings.security
        self.actions = ActionService(context.database, context.event_bus, server_operations(self._servers), s.approval_ttl_minutes * 60)
        self._servers.set_restart_runner(self.restart_by_policy)
        self._autostart_repo = AutostartRepository(context.database)
        for event_type in ("server.state_changed", "server.auto_restart", "server.recovered"):
            self._unsubscribe.append(context.event_bus.subscribe(event_type, self._on_server_event))
        context.scheduler.add_job("security.expire_approvals", self._expire, 30, essential=True, timeout=30)
        context.scheduler.add_job("security.autostart", self.scan_autostart, s.autostart_scan_minutes * 60,
                                  timeout=180, run_immediately=True)

    async def stop(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        if self._ctx is not None:
            for job in ("security.expire_approvals", "security.autostart"):
                try:
                    await self._ctx.scheduler.remove_job(job)
                except Exception:
                    log.warning("Tarefa já removida", extra={"job": job})

    def health(self) -> ModuleHealth:
        errors = self.autostart_status["errors"]
        detail = f"{self.autostart_status['entries']} itens de inicialização vigiados"
        if self.autostart_status["suspicious"]:
            detail += f"; {self.autostart_status['suspicious']} suspeito(s)"
        if errors:
            detail += f"; fontes com erro: {len(errors)}"
        return ModuleHealth(True, detail)

    # --------------------------------------------------------------- ações

    async def restart_by_policy(self, server_id: int, actor: str, reason: str) -> dict[str, Any]:
        """Reinício automático: mesma via das demais ações, aprovado pela política do usuário."""
        assert self.actions is not None
        try:
            action = await self.actions.request("server_restart", server_id, {}, actor, reason, approval="policy")
        except ActionError as exc:
            return {"ok": False, "message": str(exc)}
        result = action.get("result") or {}
        return {"ok": action["status"] == "completed", "message": result.get("message") or action.get("error_message") or action["status"]}

    async def _on_server_event(self, event: Event) -> None:
        assert self._ctx is not None and self.actions is not None
        meta = event.metadata
        server_id = meta.get("server_id")
        if server_id is None:
            return
        if event.event_type == "server.recovered":
            await self.actions.cancel_pending("server_restart", server_id, "o servidor voltou a responder")
            return
        if not self._ctx.settings.security.propose_server_restart:
            return
        if event.event_type == "server.state_changed" and meta.get("to") in STATE_LABEL:
            await self._propose(server_id, f"'{meta.get('server')}' ficou {STATE_LABEL[meta['to']]} ({event.description or 'sem detalhes'}).")
        elif event.event_type == "server.auto_restart" and "esgotado" in event.title:
            await self._propose(server_id, f"O reinício automático de '{meta.get('server')}' esgotou as tentativas. Tentar mais uma vez?")

    async def _propose(self, server_id: int, reason: str) -> None:
        """PRD 6.6 passo 6: sem política que cubra o caso, o Sentinel pede aprovação para reiniciar."""
        assert self.actions is not None
        record = self._servers.get_record(server_id)
        status = self._servers.get_status(server_id)
        if record is None or status is None or record.management != "managed" or not record.enabled:
            return
        policy = record.restart_policy
        if policy.enabled and not status.auto_restart_exhausted and status.state.value in policy.on_states:
            return  # a política autorizada cuida disso sozinha
        try:
            await self.actions.request("server_restart", server_id, {}, PROPOSER, reason, approval="required")
        except ActionError as exc:
            log.warning("Não foi possível propor reinício", extra={"server_id": server_id, "error": str(exc)})

    async def _expire(self) -> None:
        assert self.actions is not None
        await self.actions.expire_due()

    # ------------------------------------------- inicialização automática

    async def scan_autostart(self) -> dict[str, Any]:
        """Compara os itens atuais com a linha de base e avisa sobre mudanças (PRD 11 / segurança)."""
        assert self._ctx is not None and self._autostart_repo is not None
        async with self._scan_lock:
            entries, errors = await asyncio.to_thread(autostart.collect)
            baseline = await self._autostart_repo.all()
            current = {e.key: e for e in entries}
            first_scan = not baseline
            upserts, seen, changes = [], [], []
            for key, entry in current.items():
                reasons = autostart.assess(entry)
                old = baseline.get(key)
                row = {"key": key, "location": entry.location, "name": entry.name, "value": entry.value, "reasons": reasons}
                if old is None:
                    upserts.append(row)
                    if not first_scan:
                        changes.append(("added", row, None))
                elif old["value"] != entry.value or old["reasons"] != reasons:
                    upserts.append(row)
                    changes.append(("changed", row, old["value"]))
                else:
                    seen.append(key)
                if first_scan and reasons:
                    changes.append(("suspicious", row, None))
            removed = [k for k in baseline if k not in current] if not errors else []  # fonte falhou: não conclui remoção
            await self._autostart_repo.apply(upserts, removed, seen)

            if first_scan:
                self._publish(EVENT_AUTOSTART_BASELINE, Severity.INFO, "Linha de base da inicialização automática registrada",
                              f"{len(current)} itens vigiados. A partir de agora, mudanças geram alerta.", {"entries": len(current)})
            for kind, row, old_value in changes:
                self._report(kind, row, old_value)
            for key in removed:
                old = baseline[key]
                self._publish(EVENT_AUTOSTART, Severity.INFO, f"Item removido da inicialização: {old['name']}",
                              f"{old['location']}: {old['value'][:300]}", {"location": old["location"], "name": old["name"], "change": "removed"})

            self.autostart_status = {
                "last_scan": time.time(), "errors": errors, "entries": len(current),
                "suspicious": sum(1 for e in current.values() if autostart.assess(e)),
            }
            return self.autostart_status

    async def autostart_entries(self) -> list[dict[str, Any]]:
        assert self._autostart_repo is not None
        return list((await self._autostart_repo.all()).values())

    def _report(self, kind: str, row: dict[str, Any], old_value: str | None) -> None:
        suspicious = bool(row["reasons"])
        why = (" Motivo: " + "; ".join(row["reasons"]) + ".") if suspicious else ""
        if kind == "suspicious":
            title, severity = f"Item suspeito na inicialização automática: {row['name']}", Severity.CRITICAL
            description = f"{row['location']}: {row['value'][:400]}.{why}"
        elif kind == "added":
            title = f"Novo item na inicialização automática: {row['name']}"
            severity = Severity.CRITICAL if suspicious else Severity.WARNING
            description = f"{row['location']}: {row['value'][:400]}.{why} Se você não instalou nada agora, investigue."
        else:
            title = f"Item da inicialização automática alterado: {row['name']}"
            severity = Severity.CRITICAL if suspicious else Severity.WARNING
            description = f"{row['location']}: antes '{(old_value or '')[:200]}', agora '{row['value'][:200]}'.{why}"
        self._publish(EVENT_AUTOSTART, severity, title, description,
                      {"location": row["location"], "name": row["name"], "change": kind, "reasons": row["reasons"]})

    def _publish(self, event_type: str, severity: Severity, title: str, description: str, meta: dict[str, Any]) -> None:
        assert self._ctx is not None
        self._ctx.event_bus.publish(Event(event_type=event_type, source="security", severity=severity, title=title,
                                          description=description, metadata=meta))
