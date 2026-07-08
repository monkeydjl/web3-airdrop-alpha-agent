# E2E & Load Tests

> 本目录包含端到端（E2E）测试与负载测试，用于验证完整服务链路与容量。

---

## 目录结构

```
tests/
├── e2e/
│   └── test_e2e_pipeline.py   # 端到端全链路测试
└── load/
    └── locustfile.py          # locust 负载测试脚本
```

---

## E2E 测试

### 运行条件

- 本地或 CI 已启动完整服务（`docker compose -f docker-compose.prod.yml up -d`）
- 默认访问 `http://localhost:8000`

### 运行命令

```bash
pytest tests/e2e -v -m e2e
```

### 测试范围

- 健康检查
- 触发 pipeline run 并验证响应结构
- 等待数据落库后验证项目列表非空
- API 版本头校验

---

## 负载测试

### 依赖

```bash
pip install locust
```

### 运行

```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
# 然后访问 http://localhost:8089 设置并发用户数
```

### 目标指标

| 指标 | MVP 目标 | V2 目标 |
| --- | --- | --- |
| P50 延迟 | < 200ms | < 100ms |
| P99 延迟 | < 1000ms | < 500ms |
| 错误率 | < 1% | < 0.1% |
| 并发用户 | 50 | 500 |

---

_文档版本：v1.0 · 2026-07-08_
