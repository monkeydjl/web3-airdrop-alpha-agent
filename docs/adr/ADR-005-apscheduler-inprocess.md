# ADR-005: 调度用 APScheduler 进程内

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构 / 运维

## 背景

每日定时触发 `POST /run` 的调度方式可选：
- 外部 cron（宿主 crontab / GitHub Actions schedule）
- APScheduler 进程内调度
- 云函数定时触发

外部 cron 需宿主配置，容器迁移时易丢；云函数引入云依赖。

## 决策

MVP 用 **APScheduler 进程内调度**：
- FastAPI 启动时初始化 `AsyncIOScheduler`
- cron 表达式从 `SchedulerConfig` 读取（默认每日 08:00）
- 调用与 `POST /run` 相同的 Orchestrator 入口
- 保留 `POST /run` 供外部手动触发

## 理由

| 备选 | 否决理由 |
| --- | --- |
| 外部 cron | 宿主配置易丢；容器重建需重新配；本地开发需额外装 cron |
| GitHub Actions schedule | 依赖外部平台，本地/私有部署不可用；延迟可达 15min |
| Celery beat | 太重，MVP 无需分布式队列 |
| **APScheduler 进程内（本决策）** | 容器自包含、本地零依赖；与日志/监控同进程便于关联 |

## 后果

- **多实例部署问题**：V3 多实例时需避免重复触发。方案：单调度者模式（leader election）或拆出独立 scheduler 容器。MVP 单实例无此问题。
- 调度任务需**幂等**（§6.2.3 已保证：同 `dedup_key` 跨 run 不产生新 id）。
- 应用重启时调度任务丢失（APScheduler 默认内存 jobstore）；V2 可配 `SQLAlchemyJobStore` 持久化 job。
- 调度器与 FastAPI 同生命周期：服务挂了调度也停，符合预期（单实例）。
- 调度时间默认 08:00 UTC，可通过 `CRON_HOUR`/`CRON_MINUTE` 环境变量调整。
