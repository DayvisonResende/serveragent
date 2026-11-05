"""Monitoramento do sistema (PRD 5): CPU, memória, disco, rede, temperatura e processos.

Somente observação (permissão nível 0). Não depende da IA.
"""

from sentinel.modules.monitor.module import MonitorModule
from sentinel.modules.monitor.store import MetricsStore

__all__ = ["MetricsStore", "MonitorModule"]
