-- scdchain 客户注销撤回 (retraction) — PostgreSQL 16
-- Runtime bootstraps the same DDL via SQLAlchemy create_all(); this file is the
-- authoritative, re-runnable snapshot for review / offline provisioning.

CREATE TABLE IF NOT EXISTS retraction_batches (
    id SERIAL PRIMARY KEY,
    business_key VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    impact JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_by VARCHAR(120) NOT NULL DEFAULT '',
    requested_at TIMESTAMP NOT NULL DEFAULT now(),
    confirmed_by VARCHAR(120) NOT NULL DEFAULT '',
    confirmed_at TIMESTAMP,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    baseline_run_id INTEGER,
    applied_run_id INTEGER,
    restored_at TIMESTAMP,
    error_message VARCHAR(512) NOT NULL DEFAULT '',
    notes VARCHAR(255) NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_retraction_batches_status ON retraction_batches (status);
CREATE UNIQUE INDEX IF NOT EXISTS ix_retraction_batches_business_key ON retraction_batches (business_key);

CREATE TABLE IF NOT EXISTS retraction_backups (
    id SERIAL PRIMARY KEY,
    retraction_id INTEGER NOT NULL REFERENCES retraction_batches(id),
    entity_type VARCHAR(16) NOT NULL,
    row_id INTEGER NOT NULL,
    original JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_retraction_backup_row UNIQUE (retraction_id, entity_type, row_id)
);
CREATE INDEX IF NOT EXISTS ix_retraction_backups_retraction_id ON retraction_backups (retraction_id);

-- Read paths do not rely on a new index: retraction always filters by
-- business_key, which is already indexed on every personal-data table.
