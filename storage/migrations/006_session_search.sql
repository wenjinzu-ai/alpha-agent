-- 006_session_search.sql
-- 会话搜索与上下文压缩存储（PG tsvector 全文搜索）
-- 会话搜索，SQLite FTS5 改为 PG tsvector，功能更强

-- 会话记录表（全文搜索）
CREATE TABLE IF NOT EXISTS agent_sessions (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    user_message TEXT,
    assistant_message TEXT,
    tool_calls JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- tsvector 全文搜索列（自动生成）
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('simple',
            coalesce(user_message, '') || ' ' ||
            coalesce(assistant_message, '')
        )
    ) STORED
);

-- GIN 索引加速全文搜索
CREATE INDEX IF NOT EXISTS idx_agent_sessions_search
    ON agent_sessions USING GIN (search_vector);

-- 会话 ID 索引
CREATE INDEX IF NOT EXISTS idx_agent_sessions_session_id
    ON agent_sessions (session_id);

-- 时间索引（浏览模式）
CREATE INDEX IF NOT EXISTS idx_agent_sessions_created_at
    ON agent_sessions (created_at DESC);

-- 上下文快照表（存储压缩摘要）
CREATE TABLE IF NOT EXISTS agent_context_snapshots (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    compression_seq INT NOT NULL DEFAULT 0,
    summary_text TEXT,
    structured_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (session_id, compression_seq)
);

-- JSONB 索引加速结构化查询
CREATE INDEX IF NOT EXISTS idx_context_snapshots_structured
    ON agent_context_snapshots USING GIN (structured_data);

-- pg_trgm 扩展（模糊搜索）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- pg_trgm 索引加速摘要文本搜索
CREATE INDEX IF NOT EXISTS idx_context_snapshots_summary_trgm
    ON agent_context_snapshots USING GIN (summary_text gin_trgm_ops);

-- 会话 ID 索引
CREATE INDEX IF NOT EXISTS idx_context_snapshots_session_id
    ON agent_context_snapshots (session_id);