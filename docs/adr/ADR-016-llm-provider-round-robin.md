# ADR-016: 多接口多模型自动轮询（编号配置迁移 + 组合级 round-robin）

- **Status**: Accepted
- **Date**: 2026-09-03
- **Deciders**: 架构 / 运维（owner 提出「把 api 接口改为多接口多模型自动轮询」）
- **技术栈**：Python / httpx / pydantic-settings
- **影响面**：LLM 配置解析、调用调度、成本分布、出站域名白名单、密钥脱敏、状态接口

---

## 背景

仓库**已经**支持多接口多模型，但实现的是**固定顺序故障转移**，不是轮询。
实测 `backend/app/llm/client.py::llm_chat` 每次调用都从组合列表第一项开始：

```
provider-1 + model-1 → provider-1 + model-2 → provider-2 + model-1 → ...
```

成功后不记录位置，**下一次调用仍从 provider-1 + model-1 开始**。后果：

| 现象 | 后果 |
| --- | --- |
| 第一个接口永远承担全部流量 | 其余接口只在第一个挂掉时才被使用，等于冷备而非负载分担 |
| 免费额度型接口（OpenRouter free / Groq）单点耗尽 | 配了 6 个接口却只有第 1 个被限流，看起来像「多接口没用」 |
| 第一个接口质量退化时无法自然分散 | 只有硬失败才切换，慢响应/降智不触发切换 |

配置格式也与 owner 的实际使用习惯不一致。当前真相源读的是：

```
LLM_BASEURL_N / LLM_API_KEY_N / LLM_MODELS_N_M
```

owner 手里的模板是 OpenAI-compatible 生态的通用写法：

```
OPENAI_BASE_URL_N / OPENAI_API_KEY_N / OPENAI_MODEL_N_M
```

照后者填，**一个接口都不会注册**，且不会有任何报错 —— 与 §9.4 记录的
`LLM_API_KEYS` / `LLM_BASE_URLS` 是同一类失效：能填、无人读、静默。

### 如果不决策

继续用固定顺序 failover + 旧变量名，会同时留下两个坑：接口配了不生效（命名不匹配），
以及接口生效了也不分担（无轮询）。两者都不报错。

---

## 决策

### 1. 新增 `OPENAI_*` 编号格式，并置于最高优先级

解析优先级（**从上往下，命中即停，不合并**）：

| 优先级 | 格式 | 说明 |
| --- | --- | --- |
| 1 | `OPENAI_BASE_URL_N` / `OPENAI_API_KEY_N` / `OPENAI_MODEL_N_M` | 新标准格式 |
| 2 | `LLM_BASEURL_N` / `LLM_API_KEY_N` / `LLM_MODELS_N_M` | 旧编号格式，保留一个弃用窗口 |
| 3 | `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL` | 单接口回退 |

**不做两档合并**。若新旧同时存在，取新格式并打一条不含密钥的 WARNING
（`llm.legacy_numbered_config_ignored`）。合并的语义无法向运维解释：
「6 个新接口 + 2 个旧接口 = 8 个接口，轮询顺序是什么」没有正确答案，
而**一个说不清顺序的调度器等于不可复现的成本分布**。

编号扫描范围放宽到 **1–10 个接口 × 每接口 1–10 个模型**（旧实现是 5×5，
owner 手上已有 6 个接口 —— 第 6 个会被静默丢掉）。允许编号有空洞
（配了 1、3、5 不影响 3 与 5 被读到）。

### 2. 「配置了」必须等于「可调用」

定义**有效 provider**：

```
非空 base_url（必须 http:// 或 https:// 开头）
+ 非空 api_key
+ 至少一个非空 model
```

三者缺任一 → 跳过该接口 + WARNING（`llm.provider_config_incomplete`，
字段只有 `index` / `missing`，**不含 key 值**）。

这条不是洁癖。owner 提供的模板里实际出现过：

```
OPENAI_BASE_URL_2=OPENAI_MODEL_2_1=agnes-2.5-flash
```

两行粘成一行。旧实现会把 `OPENAI_MODEL_2_1=agnes-2.5-flash` 整个当成
base_url 注册进去，然后在**第一次真实调用**时才失败 —— 而且失败信息是
「连接错误」，指向网络而不是指向配置。要求 `http(s)://` 前缀能在启动侧就抓住它。

`is_llm_enabled` 同步改为「Feature Flag 开 **且** 至少有一个有效 provider」。
旧实现只查「某个编号 KEY 是否非空」，于是「配了 key 但没配模型」会得到
`enabled=true` + 零个候选组合 —— 状态接口说启用了，实际每次调用都走规则引擎。

### 3. 调度改为 `(provider, model)` 组合级 round-robin

组合列表构造不变（provider 序 × 该 provider 自己的模型序），
**改变的是每次调用的起始位置**：

```
请求 1 → provider-1 / model-1
请求 2 → provider-1 / model-2
请求 3 → provider-2 / model-1
...
请求 N → 回到 provider-1 / model-1
```

实现：模块级单调计数器 + `asyncio.Lock`，在调用**开始时**原子取值并自增，
起始位置 = `counter % len(combinations)`，遍历顺序是从该位置开始的**旋转序列**
（保证仍会试完全部组合，只是顺序轮换）。

**指针在调用开始时推进，与成功/失败无关。** 若只在成功后推进，一个持续
失败的组合会被每次调用都当成起点重试一遍 —— 那是把轮询退化回固定顺序，
且额外付出全部失败组合的超时。

### 4. failover 语义完全保留

轮询只决定**从哪开始**，不改变**遇到失败怎么走**：

