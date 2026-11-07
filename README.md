# Sentinel

Agente local de administração, monitoramento e manutenção de servidores Windows.
Especificação completa em [PRD.md](PRD.md).

**Estado atual:** Fase 5 — IA local. Monitoramento (Fase 2), servidores (Fase 3),
aprovações e auditoria (Fase 4) e agora um **assistente** no dashboard: você pergunta
em português ("algum servidor está com problema?") e a IA local (Ollama, modelo
LFM3-1.7B) consulta os dados reais do Sentinel antes de responder. A IA não executa
nada: pedidos para iniciar, parar ou reiniciar servidores viram itens em
**Aprovações**. O monitoramento não depende da IA: com o Ollama desligado, só o
assistente fica indisponível.

## Requisitos

- Windows 10/11 (alvo) — o núcleo também roda em Linux para desenvolvimento
- Python 3.12+ (testado com 3.14.4)

## Instalação no Windows

Em um PowerShell **sem** privilégios de administrador:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

Isso cria `.venv`, instala dependências, executa `sentinel init` e registra a
tarefa agendada **"Sentinel Agent"** (inicia no logon, privilégios limitados,
reinício automático em falha). Rodar de novo atualiza a instalação (o agente
antigo é parado de forma limpa antes). Para remover: `scripts\uninstall.ps1`
(os dados são mantidos).

Atalhos de dois cliques na raiz do projeto:

| Arquivo | Ação |
|---|---|
| `abrir-dashboard.bat` | abre o dashboard (link de acesso de uso único) |
| `status.bat` | estado do agente e eventos recentes |
| `verificar.bat` | verificação completa com relatório em `logs\verificacao-*.txt` |
| `parar.bat` | para o agente de forma limpa |
| `iniciar.bat` | roda o agente numa janela (depuração) |
| `instalar.bat` / `desinstalar.bat` | instala/atualiza ou remove a tarefa agendada |
| `ligar.bat` | liga o Sentinel agora (pela tarefa agendada) |
| `iniciar-com-windows.bat` | faz o Sentinel subir com o Windows, sem logon (pede a senha da conta) |
| `testar-ia.bat` | baixa o modelo e mede a IA local (Ollama): velocidade, memória e uso de ferramentas |
| `diagnosticar-ia.bat` | mede se o Ollama reaproveita a leitura das instruções entre perguntas (1–2 min) |
| `investigar-processo.bat` | relatório **somente leitura** sobre um executável suspeito (assinatura, hash, origem, inicialização automática) |

## Uso

```text
python -m sentinel init           # configuração, diretórios e banco (idempotente)
python -m sentinel run            # executa o agente em primeiro plano (Ctrl+C encerra)
python -m sentinel status         # última execução, heartbeat e eventos recentes
python -m sentinel check-config   # valida e mostra a configuração efetiva
python -m sentinel dashboard      # abre o dashboard em http://127.0.0.1:8765 com login de uso único
python -m sentinel stop           # pede ao agente que encerre de forma limpa
python -m sentinel selfcheck      # testa API, segurança, tempo real e gravação de métricas
python -m sentinel selfcheck --ai # uma pergunta real ao assistente (Ollama precisa estar ligado)
python -m sentinel ai-bench       # velocidade e precisão do modelo de IA nesta máquina
python -m sentinel server list    # servidores cadastrados e seus estados
python -m sentinel server restart <nome>   # também: start, stop
```

Códigos de saída: `0` ok · `1` erro · `2` configuração · `3` outra instância em execução · `4` banco.

Erros anteriores ao início do log (ex.: sob `pythonw.exe`, sem console) ficam em
`logs/startup-error.log`. O log principal é `logs/sentinel.log` (JSON por linha, com rotação).

## Desenvolvimento

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest
```

## Estrutura

```text
sentinel/
  agent/        CLI, configuração, ciclo de vida, agendador, logs, saúde, autoverificação
  core/         barramento de eventos, módulos, estado, gerenciador de recursos, exceções
  modules/      módulos funcionais (monitor, servers)
  api/          API local FastAPI + WebSocket, segurança
  oslayer/      tudo que é específico do sistema operacional
  database/     conexão SQLite, migrações versionadas, repositórios
dashboard/      interface web (HTML/CSS/JS, sem dependências externas)
config/         settings.yaml
scripts/        install / uninstall / start (PowerShell)
tests/          unit/ e integration/
docs/           decisões de arquitetura e documentação por módulo
```

Documentação: [docs/decisoes.md](docs/decisoes.md) e [docs/modulos/](docs/modulos/).
