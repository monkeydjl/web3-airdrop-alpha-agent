# Benchmark — 性能基准

> 本目录管理项目的性能基准测试脚本、结果与报告。
> 参考：`docs/PERFORMANCE_BENCHMARK.md`、`docs/ENGINEERING_ROADMAP.md §23`

---

## 目录结构

```
benchmark/
├── README.md               # 本文档
├── scripts/                # 基准测试脚本
│   ├── run-pipeline.sh     # Pipeline 耗时基准
│   ├── api-throughput.sh   # API 吞吐量测试
│   └── db-query.sh         # DB 查询性能测试
├── results/                # 测试结果
│   └── 2026-07-08/         # 按日期组织
└── profiles/               # 性能分析配置
    ├── pipeline.profile    # Pipeline 耗时配置
    └── api.profile         # API 吞吐量配置
```

---

## 性能目标

| 指标 | MVP 目标 | V2 目标 | V3 目标 |
| --- | --- | --- | --- |
| 单项目端到端耗时（规则） | < 1s | < 500ms | < 300ms |
| 单项目端到端耗时（含 LLM） | N/A | < 15s | < 10s |
| 单次 run 耗时（50 项目） | < 60s | < 30s | < 15s |
| API P95 响应时间 | < 500ms | < 200ms | < 100ms |
| DB 查询 P95 | < 50ms | < 20ms | < 10ms |

---

## 运行基准测试

```bash
# Pipeline 耗时基准测试
bash benchmark/scripts/run-pipeline.sh --projects 50 --runs 3

# API 吞吐量测试（需安装 hey 或 wrk）
bash benchmark/scripts/api-throughput.sh --endpoint /api/v1/projects --requests 1000 --concurrency 10

# DB 查询性能测试
bash benchmark/scripts/db-query.sh --query "SELECT COUNT(*) FROM projects WHERE sector='L2'" --runs 100
```

---

_文档版本：v1.0 · 2026-07-08_
