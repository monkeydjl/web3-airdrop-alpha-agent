# 工作区文件布局与清理指南

> 配套文档：[OPERATIONS.md](OPERATIONS.md) §1.2（库文件到底在哪）、§6（备份）、
> §9.2（.env 事故与编辑纪律）、§12.5（备错库史）。
>
> **写作规则同 OPERATIONS**：只写**实测为真**的。本文件成文于 2026-10-01
> 大清理当天——那次清理把每个"看起来像垃圾"的文件都考古了一遍引用关系，
> 结论固化在这里，下次清理直接查表，不用重新考古。
>
> ⚠️ 本文件自身遵守一个反直觉的纪律：**记录"删过什么"和"记录"留着什么"
> 同样重要**。把已删除的文件当不存在会导致有人去别处找它；把没删的当
> 已删会导致重复劳动或误删。

---

## 0. 三问判据

删除任何文件前过一遍，任何一问答不上来就不删：

1. **有引用吗？**——`grep`/`code_search` 文件名，范围：`backend/app` +
   `backend/tests` + `backend/scripts` + `docs` + `Makefile` + `Start.bat`/
   `Stop.bat` + `.vscode`/`.idea`。注释里的引用也算（本仓库有"注释教人
   填配置"的传统，见 `config.py` 对 `configs/development/` 的引用）。
2. **删了谁重建？**——pytest conftest / next build / ruff / mypy / 编译器
   都有各自的自动产物。答不出重建者的一律进灰区（§3）。
3. **承载不可再生数据吗？**——活动库、备份、密钥、回测集、一次性调试
   的结论。数据不可再生 ≠ 文件不可再生。

---

## 1. 活文件区（清理红线，永不进删除清单）

| 路径 | 是什么 | 为什么不能删 |
|---|---|---|
| `backend/data/airdrop.db`（+-wal/-shm） | **活动库** | 后端正在写（1314+ raw_projects / 43 表）。备份判据见 OPERATIONS §6.1 |
| `backend/venv/` | Python **3.11.9** 真实虚拟环境 | Start.bat、OPERATIONS §3.1、所有文档指向它；系统 Python 3.14 跑不了本项目 |
| `.env` | 全部运行配置 | 2026-10-01 曾因脚本误编辑丢前 115 行（§9.2 专坑）。**编辑必先 `cp` 留底，改完用服务同款 CWD 做语义验证** |
| `.env copy` / `.env copy 2` | 历史副本 | `.env copy 2`（9-03）是当天事故的救命恢复源 + HMAC oracle 依据。留着不占地方 |
| `backups/` | 自动+手动+PG 归档备份 | OPERATIONS §6；`pg-final/` 是已停用 PG 栈的唯一最终归档 |
| `backend/data/backtest/` | 回测数据集（`airdrops_2024_2025.json`） | 无再生途径 |
| `configs/development/` `production/` `staging/` | 环境配置模板目录 | `backend/app/config.py` 引用（教学/自检口径），删了配置体系口径断 |
| `data/cache/`（仅 `.gitkeep`） | 目录占位 | 应用缓存目录约定 |
| `logs/` | 运维证据 | `LOG_MAX_BYTES` 自动轮转（§12.6），有界；**事故排查期间别清**——日志是证据不是垃圾 |
| `frontend-next/node_modules/` | 前端依赖 | `npm install` 可重建但要分钟级 + 网络，日常清理无收益 |
| `frontend-next/.env.local` | 前端本地配置 | 同 `.env` 纪律 |
| `frontend-next/next-env.d.ts` | Next 自动生成 | **被 tsconfig 引用**：删了 typecheck 立刻红；`next dev/build` 重建。灰区，默认留 |
| `.claude/` `.freebuff/` `.workbuddy/` `.workbench/` | Agent/工具状态目录 | 工具会话与工作台状态 |
| `AGENTS.md` `CLAUDE.md` `opencode.json` | Agent 工具配置 | gitignore ≠ 垃圾 |
| Docker 数据卷（不在 git 内） | `airdrop_pg_data`（已停用栈的 PG 数据）、`grafana-data`、`loki-data` | 见 OPERATIONS §1 停用记录；卷归 Docker 管辖，`docker volume rm` 是不可逆动作 |

