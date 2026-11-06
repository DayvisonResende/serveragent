# sentinel.modules.servers

**Objetivo:** administrar servidores hospedados no computador (PRD 6): cadastro,
saúde, estados, incidentes, logs e operações controladas.

| Arquivo | Responsabilidade |
|---|---|
| `models.py` | Cadastro (`ServerSpec`), validação, estados, critério de reconhecimento |
| `matching.py` | Quais processos pertencem ao servidor; confirmação de que ainda existem |
| `health.py` | Verificações por porta, TCP e HTTP; cálculo do estado |
| `manager.py` | Módulo: verificações periódicas, transições, incidentes, operações |
| `logs.py` | Final de arquivos de log, como texto |
| `oslayer/process_control.py` | Início desacoplado, encerramento da árvore, processos protegidos |

## Tipos de servidor

- **Gerenciado:** o Sentinel pode iniciar, parar e reiniciar. Exige executável por caminho absoluto.
- **Observado:** só monitorado (ex.: PostgreSQL/MySQL rodando como serviço do Windows).

## Estados (PRD 6.3)

`online`, `offline`, `starting`, `restarting`, `degraded` (com problemas),
`unresponsive` (sem resposta), `unknown`, `disabled`.

- Processo ativo **não** basta: sem verificação de porta/TCP/HTTP o servidor aparece
  online com o aviso "saúde não verificada".
- Rebaixar exige `failure_threshold` falhas seguidas (padrão 2); a recuperação é imediata.
- Após reiniciar o agente, o último estado e o incidente aberto são retomados.

## Incidentes

Abertos na entrada em offline/sem resposta/com problemas; a linha do tempo registra
cada mudança; fechados na recuperação com a duração. Paradas pedidas pelo usuário
não geram incidente. O nome do servidor é copiado, então o histórico sobrevive à
exclusão do cadastro.

## Operações (PRD 6.5, 7.3, 11.5)

Conjunto fechado: `server_start`, `server_stop`, `server_restart`. Não existe execução genérica.

| Proteção | Como |
|---|---|
| Sem shell | `Popen` com lista de argumentos, `shell=False` |
| Sem interpretadores de comandos | cmd, PowerShell, wscript, mshta, bash… recusados no cadastro |
| Só o servidor certo | encerra apenas processos reconhecidos; critério que pega mais de 30 processos é recusado |
| Processos essenciais | lsass, csrss, svchost, explorer, executáveis em `C:\Windows`, o próprio Sentinel |
| Ciclos de reinício | no máximo 5 operações por servidor a cada 10 min |
| Concorrência | uma operação por servidor por vez |
| Rastreabilidade | toda operação (inclusive recusada) vai para a auditoria e gera evento |

Nesta fase quem autoriza é o usuário autenticado (com confirmação no dashboard ou
na CLI). **Na Fase 4 as operações passam pelo sistema de aprovações.**

## Independência (PRD 2.4, MVP 12)

Servidores iniciados pelo Sentinel nascem desacoplados: `DETACHED_PROCESS |
CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB` no Windows, nova sessão em
POSIX. Se o Windows recusar o breakaway, o servidor inicia mesmo assim e a
operação devolve um **aviso** explícito. Encerrar o Sentinel nunca encerra servidores.

**API:** `/api/v1/servers` (CRUD), `/servers/{id}/health|logs|incidents`,
`POST /servers/{id}/actions/{start|stop|restart}`, `/incidents`,
`/system/processes/{pid}/candidate`. **CLI:** `python -m sentinel server list|start|stop|restart <nome>`.
**Configuração:** seção `servers`; retenção `retention.server_checks_days`.
**Testes:** `test_servers.py`, `test_servers_e2e.py`; `selfcheck --servers prepare|finish` no agente real.

**Limitações:**
- No Windows o encerramento é imediato (processos sem console não recebem aviso).
  Não use "gerenciado" para bancos de dados — prefira "observado".
- Verificação "personalizada" (PRD 6.4) ainda não existe.
- Política de reinício automático fica para a Fase 8 (exige aprovações da Fase 4).
