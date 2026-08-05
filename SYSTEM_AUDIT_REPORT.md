# 系统审查报告：采集链路、流水线、安全与前端

> 生成日期：2026-07-26 · 承接 ADR-014 之后的第二轮工作
> 覆盖范围：9 个采集器、调度与流水线、v1 API、Next.js 前端、`docs/SECURITY.md` 逐条对照
> 验证：后端 **1908 项测试通过**，`ruff` 干净，前端无新增类型错误

---

## 一、最重要的一条：不要重算存量库，要先回填

上一份报告（`ENGINE_DUAL_RUN_REPORT.md`）用合成语料估算重算影响。这次拿到了真实库
（702 个项目 / 1040 条原始记录），结论**与那份估算相反**。

用 `/rescore` 的真实链路把 702 个项目重算一遍：

| | FARM | WATCH | IGNORE |
| --- | ---: | ---: | ---: |
| 库里现存（历史遗留） | 20 | 388 | 294 |
| 旧代码重算 · 未回填 | **0** | 126 | 576 |
| 旧代码重算 · 已回填 | 108 | 512 | 82 |
| 新代码重算 · 已回填 | 82 | 446 | 174 |

第二行是关键：**用完全未改动的旧代码重算，FARM 就已经归零**，42% 的项目换标签，
分数均值掉 4.30（最差 −34）。这不是评分口径变化，是重算链路在做**有损重建**。

原因：`projects.meta.signals` 是重算时唯一的信号来源（`_row_to_raw_project` 只读这一处），
而这 702 行的 `meta` 全部为 NULL——它们早于该机制落地。重算会重建出一个只剩
id/name/url/sector/stage 的空壳项目，7 项可验证信号里 6 项归零，confidence 全线跌破 0.5，
低置信降档规则于是在**每一个**项目上触发。

好在原始数据还在：`raw_projects`（1040 条完整载荷）与 `project_signals`（2280 条结构化信号）
都完好。`backend/scripts/backfill_meta_signals.py` 据此重建 `meta.signals`：

```bash
python scripts/backfill_meta_signals.py --db data/airdrop.db --dry-run   # 先看影响面
python scripts/backfill_meta_signals.py --db data/airdrop.db --apply     # 自动先备份
```

实测 602/702 行可回填，100 行找不到原始记录（来源为 seed/api/import，本就没有采集记录）。
回填后重算恢复正常，且那 100 个无证据项目的 confidence 仍 < 0.5——低置信降档规则精确地
只对**真的没有证据**的项目生效，而不是对全库生效。这正是它该有的样子。

**正确顺序：回填 → 重算。** 不要跳过第一步。

### 引擎改动本身的净影响

在两侧都已回填的前提下单独看引擎改动：分数变化区间 −10..+2，均值 −2.86，
19.9% 的项目跨标签（92 WATCH→IGNORE、37 FARM→WATCH、11 WATCH→FARM）。

方向是**更保守**，原因正当：修正后，已经发币的协议（AAVE、UNI、BNB 这类）不再被判为
"未发币"，`airdrop_signal` 从 85–100 回落到真实档位。本系统是空投猎手，
已发币的成熟协议本就不该按空投候选打分。

---

## 二、采集链路整体是断的

真实库的信号命中率解释了为什么全库分数拍平——7 项可验证信号里 **6 项命中率为 0%**：

| 检查项 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 有官网 url | 88.9% | 100.0% |
| 有社媒 | 0.0% | 99.2% |
| 有合约 / TVL / 测试网 | 0.0% | 100.0% |
| 有 github 仓库 | 0.0% | 13.3% |
| 有文档 / 白皮书 | 0.0% | 0.6% |
| 有任务入口 / 积分 / 显式空投 | 0.0% | 0.2% |
| 多源（≥2） | 0.0% | 见下 |

根因逐条：

**DefiLlama 没有复制 `description`。** 而 `_infer_airdrop_flags` 的全部文本判断都靠它，
没有它文本 blob 基本只剩一个 slug，`has_docs` / `has_roadmap` / `explicit_airdrop_mention`
在整个语料上恒为 False。同时 `tvl` 没有映射成 `tvl_usd`（RawProject 实际读取的字段名），
`twitter`/`github` 字段存在却没有转成 `has_twitter`/`has_github`。

