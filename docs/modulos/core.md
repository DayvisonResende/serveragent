# sentinel.core

**Objetivo:** infraestrutura comum a todos os módulos, sem dependência de
sistema operacional, banco ou rede.

| Arquivo | Responsabilidade |
|---|---|
| `event_bus.py` | Publicação não bloqueante de eventos; despacho sequencial com timeout por assinante |
| `module_registry.py` | Contrato `Module`, ordem por dependências, isolamento de falhas |
| `state_manager.py` | Estados do agente e transições permitidas |
| `context.py` | `AgentContext` entregue aos módulos |
| `clock.py` | Horário UTC e serialização ISO-8601 |
| `exceptions.py` | Hierarquia `SentinelError` |

## Contrato de módulo

```python
class MeuModulo(Module):
    name = "monitor"
    depends_on = ("security",)

    async def start(self, context: AgentContext) -> None: ...   # agenda tarefas, retorna rápido
    async def stop(self) -> None: ...                           # libera recursos
    def health(self) -> ModuleHealth: ...                       # opcional
```

- `start` e `stop` têm tempo limite (`agent.module_*_timeout_seconds`).
- Falha em `start` → módulo `failed`, evento `module.failed` (alto); dependentes
  ficam `skipped` (evento `module.skipped`); os demais continuam.
- `stop` só é chamado em módulos que iniciaram.
- `stop` **nunca** deve encerrar processos monitorados (PRD 2.4).

## Barramento de eventos

- `publish()` é síncrono e nunca bloqueia; com fila cheia o evento é descartado,
  contado em `dropped` e registrado em log.
- Assinantes rodam em sequência; exceção ou timeout de um assinante é registrado
  e não afeta os outros.
- O agente assina `*` e persiste todos os eventos na tabela `events`.
- Severidades (PRD 18.3): `info`, `warning`, `high`, `critical`.

**Permissões:** nenhuma. **Configuração:** seção `event_bus`.
**Testes:** `tests/unit/test_event_bus.py`, `test_module_registry.py`.
**Limitações:** despacho sequencial — um assinante lento atrasa os demais até o seu timeout.
