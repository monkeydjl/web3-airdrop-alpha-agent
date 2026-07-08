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
