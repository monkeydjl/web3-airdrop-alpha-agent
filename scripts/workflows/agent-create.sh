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
        raise NotImplementedError("${AGENT_NAME}Agent.run() 未实现")
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
