"""编码修复工具的回归测试（新增部分：二型 / 三型 / 四型损坏检测）。

一型 = 3 字节字符丢第 3 字节，文件变成非法 UTF-8。
二型 = 整个中文字符被替换成半角 `?`，文件**仍是合法 UTF-8**。
三型 = 字面 U+FFFD 替换符。
四型 = 含中文的 Windows 脚本缺 UTF-8 BOM ——
       **文件内容完全正确，是 PowerShell 5.1 把它读坏的**。

二型的检测比一型难，因为它必须靠"半角 ? 紧贴中文"这个启发式判据，而
mermaid 流程图的 `{全绿?}`、以及描述判据本身的文档文字都长得一样。
所以这里的测试重点是**误报**：判据必须排除代码块与行内代码。

四型的性质与前三型不同，值得单独说：前三型是"文件坏了"，
四型是"文件好的，读的人读坏了"。无 BOM 时 PowerShell 5.1 按 ANSI 代码页
（简中 = GBK）解码，GBK 会吃掉紧跟中文标点后的 ASCII 引号，
于是字符串不闭合、后面几十行代码被静默吞进字面量，
**语法仍然合法所以毫无报错** —— 脚本只是跳过那几十行然后 exit 0。
这一型的测试因此从"字节事实"开始证明（`test_gbk_really_swallows_the_quote`），
因为如果那个事实不成立，整个门禁就没有理由存在。
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

    2026-08-22 起该清单为**空集**（API_SPEC.md 的 70 处已全部修完），
    所以这个循环当前不执行任何断言。空循环的测试等于没有测试，因此
    另有 `test_mojibake_registry_is_empty` 正面钉住「清单必须保持为空」。
    """
    for rel in checker.KNOWN_BROKEN_MOJIBAKE:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        n = checker.count_mojibake(text)
        assert n > 0, f"{rel} 已无二型损坏，请从 KNOWN_BROKEN_MOJIBAKE 清单中删除"


def test_mojibake_registry_is_empty(checker):
    """二型损坏已清零，豁免清单必须保持为空。

    为什么要正面钉住「空」：**登记豁免会掩盖内容问题**。只要文件挂在豁免
    清单上，就没人会去逐行读它，于是错的内容跟错的字节一起躺着 ——
    API_SPEC.md 就是活例子：修那 70 处编码损坏的过程中，顺带查出 13 条
    根本不存在的端点、若干虚构的 query 参数和字段名。那些谎言比乱码更贵，
    却因为「反正这文件已登记待修」而没人碰。

    往这个清单里加文件是**倒退**，必须在这里显式讨论，而不是悄悄加一行。
    """
    assert not checker.KNOWN_BROKEN_MOJIBAKE, (
        f"二型豁免清单应为空，却有 {sorted(checker.KNOWN_BROKEN_MOJIBAKE)}；新增豁免等于让这些文件的内容错误一起免检。"
    )


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
    """已登记的三型损坏文件必须确实还损坏着。

    2026-08-23 起该清单为**空集**（`SYSTEM_DIRECTION_CHANGE.md` 的 2 处已修完），
    所以这个循环当前不执行任何断言 —— 空循环等于没有测试，因此另有
    `test_replacement_registry_is_empty` 正面钉住「清单必须保持为空」。
    """
    for rel in checker.KNOWN_BROKEN_REPLACEMENT:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        n = checker.count_replacement_chars(text)
        assert n > 0, f"{rel} 已无三型损坏，请从 KNOWN_BROKEN_REPLACEMENT 清单中删除"


def test_replacement_registry_is_empty(checker):
    """三型损坏已清零，豁免清单必须保持为空。

    与二型同一个理由：**登记豁免会掩盖内容问题**，不只是字节问题。
    三型的修法是把无法确定的装饰 emoji **直接去掉**，而不是猜一个补上 ——
    补一个猜的 emoji 会让文档看起来从未损坏过，下一个人再也分不清
    哪个标题是原作者写的、哪个是后来补的。

    往这个清单里加文件是**倒退**，必须在这里显式讨论，而不是悄悄加一行。
    """
    assert not checker.KNOWN_BROKEN_REPLACEMENT, (
        f"三型豁免清单应为空，却有 {sorted(checker.KNOWN_BROKEN_REPLACEMENT)}；"
        "新增豁免等于让这些文件的内容错误一起免检。"
    )


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


