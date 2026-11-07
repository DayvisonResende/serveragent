"""Catálogo fechado de operações (PRD 11.5).

Só o que está aqui pode ser executado — não existe "executar comando". Cada
operação define: nível de risco (PRD 11.2), impacto e riscos exibidos na
aprovação, como identificar o alvo (e sua impressão digital) e como executar.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from sentinel.core.exceptions import SentinelError

if TYPE_CHECKING:
    from sentinel.modules.servers.manager import ServersModule


class ActionError(SentinelError):
    """Pedido inválido ou recusado (mensagem para o usuário)."""


@dataclass(frozen=True)
class Target:
    id: int
    name: str
    fingerprint: str


@dataclass(frozen=True)
class OperationSpec:
    name: str
    label: str
    risk_level: int  # 0 observação · 1 leve · 2 exige aprovação · 3 crítica (confirmação extra)
    impact: str
    risks: str
    resolve: Callable[[int, dict[str, Any]], Target]
    execute: Callable[[int, dict[str, Any], str, str, int | None], Awaitable[dict[str, Any]]]


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def server_operations(servers: ServersModule) -> dict[str, OperationSpec]:
    def resolve(operation: str) -> Callable[[int, dict[str, Any]], Target]:
        def _resolve(target_id: int, params: dict[str, Any]) -> Target:
            record = servers.get_record(target_id)
            if record is None:
                raise ActionError(f"Servidor {target_id} não encontrado")
            if record.management != "managed":
                raise ActionError(f"'{record.name}' é apenas observado; o Sentinel não o inicia nem o encerra")
            # A aprovação vale para ESTE cadastro: qualquer alteração depois do pedido a invalida.
            fp = _fingerprint({
                "operation": operation, "target_id": record.id, "updated_at": record.updated_at,
                "executable": record.executable, "arguments": record.arguments,
                "working_directory": record.working_directory, "params": params,
            })
            return Target(record.id, record.name, fp)

        return _resolve

    def execute(operation: str) -> Callable[[int, dict[str, Any], str, str, int | None], Awaitable[dict[str, Any]]]:
        async def _execute(target_id: int, params: dict[str, Any], actor: str, reason: str, approval_id: int | None) -> dict[str, Any]:
            return await servers.execute(operation, target_id, actor, reason, approval_id)

        return _execute

    common_risk = "Usuários conectados ao servidor perdem a conexão. No Windows o encerramento é imediato."
    return {
        "server_start": OperationSpec(
            "server_start", "Iniciar servidor", 2,
            "Inicia o processo cadastrado e aguarda ele responder.",
            "Consome recursos do computador; pode falhar se a porta estiver ocupada.",
            resolve("server_start"), execute("server_start"),
        ),
        "server_stop": OperationSpec(
            "server_stop", "Parar servidor", 2,
            "Encerra o processo do servidor e os programas que ele iniciou.",
            common_risk + " O servidor fica fora do ar até ser iniciado de novo.",
            resolve("server_stop"), execute("server_stop"),
        ),
        "server_restart": OperationSpec(
            "server_restart", "Reiniciar servidor", 2,
            "Encerra (se estiver rodando) e inicia novamente o servidor, verificando se voltou a responder.",
            common_risk + " Se a causa da falha persistir, o servidor pode não voltar.",
            resolve("server_restart"), execute("server_restart"),
        ),
    }
