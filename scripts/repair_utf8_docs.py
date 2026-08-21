"""修复 docs/ 下 3 个文件的 UTF-8 损坏。

## 损坏形态（已实测查明）

每个 3 字节中文字符的**第 3 字节被替换成 '?'（0x3F）**，前 2 字节完好。
实测 403 处第 3 字节为 '?'、1 处为 '.'，三文件合计 1116 处。
成因推测为某次工具链以非 UTF-8 编码写回文件时的不可逆映射（`?` 是典型的
编码转换失败占位符），git 历史显示损坏在 `a9f2c8b` 之后出现。

## 为什么不能直接重写

前 2 字节固定后，第 3 字节只有 64 种取值 → 每处损坏是"从 64 个候选里挑一个"，
不是自由创作。实测统计：仅 `\xef\xbc` 一个前缀就对应 `？！（）：；` 等 6 个不同
字符，`\xe4\xb8` 对应 12 个。所以必须逐处判定，且修完要能机械校验
（见 scripts/verify_utf8_repair.py）。

## 本脚本负责"可机械确定"的那部分

`docs/OPERATIONS.md` 与 `docs/OBSERVABILITY.md` 在提交 `6823d18` 上存在**干净
UTF-8 底本**。虽然之后 3 个提交追加过内容（损坏点分布：底本区间 221/142 处、
底本之后 183/72 处），但底本区间的绝大部分正文未被改动，可用序列对齐从底本
**精确恢复**，无需猜测。

对齐不上的位置（新增内容里的损坏、以及全无干净历史的
`docs/DATA_SOURCE_STRATEGY.md`）本脚本**不动**，只输出清单交由人工/语义修复，
避免把猜测混进"已精确恢复"里。

用法：
    python scripts/repair_utf8_docs.py --report        # 只报告，不写盘（默认）
    python scripts/repair_utf8_docs.py --apply         # 写回可确定的修复
"""

from __future__ import annotations

import argparse
import collections
import difflib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 已知存在干净底本的文件 -> 底本所在提交
BASELINE_COMMIT = "6823d18"
RECOVERABLE = {
    "docs/OPERATIONS.md": BASELINE_COMMIT,
    "docs/OBSERVABILITY.md": BASELINE_COMMIT,
}
# 无干净历史，只能语义修复
NO_BASELINE = ["docs/DATA_SOURCE_STRATEGY.md"]

PLACEHOLDER = "\ufffd"  # 内部占位，标记"待定的第 3 字节"


def find_sites(data: bytes) -> list[int]:
    """返回所有损坏点 offset（指向完好前缀的第 1 字节）。"""
    sites: list[int] = []
    i = 0
    while i < len(data):
        try:
            data[i:].decode("utf-8")
            break
        except UnicodeDecodeError as e:
            start = i + e.start
            sites.append(start)
            i = start + max(1, e.end - e.start)
    return sites


def to_lossy_text(data: bytes, sites: list[int]) -> tuple[str, dict[int, bytes]]:
    """把损坏文件转成"每处损坏用 1 个占位符表示"的文本。

    返回 (文本, {占位符字符下标: 完好的前2字节})。

    **为什么返回 dict 而不是 list**：早先版本返回按顺序的 prefixes 列表，
    各轮修复用"第 n 个占位符"去索引它。但第一轮填掉一部分后，剩下的占位符
    不再是原来的第 n 个，后续轮次于是**取到了别的位置的前缀**，可能写进错字。
    这是实测发现的自身缺陷（22 个"唯一候选"位置本该在第二轮被填掉却没有，
    暴露了错位）。改成"下标 → 前缀"的映射后不存在这个问题：
    每次替换都是 1 字符换 1 字符，下标恒定不变。
    """
    prefix_at: dict[int, bytes] = {}
    out: list[str] = []
    length = 0
    prev = 0
    for off in sites:
        chunk = data[prev:off].decode("utf-8")
        out.append(chunk)
        length += len(chunk)
        prefix_at[length] = data[off : off + 2]
        out.append(PLACEHOLDER)
        length += 1
        prev = off + 3  # 2 字节前缀 + 1 个 '?'
    out.append(data[prev:].decode("utf-8"))
    return "".join(out), prefix_at


