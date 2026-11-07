"""Chat com a IA local (PRD 9, 14.9, 15.1)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinel.api.app import get_deps
from sentinel.modules.ai.assistant import AIBusy, AIUnavailable
from sentinel.modules.ai.module import AIModule

router = APIRouter(prefix="/api/v1")
_CONVERSATION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None

    @field_validator("conversation_id")
    @classmethod
    def _conversation(cls, value: str | None) -> str | None:
        if value is not None and not _CONVERSATION.match(value):
            raise ValueError("identificador de conversa inválido")
        return value


def _module(request: Request) -> AIModule:
    module = get_deps(request).ai
    if module is None or module.assistant is None:
        raise HTTPException(503, "Módulo de IA indisponível")
    return module


@router.get("/ai/status")
async def ai_status(request: Request, refresh: bool = False) -> dict[str, Any]:
    module = _module(request)
    return await module.refresh_status() if refresh else module.snapshot()


@router.post("/ai/warmup")
async def ai_warmup(request: Request) -> dict[str, Any]:
    """Chamado ao abrir a página Assistente: prepara o modelo enquanto o usuário digita."""
    module = _module(request)
    assert module.assistant is not None
    try:
        return await module.assistant.warm_up()
    except AIUnavailable as exc:
        await module.refresh_status()
        raise HTTPException(503, str(exc)) from exc


@router.post("/chat")
async def chat(request: Request, body: ChatRequest) -> dict[str, Any]:
    module = _module(request)
    assert module.assistant is not None
    conversation = body.conversation_id or uuid.uuid4().hex[:16]
    try:
        return await module.assistant.ask(conversation, body.message.strip())
    except AIBusy as exc:
        raise HTTPException(429, str(exc)) from exc
    except AIUnavailable as exc:
        await module.refresh_status()
        raise HTTPException(503, str(exc)) from exc


@router.get("/chat/history")
async def chat_history(request: Request, conversation_id: str = Query(..., max_length=64), limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    if not _CONVERSATION.match(conversation_id):
        raise HTTPException(422, "identificador de conversa inválido")
    module = _module(request)
    assert module.assistant is not None
    return {"conversation_id": conversation_id, "messages": await module.assistant.history(conversation_id, limit)}
