# OpenTelemetry 可观测集成

> 可选组件（P2），用于分布式追踪、指标与日志的集中采集。
> 默认未启用，通过 Docker Compose profile `observability` 启动。

---

## 组件

| 组件 | 镜像 | 端口 | 用途 |
| --- | --- | --- | --- |
| OTel Collector | `otel/opentelemetry-collector-contrib:0.103.0` | 4317/4318/8889 | 接收 OTLP 并转发 |
| Jaeger | `jaegertracing/all-in-one:1.57` | 16686 | 追踪可视化 |

---

## 配置

- `configs/observability/otel/otel-collector-config.yml`：Collector 路由与处理
- `configs/observability/otel/otel-instrumentation.json`：应用侧仪器化元数据

---

## 启用方式

监控服务使用 Docker Compose profile `observability` 控制，默认不启动。

```bash
# 启动 OTel + Jaeger + Loki + Promtail（ observability profile ）
docker compose --profile observability -f docker-compose.prod.yml up -d otel-collector jaeger loki promtail

# 仅启动 OTel + Jaeger
docker compose --profile observability -f docker-compose.prod.yml up -d otel-collector jaeger

# 在应用环境变量中注入 OTEL 导出端点
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
export OTEL_SERVICE_NAME=airdrop-alpha
export OTEL_TRACES_SAMPLER=traceidratio
export OTEL_TRACES_SAMPLER_ARG=0.1

# 访问 Jaeger UI
open http://localhost:16686
```

---

## 采样策略

| 环境 | 采样率 | 说明 |
| --- | --- | --- |
| development | 1.0 | 全量采集，便于调试 |
| staging | 0.5 | 半量采集 |
| production | 0.1 | 10% 采样，降低成本 |

---

## 指标与追踪命名

- 指标：`airdrop.<metric_name>`（如 `airdrop.pipeline.runs.total`）
- 追踪：`airdrop.<operation>`（如 `airdrop.agent.run`）

---

_文档版本：v1.0 · 2026-07-08_
