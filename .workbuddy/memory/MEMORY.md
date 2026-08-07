# 项目记忆：Web3 Airdrop Alpha Agent System

> 更新：2026-08-06 · P0+P1+P2+经济分支+CI+文档+前端+mypy+GitHub ✅ · 15 commits on master · 2,155 测试 · mypy 0 errors

## 开发环境端口约定
- 前端：**3002**（`frontend-next`；旧 `frontend/` 非主入口）
- 后端 API：**8002**（本地 / Docker / CI 统一）
- 测试 PostgreSQL：**5433**（容器内 5432；`docker-compose.postgres.yml`）
- 原因：用户多项目并行，避开常见 3000/8000/5432。
- 相关：`config.port`、`Dockerfile`、`docker-compose.yml`、`nginx.conf`、`Start.bat`、`Makefile`、`next.config.js`。

## 测试 PostgreSQL + 双后端
- 启动：`docker compose -f docker-compose.postgres.yml up -d`（主机 **5433**）
- 连接：`postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test`
- 应用切换：设置 `DATABASE_URL=...` 后 `get_connection()` / `init_db()` 走 PG；未设置仍 SQLite
- 验收：`python backend/scripts/verify_postgres.py`（CRUD + relative time + gauges + mark/save）
- `/health` 含 `db` / `db_backend`
- 依赖：`psycopg[binary]>=3.2`
- 注意：`.env` 里 `POSTGRES_PASSWORD` 若与 compose 默认不一致，需 `down -v` 后重建卷

## 协作约定
- 用户偏好：先文档后代码；有明确实现指令再写 production 代码。
- 真相源：`docs/` 设计文档 + 根目录进度文件（`W1_STATUS` / `W2_PROGRESS` / `W3_PROGRESS` / `W4_PROGRESS`）。
- 记忆与进度冲突时，以进度文件与代码为准。
- **禁止读/改 `.env`**（OpenCode leak protection）；见项目根 `opencode.json` permission deny + `AGENTS.md`。
- Agent 会话记忆：`.workbuddy/memory/MEMORY.md`（本文件）+ 按日 `YYYY-MM-DD.md`。

## 项目定位（v2.0）
- **自动扫描全网**的 Web3 早期项目发现与评分平台（ADR-012 / `SYSTEM_DIRECTION_CHANGE.md`）。
- 系统主动采集 → 去重归一化 → 多 Agent 分析 → FARM / WATCH / IGNORE；用户是评分消费者 + 反馈提供者。
- 手动输入 / CSV / seed 仅作采集盲区补充。
- **不做**：交易执行、自动 farming、资金/KYC 托管；输出仅供决策参考。

## 技术栈（当前实现）
- 后端：Python 3.11+ / FastAPI / SQLite(WAL) / pydantic-settings / 自研 Orchestrator
- 评分：规则引擎默认（ADR-001 LLM 默认关）；Agent：Collector + Narrative/Team/Risk/Tokenomics + Scorer
- 采集：`backend/app/collectors/`（DefiLlama 已联调；GitHub/CoinGecko 等需 API key）
- 前端：Next.js 16 App Router + React 19（`frontend-next/`）；旧 `frontend/index.html` 保留但非主路径
- 调度：APScheduler 进程内 + `POST /run` / collections trigger
- 测试：后端全量 **2,155 passed / 1 skipped / 87% coverage**（2026-08-06 经济分支合并后）；ruff 干净；compileall 通过
- 前端：Next.js **16.3.0** + React 19；`npm audit` **0 vulnerabilities**；Turbopack build pass；typecheck pass

## 关键文档
- 索引：`docs/00_index.md`、`QUICK_REFERENCE.md`、`docs/PROJECT_BOOTSTRAP_OVERVIEW.md`
- **实现现状（优先）**：`docs/IMPLEMENTATION_STATUS.md`
- 产品/架构：`docs/01_product.md`、`docs/02_architecture.md`、`docs/ENGINEERING_ROADMAP.md`
- 方向/数据源：`docs/SYSTEM_DIRECTION_CHANGE.md`、`docs/DATA_SOURCE_STRATEGY.md`、`docs/COLLECTION_ANALYSIS_HANDOFF.md`
- 评分校准：`docs/WEIGHT_CALIBRATION.md`（ADR-006 操作协议）
- 规范：`docs/API_SPEC.md`、`docs/DATA_SCORING_DICT.md`、`docs/DATABASE_DDL.md`、`docs/FRONTEND_SPEC.md`、`docs/SECURITY.md`、`docs/OBSERVABILITY.md`、`docs/OPERATIONS.md`、`docs/DATA_QUALITY.md`、`docs/GLOSSARY.md`
- 编码：`CONVENTIONS.md`；ADR：`docs/adr/`（至 ADR-013，Next 主前端）
- 进度：`W1_STATUS.md`、`W2_PROGRESS.md`、`W3_PROGRESS.md`、`W4_PROGRESS.md`

