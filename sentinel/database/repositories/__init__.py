"""Repositórios: única via de leitura/escrita de cada tabela."""

from sentinel.database.repositories.agent_runs import AgentRunRepository
from sentinel.database.repositories.audit import AuditRepository
from sentinel.database.repositories.auth import AuthRepository
from sentinel.database.repositories.events import EventRepository
from sentinel.database.repositories.metrics import MetricsRepository

__all__ = ["AgentRunRepository", "AuditRepository", "AuthRepository", "EventRepository", "MetricsRepository"]
