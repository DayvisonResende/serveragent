-- Fase 1 — Fundação: eventos, auditoria e execuções do agente.

CREATE TABLE events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type     TEXT NOT NULL,
    severity       TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'high', 'critical')),
    source         TEXT NOT NULL,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    metadata_json  TEXT NOT NULL DEFAULT '{}',
    timestamp      TEXT NOT NULL
);

CREATE INDEX idx_events_timestamp ON events (timestamp);
CREATE INDEX idx_events_type_timestamp ON events (event_type, timestamp);

-- Auditoria somente-inserção (PRD 11.6): UPDATE e DELETE são bloqueados no próprio banco.
CREATE TABLE audit_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    actor         TEXT NOT NULL,
    operation     TEXT NOT NULL,
    target        TEXT,
    reason        TEXT,
    approval_id   INTEGER,
    result        TEXT NOT NULL,
    details_json  TEXT NOT NULL DEFAULT '{}',
    timestamp     TEXT NOT NULL
);

CREATE INDEX idx_audit_logs_timestamp ON audit_logs (timestamp);

CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs é somente-inserção');
END;

CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs é somente-inserção');
END;

-- Cada execução do agente. stopped_at NULL em uma execução antiga indica
-- encerramento inesperado (queda, TerminateProcess, desligamento forçado).
CREATE TABLE agent_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pid             INTEGER NOT NULL,
    version         TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    last_heartbeat  TEXT NOT NULL,
    stopped_at      TEXT,
    exit_status     TEXT CHECK (exit_status IN ('clean', 'failed', 'interrupted', 'unclean'))
);
