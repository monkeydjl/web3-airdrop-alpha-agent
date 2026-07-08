# 数据库完整 DDL

> 配套文档：ENGINEERING_ROADMAP.md §5、DATA_SCORING_DICT.md §1-2。本文档汇总所有表的完整 DDL 定义，供实现阶段 `init_db()` 与迁移脚本直接照做。
>
> 适用阶段：MVP（SQLite WAL）→ V2（PostgreSQL）。MVP 与 V2 差异处用注释标注。

---

## 1. 设计原则

1. **幂等建表**：所有 `CREATE TABLE` 使用 `IF NOT EXISTS`，重复调用不报错。
2. **JSON 列**：SQLite 用 `TEXT` 存 JSON（应用层校验）；V2 PostgreSQL 可改 `JSONB`。
3. **时间戳**：统一 `TIMESTAMP` 类型，应用层写入 UTC。
4. **外键**：MVP 不启用外键约束（SQLite 需 `PRAGMA foreign_keys=ON`）；V2 启用。
5. **索引**：查询频繁的字段加索引，写入频繁的表控制索引数量。

---

## 2. MVP DDL（SQLite WAL）

```sql
-- init_db() 完整脚本（MVP）
-- 使用：sqlite3 airdrop.db < database_ddl.sql

-- 启用 WAL 模式（需在连接时执行，非 DDL）
-- PRAGMA journal_mode=WAL;
-- PRAGMA foreign_keys=ON;

-- ============================================
-- 2.1 projects 表（核心项目表）
-- ============================================
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,           -- UUID v5（dedup_key 确定性生成）
    name            TEXT NOT NULL,              -- 项目名称
    url             TEXT,                       -- 官网地址
    sector          TEXT NOT NULL,              -- 赛道（标准化后）
    stage           TEXT NOT NULL,              -- 项目阶段：testnet/mainnet/ideation
    
    score           INTEGER DEFAULT 0,          -- 综合评分 0-100
    label           TEXT DEFAULT 'IGNORE',      -- FARM/WATCH/IGNORE
    recommendation  TEXT DEFAULT 'IGNORE',      -- 参与建议（同 label）
    confidence      REAL DEFAULT 0.0,           -- 数据完整度 0-1（v1.5 新增）
    weight_version  TEXT DEFAULT 'v1',          -- 评分权重版本（ADR-006）
    
    reason          TEXT,                       -- 决策理由 JSON 数组
    narrative_json  TEXT,                       -- NarrativeResult JSON
    team_json       TEXT,                       -- TeamResult JSON
    risk_json       TEXT,                       -- RiskResult JSON
    tokenomics_json TEXT,                       -- TokenomicsResult JSON
    
    raw_signals     TEXT,                       -- 原始信号 JSON（含 sources[]）
    meta            TEXT,                       -- 元数据 JSON（missing_count 等）

    fetched_at      TIMESTAMP,                  -- 外部源采集时间（V2 填充；MVP seed 为 NULL）    
    source          TEXT NOT NULL,              -- 主数据源：seed/defillama/cryptorank/twitter
    raw_signals_hash TEXT,                      -- raw_signals 稳定哈希（用于变化检测）
    
    created_at      TIMESTAMP DEFAULT (datetime('now')),  -- 首次写入 UTC
    updated_at      TIMESTAMP DEFAULT (datetime('now'))   -- 末次更新 UTC
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_projects_score ON projects(score DESC);
CREATE INDEX IF NOT EXISTS idx_projects_label ON projects(label);
CREATE INDEX IF NOT EXISTS idx_projects_sector ON projects(sector);
CREATE INDEX IF NOT EXISTS idx_projects_stage ON projects(stage);
CREATE INDEX IF NOT EXISTS idx_projects_source ON projects(source);
CREATE INDEX IF NOT EXISTS idx_projects_created ON projects(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);

-- 复合索引（常用查询组合）
CREATE INDEX IF NOT EXISTS idx_projects_label_score ON projects(label, score DESC);
CREATE INDEX IF NOT EXISTS idx_projects_sector_score ON projects(sector, score DESC);


-- ============================================
-- 2.2 logs 表（Agent 执行日志）
-- ============================================
CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,                  -- pipeline 运行 ID
    project_id  TEXT,                           -- 关联项目（全局事件可为 NULL）
    agent_name  TEXT NOT NULL,                  -- Agent 名称
    input       TEXT,                           -- Agent 输入 JSON
    output      TEXT,                           -- Agent 输出 JSON
    error       TEXT,                           -- AgentError JSON（成功时为 NULL)
    duration_ms INTEGER,                        -- 执行耗时（毫秒）
    timestamp   TIMESTAMP DEFAULT (datetime('now'))  -- 写入时间 UTC
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_logs_run_id ON logs(run_id);
CREATE INDEX IF NOT EXISTS idx_logs_project_id ON logs(project_id);
CREATE INDEX IF NOT EXISTS idx_logs_agent_name ON logs(agent_name);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp DESC);


-- ============================================
-- 2.3 events 表（用户行为事件，V2 起）
-- ============================================
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT,                           -- 关联项目
    user_id     TEXT,                           -- 匿名用户 token（V2）
    event_type  TEXT NOT NULL,                  -- click/expand/feedback/...
    detail      TEXT,                           -- 事件详情 JSON
    timestamp   TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_project_id ON events(project_id);
CREATE INDEX IF NOT EXISTS idx_events_user_id ON events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);


-- ============================================
-- 2.4 feedback 表（用户反馈，V2 起）
-- ============================================
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT,                           -- 关联项目
    user_id     TEXT,                           -- 匿名用户 token（V2）
    signal      TEXT NOT NULL,                  -- useful/useless/wrong_label/correct_outcome
    note        TEXT,                           -- 用户备注（最长 500 字符）
    outcome     TEXT,                           -- airdropped/not_airdropped/pumped/dumped/null
    created_at  TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_feedback_project_id ON feedback(project_id);
CREATE INDEX IF NOT EXISTS idx_feedback_signal ON feedback(signal);
CREATE INDEX IF NOT EXISTS idx_feedback_outcome ON feedback(outcome);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);


-- ============================================
-- 2.5 quarantine 表（脏数据隔离，V2 起）
-- ============================================
CREATE TABLE IF NOT EXISTS quarantine (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT,                       -- 关联项目（可能为 NULL）
    raw_data        TEXT NOT NULL,              -- 原始数据 JSON
    failure_reason  TEXT NOT NULL,              -- schema_violation/business_rule_violation/accuracy_mismatch/reference_error/dedup_conflict
    severity        TEXT DEFAULT 'warning',     -- warning/critical
    status          TEXT DEFAULT 'pending',     -- pending/resolved/discarded
    resolved_at     TIMESTAMP,                  -- 解决时间
    created_at      TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_quarantine_status ON quarantine(status);
CREATE INDEX IF NOT EXISTS idx_quarantine_reason ON quarantine(failure_reason);
CREATE INDEX IF NOT EXISTS idx_quarantine_created ON quarantine(created_at DESC);


-- ============================================
-- 2.6 project_history 表（项目历史快照，V2 起）
-- ============================================
CREATE TABLE IF NOT EXISTS project_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,                  -- 关联项目
    run_id      TEXT NOT NULL,                  -- pipeline 运行 ID
    score       INTEGER,                        -- 本次评分
    label       TEXT,                           -- 本次 label
    stage       TEXT,                           -- 本次 stage
    weight_version TEXT,                        -- 权重版本
    snapshot    TEXT NOT NULL,                  -- 完整快照 JSON
    created_at  TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_project_history_project_id ON project_history(project_id);
CREATE INDEX IF NOT EXISTS idx_project_history_run_id ON project_history(run_id);
CREATE INDEX IF NOT EXISTS idx_project_history_created ON project_history(created_at DESC);


-- ============================================
-- 2.6b narratives 维表（赛道元数据，V2）
-- ============================================
CREATE TABLE IF NOT EXISTS narratives (
    sector          TEXT PRIMARY KEY,   -- 标准赛道名（§6.2.1 sector_key）
    aliases         TEXT,               -- JSON: ["restake","restaking"]
    base_heat       REAL,               -- 基础热度 0-1
    stage           TEXT,               -- early|growth|peak|mature
    momentum        REAL,               -- 动量修正系数
    updated_at      TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_narratives_stage ON narratives(stage);


-- ============================================
-- 2.7 audit_logs 表（审计日志，V2 起）
-- ============================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,                  -- run/re-score/config_change/weight_change
    user        TEXT NOT NULL,                  -- system/manual/api_key_name
    detail      TEXT,                           -- 操作详情
    ip          TEXT,                           -- 触发 IP
    created_at  TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);


-- ============================================
-- 2.8 weight_changelog 表（权重变更记录，V2 起）
-- ============================================
CREATE TABLE IF NOT EXISTS weight_changelog (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_version    TEXT NOT NULL,              -- 旧版本
    to_version      TEXT NOT NULL,              -- 新版本
    old_weights     TEXT NOT NULL,              -- 旧权重 JSON
    new_weights     TEXT NOT NULL,              -- 新权重 JSON
    trigger_samples INTEGER,                    -- 触发样本数
    metrics_before  TEXT,                       -- 变更前指标 JSON
    metrics_after   TEXT,                       -- 变更后指标 JSON
    changed_by      TEXT NOT NULL,              -- 变更触发者
    created_at      TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_weight_changelog_created ON weight_changelog(created_at DESC);


-- ============================================
-- 2.9 llm_eval_changelog 表（LLM 评估记录，V2 起）
-- ============================================
CREATE TABLE IF NOT EXISTS llm_eval_changelog (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_date       TIMESTAMP NOT NULL,         -- 评估日期
    sample_count    INTEGER NOT NULL,           -- 样本数
    rule_accuracy   REAL NOT NULL,              -- 规则准确率
    llm_accuracy    REAL NOT NULL,              -- LLM 准确率
    llm_cost_usd    REAL NOT NULL,              -- LLM 成本
    decision        TEXT NOT NULL,              -- keep_llm/disable_llm/adjust_weights
    detail          TEXT,                       -- 评估报告 JSON
    created_at      TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_llm_eval_date ON llm_eval_changelog(eval_date DESC);


-- ============================================
-- 2.10 metrics 表（数据质量指标，V2 起）
-- ============================================
CREATE TABLE IF NOT EXISTS metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,                  -- pipeline 运行 ID
    metric_name TEXT NOT NULL,                  -- 指标名称
    metric_value REAL NOT NULL,                 -- 指标值
    detail      TEXT,                           -- 详情 JSON
    timestamp   TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_metrics_run_id ON metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp DESC);


-- ============================================
-- 2.11 dedup_keys 表（去重键映射，可选）
-- ============================================
CREATE TABLE IF NOT EXISTS dedup_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key       TEXT UNIQUE NOT NULL,       -- 去重键（name_key::sector_key）
    project_id      TEXT NOT NULL,              -- 关联项目 ID
    name_raw        TEXT NOT NULL,              -- 原始名称
    sector_raw      TEXT NOT NULL,              -- 原始赛道
    created_at      TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dedup_key ON dedup_keys(dedup_key);
CREATE INDEX IF NOT EXISTS idx_dedup_project ON dedup_keys(project_id);


-- ============================================
-- 2.12 prompt_versions 表（Prompt 版本管理，V2 起）
-- ============================================
CREATE TABLE IF NOT EXISTS prompt_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name      TEXT NOT NULL,              -- Agent 名称
    prompt_key      TEXT NOT NULL,              -- Prompt 标识
    version         TEXT NOT NULL,              -- 版本号
    content         TEXT NOT NULL,              -- Prompt 内容
    is_default      INTEGER DEFAULT 0,          -- 是否默认版本（0/1）
    created_by      TEXT NOT NULL,              -- 创建者
    created_at      TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_prompt_agent ON prompt_versions(agent_name);
CREATE INDEX IF NOT EXISTS idx_prompt_version ON prompt_versions(agent_name, version);
```

