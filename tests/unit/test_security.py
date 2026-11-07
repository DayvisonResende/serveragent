"""Fase 4: executor de ações e aprovações (PRD 23.3) e vigia da inicialização automática."""

import asyncio
import sqlite3
import time
from types import SimpleNamespace

import pytest

from sentinel.core.event_bus import EventBus
from sentinel.database.database import Database
from sentinel.database.migrations import apply_migrations
from sentinel.modules.security.actions import ActionService
from sentinel.modules.security.operations import ActionError, OperationSpec, Target
from sentinel.oslayer.autostart import AutostartEntry, assess


class FakeTargets:
    """Catálogo de teste: o 'cadastro' do alvo pode mudar para testar a revalidação."""

    def __init__(self):
        self.version = 1
        self.executed = []

    def catalog(self, risk=2):
        def resolve(target_id, params):
            if target_id == 404:
                raise ActionError("Servidor 404 não encontrado")
            return Target(target_id, f"srv{target_id}", f"v{self.version}")

        async def execute(target_id, params, actor, reason, approval_id):
            self.executed.append((target_id, actor, approval_id))
            return {"ok": True, "message": "feito"}

        return {"server_restart": OperationSpec("server_restart", "Reiniciar servidor", risk, "impacto", "riscos", resolve, execute)}


def run(scenario, tmp_path, risk=2, ttl=1800):
    async def runner():
        db = Database(tmp_path / "s.db")
        await db.open()
        await apply_migrations(db)
        bus = EventBus()
        targets = FakeTargets()
        service = ActionService(db, bus, targets.catalog(risk), ttl)
        try:
            return await scenario(service, targets, db, bus)
        finally:
            await db.close()

    return asyncio.run(runner())


def test_unknown_operation_is_refused(tmp_path):
    async def scenario(service, targets, db, bus):
        with pytest.raises(ActionError, match="não permitida"):
            await service.request("execute_command", 1, {"cmd": "format c:"}, "ia", "x", approval="user")
        assert targets.executed == []

    run(scenario, tmp_path)


def test_user_request_runs_immediately_and_is_recorded(tmp_path):
    async def scenario(service, targets, db, bus):
        action = await service.request("server_restart", 1, {}, "usuario:dashboard", "teste", approval="user")
        assert action["status"] == "completed" and action["decided_by"] == "usuario:dashboard"
        assert targets.executed == [(1, "usuario:dashboard", action["approval_id"])]

    run(scenario, tmp_path)


def test_sentinel_request_waits_for_approval_and_runs_once(tmp_path):
    async def scenario(service, targets, db, bus):
        pending = await service.request("server_restart", 1, {}, "sentinel:servidores", "caiu", approval="required")
        assert pending["status"] == "pending" and targets.executed == []
        again = await service.request("server_restart", 1, {}, "sentinel:servidores", "caiu de novo", approval="required")
        assert again["id"] == pending["id"]  # não duplica pedidos abertos
        done = await service.approve(pending["id"], "usuario:dashboard")
        assert done["status"] == "completed" and len(targets.executed) == 1
        with pytest.raises(ActionError, match="não podem ser reutilizadas"):
            await service.approve(pending["id"], "usuario:dashboard")
        assert len(targets.executed) == 1
        events = [bus._queue.get_nowait().event_type for _ in range(bus._queue.qsize())]
        assert "approval.requested" in events

    run(scenario, tmp_path)


def test_target_changed_after_request_invalidates_approval(tmp_path):
    async def scenario(service, targets, db, bus):
        pending = await service.request("server_restart", 1, {}, "sentinel:servidores", "caiu", approval="required")
        targets.version = 2  # cadastro alterado depois do pedido
        with pytest.raises(ActionError, match="mudou depois do pedido"):
            await service.approve(pending["id"], "usuario:dashboard")
        assert targets.executed == [] and (await service.get(pending["id"]))["status"] == "cancelled"

    run(scenario, tmp_path)


def test_expired_approval_cannot_be_used(tmp_path):
    async def scenario(service, targets, db, bus):
        pending = await service.request("server_restart", 1, {}, "sentinel:servidores", "caiu", approval="required")
        time.sleep(0.05)
        assert await service.expire_due() == [pending["id"]]
        with pytest.raises(ActionError):
            await service.approve(pending["id"], "usuario:dashboard")
        assert targets.executed == [] and (await service.get(pending["id"]))["status"] == "expired"

    run(scenario, tmp_path, ttl=0.01)


def test_reject_and_cancel(tmp_path):
    async def scenario(service, targets, db, bus):
        a = await service.request("server_restart", 1, {}, "sentinel:servidores", "x", approval="required")
        rejected = await service.reject(a["id"], "usuario:dashboard", "não agora")
        assert rejected["status"] == "rejected" and rejected["note"] == "não agora"
        b = await service.request("server_restart", 2, {}, "sentinel:servidores", "y", approval="required")
        cancelled = await service.cancel_pending("server_restart", 2, "voltou sozinho")
        assert cancelled["status"] == "cancelled"
        with pytest.raises(ActionError):
            await service.approve(b["id"], "usuario:dashboard")
        assert targets.executed == []

    run(scenario, tmp_path)


def test_critical_operation_requires_typed_confirmation(tmp_path):
    async def scenario(service, targets, db, bus):
        a = await service.request("server_restart", 7, {}, "usuario:dashboard", "x", approval="user")
        assert a["status"] == "pending" and a["requires_confirmation"]  # nível 3: nem o próprio usuário pula a confirmação
        with pytest.raises(ActionError, match="digite o nome"):
            await service.approve(a["id"], "usuario:dashboard", confirmation="errado")
        done = await service.approve(a["id"], "usuario:dashboard", confirmation="srv7")
        assert done["status"] == "completed"

    run(scenario, tmp_path, risk=3)


