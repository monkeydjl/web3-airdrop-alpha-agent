# 项目记忆：Web3 Airdrop Alpha Agent System

> 2026-09-02 · 分支 `feat/action-loop-m2` 已推送，**PR #30** → `master`（远程默认分支是 master 不是 main）。push 仍需 owner 明示。

## 红线与门禁
- 只提供 FARM/WATCH/IGNORE 决策参考；绝不交易、代签、自动 farming、托管资金/KYC。先文档后代码；真相源：代码 + `docs/` > 旧路线图 > 本记忆。禁读写 `.env`/`.env.*`（`.env.example` 除外）。
- **commit 后必须 `sh .git/sync-head-ref.sh`，连续多个 commit 更要每次都跑。** 沙箱 git 拦截层会重放提交：每次 `git commit` 产生**两条 reflog**，且分支 ref 落后于实际提交。连续提交时第二次会拿陈旧 ref 当父节点，把前一个 commit 挤出历史（实测 `3fc9167` 父指向 `f2ffe02` 而非 `22dda91`，两个 commit 被压成一个，message 只剩后半件事）。内容不会丢（新提交是并集，`git diff` 可验证树相同），丢的是历史结构。判定：`git log --oneline -3` 看提交是否都在 + `for c in ...; do git rev-parse $c^; done` 看父链。修法就是跑那个脚本（它会打印 `ref 落后，修正:`）。`git reset --hard <正确commit>` 同样会被拨回，reset 后也要跑。
- 校准门槛固定：live ≥200、FARM ≥30，不可因回测下调。无 SQL 外键，路由显式级联。
- **DB 新列四处同落**：`db.py` 双方言 DDL + `init_db::_add_column_if_not_exists` + Alembic + `DATABASE_DDL.md`。漏第 2 处：既有表跳过 `CREATE IF NOT EXISTS` → `no column named X` → save 失败、run 报 failed，CI 全新库看不见。回归 `test_existing_database_reaches_full_column_parity_after_init`。另确认 API 有出口。
- **`except` 块内的清理动作必须再套一层 `contextlib.suppress`**：`HTTPCache.get()` 的 except 里裸 `unlink()` 自己抛的 `OSError` 没人接，一路冒泡穿出 `fetch()`，把「缓存读坏」这种可降级小事变成整个请求失败。缓存语义是有则加速无则回源，任何一层出问题都该退回真实请求。裸 `await Event.wait()` 同理危险：无超时会把一条用例失败放大成整套挂死，且 `--durations` 对挂起用例完全无效（只统计已完成的），定位只能按类/按测试二分看谁 rc=124。
- **一切后端命令走 `backend/venv/Scripts/python.exe -m ...`**（pytest 同理）：顶层 `python` 没装 ruff/mypy，系统 3.14 缺 `defusedxml` 会让 `tests/api/` 22 模块 collection error。CI ruff/format cwd 是 `backend/`，根目录 `evaluation/`、`scripts/` 不在门禁范围（16 条既有告警不用管）。pytest 加 `--no-cov`；**不要自己重定向输出**（会被沙箱中断且无输出），用后台任务 + `| tail -N`。structlog 断言用 `capture_logs()` 而非 caplog。新 migration 同步 OPERATIONS + alembic 测试；SQLite 多语句用 `_exec_script`。查测试按 `pytest --collect-only -q | grep`，别 grep 裸函数名（包在类里查不到）。
- **不要为了「验证失败是否既有问题」去动工作区。** `git stash push -- <路径>` 对未 track 新文件报错（须先 `git add`）；实测 `stash pop` 后 140+ 测试文件从工作区消失（靠 `git restore tests/` 救回）。正确判定：看**改动范围与失败模块是否相关**，不相关就是既有/环境问题。手写复现脚本必须照抄 autouse fixture 的全部 patch，否则会造出假根因（曾因漏 patch `assert_url_allowed` 误判成域名白名单问题）。
- **沙箱 safe-delete 是所有「文件删除类」失败的统一根因**：删不掉就抛 `OSError`。凡失败断言依赖「文件被删/被替换/被轮转」，先怀疑它、别怀疑业务代码。已确证纯环境问题的 3 条（CI run 33633294347 后端全量 **8m9s 全绿**）：`test_disk_cache_clear_removes_files`、`test_disk_cache_corrupt_file_handled`、`TestLogRotationIsReal::test_rotation_creates_backup_and_truncates_current` —— **刻意不改断言迁就本机**（会废掉门禁）。方法论：环境受限的失败别靠推理说服自己，push 让 CI 判。本机全量 ~45min vs CI 8min，差值是拦截器开销不是测试慢。绕过技巧：删不掉改 `write_bytes(b"")` 截断。
- **仓库内 `data/pytest_tmp`**：`conftest.py` 把 `tmp_path` 重定向到这里（绕沙箱目录锁），编码门禁 `SKIP_DIRS` 必须排除它，否则测试特意写的坏编码样本被当成仓库损坏 —— CI 全新 checkout 看不见、只在本地随执行顺序随机红。清理 best-effort 吞异常（残留几百 MB，已实测不影响耗时），排除必须做在扫描器侧。回归 `test_workspace_pytest_tmp_is_excluded_from_repository_scan`。
- 基线：后端 3226 passed/9 skipped（Task13 前）；前端全绿。前端 build：`.next` 清理受保护时先改名再删；用 `NODE_OPTIONS="" npm run build`。
- **远程比对一律用 `git ls-remote --heads origin <branch>`**：`git rev-parse origin/master` 返回陈旧本地 ref（`a0cfd7c` vs 真实 `4bd54f4`），与 `sync-head-ref.sh` 同源。`gh pr create` 中文长描述用 `--body-file`（用完删）。CI 未跑完时 `mergeStateStatus=BLOCKED` 属正常。
- **pytest 必须加 `-p no:cacheprovider`**：沙箱拦截 `.pytest_cache` 写入会让 pytest 以 exit 1 结束**且吞掉全部输出**（表现为「一堆点但没有 summary」），看起来像失败其实全过。
- **全仓扫描类测试：`if path.is_file(): continue` 这种静默跳过是门禁杀手。** 实测术语门禁因此在 CI 上只覆盖 backend 子树、漏掉 223 个文件（含 `docs/` 全部 69 个文档）却一路绿灯 —— `git ls-files` 返回路径**相对 cwd 且只列 cwd 子树**，而 CI pytest 的 cwd 是 `backend/`。凡自称「全仓」的扫描：路径基准显式钉在 `REPO_ROOT`（`--full-name` + `cwd=REPO_ROOT`，两个都要），且必须**断言真扫到了东西**（路径都存在、覆盖到 `docs/` 等关键目录），不能只断「结果为空」+「列表非空」。回归 `test_tracked_paths_are_repo_root_relative_regardless_of_cwd`、`test_scan_covers_docs_and_repo_root_files`。
- **文档里写事件类型/枚举值不要加反引号**：`test_operations_doc_parity` 与 OBSERVABILITY 门禁都按「反引号包裹的下划线标识符」抓指标名，包起来会被判成幽灵指标（`airdrop_candidate` 两次踩中）。`.workbuddy/memory/*.md` 是 git tracked 的，写记忆同样过术语门禁。**文档里引用日志事件名前先 grep 代码确认真名**：凭印象写 `llm.all_failed`（真名 `llm.all_providers_failed`）会被 `test_every_documented_event_is_emitted_somewhere` 抓住 —— 该门禁存在的理由就是「按不存在的事件名写 Loki 查询会永远返回空」。
- **日志事件名必须是调用点的字面量**：门禁用正则 `logger\.(warning|...)\("字面量"` 扫全仓，把事件名收进 helper（`_warn(event, **fields)`）后事件名成了变量，扫不到 → 文档里登记的会被判成幽灵事件。helper 只该负责「该不该发 + 返回 logger」，事件名留在调用点。
- **从被日志系统读取的 property 里写日志 = 结构性递归**：`redact._known_secrets()` 为了知道哪些字符串是密钥必须读 `settings.llm_providers`，而它在**每条日志记录**上都被调用 —— 于是 `llm_providers` 里 `logger.warning` 会无限递归（实测 `RecursionError` 红 6 条）。修法：模块级**深度计数器**（不是布尔！布尔会让最外层解析自己也置标志，连第一条告警都发不出去，而告警静默正是要修的问题本身）+ 指纹去重集合（不去重会让一条告警跟着全部日志量翻倍）。测试要配 `_reset_*_for_tests()`。
- **`for x in lst` 里重新绑定 `lst` 这个名字对当前迭代完全无效** —— 迭代器进入循环时就取好了。`llm/client.py` 的 provider 跳过靠「重建 combinations 列表」实现，是**死代码**，挂掉的接口被逐个模型重试（6 接口 × 3 模型下一次降级从 10s 拖到 30s）。它一直没被测出来是因为既有用例每个 provider 只配 1 个模型，「跳过剩余」和「没有剩余」看起来一样 —— **写 failover 用例至少给一个 provider 配 2~3 个模型**。修法：显式 `failed_providers: set[str]` + 循环开头 continue。连带 `will_retry=len(attempts) < len(combinations)` 也失真（跳过的组合不进 attempts、连接失败让剩余模型作废），只朝「还有兜底」方向错报，把排查引向不存在的「重试为什么没生效」。
- **`.env.example` 的 `env-external` 标记必须逐键写**：门禁的注释块以空行和上一个键为边界，一个标记不会跨键蔓延（刻意设计，防整文件豁免）。批量加键时漏标会红出「既不是 Settings 字段、也没标 env-external」。
- **`asyncio.Lock` 不要在模块顶层建**：会绑到导入时的 event loop，测试里每个 async 用例是新 loop，绑错 loop 的锁在 `await acquire()` 上抛 "attached to a different loop"，而那与被测逻辑毫无关系。惰性创建 + `_get_lock()`。
- **`.gitignore` 的 `.env.*` 够不到 `.env copy`**（空格后缀，不是点号后缀）。实测工作区里的 `.env copy` 一直未被忽略、在 `git add .` 射程内。已加 `.env[ _-]*` 覆盖 copy/backup/_bak/-old 形态，门禁 `test_gitignore_secret_coverage.py` 钉住（含反向约束「`.env.example` 必须仍可见」，防一条粗暴 `.env*` 把模板也埋掉）。**gitignore 漏洞是沉默的**：不报错不变红，直到密钥推上远程才发现，而泄露不可撤销。查忽略状态用 `git check-ignore --no-index -q`，别自己解析 glob。
- **编码门禁（二型）判据是「半角 ? 紧贴中文」，`${VAR:?中文提示}` 会被误报**：compose 靠这个 POSIX 语法把 API_KEY/POSTGRES_PASSWORD 做成硬必填，那个 `?` 是语法字符。2026-09-03 实测 prod compose 5 处 + 基础 compose 1 处（由 `be9ebbb` 引入，当时没跑该门禁）。`blank_code_blocks` 只屏蔽 markdown 围栏与反引号，YAML/env/sh 里没反引号所以够不到 —— 已加第三条排除 `_SHELL_PARAM_EXPANSION`（非贪婪 `[^{}\n]*`，贪婪会把两个扩展之间的散文一并豁免）。**不要反过来改 compose 迁就检测器**（改英文提示或删 `:?` 等于废掉必填门禁）。回归 `test_shell_required_param_expansion_is_not_corruption` + `test_prose_outside_param_expansion_is_still_checked`。写该文件的测试样本必须用 `_c(before, after)` 拼接，字面量会让测试文件自己被判损坏。
- **裸属性访问在测试里会被 ruff B018 判为无用表达式**：`s.llm_providers` 单独一行不行，改成 `assert s.llm_providers == []` 这种既过门禁又多断一件事的写法（`_ = x` 只是绕过、不增加约束）。

