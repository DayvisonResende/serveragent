-- Fase 5 — Histórico do chat com a IA (PRD 16.1).

CREATE TABLE chat_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    message          TEXT NOT NULL,
    context_json     TEXT NOT NULL DEFAULT '{}',   -- ferramentas consultadas, tempos, modelo
    timestamp        TEXT NOT NULL
);
CREATE INDEX idx_chat_history_conversation ON chat_history (conversation_id, id);
