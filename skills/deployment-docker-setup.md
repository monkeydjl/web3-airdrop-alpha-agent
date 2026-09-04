# Skill：Docker 构建配置

## 目标
维护/优化镜像构建配置，遵循 docs/DEPLOYMENT.md。

> **两个镜像，两个 Dockerfile，不要混在一起**：
> - 后端：`docker/Dockerfile`（**只有后端**，两个 stage 都是 `python:3.12-slim`）
> - 前端：`frontend-next/Dockerfile`（`node:22-alpine`，standalone 产物 `node server.js`）

## 适用场景
- 修改 `docker/Dockerfile` 或 `frontend-next/Dockerfile`
- 多阶段构建优化镜像体积
- 调整运行用户/健康检查/端口

## 输入要求
- 文件：`docker/Dockerfile`（后端）
- 文件：`frontend-next/Dockerfile`（前端）
- 文件：`docker-compose.prod.yml`（服务编排：nginx / frontend / web / db / prometheus / alertmanager / grafana / loki / promtail / otel-collector / jaeger）
- 文件：`docs/DEPLOYMENT.md`
- 文件：`backend/requirements.txt`（依赖清单，头部有"必须精确锁定"的理由）

## 现状事实表（改之前先核对）
| 项 | 后端 | 前端 |
| --- | --- | --- |
| 基础镜像 | `python:3.12-slim`（builder + production 两 stage） | `node:22-alpine`（deps / builder / runner 三 stage） |
| 依赖安装 | `pip install -r requirements.txt` 到 `/venv` | `npm ci` |
| 运行用户 | `USER appuser` | `USER nextjs` |
| 端口 | `EXPOSE 8002` | `EXPOSE 3002` |
| 启动命令 | `python -m uvicorn app.main:app --host 0.0.0.0 --port 8002` | `node server.js` |
| 健康检查 | `curl -f http://localhost:8002/health` | `node -e "fetch('http://localhost:3002/')..."` |

**镜像里刻意不装的东西**（别"顺手补上"）：
- `requirements-dev.txt`（pytest/ruff/mypy）—— 不进运行镜像
- `requirements-otel.txt`（链路追踪）—— `app/tracing.py` 会优雅降级；
  Dockerfile 里有注释掉的两行给需要时打开

## 执行步骤

### Step 1: 改后端镜像
- 操作：改 `docker/Dockerfile`，依赖变更改 `backend/requirements.txt`
- 验证：
  - **不要引用 `requirements.lock.txt`** —— 该文件不存在；`requirements.txt` 已是
    全 `==` 精确锁定
  - 新增系统包要说明理由，`python:3.12-slim` 基线之外的包会被镜像体积审查盯上
  - 传递依赖（如 `anyio`、`starlette`）必须显式写进 `requirements.txt` 并 pin，
    否则只有 CI 会拉到新版，本地永远复现不出（有门禁
    `backend/tests/test_requirements_pinning.py` 守着）

### Step 2: 改前端镜像
- 操作：改 `frontend-next/Dockerfile`
- 验证：Next.js 需 `output: 'standalone'`（`runner` stage 直接 `node server.js` 依赖它）；
  `npm ci` 不要换成 `npm install`

### Step 3: 健康检查与编排
- 操作：`docker-compose.prod.yml` 里配 `healthcheck`，后端探 `/health`（该路径在
  `PUBLIC_PREFIXES` 里，无需鉴权）
- 验证：探测端口与 `EXPOSE` 一致（8002 / 3002），别沿用 8000/3000

### Step 4: 验证构建
- 操作：
  ```bash
  docker build -t airdrop-backend -f docker/Dockerfile .
  docker build -t airdrop-frontend -f frontend-next/Dockerfile frontend-next
  ```
  再 `docker run` 冒烟
- 验证：容器以非 root 启动，`/health` 返回 200，前端首页可访问

## 输出
- 文件：`docker/Dockerfile` / `frontend-next/Dockerfile`（更新）
- 文件：`.dockerignore`（更新）
- 文件：`docker-compose.prod.yml`（更新）
- 文件：`docs/DEPLOYMENT.md`（如涉及部署步骤变化）

## 检查清单
- [ ] 后端基础镜像 `python:3.12-slim`（不是 3.11）
- [ ] 未引用不存在的 `requirements.lock.txt`
- [ ] 非 root 用户运行（`appuser` / `nextjs`）
- [ ] 端口 8002 / 3002 与健康检查一致
- [ ] `.dockerignore` 排除 `node_modules`/`data`/`logs`/`.next`
- [ ] dev / otel 依赖未混进运行镜像
- [ ] 两个镜像都实际 build 过

## 参考
- `docs/DEPLOYMENT.md`
- `docker/Dockerfile`、`frontend-next/Dockerfile`（关键决策都写在注释里）
- `docker-compose.prod.yml`
- `backend/requirements.txt` 头部说明
