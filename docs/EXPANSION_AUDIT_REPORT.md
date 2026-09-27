# Expansion 扩展功能含金量审计（2026-09-23）

> 审计范围：expansion v1~v7 批次的全部 28 个 `backend/app/services/` 扩展服务。
> 评级口径：**A 真实计算**（确定性算法 / 真实 I/O）→ **B 混合**（真实骨架 + 局部占位）→ **C 静态占位**（硬编码数据冒充实时）→ **D 伪检测**（随机/哈希捏造结论）。
> 结论先行：**A 级 5 个、B 级 6 个、C 级 12 个、D 级 5 个**。扩展层约 61% 是「看起来在工作」的静态或伪造数据输出。

---

## 审中发现并已修复的 P1 bug

`gas_alert_engine.evaluate_active_alerts()` 读取 `summary["data"][chain]["gas_gwei"]`，
而 `get_all_chains_gas_summary()` 实际返回 `{"chains": {chain: {"gwei": ...}}}` ——
两条数据形态完全断裂，生产端点 `GET /gas/alerts/active` **永远返回空列表**。
旧测试用 mock 喂了同款错误形态，恰好匹配实现里同样错误的读取路径，把 bug 钉成了「预期行为」。
这与 HANDOFF 中两次记录的「测试通过 ≠ 功能正确」是同一模式。

修复：`app/services/gas_alert_engine.py` 改读真实形态；测试改为钉住真实契约，
并新增一条「默认 summary 直接喂引擎」的集成口径测试。3 passed + ruff clean。

---

## 评级明细

### A 级 — 真实计算，保留（5 个）

| 服务 | 依据 |
|---|---|
| `faucet_registry.py` | 真实 HTTP 探测 + `faucet_claims` 表冷却追踪，CRUD 走 DB |
| `impermanent_loss_sentinel.py` | AMM 恒定乘积 IL 公式、V3 集中流动性放大、HF 与清算价推演，纯确定性数学 |
| `calldata_decoder.py` | 真实 4-byte selector 解码 + 32 字节槽位解参 + MAX_UINT256 无限授权检测；内置 selector 表有限但解码逻辑真实 |
| `airdrop_calendar.py`* | 读取真实 projects 表；但 `CURATED_MILESTONES` 的日期是 `now + N 天` 滚动伪造（见 B/C 备注） |
| `alpha_dossier.py` | 聚合 viability_gate / anti_pua / signal_correlation / participation_tasks 等真实子系统，Markdown 研报基于项目真实数据 |

\* calendar 的聚合逻辑是真实的，但里程碑日期是「今天 + 固定偏移」编造的，倒计时永远「快到了」——降级看是 C 的嫌疑，算 A-。

### B 级 — 混合：真实骨架 + 局部占位（6 个）

| 服务 | 真实部分 | 占位部分 |
|---|---|---|
| `gas_tracker.py` | 真实 RPC `eth_gasPrice` 探测（多节点 fallback + 15s 缓存） | RPC 全挂时回退**写死的**「兜底 gwei」且只标 `is_fallback`；「黄金时段」是写死的经验文本 |
| `bot_notifier.py` | 指令解析真实、从 DB 查真实 FARM 项目、Telegram/Discord 真实发送 | `/help` 文案里「四路 AI Agent」与实际不符；详情链接是写死的假域名 |
| `wallet_activity_diagnostic.py` | 5 维评分与补刀指南是确定性的 | **用户不传参数时用地址 MD5 生成假指纹**冒充链上数据 |
| `onchain_sybil.py` | 拓扑生成器（防关联分层教学）有真实教育价值 | `evaluate_sybil_risk` 只检查地址前缀相似 + 数量，但输出「风险分」显得像真检测 |
| `project_comparison.py` | 对比框架/裁决逻辑真实，读取真实 sub_scores | 缺失维度一律回落到 60~80 的**默认安慰分**，缺数据时对比结论是编的 |
| `security_sentinel.py` | `check_domain_safety` 的 HTTPS/Punycode/TLD 检测真实可用 | `scan_token_approvals` / `scan_dust_poison_tokens` 返回**硬编码样例授权**，与传入地址无关 |

### C 级 — 静态占位：硬编码数据冒充实时（12 个）

