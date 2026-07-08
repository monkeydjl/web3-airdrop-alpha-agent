# Prompt 工程知识

> 分类：技术知识 > Prompt Engineering  
> 更新：2026-07-08

---

## 1. Prompt 设计原则

### 1.1 清晰性（Clarity）

**原则**：明确指令，减少歧义

```json
{
  "bad": "分析这个项目",
  "good": "分析此 Web3 项目的空投潜力，输出 JSON 格式包含：team_score (0-100), tokenomics_score (0-100), reason (字符串)"
}
```

### 1.2 结构化输出（Structured Output）

**原则**：使用 JSON Schema 约束输出

```json
{
  "prompt": "...",
  "output_schema": {
    "type": "object",
    "properties": {
      "score": {"type": "number", "minimum": 0, "maximum": 100},
      "reason": {"type": "string"}
    },
    "required": ["score", "reason"]
  }
}
```

### 1.3 Few-Shot Examples

**原则**：提供 2-3 个高质量示例

```json
{
  "examples": [
    {
      "input": {"twitter_followers": 10000, "github_stars": 500},
      "output": {"score": 75, "reason": "社区活跃，技术实力强"}
    },
    {
      "input": {"twitter_followers": 100, "github_stars": 5},
      "output": {"score": 20, "reason": "社区规模小，技术积累不足"}
    }
  ]
}
```

---

## 2. Prompt 版本管理

### 2.1 语义化版本

格式：`v{major}.{minor}.{patch}`

- **major**：输出格式变更（破坏性）
- **minor**：新增字段（兼容）
- **patch**：措辞优化（兼容）

### 2.2 版本迁移

```python
# prompts/migrations/v1_to_v2.py

def migrate_prompt_v1_to_v2(old_prompt: dict) -> dict:
    """
    v1 → v2 迁移：新增 confidence 字段
    """
    new_prompt = old_prompt.copy()
    new_prompt["output_schema"]["properties"]["confidence"] = {
        "type": "number",
        "minimum": 0,
        "maximum": 1
    }
    return new_prompt
```

---

## 3. Prompt 评估指标

### 3.1 准确性（Accuracy）

**定义**：输出与 Golden Truth 的匹配度

```python
# 评分误差
accuracy = 1 - abs(predicted_score - golden_score) / 100
```

### 3.2 一致性（Consistency）

**定义**：相同输入多次调用，输出的稳定性

```python
# 标准差
consistency = 1 - std(scores) / mean(scores)
```

### 3.3 成本效率（Cost Efficiency）

**定义**：Token 消耗与质量的平衡

```python
# 每分准确度的 Token 消耗
cost_per_accuracy = total_tokens / accuracy_score
```

---

## 4. Prompt 优化技巧

### 4.1 减少 Token 消耗

**技巧**：
- 移除冗余描述
- 使用缩写（在 schema 中定义）
- 压缩示例数量

**示例**：
```json
{
  "before": "Please analyze the following Web3 project and provide a detailed assessment...",
  "after": "Analyze Web3 project. Output: score (0-100), reason (max 100 chars)."
}
```

### 4.2 提升准确性

**技巧**：
- 增加约束条件
- 提供决策树
- 使用 Chain-of-Thought

**示例**：
```json
{
  "prompt": "分析项目空投潜力。思考步骤：\n1. 评估团队背景（20%）\n2. 评估代币经济（30%）\n3. 评估社区活跃度（50%）\n最终输出总分和理由。"
}
```

### 4.3 处理边缘情况

**技巧**：明确指定异常处理逻辑

```json
{
  "edge_cases": [
    "如果 twitter_followers 为 null，使用默认值 0",
    "如果 github_stars < 0，返回 error: 'invalid_input'",
    "如果无法判断，返回 score: null, reason: 'insufficient_data'"
  ]
}
```

---

## 5. Prompt Testing

### 5.1 单元测试

```python
# tests/prompts/test_team_analysis.py

def test_team_prompt_with_high_quality_input():
    """测试高质量输入"""
    input_data = {
        "founders": ["Vitalik Buterin"],
        "advisors": ["Naval Ravikant"],
        "github_commits": 1000
    }
    result = run_prompt("team_analysis_v1", input_data)
    
    assert result["score"] >= 80
    assert "experienced" in result["reason"].lower()
```

### 5.2 Golden Test

```python
# tests/golden/test_prompts.py

GOLDEN_CASES = [
    {
        "input": {...},
        "expected_score": 85,
        "expected_keywords": ["strong", "team", "experienced"]
    }
]

@pytest.mark.parametrize("case", GOLDEN_CASES)
def test_golden_case(case):
    result = run_prompt("team_analysis_v1", case["input"])
    assert abs(result["score"] - case["expected_score"]) <= 5
    assert any(kw in result["reason"].lower() for kw in case["expected_keywords"])
```

### 5.3 Benchmark

```python
# evaluation/llm/prompt_benchmark.py

def benchmark_prompt(prompt_id: str, test_cases: List[dict]) -> dict:
    """
    Benchmark Prompt 性能
    
    Returns:
        {
            "accuracy": 0.85,
            "consistency": 0.92,
            "avg_tokens": 150,
            "avg_latency_ms": 500,
            "cost_per_call": 0.002
        }
    """
    pass
```

---

## 6. Prompt 反馈循环

### 6.1 收集生产反馈

```python
# backend/app/services/prompt_feedback.py

class PromptFeedback:
    """Prompt 反馈收集"""
    
    def log_feedback(
        self,
        prompt_id: str,
        input_data: dict,
        output_data: dict,
        user_feedback: Optional[str] = None,
        is_correct: Optional[bool] = None
    ):
        """记录反馈"""
        feedback = {
            "prompt_id": prompt_id,
            "timestamp": time.time(),
            "input": input_data,
            "output": output_data,
            "user_feedback": user_feedback,
            "is_correct": is_correct
        }
        
        # 存储到数据库
        db.prompt_feedbacks.insert(feedback)
```

### 6.2 定期评审

```bash
# 每周评审 Prompt 性能
python scripts/prompt_review.py --week 2026-W28

# 输出：
# - 准确率趋势
# - 常见失败案例
# - 优化建议
```

---

## 7. 相关文档

- Prompt 管理：`prompts/README.md`
- LLM 评估：`evaluation/llm/template_validation.py`
- ADR-001：LLM 默认关闭策略

---

_文档版本：v1.0 · 2026-07-08_
