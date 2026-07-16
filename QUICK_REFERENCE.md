# 🚀 Quick Reference Card - v2.0

> Web3 Airdrop Alpha Agent System  
> 快速参考卡片 - 常用命令与文档索引

---

## 📁 核心文档路径

```bash
# Bootstrap 总览
docs/PROJECT_BOOTSTRAP_AUDIT_REPORT_V2.md  # 完整审计报告
docs/PROJECT_BOOTSTRAP_V2_SUMMARY.md       # 快速总结
docs/PROJECT_BOOTSTRAP_CHECKLIST_V2.md     # 检查清单

# 架构与产品
docs/IMPLEMENTATION_STATUS.md               # 实现现状（优先读）
docs/01_product.md                          # 产品规格
docs/02_architecture.md                     # 系统架构（C4 模型）
docs/ENGINEERING_ROADMAP.md                 # 工程路线图
docs/COLLECTION_ANALYSIS_HANDOFF.md         # 采集→分析交接
docs/WEIGHT_CALIBRATION.md                  # 权重校准协议

# 开发指南
docs/AI_DEV_WORKFLOW.md                     # AI 开发工作流（12 步）
docs/WORKFLOW_AUTOMATION.md                 # 工作流自动化
docs/CONVENTIONS.md                         # 编码规范（17 节）

# 运维手册
docs/DEPLOYMENT.md                          # 部署指南
docs/OPERATIONS.md                          # 运维手册
docs/OBSERVABILITY.md                       # 监控与观测
```

---

## ⚡ 常用命令

### 开发环境

```bash
# 一键设置
make setup

# 启动开发服务
make dev

# 运行测试
make test

# 代码检查
make lint
make format
make typecheck
```

### Git 工作流

```bash
# 创建新功能分支
./scripts/workflows/git-new-feature.sh "feature-name"

# 创建新 Agent
./scripts/workflows/agent-create.sh "agent-id" "Agent Name"

# 快速验证（Pre-commit）
./scripts/workflows/quick-check.sh

# 准备发布
./scripts/workflows/release-prepare.sh "1.0.0"
```

### 部署运维

```bash
# 部署生产环境
./scripts/deploy/production.sh "1.0.0"

# 快速回滚
./scripts/deploy/rollback.sh

# 数据库备份
./scripts/workflows/db-backup.sh

# 健康检查（本地开发端口 8002；Docker 内多为 8000）
curl http://localhost:8002/health
```

### 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/unit/agents/test_orchestrator.py -v

# 生成覆盖率报告
pytest --cov=backend --cov-report=html

# 运行 Golden 测试
pytest tests/golden/ -v
```

---

## 📊 项目状态速览

### Bootstrap 完成度

```
P0（必须）：     18/18 ✅ 100%
P1（强烈建议）： 22/22 ✅ 100%
P2（可选）：     11/11 ✅ 100%
────────────────────────────────
总计：           51/51 ✅ 100%
```

### 核心组件

| 组件 | 状态 | 说明 |
|-----|------|------|
| Orchestrator | ✅ 实现 | 250 行，5 个测试 100% 通过 |
| Agent 系统 | ✅ 定义 | 15 个 Agent 完整定义 |
| Skills 系统 | ✅ 就绪 | 22 个 Skill |
| Prompt 管理 | ✅ 完整 | 版本管理 + 评估 |
| 监控配置 | ✅ 完善 | Dashboard + 15 条告警 |
| 部署脚本 | ✅ 就绪 | 部署 + 回滚 |

---

## 🏗️ 架构快览

### 技术栈

```
语言：      Python 3.11+
Web 框架：  FastAPI
Agent 编排：自研 Orchestrator
数据库：    SQLite (MVP) → PostgreSQL (V2)
  前端：      Next.js (`frontend-next`，3002) + 旧 HTML 原型
调度：      APScheduler 进程内
配置：      pydantic-settings + .env
部署：      Docker + docker-compose
监控：      Prometheus + Grafana + Loki
```

### 目录结构

```
.
├── backend/app/          # 后端应用
│   ├── agents/           # Agent 实现
│   ├── api/              # API 路由
│   ├── services/         # 业务逻辑
│   └── utils/            # 工具类
├── tests/                # 测试
│   ├── unit/             # 单元测试
│   ├── contracts/        # 契约测试
│   ├── golden/           # Golden 回归
│   └── api/              # API 测试
├── docs/                 # 文档体系
├── agents/               # Agent 定义
├── skills/               # Skills 定义
├── prompts/              # Prompt 管理
├── knowledge/            # 知识库
├── scripts/              # 脚本工具
│   ├── workflows/        # 工作流自动化
│   └── deploy/           # 部署脚本
└── configs/              # 配置管理
    ├── development/      # 开发环境
    ├── staging/          # 预发布
    ├── production/       # 生产环境
    └── observability/    # 监控配置
