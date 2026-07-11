-- 004_agent_skills.sql
-- Agent 技能表：结构化 Skill 存储，JSONB 索引 + 全文搜索
-- 借鉴 Hermes 的 skill_manage 设计，扩展为 PG 驱动

CREATE TABLE IF NOT EXISTS agent_skills (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(128) NOT NULL UNIQUE,
    display_name    VARCHAR(256) NOT NULL DEFAULT '',
    category        VARCHAR(64) NOT NULL DEFAULT 'general',
    description     TEXT NOT NULL DEFAULT '',
    trigger_keywords TEXT[] DEFAULT '{}',

    -- SKILL.md 的完整内容（YAML frontmatter + markdown body）
    content         TEXT NOT NULL DEFAULT '',

    -- 结构化元数据
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 技能状态: active, retired, deprecated
    status          VARCHAR(16) NOT NULL DEFAULT 'active',

    -- 来源: agent_created, hub_imported, preset, user_created
    source          VARCHAR(32) NOT NULL DEFAULT 'user_created',

    -- 父技能（fork 来源）
    parent_name     VARCHAR(128),

    -- 使用统计
    use_count       INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    fail_count      INTEGER NOT NULL DEFAULT 0,
    last_used_at    TIMESTAMPTZ,
    last_patched_at TIMESTAMPTZ,

    -- 版本号（每次 patch 递增）
    version         INTEGER NOT NULL DEFAULT 1,

    -- 是否置顶（防止误删）
    pinned          BOOLEAN NOT NULL DEFAULT FALSE,

    -- 创建者
    created_by      VARCHAR(64) NOT NULL DEFAULT 'user',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_skills_category     ON agent_skills (category);
CREATE INDEX IF NOT EXISTS idx_skills_status        ON agent_skills (status);
CREATE INDEX IF NOT EXISTS idx_skills_source        ON agent_skills (source);
CREATE INDEX IF NOT EXISTS idx_skills_use_count     ON agent_skills (use_count DESC);
CREATE INDEX IF NOT EXISTS idx_skills_parent        ON agent_skills (parent_name) WHERE parent_name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_skills_metadata      ON agent_skills USING gin (metadata jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_skills_keywords      ON agent_skills USING gin (trigger_keywords);
CREATE INDEX IF NOT EXISTS idx_skills_created       ON agent_skills (created_at DESC);

-- 全文搜索索引（pg_trgm 扩展，阶段三启用）
-- CREATE INDEX IF NOT EXISTS idx_skills_search ON agent_skills USING gin (name gin_trgm_ops, description gin_trgm_ops);

-- 更新时间触发器
CREATE OR REPLACE FUNCTION update_agent_skills_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_skills_updated_at ON agent_skills;
CREATE TRIGGER trg_skills_updated_at
    BEFORE UPDATE ON agent_skills
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_skills_updated_at();

-- 技能关联表（related_skills）
CREATE TABLE IF NOT EXISTS agent_skill_relations (
    id          SERIAL PRIMARY KEY,
    skill_name  VARCHAR(128) NOT NULL REFERENCES agent_skills(name) ON DELETE CASCADE,
    related_name VARCHAR(128) NOT NULL REFERENCES agent_skills(name) ON DELETE CASCADE,
    relation_type VARCHAR(32) NOT NULL DEFAULT 'related',  -- related, prerequisite, supersedes
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (skill_name, related_name)
);

CREATE INDEX IF NOT EXISTS idx_skill_relations_skill ON agent_skill_relations (skill_name);