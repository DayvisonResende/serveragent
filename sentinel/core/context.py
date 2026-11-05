"""Contexto entregue aos módulos na inicialização.

É a única forma de um módulo acessar serviços do núcleo — módulos não
importam uns aos outros diretamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel.agent.config import Settings
    from sentinel.agent.scheduler import Scheduler
    from sentinel.core.event_bus import EventBus
    from sentinel.core.resource_manager import ResourceManager
    from sentinel.database.database import Database
    from sentinel.oslayer.info import PlatformInfo


@dataclass(frozen=True, slots=True)
class AgentContext:
    settings: Settings
    event_bus: EventBus
    scheduler: Scheduler
    database: Database
    platform: PlatformInfo
    resources: ResourceManager
