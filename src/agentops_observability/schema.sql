CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','completed','failed','cancelled')),
    created_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL CHECK (prompt_tokens >= 0),
    completion_tokens INTEGER NOT NULL CHECK (completion_tokens >= 0),
    total_tokens INTEGER NOT NULL CHECK (total_tokens >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL, latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    success INTEGER NOT NULL CHECK (success IN (0,1)), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS retries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    retry_count INTEGER NOT NULL CHECK (retry_count >= 1), operation TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    error_type TEXT NOT NULL, error_message TEXT NOT NULL,
    fatal INTEGER NOT NULL CHECK (fatal IN (0,1)), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    dimension TEXT NOT NULL, quality_score REAL NOT NULL CHECK (quality_score BETWEEN 0 AND 1),
    metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_session ON llm_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_retries_session ON retries(session_id);
CREATE INDEX IF NOT EXISTS idx_errors_session ON errors(session_id);
CREATE INDEX IF NOT EXISTS idx_quality_scores_session ON quality_scores(session_id);
