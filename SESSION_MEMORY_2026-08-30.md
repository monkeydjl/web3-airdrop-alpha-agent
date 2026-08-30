# 2026-08-30

> 「四档」这个 long-running 目标今天收口：档1 安全缺口 / 档2 工程整洁 /
> 档3 可观测性 / 档4 数据源扩展与校准，全部在分支
> `feat/security-and-observability` 上落地（9 个提交，56d5c1a → 0d30ec6）。
> 已 push 到 origin，剩余：开 PR → CI 5 个 required context 走完 → 合并。

---

## 一、这个目标在干什么（给接手的人）

owner 拍板按顺序做四档，每项都要「补测试 + 实测不破坏运行时」，涉及产品取舍
（采集源选型 / Key / 白名单策略）向 owner 决策而非擅自定。四档已全部完成：

| 档 | 内容 | 关键提交 |
|---|---|---|
| 1 安全 | LLM 输出泄漏过滤、Agent 工具白名单、网络域名白名单+统一 HTTP 出口 | `56d5c1a` `9933f83` |
| 2 工程整洁 | pre-commit mypy hook 修对、删根 `[tool.mypy]`+`[tool.pytest.ini_options]` 死配置 | `4a2e2cd` |
| 3 可观测 | Agent 粒度指标、数据质量指标、HTTP 耗时 histogram、业务面板 | `47fd24c` `96f1d59` `0e25c3a` `73ba0f9` |
| 4 数据源 | P2 四个内容源采集器（Discord/Reddit/Medium/Mirror）、权重校准门槛钉死 | `a6745c0` `0d30ec6` |

---

## 二、owner 的两个关键决策（已拍板，不要再来回问）

1. **档4-1 P2 采集源：接全部 4 个**（Discord / Reddit / Medium / Mirror），
   并且 **owner 能提供 Key**（Discord bot token、Reddit OAuth）。
2. **权重校准门槛不调低**：有效样本 ≥200 / FARM ≥30 钉死，用测试锁住，
   不许"为了校准更快达标"把门槛调低。

---

## 三、技术要点（人话版 + 给接手 AI 的坑）

### 档4-1 四个 P2 源的本质
都是「内容里提到某项目」的**二阶信号源**，不是项目目录源。所以
`discovery_score` 上限刻意压在 **0.28**（低于 0.3 的分析阈值）——只贡献
`project_signals`，**永不触发 LLM 分析**。别把它们和 defillama/github 那类
"项目本身就是数据"的源混为一谈。

| 源 | 接入方式 | Key | 默认开关 |
|---|---|---|---|
| medium | `medium.com/feed/tag/{tag}` RSS | 无 | **开** |
| mirror | Arweave GraphQL（`arweave.net/graphql`，App-Name=Mirror） | 无 | **开** |
| reddit | OAuth client_credentials → `oauth.reddit.com/search.json` | client_id/secret/username | 关 |
| discord | Bot `discord.com/api/v10/channels/{id}/messages` | bot_token + channel_id | 关 |

**owner 还没给 Key**：discord/reddit 的采集器代码 + `.env.example` 占位都在，
`is_enabled()` 需要 Key 才为 true。等 owner 把 Key 填进 `.env` 即启用，
不用再改代码。要告诉 owner 填哪几个：`DISCORD_BOT_TOKEN`+`DISCORD_CHANNEL_ID`、
`REDDIT_CLIENT_ID`+`REDDIT_CLIENT_SECRET`+`REDDIT_USERNAME`。

### 公共代码 content_signals.py
四个源共享 `detect_signal()`（关键词→信号类型）和 `extract_name()`（从标题
抽项目名）。关键词字典 `SIGNAL_KEYWORDS` 是唯一权威，改它四个源一起变。

### 文档/门禁的双向 parity（这次最花时间的地方）
这个仓库有一堆「文档写 X 必须等于代码 X」的双向门禁，每加一个源要同步**五处**：

- `DATA_SOURCE_STRATEGY.md`：§2 优先级矩阵、§3 采集器表、§5.2 SOURCE_PRIORITY、
  §6.1 cron、§8.4 限流、§11 未实现清单、§12.9 失真记录
