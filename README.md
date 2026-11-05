# Sentinel

Agente local de administração, monitoramento e manutenção de servidores Windows.
Especificação completa em [PRD.md](PRD.md).

**Estado atual:** Fase 1 — Fundação concluída. Ainda não há monitoramento,
dashboard ou IA: o agente inicia, mantém heartbeat, registra eventos e
auditoria, e encerra de forma limpa. As próximas fases constroem sobre isso.

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
reinício automático em falha). Para remover: `scripts\uninstall.ps1` (os dados
são mantidos).

## Uso

```text
python -m sentinel init           # configuração, diretórios e banco (idempotente)
python -m sentinel run            # executa o agente em primeiro plano (Ctrl+C encerra)
python -m sentinel status         # última execução, heartbeat e eventos recentes
python -m sentinel check-config   # valida e mostra a configuração efetiva
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
  agent/        CLI, configuração, ciclo de vida, agendador, logs, saúde
  core/         barramento de eventos, registro de módulos, estado, exceções
  oslayer/      tudo que é específico do sistema operacional
  database/     conexão SQLite, migrações versionadas, repositórios
config/         settings.yaml
scripts/        install / uninstall / start (PowerShell)
tests/          unit/ e integration/
docs/           decisões de arquitetura e documentação por módulo
```

Documentação: [docs/decisoes.md](docs/decisoes.md) e [docs/modulos/](docs/modulos/).
