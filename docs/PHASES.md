# PHASES — Web3 Airdrop Alpha Agent System

> 阶段进度真相文档。状态如实记录，未完成就写「进行中 / 受阻」，不写「完成」。
> 里程碑划分沿用 [`ENGINEERING_ROADMAP.md`](ENGINEERING_ROADMAP.md) §12 演进路线与 §13 周次排期。
> 每条状态附**可复跑的验证方式**，避免下次会话凭记忆汇报。

---

## 当前阶段：W11 — 反馈与校准闭环

**状态：进行中（链路已通，等真实样本积累）**

### 目标（对齐 Roadmap §13 W11 验收门）

让「用户反馈 → 权重校准」这条链路可用：样本 ≥200 触发首次校准，且 `weight_changelog` 记录完整。

### 已完成

- [x] `feedback` / `events` / `weight_changelog` 三张表存在（`app/repositories/v2.py`、Alembic 迁移）
- [x] 反馈提交端点 `POST /api/v1/feedback`（单条）
- [x] 校准状态端点 `GET /api/v1/calibration/status`（返回样本数、门禁、信号分布、changelog）
- [x] 权重搜索与门禁校验：`app/calibration.py` + `scripts/calibrate_weights.py`
      （Roadmap 里写的 `backtest.py` 实际实现在 `calibration.py`，命名不同、能力齐备）
- [x] **降低样本录入成本**（2026-08-21）：`POST /api/v1/feedback/batch` 批量标记
      + `GET /api/v1/feedback/pending-review` 待标记清单 + `/review` 页面（三按钮一行）
      + 工作台可见的校准进度条
- [x] 批量端点安全加固：未知 `project_id` 整批拒绝（否则可用伪造数据填满门禁）

### 进行中 / 未达成

- [ ] **首次校准尚未触发**：当前样本 `0 / 200`（`GET /api/v1/calibration/status`
      实测 `calibration_ready=false`）。链路已可用，但需要真实使用积累样本 ——
      这是**使用量问题，不是工程问题**
- [ ] `weight_changelog` 为 0 条：首次校准跑起来才会产生记录
- [ ] 误报 2× 惩罚（Roadmap §24.2：`label=FARM` 但 `outcome=not_airdropped`）
      —— 待首次校准时验证实际生效

### 验证方式

```bash
# 校准门禁与样本进度
curl -H "X-API-Key: $API_KEY" http://localhost:8002/api/v1/calibration/status
# 待标记清单（前端 /review 页消费的就是这个）
curl -H "X-API-Key: $API_KEY" "http://localhost:8002/api/v1/feedback/pending-review?limit=5"
```

### 阻碍

无工程阻碍。**唯一门槛是需要真实参与并标记结果**，200 条门禁是统计显著性要求，
不应为了"让它跑起来"而调低（调低等于用噪声改评分权重）。

---

## 提前完成的 V3 子项

### ✅ 自动 farming checklist 生成（Roadmap §12 V3 条目）

原属 V3 范围，因「评分结果无人跟进」这一实际问题而提前落地：

- `app/services/participation_tasks.py` — 按项目信号生成带优先级的参与清单
- `app/services/action_queue.py` — **跨项目**聚合成「今日行动」（2026-08-21 新增）
- `GET /api/v1/action-queue` + 工作台卡片；完成状态复用 `interactions` 表

同期修掉一个使该功能长期形同虚设的 bug：扩展信号存在 `meta.signals` 而代码读顶层
键，导致 281 个项目信号判断恒为 False、任务退化为通用套话。修复后单项目任务数
从恒定 5 条变为 5~15 条（详见 CHANGELOG 2026-08-21）。

**验证**：`curl -H "X-API-Key: $API_KEY" "http://localhost:8002/api/v1/action-queue?limit=5"`

### 未开始的其余 V3 子项

- [ ] 多钱包策略建议（基于风险 / Sybil 难度）
- [ ] Memory 系统（Roadmap §24.3：项目画像、`user_profile` 偏好向量）
- [ ] 异常检测告警（Prometheus 指标已齐，检测逻辑未做）

---

## 历史阶段

### W12-补 — 上线阻断项修复（2026-08-20 完成）

**结论：完成。** 独立复核推翻了既有「✅ 可上线」结论，发现并修复 4 个 P0 + 8 个 P1。

- 关键发现：`/settings/config` 明文回显 LLM API Key（配合公开的匿名 token 构成
  零凭证窃取链路）；按官方文档启动容器必然 CrashLoop；两个整页虚构数据；
  测试实为 1 failed 且 CI 三门全红
- 详见 [`../CODE_REVIEW_REPORT.md`](../CODE_REVIEW_REPORT.md) 与
  [`../GO_LIVE_AUDIT_REPORT.md`](../GO_LIVE_AUDIT_REPORT.md)
- 教训：不要采信文档里的「已实测确认」，自己跑一遍

### W1–W10 — MVP 至 V2 数据层（此前完成）

按 Roadmap §13 排期推进，具体交付见各阶段 `SESSION_MEMORY_*.md` 与 `CHANGELOG.md`。
当前形态：8 维评分决策引擎（Σ=1.0 启动断言，ADR-006）+ 规则引擎默认路径
+ 可选 LLM 增强（ADR-001）+ 旁路机会引擎 v2.0 影子评估；9 个真实采集器；
SQLite/PostgreSQL 双后端 + Alembic；Prometheus + Grafana + Loki + OTel。