## 设计补强（2026-07-13）
- 已补：实现现状表、采集→分析交接、权重校准协议、ADR-013。
- 读文档冲突时：`IMPLEMENTATION_STATUS` + 代码 > 旧 Roadmap 阶段表述。

## 里程碑状态（截至 2026-07-17）
| 阶段 | 状态 | 要点 |
| --- | --- | --- |
| Bootstrap | ✅ | P0/P1/P2 51/51 |
| W1 基础设施 | ✅ | config/models/db/main、目录与工程骨架 |
| W2 Agent 核心 | ✅ | 7 Agent + Orchestrator + Golden/单测 |
| W3 Dashboard | ✅ | 单页 Dashboard + Insights + 反馈 UI；后迁 Next |
| W4 MVP 收尾 | ✅ | CI、seed、DefiLlama 联调、持久化优化、Start.bat、Next 主前端 |
| 后 W4 增强 | 🟡 | 噪声清洗、评分 v1.1–v1.4、融资质量+手动编辑、交互记录、AI 解读、可参与任务、Opportunity Shadow 灰度与观测 |

## 已验证能力（本地）
- `Start.bat`：后端 8002 + `frontend-next` 3002
- DefiLlama 触发采集成功（约 100 条，秒级写入）
- `/run` 批量评分；项目列表总量曾达 ~201（含 seed/历史/采集）
- Next rewrite `/api/v1/*` → 后端；`page_size` 上限 500（修复按钮无响应）
- Dashboard：按 score 排序、默认隐藏 IGNORE、空态 CTA、采集进度 toast；`purge_noise_projects.py` 清理库内蓝筹
- **手动融资**：详情页 FundingPanel → PATCH funding → tier1/quality 写入 meta → 重评 reason 含 funding（2026-07-14 冒烟 OK）

## Handoff 代码（2026-07-13）
- `pipeline_run.execute_analysis_pipeline`：/run、分析 cron、采集 auto-run 共用。
- 仅 `score is not None` 的项 mark `raw_projects.processed`（带 `raw_ids`）。
- `AnalysisScheduler`：`SCHEDULER_ENABLED` + `CRON_EXPRESSION`。
- `COLLECTION_AUTO_RUN_ENABLED`（默认 false）；trigger 响应可含 `auto_run`。

## 采集源（密钥在根目录 .env）
- config 会读 **仓库根** `.env` 与 `backend/.env`。
- 已实现并验收：DefiLlama、GitHub、CoinGecko、Etherscan、**CryptoRank**（`collectors/cryptorank.py`）。
- CryptoRank：`api_key` query；rank 50–800；**score ≤0.28**（信号源，默认不进分析）；cron `CRYPTORANK_CRON`。
- **噪声清洗**：GitHub 关键词/语言/denylist + relevance 降权；Etherscan 过滤 USDT/USDC/WETH 等 + score≤0.28；CryptoRank 排除 currency/meme 与死盘。
- **共享 denylist**：`collectors/noise.py`；DefiLlama 采集过滤 + **分析入口** `collect_from_repository` 跳过并 mark processed（旧队列不反复评分）。
- **脏数据清理**：`python backend/scripts/purge_noise_projects.py` 删除 projects 噪声并 mark raw；支持 `--dry-run`。
- **空投信号映射**：DefiLlama 写 `no_token_yet`；`CollectorAgent._infer_airdrop_flags` 从 raw 推断；否则 airdrop_signal 恒为 20。
- **评分 v1.3/v1.4**：八维 + 可验证任务/多源/履约/合约/女巫；**融资质量** `funding_quality`/`funding_tier`（RootData 采集器 `rootdata`）；`confidence` 为证据完整度。
- **RootData**：`ROOTDATA_ENABLED` + `ROOTDATA_API_KEY`（https://www.rootdata.com/api）；API `POST /open/ser_inv|get_item|get_fac`。
  - **限制**：免费档轮次/融资详情常不全；**不要指望 RootData 单独喂饱融资维度**。
  - **主路径（2026-07-14）**：用户在详情页**手动编辑融资** → `meta.signals` → 重评。
