

# 🧠 Web3 Airdrop Alpha Agent System（完整版工程方案）

> ⚠️ **版本说明**：本文档为 **v0.2 草案**（高层架构参考），后续已拆分为多份专项规范。
> - 数据库 Schema 请以 [ENGINEERING_ROADMAP.md §5](ENGINEERING_ROADMAP.md) 为准
> - 评分算法请以 [DATA_SCORING_DICT.md](DATA_SCORING_DICT.md) 为准
> - API 设计请以 [API_SPEC.md](API_SPEC.md) 为准
> - ADR 记录请以 [docs/adr/](adr/) 目录为准（当前含 ADR-001~011）
> - 本文档保留作为高层架构参考，具体实现细节以专项规范为准。

---

# 1️⃣ 项目定位（非常重要）

## 🎯 产品定义

一个基于多智能体系统的：

> 🧠 Web3 Early-Stage 项目机会识别与空投参与决策系统

---

## 📌 核心目标

系统每天自动输出：

* 新 Web3 项目列表
* 每个项目的综合评分
* 是否值得参与空投
* 具体参与策略（actionable steps）

---

## 🚫 不做什么

* 不保证收益（不是投资建议）
* 不做交易执行系统（v1）
* 不做链上资金自动操作

---

# 2️⃣ 系统总体架构（生产级设计）

```text id="arch_full"
                    ┌────────────────────┐
                    │   Frontend UI     │
                    │  (Next.js Dash)   │
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │   API Gateway      │
                    │    (FastAPI)       │
                    └────────┬───────────┘
                             │
        ┌────────────────────────────────────────┐
        │          Orchestrator Layer           │
        │   (Multi-Agent Coordination Engine)   │
        └──────┬──────────┬──────────┬──────────┘
               │          │          │
     ┌────────▼───┐ ┌────▼────┐ ┌───▼────────┐
     │ Collector   │ │ Analyzer│ │ Scoring    │
     │ Agent       │ │ Agents  │ │ Engine     │
     └────┬────────┘ └────┬────┘ └────┬──────┘
          │               │            │
     ┌────▼──────────────▼────────────▼──────┐
     │         Specialized Agents Layer        │
     │ Narrative | Team | Risk | Tokenomics   │
     └────────────────────────────────────────┘
                             │
                     ┌───────▼────────┐
                     │  Data Layer     │
                     │ SQLite / Postgres│
                     └──────────────────┘
```

---

# 3️⃣ 核心模块设计

---

# 🧲 3.1 Project Discovery Layer（项目发现）

## 🎯 功能

持续发现 Web3 新项目

## 📡 数据源

### 必须（MVP级）

* DefiLlama 新协议
* CryptoRank 项目库
* Twitter关键词扫描

### 可选增强

* GitHub trending web3
* VC portfolio feeds
* Mirror / Medium launch posts

---

## 📌 输出结构

```json id="proj"
{
  "id": "uuid",
  "name": "LayerX",
  "url": "...",
  "sector": "L2",
  "stage": "testnet",
  "raw_signals": {
    "has_points": true,
    "airdrop_hint": true
  }
}
```

---

# 🧭 3.2 Narrative Engine（赛道周期）

## 🎯 职责

判断：

> 这个赛道现在处于什么周期阶段？

---

## 📊 输出

```json id="nar"
{
  "sector": "Restaking",
  "stage": "growth",
  "heat_score": 0.82,
  "timing": "early | peak | late"
}
```

---

## 📌 关键逻辑

* Twitter热度
* VC资金流入
* 新项目数量
* 是否已KOL泛滥

---

# 🧑‍⚖️ 3.3 Team Reputation Engine（团队信誉）

## 🎯 职责

识别：

* 是否换皮团队
* 是否有 rug / scam history
* VC是否只是“洗白工具”

---

## 📊 输出

```json id="team"
{
  "score": 0.72,
  "risk_level": "medium",
  "flags": [
    "previous failed project",
    "anonymous team"
  ]
}
```

---

# ⚠️ 3.4 Risk Engine（风险模型）

## 🎯 职责

评估：

* Sybil难度
* farming成本
* token结构风险

---

## 📊 输出

```json id="risk"
{
  "sybil_difficulty": "high",
  "farming_cost": "medium",
  "token_risk": 0.68
}
```

---

# 🪙 3.5 Tokenomics Engine（新增关键模块）

