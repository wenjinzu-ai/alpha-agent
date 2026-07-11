-- 005_agent_memory.sql
-- Agent 三层记忆表：Frozen / Episodic / SkillRef
-- 借鉴 Hermes 的 MEMORY.md / USER.md 设计，扩展为 PG 驱动的结构化记忆
--
-- 三层记忆模型：
--   1. Frozen Memory  - 持久的用户画像、偏好、知识（长期不变）
--   2. Episodic Memory - 会话级经验片段（自动过期/归档）
--   3. SkillRef Memory  - 成功使用的 Skill 引用（关联 agent_skills 表）

CREATE TABLE IF NOT EXISTS agent_memory (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(128) NOT NULL,
    user_id         VARCHAR(128) NOT NULL DEFAULT 'default',

    -- 记忆层级: frozen / episodic / skill_ref
    layer           VARCHAR(16) NOT NULL DEFAULT 'episodic',

    -- 记忆内容
    content         TEXT NOT NULL DEFAULT '',
    summary         TEXT NOT NULL DEFAULT '',

    -- 标签（用于分类和搜索）
    tags            TEXT[] DEFAULT '{}',

    -- 结构化元数据
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 关联技能（skill_ref 层）
    skill_name      VARCHAR(128),

    -- 重要性权重 (0-1)
    importance      REAL NOT NULL DEFAULT 0.5,

    -- 访问统计
    access_count    INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,

    -- 来源
    source          VARCHAR(32) NOT NULL DEFAULT 'conversation',
    -- conversation / skill_execution / user_explicit / review_loop

    -- 状态: active, archived, consolidated
    status          VARCHAR(16) NOT NULL DEFAULT 'active',

    -- 归档时间（episodic 记忆可设置 TTL）
    expires_at      TIMESTAMPTZ,
    archived_at     TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_memory_session    ON agent_memory (session_id);
CREATE INDEX IF NOT EXISTS idx_memory_user       ON agent_memory (user_id);
CREATE INDEX IF NOT EXISTS idx_memory_layer      ON agent_memory (layer);
CREATE INDEX IF NOT EXISTS idx_memory_status     ON agent_memory (status);
CREATE INDEX IF NOT EXISTS idx_memory_importance ON agent_memory (importance DESC);
CREATE INDEX IF NOT EXISTS idx_memory_tags       ON agent_memory USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_memory_metadata   ON agent_memory USING gin (metadata jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_memory_expires    ON agent_memory (expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_skill      ON agent_memory (skill_name) WHERE skill_name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_created    ON agent_memory (created_at DESC);

-- 更新时间触发器
CREATE OR REPLACE FUNCTION update_agent_memory_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_memory_updated_at ON agent_memory;
CREATE TRIGGER trg_memory_updated_at
    BEFORE UPDATE ON agent_memory
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_memory_updated_at();

-- 记忆合并表（记录 consolidated 操作的来源）
CREATE TABLE IF NOT EXISTS agent_memory_merges (
    id              SERIAL PRIMARY KEY,
    target_id       INTEGER NOT NULL REFERENCES agent_memory(id) ON DELETE CASCADE,
    source_ids      INTEGER[] NOT NULL DEFAULT '{}',
    merged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_merges_target ON agent_memory_merges (target_id);