---

## 3. V2 PostgreSQL 差异

```sql
-- V2 切换 PostgreSQL 时的差异部分

-- 3.1 JSON 列改 JSONB
ALTER TABLE projects ALTER COLUMN reason TYPE JSONB USING reason::jsonb;
ALTER TABLE projects ALTER COLUMN narrative_json TYPE JSONB USING narrative_json::jsonb;
ALTER TABLE projects ALTER COLUMN team_json TYPE JSONB USING team_json::jsonb;
ALTER TABLE projects ALTER COLUMN risk_json TYPE JSONB USING risk_json::jsonb;
ALTER TABLE projects ALTER COLUMN tokenomics_json TYPE JSONB USING tokenomics_json::jsonb;
ALTER TABLE projects ALTER COLUMN raw_signals TYPE JSONB USING raw_signals::jsonb;
ALTER TABLE projects ALTER COLUMN meta TYPE JSONB USING meta::jsonb;

-- 3.2 启用外键约束
ALTER TABLE logs ADD CONSTRAINT fk_logs_project 
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE events ADD CONSTRAINT fk_events_project 
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE feedback ADD CONSTRAINT fk_feedback_project 
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE project_history ADD CONSTRAINT fk_history_project 
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- 3.3 JSONB 索引（GIN）
CREATE INDEX idx_projects_raw_signals ON projects USING GIN (raw_signals);
CREATE INDEX idx_projects_narrative ON projects USING GIN (narrative_json);
CREATE INDEX idx_logs_input ON logs USING GIN (input);
CREATE INDEX idx_logs_output ON logs USING GIN (output);

-- 3.4 时间戳带时区
-- PostgreSQL 推荐 timestamptz
ALTER TABLE projects ALTER COLUMN created_at TYPE timestamptz;
ALTER TABLE projects ALTER COLUMN updated_at TYPE timestamptz;
```

