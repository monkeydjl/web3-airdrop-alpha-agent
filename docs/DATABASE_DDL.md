# 数据库完整 DDL

> 配套文档：ENGINEERING_ROADMAP.md §5、DATA_SCORING_DICT.md §1-2。本文档汇总所有表的完整 DDL 定义，供实现阶段 `init_db()` 与迁移脚本直接照做。
>
> 适用阶段：MVP（SQLite WAL）→ V2（PostgreSQL）。MVP 与 V2 差异处用注释标注。

---

## Opportunity v2 persistence invariants

- Evidence is append-only. `supersedes_evidence_id` identifies the logical predecessor and is repository-validated for matching project and factor.
- PostgreSQL opportunity evidence, assessment, and interaction outcome timestamps use `TIMESTAMPTZ`. Legacy naive evidence timestamps are interpreted as UTC during freshness checks.
- Latest assessment ordering is `scored_at DESC`, `created_at DESC`, then `assessment_id DESC`.
- Interaction creation reads the exact inserted row in the write transaction via `INSERT ... RETURNING *` on PostgreSQL and SQLite 3.35+, or an own-row ID lookup before commit on older SQLite.

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
    from_version    TEXT,                         -- 旧版本
    to_version      TEXT,                         -- 新版本
    weights_json    TEXT NOT NULL,                -- 权重 JSON（与 calibrate_weights.py 一致）
    sample_size     INTEGER,                      -- 触发样本数
    metrics_json    TEXT,                         -- 指标 JSON（J / recall / FPR）
    triggered_by    TEXT,                         -- 变更触发者
    status          TEXT DEFAULT 'candidate',     -- candidate / baseline / active
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_weight_changelog_created ON weight_changelog(created_at DESC);

-- ============================================
-- 2.8b watchlist 表（用户关注列表，ADR-008 V2）
-- ============================================
CREATE TABLE IF NOT EXISTS watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,                   -- 关联项目
    user_id     TEXT,                             -- 用户标识（MVP 缺省 default）
    note        TEXT,                             -- 用户备注
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_project ON watchlist(project_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);


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