## 已交付
- M1 推送审计与参与流水；M2/F3 ROI（0007、6 API、Portfolio）和 live/backtest 分桶回测；数据集 19/50。回测 `PYTHONPATH=. python scripts/run_backtest.py`，读 `response.states`。

## 评分决策引擎硬语义
- **ADR-015 资格门（Accepted）**：score 答项目好不好，veto 答还有没有参与路径。否决只改 label，绝不改 score。规则：`already_launched` FARM→IGNORE，`no_participation_path` FARM→WATCH；非 FARM 原样。发币判定与 `airdrop_signal.py` 共用，禁止第三份。veto 不参与权重拟合；误否决独立监控。
  - **参与路径含 4 条**：testnet / points / task_portal / `explicit_airdrop_mention`（2026-09-02 放宽，历史行为型空投没有点击入口）。**两条规则顺序不可调换**：already_launched 必须在参与路径判定之前，否则"币已发完只剩公告"会被救成 FARM。当前 recall 1.000、FPR .400、目标 +.200、误否决 0。
  - 放宽规则前**必须先算影响面**（逐条核对会被影响的样本），不能只看目标样本转绿。19 条里仅 1 条命中 explicit 信号，补到 50 条后需复核；若出现"提过空投但没发"的样本，该信号要改成与其他证据联合成立。
