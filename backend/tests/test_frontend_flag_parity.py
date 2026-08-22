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

from app.agents.team import FLAG_ADJUSTMENTS, score_to_risk_level

REPO_ROOT = Path(__file__).resolve().parents[2]
INSIGHTS_PAGE = REPO_ROOT / "frontend-next" / "app" / "insights" / "page.tsx"
INSIGHTS_ROUTER = REPO_ROOT / "backend" / "app" / "routers" / "v1" / "insights.py"


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


def _strip_comments(src: str) -> str:
    """去掉 TS 的块注释与行注释，只留真正会执行的代码。

    **这个函数是被自己的测试逼出来的。** 最初 `test_no_fabricated_flags_fallback`
    直接在原始源码里断言 `'无公开仓库' not in src`，结果它红了 —— 红的原因不是
    代码里还留着那个编造标记，而是**我在代码上方写的注释里解释了「不要写这个」**。

    这正是本仓反复栽的同一个坑：**描述规则的文本和遵守规则的代码，
    在字符串匹配眼里长得一模一样**。反过来更危险 —— 一段注释里恰好出现了
    要断言的字符串，就能让一条本该发现问题的断言假通过。

    所以凡是"某个字面量不许出现"这类断言，都必须先剥掉注释再匹配。
    """
    without_block = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", without_block, flags=re.M)


