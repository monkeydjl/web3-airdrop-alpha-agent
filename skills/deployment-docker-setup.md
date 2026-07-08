# Skill：Docker 构建配置

## 目标
为项目编写/优化 Docker 镜像构建配置，覆盖后端（Python 3.11）与 V2 前端（Next.js），遵循 docs/DEPLOYMENT.md。

## 适用场景
- 新增/修改 `docker/Dockerfile`
- 多阶段构建优化镜像体积
- 调整运行用户/健康检查

## 输入要求
- 文件：`docker/Dockerfile`
- 文件：`docker-compose.prod.yml`
- 文件：`docs/DEPLOYMENT.md`
- 文件：`pyproject.toml`（后端依赖）

## 执行步骤

### Step 1: 后端多阶段构建
- 操作：在 `docker/Dockerfile` 用 `python:3.11-slim` 基础镜像，先装 `requirements.lock.txt` 再拷贝 `backend/`
- 验证：使用非 root 用户运行；`CMD` 启动 `uvicorn app.main:app`

### Step 2: 前端构建（V2）
- 操作：Next.js 单独 stage，`npm ci` + `next build`，产出静态/standalone 产物
- 验证：`.dockerignore` 排除 `node_modules`/`data`/`logs`

### Step 3: 健康检查
- 操作：在 `docker-compose.prod.yml` 配置 `healthcheck` 探测 `/api/v1/...` 或 `/health`
- 验证：健康检查路径存在且返回 200

### Step 4: 验证构建
- 操作：本地 `docker build -t airdrop-backend -f docker/Dockerfile .` 并 `docker run` 冒烟
- 验证：容器以非 root 启动，端口可访问

## 输出
- 文件：`docker/Dockerfile`（更新）
- 文件：`.dockerignore`（更新）
- 文件：`docker-compose.prod.yml`（更新）

## 检查清单
- [ ] 基础镜像 `python:3.11-slim`
- [ ] 非 root 用户运行
- [ ] `.dockerignore` 排除缓存/数据目录
- [ ] 前端使用 `npm ci` 锁定依赖
- [ ] 健康检查配置且路径有效

## 参考
- `docs/DEPLOYMENT.md`
- `docker/Dockerfile`
- `docker-compose.prod.yml`