**跨源合并在生产中一次都没发生过。** galxe/layer3 把 sector 写死成 `Quest`，etherscan 写死
`On-chain`，twitter 写死 `Unknown`，coingecko 写死 `DeFi`。dedup_key 是 `name::sector`，
写死的赛道让这些源的记录与 defillama 的 `name::Lending` **永不相撞**。真实库 702 个项目里
`source_count >= 2` 的比例正是 0.0%。修复：这些源不再臆造赛道（留空），并在合并前把
"赛道未知"的分组并入同名且赛道已知的分组——只在唯一匹配时归并，同名落在多个赛道时保持原样。

**三个信号补充源永远进不了合并。** coingecko 的 discovery_score 硬编码 0.1，etherscan 与
cryptorank 上限 0.28，全部低于分析阈值 0.3，于是 `get_unprocessed_raw_projects` 从不返回它们。
但 `discovery_score` 衡量的是"作为独立发现有多值得跟进"——一条低分记录自己不足以立项，
只要同一 dedup_key 已经有记录过线，它就是这个项目的佐证。修复后佐证记录会被一并载入，
且不占用 `limit` 名额（`limit` 现在约束的是项目数而非原始行数）。

**Twitter 采集器贡献恒为零。** 推文正文存在 `raw_data["text"]`，而解析器的取值列表里没有这个键。
两个 twitter 源（KOL + 关键词）此前等于白跑。

**DefiLlama 的阶段与代币推断在规模上是错的。** `_infer_stage` 把 TVL 在 $10M–$100M 之间的
一律判成 "testnet"，真实库 31.8% 的项目因此被误标为测试网——纯粹是金额分档造成的假象。
`_is_unlisted` 只看 `gecko_id`，而真实库 1040 条里 gecko_id 有值的是 **0 条**，于是整个语料
被判成"未发币"，`airdrop_signal` 直接顶到 85–100。

> 这一条我改错过一次，值得记下来：第一版改成 `if symbol: return False`，
> 但 DefiLlama 用字符串 `"-"` 表示"该协议无代币"，真实库里 658/1040 条正是这个值。
> 而 `_is_unlisted` 同时是 `_filter_candidates` 的硬过滤条件，于是采集量从 934 条塌到 **2 条**。
> 是对抗式复核跑真实数据时抓出来的。最终版按"真实 ticker > gecko_id"判断，并把 `"-"`
> 等哨兵值排除在 ticker 之外。

**GitHub 赛道推断把大半仓库判成 AI 赛道。** `"ai" in desc_lower` 会命中 `blockchain`、
`chain`、`mainnet`、`available`——`"Cross-chain bridge SDK"`、`"A blockchain indexer"` 全被判成 AI。
sector 是 dedup_key 的一半，判错既错分类又阻断合并。已改为整词匹配。

**GitHub 存的是 `updated_at` 而非 `pushed_at`。** 前者会被 star/watch/改描述顶新，
于是 §5.1b 的 `github_recent_push_days`（±18 分）量到的是元数据变动而不是开发活跃度。

**CoinGecko 拿币种图标当官网。** `url = coin.get("image")`。coingecko 优先级(4)高于 github(5)，
`url` 属于"最高可信已知值"类字段，于是一张 PNG 会直接盖掉真实官网，还让 scorer 的
`bool(p.url)` 证据检查在一个 logo 上判过。

---

## 三、流水线会静默丢数据

**持久化失败被吞掉，`/run` 仍返回成功。** 状态在持久化**之前**就算好了，于是"评分成功但一行
都没写进去"依然返回 `status=completed / error_count=0`；上游 `pipeline_run` 又只看
`state.score` 就把 `raw_projects` 标成已处理。结果：整批数据既没落库、也不再排队重试，
而 DB 与 metrics 里都查不到任何痕迹。

修复三处：状态改到落库之后再定；`save_batch_with_rows` 逐条吞掉的单行异常改由行数差额抬成
错误；出队判据从"内存里评分成功"改为"确实写进了 `projects`"。

**失败的定时运行不留痕迹。** `LogRepository.log_run` 定义了却从无调用方，调度器把异常吞成
一行日志。现在每次运行（成功或崩溃）都落一条持久记录。

