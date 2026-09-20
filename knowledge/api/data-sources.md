# 外部 API 知识：数据源接口

> 引用键：`KN:api:defillama` / `KN:api:cryptorank` / `KN:api:twitter`
> 来源：`docs/ENGINEERING_ROADMAP.md §10`、`backend/app/fetcher.py`
> 更新：2026-07-08

## 概述

系统通过 `fetcher` 统一访问外部数据源，具备缓存、重试、熔断能力（CONVENTIONS.md §7.3）。
所有外部调用禁止硬编码密钥，使用 `pydantic-settings` 注入。

## 数据源清单

| 源 | 用途 | 认证 | 限流 | 失败处理 |
| --- | --- | --- | --- | --- |
| DefiLlama | TVL / 协议列表 | 无 | 宽松 | 4xx 不重试；5xx 退避重试 |
| CryptoRank | 新项目发现 | API Key | 中 | 429 → 退避 |
| Twitter / X | 社区情绪 | OAuth2 | 严格 | 401/403 标记并跳过 |
| ~~Dune~~ | 链上分析 | — | — | **未接入**：无 collector，配置键已于 2026-09-03 删除 |

## 调用约定

- 变量填充前转义用户输入，防注入。
- 响应中敏感字段在 structlog 配置 `redact`。
- 4xx 不重试；5xx 指数退避（`base=1s, factor=2, max=30s, cap=3`）。

## 参考

- `docs/ENGINEERING_ROADMAP.md §10 数据源接入`
- `backend/app/fetcher.py`