| 服务 | 问题 |
|---|---|
| `token_unlock_radar.py` | 8 条解锁记录硬编码，`unlock_date` 用 `now + N 天` **每次重启都滚到未来**，永远「即将解锁」 |
| `sell_off_simulator.py` | 赛道漂移系数（`30d_price_factor` 等）全是拍脑袋常数，包装成「历史规律模型」 |
| `mev_rpc_sentinel.py` | 节点清单是真的公共 RPC，但 `benchmark_rpc_node` 的「延迟探测」返回**写死的 38~82ms**，从未真正发包 |
| `bridge_liquidity_radar.py` | 池子流动性、脱锚汇率全是硬编码快照，`timestamp` 却打实时时间 |
| `bridge_optimizer.py` | 费率/时长硬编码，「跨链报价」纯公式合成，未接任何桥 API |
| `identity_passport_radar.py` | 戳记目录（权重/成本）大致真实，但 `evaluate_wallet_identity` 用**地址字符和取模 3** 决定哪些戳「已激活」——与链上零关系 |
| `points_epoch_estimator.py` | 积分池参数、代币价格全是硬编码假设值，排位/回报推演建立在假数上 |
| `whale_mirror_backtester.py` | 「历史战神基准」是硬编码故事表，钱包对比即查表比对 |
| `airdrop_pnl.py` | 收益账本内置 4 条假历史记录，且**新增记录只 insert 进模块级 list，重启即失** |
| `smart_money_radar.py` | 「Vitalik 向 Farcaster 签名信令」等巨鲸动态是**编造的时间线**，社交增速是写死的数组，却显示「N 小时前」 |
| `team_studio_manager.py` | Alice/Bob/Charlie 三个操作员连同今日完成 tx 数全是编造，内存态 |
| `paymaster_sponsor_radar.py` | 「活跃赞助池余量」是硬编码，「资格模拟」只查地址长度是 42 |

### D 级 — 伪检测：随机/哈希捏造结论，建议下线或重写（5 个）

| 服务 | 危害 |
|---|---|
| `sybil_lineage_graph.py` | **编造资金关联**：用 `md5(addr1_addr2) % 7 == 0` 决定「存在互转」，共同母号/归集地址是 `0xfa1100...funder` 这类**不存在的假地址**。用户会基于虚构的「女巫红线」改变真实资金操作 |
| `gas_alert_engine.py` | 规则 CRUD 本身真实，但评估读的是错误数据形态（已修），且规则只存内存，重启即失 |
| `script_forge.py` | 生成的脚本里塞了**写死的示例合约地址**（`0x7777...`），用户照抄会与任意目标合约交互；模板本身无恶意但「开箱即用」是假的 |
| `playbook_orchestrator.py` | 预置 playbook 里一半合约地址是 `0x7777...`、`0x8888...`、`0x9999...` 的**占位假地址**，生成脚本后照跑会打向无效合约 |
| `playbook_orchestrator.py`（审计后修正） | 实施时曾把 Scroll 的 Ambient CrocSwapDex `0xaaaaAAAACB71...` 误判为占位——经官方部署文档核实（docs.ambient.finance/developers/deployed-contracts），那是真实的 vanity 地址（前 8 位同为 a）。占位判定已改为「全长重复」并豁免 faucet 零地址哨兵，避免误杀真实协议 |
| `faucet_registry.check_faucets_liveness`* | 见 B 级备注——探测逻辑真实，但 `vault_address` 字段从未在注册表里配置过，链上余额分支是死代码 |

\* faucet 主体是 A 级，此条仅指其中一个分支。

---

## 最重要的三个发现

1. **「测试全绿 + 功能全坏」的模式在扩展层系统性复现**。每个扩展服务都配了测试，但测试断言的是「函数返回我喂给它的形状」，不是「数据与现实一致」。这与 HANDOFF 记录的归档子系统 `days or 0` bug、本次的 gas_alert 形态断裂，是同一类病：**门禁验证的是代码自洽，不是事实自洽**。
2. **D 级服务的输出会被当真**。`sybil_lineage_graph` 编造资金红线、`smart_money_radar` 编造 Vitalik 动态、`calendar`/`unlock` 用滚动日期伪造紧迫感——这些不是「暂无数据时的占位」，而是**主动生成假事实**。系统红线「诚实口径」（域名白名单、seed 数据标记）在扩展层完全没有被执行。
3. **UI 广度放大了假数据的杠杆**。前端 50 个组件里大量模态框消费这些 C/D 级端点，用户看到的是漂亮雷达图 + 精确到小数点的数字，无任何「模拟数据」标记（对比：seed 项目在前端有「种子数据」标记）。

