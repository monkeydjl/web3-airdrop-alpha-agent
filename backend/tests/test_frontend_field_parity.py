"""前端读取的字段名必须真的存在于后端响应里。

## 为什么需要这个测试

项目详情页把「四路分析」结果摊开显示，读法形如 `team.risk_level`、
`risk.farming_cost`、`tokenomics.unlock_pressure`。这些键名没有任何机制保证
存在——读到不存在的键在 TypeScript 里不报错，`?? ''` 兜底之后页面只会显示
「—」或「无」。**一个永远显示「无」的字段看起来像"这个项目没有标记"，
而不是"我读错了键名"**，所以肉眼极难发现。

实测抓到三处（均已修复，本测试是防复发的锁）：

| 前端读法 | 真相 |
|---|---|
| `team.flags` | 后端字段叫 `team_flags`，`flags` 从不出现 → Flags 永远显示「无」 |
| `team.risk_level` | 后端算了但只打日志，没有字段承载 → 风险档永远空白 |
| `risk.farming_cost` | 同上，`assess_farming_cost()` 的结果只进日志 |
| `tokenomics.unlock_pressure` | 该键只在 `risk` 块，tokenomics 里只有 `unlock_penalty` |

## 做法

从 TSX 里抓出所有 `<block>.<key>` 形式的成员访问（block ∈ narrative/team/
risk/tokenomics，这四个局部变量都直接来自 `GET /projects/{id}` 的同名块），
再与后端对应 Pydantic 模型 `model_dump()` 的键集合比对。

解析器找不到目标时**显式失败**而不是返回空集合——空集合会让断言假通过。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models import NarrativeResult, RiskResult, TeamResult, TokenomicsResult

REPO_ROOT = Path(__file__).resolve().parents[2]
DETAIL_PAGE = REPO_ROOT / "frontend-next" / "app" / "project" / "[id]" / "page.tsx"

# 前端局部变量名 → 提供该块的后端模型实例（用合法的最小值构造）
BLOCK_MODELS = {
    "narrative": NarrativeResult(sector="defi", stage="early", heat_score=0.5, timing="early"),
    "team": TeamResult(team_score=0.5, team_type="unknown"),
    "risk": RiskResult(token_risk=0.5, unlock_pressure="medium"),
    "tokenomics": TokenomicsResult(vc_share=0.2, team_share=0.2, unlock_penalty=0.2),
}

# 显式豁免：这些键前端确实会读，但不是模型字段。
# 逐条写出原因，避免"加个豁免让测试变绿"成为默认动作。
ALLOWED_EXTRA = {
    # 兼容旧形状的次选读法，紧跟在正确键名之后，取不到就退回 []
    ("team", "flags"),
    # 兼容旧形状：早期落库用的是 `score`，现字段名为 `team_score`
    ("team", "score"),
    # 次选兜底：unlock_pressure 真值在 risk 块，这里只作兼容读取
    ("tokenomics", "unlock_pressure"),
}


def _source() -> str:
    if not DETAIL_PAGE.is_file():
        pytest.skip(f"前端源文件不存在（可能是仅后端的检出）：{DETAIL_PAGE}")
    return DETAIL_PAGE.read_text(encoding="utf-8")


def _member_accesses(src: str, block: str) -> set[str]:
    """抓出 `<block>.<key>` 形式的成员访问（不含方法调用）。"""
    hits = set(re.findall(rf"\b{re.escape(block)}\.([A-Za-z_]\w*)", src))
    # 排除数组/对象自带的方法与属性，它们不是数据字段
    return hits - {"length", "map", "filter", "join", "slice", "toFixed"}


class TestDetailPageFieldsExist:
    @pytest.mark.parametrize("block", sorted(BLOCK_MODELS))
    def test_every_read_key_exists_in_backend_model(self, block: str) -> None:
        model_keys = set(BLOCK_MODELS[block].model_dump().keys())
        read_keys = _member_accesses(_source(), block)
        assert read_keys, (
            f"没在详情页里找到任何 `{block}.xxx` 读法 —— 写法变了，请更新本测试；否则这条断言会因空集合而假通过。"
        )
        unknown = {k for k in read_keys - model_keys if (block, k) not in ALLOWED_EXTRA}
        assert not unknown, (
            f"详情页读了 `{block}` 块里不存在的键：{sorted(unknown)}。"
            f"后端该块实际提供：{sorted(model_keys)}。"
            "读不到的键会静默显示「—」或「无」，看起来像「这个项目没有数据」。"
        )

    def test_computed_fields_are_in_dump(self) -> None:
        """`risk_level` 是 computed_field，必须真的出现在 dump 里才会落库。

        computed_field 若忘了 `@computed_field` 装饰器，属性仍能访问、测试仍能
        读到值，但 `model_dump()` 里没有它 —— 于是落库的 JSON 缺这个键，
        前端又回到永远空白。这条断言专门盯 dump。
        """
        team_dump = TeamResult(team_score=0.85, team_type="doxxed").model_dump()
        assert "risk_level" in team_dump
        assert team_dump["risk_level"] == "low"

        risk_dump = RiskResult(token_risk=0.5, unlock_pressure="medium").model_dump()
        assert "farming_cost" in risk_dump

    def test_dump_can_be_replayed(self) -> None:
        """`model_dump()` 的结果必须能直接喂回构造器。

        `extra="forbid"` + computed_field 是一对天然冲突：dump 里带着 computed
        字段，构造时又被当成非法额外字段。任何从 `team_json` / `risk_json`
        回放的导入或重算路径都会因此硬失败，所以每加一个 computed_field
        都要验证这条回路。
        """
        team = TeamResult(team_score=0.85, team_type="doxxed")
        assert TeamResult(**team.model_dump()).risk_level == team.risk_level

        risk = RiskResult(token_risk=0.5, unlock_pressure="medium", farming_cost="high")
        assert RiskResult(**risk.model_dump()).farming_cost == "high"

        tokenomics = TokenomicsResult(vc_share=0.2, team_share=0.2, unlock_penalty=0.3)
        assert TokenomicsResult(**tokenomics.model_dump()).risk == tokenomics.risk


class TestParserFailsLoudly:
    def test_unknown_block_yields_nothing(self) -> None:
        """确认解析器不是"什么都匹配"——否则上面的断言毫无约束力。"""
        assert _member_accesses("const x = 1;", "team") == set()

    def test_parser_finds_a_known_read(self) -> None:
        assert "team_type" in _member_accesses(_source(), "team")
