# sentinel.modules.monitor

**Objetivo:** observar continuamente o computador (PRD 5) e alimentar o
dashboard, os alertas, o modo de baixa prioridade e o histórico. Não depende da IA.

| Arquivo | Responsabilidade |
|---|---|
| `cpu.py` | Uso total e por núcleo pela diferença de `cpu_times()`; frequência |
| `memory.py` | RAM e arquivo de paginação |
| `disk.py` | Partições locais e uso; partições ilegíveis são relatadas, não ignoradas |
| `network.py` | Taxas por interface e totais (sem loopback); só contadores, nunca conteúdo |
| `temperature.py` | Sensores, quando o SO os expõe; caso contrário "Sensor de temperatura indisponível." |
| `processes.py` | Lista de processos, CPU normalizada (0–100% da máquina), memória, usuário, caminho |
| `alerts.py` | Limites de CPU/memória (com duração mínima) e de disco, com histerese |
| `store.py` | Estado atual e última hora em resolução total, em memória |
| `module.py` | Agendamento das coletas, persistência, retenção |

## Coletas (configuráveis em `monitoring`)

| Tarefa | Intervalo | Essencial |
|---|---:|:-:|
| CPU, memória, rede | 5 s | sim |
| Discos | 30 s | não |
| Processos | 15 s | não |
| Temperatura | 30 s | não |
| Gravação das médias | 60 s | sim |
| Instantâneo dos processos mais pesados | 5 min | não |
| Histórico de uso de disco | 30 min | não |
| Retenção | 1 dia | não |

Tarefas **não essenciais** desaceleram quando o computador está sob pressão
(`core/resource_manager.py`, PRD 13.3): 2x sob pressão, 4x sob pressão severa.

## Regras de honestidade dos dados (PRD 26.2)

- Taxa de rede e CPU de processo ficam `null` até existir uma segunda leitura.
- Contador de rede que diminui (adaptador reiniciado) → taxa `null` naquela leitura.
- CPU sem intervalo mensurável → a coleta falha (registrada), em vez de publicar 0%.
- Falhas aparecem como lacunas nos gráficos; nada é interpolado.

## Persistência

- `system_metrics`: média e pico de cada minuto.
- `process_snapshots`: top N por CPU e por memória a cada 5 min.
- `disk_usage_history`: uso por partição a cada 30 min (base da tendência de crescimento).
- No encerramento, a janela parcial é gravada.
- Retenção por categoria em `retention`.

**Eventos:** `system.cpu_high`/`cpu_normalized`, `system.memory_high`/`memory_normalized`,
`system.disk_space_low`/`disk_space_recovered`, `resources.pressure_changed`.
**Permissões:** nível 0 (observação). Nenhum processo é alterado.
**Testes:** `test_monitor_collectors.py`, `test_alerts_and_resources.py`, `test_phase2_storage.py`, `test_agent_phase2.py`.

**Limitações:**
- No Windows, a frequência da CPU reportada pelo psutil costuma ser a nominal, não a instantânea.
- Temperatura quase sempre indisponível no Windows sem privilégios de administrador.
- "Conexões de rede relevantes" e "memória comprometida" (PRD 5.3/5.5) ainda não são coletadas.
- Processos protegidos/sumidos são tratados na Fase 3, junto com os servidores cadastrados.