-- ============================================
-- 2.13 data_sources 表（数据源注册表，v2.0 起，ADR-012）
-- ============================================
CREATE TABLE IF NOT EXISTS data_sources (
    source_id       TEXT PRIMARY KEY,              -- 如 "defillama", "twitter", "github"
    source_type     TEXT NOT NULL,                 -- "api" / "stream" / "webhook" / "manual"
    source_name     TEXT NOT NULL,
    enabled         INTEGER DEFAULT 1,             -- SQLite 用 0/1 表示 BOOLEAN
    last_sync       TIMESTAMP,
    sync_status     TEXT DEFAULT 'idle',           -- "idle" / "running" / "error" / "rate_limited"
    api_calls_today INTEGER DEFAULT 0,
    api_limit       INTEGER,                       -- 每日限额（NULL 表示无限制）
    config          TEXT,                          -- 源特定配置 JSON
    created_at      TIMESTAMP DEFAULT (datetime('now')),
    updated_at      TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_data_sources_enabled ON data_sources(enabled);
CREATE INDEX IF NOT EXISTS idx_data_sources_status ON data_sources(sync_status);


-- ============================================
-- 2.14 raw_projects 表（采集原始项目池，v2.0 起，ADR-012）
-- ============================================
CREATE TABLE IF NOT EXISTS raw_projects (
    raw_id          TEXT PRIMARY KEY,              -- 采集记录 id（UUID）
    source_id       TEXT NOT NULL,                 -- 关联 data_sources
    dedup_key       TEXT NOT NULL,                 -- 归一化去重键（§6.2.1）
    raw_data        TEXT NOT NULL,                 -- 原始采集数据 JSON
    discovered_at   TIMESTAMP DEFAULT (datetime('now')),
    processed       INTEGER DEFAULT 0,             -- 0=未处理，1=已进入分析管道
    processed_at    TIMESTAMP,
    project_id      TEXT,                          -- 关联 projects 表 id（处理后回填）
    discovery_score REAL DEFAULT 0.0               -- 发现质量分（初筛用，见 DATA_SOURCE_STRATEGY.md）
);

CREATE INDEX IF NOT EXISTS idx_raw_projects_dedup ON raw_projects(dedup_key);
CREATE INDEX IF NOT EXISTS idx_raw_projects_unprocessed ON raw_projects(processed) WHERE processed = 0;
CREATE INDEX IF NOT EXISTS idx_raw_projects_source ON raw_projects(source_id);
CREATE INDEX IF NOT EXISTS idx_raw_projects_discovered ON raw_projects(discovered_at DESC);


-- ============================================
-- 2.15 project_signals 表（项目信号聚合，v2.0 起，ADR-012）
-- ============================================
CREATE TABLE IF NOT EXISTS project_signals (
    signal_id       TEXT PRIMARY KEY,              -- UUID
    project_id      TEXT,                          -- 关联 projects 表（可为空，未建立关联时）
    dedup_key       TEXT,                          -- 关联 raw_projects
    signal_type     TEXT NOT NULL,                 -- "tvl" / "github_activity" / "twitter_mention" / "chain_activity" / "quest"
    signal_source   TEXT NOT NULL,                 -- "defillama" / "github" / "twitter" / "chain" / "galxe"
    signal_data     TEXT NOT NULL,                 -- 信号具体数据 JSON
    signal_strength REAL DEFAULT 0.0,              -- 信号强度 0-1
    captured_at     TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_signals_project ON project_signals(project_id);
CREATE INDEX IF NOT EXISTS idx_signals_dedup ON project_signals(dedup_key);
CREATE INDEX IF NOT EXISTS idx_signals_type ON project_signals(signal_type, signal_source);
CREATE INDEX IF NOT EXISTS idx_signals_captured ON project_signals(captured_at DESC);


-- ============================================
-- 2.16 collection_logs 表（采集日志，v2.0 起，ADR-012）
-- ============================================
CREATE TABLE IF NOT EXISTS collection_logs (
    log_id          TEXT PRIMARY KEY,              -- UUID
    source_id       TEXT NOT NULL,                 -- 关联 data_sources
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    items_collected INTEGER DEFAULT 0,
    items_new       INTEGER DEFAULT 0,             -- 去重后的新项目数
    items_duplicate INTEGER DEFAULT 0,
    status          TEXT,                          -- "success" / "error" / "partial" / "rate_limited"
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_collection_logs_source ON collection_logs(source_id);
CREATE INDEX IF NOT EXISTS idx_collection_logs_started ON collection_logs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_collection_logs_status ON collection_logs(status);


-- ============================================
-- 2.17 projects 表扩展字段（v2.0 起，ADR-012）
-- ============================================
-- 注：使用 ALTER TABLE 新增字段，已有记录自动填充 DEFAULT 值，不破坏既有数据
ALTER TABLE projects ADD COLUMN discovery_source TEXT DEFAULT 'manual';      -- 首次发现的来源
ALTER TABLE projects ADD COLUMN discovered_at TIMESTAMP;                    -- 首次发现时间
ALTER TABLE projects ADD COLUMN auto_discovered INTEGER DEFAULT 0;          -- 0=手动，1=自动发现
ALTER TABLE projects ADD COLUMN signal_count INTEGER DEFAULT 0;             -- 关联信号数

CREATE INDEX IF NOT EXISTS idx_projects_auto_discovered ON projects(auto_discovered);
CREATE INDEX IF NOT EXISTS idx_projects_discovery_source ON projects(discovery_source);
CREATE INDEX IF NOT EXISTS idx_projects_discovered_at ON projects(discovered_at DESC);


-- ============================================
-- 2.18 raw_projects_archive 表（归档表，v2.0 起）
-- ============================================
-- 结构与 raw_projects 完全一致，用于存放 30 天前的采集记录
CREATE TABLE IF NOT EXISTS raw_projects_archive (
    raw_id          TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    dedup_key       TEXT NOT NULL,
    raw_data        TEXT NOT NULL,
    discovered_at   TIMESTAMP,
    processed       INTEGER DEFAULT 0,
    processed_at    TIMESTAMP,
    project_id      TEXT,
    discovery_score REAL DEFAULT 0.0,
    archived_at     TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_archive_dedup ON raw_projects_archive(dedup_key);
CREATE INDEX IF NOT EXISTS idx_archive_discovered ON raw_projects_archive(discovered_at DESC);


-- ============================================
-- 2.19 project_signals_archive 表（归档表，v2.0 起）
-- ============================================
CREATE TABLE IF NOT EXISTS project_signals_archive (
    signal_id       TEXT PRIMARY KEY,
    project_id      TEXT,
    dedup_key       TEXT,
    signal_type     TEXT NOT NULL,
    signal_source   TEXT NOT NULL,
    signal_data     TEXT NOT NULL,
    signal_strength REAL DEFAULT 0.0,
    captured_at     TIMESTAMP,
    archived_at     TIMESTAMP DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_signals_archive_project ON project_signals_archive(project_id);
CREATE INDEX IF NOT EXISTS idx_signals_archive_captured ON project_signals_archive(captured_at DESC);

-- ============================================
-- 2.20 Opportunity v2.0 Shadow 证据与不可变评估快照
-- ============================================
CREATE TABLE IF NOT EXISTS opportunity_evidence (
    evidence_id         TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL,
    factor_key          TEXT NOT NULL,
    value_json          TEXT NOT NULL,
    value_type          TEXT NOT NULL,
    observation_type    TEXT NOT NULL,
    source_url          TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    source_grade        TEXT NOT NULL,
    observed_at         TIMESTAMP NOT NULL,
    effective_at        TIMESTAMP,
    expires_at          TIMESTAMP,
    verification_status TEXT NOT NULL,
    independence_group  TEXT NOT NULL,
    raw_snapshot_ref    TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opportunity_assessments (
    assessment_id      TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL,
    model_version      TEXT NOT NULL,
    profile_version    TEXT NOT NULL,
    assessment_json    TEXT NOT NULL,
    decision_status    TEXT NOT NULL,
    public_label       TEXT NOT NULL,
    decision_value     REAL,
    overall_confidence REAL NOT NULL,
    scored_at          TIMESTAMP NOT NULL,
    review_at          TIMESTAMP,
    expires_at         TIMESTAMP NOT NULL,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_opportunity_evidence_project
ON opportunity_evidence(project_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_evidence_factor
ON opportunity_evidence(project_id, factor_key, verification_status);
CREATE INDEX IF NOT EXISTS idx_opportunity_assessment_latest
ON opportunity_assessments(project_id, profile_version, scored_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_assessment_label
ON opportunity_assessments(public_label, expires_at);

-- PostgreSQL 使用相同列；仅将 assessment 的两个 REAL 列改为 DOUBLE PRECISION。

-- ============================================
-- 2.21 interactions 的 Shadow outcome 追加列
-- ============================================
-- init_db() 通过 _add_column_if_not_exists() 幂等追加，不能删除旧 cost/profit/hours 列。
-- SQLite exact columns:
-- wallet_cohort_id TEXT
-- wallet_count INTEGER DEFAULT 1
-- actual_hard_cost_usd REAL
-- actual_time_minutes INTEGER
-- eligibility_result TEXT
-- survival_result TEXT
-- disqualification_reason TEXT
-- reward_received_usd REAL
-- claim_cost_usd REAL
-- opportunity_assessment_id TEXT
-- opportunity_model_version TEXT
-- opportunity_profile_version TEXT
-- outcome_observed_at TIMESTAMP

-- PostgreSQL 将 actual_hard_cost_usd/reward_received_usd/claim_cost_usd 改为
-- DOUBLE PRECISION；其余列保持一致。
```

Opportunity 证据和评估均为追加式记录；评估没有 update 路径。`interactions.wallet_cohort_id` 是本地匿名 cohort ID，不是钱包地址。系统拒绝在 cohort、用户、活动、备注或取消资格原因字段中存储钱包地址；不得存储私钥、助记词、设备身份或 KYC 数据。模型/画像版本必须通过同项目的 `opportunity_assessment_id` 关联，`realized_net_usd` 仅在响应中计算，不落库。

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
         ├──── (1) dedup_keys
         │
         └──── (N) project_signals ──── (N) raw_projects (同 dedup_key 关联)

data_sources (1) ──── (N) raw_projects
            │
            └──── (N) collection_logs

raw_projects (1) ──── (1) projects（processed 后回填 project_id）

raw_projects_archive ─── 独立表（raw_projects 30 天归档）
project_signals_archive ─── 独立表（project_signals 90 天归档）

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
| **data_sources** | 永久（配置表） | — |
| **raw_projects** | 30 天热数据 | 归档至 `raw_projects_archive`，> 180 天删除（见下方归档脚本） |
| **project_signals** | 90 天热数据 | 归档至 `project_signals_archive`，> 365 天删除 |
| **collection_logs** | 90 天 | `DELETE FROM collection_logs WHERE started_at < datetime('now', '-90 days')` |
| **raw_projects_archive** | 180 天 | `DELETE FROM raw_projects_archive WHERE archived_at < datetime('now', '-180 days')` |
| **project_signals_archive** | 365 天 | `DELETE FROM project_signals_archive WHERE archived_at < datetime('now', '-365 days')` |

### 6.1 采集数据归档脚本（v2.0，每日 cron 执行）

```sql
-- 1. raw_projects 归档：30 天前未处理的采集记录
INSERT INTO raw_projects_archive (raw_id, source_id, dedup_key, raw_data, discovered_at, processed, processed_at, project_id, discovery_score)
SELECT raw_id, source_id, dedup_key, raw_data, discovered_at, processed, processed_at, project_id, discovery_score
FROM raw_projects
WHERE discovered_at < datetime('now', '-30 days');

DELETE FROM raw_projects WHERE discovered_at < datetime('now', '-30 days');

-- 2. project_signals 归档：90 天前信号
INSERT INTO project_signals_archive (signal_id, project_id, dedup_key, signal_type, signal_source, signal_data, signal_strength, captured_at)
SELECT signal_id, project_id, dedup_key, signal_type, signal_source, signal_data, signal_strength, captured_at
FROM project_signals
WHERE captured_at < datetime('now', '-90 days');

DELETE FROM project_signals WHERE captured_at < datetime('now', '-90 days');

-- 3. collection_logs 清理：90 天前日志直接删除
DELETE FROM collection_logs WHERE started_at < datetime('now', '-90 days');

-- 4. 归档表清理：raw_projects_archive 180 天、project_signals_archive 365 天
DELETE FROM raw_projects_archive WHERE archived_at < datetime('now', '-180 days');
DELETE FROM project_signals_archive WHERE archived_at < datetime('now', '-365 days');
```

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

-- 数据源注册（v2.0 起，ADR-012）
INSERT INTO data_sources (source_id, source_type, source_name, enabled, api_limit) VALUES
    ('defillama',  'api',      'DefiLlama',      1, NULL),
    ('github',     'api',      'GitHub',         1, 5000),
    ('coingecko',  'api',      'CoinGecko',      1, NULL),
    ('twitter',    'api',      'Twitter/X',      0, NULL),   -- 默认关闭，需付费
    ('chain',      'webhook',  'Chain (Etherscan/Alchemy)', 0, NULL),
    ('galxe',      'api',      'Galxe',          0, NULL),
    ('layer3',     'api',      'Layer3',         0, NULL),
    ('cryptorank', 'api',      'CryptoRank',     0, 100),
    ('dune',       'api',      'Dune Analytics', 0, NULL),
    ('manual',     'manual',   'Manual Input',   1, NULL);
```

---

_文档版本：v2.0 · 配套 ENGINEERING_ROADMAP.md §5、ADR-012 · 实现阶段 `init_db()` 直接引用本文件。_