---

## 4. 触发器（自动更新 updated_at）

```sql
-- SQLite 版本
CREATE TRIGGER IF NOT EXISTS trg_projects_updated
AFTER UPDATE ON projects
FOR EACH ROW
BEGIN
    UPDATE projects SET updated_at = datetime('now') WHERE id = OLD.id;
END;

-- PostgreSQL 版本（V2）
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_projects_updated
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();
```

---

## 5. 表关系图

```
projects (1) ──── (N) logs
         │
         ├──── (N) events
         │
         ├──── (N) feedback
         │
         ├──── (N) project_history
         │
         └──── (1) dedup_keys

quarantine ─── (N) projects (可选关联)

audit_logs ─── 独立表（记录操作）

weight_changelog ─── 独立表（记录权重变更）

llm_eval_changelog ─── 独立表（记录 LLM 评估）

metrics ─── 独立表（记录数据质量指标）

prompt_versions ─── 独立表（记录 Prompt 版本）
```

---

## 6. 数据保留策略

| 表 | 保留期 | 清理方式 |
|---|---|---|
| projects | 永久 | — |
| logs | 90 天 | `DELETE FROM logs WHERE timestamp < datetime('now', '-90 days')` |
| events | 180 天 | `DELETE FROM events WHERE timestamp < datetime('now', '-180 days')` |
| feedback | 永久（去标识） | — |
| quarantine | 30 天未处理 | `DELETE FROM quarantine WHERE status='pending' AND created_at < datetime('now', '-30 days')` |
| project_history | 永久 | — |
| audit_logs | 1 年 | `DELETE FROM audit_logs WHERE created_at < datetime('now', '-1 year')` |
| weight_changelog | 永久 | — |
| llm_eval_changelog | 永久 | — |
| metrics | 1 年 | `DELETE FROM metrics WHERE timestamp < datetime('now', '-1 year')` |
| dedup_keys | 永久 | — |
| prompt_versions | 永久 | — |

---

## 7. 初始化数据

```sql
-- 默认权重版本记录（V2 起）
INSERT INTO weight_changelog (from_version, to_version, old_weights, new_weights, changed_by)
VALUES ('v0', 'v1', '{}', 
        '{"airdrop_signal":0.20,"narrative_timing":0.20,"team_reputation":0.15,"risk":0.15,"tokenomics":0.15,"competition":0.15}',
        'system');

-- 默认 Prompt 版本（V2 起）
INSERT INTO prompt_versions (agent_name, prompt_key, version, content, is_default, created_by)
VALUES 
    ('narrative', 'heat_score_v1', 'v1.0', 'Analyze the narrative timing for sector: {sector}...', 1, 'system'),
    ('team', 'reputation_v1', 'v1.0', 'Evaluate team reputation for project: {name}...', 1, 'system'),
    ('risk', 'assessment_v1', 'v1.0', 'Assess risk for project: {name}...', 1, 'system'),
    ('tokenomics', 'analysis_v1', 'v1.0', 'Analyze tokenomics for project: {name}...', 1, 'system');
```

---

_文档版本：v1.0 · 配套 ENGINEERING_ROADMAP.md §5 · 实现阶段 `init_db()` 直接引用本文件。_
