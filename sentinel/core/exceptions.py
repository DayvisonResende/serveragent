"""Hierarquia de exceções do Sentinel.

Todas as falhas previstas derivam de ``SentinelError`` para que a camada de
entrada (CLI, API) consiga diferenciar erros conhecidos de bugs.
"""


class SentinelError(Exception):
    """Erro base do Sentinel."""


class ConfigurationError(SentinelError):
    """Configuração ausente, malformada ou com valores inválidos."""


class DatabaseError(SentinelError):
    """Falha de acesso ao banco de dados."""


class MigrationError(DatabaseError):
    """Falha ao descobrir ou aplicar migrações."""


class ModuleError(SentinelError):
    """Erro relacionado ao ciclo de vida de módulos."""


class ModuleRegistrationError(ModuleError):
    """Módulo inválido ou registrado em duplicidade."""


class DependencyError(ModuleError):
    """Dependência entre módulos desconhecida ou cíclica."""


class SchedulerError(SentinelError):
    """Uso inválido do agendador."""


class StateTransitionError(SentinelError):
    """Transição de estado do agente não permitida."""


class InstanceLockError(SentinelError):
    """Outra instância do Sentinel já está em execução."""
