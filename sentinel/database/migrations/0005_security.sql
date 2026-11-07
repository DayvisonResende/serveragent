-- Fase 4 — Ações, aprovações (PRD 11.3/11.4/16.1) e linha de base da inicialização automática.

CREATE TABLE actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type     TEXT NOT NULL,                 -- operação do catálogo fechado (ex.: server_restart)
    target          TEXT NOT NULL,                 -- nome legível do alvo
    target_id       INTEGER,
    params_json     TEXT NOT NULL DEFAULT '{}',
    fingerprint     TEXT NOT NULL,                 -- operação + alvo + estado do cadastro no momento do pedido
    risk_level      INTEGER NOT NULL CHECK (risk_level BETWEEN 0 AND 3),
    requested_by    TEXT NOT NULL,
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN
                        ('pending', 'approved', 'rejected', 'expired', 'executing', 'completed', 'failed', 'cancelled')),
    approval_id     INTEGER,
    created_at      TEXT NOT NULL,
    created_epoch   REAL NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    result_json     TEXT,
    error_message   TEXT
);
CREATE INDEX idx_actions_status ON actions (status, created_epoch);
CREATE INDEX idx_actions_target ON actions (action_type, target_id, status);

CREATE TABLE approvals (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id              INTEGER NOT NULL UNIQUE REFERENCES actions (id),
    requested_at           TEXT NOT NULL,
    expires_at             TEXT NOT NULL,
    expires_epoch          REAL NOT NULL,
    decided_at             TEXT,
    decided_by             TEXT,
    status                 TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
    impact                 TEXT NOT NULL,
    risks                  TEXT NOT NULL,
    requires_confirmation  INTEGER NOT NULL DEFAULT 0,
    note                   TEXT
);
CREATE INDEX idx_approvals_status ON approvals (status, expires_epoch);

-- Itens que iniciam automaticamente (registro Run, Winlogon, tarefas, serviços…), para detectar mudanças.
CREATE TABLE autostart_entries (
    key          TEXT PRIMARY KEY,                -- local|nome
    location     TEXT NOT NULL,
    name         TEXT NOT NULL,
    value        TEXT NOT NULL,
    suspicious   INTEGER NOT NULL DEFAULT 0,
    reasons      TEXT NOT NULL DEFAULT '[]',
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);
