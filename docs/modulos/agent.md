# sentinel.agent

**Objetivo:** ser o processo do Sentinel — ler a configuração, preparar o
ambiente, conduzir o ciclo de vida e oferecer a CLI.

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | CLI (`init`, `run`, `status`, `check-config`), códigos de saída, log de erro de inicialização |
| `config.py` | Modelo pydantic da configuração, leitura do YAML, resolução de caminhos |
| `bootstrap.py` | Diretórios, configuração padrão (nunca sobrescreve), criação do banco |
| `lifecycle.py` | Classe `Agent`: inicialização ordenada, heartbeat, encerramento isolado por etapa |
| `scheduler.py` | Tarefas periódicas com timeout, backoff exponencial e fator de carga |
| `logging_setup.py` | Logs JSON com rotação e mascaramento de segredos |
| `health.py` | Relatório de saúde (estado, módulos, tarefas, barramento) |

**Entradas:** `config/settings.yaml` (ou `--config` / `SENTINEL_CONFIG`).
**Saídas:** `data/sentinel.db`, `logs/sentinel.log`, `logs/startup-error.log`, `data/sentinel.lock`.
**Dependências:** `core`, `database`, `oslayer`, pydantic, PyYAML.
**Permissões:** nível 0 (observação). Não executa nenhuma ação no sistema.

**Configurações relevantes:** seções `agent`, `scheduler`, `logging`.

**Agendador:**
- intervalo efetivo = base × fator de carga (só para tarefas não essenciais) × min(2^falhas consecutivas, teto);
- uma execução nunca se sobrepõe à anterior; toda execução tem timeout;
- o fator de carga será controlado pelo Resource Manager (Fase 2, PRD 13.3).

**Testes:** `tests/unit/test_config.py`, `test_scheduler.py`, `test_logging_setup.py`,
`tests/integration/test_agent_lifecycle.py`, `test_cli.py`.

**Limitações:**
- Não há comando `stop`. Parar pela tarefa agendada usa `TerminateProcess` e será
  registrado como encerramento inesperado. Um endpoint de parada autenticado virá com a API.
- `install.ps1`, a tarefa agendada e o tratamento de Ctrl+C no Windows ainda
  não foram executados em um Windows real.
