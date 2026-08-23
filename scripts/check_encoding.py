"""拦截编码损坏的文本文件，防止它再次进入仓库。

## 为什么需要这个检查

仓库里已发现**三种**编码损坏，成因同源（写回文件时没用 UTF-8，
或用 errors='replace' 解码后又写回），但后果严重程度不同：

### 一型：非法 UTF-8（3 字节字符丢了第 3 字节）

`docs/OPERATIONS.md`、`docs/DATA_SOURCE_STRATEGY.md`，合计 902 处
（`docs/OBSERVABILITY.md` 原有的 214 处已于 2026-08-23 修完并移出登记）。
每个 3 字节中文字符的**第 3 字节被替换成 '?'**，前 2 字节完好。
文件因此变成非法 UTF-8 —— 至少还能被机械检测出来。

一度以为"前 2 字节把候选限制在 64 个以内，修复是做选择题"，
但实测证明**这道选择题做不了**：64 个候选里，同文档字符集收敛只能
唯一确定 9.1%（101/1115），结构重复标尺在 2~5 字窗口下确定 0 处，
而且损坏还额外**吞掉了相邻一个字节**（OBSERVABILITY.md 从 293 行塌成 268 行），
连上下文结构本身都被破坏。git 历史里也没有任何可解码的干净版本。
因此修复方式只能是**按实测真相重写**，绝不猜原字 ——
一个猜出来的字比一个 '?' 更坏，因为读者分不清哪个是原文。

### 二型：整字被替换成 '?'（**仍是合法 UTF-8**）

`docs/API_SPEC.md` 曾有 70 处（原始命中 129，其中 59 处是代码块误报）。
整个中文字符被替换成一个半角 `?`，结果**完全合法**，
`decode('utf-8')` 一点问题都没有 —— 一型的检查看不见它。
这一型更糟：没有前 2 字节做约束，候选字符是**全部汉字**，
除了从 git 底本对齐，没有任何办法证明原字是什么。

**已于 2026-08-22 清零**：API_SPEC.md 全部 70 处修完并移出登记清单，
二型现在是零豁免门禁。修法不是猜原字，而是**按实测重写整段** ——
损坏点都落在描述接口行为的中文散文里，那些行为可以逐条对着
`GET /openapi.json` 和真实请求量出来。

二型的判据是"半角 `?` 紧贴中文字符"（中文语境里几乎不会这样用问号）。
**代码块内不判**：mermaid 流程图的 `{全绿?}`、`{需立即修复?}` 是正常写法。
实测这条排除让误报归零。

### 三型：字面 U+FFFD 替换符

`docs/SYSTEM_DIRECTION_CHANGE.md` 2 处，是被吃掉的 emoji（该文档其余小节标题
都带 emoji，损坏处只剩 `## <FFFD> 成功指标`、`## <FFFD>️ 实施路线图`）。
成因是**用 errors='replace' 解码后又写回**，与前两型不同。

三型的判据最干净：正常写作绝不会输入 U+FFFD，所以**无需上下文、零误报**，
连代码块都不用排除。它同样是合法 UTF-8，前两型的检查都看不见它。
损失也最小（2 处 emoji，不影响任何语义），修复成本几乎为零。

## 这类损坏为什么危险

**静默**：文件照样能打开、git 照常提交，只是内容里多了一堆 `?`。
一型在 git 历史里潜伏了 3 个提交，二型潜伏了 **6 个**，三型从
`a9f2c8b` 起就在（数量从未变化）。且各型都有文件的所有历史版本已损坏、
无法恢复。

**教训**：每次以为"查完了"，换个判据又能查出一种。三型是在写完二型检测后
主动追问"还有没有别的形态"才发现的 —— 检测判据的盲区就是损坏的藏身处。

## 用法

    python scripts/check_encoding.py            # 检查全仓（跳过已知损坏文件）
    python scripts/check_encoding.py --strict    # 连已知损坏文件也报错
    python scripts/check_encoding.py <路径...>   # 只检查指定文件（pre-commit 用）

退出码 0 = 全部合法；1 = 有损坏文件。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 需要检查的文本扩展名
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yml",
    ".yaml",
    ".txt",
    ".ps1",
    ".bat",
    ".css",
    ".sql",
    ".toml",
    ".cfg",
    ".ini",
}

SKIP_DIRS = {
    "node_modules",
    "venv",
    ".venv",
    ".git",
    "htmlcov",
    ".pytest_cache",
    ".pytest_tmp",
    ".next",
    "__pycache__",
    ".ruff_cache",
    ".mypy_cache",
}

# 已知的历史损坏文件：默认只警告不阻断，避免这道检查一上线就把所有提交卡死。
# 修复完成后请从这里删除对应条目 —— 清单为空是目标状态。
#
# 2026-08-23：`docs/OBSERVABILITY.md` 的 214 处一型损坏已全部修完并**移出登记**。
# 修法与 API_SPEC 相同：不猜原字，而是按实测真相重写。
# 一型损坏（每个中文字丢第 3 字节，且吞掉相邻一个字节）在这个仓库里是
# **不可自动恢复**的 —— 实测每处的第 3 字节有 64 个合法取值，
# 同文档字符集收敛只能唯一确定 9.1%，结构重复标尺在 2~5 字窗口下确定 0 处，
# 而 git 历史里没有任何一个可解码的干净版本（旧版本是改写前的草稿）。
# 任何"自动修复"都只能是编造，而读者无法区分机器编的字与原文。
#
# 顺带修掉的内容谎言远多于编码损坏：文档列的 39 个指标名里 35 个在代码中
# 根本不存在，15 个日志事件名一个都不存在。**登记豁免会掩盖内容问题** ——
# 只要文件挂在这张清单上，就没人会去逐行读它。
# 现已由 `backend/tests/test_observability_doc_parity.py` 双向钉住。
# 2026-08-23（第二轮）：`docs/OPERATIONS.md` 的 404 处一型损坏已全部修完并
# **移出登记**。同样是重写而非猜字 —— 每条命令、端口、路径、指标名、cron
# 表达式都实测过一遍。
#
# 这一份的内容失真比 OBSERVABILITY.md 更严重：19 个指标名里 18 个不存在，
# 4 个 API 路径不存在，2 个"已提供的巡检脚本"根本没有这个文件，端口全篇
# 写错（8000 vs 真实 8002），数据库文件名也是错的。最危险的一条是
# 「LLM 超预算自动停用已生效」—— 代码里根本没有这个拦截，值班照着信就完了。
#
# 又一次印证：**登记豁免掩盖的是内容问题，不只是字节问题。**
# 现已由 `backend/tests/test_operations_doc_parity.py` 双向钉住。
KNOWN_BROKEN = {
    "docs/DATA_SOURCE_STRATEGY.md",
}

# 二型（整字变 '?'，仍是合法 UTF-8）的已知损坏文件
#
# 2026-08-22：`docs/API_SPEC.md` 的 70 处二型损坏已全部修完并**移出登记**，
# 这一型现在是零豁免的硬门禁。之所以能修完，是因为损坏点集中在中文散文里，
# 而每一段散文描述的都是可实测的接口行为 —— 重写时逐条对着
# `GET /openapi.json` 与真实请求校对，而不是猜原字。
#
# 顺带修掉的谎言比编码损坏本身更多：13 条不存在的端点、若干虚构的
# query 参数与字段名。**登记豁免会掩盖内容问题** —— 只要文件挂在这张
# 清单上，就没人会去逐行读它，于是错的内容跟错的字节一起躺着。
KNOWN_BROKEN_MOJIBAKE: set[str] = set()

# 三型（字面 U+FFFD 替换符）的已知损坏文件
KNOWN_BROKEN_REPLACEMENT = {
    "docs/SYSTEM_DIRECTION_CHANGE.md",
}

# 中日韩汉字 + CJK 标点 + 全角字符
_CJK = r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]"
# 半角 '?' 紧贴中文字符 —— 二型损坏的特征。
# 中文语境里几乎不会这样用半角问号，所以这个判据很干净。
MOJIBAKE_PAT = re.compile(f"(?<={_CJK})\\?|\\?(?={_CJK})")
# 行内代码 `...`
_INLINE_CODE = re.compile(r"`[^`\n]*`")

# 三型：字面的 Unicode 替换符 U+FFFD（EF BF BD）。
# 判据无需上下文 —— 正常写作绝不会输入这个字符，它只可能来自
# "用 errors='replace' 解码后又写回文件"。因此零误报风险。
REPLACEMENT_CHAR = "\ufffd"


def blank_code_blocks(text: str) -> str:
    """把围栏代码块与行内代码替换成等长空白（保持下标不变）。

    **必须排除代码**：mermaid 流程图里 `{全绿?}`、`{需立即修复?}` 是正常写法，
    文档里引用判据时写的 `` `{全绿?}` `` 也是。实测加上这两条排除后，
    三个误报文件（GIT_STRATEGY.md 2 处、ENCODING_REPAIR.md 1 处、
    以及本文件自己的文档字符串 4 处）全部归零 —— 当时只剩真正损坏的
    API_SPEC.md，该文件已于 2026-08-22 修完，二型现在全仓为零。

    本文件自己被自己误报这件事，恰好说明"描述判据的文字"和"符合判据的损坏"
    长得一样 —— 不排除代码就没法自洽。
    """
    out = []
    fenced = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append(" " * len(line))
        elif fenced:
            out.append(" " * len(line))
        else:
            out.append(_INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line))
    return "\n".join(out)


def count_mojibake(text: str) -> int:
    """统计二型损坏点数（整字被替换成 '?'，文件本身仍是合法 UTF-8）。"""
    return len(MOJIBAKE_PAT.findall(blank_code_blocks(text)))


def describe_first_mojibake(text: str) -> str:
    masked = blank_code_blocks(text)
    m = MOJIBAKE_PAT.search(masked)
    if m is None:
        return ""
    line = text[: m.start()].count("\n") + 1
    ctx = text[max(0, m.start() - 26) : m.start() + 14].replace("\n", "\\n")
    return f"第 {line} 行 中文字符被替换成 '?'；上下文 …{ctx}…"


def count_replacement_chars(text: str) -> int:
    """统计三型损坏点数（字面 U+FFFD 替换符）。

    无需排除代码块：正常写作不会输入这个字符。
    """
    return text.count(REPLACEMENT_CHAR)


def describe_first_replacement(text: str) -> str:
    idx = text.find(REPLACEMENT_CHAR)
    if idx < 0:
        return ""
    line = text[:idx].count("\n") + 1
    ctx = text[max(0, idx - 26) : idx + 14].replace("\n", "\\n")
    return f"第 {line} 行 含 U+FFFD 替换符（原字符已丢失）；上下文 …{ctx}…"


def describe_first_error(data: bytes) -> str:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        line = data[: e.start].count(b"\n") + 1
        ctx = data[max(0, e.start - 24) : e.start + 12]
        return f"第 {line} 行 (offset {e.start}) 非法字节 {data[e.start : e.end]!r}；上下文 {ctx!r}"
    return ""


def count_errors(data: bytes) -> int:
    n = 0
    i = 0
    while i < len(data):
        try:
            data[i:].decode("utf-8")
            break
        except UnicodeDecodeError as e:
            n += 1
            i += e.start + max(1, e.end - e.start)
    return n


def iter_repo_files() -> list[Path]:
    out: list[Path] = []
    stack = [REPO_ROOT]
    while stack:
        cur = stack.pop()
        try:
            entries = list(cur.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                if p.name not in SKIP_DIRS:
                    stack.append(p)
            elif p.suffix.lower() in TEXT_SUFFIXES:
                out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="要检查的文件（缺省=全仓扫描）")
    ap.add_argument("--strict", action="store_true", help="已知损坏文件也判为失败")
    args = ap.parse_args()

    files = [Path(p) for p in args.paths] if args.paths else iter_repo_files()

    failures: list[tuple[str, int, str]] = []
    known_hits: list[tuple[str, int]] = []
    moji_failures: list[tuple[str, int, str]] = []
    moji_known: list[tuple[str, int]] = []
    repl_failures: list[tuple[str, int, str]] = []
    repl_known: list[tuple[str, int]] = []

    for path in files:
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue

        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # 一型：非法 UTF-8
            n = count_errors(data)
            if rel in KNOWN_BROKEN and not args.strict:
                known_hits.append((rel, n))
            else:
                failures.append((rel, n, describe_first_error(data)))
            continue

        # 二型：合法 UTF-8，但整字被替换成 '?'
        n_moji = count_mojibake(text)
        if n_moji:
            if rel in KNOWN_BROKEN_MOJIBAKE and not args.strict:
                moji_known.append((rel, n_moji))
            else:
                moji_failures.append((rel, n_moji, describe_first_mojibake(text)))

        # 三型：字面 U+FFFD 替换符
        n_repl = count_replacement_chars(text)
        if n_repl:
            if rel in KNOWN_BROKEN_REPLACEMENT and not args.strict:
                repl_known.append((rel, n_repl))
            else:
                repl_failures.append((rel, n_repl, describe_first_replacement(text)))

    for rel, n in known_hits:
        print(f"[known] {rel}：{n} 处非法 UTF-8（一型：丢第 3 字节，已登记待修复）")
    for rel, n in moji_known:
        print(f"[known] {rel}：{n} 处整字变 '?'（二型：仍是合法 UTF-8，已登记待修复）")
    for rel, n in repl_known:
        print(f"[known] {rel}：{n} 处 U+FFFD 替换符（三型：已登记待修复）")

    if failures or moji_failures or repl_failures:
        print()
        total = len(failures) + len(moji_failures) + len(repl_failures)
        print(f"[FAIL] {total} 个文件存在编码损坏：")
        for rel, n, detail in failures:
            print(f"  {rel}  （一型：非法 UTF-8，{n} 处）")
            print(f"    {detail}")
        for rel, n, detail in moji_failures:
            print(f"  {rel}  （二型：整字变 '?'，{n} 处）")
            print(f"    {detail}")
        for rel, n, detail in repl_failures:
            print(f"  {rel}  （三型：U+FFFD 替换符，{n} 处）")
            print(f"    {detail}")
        print()
        print("修复提示：用 UTF-8 重新保存该文件。中文字符被替换成 '?' 或 U+FFFD 说明写入时")
        print("用了非 UTF-8 编码（或用 errors='replace' 解码后写回），原字符已不可逆丢失 ——")
        print("参见 scripts/repair_utf8_docs.py 与 scripts/verify_utf8_repair.py，")
        print("以及 docs/ENCODING_REPAIR.md。")
        return 1

    pending = len(known_hits) + len(moji_known) + len(repl_known)
    if pending:
        print()
        print(f"检查通过（{len(files)} 个文件），但仍有 {pending} 个已登记的损坏文件待修复。")
    else:
        print(f"检查通过：{len(files)} 个文本文件编码全部正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