- 验收：`python backend/scripts/verify_collectors.py`；全链路 `python backend/scripts/e2e_collect_score.py`；`purge_noise_projects.py`

## 融资信号链路（v1.4 · 2026-07-14 完成 UI）

```
采集/手动/CSV
    ↓
funding.extract_funding_from_raw / compute_funding_quality
    ↓
RawProject.funding_* + recent_funding
    ↓
repository.save → merge_meta → projects.meta.signals (JSON)
    ↓
scorer / team / tokenomics 读 funding_quality / funding_tier
```

### API
- `GET  /api/v1/projects/{id}/funding`
- `PATCH /api/v1/projects/{id}/funding?rescore=true`  body: total/rounds/date/investors/leads/recent/note
- `GET  /api/v1/projects/{id}` → `funding` + `signals` + `funding_note`

### 前端
- `FundingPanel`（详情页）：保存并重评
- 详情「重新评分」→ **PATCH funding 空 body + rescore**（保留 meta.signals；勿精简 POST `/run`）

### 关键代码
- `backend/app/services/funding.py`
- `backend/app/services/project_signals.py`
- `backend/app/routers/v1/funding.py`
- `frontend-next/components/FundingPanel.tsx`

### 冒烟（2026-07-14）
- $25M + Paradigm → `tier1` / quality `0.9`；reason 含 `tier-1 / high-quality funding`
- 单测：`pytest tests/test_funding.py tests/test_rootdata_funding_score.py` → 5 passed

## 运维脚本（在 backend/ 下，PYTHONPATH=.）
- `scripts/rescore_all.py` — 用当前规则重算全部 projects（**从 meta.signals 恢复融资等字段**）
- `scripts/feedback_snapshot.py` — 反馈样本计数（`make feedback-stats`）
- `scripts/calibrate_weights.py` — 权重校准门禁报告（`make calibrate`）；&lt;200 样本不改权重
- `scripts/quarantine_cli.py` — 隔离 list/add/release（`make quarantine-list`）
- `scripts/e2e_collect_score.py` / `verify_collectors.py` / `purge_noise_projects.py`
- 注意：golden 测试勿写进生产 DB；若污染可 `DELETE FROM projects WHERE source='seed'`

## 反馈 / 隔离 / 鉴权 / 前端能力
- `ENABLE_FEEDBACK_SYSTEM` 默认 true；项目详情页可提交 useful/useless/wrong_label
- Quarantine：`raw_projects.quarantined`；API `GET/POST /api/v1/quarantine`、`POST .../release`
- 噪声命中自动 quarantine；分析队列 `COALESCE(quarantined,0)=0`
- API 鉴权：`API_KEY` 非空时中间件校验；`/health` `/docs` 仍公开
- Next：**16.3.0** + React 19；`npm audit` **0 vulnerabilities**（2026-08-06 修复 16 CVE）
- 前端：暗色主题、Dashboard 图表/筛选/表格、详情 Agent 面板+反馈、Insights、**/ops 运维台**
- **AI 解读**：`POST /api/v1/projects/{id}/ai-brief` + `AiBriefPanel`
- **交互记录**：表 `interactions`；API `/api/v1/interactions`；详情「我的交互记录」
- **可参与任务**：`GET .../participation-tasks` + `ParticipationTasks`（localStorage 勾选）
- **融资编辑**：`FundingPanel` + PATCH funding（2026-07-14）

