# ADR-008: 用户系统与多租户隔离

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构 / 产品

## 背景

系统当前没有用户概念（MVP 单用户无鉴权），但 V2/V3 多项功能依赖用户身份：

- **匿名反馈回流**：US-010 用户提交"有用/无用"反馈、US-011 事后标注，需要区分不同用户。
- **隐式行为埋点**：US-012/US-013 需要将点击/停留等行为关联到用户。
- **个性化排序**：US-016 需要基于用户偏好调整项目排序。
- **审计追溯**：US-015 需要记录谁在何时做了什么操作。
- **多用户隔离**：V3 SaaS 场景下，用户 A 的反馈数据不应被用户 B 看到。
- **GDPR 合规**：用户应能导出/删除自己的数据。

现有设计仅在 `feedback`/`events` 表预留了 `user_id TEXT` 字段、`SECURITY.md` §4.3 一句话提了 V3 RBAC，但缺少完整的用户系统设计。

## 决策

### 1. 三阶段演进

| 阶段 | 认证 | 用户模型 | 数据隔离 | 目标 |
| --- | --- | --- | --- | --- |
| **MVP** | 无（本地绑定） | 单用户（无 user_id） | 无 | 可演示 |
| **V2** | API_KEY（管理员）+ 匿名 token（仪表盘用户） | admin + anonymous | 行级（feedback/events） | 小团队可用 |
| **V3** | JWT（OAuth2 密码）+ 可撤销 API Key | admin / analyst / viewer 三角色 + anonymous | 行级 + RBAC | 多用户 SaaS |

### 2. 角色定义（V3）

- **admin**：全部权限，包括触发 run、管理用户、管理 API Key。
- **analyst**：查看项目、提交反馈、事后标注、re-score、管理个人 API Key。
- **viewer**：只读 Dashboard（不可触发 run、不可提交反馈）。
- **anonymous**（V2+）：查看项目、提交反馈/events，不可触发 run。

### 3. 核心数据模型

- `users` 表：id/UUID、email、bcrypt password_hash、display_name、role、preferences(JSON)
- `sessions` 表：持久化 refresh token，支持多设备登录
- `blacklisted_jti` 表：JWT 吊销检测
- `api_keys` 表：可撤销的 API Key（bcrypt hash 存储）

### 4. 行级数据隔离

- `feedback`、`events`、`api_keys`、`sessions`：按 `user_id` 过滤，admin 可查看全部。
- `projects`、`logs`、`project_history`：全局共享（项目数据对所有用户一致）。
- 后端中间件自动注入 `WHERE user_id = ?`。

### 5. 个性化不改变核心评分

- 个性化排序在应用层加权，**不修改** `projects` 表的 `score`。
- 用户偏好以 JSON 存入 `users.preferences`。
- 用户可关闭个性化恢复默认排序。

### 6. GDPR 就绪

- 数据导出：`GET /api/v1/user/data`
- 账户删除：`DELETE /api/v1/user/account`（反馈去标识化、events 删除）
- 全设备登出：`POST /api/v1/auth/logout/all`

## 理由

| 备选 | 否决理由 |
| --- | --- |
| MVP 直接接 JWT | 增加了 MVP 门槛，部署需配置密钥、用户注册流程，与"零运维启动"目标冲突 |
| V2 就用完整的 JWT + RBAC | 单用户/小团队场景下 RBAC 过重；API_KEY 对脚本/CI 更友好 |
| 用户偏好用独立表而非 JSON | 字段少且变更频繁，JSON 方便演进；独立表增加 JOIN 查询 |
| 匿名用户不设 token，用 IP 标识 | IP 可变（NAT/VPN），无法可靠关联用户跨 session 的行为 |
| V2 匿名 token 用 session cookie | 单页 HTML 与 API 分离部署时 cookie 跨域复杂，Bearer header 更通用 |

## 后果

- **后端新增模块**：`auth.py`（JWT 签发/校验、bcrypt 密码、匿名 token）、`middleware.py`（鉴权中间件）。
- **新增数据库表**：V2 建 `auth` 相关表不建；V3 建 `users`/`sessions`/`blacklisted_jti`/`api_keys` 四张表。
- **新增 15 个 API 端点**（§25.10）：auth(6) + user_prefs(3) + user_data(2) + api_keys(3)。
- **API 测试扩展**：每个新端点需鉴权测试（401/403）、匿名用户测试、三角色权限测试。
- **迁移成本**：V2→V3 时，现有 feedback/events 的 `user_id` 从匿名 token 转为 users.id 外键。匿名 token 的 user_id 在 users 表中无对应行，需 V3 迁移时保留为 NULL。
- **API 版本协调**：V3 引入 JWT 时，若认证端点响应格式或鉴权方式无法向后兼容（如从 Bearer 匿名 token 切换到 JWT 时 payload 结构变化），将触发 ADR-009 的 API 版本升级流程（`/api/v2/`）。V3 设计时需前置评估：认证端点是否可在 v1 内兼容升级（如添加可选字段、保留旧 token 格式），或需启动新版本。此风险已在 [ADR_CROSS_REFERENCE.md](ADR_CROSS_REFERENCE.md) CR-01 中记录。
- **TASK_BREAKDOWN 新增**：W2 后端增加 `auth.py` 模块；W6 安全测试增加用户相关渗透测试项。