# ─────────────────────────────────────────────────────────────────
# 四型：含中文的 Windows 脚本缺 UTF-8 BOM
#
# 这一型和前三型性质不同：**文件内容完全正确，是读它的人把它读坏了。**
# Windows PowerShell 5.1 在无 BOM 时按 ANSI 代码页（简中 = GBK）解码，
# GBK 会吃掉紧跟中文标点后的 ASCII 引号，字符串不闭合，
# 后面几十行代码被静默吞进字面量 —— 语法仍合法，不报错、不警告。
#
# 2026-08-24 实测被咬：改完 `scripts/auto_backup.ps1` 跑验证，
# 脚本跳过前 150 行直接执行末尾，返回 exit 0 说"备份成功"，
# 而 Docker 根本连不上、什么都没备份。
# ─────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────
# 四型的"真值表"：在这台机器上用 PowerShell 5.1 实测出来的
# `[System.Text.Encoding]::GetEncoding(936).GetString(bytes)` 结果。
#
# ⚠️ **不能用 Python 的 `bytes.decode("gbk")` 当真值** —— 这是本轮踩的第二个坑，
# 而且比第一个更隐蔽：
#
#   同一串字节 EF BC 89 22（'）' + '"'）
#     .NET cp936（PowerShell 实际用的）→ 2 个字符，**引号被吃掉**
#     Python gbk codec + errors="replace" → 3 个字符，**引号保留**
#
# 原因：GBK 前导字节后跟一个非法尾字节时，
#   .NET 是**宽容**的 —— 无条件吃掉 2 个字节，产出一个替换字符；
#   Python 是**严格**的 —— 报 UnicodeDecodeError，`replace` 只消耗那 1 个前导字节，
#   于是后面的引号被单独解码出来，活了下来。
#
# 所以拿 Python 的 codec 去"验证" PowerShell 的行为，会得到相反的结论。
# 我第一版就是这么写的，而且当时"验证通过"了 —— 因为那个样本恰好两边一致。
# **验证用的解码器必须和被验证的解码器是同一个**，否则验证的是另一件事。
# 既然 CI 上跑的是 Python（拿不到 .NET），真值就只能是**实测记录下来的表**。
#
# 每项 = (源码片段, .NET cp936 解码后仍然保留的双引号个数)
_DOTNET_CP936_KEPT_QUOTES: tuple[tuple[str, int], ...] = (
    ('Write-Log "done"', 2),  # 纯 ASCII：不受影响
    ('Write-Log "备份完成"', 2),  # 4 个中文字（12 字节，偶）→ 引号存活
    ('Write-Log "中"', 1),  # 1 个中文字（3 字节，奇）→ 引号被吃
    ('Write-Log "中文"', 2),  # 2 个（6 字节，偶）
    ('Write-Log "中文字"', 1),  # 3 个（9 字节，奇）
    ('Write-Log "中文字符"', 2),  # 4 个（12 字节，偶）
    ('Write-Log "压缩失败（$msg）"', 1),
    ('Write-Log "错误: 压缩失败（$($_.Exception.Message)）"', 1),
    ("# 备份脚本", 0),
    ("$x = 1", 0),
)


def _dotnet_kept_quotes(checker, src: str) -> int:
    """按 .NET DBCS 规则算出：解码后还剩几个双引号没被吞掉。"""
    data = src.encode()
    eaten = checker.gbk_eaten_byte_offsets(data)
    return sum(1 for k, b in enumerate(data) if b == 0x22 and k not in eaten)


