# CLAUDE.md — Agent 工作约定

> 本文件是给 AI agent / 协作者的快速约束清单，供每次提交遵循。完整工程规范见 [CONVENTIONS.md](CONVENTIONS.md)，术语以 [docs/GLOSSARY.md](docs/GLOSSARY.md) 为唯一权威定义。

## 1. 术语约定（必须遵守）

评分子系统相关表述按下表统一，**勿混用、勿随意替换**：

| 术语 | 含义 | 使用场景 |
|---|---|---|
| **评分决策引擎**（Scoring Decision Engine） | 评分子系统总称：评分权重（Σ=1.0 启动断言，ADR-006）+ LLM 增强（ADR-001）+ 质量阈值 | 指代整个评分子系统（架构图、产品能力表、章节标题、设置页引擎层） |
| **规则引擎**（rule-based） | LLM 关闭时的默认打分路径，无外部依赖、可离线演示（ADR-001） | 描述默认打分路径、LLM fallback 回退目标、成本对比基线 |
| **LLM 增强** | 可选插件层，配置 `OPENAI_API_KEY` 且开启开关后叠加 | 描述可选增强，不作默认路径 |
| **旁路机会引擎**（Opportunity Engine） | 独立于评分决策引擎的非权威对照引擎（v2.0 影子评估） | 指 v2.0 Opportunity 子系统，勿与评分决策引擎混淆 |

**关键边界**：「评分决策引擎」与「规则引擎」不是同义词——前者是整个评分子系统（含 LLM 增强与阈值），后者仅指默认打分路径。指代整个子系统时必须用「评分决策引擎」，不得写成「规则引擎」。

术语首次出现于新文档时，锚点链接到 `[GLOSSARY §2](docs/GLOSSARY.md)`。

**强制检查**：pre-commit 钩子 `check-terminology`（`scripts/check_terminology.py`）会在提交时拦截「评分引擎 / 评分大脑 / scoring engine」等回退写法；全仓自检可手动跑 `python scripts/check_terminology.py --all`。

## 2. 文档与代码同步

- 评分权重 / 阈值 / LLM 行为变更 → 同步更新 `docs/GLOSSARY.md`（如涉及术语定义）与对应 ADR
- 环境变量变更 → 同步更新 `.env.example`
- API 变更 → 同步更新 `docs/API_SPEC.md`
- 新术语 → 先在 `docs/GLOSSARY.md` 立词条，再在其它文档引用

## 3. Secrets

- **禁止**打开 / 读取 / 提交 `.env`、`*.pem`、`*.key` 等密钥文件（`.env.example` 除外）
- 检查配置是否已设置用 `python -c "from app.config import settings; print(bool(settings.github_token))"`，只输出 True/False
- 详见 [AGENTS.md](AGENTS.md)

## 4. 参考

| 文档 | 内容 |
|---|---|
| [CONVENTIONS.md](CONVENTIONS.md) | 完整编码规范（命名/导入/测试/Git） |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | 术语唯一权威定义 |
| [docs/adr/](docs/adr/) | 架构决策记录 |
| [AGENTS.md](AGENTS.md) | 仓库级 agent 指令（secrets 防护等） |

---

_文档版本：v1.0 · 术语约定以 GLOSSARY 为准_
