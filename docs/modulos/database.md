# sentinel.database

**Objetivo:** persistência isolada atrás de repositórios, para permitir uma
troca futura de SQLite por PostgreSQL (PRD 16).

| Arquivo | Responsabilidade |
|---|---|
| `database.py` | Conexão única em thread dedicada; `execute`, `insert`, `fetch_*`, `run` (transação), `integrity_check` |
| `migrations.py` | Descoberta e aplicação de `migrations/NNNN_nome.sql`, uma transação por arquivo |
| `repositories/events.py` | Gravação e leitura de eventos |
| `repositories/audit.py` | Auditoria somente-inserção |
| `repositories/agent_runs.py` | Execuções do agente, heartbeat, detecção de encerramento inesperado |

## Esquema (migração 0001)

- `events` — índices por `timestamp` e por `(event_type, timestamp)`; `severity` com `CHECK`.
- `audit_logs` — triggers bloqueiam `UPDATE`/`DELETE`.
- `agent_runs` — `exit_status` ∈ `clean`, `failed`, `interrupted`, `unclean`.
- `schema_migrations` — controle de versões.

Timestamps são texto ISO-8601 UTC com milissegundos (ordenáveis como texto).

## Regras

- Novas tabelas = nova migração; migrações aplicadas nunca são editadas.
- Banco com versão desconhecida (de um Sentinel mais novo) é recusado.
- Integridade (`PRAGMA quick_check`) verificada a cada inicialização (configurável).
- Pragmas: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout`.

**Configuração:** seção `database`, `paths.database_file`.
**Testes:** `tests/unit/test_database.py`.
**Limitações:** ainda sem backup, retenção ou rotação (Fases 2 e 6).
Empacotar com PyInstaller exigirá incluir a pasta `migrations/` como dado.
