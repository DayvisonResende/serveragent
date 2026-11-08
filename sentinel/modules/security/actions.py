"""Solicitações, aprovações e execução restrita (PRD 11.3–11.6).

Fluxo (PRD 11.4):
  1. alguém pede uma operação do catálogo;
  2. o alvo é validado e recebe uma impressão digital;
  3. a ação e a aprovação são registradas (com prazo de validade);
  4. quem aprova:
       - o usuário que pediu (clique com confirmação no dashboard/CLI) → aprovação imediata;
       - uma política autorizada pelo usuário (reinício automático) → imediata;
       - pedido do próprio Sentinel ou da IA → fica PENDENTE até o usuário decidir;
  5. ao aprovar, o alvo é revalidado: se o cadastro mudou, a aprovação não vale;
  6. o executor roda apenas a operação aprovada, uma única vez;
  7. resultado registrado (ações + auditoria) e publicado como evento.
"""

from __future__ import annotations

import inspect

import logging
from typing import TYPE_CHECKING, Any, Literal

from sentinel.core.event_bus import Event, Severity
from sentinel.database.repositories.actions import ActionRepository
from sentinel.database.repositories.audit import AuditRepository
from sentinel.modules.security.operations import ActionError, OperationSpec, Target

if TYPE_CHECKING:
    from sentinel.core.event_bus import EventBus
    from sentinel.database.database import Database

log = logging.getLogger(__name__)

Approval = Literal["user", "policy", "required"]
EVENT_REQUESTED = "approval.requested"
EVENT_DECIDED = "approval.decided"
EVENT_ACTION = "action.finished"
SOURCE = "security"
POLICY_APPROVER = "politica-autorizada"  # ex.: reinício automático ligado pelo usuário no cadastro


class ActionNotFound(ActionError):
    pass