## 已知债务 / 下一步
1. ~~**P0**：系统审查 commit~~ ✅ 2026-08-06 完成（8 个语义提交：016693c → eff1bea）
2. ~~**P0**：pytest 基线复跑~~ ✅ 1919 passed / ruff clean / compileall pass
3. ~~**P0 红线**：`backfill_meta_signals.py --apply`~~ ✅ 602/702 已回填；备份 `airdrop.db.bak-20260806-044608`；100 条无原始记录（seed/测试）保持 NULL
4. ~~**P1**：Next.js + PostCSS 安全漏洞~~ ✅ next 16.3.0 + postcss ^8.5.26（16 CVE 修复，npm audit 0）
5. ~~**P2**：Opportunity Shadow 默认开启~~ ✅ `db26bca` shadow_enabled=true, sample_rate=1.0，渐进式转正第一阶段完成
6. ~~**经济分支合并**~~ ✅ `bd9013e` + `2e73500`：13 commits 合并，9 冲突解决，2 verifier 修复，2,155 passed
7. ~~**CI/CD 修复**~~ ✅ `1088c67`：mypy 启用（非 strict）、前端 CI、security/docs 分支对齐、secret baseline
8. ~~**文档对齐**~~ ✅ `e2e3985`：IMPLEMENTATION_STATUS.md v1.2
9. ~~**前端打磨**~~ ✅ `ae3d9ba`：有融资筛选 + tier 徽章 + CSV 导出 + 客户端路由 + 共享 tierZh
10. ~~**CI 强化 mypy**~~ ✅ `38472fa`：287→0 errors（29 文件修复），`pyproject.toml` 新增 `[tool.mypy]`，CI 阻断模式
11. ~~**GitHub 仓库完善**~~ ✅ 公开仓库 + 10 topics + 分支保护（5 CI 必过）+ Actions 权限 + 安全扫描
12. ~~**跑数据 + Shadow 验证**~~ ✅ 5 源采集成功，100 项目评分，Shadow 300 条快照全部 INSUFFICIENT_EVIDENCE（经济数据表为空）
13. **Shadow 经济数据接入**：`opportunity_economic_snapshots` 表 0 行，7 个 `economic_*` 模块已合并但未触发写入
14. **反馈积累**：0/200，需要日常使用系统并提交反馈
15. **Shadow 转正**：等 Shadow 产出有意义 action 分布后，做 dual_run_compare 对比
16. P3：观测栈日常化 / LLM 集成 / PG 切换

## ✅ 2026-07-26 系统审查（已提交 · 已回填）
**8 个语义 commit 已提交到 master（2026-08-06）；meta.signals 回填 602/702 已完成。**

提交序列：
1. `016693c` docs: ADR-014 + 4 份审计报告
2. `fbd3250` fix(collectors): 跨源字段合并 + 管道持久化
3. `a0fc3d1` fix(scoring): ADR-014 引擎规范 + opportunity shadow 加固
4. `351b457` fix(security): 认证/限流/日志脱敏/CORS
5. `960d95b` fix(frontend): Next.js 仪表盘对齐后端审计修复
6. `c43a4f1` chore(deploy): CHANGELOG + 依赖 + docker-compose + nginx
7. `01e450e` fix(security): Next.js 16.3.0 + PostCSS 8.5.26 安全补丁
8. `eff1bea` chore: .gitignore 排除 backend/data/ 和 db 备份

回填结果（`backfill_meta_signals.py --apply`）：
- 602/702 项目已回填 22 个信号字段（`explicit_airdrop_mention`、`tvl_usd`、`funding_tier` 等）
- 100 个无原始记录项目（seed/测试）保持 meta=NULL
- 备份：`backend/data/airdrop.db.bak-20260806-044608`
- **rescore 安全红线已解除**：现在可以安全执行 `/rescore` 或 `dual_run_compare.py`

## Opportunity v2.0 Shadow
- 版本：`opportunity-v2.0`；默认画像：`low-cost-curated-multiwallet-v1`。
- **默认开启（2026-08-06 `db26bca`）**：`OPPORTUNITY_SHADOW_ENABLED=true`、`OPPORTUNITY_SHADOW_SAMPLE_RATE=1.0`（全量采样）。
- 自动 Shadow 仅处理成功持久化且 legacy score 非空的项目；显式 Opportunity API 评估不采样。
- 采样按非空 project ID 做 SHA-256 确定性分桶：前 8 字节按无符号大端整数解释，`mod 10_000`，阈值为 `floor(rate * 10_000)`；扩量形成单调超集。
- 汇总字段：`eligible` / `sampled` / `attempted` / `saved` / `failed` / `skipped`。
- Shadow 非权威，现有 `score-v1.4` 分数和标签保持主输出且不会被覆盖；构造、上下文进入/退出、单项目评估和指标失败均不得影响主 Pipeline。
- 稀疏 legacy 输入返回 `INSUFFICIENT_EVIDENCE/WATCH`；证据与评估快照只追加，结果可通过匿名 cohort interaction 关联。
- 低基数指标：`airdrop_opportunity_shadow_projects_total{result}`、`airdrop_opportunity_shadow_assessments_total{status,public_label,model_version,profile_version}`、duration histogram、enabled/sample-rate gauges；禁止 project ID、assessment ID、URL、错误文本作为 label。
- `/health` 暴露 `opportunity_model_version`、`opportunity_shadow_enabled`、`opportunity_shadow_sample_rate`，不聚合 Shadow 表。
- 验收：SQLite Shadow verifier PASS；PostgreSQL `verify_postgres.py` OK、Shadow PASS、4 workers × 2 rounds 并发初始化 PASS（必须顺序运行）。