**曾引起混淆的两个 venv**：Makefile 的 `setup-venv`/`clean-all` 目标操作的
`.venv` 指**仓库根**，与 `backend/.venv` 无关。真实虚拟环境是 `backend/venv`
（3.11.9）。

---

## 2. 再生区（随时可删，删完自动重建）

| 路径 | 谁重建 | 备注 |
|---|---|---|
| `data/test.db`{`,-wal,-shm`}、`data/test_gw*.db` | pytest conftest 会话兜底 | xdist 残留曾实测 86MB（conftest 注释）；每轮测试自动重建 |
| `data/test.db.cleanliness.json` | conftest session finish 快照 | 同上 |
| `data/pytest_cache_dir{,_gw*}/`、`data/pytest_tmp/` | conftest（cache/慢盘兜底） | conftest 内有专门注释解释选址 |
| `backend/data/_probe/`、`backend/data/t.db` 等 | 行为钉测试沙箱 | 一次性，用完即弃 |
| `.pytest_cache/`（根 + backend/）、`.mypy_cache/`、`.ruff_cache/`、`__pycache__/`、`.pytest_workdir/` | 对应工具首跑重建 | Windows 下偶尔被短暂句柄锁住删不掉，无妨——零字节级 |
| `htmlcov/`、`backend/htmlcov/`、`.coverage`、`backend/.coverage`、`backend/coverage.xml` | `pytest --cov` | |
| `frontend-next/.next/`、`tsconfig.tsbuildinfo` | `next build` | 前端构建产物 |

---

## 3. 灰区（存疑就别删，先登记在这里）

| 项 | 状态 |
|---|---|
| `backend/.venv/` | 曾是 3.12.13 废弃虚拟环境副本，2026-10-01 已删。**若再出现 = 某个工具误建**，先查来源再删 |
| `SESSION_MEMORY_*.md` ×9 | **git 跟踪文件**，归 git 历史管，不归工作区清理管 |
| `docs/_utf8_worklist.json` | 一次性工作清单，2026-10-01 已删；再出现时查生成者 |
| `.pytest_cache` 删不掉 | Windows 短暂句柄占用（杀软/索引器），零字节级，留着无害 |
| `data/airdrop.db`（仓库根） | 曾是 7 月 94 项目时代的过期副本，2026-10-01 已删。**别再把它当备份/恢复目标**——真库在 `backend/data/`（§1.2） |

---

## 4. 2026-10-01 清理记录（考古结论存档）

**工作区侧**（本次文档的直接产物）：

| 删除项 | 体积 | 验证依据 |
|---|---|---|
| 测试库三件套 + xdist 残留 + pytest 目录 ×2 处 | ~8MB | 冒烟 `pytest tests/test_db_init.py tests/test_cleanliness_snapshot.py` 16 passed，产物自重建 |
| `t.db` `diag*.db` `test-*.db` ×8、`probe.bin`、`_probe/` | ~3MB | 无代码引用，纯 8-9 月调试残留 |
| `htmlcov` ×2、`.coverage` ×2、`coverage.xml`、mypy/ruff cache ×2 | ~35MB | 纯报告/缓存 |
| `backend/.venv`（3.12 废弃 venv） | 大 | 真实 venv 是 `backend/venv`（3.11.9），IDE/脚本零 `.venv` 引用 |
| `backend/airdrop.db`（0 字节）、`data/airdrop.db`（311KB 过期副本）、`data/pytest_full_m1*.log`、`docs/_utf8_worklist.json` | ~1MB | 过期/一次性 |
| `backend/data/airdrop.db.bak-20260905-*` ×4 + `bak-20260806` | ~26MB | **稳定性实证后删**：galaxy 假数据 26 天零复发（资格过滤已在代码三处落地 `07d30ac`）、采集管线每日正常、有更新的还原点（当日 17:12 zip，integrity ok） |

**Docker 侧**（约 60GB，详见 OPERATIONS §1 停用记录）：已停用生产栈的
旧镜像 ×12 + 悬空层 + 构建缓存；数据卷全部保留。

**2026-10-05 例行清理**（按 §5 SOP，PR #38 合并后）：