def test_model_matches_measured_dotnet_behavior(checker):
    """`gbk_eaten_byte_offsets` 必须复现实测的 .NET cp936 行为。

    真值来自 `_DOTNET_CP936_KEPT_QUOTES`（PowerShell 5.1 实测），
    不是来自 Python 的 gbk codec —— 理由见那张表上面的说明。

    模型和现实对不上的话，报错会指向错的行，那比不报错更误导。
    """
    for src, expected in _DOTNET_CP936_KEPT_QUOTES:
        got = _dotnet_kept_quotes(checker, src)
        assert got == expected, f"模型算出保留 {got} 个引号，实测 .NET 是 {expected} 个：{src!r}"


def test_the_parity_rule_is_real(checker):
    """核心事实：引号能否存活取决于**前面中文的字节奇偶性**，与"是什么标点"无关。

    ⚠️ 第一版这条测试写错了，值得记下来：我以为判据是"全角括号后面紧跟引号"，
    于是拿 `Write-Log "压缩失败（$msg）"` 当样本去证明 —— 但那一行里
    全角括号前面的字节数正好让引号活下来还是被吃，取决于整行前缀，
    跟"括号"本身毫无关系。**照着猜想构造的样本只能验证猜想，不能验证事实。**

    真规律：UTF-8 中文是 3 字节（奇数），GBK 按 2 字节一组啃，
    所以 1 个中文字后的引号被吃、2 个不被吃、3 个又被吃……
    """
    for n, expected_kept in ((1, 1), (2, 2), (3, 1), (4, 2), (5, 1)):
        src = 'Write-Log "' + "中" * n + '"'
        got = _dotnet_kept_quotes(checker, src)
        assert got == expected_kept, f"{n} 个中文字时应保留 {expected_kept} 个引号，模型给出 {got}：{src!r}"


def test_swallowed_quote_would_stay_syntactically_valid(checker):
    """最危险的一点：引号被吃掉之后代码**依然是合法 PowerShell**。

    正是因为合法，才没有任何报错 —— 只是静默跳过几十行。
    这里证明的是"剩余引号数变成奇数"，即字符串不闭合、
    后续代码被吞进字面量，而不是产生语法错误。
    """
    src = 'Write-Log "中"\nRemove-Item $x\nexit 3\n'
    kept = _dotnet_kept_quotes(checker, src)
    assert kept % 2 == 1, f"剩余引号数是偶数（{kept}），样本没复现问题：{src!r}"


def test_eaten_offsets_never_flags_pure_ascii(checker):
    """纯 ASCII 文件不该有任何字节被判为"被吞"。

    这是"纯 ASCII 脚本不需要 BOM"这条豁免的根据。
    如果这里出现命中，说明模型把 ASCII 也当成了双字节前导 ——
    那会让门禁去要求一堆根本没风险的文件加 BOM。
    """
    data = b'Write-Log "done"\nexit 0\n'
    assert checker.gbk_eaten_byte_offsets(data) == set()


def test_needs_utf8_bom_only_targets_windows_scripts(checker, tmp_path):
    """判据范围：只管 Windows 脚本，且只在含非 ASCII 时才管。

    .md/.py 不在范围内 —— 它们由 Python/编辑器按 UTF-8 读，不走 ANSI 代码页。
    把范围扩大到所有文件会造成大量无意义的 BOM。
    """
    cn = 'Write-Log "备份完成"\n'.encode()
    ascii_only = b'Write-Log "done"\n'

    ps1 = tmp_path / "a.ps1"
    ps1.write_bytes(cn)
    assert checker.needs_utf8_bom(ps1, cn) is True

    ps1_ascii = tmp_path / "b.ps1"
    ps1_ascii.write_bytes(ascii_only)
    assert checker.needs_utf8_bom(ps1_ascii, ascii_only) is False, (
        "纯 ASCII 脚本不需要 BOM —— GBK 与 UTF-8 对 ASCII 解码一致"
    )

    for suffix in (".md", ".py", ".ts", ".json"):
        other = tmp_path / f"c{suffix}"
        other.write_bytes(cn)
        assert checker.needs_utf8_bom(other, cn) is False, f"{suffix} 不该被四型门禁管"

    for suffix in (".psm1", ".bat", ".cmd"):
        script = tmp_path / f"d{suffix}"
        script.write_bytes(cn)
        assert checker.needs_utf8_bom(script, cn) is True, f"{suffix} 同样由 cmd/PowerShell 按代码页读，必须管"