- `OPERATIONS.md`：§4.3 门控表（`collection-ready` block）+ §7.1 cron 表
- `SECURITY.md`：§10.2 域名白名单表（`domain-whitelist` block）
- `.env.example`：新增 24 个键（`test_env_example_parity.py` 会逐键比对值与默认值）
- 测试侧的真相函数：`test_operations_doc_parity.py` 的 `_collection_cron_from_settings()`
  和 `_collection_gating_from_code()`、`test_data_source_strategy_parity.py` 的
  `_real_cron()` / `_real_collectors()`

**最容易漏的**：`test_operations_doc_parity.py::_collection_gating_from_code()`
的 `needs_key` 正则原来是 `api_key|bearer_token|github_token`，discord 用
`bot_token`、reddit 用 `client_id/client_secret` 都不匹配 → 这次把正则扩成
`...|bot_token|client_id|client_secret`，否则文档表会把"要 Key 的源"判成"不要 Key"。

### 顺手修的遗留（不是本档，但 CI 会红）
- `OPERATIONS.md §12.1` 幽灵指标清单里还有 `airdrop_data_completeness_ratio`，
  它从档3 起就是真实指标了 → 移出清单（§12.1 计数 16→15）。

---

## 四、验证记录（实际跑过的命令）

| 检查 | 结果 |
|---|---|
| `mypy app --config-file pyproject.toml --no-incremental` | **Success: 126 source files 0 错误** |
| `ruff check app tests` | All checks passed |
| `ruff format --check app tests` | 258 files already formatted |
| 新增 4 采集器测试 `tests/collectors/test_{medium,mirror,reddit,discord}.py` | 17 passed |
| 4 份 doc parity（data_source_strategy / operations / security / env_example） | 118 passed |
| observability / operations / hardening / deployment / budget 门禁 | 151 passed, 1 skipped |
| 采集器全量 + 调度/归一化/白名单（`tests/collectors` 等） | 254 passed |
| **完整后端套件 `pytest`（--cov-fail-under=80）** | **3083 passed, 9 skipped, 88.82% cov, exit 0（34m08s）** |

---

## 五、独立评审与收口（2026-08-30 下午）

`CODE_REVIEW_REPORT.md`：结论「有条件通过」，1 个 blocker + 6 条建议，已逐条处理：

- **Blocker（owner 决策「诚实口径」）**：出站域名白名单运行时强制只 cover
  fetcher + LLM 两条路径，采集器没接运行时校验但文档宣称 fail-closed。修法 =
  诚实化 SECURITY §10.2/§10.3 + `domain_allowlist.py` docstring（采集器靠写死
  URL + 静态白名单 + CI 门禁兜底，真实 SSRF 面为零）。**全量运行时强制留作
  后续小工程**（owner 拍板）。
- 修了 5 条建议：泄漏过滤密钥值清单缺口、OBSERVABILITY §6 自相矛盾、白名单
  测试补 5 域名、删 `discord_guild_id` 死配置、Reddit OAuth 异常不塞上游原文。
- 1 条不修（`_score` 复制四份）：值一致、各有测试钉住，非阻断。

全量套件还抓出 3 个真回归并修：registry 计数 10→14、前端 sourceZh 补 4 源、
工具链 parity 改为只守 backend（根 [tool.mypy] 已删）。

**PR #29 已开**（base master ← feat/security-and-observability），CI 5 个
required context 待走完。

---

## 六、下一步 & 遗留

1. 盯 PR #29 的 CI（Coverage Gate / Type Check mypy / Frontend Lint & Build /
   Lint & Format Check / Full Backend Test Suite），全绿后合并。
2. 等 owner 提供 Discord/Reddit Key 后填 `.env`（`DISCORD_BOT_TOKEN`+
   `DISCORD_CHANNEL_ID`、`REDDIT_CLIENT_ID`+`REDDIT_CLIENT_SECRET`+
   `REDDIT_USERNAME`），代码零改动即启用这两个源。
3. （可选后续）把 14 个采集器也接上运行时 `assert_url_allowed`，把「诚实口径」
   升级成「全量强制」——评审 Blocker 的另一半，owner 已选先交付。
4. （可选后续）`_score()` 复制四份抽成公共函数（评审 Suggestion 5，非阻断）。
