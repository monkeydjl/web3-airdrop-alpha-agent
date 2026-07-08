# 工作流自动化脚本 (Workflow Automation Scripts)

> 一键自动化常见开发工作流  
> 更新：2026-07-08

---

## 1. Git 工作流自动化

### 1.1 创建 Feature 分支

```bash
#!/usr/bin/env bash
# scripts/workflows/git-new-feature.sh
# 用法: ./scripts/workflows/git-new-feature.sh "add-user-auth"

set -e

FEATURE_NAME=$1

if [ -z "$FEATURE_NAME" ]; then
  echo "❌ 错误: 请提供 feature 名称"
  echo "用法: $0 <feature-name>"
  exit 1
fi

echo "🔄 从 main 更新..."
git checkout main
git pull origin main

echo "✨ 创建分支: feature/$FEATURE_NAME"
git checkout -b "feature/$FEATURE_NAME"

echo "📝 提交初始骨架..."
git commit --allow-empty -m "feat: 初始化 $FEATURE_NAME"

echo "✅ 完成! 分支已创建: feature/$FEATURE_NAME"
echo "💡 下一步: git push -u origin feature/$FEATURE_NAME"
```

### 1.2 创建 Hotfix 分支

```bash
#!/usr/bin/env bash
# scripts/workflows/git-hotfix.sh
# 用法: ./scripts/workflows/git-hotfix.sh "fix-scoring-bug"

set -e

HOTFIX_NAME=$1

if [ -z "$HOTFIX_NAME" ]; then
  echo "❌ 错误: 请提供 hotfix 名称"
  echo "用法: $0 <hotfix-name>"
  exit 1
fi

echo "🔄 从 main 更新..."
git checkout main
git pull origin main

echo "🚨 创建 hotfix 分支: hotfix/$HOTFIX_NAME"
git checkout -b "hotfix/$HOTFIX_NAME"

echo "✅ 完成! 分支已创建: hotfix/$HOTFIX_NAME"
echo "💡 修复后使用: ./scripts/workflows/git-hotfix-merge.sh $HOTFIX_NAME"
```

### 1.3 Hotfix 合并流程

```bash
#!/usr/bin/env bash
# scripts/workflows/git-hotfix-merge.sh
# 用法: ./scripts/workflows/git-hotfix-merge.sh "fix-scoring-bug"

set -e

HOTFIX_NAME=$1

if [ -z "$HOTFIX_NAME" ]; then
  echo "❌ 错误: 请提供 hotfix 名称"
  exit 1
fi

BRANCH="hotfix/$HOTFIX_NAME"

echo "🔍 检查分支: $BRANCH"
git checkout "$BRANCH"

echo "🧪 运行测试..."
make test

echo "✅ 测试通过"
echo "🔄 合并到 main..."
git checkout main
git merge --no-ff "$BRANCH" -m "Merge $BRANCH"

echo "🏷️  创建 tag..."
CURRENT_VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
PATCH_VERSION=$(echo "$CURRENT_VERSION" | awk -F. '{print $1"."$2"."$3+1}')
git tag -a "$PATCH_VERSION" -m "Hotfix: $HOTFIX_NAME"

echo "📤 推送..."
git push origin main --tags

echo "🗑️  删除本地分支..."
git branch -d "$BRANCH"

echo "✅ Hotfix 完成! 版本: $PATCH_VERSION"
```

---

## 2. 发布工作流

### 2.1 准备发布

```bash
#!/usr/bin/env bash
# scripts/workflows/release-prepare.sh
# 用法: ./scripts/workflows/release-prepare.sh "1.2.0"

set -e

VERSION=$1

if [ -z "$VERSION" ]; then
  echo "❌ 错误: 请提供版本号"
  echo "用法: $0 <version> (如 1.2.0)"
  exit 1
fi

echo "📋 准备发布 v$VERSION..."

# 1. 创建 release 分支
git checkout -b "release/$VERSION"

# 2. 更新版本号
echo "$VERSION" > VERSION
sed -i "s/version = \".*\"/version = \"$VERSION\"/" pyproject.toml

# 3. 更新 CHANGELOG
DATE=$(date +%Y-%m-%d)
sed -i "s/## \[Unreleased\]/## [Unreleased]\n\n## [$VERSION] - $DATE/" CHANGELOG.md

# 4. 提交
git add VERSION pyproject.toml CHANGELOG.md
git commit -m "chore: 准备发布 v$VERSION"

echo "✅ Release 分支已创建: release/$VERSION"
echo "💡 下一步:"
echo "   1. 运行 make test"
echo "   2. 推送: git push -u origin release/$VERSION"
echo "   3. 创建 PR 到 main"
```

### 2.2 完成发布

