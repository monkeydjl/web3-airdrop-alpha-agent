# Golden Test 用例清单

> 配套文档：ENGINEERING_ROADMAP.md §14.6、DATA_SCORING_DICT.md §12。本文档定义评分回归测试的**黄金用例**，用于验证评分算法正确性、检测权重/规则变更是否引入回归。
>
> 适用阶段：每次评分逻辑变更、权重校准、LLM 策略调整后必须跑全量 golden 测试。

---

## 1. 设计原则

1. **确定性**：每个用例输入固定，输出预期值固定（无随机性）。
2. **覆盖关键路径**：覆盖各 label 边界、缺失字段降级、LLM 回退等场景。
3. **可回归**：权重/规则变更后，跑全量用例，对比预期输出。
4. **版本化**：golden 集随系统版本迭代，新增用例需评审。

---

## 2. 用例格式

```python
{
    "id": "GT-001",                    # 用例唯一 ID
    "name": "双信号强叙事项目",          # 用例名称
    "description": "验证强空投信号+早期叙事产出 FARM",
    "input": { ... },                  # Agent 输入（对齐 DATA_SCORING_DICT §3）
    "expected": {                      # 预期输出
        "score": 85,
        "label": "FARM",
        "confidence": 1.0,
        "reason_contains": ["strong airdrop signal", "early narrative"]  # 实际 reason 列表必须包含其中所有字符串，且长度 ≥ 2
    },
    "tags": ["farm", "full-data", "happy-path"]
}
```

---

## 3. Golden 用例清单

### 3.1 Happy Path（全数据）

#### GT-001：双信号强叙事项目 → FARM
```python
{
    "id": "GT-001",
    "name": "双信号强叙事项目",
    "description": "强空投信号 + 早期叙事 + 知名团队 → FARM",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.82, "timing": "early"},
        "team": {"score": 0.85, "risk_level": "low", "flags": []},
        "risk": {"token_risk": 0.2, "sybil_difficulty": "low", "farming_cost": "low"},
        "tokenomics": {"vc_share": 0.1, "team_share": 0.15, "unlock_pressure": "low", "risk": 0.2},
        "competition_n": 3
    },
    "expected": {
        "score": 85,
        "label": "FARM",
        "confidence": 1.0,
        "reason_contains": ["strong airdrop signal", "low competition", "credible team"]
    },
    "tags": ["farm", "full-data", "happy-path"]
}
```

#### GT-002：中等信号成熟赛道 → WATCH
```python
{
    "id": "GT-002",
    "name": "中等信号成熟赛道",
    "description": "中等空投信号 + 成熟赛道 + 匿名团队 → WATCH",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": False},
        "narrative": {"sector": "DeFi", "stage": "mature", "heat_score": 0.45, "timing": "late"},
        "team": {"score": 0.4, "risk_level": "high", "flags": ["anonymous team"]},
        "risk": {"token_risk": 0.6, "sybil_difficulty": "medium", "farming_cost": "medium"},
        "tokenomics": {"vc_share": 0.3, "team_share": 0.25, "unlock_pressure": "high", "risk": 0.7},
        "competition_n": 15
    },
    "expected": {
        "score": 40,
        "label": "IGNORE",
        "confidence": 1.0,
        "reason_contains": ["team risk: anonymous or prior failure", "late narrative", "high token unlock pressure"]
    },
    "tags": ["ignore", "full-data", "happy-path"]
}
```

#### GT-003：LayerX 示例（对齐 DATA_SCORING_DICT §12）
```python
{
    "id": "GT-003",
    "name": "LayerX 标准示例",
    "description": "对齐 DATA_SCORING_DICT §12 的 LayerX 计算示例",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.82, "timing": "early"},
        "team": {"score": 0.72, "risk_level": "medium", "flags": []},
        "risk": {"token_risk": 0.68, "sybil_difficulty": "high", "farming_cost": "medium"},
        "tokenomics": {"vc_share": 0.25, "team_share": 0.2, "unlock_pressure": "high", "risk": 0.75},
        "competition_n": 4
    },
    "expected": {
        "score": 67,
        "label": "WATCH",
        "confidence": 1.0,
        "reason_contains": ["strong airdrop signal", "early narrative, high heat", "high token unlock pressure"]
    },
    "tags": ["watch", "full-data", "canonical-example"]
}
```

---

### 3.2 边界值测试

