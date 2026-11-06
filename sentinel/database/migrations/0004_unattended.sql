-- Operação sem supervisão: política de reinício automático, configurações editáveis
-- pelo dashboard e segredos protegidos (ex.: token do bot do Telegram).

ALTER TABLE servers ADD COLUMN restart_policy_json TEXT NOT NULL DEFAULT '{}';

-- Configurações alteradas pelo dashboard (as de infraestrutura continuam no settings.yaml).
CREATE TABLE settings_kv (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Segredos nunca em texto puro (PRD 17.5): no Windows, cifrados com DPAPI (ligados à conta do usuário).
CREATE TABLE secrets (
    name        TEXT PRIMARY KEY,
    protection  TEXT NOT NULL CHECK (protection IN ('dpapi', 'none')),
    value       BLOB NOT NULL,
    updated_at  TEXT NOT NULL
);
