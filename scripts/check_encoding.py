"""拦截编码损坏的文本文件，防止它再次进入仓库。

## 为什么需要这个检查

仓库里已发现**三种**编码损坏，成因同源（写回文件时没用 UTF-8，
或用 errors='replace' 解码后又写回），但后果严重程度不同：

### 一型：非法 UTF-8（3 字节字符丢了第 3 字节）

历史上共 3 份文档、合计 1116 处（`docs/OBSERVABILITY.md` 214 处、
`docs/OPERATIONS.md` 404 处、`docs/DATA_SOURCE_STRATEGY.md` 498 处），
**全部于 2026-08-23 修完，一型现在是零豁免门禁。**
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

### 四型：含中文的 PowerShell / 批处理脚本没有 UTF-8 BOM

前三型是"文件内容已经坏了"。四型不一样：**文件内容完全正确、合法 UTF-8、
一个坏字节都没有 —— 但 Windows PowerShell 5.1 读它的时候会把它读坏。**

2026-08-24 实测撞上一次，代价很大：改完 `scripts/auto_backup.ps1` 之后
跑验证，脚本**跳过了前 150 行直接执行末尾**，返回 exit 0 说"备份成功"，
而实际上 Docker 根本连不上、什么都没备份。

成因（逐字节验证过）：Windows PowerShell 5.1 在**没有 BOM** 时按系统
ANSI 代码页（简体中文机器上是 GBK/936）解码脚本，不是 UTF-8。
GBK 是双字节编码，规则是：**任何 >= 0x80 的字节都无条件吃掉紧随其后的
一个字节**，不管那个字节是什么 —— 包括 ASCII 引号。

而一个 UTF-8 中文字符是 **3 字节**（奇数），GBK 按 2 字节一组啃，
于是"引号会不会被吃掉"取决于**它前面有多少字节的中文**：

    "中"     E4 B8 AD 22           → 引号被吃（3 字节，奇）
    "中文"   E4 B8 AD E6 96 87 22  → 引号保留（6 字节，偶）
    "中文字" … E5 AD 97 22         → 引号被吃（9 字节，奇）

一旦结束引号被吃掉，字符串就不闭合，继续往下吞，
把后面几十行代码全吃进一个字符串字面量里 ——
而且**语法完全合法**（`PSParser::Tokenize` 报 0 个错误），
所以既不报错、也不警告，只是静静地不执行那几十行。

**这条奇偶性是四型最恶劣的地方**：它意味着同一个文件今天没事、
明天在某行加一个字就炸，而炸法是静默跳过代码。
所以判据不可能是"检查有没有某种危险组合"，只能是"必须有 BOM"。

判据：`.ps1` / `.psm1` / `.bat` / `.cmd` 只要含任何非 ASCII 字节，
就**必须**有 UTF-8 BOM（`EF BB BF`）。BOM 让 PowerShell 5.1 与 7.x
都走 UTF-8，问题彻底消失。

为什么不改成"脚本里不许写中文"：那是把成本转嫁给可读性，
而且挡不住 —— 下一个人照样会写。BOM 是 3 个字节的事，一次解决。

⚠️ **不要用 Python 的 `bytes.decode("gbk")` 去验证 PowerShell 的行为。**
这是核对四型时踩的第二个坑，比第一个隐蔽：

    同一串字节 EF BC 89 22（'）' + '"'）
      .NET cp936（PowerShell 实际用的）→ 引号**被吃掉**
      Python gbk codec + errors="replace" → 引号**保留**

原因是前导字节后跟非法尾字节时两者策略不同：.NET 宽容，无条件消费 2 字节；
Python 严格，抛 `UnicodeDecodeError`，`replace` 只消费那 1 个前导字节，
于是引号被单独解码出来活了下来。
拿 Python 去"验证" .NET 会得到相反结论 ——
**验证用的解码器必须和被验证的解码器是同一个**，
否则验证的是另一件事。因此 `gbk_eaten_byte_offsets()` 直接实现 .NET 的
DBCS 规则，回归测试用的是实测记录下来的真值表，不是任何 codec。

⚠️ 一型/二型/三型都会**跳过**这一型的检查（文件已经是坏的，
先修内容再谈 BOM），避免同一个文件报两遍不同性质的问题。

## 这类损坏为什么危险

**静默**：文件照样能打开、git 照常提交，只是内容里多了一堆 `?`。
一型在 git 历史里潜伏了 3 个提交，二型潜伏了 **6 个**，三型从
`a9f2c8b` 起就在（数量从未变化）。且各型都有文件的所有历史版本已损坏、
无法恢复。

**教训**：每次以为"查完了"，换个判据又能查出一种。三型是在写完二型检测后
主动追问"还有没有别的形态"才发现的 —— 检测判据的盲区就是损坏的藏身处。
四型是被咬出来的，而且咬得最狠：它证明了**"文件内容合法"和"文件被正确读取"
是两件不同的事**，前三型只查了前者。

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
    # backend/tests/conftest.py 将 tmp_path 重定向到仓库内的
    # data/pytest_tmp（为绕过沙箱目录锁）。编码门禁若扫进去，会把测试
    # 故意创建的坏编码样本当作仓库文件，并让全量 pytest 受执行顺序污染。
    "pytest_tmp",
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
#
# 2026-08-23（第三轮）：`docs/DATA_SOURCE_STRATEGY.md` 的 498 处一型损坏
# 已全部修完并移出登记 —— **一型现在也是零豁免的硬门禁，三型损坏全部清零。**
#
# 这一份的失真形态和前两份不一样，也更隐蔽：它不是"写了错的现状"，
# 而是**把已经做完的事持续标为「计划中」**。10 个采集器全都实现了，
# 文档却逐个标着「（计划实现位置）」，且 10 个文件路径 10 个都不存在
# （真实文件没有 `_collector` 后缀）。危害不是让人少做事，
# 而是**让人重做一遍已经在跑的东西**；并且读者一旦发现清单不准，
# 会连里面真正的待办一起不信。
#
# 另外它给了一条 `discovery_score` 的"统一公式"（0.4×tvl + 0.3×github +
# 0.2×twitter + 0.1×chain），代码里没有任何地方实现它 —— 真实是 10 个
# 采集器各算各的，权重和入参都不同，其中几个的上限还被刻意压在分析阈值
# 0.3 以下（省 LLM 成本的设计）。照那条公式去调权重，会以为这些源坏了。
# 现已由 `backend/tests/test_data_source_strategy_parity.py` 双向钉住。
KNOWN_BROKEN: set[str] = set()

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
#
# 2026-08-23：`docs/SYSTEM_DIRECTION_CHANGE.md` 的 2 处已修完并**移出登记**，
# 这一型现在也是零豁免的硬门禁（与二型同口径）。
#
# 修法与另两型不同：三型丢的是小节标题里的装饰 emoji（`## 📊 成功指标（KPI）`
# 之类），语义零损失。既然原 emoji 无法从任何来源确定，就**直接去掉 emoji**，
# 而不是随便补一个看起来差不多的 —— 补一个猜的 emoji 会让这份文档看起来
# 从未损坏过，下一个人无法分辨哪个标题是原作者选的、哪个是补的。
# 去掉之后标题依然完整可读，且与"猜字比乱码更坏"这条原则一致。
KNOWN_BROKEN_REPLACEMENT: set[str] = set()

# 中日韩汉字 + CJK 标点 + 全角字符
_CJK = r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]"
# 半角 '?' 紧贴中文字符 —— 二型损坏的特征。
# 中文语境里几乎不会这样用半角问号，所以这个判据很干净。
MOJIBAKE_PAT = re.compile(f"(?<={_CJK})\\?|\\?(?={_CJK})")
# 行内代码 `...`
_INLINE_CODE = re.compile(r"`[^`\n]*`")
# Shell / compose 参数扩展 `${VAR:?中文提示}`、`${VAR:-默认值}`。
#
# `${VAR:?msg}` 是 POSIX「未设置就报错并退出」的语法（compose 靠它把
# API_KEY / POSTGRES_PASSWORD 做成硬必填），那个 `?` 是**语法字符**，
# 紧跟其后的中文是给部署者看的提示 —— 于是它天然长成「半角 ? 紧贴中文」
# 这个二型损坏的判据形状。
#
# 这类文件（.yml / .env / .sh）里没有 markdown 反引号，靠上面两条排除
# 屏蔽不到，所以必须单独一条。**不能反过来去改 compose 迁就检测器**：
# 把提示改成英文或删掉冒号问号，会削弱必填门禁或让部署者看不懂报错，
# 那是让门禁反过来损害被它保护的东西。
#
# 只吃到第一个 `}`（`[^{}\n]*`）而不是贪婪匹配：一行里可能有多个扩展，
# 贪婪会把两个扩展之间的散文一并屏蔽掉，那里真出现损坏就漏检了。
_SHELL_PARAM_EXPANSION = re.compile(r"\$\{[^{}\n]*\}")

# 三型：字面的 Unicode 替换符 U+FFFD（EF BF BD）。
# 判据无需上下文 —— 正常写作绝不会输入这个字符，它只可能来自
# "用 errors='replace' 解码后又写回文件"。因此零误报风险。
REPLACEMENT_CHAR = "\ufffd"

# 四型：含非 ASCII 的 Windows 脚本必须带 UTF-8 BOM。
# 没有 BOM 时 PowerShell 5.1 按 ANSI 代码页（简中机器 = GBK）解码。
# GBK 中任何 >= 0x80 的字节都会无条件吃掉下一个字节 —— 而 UTF-8 中文字符
# 是 3 字节（奇数），于是引号会不会被吃掉取决于前面中文的字节奇偶性。
# 引号被吃 → 字符串不闭合 → 后续代码被静默吞进字面量，语法仍合法。
# 详见模块 docstring。
BOM_REQUIRED_SUFFIXES = {".ps1", ".psm1", ".bat", ".cmd"}
UTF8_BOM = b"\xef\xbb\xbf"


def blank_code_blocks(text: str) -> str:
    """把围栏代码块与行内代码替换成等长空白（保持下标不变）。

    **必须排除代码**：mermaid 流程图里 `{全绿?}`、`{需立即修复?}` 是正常写法，
    文档里引用判据时写的 `` `{全绿?}` `` 也是。实测加上这两条排除后，
    三个误报文件（GIT_STRATEGY.md 2 处、ENCODING_REPAIR.md 1 处、
    以及本文件自己的文档字符串 4 处）全部归零 —— 当时只剩真正损坏的
    API_SPEC.md，该文件已于 2026-08-22 修完，二型现在全仓为零。

    本文件自己被自己误报这件事，恰好说明"描述判据的文字"和"符合判据的损坏"
    长得一样 —— 不排除代码就没法自洽。

    **还必须排除 shell 参数扩展**（`${VAR:?中文提示}`）：那个 `?` 是 POSIX
    语法字符，后面紧跟给部署者看的中文提示，天然长成二型损坏的形状。
    这一条是必需的第三项而不是可选优化 —— 2026-09-03 实测
    `docker-compose.prod.yml` 5 处、`docker-compose.yml` 1 处误报，全部来自
    `${API_KEY:?请在 .env 里设置…}` 这种把变量做成硬必填的写法。
    YAML/env/sh 里没有 markdown 反引号，前两条排除**够不到**它。
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
            masked = _INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line)
            out.append(_SHELL_PARAM_EXPANSION.sub(lambda m: " " * len(m.group(0)), masked))
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


