# Decisões de arquitetura

Registro das decisões que divergem do PRD ou o detalham. Cada uma pode ser
revista; os contratos entre módulos foram desenhados para permitir isso.

## D1 — Processo único no MVP

**PRD 2.3** descreve cinco processos (Core, API, AI Engine, Workers, Dashboard).
Cada processo Python custa ~30–60 MB, o que conflita com a meta de ≤ 200 MB
(PRD 13.2) num OptiPlex 3020 com 10 GB que também hospeda servidores.

**Decisão:** Core + API (Fase 2) no mesmo processo asyncio; workers como
tarefas do agendador com limite de concorrência; IA = o próprio Ollama, que já
é um processo separado e carregado sob demanda; dashboard = arquivos estáticos.

**Proteção:** módulos se comunicam só pelo barramento de eventos e pelo
`AgentContext`, e falhas de módulo são isoladas (o agente fica `degraded`, não cai).
Separar a API em outro processo depois exige trocar o transporte, não os módulos.

## D2 — Pacote `sentinel/` e camada `oslayer/`

O PRD lista `agent/`, `core/`, `modules/` na raiz. Eles ficam dentro do pacote
`sentinel/` para permitir `python -m sentinel` e imports absolutos. A camada de
integração com o SO (PRD 22.5) se chama `oslayer`, pois `platform` colide com a
biblioteca padrão.

## D3 — Banco com uma thread dedicada

Todo acesso ao SQLite passa por uma única thread (`ThreadPoolExecutor(1)`), em
modo WAL. Serializa as gravações sem bloquear o loop de monitoramento
(PRD 16.3) e permite leitores externos (`sentinel status`) simultâneos.

## D4 — Auditoria imutável no banco

`audit_logs` tem triggers que abortam `UPDATE` e `DELETE`, e o repositório não
expõe métodos de alteração (PRD 11.6). Limitação: isso protege contra código
do próprio Sentinel (dashboard, IA), não contra alguém com acesso direto ao
arquivo. A retenção da auditoria (PRD 16.2) exigirá uma migração específica e
auditada.

## D5 — Detecção de encerramento inesperado

Cada execução grava uma linha em `agent_runs` e um heartbeat periódico. Na
inicialização, execuções antigas sem término são marcadas `unclean` e geram um
evento de atenção. Isso cobre quedas, desligamento forçado e o Agendador de
Tarefas (que encerra via `TerminateProcess`, sem sinal).

## D6 — Configuração estrita

Chaves desconhecidas em `settings.yaml` são rejeitadas e valores têm limites.
Um erro de digitação impede a inicialização com mensagem clara, em vez de ser
ignorado silenciosamente.

## D7 — CPU calculada pelo próprio coletor

`psutil.cpu_percent(None)` guarda estado interno compartilhado; chamado a partir
das threads de coleta, produziu leituras alternadas de 0%. O coletor calcula o
uso pela diferença entre duas leituras de `cpu_times()` que ele mesmo guarda.

## D8 — Login por link de uso único, sem senha

Para uso local, uma senha só adicionaria um segredo a ser esquecido ou reutilizado.
`abrir-dashboard.bat` grava no banco o hash de um código aleatório de 256 bits,
válido por 2 minutos e uma única vez, e abre o navegador. Só quem consegue
escrever na pasta do Sentinel consegue entrar. O acesso remoto (fase futura)
acrescentará senha e HTTPS.

## D9 — Parada limpa por arquivo de pedido

`python -m sentinel stop` cria `data/stop.request`; o agente verifica a cada
segundo e encerra limpo. Assim instalação, atualização e desinstalação não geram
falsos "encerramentos inesperados". O desligamento do Windows é tratado por uma
janela oculta (`oslayer/shutdown_listener.py`) e registrado como `system_shutdown`.

## Decisões futuras já identificadas

- **Fase 3 — Servidores sobrevivendo ao Sentinel (critério 12 do MVP):** iniciar
  processos com `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP |
  CREATE_BREAKAWAY_FROM_JOB`, pois a tarefa agendada roda num *job object* que
  pode encerrar toda a árvore de processos. Validar no Windows real.
- **Fase 4 — Aprovações:** vincular cada aprovação a um hash de
  (operação + alvo + parâmetros), revalidado pelo executor.
- **Inicialização sem logon:** a tarefa atual inicia no logon do usuário. Para
  servidores que precisam subir sem ninguém logado será preciso
  "executar estando o usuário conectado ou não", o que envolve credenciais —
  decisão do usuário.
