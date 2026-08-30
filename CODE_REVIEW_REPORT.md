# 代码评审报告 — feat/security-and-observability

> 评审者：独立代码评审 agent（全新上下文，仅依据仓库 + git 历史）
> 评审日期：2026-08-30
> 评审范围：分支 `feat/security-and-observability` 相对 `master` 的全部提交
> （真实清单见下，共 11 个提交，含一个收尾 docs 提交）

---

## 1. 结论

**有条件通过**。

一句话理由：四个采集器、可观测性指标、LLM 输出泄漏过滤这几块主体实现扎实、门控正确、都有测试钉住，但"域名白名单"这道安全锁没有真正盖住采集器这条最主要的对外出口，文档却把它写成了"已实现 fail-closed"——交付前需要把"文档说的"和"代码做的"对齐（补上校验，或把文档改回诚实态）。

---

## 2. 评审范围

- **日期**：2026-08-30
- **分支**：`feat/security-and-observability`（相对 `master`）
- **提交区间**（按 `git log master..feat/security-and-observability`，实际 11 个）：
  1. `62b8f06` docs: 收尾三连之 CHANGELOG + 当日 session memory
  2. `0d30ec6` feat: 落地档4-1 四个 P2 内容源采集器（Discord/Reddit/Medium/Mirror）
  3. `a6745c0` test: 钉住权重校准门槛常量 200/30
  4. `73ba0f9` feat: 业务面板三信号指标
  5. `0e25c3a` feat: 入站 HTTP 请求耗时 histogram
  6. `96f1d59` feat: 数据质量指标（完整性/新鲜度）Prometheus gauge
  7. `47fd24c` feat: Agent 粒度指标
  8. `4a2e2cd` chore: 删除 pre-commit mypy hook + 根死配置
  9. `9933f83` feat: 出站 HTTP 域名白名单 + 工具白名单"刻意不实现"澄清
  10. `56d5c1a` feat: LLM 输出泄漏过滤

  （注：任务简报里列的 9 个提交与仓库实际吻合，只是少了最顶上的收尾 docs 提交
  `62b8f06`，不影响评审结论。）

- **评审者身份**：独立代码评审 agent，看不到主会话上下文，只凭仓库代码、git 历史、
  规约文档（AGENTS.md / CLAUDE.md / CONVENTIONS.md / docs/）做判断。

---

## 3. 阻断问题 blocker（必须修才能交付）

### Blocker 1：「域名白名单」没有真正盖住采集器，但安全文档宣称已 fail-closed

**改了什么：**
新增 `backend/app/utils/domain_allowlist.py`，宣称是"集中的出站域名白名单，
消费方在发出请求前调 `assert_url_allowed()`，表外域名 fail-closed 拒绝"。
它被接进了**两处出口**：
- `utils/fetcher.py::fetch()`（通用 fetcher）
- `llm/client.py::_try_single()`（LLM 客户端）

但**没有任何采集器走这道校验**。四个新采集器（`discord.py` / `medium.py` /
`mirror.py` / `reddit.py`）以及全部旧采集器，全部是直接
`httpx.AsyncClient(...)` 发请求，从来没有调用 `assert_url_allowed()`。
也就是说，真正天天在往外部 API 发请求的代码路径，反而没有经过这把锁。

**风险是什么：**
- 给所有读者（尤其不看代码的 owner）造成一种"对外网络已经被锁死"的虚假安全感。
  `SECURITY.md §10.2` 写“✅ 2026-08-29 起这张表成了运行时约束”、
  `§10.3` 网络级一行写“✅ 已实现（出站前校验，表外抛 DomainNotAllowedError）”。
  这句话只在 2 条路径上为真，在主采集路径上为假。
- 就当前而言，**真实的可被远程利用的 SSRF 风险其实很低**：采集器的目标 URL 全是
  写死的常量（`DISCORD_API_BASE`、`OAUTH_ENDPOINT`、`ARWEAVE_GRAPHQL_URL` 等），
  没有一处 URL 来自用户输入，所以攻击者改不了目标地址。当前真正拦住的只是
  "开发者未来改一行 URL 打错域名"这一层。
- 但"统一出口"并不存在。将来任何一个采集器的 URL 变成可配置（比如把
  `medium_tags` 里的 tag 做成可注入、或新增一个源读外部配置的 base_url），
  就会**静默绕过**这道所有人以为存在的锁——而且没有任何日志或报错提醒。

