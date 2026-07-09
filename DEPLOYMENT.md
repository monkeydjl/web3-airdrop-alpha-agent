# Web3 Airdrop Alpha Agent System - 部署指南

本文档说明如何使用 Docker 部署系统。

## 📋 前置要求

- Docker Engine 20.10+
- Docker Compose 2.0+
- 至少 512MB 可用内存
- 至少 1GB 可用磁盘空间

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/your-org/web3-airdrop-alpha.git
cd web3-airdrop-alpha
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置（可选）
nano .env
```

**关键配置项**:
- `APP_ENV`: 环境（development/staging/production）
- `LOG_LEVEL`: 日志级别（debug/info/warning/error）
- `API_PORT`: API 服务端口（默认 8000）
- `LLM_ENABLED`: 是否启用 LLM（默认 false）

### 3. 启动服务

```bash
# 构建并启动（后台运行）
docker-compose up -d

# 查看日志
docker-compose logs -f backend

# 检查状态
docker-compose ps
```

### 4. 验证部署

```bash
# 健康检查
curl http://localhost:8000/health

# 预期响应: {"ok": true, "status": "healthy"}

# 访问 API 文档
open http://localhost:8000/docs
```

## 📦 部署架构

### 最小部署（开发/测试）

```yaml
services:
  backend:
    - FastAPI 应用
    - SQLite 数据库
    - 端口: 8000
```

```bash
docker-compose up -d
```

### 生产部署（推荐）

```yaml
services:
  backend:
    - FastAPI 应用
    - 数据持久化卷
  nginx:
    - 反向代理
    - 端口: 80
```

```bash
docker-compose --profile production up -d
```

## 🔧 常用命令

### 服务管理

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 重启服务
docker-compose restart backend

# 查看日志
docker-compose logs -f backend

# 进入容器
docker-compose exec backend bash
```

### 数据管理

```bash
# 备份数据库
docker-compose exec backend sqlite3 /app/data/app.db ".backup /app/data/backup.db"
docker cp airdrop-alpha-backend:/app/data/backup.db ./backup-$(date +%Y%m%d).db

# 清理数据（危险操作！）
docker-compose down -v
rm -rf data/ logs/
```

### 镜像管理

```bash
# 重新构建镜像
docker-compose build --no-cache

# 查看镜像大小
docker images | grep airdrop-alpha

# 清理旧镜像
docker image prune -a
```

## 🔍 健康检查

### 容器健康状态

```bash
# 查看健康状态
docker-compose ps

# 健康的容器显示: Up (healthy)
```

### API 健康检查

```bash
# 基础健康检查
curl http://localhost:8000/health

# 详细版本信息
curl http://localhost:8000/version
```

### 数据库检查

```bash
# 进入容器检查数据库
docker-compose exec backend sqlite3 /app/data/app.db

# SQLite 命令
.tables              # 列出所有表
SELECT COUNT(*) FROM projects;  # 查询项目数量
.quit                # 退出
```

## 📊 监控和日志

### 查看日志

```bash
# 实时日志
docker-compose logs -f backend

# 最近 100 行
docker-compose logs --tail=100 backend

# 特定时间范围
docker-compose logs --since 1h backend
```

### 日志位置

- **容器内**: `/app/logs/`
- **主机**: `./logs/` (通过 volume 映射)

### 日志格式

```json
{
  "timestamp": "2026-07-09T12:00:00Z",
  "level": "info",
  "event": "api.request.completed",
  "method": "POST",
  "path": "/api/v1/run",
  "status_code": 200,
  "duration_ms": 15.2
}
```

## 🔒 安全建议

### 生产环境

1. **修改默认密码**
   ```bash
   # 在 .env 中设置强密码
   POSTGRES_PASSWORD=your-strong-password-here
   ```

2. **启用 HTTPS**
   - 使用 Let's Encrypt 或其他证书
   - 配置 Nginx SSL

3. **限制访问**
   - 配置防火墙规则
   - 使用 API Key 认证
   - 启用 Rate Limiting

4. **定期备份**
   ```bash
   # 设置自动备份 cron job
   0 2 * * * /path/to/backup.sh
   ```

### 网络隔离

```bash
# 仅暴露必要端口
# 在 docker-compose.yml 中移除不需要的端口映射
```

## 🐛 故障排查

### 容器无法启动

```bash
# 查看详细日志
docker-compose logs backend

# 检查端口占用
netstat -tlnp | grep 8000

# 检查磁盘空间
df -h
```

### API 无响应

```bash
# 检查容器状态
docker-compose ps

# 检查健康状态
curl http://localhost:8000/health

# 重启容器
docker-compose restart backend
```

### 数据库错误

```bash
# 检查数据库文件
docker-compose exec backend ls -lh /app/data/

# 检查权限
docker-compose exec backend stat /app/data/app.db

# 重新初始化（会丢失数据！）
docker-compose down -v
docker-compose up -d
```

### 内存不足

```bash
# 查看容器资源使用
docker stats airdrop-alpha-backend

# 限制内存使用（在 docker-compose.yml 中）
deploy:
  resources:
    limits:
      memory: 512M
```

## 📈 性能优化

### 资源限制

```yaml
# docker-compose.yml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
```

### 数据库优化

```bash
# SQLite WAL 模式已自动启用
# 定期清理 WAL 文件
docker-compose exec backend sqlite3 /app/data/app.db "PRAGMA wal_checkpoint(FULL);"
```

## 🔄 更新部署

### 更新到新版本

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 备份数据
./scripts/backup.sh  # 如果有备份脚本

# 3. 重新构建并启动
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# 4. 验证
curl http://localhost:8000/health
curl http://localhost:8000/version
```

### 回滚版本

```bash
# 1. 停止当前版本
docker-compose down

# 2. 切换到旧版本
git checkout v0.1.0

# 3. 重新部署
docker-compose up -d
```

## 📞 支持

- **文档**: [ENGINEERING_ROADMAP.md](../docs/ENGINEERING_ROADMAP.md)
- **API 文档**: http://localhost:8000/docs
- **Issues**: https://github.com/your-org/web3-airdrop-alpha/issues

## 📝 附录

### 环境变量完整列表

详见 [.env.example](.env.example)

### Docker Compose 配置说明

详见 [docker-compose.yml](docker-compose.yml)

### Nginx 配置说明

详见 [nginx.conf](nginx.conf)