## CI / Docker 收尾（2026-07-17）
- CI push/PR 同时支持 `master` 与 `main`；保留 `feat/**`、`fix/**`、`docs/**` push 规则。
- CI Docker smoke 与禁用的 release demo 使用最多 30 次、每秒一次的 `/health` 轮询；超时输出日志，CI 临时容器始终清理。
- 工作流镜像使用仓库根 context 与 `docker/Dockerfile`；已移除被 `.dockerignore` 排除的 `COPY data/`。
- 容器入口为 `/app/backend` 下的 Uvicorn：`app.main:app --host 0.0.0.0 --port 8002`。
- 本地 Docker build 与 health smoke 已通过；响应确认 SQLite backend 和两个 Shadow rollout 字段。
- 设计、实施计划和实现已本地合并到 `master`；计划 49 个步骤已归档完成。当前未配置 Git remote，因此未 push / 未建 PR。

## 历史设计阶段备忘（2026-07-08，已过时阶段标签）
- 曾经历纯文档推进（Roadmap v1.2/v1.3、ADR 拆分、OBSERVABILITY/SECURITY/DATA_QUALITY 等）。
- 第五轮复核后文档体系达可实现标准；**现已进入实现并完成 W1–W4**，勿再按“未写代码”理解项目。

## Opportunity Outcome Calibration（2026-07-20 已合并 master）
- 离线只读校准：ackend/app/opportunity/calibration/
- CLI：python scripts/calibrate_opportunity.py --as-of <UTC> --output-dir reports/opportunity-calibration
- Verifier：python scripts/verify_opportunity_calibration.py --as-of 2026-10-15T00:00:00Z
- 样本：assessment×cohort；90/180 天成熟窗口；建议永不自动应用
- 最终基线：1,751 passed / 1 skipped / 85.48% coverage
- SQLite Shadow + calibration verifiers PASS；Docker Desktop 不可用，live PostgreSQL 未跑
- 设计：docs/superpowers/specs/2026-07-17-opportunity-outcome-calibration-design.md
- 计划：docs/superpowers/plans/2026-07-17-opportunity-outcome-calibration.md

## Opportunity Economic Data Acquisition（2026-07-26 完成，尚未合并）
- 分支：`feature/opportunity-economic-data-acquisition`
- worktree：`.worktrees/opportunity-economic-data-acquisition`
- 冻结基线：`80f6643`；当前 HEAD：`d9794fe507a342adb1a886631c30857fa870f3c4`
- 提交序列：2 个文档提交 + 9 个实现提交，共 11 个；已 autosquash，无 fixup、无 Task 10 提交。
- 已实现：经济快照冻结模型与 canonical hash、SQLite/PostgreSQL 双后端仓储、provider normalizer、指标与 writer、evidence insert-if-absent、双身份链接与 post-link replay、时间序列 resolver、持久化采集接线、安全 workflow projection、无网络 verifier。
- 最终选择 **方案 A**：相同 `snapshot_id` 且仅 `collected_at` 漂移时视为 duplicate，返回已有不可变行并保留原时间戳；其他字段不同仍报 content conflict。
- 冻结边界：workflow 不暴露 `raw_snapshot_ref`；既有 evidence API 合同保持不变。
- Task 10 全量验收：Tasks 1–9 focused PASS；后端 `2,039 passed, 1 skipped`；coverage 87%；离线 verifier 26/26、`RESULT: PASS`；compileall、Ruff、静态边界证明、`git diff --check 80f6643..HEAD` 全部 PASS。
- 最终复审：Critical 0、Important 0、Minor 5、Ready to merge = Yes。初审两项 Important 经聚焦复核均驳回：同步 DB 临界段无 `await`，不存在所述 asyncio 交错；`raw_snapshot_ref` 限制只适用于 workflow，修改 evidence API 会越过冻结合同。
- 交付策略：按用户选择保留本地 feature 分支和 worktree；不 merge、不 push、不删除 worktree。
- 协作约束：主代理负责架构、调度与验收；实现代码交给 Grok Agent；Git 仅本地 commit，绝不主动 push。