def needs_utf8_bom(path: Path, data: bytes) -> bool:
    """这个文件是否属于"含非 ASCII 的 Windows 脚本"（四型的适用范围）。"""
    if path.suffix.lower() not in BOM_REQUIRED_SUFFIXES:
        return False
    return any(b > 0x7F for b in data)


def gbk_eaten_byte_offsets(data: bytes) -> set[int]:
    """按 .NET cp936（DBCS）规则，算出哪些字节会被当作"尾字节"吞掉。

    规则很简单，实测与 `[System.Text.Encoding]::GetEncoding(936)` 完全一致：
    **任何 >= 0x80 的字节都无条件吃掉紧随其后的一个字节**，不管那个字节是什么。
    ASCII 字节（< 0x80）单独成字符。

    ⚠️ 这里刻意**不调用任何 codec**。Python 的 `gbk` codec 在遇到非法尾字节时
    只消费 1 个字节（严格），而 .NET 消费 2 个（宽容）—— 结论正好相反。
    PowerShell 用的是 .NET，所以模型必须照 .NET 写，
    回归测试也用实测真值表而不是 Python codec 来校验。

    危险不在"中文标点后面跟引号"，而在**字节奇偶性**：
    一个 UTF-8 中文字符是 3 字节，GBK 按 2 字节一组吞，
    于是 1 个中文字后面的引号会被吃掉、2 个不会、3 个会、4 个不会……
    实测（.NET 936）：

        "中"   E4 B8 AD 22  → 引号被吃
        "中文" E4 B8 AD E6 96 87 22 → 引号保留
        "中文字" …E5 AD 97 22 → 引号被吃

    这条也解释了为什么问题会**随机出现**：同一行改一个字、
    加一个全角括号，奇偶性就翻转。所以判据不能是"看有没有某种组合"，
    只能是"这个文件必须有 BOM"。
    """
    eaten: set[int] = set()
    i = 0
    n = len(data)
    while i < n:
        if data[i] < 0x80:
            i += 1
        else:
            if i + 1 < n:
                eaten.add(i + 1)
            i += 2
    return eaten


