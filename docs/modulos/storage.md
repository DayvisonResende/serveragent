# sentinel.modules.cleaner

**Objetivo:** mostrar o que ocupa o disco e liberar espaço com segurança (PRD 8):
análise → recomendação → aprovação → execução, sempre com volta possível.

| Arquivo | Responsabilidade |
|---|---|
| `scope.py` | Pastas autorizadas (padrão: temporários e Downloads) e proteções (PRD 8.6) |
| `analyzer.py` | Análise somente leitura: pastas que mais ocupam, temporários e logs antigos, grandes, duplicados |
| `quarantine.py` | Mover para `data/quarantine/limpeza-<id>/`, restaurar, excluir |
| `module.py` | `CleanerModule`: análise em segundo plano, planos, operações do catálogo, retenção |
| `database/repositories/storage.py` | Tabelas `storage_analyses`, `storage_findings`, `cleanup_reports`, `quarantine_items` |

## O que é limpável

Só arquivos dentro das **pastas autorizadas** (editáveis na página Armazenamento) e
que não estejam protegidos. Nunca são tocados, mesmo dentro delas: pasta do Windows,
Arquivos de Programas, ProgramData, pastas Inicializar, o próprio Sentinel e seus
dados, pastas dos servidores cadastrados (trabalho, executável, log), arquivos com
atributo de sistema, bancos de dados (`.db`, `.sqlite`, `.mdf`, …) e arquivos do
OneDrive que estão só na nuvem. Não é possível autorizar um disco inteiro, a pasta
pessoal inteira ou uma pasta protegida.

A **visão do disco** (opcional, ligada por padrão) mede as pastas de todos os
discos para mostrar "o que ocupa espaço" — só leitura. Arquivos grandes fora das
pastas autorizadas aparecem como informativos.

## Categorias

| Categoria | Regra (settings.yaml, seção `storage`) |
|---|---|
| Temporários antigos | na pasta de temporários, sem alteração há `temp_min_age_days` (7) |
| Logs antigos | `.log`, `.log.N`, `.old` sem alteração há `log_min_age_days` (30) |
| Duplicados | ≥ `duplicate_min_mb` (1 MB); mesmo tamanho → mesmo início e fim → mesmo SHA-256; fica a cópia mais antiga |
| Arquivos grandes | ≥ `large_file_mb` (200 MB), os 50 maiores |

Duplicados leem no máximo `max_hash_gb` (4 GB) por análise; os maiores grupos
primeiro. Links e junções não são seguidos. A análise pausa sob pressão severa.

## Execução

| Operação (catálogo) | Nível | Quem aprova |
|---|---|---|
| `cleanup_quarantine` (plano de limpeza) | 2 | o clique do usuário; pedido da IA fica pendente |
| `quarantine_restore` | 1 | o clique do usuário |
| `quarantine_delete` (uma limpeza inteira) | 3 | usuário, digitando `limpeza #N` |

Antes de mover, cada arquivo é revalidado: ainda existe, mesmo tamanho e data da
análise, dentro das pastas autorizadas, não protegido. O que mudou é ignorado e
aparece no relatório. A quarentena tem limite (`quarantine_max_gb`, 5 GB) e
retenção (`quarantine_retention_days`, 30 dias: depois disso o item é excluído
pela `politica-retencao`, com registro na auditoria).

**Atenção:** mover para a quarentena no mesmo disco não libera espaço. O espaço
volta quando a limpeza é excluída definitivamente ou quando a retenção vence.

## API

| Rota | Uso |
|---|---|
| `GET /api/v1/storage/status` | análise em andamento, última análise, quarentena, pastas autorizadas |
| `POST /api/v1/storage/analyze` `{full_disk?}` | inicia (202); 409 se já houver uma |
| `POST /api/v1/storage/analyze/cancel` | cancela |
| `GET /api/v1/storage/findings?category=` | achados da última análise (omite o que já não existe) |
| `POST /api/v1/storage/plans` `{finding_ids? , category?}` | monta um plano (relatório `proposed`) |
| `POST /api/v1/storage/plans/{id}/discard` | descarta um plano não executado |
| `GET /api/v1/storage/reports[/{id}]` | relatórios de limpeza |
| `GET /api/v1/storage/quarantine` | itens na quarentena |
| `PUT /api/v1/storage/authorized` `{folders}` | pastas autorizadas (recusa as proibidas) |

Executar, restaurar e excluir: `POST /api/v1/actions` com a operação do catálogo.

## IA

`get_storage_analysis` (resumo da última análise) e `request_cleanup(category)`,
que cria um plano e um pedido **pendente** em Aprovações.

## Verificação

`verificar.bat`, etapa 9 (`sentinel selfcheck --storage`): arquivos de teste em
`%TEMP%\sentinel-autoteste-*` passam por análise, quarentena, restauração e
exclusão com confirmação; um `.db` antigo prova que bancos de dados não são
sugeridos. A pasta de teste é apagada no final.