class ActionService:
    def __init__(self, database: Database, event_bus: EventBus, catalog: dict[str, OperationSpec], ttl_seconds: float = 1800) -> None:
        self._repo = ActionRepository(database)
        self._audit = AuditRepository(database)
        self._bus = event_bus
        self._catalog = catalog
        self._ttl = ttl_seconds

    @property
    def catalog(self) -> dict[str, OperationSpec]:
        return self._catalog

    def register(self, specs: dict[str, OperationSpec]) -> None:
        """Outros módulos acrescentam suas operações ao catálogo fechado (ex.: limpeza)."""
        clash = set(specs) & set(self._catalog)
        if clash:
            raise ValueError(f"operações já cadastradas: {', '.join(sorted(clash))}")
        self._catalog.update(specs)

    async def request(
        self, operation: str, target_id: int, params: dict[str, Any] | None, requested_by: str, reason: str,
        approval: Approval,
    ) -> dict[str, Any]:
        """Registra o pedido. Com aprovação do usuário/política executa já; senão fica pendente."""
        spec = self._spec(operation)
        params = params or {}
        target = await _resolve(spec, target_id, params)
        if approval == "required":
            existing = await self._repo.pending_for(operation, target.id)
            if existing:
                return existing  # não duplica pedidos iguais em aberto
        requires_confirmation = spec.risk_level >= 3
        action_id = await self._repo.create(
            {"action_type": operation, "target": target.name, "target_id": target.id, "params": params,
             "fingerprint": target.fingerprint, "risk_level": spec.risk_level, "requested_by": requested_by,
             "reason": reason or spec.label},
            {"ttl_seconds": self._ttl, "impact": spec.impact, "risks": spec.risks, "requires_confirmation": requires_confirmation},
        )
        await self._audit.record(actor=requested_by, operation="action.request", target=target.name, reason=reason,
                                 result="pending", details={"action_id": action_id, "operation": operation})
        if approval == "required" or requires_confirmation:
            if approval == "user":
                # O próprio usuário pediu e está digitando a confirmação: registro, sem alarme (nem Telegram).
                self._publish(EVENT_REQUESTED, Severity.INFO, f"Confirmação pedida: {spec.label.lower()} '{target.name}'",
                              "Operação crítica: aguardando o usuário digitar o nome do alvo.",
                              {"action_id": action_id, "operation": operation, "target": target.name})
            else:
                self._publish(EVENT_REQUESTED, Severity.WARNING, f"Aprovação pendente: {spec.label.lower()} '{target.name}'",
                              f"{reason} Abra o dashboard (Aprovações) para aprovar ou rejeitar.",
                              {"action_id": action_id, "operation": operation, "target": target.name})
            return await self._get(action_id)
        decided_by = requested_by if approval == "user" else POLICY_APPROVER
        return await self._approve_and_run(action_id, decided_by, confirmation=None)

    async def approve(self, action_id: int, user: str, confirmation: str | None = None) -> dict[str, Any]:
        return await self._approve_and_run(action_id, user, confirmation)

    async def reject(self, action_id: int, user: str, note: str | None = None) -> dict[str, Any]:
        action = await self._get(action_id)
        if not await self._repo.decide(action_id, "rejected", user, note):
            raise ActionError(f"A solicitação #{action_id} não está mais pendente ({action['status']})")
        await self._audit.record(actor=user, operation="approval.reject", target=action["target"], reason=note,
                                 approval_id=action["approval_id"], result="rejected", details={"action_id": action_id})
        self._publish(EVENT_DECIDED, Severity.INFO, f"Solicitação rejeitada: {self._label(action)} '{action['target']}'",
                      note or "", {"action_id": action_id, "decision": "rejected"})
        return await self._get(action_id)

    async def cancel_pending(self, operation: str, target_id: int, reason: str) -> dict[str, Any] | None:
        """Cancela um pedido em aberto que perdeu o sentido (ex.: o servidor voltou sozinho)."""
        pending = await self._repo.pending_for(operation, target_id)
        if pending is None or not await self._repo.decide(pending["id"], "cancelled", "sentinel", reason):
            return None
        await self._audit.record(actor="sentinel", operation="approval.cancel", target=pending["target"], reason=reason,
                                 approval_id=pending["approval_id"], result="cancelled", details={"action_id": pending["id"]})
        self._publish(EVENT_DECIDED, Severity.INFO, f"Solicitação cancelada: {self._label(pending)} '{pending['target']}'",
                      reason, {"action_id": pending["id"], "decision": "cancelled"})
        return await self._get(pending["id"])

    async def expire_due(self) -> list[int]:
        expired = await self._repo.expire_due()
        for action_id in expired:
            action = await self._get(action_id)
            await self._audit.record(actor="sentinel", operation="approval.expire", target=action["target"],
                                     approval_id=action["approval_id"], result="expired", details={"action_id": action_id})
            self._publish(EVENT_DECIDED, Severity.INFO, f"Solicitação expirou: {self._label(action)} '{action['target']}'",
                          "Ninguém aprovou dentro do prazo; nada foi executado.", {"action_id": action_id, "decision": "expired"})
        return expired

    async def get(self, action_id: int) -> dict[str, Any]:
        return await self._get(action_id)

    async def list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        actions = await self._repo.list(status, limit)
        for action in actions:
            spec = self._catalog.get(action["action_type"])
            action["label"] = spec.label if spec else action["action_type"]
        return actions

    async def count_pending(self) -> int:
        return await self._repo.count_pending()

    # ------------------------------------------------------------------ interno

    async def _approve_and_run(self, action_id: int, approver: str, confirmation: str | None) -> dict[str, Any]:
        action = await self._get(action_id)
        if action["status"] != "pending":
            raise ActionError(f"A solicitação #{action_id} não está pendente ({action['status']}); aprovações não podem ser reutilizadas")
        spec = self._spec(action["action_type"])
        if action["requires_confirmation"] and (confirmation or "").strip() != action["target"]:
            raise ActionError(f"Operação crítica: digite o nome do alvo ('{action['target']}') para confirmar")
        # Revalida o alvo (PRD 11.4 passo 6): a aprovação vale só para o que foi pedido.
        try:
            current = await _resolve(spec, action["target_id"], action["params"])
        except ActionError as exc:
            await self._repo.decide(action_id, "cancelled", "sentinel", str(exc))
            raise ActionError(f"Solicitação cancelada: {exc}") from exc
        if current.fingerprint != action["fingerprint"]:
            note = "o cadastro do alvo mudou depois do pedido"
            await self._repo.decide(action_id, "cancelled", "sentinel", note)
            await self._audit.record(actor="sentinel", operation="approval.cancel", target=action["target"], reason=note,
                                     approval_id=action["approval_id"], result="cancelled", details={"action_id": action_id})
            raise ActionError(f"Solicitação cancelada: {note}. Faça um novo pedido.")
        if not await self._repo.decide(action_id, "approved", approver):
            raise ActionError(f"A solicitação #{action_id} expirou ou já foi decidida")
        await self._audit.record(actor=approver, operation="approval.approve", target=action["target"],
                                 approval_id=action["approval_id"], result="approved", details={"action_id": action_id})
        return await self._run(action, spec, approver)

    async def _run(self, action: dict[str, Any], spec: OperationSpec, approver: str) -> dict[str, Any]:
        action_id = action["id"]
        await self._repo.set_status(action_id, "executing")
        reason = action["reason"]
        if action["requested_by"] != approver and approver != POLICY_APPROVER:
            reason = f"{reason} (solicitado por {action['requested_by']}, aprovado por {approver})"
        actor = action["requested_by"] if approver == POLICY_APPROVER else approver
        try:
            result = await spec.execute(action["target_id"], action["params"], actor, reason, action["approval_id"])
        except ActionError:
            raise
        except Exception as exc:
            # Inclui recusas do executor (ex.: já em execução): a ação falha com o motivo.
            await self._repo.set_status(action_id, "failed", error=str(exc))
            self._publish(EVENT_ACTION, Severity.HIGH, f"{spec.label} '{action['target']}': recusado", str(exc),
                          {"action_id": action_id, "ok": False})
            raise ActionError(str(exc)) from exc
        status = "completed" if result.get("ok") else "failed"
        await self._repo.set_status(action_id, status, result=result, error=None if result.get("ok") else result.get("message"))
        return await self._get(action_id)

    async def _get(self, action_id: int) -> dict[str, Any]:
        action = await self._repo.get(action_id)
        if action is None:
            raise ActionNotFound(f"Solicitação #{action_id} não encontrada")
        spec = self._catalog.get(action["action_type"])
        action["label"] = spec.label if spec else action["action_type"]
        return action

    def _spec(self, operation: str) -> OperationSpec:
        spec = self._catalog.get(operation)
        if spec is None:
            raise ActionError(f"Operação não permitida: {operation}")
        return spec

    def _label(self, action: dict[str, Any]) -> str:
        spec = self._catalog.get(action["action_type"])
        return (spec.label if spec else action["action_type"]).lower()

    def _publish(self, event_type: str, severity: Severity, title: str, description: str, meta: dict[str, Any]) -> None:
        self._bus.publish(Event(event_type=event_type, source=SOURCE, severity=severity, title=title,
                                description=description, metadata=meta))


async def _resolve(spec: OperationSpec, target_id: int, params: dict[str, Any]) -> Target:
    """``resolve`` pode ser síncrono (servidores, em memória) ou assíncrono (planos no banco)."""
    target = spec.resolve(target_id, params)
    return await target if inspect.isawaitable(target) else target