```

---

## 🎯 开发工作流

### 完整流程

```
1. 创建分支
   ./scripts/workflows/git-new-feature.sh "feature-name"

2. 创建 Agent（如需）
   ./scripts/workflows/agent-create.sh "agent-id" "Agent Name"

3. 编写代码
   - 实现 backend/app/agents/agent-id.py
   - 编写 tests/unit/agents/test_agent-id.py

4. 快速验证
   ./scripts/workflows/quick-check.sh

5. 运行测试
   pytest tests/unit/agents/test_agent-id.py -v

6. 提交代码
   git commit -m "feat: 添加 XXX Agent"

7. 推送并创建 PR
   git push -u origin feature/feature-name
```

### 测试驱动开发（TDD）

```
1. 编写测试（Red）
   tests/unit/agents/test_new_agent.py

2. 运行测试，确认失败
   pytest tests/unit/agents/test_new_agent.py

3. 实现功能（Green）
   backend/app/agents/new_agent.py

4. 运行测试，确认通过
   pytest tests/unit/agents/test_new_agent.py

5. 重构（Refactor）
   优化代码，保持测试通过
```

---

## 📚 文档索引

### 按角色

**产品经理**
- `docs/01_product.md`
- `docs/USER_STORIES.md`
- `docs/GLOSSARY.md`

**架构师**
- `docs/02_architecture.md`
- `docs/ENGINEERING_ROADMAP.md`
- `docs/adr/` (11 份 ADR)

**后端开发**
- `docs/API_SPEC.md`
- `docs/DATABASE_DDL.md`
- `backend/app/agents/ORCHESTRATOR_IMPLEMENTATION.md`

**前端开发**
- `docs/FRONTEND_SPEC.md`
- `docs/DESIGN_TOKENS.md`

**测试工程师**
- `docs/TESTING_FRAMEWORK.md`
- `docs/GOLDEN_TEST_CASES.md`
- `docs/PERFORMANCE_BENCHMARK.md`

**运维工程师**
- `docs/DEPLOYMENT.md`
- `docs/OPERATIONS.md`
- `docs/OBSERVABILITY.md`

**安全工程师**
- `docs/SECURITY.md`

---

## 🔧 故障排查

### 常见问题

**Orchestrator 测试失败**
```bash
# 检查 structlog 是否安装
pip install structlog

# 运行测试（不检查覆盖率）
pytest tests/unit/agents/test_orchestrator.py -v --no-cov
```

**部署健康检查失败**
```bash
# 查看容器日志
docker logs <container-id>

# 检查端口
netstat -an | grep 8000

# 手动健康检查
curl http://localhost:8002/health
```

**数据库锁定**
```bash
# 检查 WAL 模式
sqlite3 data/airdrop.db "PRAGMA journal_mode;"

# 应该返回 "wal"
```

---

## 📞 获取帮助

### 文档
- **完整报告**：`docs/PROJECT_BOOTSTRAP_AUDIT_REPORT_V2.md`
- **快速总结**：`docs/PROJECT_BOOTSTRAP_V2_SUMMARY.md`
- **一致性检查**：`docs/DOCUMENTATION_CONSISTENCY_REPORT.md`

### 工具
- **工作流自动化**：`docs/WORKFLOW_AUTOMATION.md`
- **AI 开发流程**：`docs/AI_DEV_WORKFLOW.md`
- **编码规范**：`CONVENTIONS.md`

### 模板
- **Agent 模板**：自动生成 `./scripts/workflows/agent-create.sh`
- **ADR 模板**：`docs/adr/TEMPLATE.md`
- **Skill 模板**：`skills/README.md` §2

---

## 🎓 最佳实践速记

### 代码质量

```bash
✓ 所有 Agent 必须有测试
✓ 测试覆盖率 ≥ 80%
✓ Type Hint 全覆盖
✓ Docstring 必填
✓ 通过 ruff/mypy 检查
```

### Git 规范

```bash
✓ 使用 Conventional Commits
✓ 分支命名：feature/, bugfix/, hotfix/
✓ 小而频繁的提交
✓ PR 必须通过 CI
✓ 代码评审必须通过
```

### 文档规范

```bash
✓ 新功能必须有文档
✓ ADR 记录重要决策
✓ README 保持更新
✓ 文档末尾标注版本
✓ 使用相对路径引用
```

---

## 🎉 v2.0 亮点

| 亮点 | 说明 |
|-----|------|
| 🤖 **Orchestrator 实现** | ADR-002 落地，250 行生产级代码 |
| ⚡ **效率提升 99%** | Agent 创建从 30 分钟缩短至 3 秒 |
| 🚀 **一键部署** | 完整的部署 + 回滚脚本 |
| 📊 **全面监控** | 9 个面板 + 15 条告警规则 |
| 📚 **文档完整** | 51/51 项 100% 完成 |

---

_快速参考：v2.0 · 2026-07-08_
