"""前端 flag 中文化表与后端 `FLAG_ADJUSTMENTS` 的一致性回归。

## 为什么需要这个测试

`frontend-next/app/insights/page.tsx` 里有三张表：
`FLAG_ZH`（英文 flag → 中文名）、`POSITIVE_FLAGS`、`NEGATIVE_FLAGS`（正/负分色）。
它们的真值在后端 `app/agents/team.py` 的 `FLAG_ADJUSTMENTS` —— 那里每个 flag
带一个正负分数调整，**正负号本身就定义了它是好信号还是坏信号**。

实测发现前端漏了 `wash-trading VC`（后端 -0.20）。漏掉的后果不是"少显示一个"，
而是它会走 fallback：显示英文原文 + 中性灰 —— 一个扣分项被渲染得像无关紧要的
补充说明。这类错误没有任何运行时报错，只能靠一致性断言发现。

## 为什么用文本解析而不是让前端导出 JSON

前端是 TS/TSX，后端测试跑在 Python 里，没有共享的运行时。可选方案有三种：
把表挪到一份 JSON 由两边读、在前端加测试去读 Python、或者在这里解析 TSX。
前两种都需要新增构建步骤或跨语言依赖；这里选**解析 TSX 源文本**，
零新增依赖，且失败信息足够具体（会直接列出缺哪个 flag）。

代价是解析对源码格式有假设。所以下面每个解析函数在找不到目标时都
**显式失败并说明原因**，而不是返回空集合——空集合会让断言意外通过，
那才是最坏的结果：一个永远为真的测试。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.agents.team import FLAG_ADJUSTMENTS

REPO_ROOT = Path(__file__).resolve().parents[2]
INSIGHTS_PAGE = REPO_ROOT / "frontend-next" / "app" / "insights" / "page.tsx"


def _source() -> str:
    if not INSIGHTS_PAGE.is_file():
        pytest.skip(f"前端源文件不存在（可能是仅后端的检出）：{INSIGHTS_PAGE}")
    return INSIGHTS_PAGE.read_text(encoding="utf-8")


def _extract_object_keys(src: str, decl: str) -> set[str]:
    """从 `const <decl>: Record<string, string> = { 'a': '..', ... }` 里取出所有键。"""
    match = re.search(
        rf"const\s+{re.escape(decl)}\s*:[^=]*=\s*\{{(.*?)\n\}};",
        src,
        re.S,
    )
    assert match, (
        f"在 {INSIGHTS_PAGE.name} 里找不到 `const {decl} = {{...}}`。"
        "如果这张表被改名或改写了，请同步更新本测试——"
        "不要让它静默地什么都不检查。"
    )
    return set(re.findall(r"^\s*'([^']+)'\s*:", match.group(1), re.M))


def _extract_set_members(src: str, decl: str) -> set[str]:
    """从 `const <decl> = new Set([ 'a', 'b', ])` 里取出所有成员。"""
    match = re.search(
        rf"const\s+{re.escape(decl)}\s*=\s*new Set\(\[(.*?)\]\);",
        src,
        re.S,
    )
    assert match, (
        f"在 {INSIGHTS_PAGE.name} 里找不到 `const {decl} = new Set([...])`。"
        "如果这张表被改名或改写了，请同步更新本测试。"
    )
    return set(re.findall(r"'([^']+)'", match.group(1)))


class TestFlagParity:
    def test_every_backend_flag_has_chinese_label(self) -> None:
        """后端每个 flag 都必须在前端有中文名，否则界面上会露出英文原文。"""
        labelled = _extract_object_keys(_source(), "FLAG_ZH")
        missing = set(FLAG_ADJUSTMENTS) - labelled
        assert not missing, (
            f"这些后端 flag 在前端 FLAG_ZH 里没有中文名：{sorted(missing)}。"
            "界面会显示英文原文。请在 frontend-next/app/insights/page.tsx 补上。"
        )

    def test_no_frontend_only_flags(self) -> None:
        """反向也要成立：前端不能给后端根本不会产生的 flag 编中文名。

        多出来的条目是死代码，更要紧的是它会让人以为系统会输出这种信号。
        """
        labelled = _extract_object_keys(_source(), "FLAG_ZH")
        extra = labelled - set(FLAG_ADJUSTMENTS)
        assert not extra, f"前端 FLAG_ZH 里这些 flag 后端并不产生：{sorted(extra)}。要么后端漏了，要么前端该删。"

    def test_sign_classification_matches_backend(self) -> None:
        """正/负分色必须与后端分数调整的正负号一致。

        后端 `FLAG_ADJUSTMENTS` 的正负号是唯一真值：负数 = 扣分 = 负面信号。
        前端如果把扣分项归进 POSITIVE_FLAGS，用户会把一个风险信号看成利好。
        """
        src = _source()
        positive = _extract_set_members(src, "POSITIVE_FLAGS")
        negative = _extract_set_members(src, "NEGATIVE_FLAGS")

        # 同一个 flag 不能同时出现在两张表里（flagClass 先查 positive，
        # 于是负面信号会被静默染成绿色）
        both = positive & negative
        assert not both, f"这些 flag 同时出现在正负两张表里：{sorted(both)}"

        wrong: list[str] = []
        for flag, adjustment in FLAG_ADJUSTMENTS.items():
            if adjustment > 0 and flag in negative:
                wrong.append(f"{flag}（后端 {adjustment:+} 却被归为负面）")
            if adjustment < 0 and flag in positive:
                wrong.append(f"{flag}（后端 {adjustment:+} 却被归为正面）")
        assert not wrong, "前端分色与后端分数符号矛盾：" + "；".join(wrong)

    def test_every_backend_flag_is_classified(self) -> None:
        """每个 flag 都要明确归类，不能靠 fallback 显示成中性灰。

        `wash-trading VC` 就是这么漏掉的：后端 -0.20，前端两张表都没有它，
        于是走 `flag-chip-neutral`，一个扣分项被渲染得像中性补充说明。
        """
        src = _source()
        classified = _extract_set_members(src, "POSITIVE_FLAGS") | _extract_set_members(src, "NEGATIVE_FLAGS")
        missing = set(FLAG_ADJUSTMENTS) - classified
        assert not missing, (
            f"这些后端 flag 在前端没有正/负归类：{sorted(missing)}，会被显示成中性灰，看不出是加分还是扣分。"
        )


class TestParserItself:
    """解析函数自身的自检 —— 一个永远返回空集合的解析器会让上面全部断言假通过。"""

    def test_parsers_find_real_tables(self) -> None:
        src = _source()
        assert len(_extract_object_keys(src, "FLAG_ZH")) >= 5
        assert len(_extract_set_members(src, "POSITIVE_FLAGS")) >= 3
        assert len(_extract_set_members(src, "NEGATIVE_FLAGS")) >= 2

    def test_parser_fails_loudly_on_missing_table(self) -> None:
        """表名不存在时必须断言失败，而不是返回空集合。"""
        with pytest.raises(AssertionError):
            _extract_object_keys("const OTHER = {};", "FLAG_ZH")
        with pytest.raises(AssertionError):
            _extract_set_members("const OTHER = new Set([]);", "POSITIVE_FLAGS")