**定时任务不按配置的时区跑。** `CronTrigger.from_crontab()` 没传 `timezone`，而 APScheduler
只在**它自己**构造 trigger 时才注入 `scheduler.timezone`——对预先构造好的实例不生效。
`TIMEZONE=Asia/Shanghai` 被静默忽略，10 个采集任务加 1 个分析任务全部按容器时钟触发。

**`misfire_grace_time` 默认 1 秒。** 日更任务只要错过 1 秒就整天不跑，且不告警；而一次分析
运行本身就可能占用数秒（500 条队列实测 2.8 秒），足以自造 misfire。现在设为 1 小时补跑窗口
并配 `coalesce=True`（只补跑一次）。

---

## 四、安全

对照 `docs/SECURITY.md` 逐条核，确认并修复：

**密钥会进 500 响应体。** 5 个端点用 f-string 把异常原文塞进 `detail`。psycopg 的
`OperationalError` 携带完整 DSN（含库密码），httpx 的异常携带完整 URL（含 `?apikey=`）。
实测能从 `POST /api/v1/run` 的 500 响应里读出明文密码。

**§3.3 要求的日志脱敏从未生效。** 全仓库没有任何 `structlog.configure()` 调用，
而代码里约 40 处 `logger.error(..., error=str(e))`、19 处 `exc_info=True`。
现已安装 processor，按字段名脱敏并递归处理嵌套容器。

> 这里也踩了一次：processor 第一版排在 `format_exc_info` **之前**，而 traceback 字符串
> 是在那一步才生成的——等于什么都没脱敏，恰好漏掉最主要的泄漏渠道。已调整顺序并加测试锁定。

**`APP_ENV=Production`（大写 P）绕过全部生产安全校验。** 精确比较 `== "production"`，
而 docker-compose 里 `APP_ENV=${APP_ENV:-production}` 直接取自操作员的 shell。
`PRODUCTION`、`prod`、`"production "` 同样绕过。已归一化。

**生产环境接受 1 个字符的 API_KEY。** §4.2 要求 ≥32 字符，原实现只校验非空。
配合"完全没有限流"，等于可以按线速爆破。

**限流配置项定义了但无人读取。** `RATE_LIMIT_ENABLED` / `_REQUESTS` / `_WINDOW` 三个配置
在代码里没有任何读取方。现已实现按 IP 滑动窗口 + 429/Retry-After，昂贵端点额外限制
（LLM 开启时 `/run` 每小时 1 次，关闭时 10 次——按 §10.4 给出的理由分档，而不是照字面
把手动触发也锁死一小时）。

> 第一版取 `X-Forwarded-For` 首段作为客户端标识。但本仓库的 nginx 用
> `$proxy_add_x_forwarded_for`，它会把客户端**自带的值前置**——攻击者每次换一个伪造值
> 就能无限刷配额，限流的首要目的当场失效。现在默认完全不采信该头，只有显式配置
> `TRUSTED_PROXY_COUNT=N` 时才从右往左数第 N 个值（链上唯一不可伪造的位置）。

**输入无长度上限。** feedback 的 `note` 实测 20MB 直接落库，未鉴权即可重复调用 → 磁盘耗尽。
funding 的 `NaN`/`Infinity` 会先把非法 JSON 写进 `projects.meta`，再以 500 告诉调用方"写失败了"。

**根目录 `nginx.conf` 对所有响应加 `Access-Control-Allow-Origin: *` 并自动放行预检。**
`always` 标志让它连 401 都带上，任何网页都能跨站调用 `POST /api/v1/run`、
`POST /api/v1/import/projects` 并读取响应；它还与后端自己发的同名头重复，浏览器判定为畸形
而整体拒绝——后端精心配置的白名单反而失效。已改为一律交给后端处理。

### 查过并确认没问题的

- **SQL 注入面干净。** 那个 `?` → `%s` 的字符串改写确实可疑，逐个调用点验证下来：
  `_column_exists` / `_add_column_if_not_exists` 的 f-string 全部只接收字面量表名；
  用户提供的值里含 `?` 或 `%s` 不会污染改写后的语句（参数始终独立绑定）；
  `datetime('now', '<literal>')` 的正则捕获组是 `[^']+`，无法闭合引号越狱。