---

## 收敛建议（按 ROI 排序）

| 优先级 | 动作 | 对象 |
|---|---|---|
| P0 | 给所有 C/D 级端点响应加 `data_quality: "simulated"` 字段，前端统一渲染「模拟数据」角标（复用 seed 标记模式） | 全部 C/D |
| P0 | 删除或改写编造「事实」的输出：假巨鲸动态、假资金红线、假操作员 | smart_money / sybil_lineage / team_studio |
| P1 | 占位合约地址换成显式空值 + 前端提示「请填入真实合约」，或直接从 playbook/script_forge 移除默认值（已完成：地址必填 + 生成前拦截 + faucet 零地址哨兵豁免 + vanity 地址不误判） | playbook / script_forge |
| P1 | 内存态 CRUD（gas 规则、pnl 账本、team studio）落 SQLite，与 faucet_claims 同模式（已完成：`gas_alert_rules` / `harvest_records` / `team_studio_operators` + `team_studio_tasks` 五张表；默认规则与样例账本仅首次播种，测试以 `:memory:` 连接隔离并新增跨连接持久化钉子） | gas_alert / pnl / team_studio |
| P2 | 「黄金时段」「历史规律」类经验文本改为引用可验证出处或标注「经验法则」 | gas_tracker / sell_off |
| P2 | 接一个真实解锁数据源（如 token unlock 免费 API）替换滚动日期，或砍掉 unlock/calendar 的伪造条目 | unlock_radar / calendar |

**不建议**：继续为 C/D 级服务补测试或加功能——在数据源补齐前（本次搁置的方向），这些服务的正确输出是空 + 标注，而不是更多假数字。

---

## 附：CI 口径差排查与修复（2026-09-23）

排查「干净 HEAD 上本地 mypy 报 66 个错误但 CI 声称全绿」的结论：**CI 自 2026-09-04 起 56 连败**，
「全绿」是过期印象。时间线：9-04 最后一次绿灯 → 9-05 起上游改动（expansion v2 起）使 lint 红，
mypy job 因 `needs: lint` 从未再执行 → 期间合入的代码（collector 14→17、interactions 加 `req`、
leader_election 置位契约、pipeline P1-4 把 gauges 移入 to_thread）对应的测试断言全部过期。

本次已统一口径并修复：

- **mypy strict 全仓 66 → 0**（225 文件）：16 个文件的违规，主体是四类同源模式——
  ① `meta.get("signals") if isinstance(meta.get("signals"), dict)` 双 get 收窄失效（8 处，收敛为
  `project_signals.signals_of()` 共享 helper）；② 异构字面量常量缺显式注解（bridge/sell_off/calendar）；
  ③ Literal 键 dict 用 `str | None` 查询（anti_pua/viability_gate 显示表放宽为 `dict[str, str]`）；
  ④ 其余单发（auth 冗余 cast、faucet 探测缓存窄化、leader unreachable、sybil 复名、gas `Body(...)`）。
- **ruff check 163 → 0、format 91 文件全对齐**（CI lint 两道门恢复绿色）。
- **顺带修掉 1 个真实潜在 NameError**：`bot_notifier` 的 `/faucets` 处理器调用不存在的
  `list_faucets()`（真名 `list_faucets_with_status`，字段名/状态值也全对不上）——用户在 Telegram
  敲该指令必 500，因 lint 先红 mypy 从未跑到而存活三周。
- **过期测试契约修正**（全部 stash 基线验证过在 HEAD 即失败，非本次引入）：
  `main_lifespan`（collector 14→17；`items_new>0` 才触发管线）、`leader_election`（断言与实现
  自相矛盾，按 734f0a7 实现改为初取即 `is_leader=True`）、`interactions`（3 处直调缺 `req`）、
  `pipeline_run`（P1-4 后 to_thread 契约×2）。
- **1 个真实产品 bug**：匿名（MVP 无凭证放行）POST 时 body 的 `user_id` 被直接落库为属主，
  同一匿名身份 PATCH 自己刚创建的记录会被属主校验 404 死锁。修复：匿名不采信 body.user_id，
  属主留空（None），属主校验对空属主放行。

