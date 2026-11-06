"""Notificações para fora do dashboard (PRD 18): hoje, Telegram.

- Desligado até o usuário configurar e ativar no dashboard.
- Envia eventos a partir da severidade escolhida, mais recuperações e o
  resultado de reinícios automáticos.
- Nunca bloqueia o agente: fila limitada e envio numa tarefa própria.
- Sem enxurrada: 20 mensagens/min no máximo; a mesma notícia repetida em
  2 min é suprimida; até 3 tentativas por mensagem.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Callable

from sentinel.core.clock import to_iso, utc_now
from sentinel.core.event_bus import WILDCARD, Event
from sentinel.core.module_registry import Module, ModuleHealth
from sentinel.database.repositories.settings import SecretRepository, SettingsRepository
from sentinel.modules.notifications.channels import TelegramChannel, TelegramError, Transport, https_transport

if TYPE_CHECKING:
    from sentinel.core.context import AgentContext

log = logging.getLogger(__name__)

SETTINGS_KEY = "notifications"
TOKEN_SECRET = "telegram_bot_token"
DEFAULTS: dict[str, Any] = {"enabled": False, "telegram_chat_id": None, "min_severity": "warning", "include_recoveries": True}
SEVERITY_RANK = {"info": 0, "warning": 1, "high": 2, "critical": 3}
ALWAYS_TYPES = frozenset({"server.recovered", "server.auto_restart", "agent.unclean_shutdown"})
RECOVERY_TYPES = frozenset({"server.recovered"})
ICONS = {"info": "ℹ️", "warning": "⚠️", "high": "🟠", "critical": "🔴"}
LABELS = {"info": "Informativo", "warning": "Atenção", "high": "Alto", "critical": "Crítico"}
MAX_PER_MINUTE = 20
DEDUP_SECONDS = 120
RETRY_DELAYS = (2.0, 5.0, 10.0)


class NotificationsModule(Module):
    name = "notifications"

    def __init__(self, transport: Transport = https_transport, sleep: Callable[[float], Any] = asyncio.sleep) -> None:
        self._channel = TelegramChannel(transport)
        self._sleep = sleep
        self._ctx: AgentContext | None = None
        self._settings: SettingsRepository | None = None
        self._secrets: SecretRepository | None = None
        self.config: dict[str, Any] = dict(DEFAULTS)
        self._token: str | None = None
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=200)
        self._task: asyncio.Task[None] | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._sent_times: deque[float] = deque()
        self._recent: dict[str, float] = {}
        self._suppressed = 0
        self.stats: dict[str, Any] = {"sent": 0, "failed": 0, "dropped": 0, "last_sent_at": None, "last_error": None}

    async def start(self, context: AgentContext) -> None:
        self._ctx = context
        self._settings = SettingsRepository(context.database)
        self._secrets = SecretRepository(context.database)
        await self.reload()
        self._unsubscribe = context.event_bus.subscribe(WILDCARD, self._on_event)
        self._task = asyncio.create_task(self._sender(), name="sentinel-notifications")

    async def stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def health(self) -> ModuleHealth:
        if not self.active:
            return ModuleHealth(True, "Notificações externas desativadas")
        if self.stats["last_error"] and self.stats["failed"] and not self.stats["sent"]:
            return ModuleHealth(False, f"Falha ao enviar: {self.stats['last_error']}")
        return ModuleHealth(True, f"Telegram ativo · {self.stats['sent']} enviada(s)")

    @property
    def active(self) -> bool:
        return bool(self.config.get("enabled") and self._token and self.config.get("telegram_chat_id"))

    async def reload(self) -> None:
        assert self._settings is not None and self._secrets is not None
        self.config = {**DEFAULTS, **(await self._settings.get(SETTINGS_KEY, {}))}
        try:
            self._token = await self._secrets.get(TOKEN_SECRET)
        except (OSError, ValueError) as exc:
            self._token = None
            self.stats["last_error"] = f"Não foi possível ler o token: {exc}"
            log.error("Token do Telegram ilegível", extra={"error": str(exc)})

    def status(self) -> dict[str, Any]:
        return {**self.stats, "active": self.active, "queued": self._queue.qsize(), "suppressed": self._suppressed}

    # ------------------------------------------------------------- operações

    async def send_test(self) -> dict[str, Any]:
        if not self._token or not self.config.get("telegram_chat_id"):
            return {"ok": False, "message": "Configure o token do bot e o chat antes de testar"}
        text = f"✅ Teste do Sentinel · {socket.gethostname()}\nSe você recebeu esta mensagem, as notificações estão funcionando."
        try:
            await asyncio.to_thread(self._channel.send, self._token, self.config["telegram_chat_id"], text)
        except TelegramError as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "Mensagem de teste enviada"}

    async def bot_and_chats(self, token: str | None = None) -> dict[str, Any]:
        token = token or self._token
        if not token:
            raise TelegramError("Informe o token do bot")
        bot = await asyncio.to_thread(self._channel.bot_name, token)
        chats = await asyncio.to_thread(self._channel.recent_chats, token)
        return {"bot": bot, "chats": chats}

    # ----------------------------------------------------------------- envio

    def wants(self, event: Event) -> bool:
        if not self.active:
            return False
        if event.event_type in RECOVERY_TYPES:
            return bool(self.config.get("include_recoveries", True))
        if event.event_type in ALWAYS_TYPES:
            return True
        return SEVERITY_RANK[event.severity.value] >= SEVERITY_RANK.get(self.config.get("min_severity", "warning"), 1)

    async def _on_event(self, event: Event) -> None:
        if not self.wants(event):
            return
        key = f"{event.event_type}|{event.title}"
        now = time.monotonic()
        if now - self._recent.get(key, -1e9) < DEDUP_SECONDS:
            self._suppressed += 1
            return
        self._recent[key] = now
        if len(self._recent) > 500:
            self._recent = {k: v for k, v in self._recent.items() if now - v < DEDUP_SECONDS}
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.stats["dropped"] += 1

    async def _sender(self) -> None:
        while True:
            event = await self._queue.get()
            await self._respect_rate_limit()
            text = format_message(event, self._suppressed)
            self._suppressed = 0
            await self._deliver(text)

    async def _respect_rate_limit(self) -> None:
        while True:
            now = time.monotonic()
            while self._sent_times and now - self._sent_times[0] > 60:
                self._sent_times.popleft()
            if len(self._sent_times) < MAX_PER_MINUTE:
                self._sent_times.append(now)
                return
            await self._sleep(60 - (now - self._sent_times[0]) + 0.1)

    async def _deliver(self, text: str) -> None:
        for attempt, delay in enumerate((0.0, *RETRY_DELAYS)):
            if delay:
                await self._sleep(delay)
            if not self.active:
                return
            try:
                await asyncio.to_thread(self._channel.send, self._token, self.config["telegram_chat_id"], text)
            except TelegramError as exc:
                self.stats["last_error"] = str(exc)
                log.warning("Falha ao enviar notificação", extra={"attempt": attempt + 1, "error": str(exc)})
                continue
            self.stats["sent"] += 1
            self.stats["last_sent_at"] = to_iso(utc_now())
            self.stats["last_error"] = None
            return
        self.stats["failed"] += 1
        log.error("Notificação descartada após tentativas", extra={"error": self.stats["last_error"]})


def format_message(event: Event, suppressed: int = 0) -> str:
    sev = event.severity.value
    icon = "✅" if event.event_type in RECOVERY_TYPES or (event.event_type == "server.auto_restart" and sev == "info") else ICONS[sev]
    when = event.timestamp.astimezone().strftime("%d/%m %H:%M")
    lines = [f"{icon} {LABELS[sev]} · {socket.gethostname()}", event.title]
    if event.description:
        lines.append(event.description[:1500])
    lines.append(when)
    if suppressed:
        lines.append(f"(+{suppressed} notificação(ões) repetida(s) suprimida(s))")
    return "\n".join(lines)


def severity_ok(value: str) -> bool:
    return value in SEVERITY_RANK


__all__ = ["NotificationsModule", "format_message"]