#### GT-004：FARM 下边界（score=70）
```python
{
    "id": "GT-004",
    "name": "FARM 下边界",
    "description": "score 恰好 70 → FARM（边界包含）",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.7, "timing": "early"},
        "team": {"score": 0.7, "risk_level": "low", "flags": []},
        "risk": {"token_risk": 0.3, "sybil_difficulty": "low", "farming_cost": "low"},
        "tokenomics": {"vc_share": 0.15, "team_share": 0.15, "unlock_pressure": "low", "risk": 0.3},
        "competition_n": 5
    },
        "expected": {
            "score": 74,
            "label": "FARM",
            "confidence": 1.0,
            "reason_contains": ["strong airdrop signal", "early narrative, high heat", "credible team"]
        },
        "tags": ["farm", "boundary", "full-data"]
    }
}
```

#### GT-005：WATCH 下边界（score=50）
```python
{
    "id": "GT-005",
    "name": "WATCH 下边界",
    "description": "score 恰好 50 → WATCH（边界包含）",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": False},
        "narrative": {"sector": "DeFi", "stage": "peak", "heat_score": 0.5, "timing": "peak"},
        "team": {"score": 0.5, "risk_level": "medium", "flags": []},
        "risk": {"token_risk": 0.5, "sybil_difficulty": "medium", "farming_cost": "medium"},
        "tokenomics": {"vc_share": 0.2, "team_share": 0.2, "unlock_pressure": "medium", "risk": 0.5},
        "competition_n": 8
    },
        "expected": {
            "score": 53,
            "label": "WATCH",
            "confidence": 1.0,
            "reason_contains": ["moderate airdrop signal", "peak narrative"]
        },
        "tags": ["watch", "boundary", "full-data"]
    }
}
```

#### GT-006：WATCH 上边界（score=69）
```python
{
    "id": "GT-006",
    "name": "WATCH 上边界",
    "description": "score 恰好 69 → WATCH（FARM 边界前）",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.65, "timing": "early"},
        "team": {"score": 0.65, "risk_level": "medium", "flags": []},
        "risk": {"token_risk": 0.45, "sybil_difficulty": "medium", "farming_cost": "medium"},
        "tokenomics": {"vc_share": 0.2, "team_share": 0.2, "unlock_pressure": "medium", "risk": 0.55},
        "competition_n": 6
    },
        "expected": {
            "score": 68,
            "label": "WATCH",
            "confidence": 1.0,
            "reason_contains": ["strong airdrop signal", "early narrative"]
        },
        "tags": ["watch", "boundary", "full-data"]
    }
}
```

#### GT-007：IGNORE 上边界（score=49）
```python
{
    "id": "GT-007",
    "name": "IGNORE 上边界",
    "description": "score 恰好 49 → IGNORE（WATCH 边界前）",
    "input": {
        "raw_signals": {"has_points": False, "airdrop_hint": False},
        "narrative": {"sector": "DeFi", "stage": "mature", "heat_score": 0.3, "timing": "late"},
        "team": {"score": 0.3, "risk_level": "high", "flags": ["anonymous team"]},
        "risk": {"token_risk": 0.8, "sybil_difficulty": "low", "farming_cost": "high"},
        "tokenomics": {"vc_share": 0.4, "team_share": 0.3, "unlock_pressure": "high", "risk": 0.85},
        "competition_n": 20
    },
        "expected": {
            "score": 22,
            "label": "IGNORE",
            "confidence": 1.0,
            "reason_contains": ["team risk: anonymous or prior failure", "elevated token structure risk", "late narrative"]
        },
        "tags": ["ignore", "boundary", "full-data"]
    }
}
```

---

### 3.3 缺失字段降级

#### GT-008：Tokenomics 缺失
```python
{
    "id": "GT-008",
    "name": "Tokenomics 缺失",
    "description": "tokenomics_json 为空 → 子分=50，reason 标记缺失",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.8, "timing": "early"},
        "team": {"score": 0.8, "risk_level": "low", "flags": []},
        "risk": {"token_risk": 0.3, "sybil_difficulty": "low", "farming_cost": "low"},
        "tokenomics": None,  # 缺失
        "competition_n": 4
    },
        "expected": {
            "score": 74,
            "label": "FARM",
            "confidence": 0.75,  # 3/4 agent 成功
            "reason_contains": ["tokenomics data missing", "strong airdrop signal", "early narrative, high heat", "credible team"]
        },
        "tags": ["farm", "missing-data", "degradation"]
    }
}
```