```bash
#!/usr/bin/env bash
# scripts/workflows/release-finish.sh
# 用法: ./scripts/workflows/release-finish.sh "1.2.0"

set -e

VERSION=$1

if [ -z "$VERSION" ]; then
  echo "❌ 错误: 请提供版本号"
  exit 1
fi

BRANCH="release/$VERSION"

echo "🔍 检查分支: $BRANCH"
git checkout "$BRANCH"

echo "🧪 最终测试..."
make test
make lint
make typecheck

echo "✅ 所有检查通过"

echo "🔄 合并到 main..."
git checkout main
git merge --no-ff "$BRANCH" -m "Release v$VERSION"

echo "🏷️  创建 tag..."
git tag -a "v$VERSION" -m "Release v$VERSION"

echo "📤 推送..."
git push origin main --tags

echo "🗑️  删除 release 分支..."
git branch -d "$BRANCH"
git push origin --delete "$BRANCH" 2>/dev/null || true

echo "✅ 发布完成! 版本: v$VERSION"
echo "🎉 GitHub Release 将自动创建"
```

---

## 3. 开发工作流

### 3.1 完整开发循环

```bash
#!/usr/bin/env bash
# scripts/workflows/dev-cycle.sh
# 用法: ./scripts/workflows/dev-cycle.sh

set -e

echo "🔄 运行完整开发循环..."

echo "1️⃣  安装依赖..."
make setup

echo "2️⃣  格式化代码..."
make format

echo "3️⃣  代码检查..."
make lint

echo "4️⃣  类型检查..."
make typecheck

echo "5️⃣  运行测试..."
make test

echo "6️⃣  生成覆盖率报告..."
make coverage

echo "✅ 开发循环完成!"
echo "📊 覆盖率报告: htmlcov/index.html"
```

### 3.2 快速验证（Pre-commit）

```bash
#!/usr/bin/env bash
# scripts/workflows/quick-check.sh
# 用法: ./scripts/workflows/quick-check.sh

set -e

echo "⚡ 快速验证..."

# 只检查暂存文件
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)

if [ -z "$STAGED_FILES" ]; then
  echo "✅ 无 Python 文件变更"
  exit 0
fi

echo "📝 检查文件:"
echo "$STAGED_FILES"

echo "1️⃣  格式化..."
ruff format $STAGED_FILES

echo "2️⃣  Lint..."
ruff check --fix $STAGED_FILES

echo "3️⃣  类型检查..."
mypy $STAGED_FILES

echo "4️⃣  运行相关测试..."
pytest --lf --ff

echo "✅ 验证通过!"
```

---

## 4. Agent 工作流

### 4.1 创建新 Agent

```bash
#!/usr/bin/env bash
# scripts/workflows/agent-create.sh
# 用法: ./scripts/workflows/agent-create.sh "sentiment" "Sentiment Analyzer"

set -e

AGENT_ID=$1
AGENT_NAME=$2

if [ -z "$AGENT_ID" ] || [ -z "$AGENT_NAME" ]; then
  echo "❌ 错误: 缺少参数"
  echo "用法: $0 <agent-id> <agent-name>"
  echo "示例: $0 sentiment 'Sentiment Analyzer'"
  exit 1
fi

AGENT_DIR="agents/$AGENT_ID"

echo "✨ 创建 Agent: $AGENT_NAME"

# 1. 创建目录
mkdir -p "$AGENT_DIR"

# 2. 生成 AGENT.md
cat > "$AGENT_DIR/AGENT.md" << EOF
# $AGENT_NAME Agent

> Agent ID: \`$AGENT_ID\`  
> 版本: v1.0  
> 创建: $(date +%Y-%m-%d)

---

## 职责

描述此 Agent 的核心职责...

---

## 输入

\`\`\`python
class ${AGENT_NAME}Input(BaseModel):
    # TODO: 定义输入模型
    pass
\`\`\`

---

## 输出

\`\`\`python
class ${AGENT_NAME}Output(BaseModel):
    # TODO: 定义输出模型
    pass
\`\`\`

---

## 实现

实现文件: \`backend/app/agents/${AGENT_ID}.py\`

---

## 限制

- TODO: 列出限制

---

## 工具依赖

- TODO: 列出外部依赖

---

## 测试

测试文件: \`tests/unit/agents/test_${AGENT_ID}.py\`

---

_文档版本: v1.0 · $(date +%Y-%m-%d)_
EOF

# 3. 生成实现骨架
mkdir -p "backend/app/agents"
cat > "backend/app/agents/${AGENT_ID}.py" << EOF
"""
$AGENT_NAME Agent
"""

from typing import Any, Dict
from pydantic import BaseModel

class ${AGENT_NAME}Input(BaseModel):
    """Agent 输入"""
    pass

class ${AGENT_NAME}Output(BaseModel):
    """Agent 输出"""
    pass

class ${AGENT_NAME}Agent:
    """$AGENT_NAME Agent 实现"""
    
    def __init__(self):
        pass
    
    async def run(self, input_data: ${AGENT_NAME}Input) -> ${AGENT_NAME}Output:
        """执行 Agent 逻辑"""
        # TODO: 实现逻辑
        raise NotImplementedError
EOF

# 4. 生成测试骨架
mkdir -p "tests/unit/agents"
cat > "tests/unit/agents/test_${AGENT_ID}.py" << EOF
"""
$AGENT_NAME Agent 测试
"""

import pytest
from backend.app.agents.${AGENT_ID} import ${AGENT_NAME}Agent, ${AGENT_NAME}Input

@pytest.fixture
def agent():
    return ${AGENT_NAME}Agent()

@pytest.mark.asyncio
async def test_agent_run(agent):
    """测试 Agent 基本运行"""
    # TODO: 实现测试
    pass
EOF

echo "✅ Agent 创建完成!"
echo "📁 文档: $AGENT_DIR/AGENT.md"
echo "💻 代码: backend/app/agents/${AGENT_ID}.py"
echo "🧪 测试: tests/unit/agents/test_${AGENT_ID}.py"
echo "💡 下一步: 编辑 AGENT.md 完善定义"
```

