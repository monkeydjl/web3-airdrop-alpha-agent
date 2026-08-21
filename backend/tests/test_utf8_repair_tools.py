"""UTF-8 修复工具的回归测试。

为什么值得写测试：`scripts/repair_utf8_docs.py` 会**改写文档正文**，一旦规则
出错就是静默污染 —— 填进去的错字看起来和原文一样自然，事后无从分辨。所以每条
推断规则都必须有可复现的准确率证据。

测试策略是"用已知答案考规则"：
  1. `6823d18` 提交里有 `OPERATIONS.md` / `OBSERVABILITY.md` 的**干净版本**，
     而工作区里的同名文件是损坏版。于是同一个损坏位置有两个独立来源 ——
     规则推断出的字符、底本恢复出的字符。两者必须一致。
  2. 拿干净文档当语料，人为按同样形态损坏，再检验修复能否还原。

跑法：pytest backend/tests/test_utf8_repair_tools.py
（脚本在仓库根 scripts/ 下，非 backend 包，靠 sys.path 注入导入。）
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load(name: str):
    """按路径加载仓库根 scripts/ 下的脚本模块。"""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def repair():
    return _load("repair_utf8_docs")


@pytest.fixture(scope="module")
def verifier():
    return _load("verify_utf8_repair")


@pytest.fixture(scope="module")
def checker():
    return _load("check_encoding")


def _corrupt(text: str, every: int = 8) -> bytes:
    """按真实损坏形态人为损坏：每 `every` 个 3 字节字符坏 1 个，第 3 字节变 '?'。

    `every=8` 对应实测密度：三个损坏文档分别是 9.8% / 9.4% / 7.7%。
    **不要把全部中文都损坏** —— 那会把底本对齐的锚点全毁掉，测出来的失败是
    测试设计问题而非工具缺陷（这是实际踩过的坑）。
    """
    out = bytearray()
    seen = 0
    for ch in text:
        b = ch.encode("utf-8")
        if len(b) == 3:
            if seen % every == 0:
                out += b[:2] + b"?"
            else:
                out += b
            seen += 1
        else:
            out += b
    return bytes(out)


def _write_exact(path: Path, text: str) -> None:
    """按字节写入，绕开 Windows 上 write_text 把 \\n 转成 \\r\\n 的行为。

    校验器要做逐字节比对，行尾被悄悄改写会让它误报"正文被改动"。
    """
    path.write_bytes(text.encode("utf-8"))


# ── 损坏点识别 ──────────────────────────────────────────────


def test_find_sites_locates_every_corruption(repair):
    """人为损坏 N 个字符，应识别出恰好 N 个损坏点。"""
    clean = "第一句。第二句，第三句；完。"
    raw = _corrupt(clean, every=2)
    expected = sum(1 for i, ch in enumerate(_cjk_only(clean)) if i % 2 == 0)
    assert len(repair.find_sites(raw)) == expected


def _cjk_only(text: str) -> list[str]:
    return [c for c in text if len(c.encode("utf-8")) == 3]


def test_find_sites_on_clean_text_returns_nothing(repair):
    assert repair.find_sites("完全正常的中文，没有损坏。".encode()) == []


def test_prefix_map_is_keyed_by_char_offset_not_ordinal(repair):
    """下标映射必须稳定：这正是早先"按序号索引"版本的 bug 所在。

    填掉前面的占位符后，后面占位符的序号会变，但字符下标不变。
    """
    broken = bytearray()
    for ch in "甲。乙、丙；":
        b = ch.encode("utf-8")
        broken += (b[:2] + b"?") if ch in "。、；" else b
    lossy, prefix_at = repair.to_lossy_text(bytes(broken), repair.find_sites(bytes(broken)))
    assert lossy.count(repair.PLACEHOLDER) == 3
    # 每个占位符下标都能查到自己的前缀
    for pos, ch in enumerate(lossy):
        if ch == repair.PLACEHOLDER:
            assert pos in prefix_at
            assert len(prefix_at[pos]) == 2
    # 填掉第一个后，剩下两个的下标（以及查得到的前缀）不变
    first = lossy.index(repair.PLACEHOLDER)
    patched = lossy[:first] + "。" + lossy[first + 1 :]
    remaining = [p for p, c in enumerate(patched) if c == repair.PLACEHOLDER]
    assert len(remaining) == 2
    for pos in remaining:
        assert pos in prefix_at, "填补后下标发生漂移 —— 这正是早先版本的 bug"


# ── 底本对齐 ──────────────────────────────────────────────


def test_baseline_alignment_restores_exactly(repair):
    """有干净底本时应完全还原，且不改动未损坏正文。"""
    clean = (
        "# 标题\n\n第一段说明文字，用来给对齐算法足够的锚点。\n"
        "第二段说明，包含（括号）与顿号、句号。\n第三段继续叙述，保证上下文充分。\n"
    )
    raw = _corrupt(clean, every=6)
    sites = repair.find_sites(raw)
    assert sites, "测试数据本身应含损坏点"
    lossy, prefix_at = repair.to_lossy_text(raw, sites)
    fixed, n, pending = repair.repair_with_baseline(lossy, prefix_at, clean)
    assert pending == 0
    assert n == len(sites)
    assert fixed == clean


def test_baseline_alignment_survives_crlf_mismatch(repair):
    """损坏版 CRLF、底本 LF 时仍要对齐 —— 这是实测踩过的坑。"""
    clean_lf = "# 标题\n\n说明文字，内容足够长以便对齐。第二句话在这里。\n结束段落。\n"
    clean_crlf = clean_lf.replace("\n", "\r\n")
    raw = _corrupt(clean_crlf, every=6)
    lossy, prefix_at = repair.to_lossy_text(raw, repair.find_sites(raw))
    fixed, n, pending = repair.repair_with_baseline(lossy, prefix_at, clean_lf)
    assert n > 0, "CRLF/LF 差异不应让对齐全部失效"
    assert pending == 0
    assert fixed == clean_crlf


def test_baseline_alignment_rejects_prefix_mismatch(repair):
    """底本内容完全不同时，宁可不填也不能写错字。"""
    broken = bytearray()
    for ch in "說明。":
        b = ch.encode("utf-8")
        broken += (b[:2] + b"?") if ch == "。" else b
    data = bytes(broken)
    lossy, prefix_at = repair.to_lossy_text(data, repair.find_sites(data))
    fixed, n, pending = repair.repair_with_baseline(lossy, prefix_at, "毫不相干的另一段文字")
    assert n == 0
    assert pending == 1
    assert repair.PLACEHOLDER in fixed


# ── 语料唯一前缀 ──────────────────────────────────────────


def test_corpus_fill_only_takes_unique_candidates(repair):
    """唯一候选才填；多候选必须留给人工。

    注意占位符的字符下标：`每▢运行▢说明` 里第二个占位符在下标 4，不是 5。
    """
    corpus = {b"\xe6\xac": {"次"}, b"\xef\xbc": {"（", "）", "："}}
    text = f"每{repair.PLACEHOLDER}运行{repair.PLACEHOLDER}说明"
    p1 = text.index(repair.PLACEHOLDER)
    p2 = text.index(repair.PLACEHOLDER, p1 + 1)
    prefix_at = {p1: b"\xe6\xac", p2: b"\xef\xbc"}
    out, filled, pending = repair.fill_from_corpus(text, prefix_at, corpus)
    assert filled == 1, "唯一候选才填"
    assert pending == 1, "多候选必须留给人工"
    assert out[p1] == "次"
    assert out[p2] == repair.PLACEHOLDER


# ── 上下文规则的准确率（核心保障）────────────────────────────


@pytest.mark.parametrize(
    ("rel", "min_checked"),
    [("docs/OPERATIONS.md", 40), ("docs/OBSERVABILITY.md", 30)],
)
def test_context_rules_never_contradict_baseline(repair, rel, min_checked):
    """在**真实损坏位置**上，规则推断必须与底本恢复完全一致。

    这是最硬的一道检验：两条独立路径（局部结构规则 vs 历史底本对齐）落在同一
    位置上，若有任何一处结论不同，说明规则会写错字，必须收紧或撤掉。
    实测基线：OPERATIONS 61 处可核对、OBSERVABILITY 44 处可核对，冲突 0。
    """
    path = REPO_ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} 不存在")
    data = path.read_bytes()
    sites = repair.find_sites(data)
    if not sites:
        pytest.skip(f"{rel} 已修复，无损坏点可比对")

    raw_baseline = repair.git_show(repair.BASELINE_COMMIT, rel)
    if raw_baseline is None:
        pytest.skip("取不到底本（git 不可用）")
    try:
        baseline = raw_baseline.decode("utf-8")
    except UnicodeDecodeError:
        pytest.skip("底本本身已损坏")

    lossy, prefix_at = repair.to_lossy_text(data, sites)
    ruled, _n, _ = repair.repair_by_context(lossy, prefix_at)
    truth, _m, _ = repair.repair_with_baseline(lossy, prefix_at, baseline)

    conflicts = []
    checked = 0
    for pos in prefix_at:
        r, t = ruled[pos], truth[pos]
        if r == repair.PLACEHOLDER or t == repair.PLACEHOLDER:
            continue
        checked += 1
        if r != t:
            conflicts.append((pos, r, t, truth[max(0, pos - 30) : pos + 10]))

    assert checked >= min_checked, f"可核对样本只有 {checked} 处，低于预期，检查是否有回归"
    assert not conflicts, f"规则与底本冲突 {len(conflicts)} 处：{conflicts[:3]}"


def test_context_rule_fills_closing_bracket(repair):
    text = f"检查项（每周一次{repair.PLACEHOLDER}\n下一行"
    prefix_at = {text.index(repair.PLACEHOLDER): b"\xef\xbc"}
    out, filled, _ = repair.repair_by_context(text, prefix_at)
    assert filled == 1
    assert "（每周一次）" in out


def test_context_rule_skips_bracket_when_ambiguous(repair):
    """占位符之后还有右括号时不能填 —— 它可能是括号内部的逗号。"""
    text = f"检查项（V2+{repair.PLACEHOLDER}超 90 天提醒）\n"
    prefix_at = {text.index(repair.PLACEHOLDER): b"\xef\xbc"}
    out, filled, pending = repair.repair_by_context(text, prefix_at)
    assert filled == 0
    assert pending == 1
    assert repair.PLACEHOLDER in out


def test_context_rule_fills_sentence_final_period(repair):
    text = f"这是一句说明{repair.PLACEHOLDER}\n下一段"
    prefix_at = {text.index(repair.PLACEHOLDER): b"\xe3\x80"}
    out, filled, _ = repair.repair_by_context(text, prefix_at)
    assert filled == 1
    assert out.startswith("这是一句说明。")


def test_context_rule_skips_mid_sentence_enumeration(repair):
    """句中位置无法区分顿号与句号，必须留空。"""
    text = f"日志{repair.PLACEHOLDER}指标、追踪各司其职\n"
    prefix_at = {text.index(repair.PLACEHOLDER): b"\xe3\x80"}
    _out, filled, pending = repair.repair_by_context(text, prefix_at)
    assert filled == 0
    assert pending == 1


# ── 答案合并的越界拒绝 ─────────────────────────────────────


def test_apply_choices_rejects_out_of_candidate_answer(repair):
    text = f"阈值{repair.PLACEHOLDER}95%"
    pos = text.index(repair.PLACEHOLDER)
    prefix_at = {pos: b"\xe2\x89"}  # ≈≤≥ 族
    out, applied, rejected = repair.apply_choices(text, prefix_at, {pos: "错"})
    assert applied == 0
    assert rejected == 1
    assert out == text, "越界答案不得改动文本"


def test_apply_choices_accepts_in_candidate_answer(repair):
    text = f"阈值{repair.PLACEHOLDER}95%"
    pos = text.index(repair.PLACEHOLDER)
    out, applied, rejected = repair.apply_choices(text, {pos: b"\xe2\x89"}, {pos: "≥"})
    assert (applied, rejected) == (1, 0)
    assert out == "阈值≥95%"


# ── 修复结果的机械校验 ─────────────────────────────────────


def test_verifier_accepts_correct_repair(verifier, tmp_path):
    clean = "说明文字。第二句，结束。\n"
    bp = tmp_path / "broken.md"
    fp = tmp_path / "fixed.md"
    bp.write_bytes(_corrupt(clean, every=2))
    _write_exact(fp, clean)
    assert verifier.verify(bp, fp) == 0


def test_verifier_rejects_substituted_character(verifier, tmp_path):
    clean = "说明文字。第二句，结束。\n"
    bp = tmp_path / "broken.md"
    fp = tmp_path / "wrong.md"
    bp.write_bytes(_corrupt(clean, every=2))
    _write_exact(fp, clean.replace("说", "错"))
    assert verifier.verify(bp, fp) != 0


def test_verifier_rejects_rewritten_prose(verifier, tmp_path):
    """改写未损坏的正文也必须被拦下 —— 修复不是重写的许可。"""
    clean = "说明文字。第二句，结束。\n"
    bp = tmp_path / "broken.md"
    fp = tmp_path / "rewritten.md"
    bp.write_bytes(_corrupt(clean, every=2))
    _write_exact(fp, "完全换了一段话。内容也不同，真的。\n")
    assert verifier.verify(bp, fp) != 0


def test_verifier_accepts_pending_placeholder(verifier, repair, tmp_path):
    """半成品里的待定占位符是合法状态，不该被当成错误的修复。

    `--apply` 在还有待定处时写出 `.partial`，里面留着 U+FFFD。校验器必须能
    区分"还没判定"和"填了个不相关的字"——否则半成品永远过不了校验，
    这个流程就没法用了。
    """
    clean = "说明文字。第二句，结束。\n"
    partial = clean.replace("。", repair.PLACEHOLDER, 1)
    bp = tmp_path / "broken.md"
    fp = tmp_path / "partial.md"
    bp.write_bytes(_corrupt(clean, every=2))
    _write_exact(fp, partial)
    assert verifier.verify(bp, fp) == 0


def test_verifier_still_rejects_wrong_char_in_partial(verifier, repair, tmp_path):
    """占位符可以留着，但不能换成候选集外的字。"""
    clean = "说明文字。第二句，结束。\n"
    bp = tmp_path / "broken.md"
    fp = tmp_path / "partial.md"
    bp.write_bytes(_corrupt(clean, every=2))
    _write_exact(fp, clean.replace("。", "錯", 1))
    assert verifier.verify(bp, fp) != 0
    assert repair.PLACEHOLDER  # 占位符常量存在，说明两者语义不同


def test_write_exact_preserves_crlf(repair, tmp_path):
    """写盘不得改动行尾 —— 实测踩过的坑：Windows 上 write_text 会把 \\n 变
    \\r\\n，CRLF 文档因此变成 \\r\\r\\n，521 处全中，校验直接判"正文被改动"。
    """
    text = "第一行。\r\n第二行。\r\n"
    p = tmp_path / "out.md"
    repair.write_exact(p, text)
    raw = p.read_bytes()
    assert raw == text.encode("utf-8")
    assert b"\r\r\n" not in raw


# ── 编码闸门 ───────────────────────────────────────────────


def test_checker_flags_new_corruption(checker, tmp_path):
    bad = tmp_path / "new_doc.md"
    bad.write_bytes(b"# \xe6\xb5\x8b\xe8\xaf\x95\xe3\x80?\n")
    assert checker.count_errors(bad.read_bytes()) == 1
    assert "非法字节" in checker.describe_first_error(bad.read_bytes())


def test_checker_passes_clean_file(checker, tmp_path):
    good = tmp_path / "ok.md"
    good.write_text("# 测试。一切正常，没有问题。\n", encoding="utf-8")
    assert checker.count_errors(good.read_bytes()) == 0


def test_known_broken_list_matches_reality(checker):
    """已登记的损坏文件清单必须与实际相符。

    清单为空是目标状态；若某个文件已修好却还留在清单里，这个断言会提醒删除。
    """
    for rel in checker.KNOWN_BROKEN:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        n = checker.count_errors(path.read_bytes())
        assert n > 0, f"{rel} 已无损坏，请从 KNOWN_BROKEN 清单中删除"
