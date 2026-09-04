# 项目记忆：Web3 Airdrop Alpha Agent System

> 2026-09-04 · 分支 `feat/action-loop-m2`，远程默认分支为 `master`。本记忆于 2026-09-04 精简改写，**改写前的详细踩坑版仅存于 git 历史**（`git show 5a32a0e:.workbuddy/memory/MEMORY.md`），排查历史问题时优先取回原版。

## 红线与验证门禁
- 只提供 FARM/WATCH/IGNORE 决策参考；禁止交易、代签、自动 farming、托管资金/KYC。真相源：代码与 `docs/` 优先；禁读写 `.env`/`.env.*`（`.env.example` 除外）。
- 每次 commit/reset 后运行 `sh .git/sync-head-ref.sh`；远程比对用 `git ls-remote --heads origin <branch>`，不要信陈旧本地远程 ref。
- 后端命令统一用 `backend/venv/Scripts/python.exe -m ...`；pytest 加 `--no-cov -p no:cacheprovider`。CI 是环境受限删除类测试的最终判定，勿改断言迁就沙箱。
- DB 新列必须同步双言 DDL、`init_db` 补列、Alembic、`DATABASE_DDL.md` 与回归测试；路由显式级联，无 SQL 外键。
- 全仓扫描必须以仓库根目录为 cwd，使用 `git ls-files --full-name`，并断言覆盖关键目录。事件名文档必须先从代码确认，调用点保留字面量；文档枚举/事件标识不要用反引号包裹。
- `.gitignore` 需覆盖 `.env`、`.env.*`、`.env copy/backup/_bak/-old` 及密钥文件，同时保留 `.env.example` 可见；用 Git 自身检查规则。
- `except` 清理动作套 `contextlib.suppress`；异步锁惰性创建；测试避免裸属性表达式（Ruff B018）。
- `data/pytest_tmp` 必须排除全仓编码扫描。`${VAR:?中文提示}` 是 Shell 必填参数语法，不应被乱码检测器误报。

## 已交付与当前语义
- M1 推送审计/参与流水；M2/F3 ROI、6 API、Portfolio、live/backtest 分桶回测。校准门槛 live ≥200、FARM ≥30。
- ADR-015 资格门：score 与 veto 分离，`already_launched` 优先于参与路径，FARM→IGNORE/WATCH；参与路径为 testnet、points、task_portal、explicit_airdrop_mention。sector/competition 使用规范化查表与 `canonical_sector_counts()`，未知 sector 保留原值并告警。
- LLM：配置优先级为 `OPENAI_*_N` → `LLM_*_N` → 单接口回退；provider 必须有 http(s) URL、key、至少一个 model，最多 10×10。候选按 provider×model 组合进程内 round-robin，调用开始推进指针并旋转完整列表；连接错误跳过 provider 剩余模型，模型错误仅跳过当前模型，预算/账本/泄漏检测立即停止。`is_llm_enabled` 与有效 provider 一致。多 worker 不保证全局均衡。
- LLM 主要文件：`backend/app/config.py`、`backend/app/llm/client.py`、`backend/app/routers/v1/llm.py`、`backend/tests/test_llm_failover.py`、`docs/adr/ADR-016-llm-provider-round-robin.md`。

## 前端中文化（2026-09-04 已完成静态层）
- 已中文化 10 个文件的显示层文案：InteractionPanel、OpportunityWorkflowPanel、RoiLedger、lib/api.ts、lib/export.ts、ops、portfolio、project/[id]、insights、settings。协议契约零改动。
- 边界：API 路由、环境变量、HTTP 头、后端枚举传输值、模型/版本号、品牌名、扩展名、输入前缀（tx:）一律保留原文；枚举走「传输值保留 + 显示层映射表」。
- 三条硬经验：中文不能套 `is-mono` 等宽类；健康状态要先判 ok 再回退后端 status，否则永远显示英文；`_STATE_FIXTURES` 等编译期类型夹具不是文案、不可翻译。
- 验证基线：前端 lint/typecheck/20 tests/build(12 页)/audit 0 漏洞，后端前后端一致性门禁 84 passed（enum/field/flag parity + structure + terminology）。改枚举映射后必须跑后端这 5 个文件。
- 遗留：ActionQueue、ParticipationTasks、评分理由、证据字段、blocker code 等**动态 API 值仍为英文**，需后端 zh 字段/locale 参数，前端静态替换无法解决。

## 其他
- **依赖必须锁到传递依赖层**：`anyio`、`starlette` 未锁曾让 CI 整套后端测试在收集阶段崩（本机装旧版看不到）。判据：collection error + 秒级失败 + 无覆盖率产物 = 环境/依赖问题而非业务代码。门禁 `backend/tests/test_requirements_pinning.py` 钉住，不要放宽 CI 的 `-W error::DeprecationWarning`。
- **当日记忆日志不进版本控制**：`.git/info/exclude` 忽略 `/.workbuddy/memory/*.md`，不要用 `git add -f` 强推；MEMORY.md 因已 tracked 不受影响。
- 前端依赖漏洞优先通过 `frontend-next/package.json` 的 `overrides`；改依赖后跑五项门禁。
- 遗留：数据集补 50、explicit_no_airdrop、M3/F4 watched wallets + Alchemy、前端代理管理员密钥/同步 IO/反代限流/采集 URL 白名单、动态 API 内容中文化（任务 #42）。