---

## 5. 文档工作流

### 5.1 文档链接检查

```bash
#!/usr/bin/env bash
# scripts/workflows/docs-check.sh

set -e

echo "📚 检查文档链接..."

# 使用 markdown-link-check
find docs -name "*.md" | while read file; do
  echo "🔍 检查: $file"
  markdown-link-check "$file" --config .github/markdown-link-check.json
done

echo "✅ 所有链接有效"
```

### 5.2 生成文档索引

```bash
#!/usr/bin/env bash
# scripts/workflows/docs-index.sh

set -e

echo "📑 生成文档索引..."

cat > docs/INDEX.md << 'EOF'
# 文档索引

> 自动生成 · $(date +%Y-%m-%d)

---

## 核心文档

EOF

# 添加核心文档
find docs -maxdepth 1 -name "*.md" ! -name "INDEX.md" | sort | while read file; do
  filename=$(basename "$file")
  title=$(grep -m 1 "^# " "$file" | sed 's/# //')
  echo "- [$title]($filename)" >> docs/INDEX.md
done

cat >> docs/INDEX.md << 'EOF'

---

## ADR (架构决策)

EOF

# 添加 ADR
find docs/adr -name "ADR-*.md" | sort | while read file; do
  filename=$(basename "$file")
  title=$(grep -m 1 "^# " "$file" | sed 's/# //')
  echo "- [$title](adr/$filename)" >> docs/INDEX.md
done

echo "✅ 索引生成: docs/INDEX.md"
```

---

## 6. 数据库工作流

### 6.1 数据库备份

```bash
#!/usr/bin/env bash
# scripts/workflows/db-backup.sh

set -e

DB_PATH="${DB_PATH:-data/airdrop.db}"
BACKUP_DIR="backups/$(date +%Y-%m)"
BACKUP_FILE="$BACKUP_DIR/airdrop_$(date +%Y%m%d_%H%M%S).db"

echo "💾 备份数据库..."

mkdir -p "$BACKUP_DIR"

if [ -f "$DB_PATH" ]; then
  cp "$DB_PATH" "$BACKUP_FILE"
  gzip "$BACKUP_FILE"
  echo "✅ 备份完成: $BACKUP_FILE.gz"
  
  # 保留最近 7 天的备份
  find "$BACKUP_DIR" -name "*.db.gz" -mtime +7 -delete
  echo "🗑️  清理旧备份"
else
  echo "⚠️  数据库文件不存在: $DB_PATH"
fi
```

### 6.2 数据库迁移验证

```bash
#!/usr/bin/env bash
# scripts/workflows/db-migrate-check.sh

set -e

echo "🔍 验证数据库迁移..."

# 1. 备份当前数据库
./scripts/workflows/db-backup.sh

# 2. 运行迁移（模拟）
echo "🔄 模拟迁移..."
# TODO: 实际迁移逻辑

# 3. 验证表结构
echo "📋 检查表结构..."
sqlite3 data/airdrop.db ".schema" > /tmp/schema_after.sql

# 4. 运行测试
echo "🧪 运行测试..."
make test

echo "✅ 迁移验证完成"
```

---

## 使用说明

### 安装脚本

```bash
# 赋予执行权限
chmod +x scripts/workflows/*.sh

# 添加到 PATH（可选）
export PATH="$PATH:$(pwd)/scripts/workflows"
```

### 集成到 Makefile

```makefile
# Makefile 中添加

.PHONY: workflow-feature
workflow-feature:
	@./scripts/workflows/git-new-feature.sh $(name)

.PHONY: workflow-release
workflow-release:
	@./scripts/workflows/release-prepare.sh $(version)
```

---

_文档版本：v1.0 · 2026-07-08_
