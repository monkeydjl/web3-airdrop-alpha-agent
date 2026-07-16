# Web3 Airdrop Alpha Agent System

多智能体驱动的 Web3 早期项目识别与空投参与决策系统

[![Tests](https://img.shields.io/badge/tests-417%20passed-brightgreen)](backend/tests/)
[![Python](https://img.shields.io/badge/python-3.14-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

## ✨ 功能特点

- 🤖 **多 Agent 智能分析** - 4 个专业 Agent 并行评估项目
- 📊 **三档分类建议** - FARM (高推荐) / WATCH (观察) / IGNORE (忽略)
- 🚀 **批量评分** - 一次最多评分 100 个项目
- 💾 **数据持久化** - SQLite 存储，支持历史查询
- 📁 **导入导出** - Excel/CSV 批量导入导出
- 🌐 **REST API** - 完整的 OpenAPI 文档
- 🐳 **Docker 部署** - 一键容器化部署
- 🎨 **Web 界面** - 简洁易用的测试界面

## 🚀 快速开始

### 方式 1: 一键启动 (Windows 推荐)

```batch
# 双击运行
Start.bat

# 或命令行运行
.\Start.bat
```

**自动完成**:
- ✅ 检查 Python 环境
- ✅ 创建虚拟环境
- ✅ 安装依赖
- ✅ 启动后端 API (http://localhost:8002)
- ✅ 启动前端界面 (http://localhost:3002)
- ✅ 自动打开浏览器

**停止服务**:
```batch
Stop.bat
```

### 方式 2: 手动启动

**启动后端**:
```bash
cd backend
pip install -e .
uvicorn app.main:app --reload --port 8002
```

**启动前端**:
```bash
cd frontend
python -m http.server 3002
```

**导入种子数据**（可选，首次运行查看示例项目）:
```bash
cd backend
make seed
```

**访问**:
- 前端界面: http://localhost:3002
- API 文档: http://localhost:8002/docs
- API 端点: http://localhost:8002/api/v1

### 方式 3: Docker 部署

```bash
# 开发环境
./scripts/deploy.sh dev

# 生产环境（含 Nginx）
./scripts/deploy.sh prod

# 查看日志
docker-compose logs -f backend

# 停止服务
docker-compose down
```

详见 [DEPLOYMENT.md](DEPLOYMENT.md)

## 📖 使用示例

### Web 界面使用

1. **评分单个项目**
   - 打开 http://localhost:3002
   - 填写项目信息（名称、赛道、阶段等）
   - 勾选空投信号（测试网、积分计划等）
   - 点击"开始评分"
   - 查看评分结果和详细分析

2. **批量导入**
   - 点击"批量导入"标签
   - 下载 Excel 模板
   - 填写项目数据
   - 上传文件自动评分

3. **查看列表**
   - 点击"项目列表"标签
   - 查看所有已评分项目
   - 按标签筛选（FARM/WATCH/IGNORE）

4. **导出数据**
   - 点击"导出数据"标签
   - 选择格式（Excel/CSV）
   - 选择筛选条件
   - 下载文件

### API 使用

**评分单个项目**:
```bash
curl -X POST http://localhost:8002/api/v1/run \
  -H 'Content-Type: application/json' \
  -d '{
    "projects": [{
      "name": "LayerX",
      "url": "https://layerx.xyz",
      "sector": "L2",
      "stage": "testnet",
      "has_testnet": true,
      "has_points_program": true,
      "no_token_yet": true,
      "recent_funding": true
    }]
  }'
```

**查询项目列表**:
```bash
curl http://localhost:8002/api/v1/projects?label=FARM&min_score=80
```

**导出 Excel**:
```bash
curl -o projects.xlsx \
  "http://localhost:8002/api/v1/export/projects?format=excel&label=FARM"
```

**批量导入**:
```bash
curl -X POST http://localhost:8002/api/v1/import/projects \
  -F "file=@projects.xlsx"
```

## 🏗️ 系统架构

### 核心组件

```
┌─────────────────────────────────────────┐
│           Web Frontend (HTML)           │
│         http://localhost:3002           │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│         FastAPI Backend                 │
│      http://localhost:8002/api/v1       │
├─────────────────────────────────────────┤
│  ┌─────────────────────────────────┐   │
│  │   Multi-Agent Pipeline          │   │
│  │  ┌───┬───┬───┬────┐             │   │
│  │  │ N │ T │ R │ To │  → Scorer  │   │
│  │  └───┴───┴───┴────┘             │   │
│  └─────────────────────────────────┘   │
│                ↓                        │
│  ┌─────────────────────────────────┐   │
│  │   Repository Pattern            │   │
│  │   (SQLite Database)             │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

### Agent 架构

```
Collector → [Narrative, Team, Risk, Tokenomics] → Scorer
                     (并行执行)

- Narrative: 叙事时机分析 (赛道热度 + 项目阶段)
- Team: 团队信誉分析 (VC 背书 + 创始人)
- Risk: 风险评估 (代币风险 + 解锁压力)
- Tokenomics: 代币经济学 (分配比例 + 解锁)
- Scorer: 综合评分 (6维加权 + 竞争系数)
```

### 评分算法

```python
score = (
    airdrop_signal * 0.30 +      # 空投信号权重 30%
    narrative_timing * 0.25 +     # 叙事时机权重 25%
    team_reputation * 0.20 +      # 团队信誉权重 20%
    risk_factor * 0.15 +          # 风险因素权重 15%
    tokenomics * 0.10             # 代币经济权重 10%
) * competition_factor            # 竞争系数调整
```

**三档分类**:
- **FARM** (≥75分): 高度推荐参与
- **WATCH** (60-74分): 观察等待
- **IGNORE** (<60分): 不推荐

## 📊 项目统计

```
总代码行数: ~5,000+ 行
测试覆盖: 417 个测试 (100% 通过)
API 端点: 12 个
Agent 数量: 6 个
开发用时: ~32 小时
```

### 测试统计

| 模块 | 测试数 | 状态 |
|------|--------|------|
| Agent 核心 | 272 | ✅ 100% |
| API 层 | 76 | ✅ 100% |
| Repository | 20 | ✅ 100% |
| 部署配置 | 23 | ✅ 100% |
| 导入导出 | 26 | ✅ 100% |
| **总计** | **417** | **✅ 100%** |

## 🛠️ 技术栈

### 后端

- **框架**: FastAPI 0.115
- **Python**: 3.14
- **数据库**: SQLite 3 (WAL 模式)
- **日志**: structlog
- **测试**: pytest + pytest-asyncio
- **文档**: OpenAPI 3.1.0

### 前端

- **当前版本**: 纯 HTML/CSS/JavaScript (测试界面)
- **未来版本**: React + TypeScript + TailwindCSS

### 部署

- **容器化**: Docker + docker-compose
- **反向代理**: Nginx (可选)
- **自动化**: Shell 脚本 + Batch 脚本

## 📁 项目结构

```
Web3-Airdrop-Alpha-Agent-System/
├── backend/                 # 后端服务
│   ├── app/
│   │   ├── agents/          # Agent 实现
│   │   ├── routers/         # API 路由
│   │   ├── config.py        # 配置管理
│   │   ├── db.py            # 数据库连接
│   │   ├── repository.py    # 数据访问层
│   │   ├── export.py        # 导出工具
│   │   ├── import_utils.py  # 导入工具
│   │   └── main.py          # 应用入口
│   ├── tests/               # 测试套件 (417 tests)
│   ├── data/                # SQLite 数据库
│   └── pyproject.toml       # 依赖配置
├── frontend/                # 前端界面
│   ├── index.html           # 单页面应用
│   └── README.md            # 前端文档
├── scripts/                 # 运维脚本
│   ├── deploy.sh            # 部署脚本
│   ├── health-check.sh      # 健康检查
│   └── backup.sh            # 备份脚本
├── docs/                    # 完整技术文档
│   ├── ENGINEERING_ROADMAP.md
│   ├── API_SPEC.md
│   └── ...
├── docker-compose.yml       # Docker 编排
├── Dockerfile               # 镜像定义
├── nginx.conf               # Nginx 配置
├── Start.bat                # Windows 一键启动 ⭐
├── Stop.bat                 # Windows 停止服务
├── DEPLOYMENT.md            # 部署文档
└── README.md                # 本文件
```

## 🔧 配置

### 环境变量

复制 `.env.example` 到 `.env` 并修改:

```bash
# 应用配置
APP_ENV=production
LOG_LEVEL=info

# 数据库
DB_PATH=/app/data/app.db

# LLM (可选，默认使用启发式规则)
LLM_ENABLED=false
OPENAI_API_KEY=

# 并发控制
MAX_CONCURRENT_PROJECTS=10
```

### API 端口

- 默认后端: `8000`
- 默认前端: `3000`

可在 `docker-compose.yml` 或启动时修改。

## 📚 文档

### 快速入门
- [README.md](README.md) - 本文件
- [frontend/README.md](frontend/README.md) - 前端使用
- [DEPLOYMENT.md](DEPLOYMENT.md) - 部署指南

### API 文档
- [Swagger UI](http://localhost:8002/docs) - 交互式 API 文档
- [ReDoc](http://localhost:8002/redoc) - API 参考文档
- [docs/API_SPEC.md](docs/API_SPEC.md) - API 规格说明

### 技术文档
- [docs/ENGINEERING_ROADMAP.md](docs/ENGINEERING_ROADMAP.md) - 工程路线图
- [docs/DATA_SCORING_DICT.md](docs/DATA_SCORING_DICT.md) - 评分算法
- [docs/DATABASE_DDL.md](docs/DATABASE_DDL.md) - 数据库设计
- [docs/GOLDEN_TEST_CASES.md](docs/GOLDEN_TEST_CASES.md) - 测试用例

## 🧪 测试

```bash
# 运行所有测试
cd backend
pytest

# 运行特定模块
pytest tests/agents/          # Agent 测试
pytest tests/api/             # API 测试
pytest tests/test_repository.py  # Repository 测试

# 生成覆盖率报告
pytest --cov=app --cov-report=html

# 查看覆盖率
open htmlcov/index.html
```

## 🐛 故障排查

### 后端启动失败

```bash
# 检查端口占用
netstat -ano | findstr :8002

# 重新安装依赖
cd backend
pip install -e . --force-reinstall

# 检查 Python 版本
python --version  # 需要 3.10+
```

### 前端无法连接后端

1. 检查后端是否运行: http://localhost:8002/health
2. 检查浏览器控制台是否有 CORS 错误
3. 确认 API 地址配置正确（`frontend/index.html` 中的 `API_BASE`）

### 数据库错误

```bash
# 重新初始化数据库
rm backend/data/app.db
# 重启后端会自动创建新数据库
```

### 导入失败

1. 检查文件格式（必须是 .xlsx 或 .csv）
2. 确保至少包含"项目名称"列
3. 查看验证错误消息

## 🎯 开发路线图

### ✅ 已完成 (MVP)

- [x] W2: Agent 核心实现
- [x] W3: REST API 层
- [x] W4: 数据持久化
- [x] W5: Docker 部署
- [x] W6: 导入导出功能
- [x] W7: 简单前端界面

### 🔜 计划中

- [ ] 完整 React 前端
- [ ] 图表可视化
- [ ] 用户认证
- [ ] 定时任务调度
- [ ] 实时数据源集成

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - 现代 Python Web 框架
- [SQLite](https://www.sqlite.org/) - 轻量级数据库
- [OpenAI](https://openai.com/) - LLM 支持（可选）
- [Claude](https://claude.ai/) - AI 开发助手

## 📞 联系方式

- **Issues**: [GitHub Issues](https://github.com/your-org/web3-airdrop-alpha/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/web3-airdrop-alpha/discussions)

---

**Made with ❤️ for the Web3 Community**

---

## 🔗 相关链接

- [完整技术文档](docs/)
- [设计原始 README](README_old.md)
