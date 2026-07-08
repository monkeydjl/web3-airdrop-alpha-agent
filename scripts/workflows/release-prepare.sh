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
