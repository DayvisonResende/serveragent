-- Fase 3 — Servidores cadastrados, verificações de saúde e incidentes.

CREATE TABLE servers (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description            TEXT NOT NULL DEFAULT '',
    server_type            TEXT NOT NULL,
    management             TEXT NOT NULL CHECK (management IN ('managed', 'observed')),
    executable             TEXT,
    arguments_json         TEXT NOT NULL DEFAULT '[]',
    working_directory      TEXT,
    port                   INTEGER CHECK (port IS NULL OR (port BETWEEN 1 AND 65535)),
    protocol               TEXT NOT NULL DEFAULT 'tcp',
    health_check_json      TEXT NOT NULL DEFAULT '{}',
    process_match_json     TEXT NOT NULL DEFAULT '{}',
    log_path               TEXT,
    criticality            TEXT NOT NULL CHECK (criticality IN ('low', 'medium', 'high', 'critical')),
    startup_grace_seconds  INTEGER NOT NULL DEFAULT 30,
    enabled                INTEGER NOT NULL DEFAULT 1,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);

CREATE TABLE server_checks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id         INTEGER NOT NULL REFERENCES servers (id) ON DELETE CASCADE,
    timestamp         TEXT NOT NULL,
    ts_epoch          REAL NOT NULL,
    state             TEXT NOT NULL,
    process_alive     INTEGER NOT NULL,
    pid               INTEGER,
    port_listening    INTEGER,          -- NULL quando não se aplica
    health_status     TEXT NOT NULL,    -- ok | fail | timeout | skipped
    response_time_ms  REAL,
    error_message     TEXT
);
CREATE INDEX idx_server_checks_server ON server_checks (server_id, ts_epoch);
CREATE INDEX idx_server_checks_epoch ON server_checks (ts_epoch);

-- O nome do servidor é copiado para o incidente: o histórico sobrevive à exclusão do cadastro.
CREATE TABLE incidents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id      INTEGER REFERENCES servers (id) ON DELETE SET NULL,
    server_name    TEXT NOT NULL,
    kind           TEXT NOT NULL,       -- offline | unresponsive | degraded
    severity       TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'high', 'critical')),
    title          TEXT NOT NULL,
    timeline_json  TEXT NOT NULL DEFAULT '[]',
    opened_at      TEXT NOT NULL,
    opened_epoch   REAL NOT NULL,
    closed_at      TEXT,
    closed_epoch   REAL,
    resolution     TEXT
);
CREATE INDEX idx_incidents_server ON incidents (server_id, opened_epoch);
CREATE INDEX idx_incidents_open ON incidents (closed_epoch);