def test_bom_hazard_description_points_at_the_real_line(checker):
    """报错必须指出**具体哪一行的引号真的会被吃掉**，不是只说"有中文"。

    只说"有中文"的话，读的人不知道为什么危险，会倾向于认为是洁癖要求。
    指出那一行之后，"这里会静默吞掉后面的代码"就变成了可验证的事实。
    """
    data = ('# 备份脚本\n$x = 1\nWrite-Log "中"\nexit 3\n').encode()
    detail = checker.describe_bom_hazard(data)
    assert "第 3 行" in detail, f"没指出正确行号：{detail}"
    assert "静默" in detail or "不闭合" in detail, f"没说清后果：{detail}"


def test_bom_hazard_description_when_parity_happens_to_be_safe(checker):
    """含中文但引号恰好没落在尾字节位时，仍然要求 BOM。

    理由必须写进提示里：那只是字节奇偶性的巧合，改一个字就翻转。
    一个"暂时安全"的文件不值得放过 —— 放过它等于把炸弹留给下一个人。
    """
    data = "# 备份脚本\n$x = 1\nexit 0\n".encode()
    detail = checker.describe_bom_hazard(data)
    assert "奇偶" in detail and "仍必须加 BOM" in detail, f"提示没说清为什么仍需 BOM：{detail}"


def _run_main(checker, monkeypatch, *paths: Path) -> int:
    monkeypatch.setattr(sys, "argv", ["check_encoding.py", *[str(p) for p in paths]])
    return checker.main()


def test_main_actually_enforces_the_bom_rule(checker, monkeypatch, tmp_path):
    """端到端：`main()` 必须真的因为缺 BOM 而返回 1。

    ⚠️ 这条是变异测试逼出来的，值得单独记：
    我最初只测了 `needs_utf8_bom()` / `describe_bom_hazard()` / 全仓扫描，
    然后做变异 —— 把 `main()` 里那个 `if needs_utf8_bom(...)` 分支整段删掉，
    **36 条测试全绿**。

    也就是说：判据写得再对，只要没接进主流程，门禁就是不存在的。
    而当时全仓恰好没有违规文件，所以"全仓扫描通过"这条也照样绿 ——
    **一个只在没有违规时被执行的检查，无法证明它会拦住违规。**

    所以这条测试必须走真正的入口，并且必须构造一个真实的违规文件。
    """
    bad = tmp_path / "bad.ps1"
    bad.write_bytes('Write-Log "中"\nexit 0\n'.encode())  # 合法 UTF-8，无 BOM
    assert _run_main(checker, monkeypatch, bad) == 1, "缺 BOM 的脚本没被 main() 拦住 —— 四型门禁没有接进主流程"

    good = tmp_path / "good.ps1"
    good.write_bytes(checker.UTF8_BOM + 'Write-Log "中"\nexit 0\n'.encode())
    assert _run_main(checker, monkeypatch, good) == 0, "带 BOM 的脚本被误判 —— 会逼着人把正确的文件改坏"

    ascii_no_bom = tmp_path / "ascii.ps1"
    ascii_no_bom.write_bytes(b'Write-Log "done"\nexit 0\n')
    assert _run_main(checker, monkeypatch, ascii_no_bom) == 0, "纯 ASCII 脚本不该被要求加 BOM"


