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
- 当前基线：**3191 passed / 9 skipped，无 xfail**。前端 build/tsc/lint/20 单测全绿。
- 前端 build 两坑：① `.next/turbopack` 清理被沙箱批量删除保护拦 → 把 `.next` 改名再 build，改完记得删掉改名目录否则污染 git status；② `NODE_OPTIONS` 含 `--use-system-ca` 会让 worker 报 `ERR_WORKER_INVALID_EXEC_ARGV` → 用 `NODE_OPTIONS="" npm run build`。
- 新日志事件用调用点字面量并同步 `OBSERVABILITY.md` 实测总数；新增 migration 同步 `OPERATIONS.md` 清单 + `test_alembic_migration.py` 登记；SQLite 多语句 migration 用 `_exec_script` 拆分。

## 已交付
- M1：推送（notify_log / 双通道 / 默认不发送但审计）、参与流水（plan/task 状态机，user_id 仅 token）。
- M2/F3：ROI 台账（0007）、6 API、Portfolio `RoiLedger`；回测按 `live|backtest` 分桶，校准只计 live；数据集 19/50（14 正 / 5 负）。
- 回测：`PYTHONPATH=. python scripts/run_backtest.py [--json] [--export-samples]`；读 `response.states` 而非 `results`。

## ADR-015 资格门（Accepted，已实现）
- 语义：`score` 答「项目好不好」，`veto` 答「现在还有没有可参与路径」。**否决只改 label，绝不改 score** —— 68 分改成 34 会被读成「模型认为项目差」，也让回测无法区分低分与规则否决。
- 落点 `scorer.py`：`_score_to_label` → `apply_eligibility_gate` → `_apply_confidence_degradation`，复用已有「只改 label」钩子，不重构加权求和。
- 两条规则：`already_launched`（已发币且无 points/明确空投/portal）FARM→IGNORE；`no_participation_path`（无 testnet/points/portal）FARM→WATCH（只到 WATCH，采集字段缺失可能误判）。非 FARM 原样返回。
- `is_already_launched_without_airdrop_path()` 由 `airdrop_signal.py` 已上市封顶与资格门**共用**，禁止写第三份判定。
- veto 不参与权重拟合（搜索空间只含八权重 + 两阈值，重加权时 veto 保持原值）。`veto_false_negatives` 必须独立于 FPR 监控 —— 误否决是把真机会永久挡掉。
- 实测：recall 1.000→0.929、fpr 1.000→0.400，目标函数 `recall−2×fpr` **−1.00 → +0.129**。Chainlink/Worldcoin score 仍 68/69。
- **待 owner 拍板**：`veto_false_negatives=1`，Jupiter 被 `no_participation_path` 误否决（参与路径是历史交易行为，三个信号字段表达不了）。放宽规则属业务调整，不单方面改。
- 回测 sector 已归一化到 `SECTOR_PROFILE` 键；`social`/`identity` 保留原值并在测试登记为已批准 fallback。**生产路径 sector normalize + 未命中 warning 仍未做**（独立立项）：查表大小写敏感且静默走默认档，会让 0.15 权重白扔。

## 其他约定
- Repository 三条写入路径（PG / SQLite UPSERT / legacy fallback）须同步。`weight_version`/`sub_scores` 用 COALESCE 保旧值，但 `veto` 必须 `EXCLUDED.veto` 直接覆盖 —— 一次成功评分若无否决要能清除过期 veto。
- `pipeline_run` 响应有逐键精确契约，勿随意加字段。写端点有 auth/document parity；文档路径标题不带 query。
- `.gitignore` 目录规则不可用 `git add -f` 强推；`.workbuddy/memory/` 日志可能被忽略但仍要维护。
- 生产遗留：P1-5 前端代理管理员密钥、P1-4 同步 IO、反代限流与采集器运行时 URL 白名单。M3/F4 为 watched wallets + Alchemy webhook。