class TestRiskBadgeColours:
    """「高风险团队」徽章必须按风险档位分色，且不得编造 flags 兜底。

    实测这个列表返回 **270 条：high 71 条、medium 199 条** ——
    74% 是「中」。此前徽章一律写死红底红字，于是四分之三的中风险项目
    被渲染成和高风险完全一样的红色警告。

    **同一种视觉强度代表两种严重程度，等于把分级取消掉了**：用户要么
    把 199 个中风险全当高危处理，要么整片红色一起无视、连真正的 71 个
    也漏掉。两种反应都比不分色更糟。
    """

    @staticmethod
    def _levels_endpoint_can_return() -> set[str]:
        """本端点实际会输出的风险档位。

        真值是 `score_to_risk_level` 的值域，再交上路由的过滤条件
        —— `insights.py` 只把 high / medium 放进 risky_teams
        （low 不算「高风险团队」）。这里从路由源码解析那个过滤元组，
        而不是在测试里再抄一份，否则路由放宽档位时这里不会跟着红。
        """
        src = INSIGHTS_ROUTER.read_text(encoding="utf-8")
        match = re.search(r"if risk_level in \(([^)]*)\):", src)
        assert match, (
            f"在 {INSIGHTS_ROUTER.name} 里找不到 `if risk_level in (...)` 过滤条件。"
            "路由写法变了，请同步更新本测试，别让它静默什么都不查。"
        )
        levels = set(re.findall(r'"([^"]+)"', match.group(1)))
        assert levels, f"没能从 {INSIGHTS_ROUTER.name} 的过滤条件里解析出任何档位。"
        # 反向确认：解析出的档位必须都是 score_to_risk_level 真的会产出的值
        producible = {score_to_risk_level(s / 100) for s in range(0, 101)}
        bogus = levels - producible
        assert not bogus, f"路由过滤了 score_to_risk_level 从不产出的档位：{sorted(bogus)}"
        return levels

    def test_badge_helper_covers_every_level(self) -> None:
        """每个会出现的档位都要在 `riskBadgeClass` 里有独立分支。"""
        src = _source()
        match = re.search(r"function riskBadgeClass\(level: string\): string \{(.*?)\n\}", src, re.S)
        assert match, (
            f"在 {INSIGHTS_PAGE.name} 里找不到 `function riskBadgeClass(level: string)`。"
            "这个函数若被改名或删掉，请同步更新本测试。"
        )
        body = match.group(1)
        handled = set(re.findall(r"level === '([^']+)'", body))
        assert handled, "riskBadgeClass 里没解析到任何 `level === '...'` 分支，解析器已失效。"

        missing = self._levels_endpoint_can_return() - handled
        assert not missing, (
            f"这些风险档位在 riskBadgeClass 里没有分支：{sorted(missing)}，"
            "会退回中性灰 —— 一个高风险条目会被显示得和「未知」一样。"
        )

    def test_levels_are_visually_distinct(self) -> None:
        """不同档位不能共用同一套配色，否则分级在界面上不存在。"""
        src = _source()
        match = re.search(r"function riskBadgeClass\(level: string\): string \{(.*?)\n\}", src, re.S)
        assert match, f"在 {INSIGHTS_PAGE.name} 里找不到 riskBadgeClass"
        body = match.group(1)
        pairs = re.findall(r"level === '([^']+)'\)?\s*\n?\s*return\s+'([^']+)'", body)
        assert len(pairs) >= 2, f"只解析到 {len(pairs)} 个 `level === '...' → return '...'` 配对，解析器已失效。"
        classes = [cls for _level, cls in pairs]
        duplicates = {c for c in classes if classes.count(c) > 1}
        assert not duplicates, f"这些配色被多个风险档位共用：{sorted(duplicates)}。档位不同而观感相同，等于没有分级。"

    def test_no_fabricated_flags_fallback(self) -> None:
        """flags 缺失时不许填入编造的默认标记。

        原代码写的是 `(t.flags as string[]) || ['匿名团队', '无公开仓库']`。
        两处都有问题：`'无公开仓库'` 后端**根本不存在这个 flag**；
        而且 JS 里空数组是真值，所以这个兜底只在后端不发这个键时触发 ——
        真到那天，界面会替后端凭空断言「这个团队匿名、没有公开仓库」。

        **编造一个看起来合理的默认值比留空危险得多**：读者无法分辨
        「系统查到了这两条」和「系统什么都没查到」。

        注意断言前先剥注释（见 `_strip_comments`）：注释里会解释「不要写
        这个标记」，字符串匹配分不清解释和代码。
        """
        src = _strip_comments(_source())
        backend_flags = set(FLAG_ADJUSTMENTS)
        chinese_labels = _extract_object_keys(src, "FLAG_ZH")
        assert chinese_labels, "FLAG_ZH 解析为空，解析器已失效。"

        # 找出所有给 flags 变量赋值的行，检查右侧是否有硬编码数组字面量
        offenders = [
            line.strip()
            for line in src.splitlines()
            if re.search(r"\bflags\s*=", line) and re.search(r"\?\?\s*\[[^\]]+\]|\|\|\s*\[[^\]]+\]", line)
        ]
        assert not offenders, "flags 的兜底值里含有硬编码内容，应当只兜底成空数组：\n  " + "\n  ".join(offenders)
        # 正向确认兜底确实存在且为空数组（否则 undefined 会让 .map 抛错）
        assert re.search(r"\bflags\s*=.*\?\?\s*\[\]", src), (
            "没找到 `flags = ... ?? []` 形式的空数组兜底。flags 为 undefined 时 `.map` 会直接抛错，页面整块白屏。"
        )
        # 再钉一层：确保当年那个编造的标记没被以别的形式写回来
        assert "无公开仓库" not in src, (
            "'无公开仓库' 不是后端 FLAG_ADJUSTMENTS 里的 flag，"
            f"后端真实 flag 是 {sorted(backend_flags)}，不要在前端编造。"
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

    def test_strip_comments_removes_both_comment_forms(self) -> None:
        """剥注释函数必须同时处理 `//` 与 `/* */`，且不动真正的代码。

        这个自检不是形式主义：如果 `_strip_comments` 哪天被改成只剥一种，
        `test_no_fabricated_flags_fallback` 会**因为注释里的字样而误红**，
        或者更糟 —— 反向失效时因为注释里的字样而**假绿**。
        """
        assert _strip_comments("// 不要写 编造标记\nconst a = 1;").strip() == "const a = 1;"
        assert _strip_comments("/* 不要写 编造标记 */\nconst a = 1;").strip() == "const a = 1;"
        assert _strip_comments("/**\n * 多行 编造标记\n */\nconst a = 1;").strip() == "const a = 1;"
        # 代码本体必须留下来，否则「不许出现某字面量」的断言会永远通过
        assert "编造标记" in _strip_comments("const bad = ['编造标记'];")
