-- Fase 2 — Monitoramento, sessões do dashboard e encerramento pelo Windows.
-- ts_epoch (segundos UTC) acompanha o timestamp ISO para consultas por intervalo e agregação.

CREATE TABLE system_metrics (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    ts_epoch          REAL NOT NULL,
    sample_count      INTEGER NOT NULL CHECK (sample_count > 0),
    cpu_percent       REAL NOT NULL,          -- média da janela
    cpu_percent_max   REAL NOT NULL,          -- pico da janela
    ram_used          INTEGER NOT NULL,
    ram_available     INTEGER NOT NULL,
    ram_percent       REAL NOT NULL,
    swap_used         INTEGER,
    disk_used         INTEGER,                -- soma das partições locais
    disk_free         INTEGER,
    network_upload    REAL,                   -- bytes/s, média da janela (NULL sem medição)
    network_download  REAL
);
CREATE INDEX idx_system_metrics_epoch ON system_metrics (ts_epoch);

CREATE TABLE process_snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT NOT NULL,
    ts_epoch         REAL NOT NULL,
    pid              INTEGER NOT NULL,
    process_name     TEXT NOT NULL,
    executable_path  TEXT,
    cpu_percent      REAL,
    memory_bytes     INTEGER,
    status           TEXT
);
CREATE INDEX idx_process_snapshots_epoch ON process_snapshots (ts_epoch);
CREATE INDEX idx_process_snapshots_name ON process_snapshots (process_name, ts_epoch);

CREATE TABLE disk_usage_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    ts_epoch    REAL NOT NULL,
    mountpoint  TEXT NOT NULL,
    device      TEXT NOT NULL,
    total       INTEGER NOT NULL,
    used        INTEGER NOT NULL,
    free        INTEGER NOT NULL
);
CREATE INDEX idx_disk_usage_history ON disk_usage_history (mountpoint, ts_epoch);

-- Apenas hashes SHA-256 de valores aleatórios de 256 bits são armazenados (PRD 17.5).
CREATE TABLE sessions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash        TEXT NOT NULL UNIQUE,
    created_at        TEXT NOT NULL,
    expires_at_epoch  REAL NOT NULL
);

CREATE TABLE login_codes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code_hash         TEXT NOT NULL UNIQUE,
    created_at        TEXT NOT NULL,
    expires_at_epoch  REAL NOT NULL,
    used_at           TEXT
);

-- agent_runs ganha o status 'system_shutdown' (desligamento/logoff do Windows).
-- SQLite não altera CHECK existente: a tabela é reconstruída preservando os dados.
CREATE TABLE agent_runs_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pid             INTEGER NOT NULL,
    version         TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    last_heartbeat  TEXT NOT NULL,
    stopped_at      TEXT,
    exit_status     TEXT CHECK (exit_status IN ('clean', 'failed', 'interrupted', 'unclean', 'system_shutdown'))
);
INSERT INTO agent_runs_new (id, pid, version, started_at, last_heartbeat, stopped_at, exit_status)
    SELECT id, pid, version, started_at, last_heartbeat, stopped_at, exit_status FROM agent_runs;
DROP TABLE agent_runs;
ALTER TABLE agent_runs_new RENAME TO agent_runs;