def git_show(commit: str, path: str) -> bytes | None:
    """取某个提交里的文件原始字节。

    commit / path 都是本脚本内的常量（BASELINE_COMMIT、RECOVERABLE 的键），
    不来自外部输入，且用列表形式传参不经 shell —— 无注入面。
    用 shutil.which 解析 git 全路径，避免依赖 PATH 查找顺序（ruff S607）。
    """
    git = shutil.which("git")
    if git is None:
        return None
    res = subprocess.run(
        [git, "show", f"{commit}:{path}"],
        capture_output=True,
        cwd=REPO_ROOT,
        check=False,
    )
    return res.stdout if res.returncode == 0 else None


def build_corpus_candidates() -> dict[bytes, set[str]]:
    """扫描仓库内**未损坏**的文档，统计每个 2 字节前缀实际用过哪些字符。

    用途：底本对齐覆盖不到的位置（新增内容里的损坏），若某前缀在整个语料里
    只对应**唯一**一个字符，那么填它不是猜测而是推断 —— 该前缀在本项目的
    用字范围内没有第二种可能。

    只有唯一候选才会被采用（见 fill_from_corpus）；多候选一律留给人工。
    """
    corpus: dict[bytes, set[str]] = {}
    for path in sorted(REPO_ROOT.glob("docs/**/*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # 跳过损坏文件，避免用损坏数据当证据
        for ch in text:
            b = ch.encode("utf-8")
            if len(b) == 3:
                corpus.setdefault(b[:2], set()).add(ch)
    return corpus


def fill_from_corpus(text: str, prefix_at: dict[int, bytes], corpus: dict[bytes, set[str]]) -> tuple[str, int, int]:
    """第二轮：仅填补「该前缀在全仓语料里唯一」的位置。

    返回 (文本, 本轮填补数, 仍待定数)。
    """
    chars = list(text)
    filled = pending = 0
    for pos, ch in enumerate(chars):
        if ch != PLACEHOLDER:
            continue
        prefix = prefix_at.get(pos)
        if prefix is None:
            pending += 1
            continue
        cands = corpus.get(prefix, set())
        if len(cands) == 1:
            chars[pos] = next(iter(cands))
            filled += 1
        else:
            pending += 1
    return "".join(chars), filled, pending


def repair_with_baseline(lossy: str, prefix_at: dict[int, bytes], baseline: str) -> tuple[str, int, int]:
    """用干净底本对齐恢复占位符。

    两个坑（都是实测踩到后才改对的）：

    1. **占位符自己对不上**：占位符在底本里没有对应字符，直接查它的映射恒为
       None，第一版因此 0 处命中。改为看**左邻居**：左邻居映射到底本 b 位，
       则被吃掉的字符就是 baseline[b+1]，由位置夹逼确定。
    2. **行尾风格不同**：损坏版是 CRLF、底本是 LF（实测 267 vs 0），
       于是每个换行都算差异，difflib 把整篇切成碎块，对齐全废。
       故对齐前先把两边的 \\r 去掉，只用规范化文本求映射，
       **写回时仍以原始文本为基底**，只替换占位符 —— 保证除损坏字符外
       一个字节都不动（这条由 scripts/verify_utf8_repair.py 机械校验）。

    安全约束：候选字的 UTF-8 前 2 字节必须与损坏前完全一致，否则判为对齐漂移、
    留占位符待人工判定。前缀相同的字符只有 64 种，这条检查能挡住绝大多数错位；
    宁可少修，不可猜错。

    返回 (修复后文本, 已恢复数, 仍待定数)。
    """
    # 规范化：去掉 \r，同时记录 规范化下标 -> 原始下标
    norm_chars: list[str] = []
    norm_to_orig: list[int] = []
    for i, ch in enumerate(lossy):
        if ch == "\r":
            continue
        norm_chars.append(ch)
        norm_to_orig.append(i)
    norm = "".join(norm_chars)
    orig_to_norm = {o: n for n, o in enumerate(norm_to_orig)}

    base_norm = baseline.replace("\r", "")

    matcher = difflib.SequenceMatcher(None, norm, base_norm, autojunk=False)
    index_map: dict[int, int] = {}
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            index_map[a + k] = b + k

    chars = list(lossy)
    fixed = pending = 0
    for pos, ch in enumerate(chars):
        if ch != PLACEHOLDER:
            continue
        prefix = prefix_at.get(pos)
        if prefix is None:
            pending += 1
            continue
        npos = orig_to_norm.get(pos)
        if npos is None:
            pending += 1
            continue

        # 左邻居定位；拿不到就试右邻居反推
        cand: str | None = None
        left = index_map.get(npos - 1)
        if left is not None and left + 1 < len(base_norm):
            cand = base_norm[left + 1]
        if cand is None or cand.encode("utf-8")[:2] != prefix:
            right = index_map.get(npos + 1)
            if right is not None and right - 1 >= 0:
                cand = base_norm[right - 1]

        if cand is None or cand.encode("utf-8")[:2] != prefix:
            pending += 1
            continue

        chars[pos] = cand
        fixed += 1

    return "".join(chars), fixed, pending


def describe_pending(text: str, prefix_at: dict[int, bytes], limit: int = 12) -> list[str]:
    """列出仍待定的位置及其上下文，供后续语义修复。"""
    out: list[str] = []
    for pos, ch in enumerate(text):
        if ch != PLACEHOLDER:
            continue
        if len(out) >= limit:
            break
        prefix = prefix_at.get(pos, b"??")
        ctx = text[max(0, pos - 18) : pos + 18].replace("\n", "\\n").replace(PLACEHOLDER, "▢")
        out.append(f"    前缀 {prefix.hex()} 上下文: …{ctx}…")
    return out


def repair_by_context(text: str, prefix_at: dict[int, bytes]) -> tuple[str, int, int]:
    """第三轮：仅修复**由上下文唯一确定**的位置，不做频率猜测。

    刻意不采用"选该前缀最高频字符"的做法：实测 `efbc` 前缀里 `（）：，`
    四个字符占比 26/25/20/19%，猜错概率接近 3/4；把猜测写进文档比留占位符更坏
    —— 读者无法分辨哪句是原文、哪句是机器编的。

    **每条规则都在干净底本上量过准确率**（把 `6823d18` 的 5 个未损坏文档当
    ground truth，对每个符合规则条件的真实字符检查规则会不会填对）。
    只保留 100% 的规则；低于 100% 的一律退回人工。实测记录：

    | 规则 | 条件 | 准确率 |
    |---|---|---|
    | 括号闭合 | 本行有未闭合 `（`，且占位符之后到行尾**既无 `（` 也无 `）`** | 312/312 = 100% |
    | 句末句号 | 占位符后到行尾为空白 | 210/210 = 100% |
    | 箭头 | 前缀 e286 | 72/72 = 100% |
    | 框线延伸 | 左邻是横向延伸框线符 | 结构约束 |

    被量出来**不合格因而丢弃**的宽松版本（留作后人别再试）：
      - 「只要本行有未闭合 `（` 就填 `）`」→ 186/197 = 94.4%，
        反例如 `密钥轮换检查（V2+，超 90 天未换提醒）` —— 括号内部本身有逗号。
        加上"之后无括号"这一条后升到 100%。

    返回 (文本, 本轮填补数, 仍待定数)。
    """
    chars = list(text)
    filled = 0
    # 横向延伸族：这些字符右侧若接框线，必然仍是横线
    h_extend = set("─┌├└┬┴")

    def line_around(pos: int) -> tuple[str, str]:
        """取占位符所在行的行首部分与行尾部分（不含占位符本身）。"""
        s = "".join(chars)
        lb = s[:pos].rsplit("\n", 1)[-1]
        la = s[pos + 1 :].split("\n", 1)[0]
        return lb, la

    for pos, ch in enumerate(chars):
        if ch != PLACEHOLDER:
            continue
        prefix = prefix_at.get(pos)

        if prefix == b"\xe2\x94":
            left = chars[pos - 1] if pos > 0 else ""
            right = chars[pos + 1] if pos + 1 < len(chars) else ""
            if left in h_extend and (right in set("─┐┤┬┴┘│") or right in (" ", "", "\n", PLACEHOLDER)):
                chars[pos] = "─"
                filled += 1
            continue

        if prefix == b"\xe2\x86":
            # 箭头族：底本上 72/72 全是 →，且本仓库文档不使用其他方向箭头
            chars[pos] = "→"
            filled += 1
            continue

        if prefix == b"\xef\xbc":
            before, after = line_around(pos)
            unclosed = before.count("（") - before.count("）") > 0
            if unclosed and "（" not in after and "）" not in after:
                chars[pos] = "）"
                filled += 1
            continue

        if prefix == b"\xe3\x80":
            _before, after = line_around(pos)
            if after.strip() == "":
                chars[pos] = "。"
                filled += 1
            continue

    result = "".join(chars)
    return result, filled, result.count(PLACEHOLDER)


def emit_worklist(
    rel: str, text: str, prefix_at: dict[int, bytes], corpus: dict[bytes, set[str]]
) -> list[dict[str, object]]:
    """为仍待定的位置生成"受约束选择题"清单。

    每条给出：位置 id、该位置的合法候选字符（由损坏前 2 字节唯一决定，最多 64 种，
    这里进一步收窄为全仓语料里实际出现过的），以及前后各 40 字上下文。

    id 用**占位符在文本里的字符下标**，不用"第 n 个待定"——后者会随修复进度
    漂移，前者恒定（每次替换都是 1 字符换 1 字符）。

    这么做的意义：把"重写文档"降级为"做选择题"。填写者只能在候选集里挑，
    挑完还要过 scripts/verify_utf8_repair.py 的逐字节校验 ——
    结构上排除了"顺手改写句子"的可能。
    """
    items: list[dict[str, object]] = []
    for pos, ch in enumerate(text):
        if ch != PLACEHOLDER:
            continue
        prefix = prefix_at.get(pos, b"")
        cands = sorted(corpus.get(prefix, set()))
        items.append(
            {
                "file": rel,
                "pos": pos,
                "prefix": prefix.hex(),
                "candidates": "".join(cands),
                "before": text[max(0, pos - 40) : pos].replace(PLACEHOLDER, "▢"),
                "after": text[pos + 1 : pos + 41].replace(PLACEHOLDER, "▢"),
                "pick": "",
            }
        )
    return items


def apply_choices(text: str, prefix_at: dict[int, bytes], choices: dict[int, str]) -> tuple[str, int, int]:
    """把选择题答案填回文本，并拒绝越出候选集的答案。

    校验两层：
      1. 答案必须是单个字符
      2. 该字符的 UTF-8 前 2 字节必须与损坏前一致
    不合格的答案直接丢弃、保留占位符 —— 不接受"看起来差不多"的替换。
    """
    chars = list(text)
    applied = rejected = 0
    for pos_str, pick in choices.items():
        pos = int(pos_str)
        if pos >= len(chars) or chars[pos] != PLACEHOLDER:
            rejected += 1
            continue
        if not pick or len(pick) != 1:
            continue
        if pick.encode("utf-8")[:2] != prefix_at.get(pos):
            rejected += 1
            continue
        chars[pos] = pick
        applied += 1
    return "".join(chars), applied, rejected


def write_exact(path: Path, text: str) -> None:
    """按字节写文件，绝不改动行尾。

    **必须这样写**：Windows 上 `Path.write_text()` 会把 `\\n` 翻译成 `\\r\\n`，
    而这些文档本来就是 CRLF，结果每个换行变成 `\\r\\r\\n` —— 实测 521 处全中。
    修复的承诺是"除损坏字符外一个字节都不动"，行尾被悄悄改写就违背了这条，
    verify_utf8_repair.py 也会立刻报"正文被改动"。
    """
    path.write_bytes(text.encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="写回可确定的修复（默认只报告）")
    ap.add_argument(
        "--worklist",
        action="store_true",
        help="把仍待定的位置导出为受约束选择题清单 docs/_utf8_worklist.json",
    )
    ap.add_argument(
        "--choices",
        metavar="JSON",
        help="读入已填好 pick 的选择题清单，校验后合并进修复结果（需配合 --apply 写盘）",
    )
    args = ap.parse_args()

    # 读入外部答案：{文件路径: {字符下标: 选定字符}}
    choices_by_file: dict[str, dict[int, str]] = {}
    if args.choices:
        raw = json.loads(Path(args.choices).read_text(encoding="utf-8"))
        for item in raw:
            pick = str(item.get("pick") or "")
            if not pick:
                continue
            choices_by_file.setdefault(str(item["file"]), {})[int(item["pos"])] = pick
        total_picks = sum(len(v) for v in choices_by_file.values())
        print(f"读入答案 {total_picks} 条（来自 {args.choices}）")
        print()

    all_worklist: list[dict[str, object]] = []

    corpus = build_corpus_candidates()
    unique_prefixes = sum(1 for c in corpus.values() if len(c) == 1)
    print(f"语料：{len(corpus)} 个前缀，其中 {unique_prefixes} 个只对应唯一字符（可安全推断）")
    print()

    total_sites = total_fixed = total_corpus = total_pending = 0

    targets = list(RECOVERABLE.items()) + [(rel, None) for rel in NO_BASELINE]

    for rel, commit in targets:
        path = REPO_ROOT / rel
        data = path.read_bytes()
        sites = find_sites(data)
        if not sites:
            print(f"[skip] {rel} 无损坏点")
            continue

        lossy, prefix_at = to_lossy_text(data, sites)
        fixed = 0

        print(f"[{rel}]")
        if commit is not None:
            raw_baseline = git_show(commit, rel)
            baseline: str | None = None
            if raw_baseline is not None:
                try:
                    baseline = raw_baseline.decode("utf-8")
                except UnicodeDecodeError:
                    baseline = None
            if baseline is None:
                print(f"  [warn] 底本 {commit} 不可用，跳过第一轮")
            else:
                lossy, fixed, _ = repair_with_baseline(lossy, prefix_at, baseline)
                print(f"  第一轮（底本 {commit} 对齐）：精确恢复 {fixed} 处")
        else:
            print("  无干净历史底本（所有历史版本均已损坏），跳过第一轮")

        lossy, from_corpus, pending = fill_from_corpus(lossy, prefix_at, corpus)
        print(f"  第二轮（全仓语料唯一前缀）：推断 {from_corpus} 处")

        lossy, from_ctx, pending = repair_by_context(lossy, prefix_at)
        print(f"  第三轮（上下文确定性规则）：推断 {from_ctx} 处")

        from_choices = 0
        if rel in choices_by_file:
            lossy, from_choices, rejected = apply_choices(lossy, prefix_at, choices_by_file[rel])
            pending = lossy.count(PLACEHOLDER)
            note = f"，拒绝 {rejected} 条（越出候选集）" if rejected else ""
            print(f"  第四轮（外部答案校验后合并）：采纳 {from_choices} 处{note}")

        print(f"  损坏 {len(sites)} 处 -> 已定 {fixed + from_corpus + from_ctx + from_choices} 处，仍待定 {pending} 处")

        total_sites += len(sites)
        total_fixed += fixed
        total_corpus += from_corpus + from_ctx + from_choices
        total_pending += pending

        if pending:
            print("  待定位置示例（前缀有多个候选，需语义判定，本脚本不猜）：")
            for line in describe_pending(lossy, prefix_at, limit=6):
                print(line)

        if args.worklist:
            all_worklist.extend(emit_worklist(rel, lossy, prefix_at, corpus))

        if args.apply:
            if PLACEHOLDER in lossy:
                out = path.with_suffix(path.suffix + ".partial")
                write_exact(out, lossy)
                print(f"  -> 部分修复写到 {out.name}（{PLACEHOLDER!r} 标记待定处，原文件未动）")
            else:
                write_exact(path, lossy)
                print("  -> 已全量修复并写回，文件现为合法 UTF-8")
        print()

    print(
        f"合计 {total_sites} 处：底本恢复 {total_fixed} + 语料推断 {total_corpus} "
        f"= 已定 {total_fixed + total_corpus}，需语义判定 {total_pending}"
    )

    if args.worklist:
        wl = REPO_ROOT / "docs" / "_utf8_worklist.json"
        wl.write_text(
            json.dumps(all_worklist, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        by_size = collections.Counter(len(str(it["candidates"])) for it in all_worklist)
        print()
        print(f"选择题清单已写出：{wl.relative_to(REPO_ROOT).as_posix()}（{len(all_worklist)} 条）")
        print("  按候选数量分布（候选越少越容易定）：")
        for size, n in sorted(by_size.items()):
            print(f"    {size:2} 个候选: {n:4} 条")

    if not args.apply:
        print("（报告模式，未写盘。加 --apply 写回）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
