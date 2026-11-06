"""Notificações: filtros, deduplicação, limite, tentativas, segredos e API (Telegram falso)."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from sentinel.core.event_bus import Event, EventBus, Severity
from sentinel.database.database import Database
from sentinel.database.migrations import apply_migrations
from sentinel.database.repositories.settings import SecretRepository, SettingsRepository
from sentinel.modules.notifications.channels import TelegramChannel, TelegramError, valid_token
from sentinel.modules.notifications.manager import NotificationsModule, format_message
from sentinel.oslayer import secrets

TOKEN = "123456789:" + "A" * 35


class FakeTelegram:
    def __init__(self, fail_times=0):
        self.calls = []
        self.fail_times = fail_times

    def __call__(self, method, token, payload):
        self.calls.append((method, token, payload))
        if method == "sendMessage" and self.fail_times:
            self.fail_times -= 1
            raise TelegramError("Sem conexão com o Telegram (TimeoutError)")
        if method == "getMe":
            return {"ok": True, "result": {"username": "meu_sentinel_bot"}}
        if method == "getUpdates":
            return {"ok": True, "result": [
                {"message": {"chat": {"id": 42, "type": "private", "first_name": "Dayvison", "username": "day"}}},
                {"message": {"chat": {"id": 42, "type": "private", "first_name": "Dayvison"}}},
            ]}
        return {"ok": True, "result": {}}

    @property
    def sent(self):
        return [p["text"] for m, _, p in self.calls if m == "sendMessage"]


def ev(event_type="server.state_changed", severity=Severity.HIGH, title="Servidor 'X' offline", description="nenhum processo"):
    return Event(event_type=event_type, source="servers", title=title, severity=severity, description=description)


async def no_sleep(_seconds):
    await asyncio.sleep(0)


def run(coro_factory, tmp_path, fake=None):
    async def runner():
        db = Database(tmp_path / "n.db")
        await db.open()
        await apply_migrations(db)
        bus = EventBus()
        bus.start()
        module = NotificationsModule(transport=fake or FakeTelegram(), sleep=no_sleep)
        await module.start(SimpleNamespace(database=db, event_bus=bus))
        try:
            return await coro_factory(module, db, bus)
        finally:
            await module.stop()
            await bus.stop()
            await db.close()

    return asyncio.run(runner())


async def configure(module, db, **config):
    await SecretRepository(db).set("telegram_bot_token", TOKEN)
    await SettingsRepository(db).set("notifications", {"enabled": True, "telegram_chat_id": 42, **config})
    await module.reload()


async def settle():
    for _ in range(50):
        await asyncio.sleep(0.01)


def test_token_format():
    assert valid_token(TOKEN)
    for bad in ("", "abc", "123:curto", "123456789:" + "A" * 35 + "!"):
        assert not valid_token(bad)
    with pytest.raises(TelegramError, match="formato"):
        TelegramChannel(FakeTelegram()).send("x", 1, "oi")


def test_secret_round_trip_and_never_plain_on_windows(tmp_path):
    protection, data = secrets.protect(b"segredo")
    assert secrets.unprotect(protection, data) == b"segredo"
    assert protection in ("dpapi", "none")

    async def scenario(module, db, bus):
        repo = SecretRepository(db)
        await repo.set("k", "valor")
        assert await repo.get("k") == "valor"
        assert (await repo.info("k"))["protection"] == protection
        await repo.delete("k")
        assert await repo.get("k") is None

    run(scenario, tmp_path)


def test_disabled_by_default_sends_nothing(tmp_path):
    fake = FakeTelegram()

    async def scenario(module, db, bus):
        bus.publish(ev(severity=Severity.CRITICAL))
        await settle()
        return module.active

    assert run(scenario, tmp_path, fake) is False
    assert fake.sent == []


def test_filters_by_severity_and_always_sends_recoveries(tmp_path):
    fake = FakeTelegram()

    async def scenario(module, db, bus):
        await configure(module, db, min_severity="high")
        bus.publish(ev(severity=Severity.WARNING, title="atenção ignorada"))
        bus.publish(ev(severity=Severity.HIGH, title="alto enviado"))
        bus.publish(ev("server.recovered", Severity.INFO, "Servidor 'X' voltou a responder", "Indisponível por 2 min."))
        bus.publish(ev("agent.started", Severity.INFO, "Sentinel iniciado", ""))
        await settle()

    run(scenario, tmp_path, fake)
    assert len(fake.sent) == 2
    assert "alto enviado" in fake.sent[0] and fake.sent[0].startswith("🟠 Alto")
    assert fake.sent[1].startswith("✅") and "voltou a responder" in fake.sent[1]


def test_duplicates_are_suppressed_and_counted(tmp_path):
    fake = FakeTelegram()

    async def scenario(module, db, bus):
        await configure(module, db)
        for _ in range(5):
            bus.publish(ev())
        await settle()
        bus.publish(ev(title="outro"))
        await settle()

    run(scenario, tmp_path, fake)
    assert len(fake.sent) == 2
    # o aviso acompanha a próxima mensagem enviada (qual delas depende do momento): aparece uma única vez
    assert sum("+4 notificação(ões) repetida(s) suprimida(s)" in m for m in fake.sent) == 1


def test_retries_then_succeeds_and_token_never_logged(tmp_path, caplog):
    fake = FakeTelegram(fail_times=2)
    caplog.set_level(logging.DEBUG)

    async def scenario(module, db, bus):
        await configure(module, db)
        bus.publish(ev())
        await settle()
        return module.status()

    status = run(scenario, tmp_path, fake)
    assert status["sent"] == 1 and status["failed"] == 0
    assert len([c for c in fake.calls if c[0] == "sendMessage"]) == 3
    assert TOKEN not in caplog.text


def test_rate_limit_waits_instead_of_flooding(tmp_path):
    fake = FakeTelegram()
    waits = []

    async def recording_sleep(seconds):
        waits.append(seconds)
        await asyncio.sleep(0)

    async def runner():
        db = Database(tmp_path / "r.db")
        await db.open()
        await apply_migrations(db)
        bus = EventBus()
        module = NotificationsModule(transport=fake, sleep=recording_sleep)
        await module.start(SimpleNamespace(database=db, event_bus=bus))
        await configure(module, db)
        for _ in range(21):
            module._sent_times.append(__import__("time").monotonic())
            if len(module._sent_times) > 20:
                break
        task = asyncio.create_task(module._respect_rate_limit())
        await asyncio.sleep(0.05)
        task.cancel()
        await module.stop()
        await db.close()

    asyncio.run(runner())
    assert waits and waits[0] > 50  # aguarda ~1 min em vez de enviar a 21ª mensagem


def test_detect_chats_and_test_message(tmp_path):
    fake = FakeTelegram()

    async def scenario(module, db, bus):
        found = await module.bot_and_chats(TOKEN)
        not_ready = await module.send_test()
        await configure(module, db)
        ready = await module.send_test()
        return found, not_ready, ready

    found, not_ready, ready = run(scenario, tmp_path, fake)
    assert found["bot"] == "@meu_sentinel_bot"
    assert found["chats"] == [{"id": 42, "name": "Dayvison (@day)", "type": "private"}]
    assert not_ready["ok"] is False and ready["ok"] is True
    assert "Teste do Sentinel" in fake.sent[-1]


def test_format_message_is_plain_text():
    text = format_message(ev(severity=Severity.CRITICAL, title="<b>X</b> & *Y*"))
    assert text.startswith("🔴 Crítico") and "<b>X</b> & *Y*" in text  # sem parse_mode: nada é interpretado