def test_missing_target_is_refused(tmp_path):
    async def scenario(service, targets, db, bus):
        with pytest.raises(ActionError, match="não encontrado"):
            await service.request("server_restart", 404, {}, "usuario:dashboard", "x", approval="user")

    run(scenario, tmp_path)


def test_audit_trail_cannot_be_edited(tmp_path):
    async def scenario(service, targets, db, bus):
        await service.request("server_restart", 1, {}, "usuario:dashboard", "teste", approval="user")
        conn = sqlite3.connect(tmp_path / "s.db")
        ops = [r[0] for r in conn.execute("SELECT operation FROM audit_logs ORDER BY id")]
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM audit_logs")
        conn.close()
        assert ops == ["action.request", "approval.approve"]

    run(scenario, tmp_path)


# ----------------------------------------------------- inicialização automática

def E(location, name, value):
    return AutostartEntry(location, name, value)


@pytest.mark.parametrize("entry", [
    E("HKLM\\Winlogon", "Shell", r'explorer.exe, "C:\Users\D\AppData\Local\google\chrome\user data\wzone.exe" "C:\Users\D\AppData\Local\google\chrome\user data\wtime.cmd" wlocale.cmd'),
    E("HKLM\\Winlogon", "Userinit", r"C:\Windows\system32\userinit.exe, C:\Users\Public\x.exe"),
    E("HKCU\\Run", "Windows Driver Foundation", r'"C:\Users\D\AppData\Local\x\Windows Driver Foundation (WDM).exe"'),
    E("Tarefa agendada", r"\Updater", r"powershell -w hidden -f C:\Users\D\AppData\Roaming\u.ps1"),
    E("HKLM\\IFEO", "sethc.exe", r"C:\Windows\System32\cmd.exe"),
    E("HKCU\\Command Processor\\AutoRun", "AutoRun", r"C:\x.bat"),
])
def test_known_malicious_patterns_are_flagged(entry):
    assert assess(entry)


@pytest.mark.parametrize("entry", [
    E("HKLM\\Winlogon", "Shell", "explorer.exe"),
    E("HKLM\\Winlogon", "Userinit", r"C:\Windows\system32\userinit.exe,"),
    E("Tarefa agendada", r"\Microsoft\Windows\Windows Defender\Windows Defender Cleanup", r"C:\ProgramData\Microsoft\Windows Defender\Platform\4.18\MpCmdRun.exe -IdleTask"),
    E("HKCU\\Run", "OneDrive", r'"C:\Users\D\AppData\Local\Microsoft\OneDrive\OneDrive.exe" /background'),
    E("HKCU\\Run", "Discord", r"C:\Users\D\AppData\Local\Discord\Update.exe --processStart Discord.exe"),
    E("HKLM\\Run", "RtHDVCpl", r'"C:\Program Files\Realtek\Audio\HDA\RtkNGUI64.exe" /s'),
    E("Inicializar (todos)", "AnyDesk.lnk", r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\AnyDesk.lnk (1000 bytes)"),
])
def test_common_legitimate_entries_are_not_flagged(entry):
    assert assess(entry) == []


def test_autostart_scan_baseline_then_detects_changes(tmp_path, monkeypatch):
    from sentinel.modules.security.module import SecurityModule
    from sentinel.oslayer import autostart

    snapshots = [
        [E("HKCU\\Run", "OneDrive", "onedrive.exe"), E("HKLM\\Winlogon", "Shell", r"explorer.exe, C:\Users\D\AppData\Local\x\w.cmd")],
        [E("HKCU\\Run", "OneDrive", "onedrive.exe"), E("HKLM\\Winlogon", "Shell", r"explorer.exe, C:\Users\D\AppData\Local\x\w.cmd"),
         E("HKCU\\Run", "Novo", r"C:\Users\D\AppData\Roaming\svchost.exe")],
        [E("HKLM\\Winlogon", "Shell", "explorer.exe"), E("HKCU\\Run", "Novo", r"C:\Users\D\AppData\Roaming\svchost.exe")],
    ]
    monkeypatch.setattr(autostart, "collect", lambda: (snapshots.pop(0), []))

    async def scenario():
        db = Database(tmp_path / "a.db")
        await db.open()
        await apply_migrations(db)
        bus = EventBus()
        module = SecurityModule(servers=None)  # type: ignore[arg-type]
        module._ctx = SimpleNamespace(event_bus=bus)
        from sentinel.database.repositories.autostart import AutostartRepository
        module._autostart_repo = AutostartRepository(db)
        results = []
        for _ in range(3):
            await module.scan_autostart()
            results.append([(e.title, e.severity.value) for e in (bus._queue.get_nowait() for _ in range(bus._queue.qsize()))])
        entries = await module.autostart_entries()
        await db.close()
        return results, entries

    (first, second, third), entries = asyncio.run(scenario())
    assert first[0][0].startswith("Linha de base") and any("suspeito" in t and s == "critical" for t, s in first)
    assert second == [("Novo item na inicialização automática: Novo", "critical")]  # novo e com nome de sistema
    assert ("Item da inicialização automática alterado: Shell", "warning") in third  # voltou ao normal: avisa, sem suspeita
    assert any(t.startswith("Item removido") for t, _ in third)
    shell = next(e for e in entries if e["name"] == "Shell")
    assert shell["value"] == "explorer.exe" and not shell["suspicious"]


def test_listed_actions_carry_readable_label(tmp_path):
    async def scenario(service, targets, db, bus):
        await service.request("server_restart", 1, {}, "sentinel:servidores", "caiu", approval="required")
        return await service.list("pending")

    assert run(scenario, tmp_path)[0]["label"] == "Reiniciar servidor"
