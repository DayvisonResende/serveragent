"""Canal Telegram (PRD 18.4). Mensagens em texto puro, sem formatação interpretada.

O token do bot faz parte da URL da API do Telegram; por isso nenhuma mensagem de
erro gerada aqui contém a URL — o token nunca chega aos logs.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable

API_HOST = "https://api.telegram.org"
TOKEN_PATTERN = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")
MAX_MESSAGE = 4000

# (método da API, token, carga JSON ou None) → resposta JSON decodificada
Transport = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]


class TelegramError(Exception):
    """Falha ao falar com o Telegram (mensagem já sem o token)."""


def valid_token(token: str) -> bool:
    return bool(TOKEN_PATTERN.match(token or ""))


def https_transport(method: str, token: str, payload: dict[str, Any] | None, timeout: float = 15.0) -> dict[str, Any]:
    url = f"{API_HOST}/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json", "User-Agent": "Sentinel"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            description = body.get("description", "")
        except (ValueError, OSError):
            description = ""
        raise TelegramError(f"Telegram respondeu HTTP {exc.code}{': ' + description if description else ''}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TelegramError(f"Sem conexão com o Telegram ({type(reason).__name__})") from None


class TelegramChannel:
    def __init__(self, transport: Transport = https_transport) -> None:
        self._transport = transport

    def _call(self, method: str, token: str, payload: dict[str, Any] | None = None) -> Any:
        if not valid_token(token):
            raise TelegramError("Token do bot em formato inválido")
        response = self._transport(method, token, payload)
        if not response.get("ok"):
            raise TelegramError(f"Telegram recusou: {response.get('description', 'erro desconhecido')}")
        return response.get("result")

    def bot_name(self, token: str) -> str:
        result = self._call("getMe", token)
        return f"@{result.get('username')}" if result.get("username") else str(result.get("first_name", "bot"))

    def send(self, token: str, chat_id: str | int, text: str) -> None:
        self._call("sendMessage", token, {"chat_id": chat_id, "text": text[:MAX_MESSAGE], "disable_web_page_preview": True})

    def recent_chats(self, token: str) -> list[dict[str, Any]]:
        """Conversas que escreveram ao bot recentemente (para descobrir o chat_id sem digitar nada)."""
        updates = self._call("getUpdates", token, {"timeout": 0, "allowed_updates": ["message"]}) or []
        chats: dict[int, dict[str, Any]] = {}
        for update in updates:
            chat = (update.get("message") or {}).get("chat") or {}
            if "id" not in chat:
                continue
            name = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
            if chat.get("username"):
                name = f"{name} (@{chat['username']})".strip()
            entry = {"id": chat["id"], "name": name or str(chat["id"]), "type": chat.get("type")}
            previous = chats.get(chat["id"])
            if previous is None or len(entry["name"]) > len(previous["name"]):  # mantém a identificação mais completa
                chats[chat["id"]] = entry
        return list(chats.values())
