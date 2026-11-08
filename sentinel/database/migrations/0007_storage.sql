-- Fase 6 — Análise de armazenamento, limpeza e quarentena (PRD 8, 16.1).

CREATE TABLE storage_analyses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    trigger       TEXT NOT NULL,                 -- usuario | agendada | ia | autoteste
    summary_json  TEXT NOT NULL DEFAULT '{}',    -- totais por categoria, pastas maiores, avisos
    error         TEXT
);

-- Achados de uma análise: candidatos à limpeza e itens só informativos.
CREATE TABLE storage_findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id   INTEGER NOT NULL REFERENCES storage_analyses (id) ON DELETE CASCADE,
    category      TEXT NOT NULL CHECK (category IN ('temp', 'old_log', 'large', 'duplicate')),
    path          TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    modified_at   REAL NOT NULL,                 -- epoch: revalidado antes de mover
    group_key     TEXT,                          -- duplicados: hash do conteúdo
    keep          INTEGER NOT NULL DEFAULT 0,    -- duplicados: a cópia que fica
    cleanable     INTEGER NOT NULL DEFAULT 1,    -- 0 = fora das pastas autorizadas ou protegido (só informativo)
    note          TEXT
);
CREATE INDEX idx_storage_findings_analysis ON storage_findings (analysis_id, category);

-- Plano de limpeza (status 'proposed') que vira relatório depois de executado (PRD 16.1).
CREATE TABLE cleanup_reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT NOT NULL,
    analysis_id       INTEGER,
    requested_by      TEXT NOT NULL,
    files_found       INTEGER NOT NULL,
    bytes_recoverable INTEGER NOT NULL,
    files_moved       INTEGER NOT NULL DEFAULT 0,
    files_deleted     INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL CHECK (status IN ('proposed', 'completed', 'partial', 'failed', 'discarded')),
    finished_at       TEXT,
    details_json      TEXT NOT NULL DEFAULT '{}'  -- itens do plano e resultado de cada um
);

CREATE TABLE quarantine_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id       INTEGER NOT NULL REFERENCES cleanup_reports (id),
    original_path   TEXT NOT NULL,
    stored_path     TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    sha256          TEXT,
    modified_at     REAL,
    category        TEXT NOT NULL,
    reason          TEXT NOT NULL,
    quarantined_at  TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('quarantined', 'restored', 'deleted')),
    resolved_at     TEXT,
    resolved_by     TEXT
);
CREATE INDEX idx_quarantine_status ON quarantine_items (status, quarantined_at);