**建议怎么改（二选一，目标都是"文档说的 = 代码做的"）：**
1. （更彻底的修法）把校验补到采集器这一层：抽一个很小的统一出站 helper
   （比如给每个 collector 加一个 `_request()`、或在 `DataCollector` 基类加一个
   发请求前先 `assert_url_allowed(url)` 的封装），让所有采集器也必经白名单。
   因为采集器域名全部是已知常量，接入成本低、改动面小。
2. （更诚实的修法）如果暂时不想改采集器代码，就把 `SECURITY.md §10.3` 网络级那行
   从 "✅ 已实现" 改回 "⚠️ 部分实现：仅 fetcher / LLM 两条路径强制，各采集器靠
   写死 URL + 测试约束，不在运行时强制"。同时把 `domain_allowlist.py` 顶部那段
   "集中的出口"的描述也改成不夸大。

> 补充说明：`SECURITY.md §10.2` 里那句"采集器各自的 `_http_client()` 仍是独立连接"
> 本身也不准确——仓库里只有 `twitter.py` 有 `_http_client()`，其余采集器连这个
> helper 都没有。这进一步说明文档描述和实际代码早就脱节了。

---

## 4. 建议 suggestion（不阻断，但值得改）

### Suggestion 1：泄漏过滤 / 日志脱敏的"已知密钥值"清单有漏洞

**问题：**
`redact.py::_SECRET_ATTRS` 用来收集"已知密钥的真实值"，但里面有一个**幽灵条目**
`"llm_api_keys"`——`settings` 上根本没有这个属性（LLM 的编号 Key `LLM_API_KEY_1..5`
是在 `config.py` 的 `llm_providers` 属性里用 `os.environ.get` 现读的，不是一个字段），
所以它永远取到 None。同时本批新增的两个真密钥 **`discord_bot_token`、
`reddit_client_secret`**（以及更早的 `twitter_api_secret`）也没进这个清单。

**后果：**
这些密钥的"真实值"一旦流入日志或 LLM 输出，靠"值匹配"的脱敏 / 泄漏检测**抓不到**，
只能靠两件事兜底：① 字段名规则（只有字段名长得像 `token`/`secret` 才被替换）；
② 通用 pattern（只认 `sk-`、`ghp_`、`AKIA`、JWT、`Bearer` 这几种形状）。
一个自定义大模型代理的 Key（不是 `sk-` 开头）就会两头都漏。

**建议：**
把 `settings.llm_providers` 里每个 `api_key`、以及 `discord_bot_token`、
`reddit_client_secret`、`twitter_api_secret` 都并入 secret 集合，同时删掉幽灵
`llm_api_keys` 条目。配套补一条测试：构造"自定义 LLM Key 出现在文本里"应当被
`detect_secret_leak` / `redact` 命中。

### Suggestion 2：OBSERVABILITY.md §6 还留着一句与 §3.2 自相矛盾的旧话

**问题：**
`OBSERVABILITY.md §3.2` 新增了"业务面板三指标已实现"，但 §6 末尾仍然写着
"**没有业务面板。**……依赖的三个指标都不存在（见 §3.3），面板本身也不存在。"
其中"三个指标都不存在"已经和 §3.2 打架了。parity 测试只核对"指标名"，不核对
这段陈述，所以 CI 不会红，这句话会在文档里一直错下去。

**建议：**
把 §6 那句改成只陈述事实——"业务面板的 Grafana 看板 JSON 目前还没有；但三个
底层指标（评分/热度/反馈）已于 2026-08-29 实现于 §3.2"。

### Suggestion 3：白名单测试漏了本批 5 个新域名

`test_domain_allowlist.py::test_collector_domains_present` 只断言了 9 个旧域名
（defillama/github/coingecko/.../galxe），**没有**断言本批加入 `_KNOWN_DOMAINS` 的
`discord.com`、`www.reddit.com`、`oauth.reddit.com`、`medium.com`、`arweave.net`
五个域名确实在清单里（它们实际在，只是没被测试钉住）。将来有人误删其中一个，测试
不会报。建议把这 5 个也加进同一断言。

### Suggestion 4：两个小脏点——`discord_guild_id` 死配置 + Reddit 把上游响应体塞进异常

- `config.py` 里声明了 `discord_guild_id`，`.env.example` 也有，但整个仓库**没有任何
  代码读它**（`discord.py` 只用到 bot_token + channel_id）。属于"能填但填了不生效"
  的配置，与仓库自己反复反对的假配置是同一类，建议删掉或真正用起来。
