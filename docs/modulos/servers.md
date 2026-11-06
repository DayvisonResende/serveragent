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

## Reinício automático (opcional, por servidor)

Desligado por padrão. Ao ligar, o usuário autoriza o Sentinel a reiniciar aquele
servidor sem perguntar (PRD 6.5: "política específica e limitada"). Fluxo do PRD 6.6:

1. queda detectada → incidente aberto;
2. espera a 1ª tentativa (padrão 10 s) e reconfere: se voltou sozinho, foi parado
   pelo usuário ou há outra operação, não faz nada;
3. reinicia (auditado como `sentinel:politica-reinicio`) e verifica a saúde;
4. falhou → nova tentativa com espera dobrada (máx. 5 min);
5. esgotado o limite (padrão 3 em 60 min) → para de tentar e avisa (crítico).

Paradas feitas pelo usuário nunca disparam o reinício. O limite geral de
operações por servidor continua valendo.

## Scripts .bat/.cmd

Aceitos como executável de servidores gerenciados (Windows). Como passam pelo
`cmd.exe`, o Sentinel monta a linha de comando num formato fixo
(`cmd /d /s /c ""script" args"`) e os argumentos só podem ter letras, números e
`. _ - : \ / = + , @` — sem espaços nem `& | % ^ < > ! "`, que o cmd interpretaria
como comandos extras. O processo é reconhecido pelo `cmd.exe` cuja linha de
comando contém o caminho do script; CPU e memória somam os processos filhos
(ex.: `java.exe`). Parar encerra o `cmd.exe` desse script e toda a sua árvore.

## Escolha de arquivos

O botão "Procurar…" do cadastro usa `GET /api/v1/files/browse` (somente leitura):
unidades, atalhos (pasta pessoal, Área de Trabalho, Documentos, Downloads,
Arquivos de Programas) e o conteúdo de pastas filtrado por tipo — executáveis/scripts,
logs ou só pastas. Nunca devolve conteúdo de arquivos.

## Independência (PRD 2.4, MVP 12)

Servidores iniciados pelo Sentinel nascem desacoplados: `CREATE_NO_WINDOW |
CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB` no Windows (console oculto: sem janelas pretas), nova sessão em
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