def describe_bom_hazard(data: bytes) -> str:
    """指出第一行**引号真的会被吃掉**的位置，按字节实算而不是靠猜模式。

    只报"有中文"没用 —— 读的人不知道为什么危险，会当成洁癖要求。
    按 GBK 规则实算出被吞的引号位置，"这里会静默吞掉后面的代码"
    就变成一个可验证的事实。
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:  # pragma: no cover - 一型已先行拦截
        return "文件不是合法 UTF-8，先修一型损坏"

    eaten = gbk_eaten_byte_offsets(data)
    offset = 0
    for lineno, line in enumerate(text.splitlines(keepends=True), 1):
        raw = line.encode("utf-8")
        for k, byte in enumerate(raw):
            if byte in (0x22, 0x27) and (offset + k) in eaten:
                quote = chr(byte)
                return (
                    f"第 {lineno} 行的 {quote} 会被 GBK 吞掉（字节偏移 {offset + k}）——"
                    f"字符串不闭合，后续代码被静默吞进字面量：{line.strip()[:70]}"
                )
        offset += len(raw)

    return (
        "含非 ASCII 字符，当前恰好没有引号落在 GBK 尾字节位置上 —— "
        "但这只是字节奇偶性的巧合，改动任意一个中文字就会翻转，仍必须加 BOM"
    )


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
    bom_failures: list[tuple[str, str]] = []

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

        # 四型：含非 ASCII 的 Windows 脚本缺 UTF-8 BOM。
        # 零豁免、零登记 —— 这一型的修法是加 3 个字节，没有"不可逆丢失"的情况，
        # 因此没有理由给任何文件开豁免。
        if needs_utf8_bom(path, data) and not data.startswith(UTF8_BOM):
            bom_failures.append((rel, describe_bom_hazard(data)))

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

    if bom_failures:
        print()
        print(f"[FAIL] {len(bom_failures)} 个 Windows 脚本含中文但缺 UTF-8 BOM（四型）：")
        for rel, detail in bom_failures:
            print(f"  {rel}")
            print(f"    {detail}")
        print()
        print("为什么这是硬错误：Windows PowerShell 5.1 在没有 BOM 时按系统 ANSI 代码页")
        print("（简中机器 = GBK）解码脚本。GBK 中任何 >= 0x80 的字节都会无条件吃掉下一个")
        print("字节，而 UTF-8 中文字符是 3 字节（奇数）—— 于是结束引号会不会被吃掉，")
        print("取决于它前面有多少字节的中文。引号一旦被吃，字符串不闭合，后面几十行代码")
        print("被静默吞进字面量：语法仍然合法，不报错也不警告，脚本只是跳过那几十行然后 exit 0。")
        print()
        print("注意这条奇偶性意味着「今天没事」不等于安全 —— 改一个字就会翻转。")
        print()
        print("修法（3 个字节，一次解决）：")
        print("  $t = [System.IO.File]::ReadAllText($f, [System.Text.Encoding]::UTF8)")
        print("  [System.IO.File]::WriteAllText($f, $t, (New-Object System.Text.UTF8Encoding $true))")
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
