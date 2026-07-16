# Examples — 示例与使用指南

> 本目录存放项目的使用示例，包括 API 调用、脚本运行、数据查看等。
> 每个示例文件为自包含的 `.md` 文档或可运行的脚本。

---

## 目录结构

```
examples/
├── README.md                     # 本文档
├── api/                          # API 调用示例
│   ├── run-pipeline.sh           # 触发分析 pipeline
│   ├── query-projects.sh         # 查询项目列表
│   └── re-score.sh               # 重算评分
├── data/                         # 数据操作示例
│   ├── query-logs.sql            # logs 表查询
│   └── seed-data.sh              # 导入种子数据
└── docker/                       # Docker 操作示例
    ├── docker-run.sh             # Docker 运行
    └── docker-compose-example.yml
```

---

## API 示例

### 1. 触发分析 Pipeline

```bash
# 用种子数据跑分析
curl -X POST http://localhost:8002/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{"source": "seed", "limit": 50}'

# 预期响应：
# {
#   "ok": true,
#   "data": {
#     "analyzed": 5,
#     "inserted": 5,
#     "updated": 0,
#     "failed": 0,
#     "errors": [],
#     "elapsed_ms": 1240
#   }
# }
```

### 2. 查询项目列表

```bash
# 获取 Top 10 FARM 项目
curl "http://localhost:8002/api/v1/projects?label=FARM&limit=10&order=DESC"

# 获取特定赛道的项目
curl "http://localhost:8002/api/v1/projects?sector=L2&limit=20"
```

### 3. 查看项目详情

```bash
# 获取单个项目完整信息
curl "http://localhost:8002/api/v1/project/a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
```

### 4. 重算评分

```bash
# 用最新规则重算某个项目的评分
curl -X POST "http://localhost:8002/api/v1/re-score/a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
```

---

## 脚本示例

### 导入种子数据

```bash
python scripts/seed.py --force
```

### 运行完整测试

```bash
pytest tests/ -v --cov=backend/app
```

---

_文档版本：v1.0 · 2026-07-08_