## 🎯 职责

分析：

* token分配
* unlock压力
* VC & team占比
* 通胀机制

---

## 📊 输出

```json id="token"
{
  "vc_share": 0.25,
  "team_share": 0.2,
  "unlock_pressure": "high",
  "risk": 0.75
}
```

---

# 📊 3.6 Scoring Engine（核心决策）

## 🎯 输出统一评分

```json id="score"
{
  "score": 83,
  "label": "HIGH POTENTIAL",
  "recommendation": "FARM",
  "reason": [
    "early narrative",
    "low competition",
    "strong airdrop signal"
  ]
}
```

---

## 📌 权重模型（生产版）

```text id="weight"
Airdrop Signal        20%
Narrative Timing      20%
Team Reputation       15%
Risk Engine           15%
Tokenomics            15%
Competition Level     15%
```

---

# 🧠 3.7 Orchestrator（系统大脑）

## 🎯 职责

* 调度所有 agents
* 去重项目
* 控制计算顺序
* 输出最终结果

---

## 流程

```text id="flow"
collect → enrich → analyze → risk → score → rank → output
```

---

# 🧾 4️⃣ 数据库设计（生产级）

## projects 表

```sql id="db"
id TEXT PRIMARY KEY
name TEXT
sector TEXT
stage TEXT

score INTEGER
label TEXT

narrative_json TEXT
team_json TEXT
risk_json TEXT
tokenomics_json TEXT

created_at TIMESTAMP
```

---

## logs 表

```sql id="logs"
id
project_id
agent_name
input
output
timestamp
```

---

# ⚙️ 5️⃣ API 设计（FastAPI）

## 核心接口

### 1️⃣ 运行分析

```
POST /run
```

---

### 2️⃣ 获取项目列表

```
GET /projects
```

---

### 3️⃣ 单项目详情

```
GET /project/{id}
```

---

### 4️⃣ 触发重新评分

```
POST /re-score/{id}
```

---

# 🖥️ 6️⃣ 前端系统（Next.js Dashboard）

## 页面结构

### 📊 Dashboard

* Top ranked projects
* score distribution

### 📄 Project Detail

* full agent analysis
* risk breakdown
* narrative stage

### 🧠 Insight Page

* hottest narratives
* risky teams cluster

---

## UI核心指标展示

* Score（0–100）
* Label（FARM / WATCH / IGNORE）
* Risk level
* Narrative stage

---

# 🤖 7️⃣ Agent设计（CrewAI / LangGraph）

## Agents列表

| Agent        | 职责   |
| ------------ | ---- |
| Collector    | 找项目  |
| Narrative    | 赛道判断 |
| Team         | 信誉分析 |
| Risk         | 风险分析 |
| Tokenomics   | 结构分析 |
| Scorer       | 综合评分 |
| Orchestrator | 控制流程 |

---

# 🔁 8️⃣ 系统运行流程

```text id="runtime"
1. 每日 cron trigger
2. Collector 拉取项目
3. 每个项目进入 agent pipeline
4. 所有 agent 并行分析
5. Scoring engine 汇总
6. 排序输出
7. API + dashboard 更新
```

---

# 🚀 9️⃣ MVP → V2 → V3 演进路线

---

## 🟢 MVP（现在这个）

* 静态数据 + agent逻辑
* 本地运行
* dashboard展示

---

## 🟡 V2（增强）

* Twitter + Dune真实数据
* 自动趋势识别
* Telegram推送

---

## 🔴 V3（高级）

* 多钱包策略建议
* 自动 farming checklist
* AI持续学习（memory system）

---

# 💡 10️⃣ 系统本质（很重要）

这个系统不是：

❌ 空投工具

而是：

> 🧠 Web3 叙事周期 + 项目质量 + 风险建模 + 时间窗口识别系统

---

# 🧭 如果你下一步要做

我建议你进入真正工程阶段，我可以帮你继续做：

### ✔ 1. 完整 repo（可直接 clone）

### ✔ 2. CrewAI / LangGraph agent 实现

### ✔ 3. Next.js dashboard UI设计稿

### ✔ 4. Twitter + Dune 数据接入

### ✔ 5. Docker 一键部署

---

只要你下一句说：

> “开始写 production repo”

我可以直接帮你把这个系统升级成**可以上线的 Web3 Alpha SaaS 雏形**。
