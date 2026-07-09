# Frontend - 简单测试界面

简单的单页面测试界面，用于快速验证系统功能。

## 功能

- ✅ 单项目评分测试
- ✅ 项目列表查看
- ✅ 批量导入（Excel/CSV）
- ✅ 数据导出（Excel/CSV）

## 使用方法

### 方式 1: 直接打开（推荐用于测试）

```bash
# 在浏览器中打开
open frontend/index.html
# 或
start frontend/index.html
```

**注意**: 需要先启动后端 API 服务：
```bash
cd backend
uvicorn app.main:app --reload
```

### 方式 2: 使用本地服务器（推荐用于开发）

```bash
# Python 自带的 HTTP 服务器
cd frontend
python -m http.server 3000

# 访问
open http://localhost:3000
```

### 方式 3: Docker 部署（生产环境）

在 `docker-compose.yml` 中添加前端服务（未来实现）。

## 界面说明

### 1. 评分测试

- 填写项目信息（名称、URL、赛道、阶段）
- 勾选空投信号（测试网、积分计划等）
- 点击"开始评分"
- 查看评分结果和详细分析

### 2. 项目列表

- 查看所有已评分的项目
- 按标签筛选（FARM/WATCH/IGNORE）
- 显示分数、标签、赛道信息
- 颜色标记（绿色=FARM，黄色=WATCH，红色=IGNORE）

### 3. 批量导入

- 下载导入模板
- 填写项目数据
- 上传 Excel 或 CSV 文件
- 自动评分并显示结果

### 4. 导出数据

- 选择导出格式（Excel/CSV）
- 选择筛选条件（全部/FARM/WATCH/IGNORE）
- 点击导出下载文件

## CORS 配置

如果遇到 CORS 错误，需要在后端配置中允许前端域名：

```python
# backend/app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "file://"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 未来增强版本

当前版本是简单测试界面。未来完整版本将包括：

- ✨ React + TypeScript
- ✨ 完整的组件库
- ✨ 图表可视化
- ✨ 响应式设计
- ✨ 深色模式
- ✨ 用户认证
- ✨ 实时更新
- ✨ 高级筛选

## 截图

（待添加）

## 技术栈

- 纯 HTML/CSS/JavaScript
- 原生 Fetch API
- 无依赖
- 轻量级（< 10KB）
