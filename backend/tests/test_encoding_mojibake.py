"""编码修复工具的回归测试（新增部分：二型损坏检测）。

一型 = 3 字节字符丢第 3 字节，文件变成非法 UTF-8。
二型 = 整个中文字符被替换成半角 `?`，文件**仍是合法 UTF-8**。

二型的检测比一型难，因为它必须靠"半角 ? 紧贴中文"这个启发式判据，而
mermaid 流程图的 `{全绿?}`、以及描述判据本身的文档文字都长得一样。
所以这里的测试重点是**误报**：判据必须排除代码块与行内代码。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def checker():
    return _load("check_encoding")


def _c(before: str, after: str) -> str:
    """拼出一处二型损坏样本：`before` + 半角问号 + `after`。

    **必须用拼接而不是字面量**：若把损坏样本直接写成字面量（中文 + 半角问号 +
    中文），本文件自己就会被 `test_no_unregistered_mojibake_in_repo` 判成损坏
    文件（实测已发生两次，第二次是这段注释本身）。拼接后源码里的问号两侧都是
    ASCII 引号，不触发判据，而运行时得到的字符串仍是真实的损坏形态。
    """
    return f"{before}?{after}"


# ── 二型损坏：真阳性 ────────────────────────────────────────


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("本文档给出每个端点的请", "响应样例。"),  # 问号夹在中文之间
        ("所有端点返回统一结构", "下面是示例。"),
        ("无鉴权", "仅限本地使用。"),
        ("结尾也算", ""),  # 问号紧跟中文、位于串尾
        ("", "开头也算"),  # 问号紧贴其后的中文
    ],
)
def test_detects_mojibake(checker, before, after):
    assert checker.count_mojibake(_c(before, after)) >= 1


def test_reports_line_and_context(checker):
    text = "第一行正常。\n" + _c("第二行有请", "响应问题。") + "\n"
    desc = checker.describe_first_mojibake(text)
    assert "第 2 行" in desc
    assert "被替换成" in desc


# ── 二型损坏：误报防线（这部分才是重点）────────────────────


def test_mermaid_question_mark_is_not_corruption(checker):
    """流程图判定节点里的问号是正常写法，不能报错。

    这是实测遇到的误报：`docs/GIT_STRATEGY.md` 有 2 处 mermaid 判定节点。
    """
    text = "```mermaid\nflowchart TD\n  D --> E{" + _c("全绿", "") + "}\n```\n"
    assert checker.count_mojibake(text) == 0


def test_inline_code_question_mark_is_not_corruption(checker):
    """行内代码里的同样写法也不算。

    实测误报来源：`check_encoding.py` 自己的文档字符串在解释判据时，
    写下的例子恰好符合判据 —— 不排除行内代码就无法自洽。
    """
    text = "判据说明：mermaid 的 `{" + _c("全绿", "") + "}` 属正常写法。\n"
    assert checker.count_mojibake(text) == 0


def test_fenced_block_spanning_multiple_lines(checker):
    text = "正文说明。\n```\n" + _c("打印（x", "") + "\n" + _c("更多内容", "") + "\n```\n正文继续。\n"
    assert checker.count_mojibake(text) == 0


def test_ascii_question_mark_not_touching_cjk_is_fine(checker):
    """英文语境的问号、以及与中文隔着空格的问号，都不算损坏。"""
    assert checker.count_mojibake("Is this ok? Yes.\n") == 0
    assert checker.count_mojibake("这样呢 ? 应该没事\n") == 0


def test_fullwidth_question_mark_is_fine(checker):
    """全角问号是正常标点，只有半角问号才是损坏特征。"""
    assert checker.count_mojibake("这样可以吗？当然。\n") == 0


def test_checker_source_is_self_consistent(checker):
    """本仓库的检查脚本自己必须过自己的检查。

    否则说明判据把"描述判据的文字"也当成了损坏 —— 实测踩过这个坑。
    """
    for name in ("check_encoding.py", "repair_utf8_docs.py", "verify_utf8_repair.py"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert checker.count_mojibake(text) == 0, f"{name} 被自己的判据误报"


# ── 已登记清单与现实一致 ───────────────────────────────────


def test_known_mojibake_list_matches_reality(checker):
    """已登记的二型损坏文件必须确实还损坏着。

    修好后请从 KNOWN_BROKEN_MOJIBAKE 删除 —— 这个断言会提醒你。
    """
    for rel in checker.KNOWN_BROKEN_MOJIBAKE:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        n = checker.count_mojibake(text)
        assert n > 0, f"{rel} 已无二型损坏，请从 KNOWN_BROKEN_MOJIBAKE 清单中删除"


def test_no_unregistered_mojibake_in_repo(checker):
    """全仓不得出现**未登记**的二型损坏。

    这条等于把 pre-commit 钩子的效果固化成测试：新写的文档若被非 UTF-8
    编码写回，这里会红。
    """
    offenders: list[tuple[str, int]] = []
    for path in checker.iter_repo_files():
        try:
            text = path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # 一型损坏由另一组测试覆盖
        n = checker.count_mojibake(text)
        if not n:
            continue
        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        if rel not in checker.KNOWN_BROKEN_MOJIBAKE:
            offenders.append((rel, n))
    assert not offenders, f"发现未登记的二型编码损坏：{offenders}"


# ── 三型：字面 U+FFFD 替换符 ────────────────────────────────
#
# 三型是在写完二型检测后主动追问"还有没有别的形态"才发现的。
# 教训：检测判据的盲区就是损坏的藏身处。


def test_detects_replacement_char(checker):
    text = "## " + "\ufffd" + " 成功指标（KPI）\n"
    assert checker.count_replacement_chars(text) == 1


def test_counts_multiple_replacement_chars(checker):
    text = f"## {chr(0xFFFD)} 标题一\n## {chr(0xFFFD)}\ufe0f 标题二\n"
    assert checker.count_replacement_chars(text) == 2


def test_clean_text_has_no_replacement_char(checker):
    assert checker.count_replacement_chars("## 📋 执行摘要\n正常中文。\n") == 0


def test_replacement_char_needs_no_code_block_exclusion(checker):
    """三型判据不排除代码块 —— 正常写作绝不会输入 U+FFFD，零误报风险。

    这是三型与二型的关键差别：二型的 `?` 在 mermaid 图里是合法写法，
    必须排除代码；三型没有这个顾虑。
    """
    text = f"```mermaid\ngraph TD\n  A{{全绿?}} --> B\n```\n正文 {chr(0xFFFD)} 这里坏了\n"
    assert checker.count_mojibake(text) == 0  # 二型：代码块内不判
    assert checker.count_replacement_chars(text) == 1  # 三型：照样抓到正文那处


def test_reports_replacement_line_and_context(checker):
    text = f"第一行\n第二行\n## {chr(0xFFFD)} 成功指标\n"
    desc = checker.describe_first_replacement(text)
    assert "第 3 行" in desc
    assert "成功指标" in desc


def test_describe_replacement_empty_when_clean(checker):
    assert checker.describe_first_replacement("完全正常的中文。\n") == ""


def test_repair_scripts_contain_no_literal_replacement_char(checker):
    """修复脚本用 U+FFFD 当"待定"占位符，但只能是转义写法。

    若谁把它写成字面量，脚本文件自己就成了三型损坏样本。
    """
    for name in ("check_encoding.py", "repair_utf8_docs.py", "verify_utf8_repair.py"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        n = checker.count_replacement_chars(text)
        assert n == 0, f"{name} 含 {n} 个字面 U+FFFD，请改用转义写法"


def test_known_replacement_list_matches_reality(checker):
    for rel in checker.KNOWN_BROKEN_REPLACEMENT:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        n = checker.count_replacement_chars(text)
        assert n > 0, f"{rel} 已无三型损坏，请从 KNOWN_BROKEN_REPLACEMENT 清单中删除"


def test_no_unregistered_replacement_char_in_repo(checker):
    """全仓不得出现**未登记**的三型损坏。"""
    offenders: list[tuple[str, int]] = []
    for path in checker.iter_repo_files():
        try:
            text = path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = checker.count_replacement_chars(text)
        if not n:
            continue
        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        if rel not in checker.KNOWN_BROKEN_REPLACEMENT:
            offenders.append((rel, n))
    assert not offenders, f"发现未登记的三型编码损坏：{offenders}"


def test_three_modes_are_mutually_distinguishable(checker):
    """三型判据互不重叠 —— 每种损坏只应被对应的检查抓到。

    这条锁住"新增一型不会污染既有判据"这个性质。
    注意样本仍用 `_c()` 拼接，理由见该函数的说明。
    """
    # 一型：非法 UTF-8（3 字节字符的第 3 字节被换掉）
    mode1 = "运".encode()[:2] + b"?"
    with pytest.raises(UnicodeDecodeError):
        mode1.decode("utf-8")

    # 二型：整字变半角问号，文件仍是合法 UTF-8
    mode2 = _c("运维手", "每周检查") + "\n"
    assert checker.count_mojibake(mode2) == 1
    assert checker.count_replacement_chars(mode2) == 0

    # 三型：字面 U+FFFD
    mode3 = f"运维手{chr(0xFFFD)}每周检查\n"
    assert checker.count_replacement_chars(mode3) == 1
    assert checker.count_mojibake(mode3) == 0