---

## 当前基线（2026-08-21 实测）

```
pytest -q                     → 2490 passed, 4 skipped, 0 failed（32分55秒，exit 0）
覆盖率                         → 87.85%（门槛 80%）
ruff check / format           → All checks passed / 241 files already formatted
mypy app                      → no issues in 114 source files
前端 tsc / eslint / next build → 全绿（eslint 0 problems）
```

> ⚠️ 两个环境陷阱：`ruff format --check .`（全仓带点）在 ruff 0.16.1 会 panic，
> 必须按子目录跑；全量 pytest 约 33 分钟，不要误判卡死。

## 未决事项（跨阶段）

- **30 个本地 commit 未推远程**（实测 `git rev-list --count origin/master..HEAD`）
- **文档编码损坏三型，共 542 处待处理**：
  - 一型（非法 UTF-8）1116 处 → 已修 646 处（58%），**470 处**待人工判定。
    `DATA_SOURCE_STRATEGY.md` 占 350 处且无干净历史底本。
  - 二型（整字变 `?`，仍是合法 UTF-8）`docs/API_SPEC.md` **70 处**，
    只检测不修复 —— 实测它连"1 字符换 1 字符"都不成立（24 处可核对位置里，
    恰好 1 字符的 0 处、多于 1 字符的 24 处），无法机械校验修复没越界。
  - 三型（字面 U+FFFD）`docs/SYSTEM_DIRECTION_CHANGE.md` **2 处**，
    丢的是两个小节标题的装饰性 emoji，**损失可忽略**；只登记不修复
    （补图标属内容编辑，不是数据恢复）。
  - 已挂 pre-commit 钩子防复发，三型都拦。详见 `docs/ENCODING_REPAIR.md`。
- **上下文推断规则在大样本下不是 100%**（箭头 92.2% / 括号 99.6% / 句号 99.4%）。
  本次输出因与底本交叉验证（冲突 0）而未受影响，但规则本身待收紧。
  这是我自己更正的一条结论：最初只用 5 个文档量出 100%，**小样本给了虚假的
  安全感**。
- **术语闸门此前是坏的且无针对性测试**：`check_terminology.py --all` 实跑失败
  （3 文件 5 处）。已加行级豁免机制 + 27 个测试 + 把 `--all` 结果固化成测试
  （此前只有 pre-commit 守，`--no-verify` 就绕过了）。现在退出码 0。
- **OTel 降级路径已补测试**：拆成可选依赖后，"缺包时能降级"从隐含假设变成
  契约，补了 18 个测试（`app/tracing.py` 覆盖率 44% → 58%）。
  正向路径（真装 OTel 能上报）本机无法验证，PyPI 不可达。
- `SEED_FALLBACK_ENABLED` 生产建议设 `false`（默认 `true`）
- **Python 版本口径不一致**：镜像与 CI 用 3.12、mypy 配置写 3.12，
  但本地 venv 是 3.11.9（`requires-python = ">=3.11"`）。
  意味着本地跑通 2500+ 测试的解释器与生产镜像里的不是同一个。
  需所有者决定统一到哪个版本 —— 两种选择代价不同，未擅自改。
- ~~Docker 依赖未锁版本（`requirements.txt` 全浮动 `>=`）~~ →
  **已锁定**（2026-08-21）：拆成三个文件，运行时 13 个 + 开发 7 个全部精确 `==`，
  逐包与本地跑通 2500 测试的环境核对一致，并在干净 venv 里实测装完能启动。
  CI 三处散装安装（`pip install ruff` / `pytest` / `mypy`）也改为装锁定文件。
  唯一例外是可选的 `requirements-otel.txt` 仍为区间 —— 本机无法访问 PyPI 无从
  验证，且该路径零测试覆盖，故不凭记忆写死版本（详见 docs/SECURITY.md §6.1）
- ~~`action-queue` 无缓存，项目数上万时需优化~~ →
  **已核实无需优化**（2026-08-21）：候选池固定 60，耗时与库内项目总数**无关**。
  实测端到端中位数 26ms（比 `/dashboard/overview` 的 46ms 更快），纯聚合
  约 0.04ms/项目。刻意不加缓存 —— 缓存会引入失效时机问题（标记「已做」需立即
  反映），收益只有几毫秒。已加测试锁死「考察项目数 ≤ 候选池上限」
- ~~`user_id` 过滤两处不一致~~ → **已统一**（2026-08-21）：抽出
  `app/services/user_scope.py`。根因是两张表写入约定不同（实测：
  `POST /interactions` 不传 user_id 落 **NULL**，`POST /watchlist/{id}` 落
  **'default'**）。现在默认用户会同时认 NULL 与 default，具名用户严格匹配、
  不读 NULL —— 多用户启用后不会跨用户串数据。`pending-review` 也补上了用户过滤
- `/archive` 与 `/ops` 部分区块仍无后端接口（当前为诚实占位，非假数据）

---

_更新日期：2026-08-21 · 里程碑定义见 ENGINEERING_ROADMAP §12/§13 · 术语以 docs/GLOSSARY.md 为准_
