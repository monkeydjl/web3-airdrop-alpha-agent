# 项目记忆：Web3 Airdrop Alpha Agent System

> 2026-09-01 · 分支 `feat/action-loop-m2`，仅本地提交，未经 owner 明示不得 push。

## 红线
- 只提供 FARM/WATCH/IGNORE 决策参考，绝不交易、代签、自动 farming 或托管资金/KYC。
- 先文档后代码；真相源：代码 + `docs/` > 旧路线图 > 本记忆。
- 禁读写 `.env` / `.env.*`（`.env.example` 除外）；commit 后跑 `sh .git/sync-head-ref.sh`。
- 校准门槛固定：有效 live 样本 ≥200 且 FARM ≥30，不可因回测降低。
- **DB 新列四处同落**：`db.py` 双方言建表 DDL + `db.py::init_db` 的 `_add_column_if_not_exists`（既有库升级路径，最易漏）+ Alembic + `docs/DATABASE_DDL.md`。无 SQL 外键，路由显式级联。
  - 漏第 2 处的失效模式：建表是 `CREATE TABLE IF NOT EXISTS`，既有库整条跳过 → 写入报 `no column named X` → pipeline run 变 `status="failed"`（评分其实成功）。**CI 全新 checkout 看不见**，只在已跑过的库升级时炸。回归测试 `test_db_init.py::test_existing_database_reaches_full_column_parity_after_init`。
  - 新列还要确认 API 有出口，否则是死数据（`projects.veto`、当年 `team.risk_level` 都栽过）。详情响应是 `routers/v1/projects.py` 手写字典，加字段同步 `API_SPEC.md`。

## 环境与门禁
- 前端 `frontend-next` :3002；API :8002；测试 PG 宿主 :5433。后端用 `backend/venv/Scripts/python.exe`。
- CI 口径：`cd backend && python -m ruff check . && python -m ruff format --check . && python -m mypy app`；勿只 lint 改动文件。
- 全量 pytest 约 45 分钟，后台单跑写日志，勿并行两套。本机需加 `--no-cov`（沙箱删不掉 `.coverage`）。
- 断言结构化日志用 `structlog.testing.capture_logs()`，**不是 caplog** —— 日志不走 stdlib logging，caplog 抓不到。
- 当前基线：**3226 passed / 9 skipped，无 xfail**（45m22s）。前端 build/tsc/lint/20 单测全绿。
- 前端 build 两坑：① `.next/turbopack` 清理被沙箱批量删除保护拦 → 把 `.next` 改名再 build，改完记得删掉改名目录否则污染 git status；② `NODE_OPTIONS` 含 `--use-system-ca` 会让 worker 报 `ERR_WORKER_INVALID_EXEC_ARGV` → 用 `NODE_OPTIONS="" npm run build`。
- 新日志事件用调用点字面量并同步 `OBSERVABILITY.md` 实测总数；新增 migration 同步 `OPERATIONS.md` 清单 + `test_alembic_migration.py` 登记；SQLite 多语句 migration 用 `_exec_script` 拆分。

## 已交付
- M1：推送（notify_log / 双通道 / 默认不发送但审计）、参与流水（plan/task 状态机，user_id 仅 token）。
- M2/F3：ROI 台账（0007）、6 API、Portfolio `RoiLedger`；回测按 `live|backtest` 分桶，校准只计 live；数据集 19/50（14 正 / 5 负）。
- 回测：`PYTHONPATH=. python scripts/run_backtest.py [--json] [--export-samples]`；读 `response.states` 而非 `results`。

## 评分引擎两条硬语义
- **ADR-015 资格门**（Accepted）：`score` 答「项目好不好」，`veto` 答「现在还有没有可参与路径」。**否决只改 label 不改 score** —— 68 改 34 会被读成「模型认为项目差」，也让回测分不清低分与规则否决。落点 `scorer.py`：`_score_to_label` → `apply_eligibility_gate` → `_apply_confidence_degradation`。两条规则 `already_launched`（FARM→IGNORE）、`no_participation_path`（FARM→WATCH，只到 WATCH 因采集字段可能缺）。非 FARM 原样返回。
  - `is_already_launched_without_airdrop_path()` 由 `airdrop_signal.py` 封顶逻辑与资格门**共用**，禁止写第三份。
  - veto 不参与权重拟合；`veto_false_negatives` 独立于 FPR 监控（误否决是永久挡掉真机会）。
  - 实测 recall 1.000→0.929、fpr 1.000→0.400，目标函数 **−1.00 → +0.129**。
  - **待 owner 拍板**：`veto_false_negatives=1`，Jupiter 被 `no_participation_path` 误否决（参与路径是历史交易行为，三字段表达不了）。放宽规则属业务调整，不单方面改。
- **sector 查表**（已修）：`narrative.py::resolve_sector_profile()` 三级查找，未命中返回 `(DEFAULT_PROFILE, None)` 并打 `narrative.sector_profile_missing`。原实现静默走默认档 → `narrative_timing` 恒 60，0.15 权重白扔。
  - **归一只能做在查表侧**：`normalize_sector()` 的产出进 `generate_deterministic_id()`，sector 是项目 ID 组成部分，扩 `SECTOR_ALIAS` 会让既有项目 ID 漂移。反向测试 `test_lookup_alias_is_not_wired_into_normalize_sector` 拦住「顺手统一两张表」。
  - 没档位的新赛道（如 `RWA`）保持未命中 + 告警；硬塞进现有档等于编造赛道热度。
  - 校准前必须确认没有维度方差≈0（`WEIGHT_CALIBRATION.md §4.1.2`），常数维度会让优化器在错误输入上拟合。

## 其他约定
- Repository 三条写入路径（PG / SQLite UPSERT / legacy）须同步。`weight_version`/`sub_scores` 用 COALESCE 保旧值，但 `veto` 必须 `EXCLUDED.veto` 覆盖 —— 成功评分若无否决要能清除过期 veto。
- `pipeline_run` 响应有逐键精确契约，勿随意加字段。写端点有 auth/document parity；文档路径标题不带 query。
- `.gitignore` 目录规则不可用 `git add -f` 强推。
- 生产遗留：P1-5 前端代理管理员密钥、P1-4 同步 IO、反代限流与采集器运行时 URL 白名单。M3/F4 = watched wallets + Alchemy webhook。
