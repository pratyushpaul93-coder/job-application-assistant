-- Migration: add enrichment_cache table
-- Purpose: cache LLM-enriched company URLs for idempotent re-runs and onboarding hot path
-- Run via: sqlite3 workspace/jobapp.db < tools/migration_add_enrichment_cache.sql

CREATE TABLE IF NOT EXISTS enrichment_cache (
    name_normalized TEXT PRIMARY KEY,
    name_original   TEXT NOT NULL,
    url             TEXT,
    source          TEXT NOT NULL,           -- 'deepseek' | 'claude_websearch' | 'manual' | 'unknown'
    confidence      TEXT NOT NULL,           -- 'high' | 'medium' | 'low' | 'none'
    head_status     INTEGER,                 -- HTTP status from HEAD verify; NULL if skipped
    reasoning       TEXT,                    -- Model-provided rationale for audit
    checked_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_enrichment_source     ON enrichment_cache(source);
CREATE INDEX IF NOT EXISTS idx_enrichment_confidence ON enrichment_cache(confidence);
CREATE INDEX IF NOT EXISTS idx_enrichment_checked_at ON enrichment_cache(checked_at);