验证：全仓 `mypy app` 0 错误、`ruff check .` 与 `ruff format --check .` 全绿；
受影响 12 个测试文件（collectors/agents/golden/utils 583 + interactions 226 三块 + 
pipeline_run 50 + main_lifespan 22 + 其余批次）全部通过。本地唯一遗留差异是
**Python 3.11（本地 venv）vs 3.12（CI）**——本次修复后两边 mypy 均为 0，该口径差异已无害。

---

## 附 2：测试套件提速 19 分钟 → 3.5 分钟（2026-09-24）

**目标**：`test_interactions.py` 每 API 用例 ~2.5s 导致全量 19 分钟；引入
pytest-xdist 把全量压进 5 分钟。

### 根因与修复（按 ROI 排序）

| 慢因 | 实测 | 修复 |
|---|---|---|
| **tmp 落在仓库目录**：实时杀毒/索引扫描放大每条 SQLite DDL 提交成本，conftest 的 tmp_path 覆盖把 per-test 目录建在 `data/pytest_tmp` | 同一 30KB DDL 仓库目录 ~4s vs 系统 TEMP ~0.3s（~12×） | conftest tmp 基准改为系统 TEMP 优先（保留仓库目录回退），**19min → 2min** |
| **xdist worker 共库**：controller 先加载 conftest（此时无 worker 标识），worker 继承被污染的 `DB_PATH`，8 个 worker 全写同一个 `data/test.db`（残留 86MB）；`setdefault` 在继承环境前已失效 | 固定 ID 用例（`usr_alice` 等）并行下撞 UNIQUE/残留计数，且 loadfile 模式大面积红 | worker 内改为**强制覆盖** `DB_PATH`（串行仍 `setdefault`），并在 `pytest_configure` 里删库重建 + `init_db()`，等价 CI 全新库 |
| **Twitter 限流器真实时钟白等**：`twitter_kol/keyword` 0.2 rps / burst 1，mock 的 HTTP 每请求真等 ~5s | 2 个采集用例各 31s（pytest --durations） | 测试 fixture `monkeypatch.setitem` 降速令牌桶（被测对象是采集逻辑非限流器），**94s → 7s** |
| **admin 用例误跑真实采集**：鉴权放行后 defillama 采集器真出网（DNS/超时） | 单用例 42s | fixture 里把注册表单例的 defillama `collect()` 换成带时间戳的空结果桩（鉴权中间件路径原样保留），**42s → 5s** |
| **calibration verifier 重采样**：`run_verification` 每例双跑报告管线，`BOOTSTRAP_REPLICATES=1000` | 9 用例 ×26s ≈ 240s | 仓库既有惯例：测试 monkeypatch 降到 20；脚本契约改为调用时读 report 模块运行时属性（from-import 会冻结 1000 导致契约自相矛盾），**240s → 10s** |

### xdist 结论

- `pytest-xdist==3.8.0` 已锁定进 `requirements-dev.txt`（CI 的 `pytest tests -q` 无需改命令即自动并行——前提是 CI 决定引入；未引入时 CI 维持串行也完全安全）。
- **默认 load 分发（-n 8）是甜点**：本机 24 逻辑核，`-n 12` 反而更慢（CPU 争抢），
  **`--dist loadfile` 是负优化**（auth-DB 文件被钉到同 worker，初始化顺序依赖暴露：
  `clean_auth_db` 跑在 `create_app()` 建表之前 → "no such table"，残留行污染同 worker 下一个文件）。
- 顺带修掉一个顺序耦合：`test_unified_scheduler` 两处对 `get_jobs()` 的**列表**相等断言改为集合
  （APScheduler 按下次触发时间排序，注册顺序不可依赖），连续多轮验证稳定。

### 最终数据

- 全量 **3796 用例：3:29–3:42（8 worker）**，两轮失败集合逐项一致（14 个全部是已确认的
  存量文档漂移，见附 1），跨轮次确定性达成；串行口径与并行口径失败一致。
- 改动文件 `ruff check` / `ruff format --check` 全绿；`mypy app` 维持 0 错误（225 文件）。
- CI 可用性说明：CI 不装 `pytest-xdist` 时现有 `pytest tests -q` 行为不变（xdist 仅是
  已安装才激活的插件，addopts 未写入 `-n`）。

---

_审计方法：逐文件通读全部 28 个服务 + 抽查对应路由与测试；gas_alert bug 已现场修复并验证。_