| 错误类型 | 行为 |
| --- | --- |
| timeout / connection / 5xx / 429 | 跳过该 provider 的剩余模型，切下一个 provider |
| 400 / 404 / 422 / model not found | 只跳过当前模型，同 provider 下一个模型继续 |
| 预算拒绝 | 立即返回，**一个字节都不发**，不尝试任何组合 |
| 账本不可用 | fail-closed，同上 |
| 输出泄漏检测命中 | 立即返回，不重试其它组合（内容问题，换接口大概率同样内容） |
| 全部组合失败 | 返回 `text=None`，调用方降级规则引擎（ADR-001） |

### 5. 预算仍是全局单账本，不按接口拆分

`LLM_DAILY_BUDGET_USD` 与 `llm_spend_daily` 表保持全局维度。轮询不会绕过
调用前的预算闸门。

**刻意不做 per-provider 预算**：钱是一笔，拆成 6 份配额只会制造
「总预算没超但某接口先被拦」这类既难解释又难运维的状态。
未知模型（owner 配的 `minimax/minimax-m3:free`、`claude-opus-5` 等大多不在
`pricing.py` 表内）仍按 `LLM_FALLBACK_PRICE_PER_1M_USD` 保守估算 ——
**免费接口也必须计入估算**，否则「换个价格表外的模型名」就等于关掉预算。

### 6. 轮询公平性的边界，写进文档而不是假装没有

- **进程内轮询**。每个 uvicorn worker 各持一个计数器。
- 多 worker / 多实例下**不保证全局严格均衡**，只保证每个进程内均衡。
- 进程重启后从首个组合重新开始。
- 这些**只影响流量分布，不影响 failover 正确性与预算正确性**。

需要跨节点严格轮询时才引入 Redis / DB 原子计数器 —— 那意味着「选一个模型」
要先做一次网络往返，为均衡付出可用性代价，当前规模不值得。

---

## 理由

| 备选 | 否决理由 |
| --- | --- |
| 保持固定顺序，只改变量名 | 解决不了「配了 6 个接口只有第 1 个在用」，而这正是 owner 的原始诉求 |
| 随机选起点 | 分布只在大量调用后才均匀；日调用量只有几十次时会出现明显偏斜，且**不可复现** —— 排查「为什么这次用了 model-X」时无从追溯 |
| 按接口轮询（provider 级），provider 内固定首模型 | 每个 provider 的第 2、3 个模型永远不被使用。owner 每个接口配了 2–3 个模型，那些配置会成为死配置 |
| 按延迟/成功率加权选择 | 需要滑动窗口统计与冷启动策略，且引入「越健康越被用 → 越被用越容易限流」的正反馈。加权是轮询之上的优化，不该在同一步做 |
| 跨进程共享计数器（Redis） | 为流量均衡引入一个新的可用性依赖；Redis 挂了 LLM 就不可用，而 LLM 本身是可选增强层 |
| 新旧变量合并成一个大列表 | 顺序无法向运维解释；且「旧配置忘删」会静默变成额外的付费接口 |
| **组合级确定性轮询（本决策）** | 每个配置组合都会被用到；顺序可复现可解释；无外部依赖；failover 与预算语义零改动 |

---

## 后果

### 正面
- 6 个接口 × 2–3 个模型的配置**全部进入轮换**，免费额度被分摊而不是单点耗尽
- 单接口质量退化时影响面被摊薄到 `1/组合数`
- 配置格式与 OpenAI-compatible 生态通用写法对齐，照模板填即生效
- 半配置（缺 key / 缺模型 / base_url 粘连）在解析侧就报 WARNING，不再等到首次调用

### 负面 / 限制
- **同一 prompt 在不同请求上可能由不同模型回答**，输出风格与质量会有波动。
  对本系统可接受：LLM 是增强层，`prompt_version` 与 `model_used` 都已落日志，
  可回溯是哪一个模型产出了某条结论。若某个模型质量不达标，处置是从配置里
  摘掉它，而不是回退到固定顺序
- 成本估算的方差变大：不同模型单价不同，日花费不再近似线性。预算仍是硬上限，
  但「今天大概花多少」更难预测
- 多 worker 下分布不严格均衡（见决策 §6）
- 旧 `LLM_*_N` 进入弃用窗口，最终移除需要另一个 PR + 文档同步

### 需配套的工作
- [x] `backend/app/config.py`：新格式优先解析 + 有效性校验 + `is_llm_enabled` 收紧
- [x] `backend/app/llm/client.py`：轮询指针 + 旋转组合序 + 并发锁
- [x] `backend/app/routers/v1/llm.py`：状态接口暴露 `selection_strategy` /
      `failover_strategy` / `candidate_count` / `config_source`
- [x] `backend/tests/test_llm_failover.py`：迁移优先级、有效性、轮询推进、
      一轮回到首项、并发安全、provider 级跳过
- [x] `.env.example`：新格式占位符（**空值**，不写任何真实密钥）
- [x] `docs/OPERATIONS.md §9.5`：配置格式、迁移优先级、轮询与公平性边界
- [x] `docs/API_SPEC.md §33a`：状态接口新字段
- [x] `docs/GO_LIVE_CHECKLIST.md §10`：多接口上线核对项
- [x] `docs/adr/README.md`：ADR-016 索引

---

## 关联

- ADR-001（LLM 默认关闭）：轮询不改变「默认关、失败回退规则引擎」，
  只改变启用后的候选选择顺序
- ADR-012（LLM 分级使用）：`LLM_DISCOVERY_SCORE_THRESHOLD` 仍在轮询之前生效，
  轮询不增加被调用的项目数量
- `docs/OPERATIONS.md §9.4`：`.env.example` 门禁；本 ADR 新增的编号变量同样
  走 `os.environ` 不经 Settings，模板里必须标 `env-external` 并写清谁读它
