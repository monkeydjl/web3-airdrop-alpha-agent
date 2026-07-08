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
