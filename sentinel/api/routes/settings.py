"""Configurações editáveis no dashboard (PRD 21) — por enquanto, notificações.

O token do bot só entra (nunca é devolvido): a resposta diz apenas se existe e
como está protegido. Mudanças são auditadas sem o valor do token.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from sentinel.api.app import get_deps
from sentinel.database.repositories import AuditRepository
from sentinel.database.repositories.settings import SecretRepository, SettingsRepository
from sentinel.modules.notifications.channels import TelegramError, valid_token
from sentinel.modules.notifications.manager import DEFAULTS, SETTINGS_KEY, TOKEN_SECRET, NotificationsModule

router = APIRouter(prefix="/api/v1/settings")


class NotificationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    telegram_chat_id: int | None = None
    min_severity: Literal["info", "warning", "high", "critical"] = "warning"
    include_recoveries: bool = True
    # None: mantém o token atual; "": remove; texto: substitui.
    telegram_token: str | None = Field(None, max_length=200)


class DetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_token: str | None = Field(None, max_length=200)


def _module(request: Request) -> NotificationsModule:
    module = get_deps(request).notifications
    if module is None:
        raise HTTPException(503, "Módulo de notificações indisponível")
    return module


async def _view(request: Request) -> dict[str, Any]:
    deps = get_deps(request)
    module = _module(request)
    token = await SecretRepository(deps.database).info(TOKEN_SECRET)
    return {
        "config": {**DEFAULTS, **(await SettingsRepository(deps.database).get(SETTINGS_KEY, {}))},
        "token": {"configured": token is not None, "protection": token["protection"] if token else None,
                  "updated_at": token["updated_at"] if token else None},
        "status": module.status(),
    }


@router.get("/notifications")
async def get_notifications(request: Request) -> dict[str, Any]:
    return await _view(request)


@router.put("/notifications")
async def put_notifications(request: Request, body: NotificationSettings) -> dict[str, Any]:
    deps = get_deps(request)
    module = _module(request)
    secrets = SecretRepository(deps.database)
    token_change = None
    if body.telegram_token is not None:
        token = body.telegram_token.strip()
        if token == "":
            await secrets.delete(TOKEN_SECRET)
            token_change = "removido"
        elif not valid_token(token):
            raise HTTPException(422, "Token do bot inválido. Ele tem o formato 123456789:ABC… e é fornecido pelo @BotFather.")
        else:
            await secrets.set(TOKEN_SECRET, token)
            token_change = "alterado"
    has_token = await secrets.info(TOKEN_SECRET) is not None
    if body.enabled and (not has_token or body.telegram_chat_id is None):
        raise HTTPException(422, "Para ativar, informe o token do bot e escolha o chat que receberá as mensagens.")
    config = body.model_dump(exclude={"telegram_token"})
    await SettingsRepository(deps.database).set(SETTINGS_KEY, config)
    await module.reload()
    await AuditRepository(deps.database).record(
        actor="usuario:dashboard", operation="settings.notifications", result="success",
        details={**config, "token": token_change or "inalterado"},
    )
    return await _view(request)


@router.post("/notifications/test")
async def test_notifications(request: Request) -> dict[str, Any]:
    return await _module(request).send_test()


@router.post("/notifications/detect-chats")
async def detect_chats(request: Request, body: DetectRequest | None = None) -> dict[str, Any]:
    """Lista quem escreveu ao bot recentemente — evita digitar o chat_id à mão."""
    token = (body.telegram_token or "").strip() if body else ""
    if token and not valid_token(token):
        raise HTTPException(422, "Token do bot inválido")
    try:
        return await _module(request).bot_and_chats(token or None)
    except TelegramError as exc:
        raise HTTPException(502, str(exc)) from exc