- **sector 查表已修**：`resolve_sector_profile()` 三级查找，未命中 `(DEFAULT_PROFILE,None)` + `narrative.sector_profile_missing`；避免 narrative_timing 恒 60。归一只能在查表/分组侧，绝不扩 `normalize_sector()`（参与确定性 ID）；RWA 等真未知保持未命中+告警；校准前确认维度非零方差。
- **competition 拆组已修**：`canonical_sector_key()` 与 profile 查表共用别名；orchestrator 计数与 scorer 查表必须都按规范键，否则静默退 50。未知 sector 返回 trim 原值不塌 None（否则 RWA/SocialFi 互算竞品）；ZK 独立不折 L2；project.sector 不改。
  - 全库用 `canonical_sector_counts()`：`GROUP BY sector` 后 Python 折叠，不能精确 `WHERE sector=?`（DEX 查不到 Dexes），刻意不过 `SectorCountCache`（单键缓存装不下折叠分布）。瓶颈时走 PG 物化表按规范键存。
  - 测试 `test_competition_grouping.py`（反向改回会红 4 条）。COMPETITION_MAP 阈值是否过宽仍需真实分布校准。

## 其他
- Repository PG/SQLite/legacy 三写路同步；weight_version/sub_scores COALESCE 保旧，veto 须 EXCLUDED 覆盖。`pipeline_run` 响应逐键契约；写端点 auth/doc parity。`.gitignore` 不用 `git add -f`。
- **前端传递依赖漏洞走 `frontend-next/package.json` 的 `overrides`**（postcss、browserslist 已在内）。`npm audit --audit-level=high` 是 CI 硬门禁，会单独红掉 Frontend job；直接依赖里查不到的包只能 override。改完必跑 audit + typecheck + test + lint + build 五项。
- 遗留：数据集补 50；explicit_no_airdrop；M3/F4 watched wallets + Alchemy；前端代理管理员密钥、同步 IO、反代限流、采集 URL 白名单。
