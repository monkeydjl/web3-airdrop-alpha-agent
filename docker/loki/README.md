# Loki 日志集中采集

> 可选组件（P2），用于集中化收集应用日志。
> 默认未启用，通过 Docker Compose profile `observability` 启动。

---

## 组件

| 组件 | 镜像 | 端口 | 用途 |
| --- | --- | --- | --- |
| Loki | `grafana/loki:2.9.0` | 3100 | 日志存储与查询 |
| Promtail | `grafana/promtail:2.9.0` | 9080 | 日志采集与推送 |

---

## 配置

- `docker/loki/loki-config.yml`：Loki 本地文件存储配置
- `docker/loki/promtail-config.yml`：Promtail 采集规则

---

## 启用方式

监控服务使用 Docker Compose profile `observability` 控制，默认不启动。

```bash
# 启动 Loki + Promtail + OTel + Jaeger（observability profile）
docker compose --profile observability -f docker-compose.prod.yml up -d loki promtail otel-collector jaeger

# 仅启动 Loki + Promtail
docker compose --profile observability -f docker-compose.prod.yml up -d loki promtail

# 查询日志示例
curl -G -s "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="airdrop-alpha",service="backend"}'
```

---

## 标签规范

| 标签 | 值 | 说明 |
| --- | --- | --- |
| `job` | `airdrop-alpha` | 全局任务名 |
| `service` | `backend` / `nginx` | 服务名 |

---

## 保留策略

- 默认 7 天（`reject_old_samples_max_age: 168h`）
- 生产环境建议切换至对象存储 + 更长保留期

---

_文档版本：v1.0 · 2026-07-08_