| 项 | 体积 | 处理 / 依据 |
|---|---|---|
| `backend/htmlcov`、`backend/.coverage`、`backend/.mypy_cache`、`.ruff_cache`、全部 `__pycache__/` | ~63MB | 删；§2 再生区 |
| `data/test*.db`、`data/pytest_tmp/`、`backend/data/_probe/`（空） | ~3MB | 删；冒烟 16 passed，conftest 已自重建 |
| `frontend-next/.next/` | 921MB | 删；先停掉 `next dev --port 3002`（开着删会把 dev server 弄挂），下次 `npm run dev` / Start.bat 重建 |
| `backend/.pytest_cache/`、`backend/.pytest_tmp/` | — | Permission denied，同 §3 句柄占用，留着无害 |
| git worktree `opportunity-economic-data-acquisition` | — | `git worktree prune`：记录指向的 `E:/…/.worktrees/` 已不存在 |
| 已并入 master 的本地分支 ×21 | — | `git branch -d`（仅已合并才删得掉）；tip 均是 master 祖先，`git branch <名> <SHA>` 可恢复（SHA 同下表远端） |
| 本地 `fix/mypy-strict`（`934571d`） | — | `git branch -D`：唯一 commit 经 `git cherry` 判定已以别的 SHA 进 master |
| 本地 `backup/lint-recovery-pre-rewrite`（`38230f7`） | — | **留**：opportunity-economic 重写前副本，10 个 patch 与 master 不等价，需人工确认是否有遗漏 |
| `origin` 上已合并分支 ×25 | — | `git push origin --delete`；tip 均在 master 历史里，恢复用 `git push origin <SHA>:refs/heads/<名>` |

远端分支删除前的 tip（恢复依据）：`chore/root-pyproject-mypy-alignment` 97af329、
`chore/security-scan-no-cache-docs` c149ca1、`docs/record-verified-green` e1ce298、
`docs/session-wrap-0828` c7833ae、`docs/truthful-data-source-strategy` 187aa7d、
`feat/action-loop-m2` 734f0a7、`feat/llm-budget-enforcement` 43fab41、
`feat/scheduler-jobs-endpoint` c4f57a0、`fix/admin-only-write-endpoints` fea429c、
`fix/agent-budget-refusal-distinct` 6628991、`fix/encoding-mode3-and-collection-readiness` 81b3bf7、
`fix/encoding-type4-bom` 4bd4739、`fix/expose-label-thresholds` 013a590、
`fix/frontend-truthful-config` 392c399、`fix/label-vocabulary-gate` b80aac0、
`fix/mypy-strict` 375a890、`fix/production-config-hardening` 8e997d3、
`fix/risk-level-vocabulary` b9b6d8f、`fix/security-doc-parity` 03b35f3、
`fix/security-scan-permissions` f61787c、`fix/truthful-api-spec-and-ui-fidelity` d3e35d6、
`fix/truthful-env-example` c6c8925、`fix/truthful-observability-and-log-level` b8655b7、
`fix/truthful-operations-runbook` 8585202、`release/v2-consolidation` 0f3e606。
仅本地存在过的已删分支：`docs/action-loop-design` cfa6350、`feat/action-loop-m1` 760582b、
`feature/opportunity-economic-data-acquisition` d9794fe、`fix/p1-audit-hardening` cbbfea4。

---

## 5. 清理 SOP（下次照做）

1. **盘点**：`git status --ignored --short` 看全貌；`docker system df` 看 Docker 侧。
2. **对照本文件**：先分拣进 §1（不删）/ §2（删）/ §3（登记不删）。
3. **引用核查**：新面孔（本文件没登记的）必过 §0 三问，查完把结论**登记进本文件**再动手。
4. **删 §2 产物** → 跑冒烟（`pytest tests/test_db_init.py tests/test_cleanliness_snapshot.py --no-cov -q`）证明自重建。
5. **`.env` 永远不走批量脚本编辑**（§9.2 的血泪：split 后段拼接丢前半部 + 验证 CWD 不对造成假绿）。
6. 删备份类文件前先确认有**更新的还原点**（§6.1 验证过的 zip）。
7. 本文件与实际状态的任何分叉，当天修文档——这份文档的价值就在于它不过期。
