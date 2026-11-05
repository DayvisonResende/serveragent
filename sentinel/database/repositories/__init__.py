"""Repositórios: única via de leitura/escrita de cada tabela."""

from sentinel.database.repositories.agent_runs import AgentRunRepository
from sentinel.database.repositories.audit import AuditRepository
from sentinel.database.repositories.events import EventRepository

__all__ = ["AgentRunRepository", "AuditRepository", "EventRepository"]