#### GT-009：Team + Tokenomics 双缺失
```python
{
    "id": "GT-009",
    "name": "Team + Tokenomics 双缺失",
    "description": "两个分析 agent 缺失 → confidence=0.5；降级条件为 ≥3 缺失，故本例不降级（仍 FARM）",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.85, "timing": "early"},
        "team": None,         # 缺失
        "risk": {"token_risk": 0.25, "sybil_difficulty": "low", "farming_cost": "low"},
        "tokenomics": None,   # 缺失
        "competition_n": 3
    },
    "expected": {
        "score": 75,
        "label": "FARM",  # 双缺失未达 ≥3 降级阈值，保持 FARM
        "confidence": 0.5,  # 2/4 agent 成功
        "reason_contains": ["team data missing", "tokenomics data missing", "strong airdrop signal", "low competition", "early narrative, high heat"]
    },
    "tags": ["farm", "missing-data", "degradation"]
}
```

#### GT-010：三 agent 缺失（强制降级）
```python
{
    "id": "GT-010",
    "name": "三 agent 缺失",
    "description": "≥3 个分析 agent 缺失 → label 强制降一档",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": None,    # 缺失
        "team": None,         # 缺失
        "risk": {"token_risk": 0.5, "sybil_difficulty": "medium", "farming_cost": "medium"},
        "tokenomics": None,   # 缺失
        "competition_n": 5
    },
    "expected": {
        "score": 63,
        "label": "IGNORE",  # ≥3 缺失强制降级（本例分数 63 原即 IGNORE，降级不改变 label）
        "confidence": 0.25,  # 1/4 agent 成功
        "reason_contains": ["narrative heat unknown", "team data missing", "tokenomics data missing", "low data confidence", "strong airdrop signal"]
    },
    "tags": ["ignore", "missing-data", "degradation", "label-downgrade"]
}
```

#### GT-011：全缺失（仅 raw_signals）
```python
{
    "id": "GT-011",
    "name": "全分析 agent 缺失",
    "description": "仅 raw_signals，所有分析 agent 缺失 → 最低 confidence",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": False},
        "narrative": None,
        "team": None,
        "risk": None,
        "tokenomics": None,
        "competition_n": 0
    },
        "expected": {
            "score": 58,
            "label": "IGNORE",
            "confidence": 0.0,  # 0/4 agent 成功
            "reason_contains": ["narrative heat unknown", "team data missing", "risk estimate uncertain", "tokenomics data missing", "low data confidence", "low competition", "moderate airdrop signal"]
        },
        "tags": ["ignore", "missing-data", "degradation", "edge-case"]
    }
}
```

---

### 3.4 特殊场景

#### GT-012：空投信号双假
```python
{
    "id": "GT-012",
    "name": "空投信号双假",
    "description": "has_points=False + airdrop_hint=False → airdrop_signal 子分=0",
    "input": {
        "raw_signals": {"has_points": False, "airdrop_hint": False},
        "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.9, "timing": "early"},
        "team": {"score": 0.9, "risk_level": "low", "flags": []},
        "risk": {"token_risk": 0.1, "sybil_difficulty": "low", "farming_cost": "low"},
        "tokenomics": {"vc_share": 0.05, "team_share": 0.1, "unlock_pressure": "low", "risk": 0.1},
        "competition_n": 2
    },
        "expected": {
            "score": 73,
            "label": "FARM",
            "confidence": 1.0,
            "reason_contains": ["low competition", "early narrative, high heat", "credible team"]
        },
        "tags": ["farm", "full-data", "edge-case"]
    }
}
```

#### GT-013：高竞争赛道
```python
{
    "id": "GT-013",
    "name": "高竞争赛道",
    "description": "competition_n > 20 → competition 子分=0",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "DeFi", "stage": "peak", "heat_score": 0.95, "timing": "peak"},
        "team": {"score": 0.8, "risk_level": "low", "flags": []},
        "risk": {"token_risk": 0.3, "sybil_difficulty": "high", "farming_cost": "low"},
        "tokenomics": {"vc_share": 0.1, "team_share": 0.15, "unlock_pressure": "low", "risk": 0.2},
        "competition_n": 25
    },
        "expected": {
            "score": 76,
            "label": "FARM",
            "confidence": 1.0,
            "reason_contains": ["strong airdrop signal", "credible team", "heated narrative, peak timing"]
        },
        "tags": ["farm", "full-data", "edge-case"]
    }
}
```

#### GT-014：零竞争（全新赛道）
```python
{
    "id": "GT-014",
    "name": "零竞争新赛道",
    "description": "competition_n = 0 → competition 子分=100",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "NewSector", "stage": "early", "heat_score": 0.6, "timing": "early"},
        "team": {"score": 0.7, "risk_level": "medium", "flags": []},
        "risk": {"token_risk": 0.4, "sybil_difficulty": "medium", "farming_cost": "low"},
        "tokenomics": {"vc_share": 0.15, "team_share": 0.15, "unlock_pressure": "low", "risk": 0.3},
        "competition_n": 0
    },
        "expected": {
            "score": 76,
            "label": "FARM",
            "confidence": 1.0,
            "reason_contains": ["strong airdrop signal", "low competition", "credible team"]
        },
        "tags": ["farm", "full-data", "edge-case"]
    }
}
```

