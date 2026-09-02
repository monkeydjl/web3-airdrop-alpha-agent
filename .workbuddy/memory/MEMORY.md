# 项目记忆：Web3 Airdrop Alpha Agent System

> 2026-09-02 · 分支 `feat/action-loop-m2`，仅本地提交，未经 owner 明示不得 push。

## 红线与门禁
- 只提供 FARM/WATCH/IGNORE 决策参考；绝不交易、代签、自动 farming、托管资金/KYC。先文档后代码；真相源：代码 + `docs/` > 旧路线图 > 本记忆。禁读写 `.env`/`.env.*`（`.env.example` 除外）。commit 后跑 `sh .git/sync-head-ref.sh`。
- 校准门槛固定：live ≥200、FARM ≥30，不可因回测下调。无 SQL 外键，路由显式级联。
- **DB 新列四处同落**：`db.py` 双方言 DDL + `init_db::_add_column_if_not_exists` + Alembic + `DATABASE_DDL.md`。漏第 2 处：既有表跳过 `CREATE IF NOT EXISTS` → `no column named X` → save 失败、run 报 failed，CI 全新库看不见。回归 `test_existing_database_reaches_full_column_parity_after_init`。另确认 API 有出口。
- **一切后端命令走 `backend/venv/Scripts/python.exe -m ...`**（pytest 也一样）：顶层 `python` 没装 ruff/mypy，系统 3.14 缺 `defusedxml` 会让 `tests/api/` 22 模块 collection error。CI ruff/format 的 cwd 是 `backend/`，根目录 `evaluation/`、`scripts/` 不在门禁范围（那里 16 条既有告警不用管）。pytest 加 `--no-cov`（沙箱删不掉 `.coverage`）；全量约 45 分钟，只能后台单跑且**不要自己重定向输出**（会被沙箱中断且无任何输出），用后台任务 + `| tail -N`。structlog 断言用 `capture_logs()`，不能用 caplog。新 migration 同步 OPERATIONS、alembic 测试；SQLite 多语句用 `_exec_script`。
- **不要为了「验证失败是否既有问题」去动工作区。** `git stash push -- <路径>` 对未 track 新文件直接报错（须先 `git add`）；本机实测 `stash pop` 后 140+ 测试文件从工作区消失（靠 `git restore tests/` 救回）。正确判定方式：看**改动范围与失败模块是否相关**，不相关就是既有/环境问题。
- **仓库内 `data/pytest_tmp`**：`conftest.py` 把 `tmp_path` 重定向到这里（绕沙箱目录锁），编码门禁 `SKIP_DIRS` 必须排除它，否则测试特意写的坏编码样本会被当成仓库损坏 —— 且 CI 全新 checkout 看不见、只在本地随执行顺序随机红。清理是 best-effort 且吞异常（残留会累积到几百目录/几百 MB），所以排除必须做在扫描器侧。回归：`test_workspace_pytest_tmp_is_excluded_from_repository_scan`。
- 基线：后端 3226 passed/9 skipped（Task13 前）；前端全绿。前端 build：`.next` 清理受保护时先改名再删；用 `NODE_OPTIONS="" npm run build`。

## 已交付
- M1 推送审计与参与流水；M2/F3 ROI（0007、6 API、Portfolio）和 live/backtest 分桶回测；数据集 19/50。回测 `PYTHONPATH=. python scripts/run_backtest.py`，读 `response.states`。

## 评分引擎硬语义
- **ADR-015 资格门（Accepted）**：score 答项目好不好，veto 答还有没有参与路径。否决只改 label，绝不改 score。规则：`already_launched` FARM→IGNORE，`no_participation_path` FARM→WATCH；非 FARM 原样。发币判定与 `airdrop_signal.py` 共用，禁止第三份。veto 不参与权重拟合；误否决独立监控。实测 recall 1→.929、FPR 1→.4、目标 −1→+.129。Jupiter 误否决 1 条待 owner 决策，不能单方面放宽。
- **sector 查表已修**：`resolve_sector_profile()` 三级查找，未命中 `(DEFAULT_PROFILE,None)` + `narrative.sector_profile_missing`；避免 narrative_timing 恒 60。归一只能在查表/分组侧，绝不扩 `normalize_sector()`（参与确定性 ID）；RWA 等真未知保持未命中+告警；校准前确认维度非零方差。
- **competition 原始写法拆组已修（Task13）**：`canonical_sector_key()` 与 profile 查表共用别名，orchestrator 计数和 scorer 查表必须都按规范键，否则会静默退 50。未知 sector 返回 trim 原值，不能全塌 None（RWA/SocialFi 会互算竞品）；ZK 是独立赛道，不折 L2。project.sector 不改。
  - 全库用 `canonical_sector_counts()`：一次 `GROUP BY sector` 后 Python 折叠，不能精确 `WHERE sector=?`（DEX 查不到 Dexes），也刻意不过 `SectorCountCache`（单键缓存装不下整张折叠分布，原始键失效打不中规范键）。若成瓶颈，PG materialized table 按规范键存。
  - 测试 `test_competition_grouping.py`；反向改回原始分组会红 4 条。ADR-015/010、DATA_SCORING_DICT、ACTION_LOOP 已同步；competition map 阈值本身是否宽松仍需真实分布后校准。

## 其他
- Repository PG/SQLite/legacy 三写路同步；weight_version/sub_scores COALESCE 保旧，veto 须 EXCLUDED 覆盖。`pipeline_run` 响应逐键契约；写端点 auth/doc parity。`.gitignore` 不用 `git add -f`。
- 遗留：数据集补 50；explicit_no_airdrop；M3/F4 watched wallets + Alchemy；前端代理管理员密钥、同步 IO、反代限流、采集 URL 白名单。
