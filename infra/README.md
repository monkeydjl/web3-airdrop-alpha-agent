# Infrastructure — 基础设施文档

> 本目录管理项目的基础设施配置，包括 Docker/Prometheus/Grafana/Nginx 等。
> 参考：`docs/DEPLOYMENT.md`、`docs/OBSERVABILITY.md`

---

## 目录结构

```
infra/
├── README.md               # 本文档
├── docker/                  # Docker 配置
│   ├── Dockerfile           # 生产多阶段构建
│   └── docker-compose.yml   # 本地编排
├── monitoring/              # 监控配置
│   ├── prometheus/
│   │   └── prometheus.yml   # Prometheus scrape config
│   └── grafana/
│       └── dashboards/      # Grafana 面板 JSON
├── nginx/
│   ├── nginx.conf           # Nginx 反向代理
│   └── ssl/                 # TLS 证书（.gitignored）
└── scripts/                 # 基础设施脚本
    ├── backup.sh            # 数据备份
    ├── restore.sh           # 数据恢复
    └── healthcheck.sh       # 健康检查
```

---

## 部署架构

### MVP（单容器）

```
┌──────────────┐
│  Docker Host │
│  ┌─────────┐ │
│  │ FastAPI │ │
│  │ + SQLite│ │
│  │ + 静态   │ │
│  │  前端    │ │
│  └─────────┘ │
│  端口: 8000  │
└──────────────┘
```

### V2（多服务）

```
         ┌──────────┐
         │  Nginx   │
         │  443/80  │
         └────┬─────┘
              │
              ▼
    ┌─────────────────┐
    │   FastAPI Web   │
    │  (8 workers)    │
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │  PostgreSQL 15  │
    │  (主实例)        │
    └─────────────────┘
```

### V3（高可用）

```
       ┌──────────────┐
       │  Load        │
       │  Balancer    │
       └──────┬───────┘
              │
      ┌───────┴───────┐
      │               │
  ┌───▼───┐      ┌───▼───┐
  │ Web-1 │      │ Web-2 │
  │ (app) │      │ (app) │
  └───┬───┘      └───┬───┘
      │               │
      └───────┬───────┘
              │
       ┌──────▼──────┐
       │ PostgreSQL  │
       │ Primary +   │
       │ Standby     │
       └─────────────┘
```

---

## Prometheus 配置

`infra/monitoring/prometheus/prometheus.yml`

```yaml
global:
  scrape_interval: 30s
  evaluation_interval: 30s

scrape_configs:
  - job_name: 'airdrop-alpha'
    static_configs:
      - targets: ['web:8000']
    metrics_path: '/metrics'
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        regex: '(.*):.*'
        replacement: '$1'

  - job_name: 'postgresql'
    static_configs:
      - targets: ['db:9187']
    metrics_path: '/metrics'

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
```

---

## 备份策略

### 数据备份

```bash
# SQLite（MVP）
bash infra/scripts/backup.sh

# PostgreSQL（V2）
pg_dump -U airdrop -h localhost airdrop > backups/airdrop-$(date +%F).sql
```

### 备份保留

| 类型 | 保留期 | 频率 | 存储 |
| --- | --- | --- | --- |
| 每日快照 | 14 天 | 每日 04:00 | 本地 `backups/` |
| 每周快照 | 3 个月 | 每周日 | 远程存储 |
| 月度快照 | 12 个月 | 每月 1 日 | 远程存储 |

---

## 健康检查端点

| 端点 | 用途 | 预期响应 |
| --- | --- | --- |
| `GET /health` | 应用健康 | `{"ok":true,"data":{"status":"healthy","db":"connected","uptime_seconds":12345}}` |
| `GET /metrics` | Prometheus 指标 | Prometheus 文本格式 |
| `GET /api/v1/` | API 可用性 | 200（版本信息） |

---

_文档版本：v1.0 · 2026-07-08_