#### GT-015：极端风险（token_risk=1.0）
```python
{
    "id": "GT-015",
    "name": "极端风险项目",
    "description": "token_risk=1.0 + unlock_pressure=high → risk 子分极低",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.8, "timing": "early"},
        "team": {"score": 0.6, "risk_level": "medium", "flags": []},
        "risk": {"token_risk": 1.0, "sybil_difficulty": "high", "farming_cost": "high"},
        "tokenomics": {"vc_share": 0.5, "team_share": 0.3, "unlock_pressure": "high", "risk": 0.95},
        "competition_n": 5
    },
        "expected": {
            "score": 57,
            "label": "WATCH",
            "confidence": 1.0,
            "reason_contains": ["strong airdrop signal", "elevated token structure risk", "high token unlock pressure"]
        },
        "tags": ["watch", "full-data", "edge-case"]
    }
}
```

---

### 3.5 LLM 回退场景

#### GT-016：LLM 回退规则引擎
```python
{
    "id": "GT-016",
    "name": "LLM 超时回退",
    "description": "LLM 调用超时 → 回退规则引擎结果，不中断 pipeline",
    "input": {
        "raw_signals": {"has_points": True, "airdrop_hint": True},
        "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.75, "timing": "early"},
        "team": {"score": 0.7, "risk_level": "low", "flags": []},
        "risk": {"token_risk": 0.35, "sybil_difficulty": "medium", "farming_cost": "low"},
        "tokenomics": {"vc_share": 0.15, "team_share": 0.15, "unlock_pressure": "low", "risk": 0.3},
        "competition_n": 4,
        "llm_enabled": True,
        "llm_should_fail": True  # 模拟 LLM 失败
    },
    "expected": {
        "score": 76,
        "label": "FARM",
        "confidence": 1.0,
        "reason_contains": ["strong airdrop signal", "early narrative, high heat", "credible team"],
        "llm_fallback_count": 1  # 至少 1 次 LLM 回退
    },
    "tags": ["farm", "full-data", "llm-fallback"]
}
```

---

## 4. 运行方式

### 4.1 本地运行
```bash
pytest tests/golden/ -v --tb=short
```

### 4.2 CI 集成
```yaml
# .github/workflows/golden.yml
name: Golden Tests
on: [push, pull_request]
jobs:
  golden:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r backend/requirements.txt
      - run: pytest tests/golden/ -v --junitxml=reports/golden.xml
```

### 4.3 输出格式
```xml
<!-- reports/golden.xml -->
<testsuite name="golden" tests="16" failures="0" errors="0">
    <testcase name="GT-001" classname="golden.happy_path"/>
    <testcase name="GT-002" classname="golden.happy_path"/>
    ...
</testsuite>
```

---

## 5. 用例维护规则

| 规则 | 说明 |
|---|---|
| 新增用例 | 功能变更时同步新增，需 code review |
| 修改预期值 | 仅当评分逻辑有意变更时，需 ADR + 全量回归 |
| 删除用例 | 禁止删除历史用例（保留归档），可标记 `deprecated` |
| 版本标签 | 每个用例标注 `since: v1.0`，便于追溯 |

---

## 6. 用例统计

| 类别 | 数量 | 用例 ID |
|---|---|---|
| Happy Path | 3 | GT-001, GT-002, GT-003 |
| 边界值 | 4 | GT-004, GT-005, GT-006, GT-007 |
| 缺失降级 | 4 | GT-008, GT-009, GT-010, GT-011 |
| 特殊场景 | 4 | GT-012, GT-013, GT-014, GT-015 |
| LLM 回退 | 1 | GT-016 |
| **合计** | **16** | — |

---

_文档版本：v1.2 · 2026-07-08 修正：按 DATA_SCORING_DICT.md §5/§12 公式重算全部用例 `expected`（`expected.score` 原值与公式不一致，已修正 GT-002/004/005/006/007/008/009/010/011/012/013/014/015；GT-009 双缺失不触发降级，label 改回 FARM；修正 reason 与评分依据的自洽性）。**v1.2 新增**：按 `DATA_SCORING_DICT.md §8` 的完整 reason 生成表统一修订全部 `reason_contains`；GT-002 修正 `team.risk_level` 为 `high`（与 `team.score=0.4` 推导一致）；GT-016 补齐 LLM 回退后的 reason。配套 ENGINEERING_ROADMAP.md §14.6 · 实现阶段同步落地测试代码。_