- `reddit.py::_fetch_access_token` 在拿不到 access_token 时
  `raise ValueError(f"Reddit OAuth 无 access_token：{data}")`，把整个 OAuth 响应体
  拼进异常信息，随后又被 `collect()` 写进 `error_message`、`health_check` 直接返回。
  虽然 Reddit 的 OAuth 响应里不含 secret，但"把上游原文塞进日志/接口"是坏习惯，
  建议只取 `data.get("error")` 之类的错误码。

### Suggestion 5：四个采集器的评分函数整段复制了四份

`_score()` + `MAX_DISCOVERY_SCORE = 0.28` + `type_map` 在 discord/medium/mirror/reddit
四个文件里一模一样地复制了四份。现在值都一致（我已核对：funding 0.13 → 上限正好
0.28，恒 < 0.3），但将来要调评分口径，很容易漏改其中一个导致四源口径漂移。建议把这
段提进 `content_signals.py` 共用一个 `score_by_signal()`。

### Suggestion 6（工程整洁结论，非问题，记一笔）：「删 mypy hook + 根死配置」是干净的

任务简报里写"pre-commit mypy hook 改成 pass_filenames:false + 指向 backend 配置"，
**实际做的是直接把 pre-commit 的 mypy hook 整段删了**（不是改，是删）。评审确认这
次是干净的：
- CI 仍用 `mypy app --config-file pyproject.toml`（strict=true）把关类型检查，所以
  类型纪律没有消失，只是从"提交前"挪到了"CI"。
- 根 `pyproject.toml` 删掉的 `[tool.mypy]` / `[tool.pytest.ini_options]` /
  `[tool.coverage]` 确实是死配置（权威在 `backend/pyproject.toml`）。
- 我核实过：仓库里没有任何自定义 pytest marker（只有 `asyncio`/`parametrize`/
  `skipif` 这些内置的），所以删掉根配置里的 `markers` 清单、`backend` 那侧又开着
  `--strict-markers`，**不会**报"unknown marker"。

唯一代价：开发者本地提交前不再跑类型检查，类型错误要等 CI 才暴露。属于可接受，
不算问题。

---

## 5. 测试与验证评估

**改动有没有对应测试：**
- 每个新采集器都有 respx（mock 网络）测试，且覆盖了主要分支：
  `test_discord / test_medium / test_mirror / test_reddit` 都测了「开关/Key 门控、
  正常命中信号、空结果→partial、HTTP 错误→error」；Mirror 额外测了 GraphQL error，
  Reddit 额外测了 OAuth 401。**不是只有 happy path**，这是本次做得好的地方。
- 白名单：`test_domain_allowlist.py` 测了 fail-closed（表外域名、非 http、空串都拒）、
  LLM provider 域名动态放行、`fetch()` 入口拒绝表外域名。
- 泄漏过滤：`test_llm_failover.py` 的 `TestDetectSecretLeak` / `TestSecretLeakDiscard`
  测了已知密钥值 + 各通用 pattern 命中丢弃、干净输出不误报、丢弃不重试下一个组合。
- 指标：`test_metrics.py`（api）用 `metric_sample_value` / `_histogram_sum` **真读
  Prometheus 样本值**，钉住了 agent/业务面板/HTTP 耗时这些指标确实递增或 observe，
  而不是只查"注册表里有没有这个名字"。这一点尤其难得（避免了"只注册不调用"的幽灵指标）。
- 校准门槛：`test_calibration.py::test_gate_constants_not_lowered` 钉住 200/30 常量。

**文档/门禁 parity（否则 CI 会红）：**
- 四个新源都登记进了 `DATA_SOURCE_STRATEGY.md`（§2 状态表、§3 采集器落点表、§5.4
  分数上限、§8.4 限流 0.5rps/burst2、cron 表）、`OPERATIONS.md`（门控表 + cron 表 +
  幽灵指标清单）、`SECURITY.md`（域名白名单表 + ghost 符号清单）。
- 限流数值与代码一致：`rate_limiter.py::DEFAULTS` 里 discord/reddit/medium/mirror 都是
  `0.5 req/s, burst 2, 无日限额`，与 DATA_SOURCE_STRATEGY §8.4 逐字对得上。
- `is_enabled()` 门控正确：medium/mirror 无 Key 默认开（`MEDIUM_ENABLED=true` /
  `MIRROR_ENABLED=true`），discord 需 `enabled+bot_token+channel_id`、reddit 需
  `enabled+client_id+secret+username`，默认都关。