def test_main_reports_the_offending_path_and_reason(checker, monkeypatch, tmp_path, capsys):
    """报错输出必须同时给出**文件路径**、**为什么危险**、**怎么修**。

    只打印一个退出码的门禁会被当成误报关掉。
    这里断言的是"人能照着输出修"，不是"函数返回了 1"。

    ⚠️ 断言要挑**每条信息独有的字样**，这也是变异测试逼出来的：
    第一版写的是 `"静默" in out or "不闭合" in out`，而这两个词
    在逐文件的明细行里也出现 —— 把整段解释删掉之后测试照样绿。
    **一个能被两处满足的断言，只能证明其中一处存在。**
    现在改成断言解释段独有的内容：ANSI 代码页、以及最反直觉的那句
    "然后 exit 0"（脚本静默跳过代码却报成功，正是这一型的杀伤力所在）。
    """
    bad = tmp_path / "hazard.ps1"
    bad.write_bytes('# 头部\nWrite-Log "中"\nexit 0\n'.encode())
    assert _run_main(checker, monkeypatch, bad) == 1
    out = capsys.readouterr().out
    assert "hazard.ps1" in out, f"没报出文件名：{out}"
    assert "BOM" in out, f"没说清缺什么：{out}"
    # 逐文件明细：指出具体哪一行的引号会被吃
    assert "第 2 行" in out, f"没指出具体行号：{out}"
    # 解释段：为什么会这样。三个要素各自独有，缺一个就说不完整
    assert "代码页" in out, f"没说是代码页问题：{out}"
    assert "0x80" in out, f"没给出「>= 0x80 吃掉下一字节」这个机制，读者无法自己判断风险：{out}"
    assert "3 字节" in out, f"没说 UTF-8 中文是 3 字节（奇偶性的来源），解释就断了：{out}"
    assert "exit 0" in out, f"没说清最要命的后果（静默跳代码却报成功）：{out}"
    # 修法：可照抄
    assert "UTF8Encoding" in out, f"没给可照抄的修法：{out}"


def test_main_still_prioritises_real_corruption(checker, monkeypatch, tmp_path, capsys):
    """一个既非法 UTF-8、又缺 BOM 的文件，应当先按一型报，不要两头都报。

    理由：一型是内容已经坏了，修内容时必然要重写文件，BOM 顺手就有了。
    同一个文件报两种性质不同的问题只会让人不知道先修哪个。
    """
    both = tmp_path / "broken.ps1"
    both.write_bytes("运".encode()[:2] + b"?\nexit 0\n")  # 非法 UTF-8，且无 BOM
    assert _run_main(checker, monkeypatch, both) == 1
    out = capsys.readouterr().out
    assert "一型" in out, f"没按一型报：{out}"
    assert "四型" not in out, f"同一个文件同时报了一型和四型，会让人不知道先修哪个：{out}"


def test_repo_windows_scripts_all_have_bom(checker):
    """全仓实测：每个含中文的 Windows 脚本都必须带 BOM。

    这一型**零豁免、零登记** —— 修法是加 3 个字节，
    不存在前三型那种"原字符已不可逆丢失"的情况，没有理由给谁开豁免。
    """
    offenders: list[tuple[str, str]] = []
    checked = 0
    for path in checker.iter_repo_files():
        if path.suffix.lower() not in checker.BOM_REQUIRED_SUFFIXES:
            continue
        data = path.read_bytes()
        if not checker.needs_utf8_bom(path, data):
            continue
        checked += 1
        if not data.startswith(checker.UTF8_BOM):
            try:
                rel = path.resolve().relative_to(checker.REPO_ROOT).as_posix()
            except ValueError:
                rel = path.as_posix()
            offenders.append((rel, checker.describe_bom_hazard(data)))
    assert checked > 0, "全仓一个含中文的 Windows 脚本都没扫到 —— 解析器已失效，本条门禁在空转"
    assert not offenders, f"这些 Windows 脚本含中文但缺 UTF-8 BOM，PowerShell 5.1 会静默跳代码：{offenders}"