- **`hmac.compare_digest` 用对了**，鉴权无路径穿越/前缀绕过。
- **没有可达的 SSRF。** 每个 `client.get/post` 的目标都来自硬编码常量或 `settings.*_base_url`；
  `defillama`/`github` 从上游 JSON 里读到的 `url` 只做存储不做请求；httpx 默认不跟随重定向。
  `utils/fetcher.fetch()` 是死代码，无调用方。

---

## 五、前端

**"开始采集"按钮点了等于没点。** 后端返回顶层 `is_enabled` + 嵌套 `status.{enabled,…}`，
前端读顶层 `s.enabled` → 恒为 `undefined` → 启用列表恒为空。按钮仍提示"完成 · 采集成功 0"。
同一处错位让 Ops 页每个源都显示"已禁用"、触发按钮全部灰掉。因为响应只做了类型断言、
没有运行时校验，`tsc` 查不出来。

**Insights 页渲染 `热度 NaN`。** 后端发 `avg_heat_score`，前端读 `heat_score`。

**失败的请求被渲染成"空数据成功"。** Ops 页 `.catch(() => ({count:0, items:[]}))` 让接口挂掉时
显示"隔离区为空 · 共 0 条"，与真的没有数据无法区分。Nav 的接口状态指示器把"失败"和
"加载中"渲染成同一句话（"接口检测中…"），故障永远不显形。

**项目详情页的数据竞态。** 三处会触发 `loadProject`（首次加载、重评后、融资保存后），
既无 AbortController 也无代次守卫，慢的旧响应后到会覆盖新响应——重评完成后紧接着的刷新
可能把页面写回重评**之前**的分数。已加代次守卫与取消。

**未修复（如实说明）：** 另有 7 处 fetch 站点存在同类竞态（`InteractionPanel`、
`ParticipationTasks`、`AiBriefPanel`、`OpportunityWorkflowPanel`、`FundingPanel` 等）。
容器内没有 `node_modules`、无法真实构建，全量重构这些组件的风险高于收益，
留待有构建环境时用现成的 `useAsyncData` 钩子统一收口。

---

## 六、验证方式

| 项 | 结果 |
| --- | --- |
| 后端全量测试 | **1908 passed** |
| `ruff check` | 全部通过 |
| 前端类型检查 | 无新增错误（剩余 4 处为 `--noResolve` 造成的假阳，基线同样存在） |
| 真实数据验证 | 用 702 项目 / 1040 原始记录实测信号命中率、采集量、合并行为 |
| 回填脚本 | 在真实库副本上连跑两次，`projects.meta` 的 SHA-256 完全一致（幂等） |
| 对抗式复核 | 两轮独立子代理逐条证伪，共确认 17 处缺陷 |

**本轮改动自身引入了 8 处缺陷，全部由对抗式复核抓出并修复**，其中三处会造成实际损失：
`_is_unlisted` 把采集量从 934 打到 2；限流的 `X-Forwarded-For` 可伪造绕过；
脱敏 processor 排在 traceback 渲染之前等于没脱敏。每一处都补了回归测试。

还有一处是复核预言、随后被我复现的：`_corroborating_rows` 让更多记录落进同一个合并组之后，
`merge_raw_records` 里 naive/aware 时间戳混用的 `TypeError` 从"理论上不可达"变成实际会崩——
而它位于逐行 try 之外，一条记录就能中断整批采集。已修。

---

## 七、建议的执行顺序

1. **先回填**：`python scripts/backfill_meta_signals.py --db data/airdrop.db --dry-run`，
   确认影响面后加 `--apply`（脚本自动备份）。
2. **再重算**：回填后重算才是无损的。仍建议先在副本上跑
   `python scripts/dual_run_compare.py dump-db /tmp/after.json data/airdrop.db` 看迁移矩阵。
3. **然后重采一轮**：采集链路修好后，新一轮采集才能真正拿到文档/仓库/任务入口这些信号，
   并且跨源合并会第一次真实发生。
4. **生产部署前**：设置 ≥32 字符的 `API_KEY`；确认 `APP_ENV` 拼写；若前面有反向代理，
   按层数设置 `TRUSTED_PROXY_COUNT`（否则限流按直连处理）；确认用的是
   `docker/nginx/nginx.conf` 而不是根目录那份。