- `discovery_score` 上限 0.28 恒 < 0.3：四个源的 `_score()` 最高是 funding 分支
  `0.15+0.13=0.28`，且被 `min(MAX_DISCOVERY_SCORE=0.28, ...)` 夹住，永不越过分析阈值
  `DISCOVERY_SCORE_ANALYSIS_THRESHOLD=0.3`。这个设计意图成立，测试也断言了 `< 0.3`。
- secrets 边界：四个采集器的 `raw_data` 都不含 token/密钥；Discord token、Reddit
  client_secret 都只放进 HTTP header，不落日志、不进 raw_data。符合 AGENTS.md /
  SECURITY.md 的要求。
- Discord 只读单个配置频道（有合规注释 + 只读 `channels/{channel_id}/messages`）；
  Reddit 用 OAuth 关键词搜索（3 个词 × 25 条，每小时间隔），不是全站枚举，ToS 层面
  没有明显越界。

**我没亲跑、但主 agent 声称会过的检查，值得警惕的点：**
- 本评审是纯静态审查，**没有实际执行 pytest / mypy / pre-commit**，上述"测试覆盖"
  是基于代码与测试文件的静态判断，不是运行结果。
- 即便 CI 全绿，下面这几处也**不会变红**、需要人工改：① `SECURITY.md` 宣称的
  fail-closed 白名单实际没盖住采集器（Blocker 1）；② OBSERVABILITY §6 那句自相矛盾
  的"三个指标不存在"（Suggestion 2）；③ 白名单测试未覆盖本批 5 个新域名
  （Suggestion 3）；④ 泄漏过滤的秘密值清单缺口（Suggestion 1，能用测试钉，但目前
  没测）。

---

## 附：评审核对清单（供 owner 快速看结论）

| 评审重点 | 结论 |
|---|---|
| 域名白名单是否 fail-closed、是否覆盖所有出口 | ⚠️ 只覆盖 fetcher + LLM，**采集器全部绕过**（Blocker 1） |
| LLM 泄漏过滤是否覆盖所有输出路径、打码是否漏 | ✅ 覆盖两个 LLM 调用点（base + ai_brief），但"已知密钥值"清单有缺口（Suggestion 1） |
| 工具白名单校验是否在执行前发生 | ✅ 刻意不实现，理由成立（Agent 无工具调用点），文档已澄清 |
| pre-commit mypy 删除 + 根死配置清理 | ✅ 干净，无漏配、无自定义 marker 受牵连 |
| 指标命名 / 标签基数 / record_* 是否真被调用 | ✅ 命名合规，词表闭合，埋点都在真实路径（orchestrator_simple 是实际分析路径） |
| 四采集器 discovery_score / is_enabled / 限流 / secrets / ToS / 异常处理 | ✅ 全部正确，0.28<0.3、门控对、限流对表、不落密钥、异常转 error 态 |
| 测试覆盖与文档/门禁 parity | ✅ 主体覆盖良好；4 个新源全部登记；三处"测试测不到"的边角见上 |

---

## 6. 处理记录（2026-08-30，主 agent 响应）

| 项 | 处理 |
|---|---|
| Blocker 1 域名白名单覆盖不全 | ✅ **已修**（owner 决策「诚实口径」）：SECURITY §10.2/§10.3 与 `domain_allowlist.py` docstring 改为如实描述「运行时强制只 cover fetcher + LLM 两条路径；采集器靠写死 URL + 静态白名单 + CI 门禁兜底」，删掉「统一出口」「采集器各自 _http_client()」等不准确措辞 |
| Suggestion 1 密钥值清单缺口 | ✅ **已修**：`redact.py` 删除幽灵 `llm_api_keys`，补 `discord_bot_token`/`reddit_client_secret`/`twitter_api_secret` + `llm_providers` 各 api_key；新增测试钉住 |
| Suggestion 2 OBSERVABILITY §6 自相矛盾 | ✅ **已修**：改为「指标已实现，缺的是看板 JSON」 |
| Suggestion 3 白名单测试漏 5 域名 | ✅ **已修**：`test_collector_domains_present` 补 5 个新域名 |
| Suggestion 4 死配置 + 异常塞上游原文 | ✅ **已修**：删 `discord_guild_id`（config + .env.example）；Reddit OAuth 异常只留 error 码 |
| Suggestion 5 `_score` 复制四份 | ⏸️ **不修（非阻断）**：四份值一致、各有测试钉住；将来改评分口径再抽公共函数，现在抽反而让四个源更耦合 |
| Suggestion 6 删 mypy hook 已干净 | ✅ 确认，无动作 |

**全量测试**：修复后 `mypy` 0 错误、`ruff` 全绿；评审针对的测试集 221 passed，全量后端套件复跑见 session memory。