def test_bom_registry_does_not_exist(checker):
    """四型不设登记清单 —— 断言这一点，防止有人"临时"加一个。

    前三型的登记清单是历史包袱（损坏不可逆，只能先挂起来）。
    四型没有这个属性：加 3 字节即可修好。一旦有了豁免清单，
    "先登记着"就会变成默认选项，而门禁的意义就消失了。
    """
    assert not hasattr(checker, "KNOWN_BROKEN_BOM"), (
        "出现了四型豁免清单 —— 四型的修法是加 3 个字节 BOM，不存在需要豁免的情况。"
        "如果确实有例外，请先在这条测试里写清楚理由。"
    )


def test_precommit_hook_covers_every_bom_required_suffix(checker):
    """pre-commit 的 `files` 正则必须覆盖四型管的每一个扩展名。

    这是双向登记表的另一半：判据管 `.ps1/.psm1/.bat/.cmd`，
    但如果 pre-commit 的正则只写了 `ps1|bat`，那么新增一个 `.psm1`
    脚本时钩子根本不会被触发 —— **判据是对的，触发条件漏了。**

    实测确实漏了：这条测试写出来时正则里只有 `ps1|bat`，
    没有 `psm1`/`cmd`。CI 的 pytest 会跑本文件的全仓扫描兜底，
    但 pre-commit 是第一道门，漏在这里意味着问题会先被提交进去。

    ⚠️ 定位钩子必须**整行精确匹配**，不能用 `"id: check-encoding" in config`。
    变异测试把 id 改成 `check-encoding-DISABLED`（pre-commit 里等于停用这个钩子），
    子串匹配照样命中，测试全绿。**子串匹配会把"改了名字的东西"当成原来那个。**
    """
    config = (checker.REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "check_encoding.py" in config, "pre-commit 里没有 check_encoding 钩子 —— 第一道门不存在。"

    lines = config.splitlines()
    hook_idx = [i for i, line in enumerate(lines) if line.strip() == "- id: check-encoding"]
    assert hook_idx, (
        "找不到 id 恰好为 `check-encoding` 的钩子。"
        "注意改名（如 `check-encoding-DISABLED`）等于停用它 —— 这里刻意做整行精确匹配，不接受子串。"
    )

    # 取这个钩子那一段（到下一个 `- id:` 或文件末尾）
    start = hook_idx[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("- id:")), len(lines))
    section = "\n".join(lines[start:end])
    assert "files:" in section, f"`check-encoding` 钩子没有 files 正则：{section}"
    assert "check_encoding.py" in section, f"`check-encoding` 钩子的 entry 不是 check_encoding.py：{section}"

    missing = [s for s in sorted(checker.BOM_REQUIRED_SUFFIXES) if s.lstrip(".") not in section]
    assert not missing, (
        f"这些扩展名被四型判据管着，但 pre-commit 的 files 正则里没有：{missing}。"
        "判据写对了而触发条件漏了，等于这类文件的第一道门是空的。"
    )


def test_four_modes_are_mutually_distinguishable(checker, tmp_path):
    """四型与前三型正交：一个只缺 BOM 的文件，前三型判据必须全部判它干净。

    这条锁住"新增第四型不会污染既有判据" —— 与
    `test_three_modes_are_mutually_distinguishable` 同一目的。
    """
    text = 'Write-Log "压缩失败（$msg）"\n'
    data = text.encode()  # 合法 UTF-8，无 BOM
    ps1 = tmp_path / "clean_but_no_bom.ps1"
    ps1.write_bytes(data)

    # 一型：合法 UTF-8
    assert data.decode("utf-8") == text
    assert checker.count_errors(data) == 0
    # 二型 / 三型：干净
    assert checker.count_mojibake(text) == 0
    assert checker.count_replacement_chars(text) == 0
    # 四型：命中
    assert checker.needs_utf8_bom(ps1, data) is True
    assert not data.startswith(checker.UTF8_BOM)

    # 加上 BOM 后四型也干净，且不影响前三型
    with_bom = checker.UTF8_BOM + data
    assert with_bom.startswith(checker.UTF8_BOM)
    assert checker.count_errors(with_bom) == 0
