"""`docs/SECURITY.md` 与代码实际安全面的一致性回归。

## 为什么需要这个测试

`SECURITY.md` 的错误方式和之前几份文档都不同，而且更危险。

前几份是"写错了现状"（幽灵指标、错的文件路径），或"把做完的标成计划中"。
这一份是**系统性地把 ADR 里的设计决定抄成"实现"段落** —— 于是文档描述了
一整套并不存在的安全控制：域名白名单、工具权限校验、LLM 日预算熔断、
输出侧密钥扫描。

**对普通文档来说这只是过时；对安全文档来说，它让人在评估风险时
把不存在的控制算进去。** 上线前看这份文档做风险评估的人会得出
"LLM 成本有日上限、采集器打不到白名单外的域名"这两个结论 —— 两个都错。

而且方向是双向的：同一份文档里既有"说了有其实没有"（预算熔断），
也有"其实有但没说清"（限流中间件写得相当细，文档却只留了一句设计意图）。
**两个方向的错代价不对称但都真实**：
把未实现写成已实现 → 有人把不存在的保护算进风险评估；
把已实现写成未实现 → 有人去重复实现一遍。

## 测什么

正向（文档说存在的，必须真存在）：
1. §10.2 域名表标 ✅ 的行，对应主机名必须真的出现在 `backend/app` 里；
   标 ❌ 的行必须**确实不出现** —— 否则这张表又开始骗人。
2. 文档正文引用的 `backend/...` 路径必须真实存在。
3. 文档正文引用的 `/api/v1` 路径必须命中 OpenAPI。
4. §4.2 描述的限流机制必须真的装着：中间件类存在、`main.py` 装载、
   豁免前缀一致、昂贵端点配额与代码一致、默认值与文档写的数字一致。

反向（§11 点名不存在的，必须确实不存在）：
5. `PermissionError` / `allowed_tools` / `ALLOWED_DOMAINS` / `allowed_domains` /
   `output_schema` / `output_leakage_suspected` / `llm_budget_exhausted` /
   `system_prompt` 这 8 个符号在 `backend/app` 里必须**一处都没有**。
6. `backend/app/http_client.py` 必须**不存在**（真实出口是 `utils/fetcher.py`）。
7. `LLM_DAILY_BUDGET_USD` 必须**仍然只被读来展示、不被用来拦截**：
   判据是全仓没有 `daily_spend` / `budget_exceeded` / `llm_budget_exhausted`。
8. `/projects/{id}/debug` 端点必须**不在** OpenAPI 里。

反向断言这么写是有意的：**这些是"待实现"清单，不是"永远不许实现"清单。**
真去实现预算熔断时，对应的反向断言会变红 —— 那正是提醒去更新
§10 与 §11 的时机。测试挂在这里的意思是"文档还说它不存在，请同步"，
而不是"不准做"。

## 搜索器本身必须先被证明有效

写这份测试时踩了一个大坑，值得写在文件头：
我最初用 `backend/app/**/*.py` 搜"限流有没有实现"，在那个 shell 里
`**` 只匹配**恰好一层子目录**，于是 `backend/app/*.py`（顶层 22 个文件）
整个没被搜到 —— 而 `rate_limit.py` / `main.py` / `config.py` 全在那一层。
实测：递归 117 个文件，那个模式只有 66 个，**漏 51 个**。

结论是"`RATE_LIMIT_*` 0 处读取、限流未实现"，而真相是有一个 155 行、
写得相当细的中间件，`main.py:288` 也确实装载了。**我照这个错结论改了三处文档。**

所以：**「搜不到」不等于「不存在」，中间差一步 —— 先证明搜索本身有效。**
`TestParsersFailLoudly` 里有一条 `_grep_app("RateLimitExceededError")`：
用一个**已知存在**的符号验证搜索器工作正常，再去相信它给出的"0 处"。
这跟本仓反复出现的「解析器必须大声失败」是同一条，只不过对象是搜索工具自己。

## 解析器必须大声失败

每个解析函数在什么都没找到时**显式断言失败**，绝不返回空集合。
一个静默返回空集合的解析器会让所有断言意外通过 ——
一个永远为真的测试比没有测试更有害。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.rate_limit as rate_limit_module
from app.config import settings
from app.main import create_app
from app.rate_limit import EXEMPT_PREFIXES, RateLimitMiddleware, _expensive_limits

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "SECURITY.md"
APP_DIR = REPO_ROOT / "backend" / "app"

# §11 整节是「失真记录」：里面刻意写着不存在的符号名、路径名、文件名。
# 正向断言必须整节排除，否则会把这些反例当成正例来查。
_DISTORTION_ANCHOR = "## 11. 本文档的失真记录"

_GHOSTS_BLOCK = ("<!-- security-ghosts:begin -->", "<!-- security-ghosts:end -->")
_DOMAINS_BLOCK = ("<!-- domain-whitelist:begin -->", "<!-- domain-whitelist:end -->")

_BACKEND_PATH_RE = re.compile(r"`(backend/[A-Za-z0-9_/.\-]+\.(?:py|yml|yaml))`")
_API_PATH_RE = re.compile(r"`(?:GET|POST|PATCH|PUT|DELETE)?\s*(/api/v1[A-Za-z0-9_/{}.\-]*)`")
# 域名表行：第一列是 `主机名`（可能被 ~~删除线~~ 包着），最后一列带 ✅/⚠️/❌ 判定
_DOMAIN_ROW_RE = re.compile(r"^\|\s*~{0,2}`([a-z0-9.\-]+\.[a-z]{2,})`~{0,2}\s*\|(.+)\|\s*$", re.M)
# 正文里出现的所有「N req/min」。必须全部等于真值 —— 见
# test_documented_global_default_matches_settings 里记的"至少一处写对"陷阱。
_RPM_RE = re.compile(r"(\d+)\s*req/min")

# 这 6 个符号是 §11 点名"不存在"的。任何一个真的出现在 backend/app 里，
# 意味着有人实现了它，而 §10/§11 还在说它不存在 —— 文档必须同步。
#
# 注意：`ALLOWED_DOMAINS` / `allowed_domains` 已从本清单移除 —— 域名白名单
# 在 2026-08-29 实现了（`app/utils/domain_allowlist.py`），不再是 ghost。
_GHOST_SYMBOLS = (
    "PermissionError",
    "allowed_tools",
    "output_schema",
    "output_leakage_suspected",
    "llm_budget_exhausted",
    "system_prompt",
)

# LLM 日预算在 2026-08-24 之前是"能填、能查、不拦"的装饰性配置。
# 现在真的会拦（app/llm/budget.py），所以判据整体转向：
# 从"这三个符号必须不存在"改成"累计与拦截必须存在"。
# 见 TestLLMBudgetIsReallyEnforced。
#
# 注意 `llm_budget_exhausted` 仍留在 _GHOST_SYMBOLS 里：实现用的原因常量是
# `budget_exceeded`，那个更早的幻影名字确实仍不存在，§11 那一行没错。
_BUDGET_ENFORCEMENT_SYMBOLS = ("daily_spend", "budget_exceeded")


def _doc_text() -> str:
    assert DOC.is_file(), f"{DOC} 不存在 —— 这份测试的被测对象没了，请同步。"
    text = DOC.read_text(encoding="utf-8")
    # 文档被截断/清空时，下面所有"文档说 X 存在"的断言会因为集合为空而假通过。
    assert len(text) > 8000, f"{DOC.name} 只有 {len(text)} 字符，疑似被截断 —— 解析器已失效。"
    return text


def _body_without_distortion_section(text: str) -> str:
    """正文（不含 §11 失真记录）。"""
    idx = text.find(_DISTORTION_ANCHOR)
    assert idx > 0, f"找不到失真记录锚点 `{_DISTORTION_ANCHOR}` —— 章节若改名，请同步本测试。"
    body = text[:idx]
    assert len(body) > 6000, "排除失真记录后正文过短，解析器已失效。"
    return body


def _block(text: str, anchors: tuple[str, str]) -> str:
    begin, end = anchors
    i, j = text.find(begin), text.find(end)
    assert i > 0, f"找不到 `{begin}`"
    assert j > i, f"找不到 `{end}`（或顺序颠倒）"
    body = text[i + len(begin) : j].strip()
    assert body, f"`{begin}` 标记块是空的 —— 里面必须有内容。"
    return body


def _app_py_files() -> list[Path]:
    """`backend/app` 下**递归**全部 .py。

    必须递归。用只匹配一层子目录的模式会漏掉 `app/*.py` 顶层 22 个文件
    （含 `rate_limit.py` / `main.py` / `config.py`）—— 见模块 docstring 里
    记的那次误判。
    """
    files = sorted(APP_DIR.rglob("*.py"))
    assert len(files) > 100, (
        f"`backend/app` 递归只扫到 {len(files)} 个 .py（预期 >100）。"
        "要么路径变了，要么用了非递归的匹配 —— 后者会让下面所有「0 处」结论全假。"
    )
    top = list(APP_DIR.glob("*.py"))
    assert len(top) > 15, f"`backend/app` 顶层只有 {len(top)} 个 .py，疑似没扫到顶层 —— 解析器已失效。"
    return files


def _grep_app(symbol: str, *, skip: tuple[str, ...] = ()) -> list[str]:
    """在 `backend/app` 里递归找一个符号，返回 `相对路径:行号` 列表。"""
    hits: list[str] = []
    for path in _app_py_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(rel.endswith(s) for s in skip):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if symbol in line:
                hits.append(f"{rel}:{lineno}")
    return hits


def _app_source_blob() -> str:
    """`backend/app` 全部源码拼成一坨，用于查主机名字面量。"""
    blob = "\n".join(p.read_text(encoding="utf-8") for p in _app_py_files())
    assert len(blob) > 200_000, f"app 源码合计只有 {len(blob)} 字符，解析器已失效。"
    return blob


def _openapi_paths() -> set[str]:
    with TestClient(create_app()) as client:
        spec = client.get("/openapi.json").json()
    paths = set(spec.get("paths", {}))
    assert len(paths) >= 40, f"OpenAPI 只有 {len(paths)} 条路径，疑似应用未装载完整。"
    return paths


def _executable_source(module, func_name: str) -> str:
    """某个函数的源码，**剥掉 docstring**。

    为什么需要这个：`_client_ip` 的 docstring 里引用了
    `split(",")[0]` 来解释"为什么不能这么写"。直接 `inspect.getsource`
    去断言"代码里没有这个写法"，就会把**解释禁止的文字**当成那个写法本身。

    这是「断言要对着代码，不是对着描述代码的文字」的一个具体形态：
    注释和 docstring 属于"描述代码的文字"，不是被测对象。
    """
    func = getattr(module, func_name, None)
    assert func is not None, f"`{module.__name__}` 里没有 `{func_name}` —— 被测对象改名了，请同步。"
    src = inspect.getsource(func)
    doc = inspect.getdoc(func)
    if doc:
        # 逐行剔除 docstring 正文：比正则匹配三引号块更稳（避免嵌套引号问题）
        doc_lines = {line.strip() for line in doc.splitlines() if line.strip()}
        kept = []
        for line in src.splitlines():
            stripped = line.strip().strip('"').strip("'").strip()
            if stripped and stripped in doc_lines:
                continue
            if stripped in ('"""', "'''"):
                continue
            kept.append(line)
        src = "\n".join(kept)
    assert src.strip(), f"剥掉 docstring 后 `{func_name}` 没有可执行代码了 —— 解析器已失效。"
    return src


class TestDomainWhitelistTable:
    """§10.2 域名表的 ✅/❌ 判定必须与代码一致。

    这张表最值得钉住：**一个没实现的白名单，它的清单本身也从没被现实检验过。**
    实测发现上一版有三处错 —— Galxe 主机名写错（真实是
    `graphigo.prd.galaxy.eco`）、RootData 漏登记、Alchemy 那条集成不存在。
    假如当初真按那张表实现了白名单，Galxe 与 RootData 会被自己的白名单拦死。
    """

    @staticmethod
    def _rows() -> list[tuple[str, str]]:
        """返回 (主机名, 行尾判定文本)。"""
        block = _block(_doc_text(), _DOMAINS_BLOCK)
        rows = _DOMAIN_ROW_RE.findall(block)
        assert len(rows) >= 10, f"域名表只解析到 {len(rows)} 行（预期 ≥10），解析器已失效。"
        return [(host, rest) for host, rest in rows]

    def test_present_domains_really_in_code(self) -> None:
        """标 ✅ 的主机名必须真的出现在 `backend/app` 里。"""
        blob = _app_source_blob()
        missing = [host for host, rest in self._rows() if "✅" in rest and host not in blob]
        assert not missing, (
            f"域名表标 ✅ 但代码里找不到的主机名：{missing}。"
            "标 ✅ 的意思是「这是真实出口」—— 找不到就说明表又开始骗人了。"
        )

    def test_absent_domains_really_absent(self) -> None:
        """标 ❌ 的主机名必须确实不出现。

        真接入了某个源却还标 ❌，这张表就又变回一份不能信的清单。
        """
        blob = _app_source_blob()
        present = [host for host, rest in self._rows() if "❌" in rest and host in blob]
        assert not present, (
            f"域名表标 ❌（未接入）但代码里真出现了的主机名：{present}。如果确实新接入了这个源，请更新 §10.2 表格。"
        )

    def test_every_real_collector_host_is_registered(self) -> None:
        """反过来查：采集器里真实的 API 主机名必须都在表里登记。

        这条才是 RootData 漏登记那类问题的检出手段 ——
        只检查"表里的域名存在"永远发现不了"代码里的域名没进表"。
        """
        documented = {host for host, _ in self._rows()}
        pat = re.compile(r"https://([a-z0-9.\-]+\.[a-z]{2,})")
        # 只看采集器与 LLM 客户端：seed / 测试夹具里的示例域名不是真实出口
        real: set[str] = set()
        for sub in ("collectors", "llm"):
            for path in sorted((APP_DIR / sub).rglob("*.py")):
                for host in pat.findall(path.read_text(encoding="utf-8")):
                    real.add(host)
        assert real, "采集器里一个 https 主机名都没抓到 —— 解析器已失效。"
        # 采集器里也有指向项目官网的展示链接（galxe.com/xxx、twitter.com/xxx 等），
        # 那些不是 API 出口。只要求 `api.*` 与已登记的非常规出口被覆盖。
        api_hosts = {h for h in real if h.startswith("api.")}
        assert api_hosts, "抓不到任何 `api.*` 主机名 —— 解析器已失效。"
        unregistered = sorted(api_hosts - documented)
        assert not unregistered, (
            f"这些 API 主机名出现在采集器代码里，但 §10.2 表里没有：{unregistered}。"
            "一个漏登记的出口意味着白名单真实现时会把它拦死。"
        )


class TestRateLimitIsReal:
    """§4.2 描述的限流必须真的装着，且数字与文档一致。

    这一组存在的理由是我自己犯过的错：搜索模式漏了 `app/*.py` 顶层，
    于是把这套已实现的机制判成"未实现"并照此改了文档。
    断言直接读中间件对象和 `main.py` 源码，不读任何描述它的文字。
    """

    def test_middleware_is_wired_into_app(self) -> None:
        main_src = (APP_DIR / "main.py").read_text(encoding="utf-8")
        assert "RateLimitMiddleware" in main_src, (
            "`main.py` 里找不到 `RateLimitMiddleware` —— 限流中间件没装载，SECURITY.md §4.2 却说已实现，请同步。"
        )
        assert "add_middleware(RateLimitMiddleware)" in main_src, "中间件被 import 了但没 `add_middleware`，等于没装。"
        assert hasattr(RateLimitMiddleware, "dispatch"), "`RateLimitMiddleware` 没有 dispatch —— 不是一个可用的中间件。"

    def test_exempt_prefixes_match_doc(self) -> None:
        doc = _body_without_distortion_section(_doc_text())
        for prefix in EXEMPT_PREFIXES:
            assert f"`{prefix}`" in doc, (
                f"代码豁免了 `{prefix}` 但 SECURITY.md 没提。一个没写进文档的豁免路径，就是一个没人知道的限流缺口。"
            )
        assert "/health" in EXEMPT_PREFIXES, "`/health` 应当豁免（探针高频拉取）。"
        assert "/metrics" in EXEMPT_PREFIXES, "`/metrics` 应当豁免（Prometheus 高频拉取）。"

    def test_documented_global_default_matches_settings(self) -> None:
        """文档写的默认值必须是 `Settings` 的**声明默认**，不是本机 `.env` 的值。

        读实例属性会把本地 `.env` 当成"默认"，那是在给本机配置背书。

        ⚠️ 断言方式也踩过坑：第一版只写 `assert "100 req/min" in doc`。
        文档里有 4 处写着这个数字，把其中一处改成 60 之后测试照样通过 ——
        **"至少有一处写对了"不等于"没有一处写错"**。
        正确做法是把正文里所有 `N req/min` 全抓出来，要求它们**全部**等于真值。
        """
        fields = type(settings).model_fields
        requests_default = fields["rate_limit_requests"].default
        window_default = fields["rate_limit_window"].default
        assert requests_default == 100, f"`rate_limit_requests` 声明默认变成 {requests_default} 了，请同步 §4.2。"
        assert window_default == 60, f"`rate_limit_window` 声明默认变成 {window_default} 了，请同步 §4.2。"

        body = _body_without_distortion_section(_doc_text())
        quoted = _RPM_RE.findall(body)
        assert quoted, "正文里一处 `N req/min` 都没写 —— 读者无从知道配额是多少。"
        wrong = sorted({n for n in quoted if int(n) != requests_default})
        assert not wrong, (
            f"正文里这些 req/min 数字与真实默认 {requests_default} 不符：{wrong}。"
            "一个错的限流数字会让人以为配额比实际紧或松。"
            "（§11.1 那张「文档写 vs 代码实际」对照表在失真记录里，已排除。）"
        )

    def test_expensive_endpoint_quota_matches_doc(self) -> None:
        """`/run` 的分档配额必须与文档一致（1 次 / 10 次，按 LLM 开关）。"""
        src = inspect.getsource(_expensive_limits)
        assert "/api/v1/run" in src, "昂贵端点配额里没有 `/api/v1/run` —— §10.4 却说它有额外限制。"
        assert "is_llm_enabled" in src, "配额没按 LLM 开关分档，但 §4.2 写的是分档。"
        limits = _expensive_limits()
        assert limits, "`_expensive_limits()` 返回空 —— 昂贵端点配额等于没有。"
        prefixes = {prefix for prefix, _, _ in limits}
        assert "/api/v1/run" in prefixes, f"昂贵端点前缀是 {sorted(prefixes)}，没有 `/api/v1/run`。"
        for prefix, limit, window in limits:
            assert limit >= 1, f"`{prefix}` 配额 {limit} < 1，等于全禁。"
            assert window == 3600, f"`{prefix}` 窗口是 {window} 秒，文档写的是每小时。"
        doc = _body_without_distortion_section(_doc_text())
        assert "每小时 1 次" in doc and "10 次" in doc, (
            "§4.2 必须写出两档配额（LLM 开启 1 次 / 关闭 10 次），否则读者会以为一律 1 次。"
        )

    def test_forwarded_for_is_not_naively_trusted(self) -> None:
        """`X-Forwarded-For` 不能取 `split(",")[0]`。

        本仓 nginx 用 `proxy_add_x_forwarded_for`，会把客户端自带的头**前置**。
        取第一个值 = 攻击者每次换一个伪造值就能无限刷配额，
        限流的首要目的（挡 API key 爆破）当场失效。

        ⚠️ 断言必须只看**可执行代码**，不能看 docstring。
        第一版这条挂了，因为 `_client_ip` 的 docstring 里正好引用了
        `split(",")[0]` 来解释"为什么不能这么写" —— 于是测试把一段
        **解释禁止某写法的文字**当成了那个写法本身。
        这是本仓反复出现的那条：**断言要对着代码，不是对着描述代码的文字。**
        """
        code = _executable_source(rate_limit_module, "_client_ip")
        assert 'split(",")[0]' not in code.replace(" ", ""), (
            "`_client_ip` 取了 X-Forwarded-For 的第一个值 —— 那个位置可被客户端伪造，限流会被绕过。"
        )
        assert "trusted_proxy_count" in code, "没有 `TRUSTED_PROXY_COUNT` 概念 —— 代理层数必须显式配置才能采信转发头。"

    def test_429_carries_retry_after(self) -> None:
        """429 响应必须带 `Retry-After`，否则调用方无从知道等多久。

        ⚠️ 同样只看**可执行代码**：`rate_limit.py` 的**模块** docstring 第 5 行
        就写着"超限 429 + Retry-After"。第一版这条读整模块源码，
        于是删掉真正那行 header 之后测试依然通过 —— 变异存活。
        这是同一个坑在同一个文件里的**第二次**出现，说明"读源码做断言"
        天然会撞上注释：**默认就该剥掉文字，而不是等被咬了再剥。**
        """
        code = _executable_source(rate_limit_module, "_too_many")
        assert "429" in code, "限流不返回 429 —— 与 §4.2 不符。"
        assert "Retry-After" in code, "429 不带 `Retry-After` 头 —— 调用方无从知道等多久，与 §4.2 不符。"


class TestRateLimitDocstringMatchesItsOwnCode:
    """`rate_limit.py` 的模块 docstring 不能否认它自己在做的事。

    这一组针对的是一个具体事故：那段 docstring 曾经写着
    「这三个配置项没有任何代码读取、限流从未实现」，
    而**紧接其下的 100 多行就是在读它们**。

    为什么值得单独立一组门禁：一个文件的注释否认自己的实现，
    是最难被发现的一类错 —— 读代码的人先读注释，读完就不往下看了。
    它也是本轮那次误判的起点（外部文档的四处"❌ 未实现"都源自这里）。
    所以钉的不是措辞，而是**「注释与它所在的文件」这条最短的一致性**。
    """

    #: 只要这些说法出现在 docstring 里，就与本文件的实现直接矛盾。
    #:
    #: 分两类，都是变异测试逐个补出来的：
    #: - **过去式否认**：说这些配置项没人读、限流没实现（当年那句原话）。
    #: - **未来式否认**：说限流"计划/待/尚未"实现 —— 危害完全一样。
    #:   变异 `d11` 把「这个文件就是限流的实现本体」换成「本文件计划实现限流」，
    #:   一条测试都没红。也就是说只防了"说没做"，没防"说还没做"。
    #:   而后者更容易被写出来：改代码时顺手把注释写成路线图口吻。
    _DENIALS = (
        "从未实现",
        "没有任何代码读取",
        "全仓库没有任何代码",
        "未实现限流",
        "计划实现",
        "尚未实现",
        "待实现",
        "还没有实现",
    )

    #: 行级豁免标记。docstring 里需要**引用**当年那句错话来说明事故，
    #: 引用和主张是两回事 —— 但豁免必须逐行显式，可 grep 审计，
    #: 与本仓 `terminology-ok` 同一套做法。整段/整文件豁免一律不给：
    #: **豁免的粒度就是漏洞的大小。**
    _EXEMPT_MARKER = "denial-quote-ok"

    def test_docstring_does_not_deny_the_implementation(self) -> None:
        doc = inspect.getdoc(rate_limit_module) or ""
        assert doc.strip(), "`rate_limit.py` 没有模块 docstring —— 这条门禁在空转，请先补 docstring。"

        # 先证明这个文件确实在读那三个配置项（否则"矛盾"无从成立）
        src = (APP_DIR / "rate_limit.py").read_text(encoding="utf-8")
        body = src.replace(doc, "", 1)
        for key in ("rate_limit_enabled", "rate_limit_requests", "rate_limit_window"):
            assert key in body, (
                f"`rate_limit.py` 的可执行代码里读不到 `{key}` —— "
                "如果限流真的被移除了，请把 docstring、SECURITY.md §4.2 与本组测试一起改掉。"
            )

        offenders: list[tuple[int, str]] = []
        exempted = 0
        for lineno, line in enumerate(doc.splitlines(), 1):
            hits = [phrase for phrase in self._DENIALS if phrase in line]
            if not hits:
                continue
            if self._EXEMPT_MARKER in line:
                exempted += 1
                continue
            offenders.extend((lineno, phrase) for phrase in hits)

        assert not offenders, (
            f"`rate_limit.py` 的 docstring 里有否认自己实现的说法 {offenders}，"
            "但同一个文件下面就在读这些配置项。"
            "一个否认自己实现的注释比没有注释更坏：读代码的人先读注释，读完就不往下看了。"
            f"（若确实是在引用当年那句错话，请在该行行尾加 `{self._EXEMPT_MARKER}` 标记。）"
        )
        assert exempted >= 1, (
            "docstring 里一处豁免标记都没有 —— 说明那段「当年写错了什么」的引用被删掉了。"
            "只留下正确结论、不留下错误原文，下一个人无法判断自己是不是又搜错了。"
        )

    def test_docstring_states_it_is_wired(self) -> None:
        """docstring 必须正面声明"这个文件就是实现本体、已装载"。

        只禁止否认句是不够的 —— 变异测试证明了：把那句正面声明改成
        「本文件计划实现限流」之后，全部测试仍然绿（当时否认词表里
        没有"计划实现"）。补词表能挡住已知说法，但挡不住下一种措辞。

        所以这里从两侧钉：**既要求没有否认句，也要求有肯定句。**
        肯定句同时被 `test_middleware_is_wired_into_app` 用真实对象验证过，
        因此它不是一句自说自话的口号，而是一个有代码背书的断言。
        """
        doc = inspect.getdoc(rate_limit_module) or ""
        assert "实现本体" in doc, (
            "docstring 没正面写出「这个文件就是限流的实现本体」。"
            "只靠禁止否认句挡不住下一种措辞 —— 必须有一句肯定的声明作为对照。"
        )
        assert "add_middleware" in doc, (
            "docstring 没说清它是怎么生效的（由 `main.py` 通过 `add_middleware` 装上）。"
            "一个不说明自己如何被装载的中间件，下一个人无法判断它到底在不在链上。"
        )

    def test_docstring_records_the_misjudgement(self) -> None:
        """docstring 必须留下那次误判的成因，而不是悄悄改对。

        悄悄改对的代价：下一个人（或下一个我）会用同一个一层 glob
        得出同一个错结论，再改错一遍文档。
        写下"搜索器本身可能是坏的"这条，比写对当前结论更有价值。

        ⚠️ 断言粒度也是变异测试逼细的，而且**被同一个坑咬了两次**：
        第一版只要求 `"glob" in doc`，而"不用 shell glob"那句里也有 glob；
        改成要求 `"0 命中"` 之后仍然存活，因为下面那条教训里也写着"0 命中"。
        两次都是**同一个词在 docstring 里出现两处**，
        于是断言只证明了其中一处存在，把成因整句删掉照样绿。

        结论：钉"某个词出现过"永远不够，要钉**只可能出自那一句的内容** ——
        这里是那个具体命令（`Select-String`）、它的真实行为（只匹配一层）、
        以及实测数字（117 / 66）。
        """
        doc = inspect.getdoc(rate_limit_module) or ""
        assert "Select-String" in doc, (
            "docstring 没写出当年那条具体命令 —— 只说「搜索方式不对」，下一个人认不出自己正在用同一条命令。"
        )
        assert "只匹配一层" in doc, (
            "docstring 没写清那个 glob 的真实行为（只匹配一层目录）—— 成因丢了，下一个人会用同一个 glob 重犯。"
        )
        assert "117" in doc and "66" in doc, (
            "docstring 没留下实测数字（递归 117 个 .py vs 那个 glob 只看到 66 个）。"
            "没有数字的教训会被当成模糊的告诫，下次照样会信一个 0 命中的结果。"
        )
        assert "rglob" in doc, "docstring 没给出替代做法（`pathlib.rglob`），只说别犯错等于没说。"
        assert doc.count("0 命中") >= 2, (
            "「0 命中」在 docstring 里应当出现两次：一次是事故叙述（当时搜到 0 条），"
            "一次是由此得出的教训（不要信任任何 0 命中结论）。"
            "只剩一处说明其中一半被删了 —— 而这一半正是这段记录的要点："
            "**一个 0 命中的结果，可能是搜索器坏了而不是代码没有。**"
        )

    def test_docstring_distinguishes_inbound_from_outbound(self) -> None:
        """必须写清这是**入站**限流，与 `collectors/rate_limiter.py` 的出站限流无关。

        两个文件名几乎一样、都叫 rate limit，方向完全相反。
        实测出站那个的配额是 `defillama 2.0/5`、`etherscan 0.2/2` 之类，
        与入站的 100 req/min 毫无关系 —— 改错一个会以为改了另一个。
        """
        doc = inspect.getdoc(rate_limit_module) or ""
        assert "入站" in doc and "出站" in doc, (
            "docstring 没区分入站/出站限流。仓里有两套同名机制方向相反，不写清会有人改错文件。"
        )
        outbound = APP_DIR / "collectors" / "rate_limiter.py"
        assert outbound.is_file(), f"`{outbound}` 不存在 —— docstring 提到的出站限流已消失，请同步 docstring。"


class TestReferencedPathsExist:
    """正文引用的 `backend/...` 文件必须真实存在。"""

    def test_backend_paths_exist(self) -> None:
        body = _body_without_distortion_section(_doc_text())
        referenced = set(_BACKEND_PATH_RE.findall(body))
        assert len(referenced) >= 3, f"只解析到 {sorted(referenced)}，解析器已失效。"
        missing = sorted(p for p in referenced if not (REPO_ROOT / p).is_file())
        assert not missing, (
            f"SECURITY.md 正文引用了这些不存在的文件：{missing}。安全文档里一个错的文件路径会让人以为某处有校验代码。"
        )

    def test_api_paths_hit_openapi(self) -> None:
        body = _body_without_distortion_section(_doc_text())
        referenced = set(_API_PATH_RE.findall(body))
        assert referenced, "正文一条 `/api/v1` 路径都没解析到 —— 解析器已失效。"
        real = _openapi_paths()
        # 文档确实需要提「前缀」（如 /api/v1/run 作为限流分档的前缀），所以前缀匹配也算命中
        missing = sorted(p for p in referenced if p not in real and not any(r.startswith(p) for r in real))
        assert not missing, f"SECURITY.md 正文引用了这些不存在的 API 路径：{missing}。"


class TestGhostListIsHonest:
    """§11 点名"不存在"的东西，必须确实都不存在。

    否则这份纠错清单本身就成了新的谎言 —— 而这一节是读者判断
    「哪些安全控制真的有」的唯一依据，它错了比正文错更糟。

    ⚠️ 这些是**待实现清单，不是禁止实现清单**。真去实现预算熔断时，
    对应断言会变红 —— 那正是提醒去更新 §10 与 §11 的时机。
    """

    def test_ghosts_block_lists_the_symbols(self) -> None:
        """先确认 §11 确实点了这些名字，否则下面的反向断言是在替文档编内容。"""
        block = _block(_doc_text(), _GHOSTS_BLOCK)
        missing = [s for s in _GHOST_SYMBOLS if s not in block]
        assert not missing, (
            f"§11 失真记录里没有提到这些符号：{missing}，但本测试在替它们做反向断言 —— 断言必须与文档实际写的内容对应。"
        )

    @pytest.mark.parametrize("symbol", _GHOST_SYMBOLS)
    def test_ghost_symbol_absent(self, symbol: str) -> None:
        hits = _grep_app(symbol)
        assert not hits, (
            f"`{symbol}` 现在真的出现在代码里了：{hits[:5]}。"
            "SECURITY.md §10/§11 还在说它不存在 —— 如果这是新实现的控制，请更新文档；"
            "这条测试挂在这里的意思是「文档需要同步」，不是「不准实现」。"
        )

    def test_http_client_module_absent(self) -> None:
        """`backend/app/http_client.py` 不存在；真实出口是 `utils/fetcher.py`。"""
        ghost = APP_DIR / "http_client.py"
        assert not ghost.is_file(), (
            "`backend/app/http_client.py` 现在存在了 —— SECURITY.md §10.2 还标着它"
            "不存在，请更新文档（并确认它是否真的做了域名校验）。"
        )
        real = APP_DIR / "utils" / "fetcher.py"
        assert real.is_file(), "`backend/app/utils/fetcher.py` 不见了 —— 文档指向的真实 HTTP 出口变了，请同步。"

    def test_llm_budget_is_really_enforced_now(self) -> None:
        """`LLM_DAILY_BUDGET_USD` 从"能填、能查、不拦"变成了真的会拦。

        这条门禁在 2026-08-24 之前是**反方向**的：它断言
        `daily_spend` / `budget_exceeded` / `llm_budget_exhausted` 在
        `backend/app` 里一处都不存在，用来保护 §10.4「只展示不拦截」的真实性。

        实现补上后门禁必须一起转向。一个断言"这个安全控制必须仍然缺失"的测试，
        在控制实现后就成了反向的假绿 —— 它会让 CI 拒绝真正的加固。

        判据仍然落在**累计**上而不是"有人读了这个配置"：
        实测曾有 3 处读它来回显，搜一下像是实现了。没有累计就无从超限。
        """
        fields = type(settings).model_fields
        assert "llm_daily_budget_usd" in fields, (
            "`LLM_DAILY_BUDGET_USD` 配置项不见了 —— 若已删除，请同步 §10.4 与 §11。"
        )
        for symbol in _BUDGET_ENFORCEMENT_SYMBOLS:
            hits = _grep_app(symbol)
            assert hits, (
                f"`{symbol}` 在 backend/app 里一处都没有 —— 预算拦截被移除了？\n"
                "SECURITY.md §10.3/§10.4/§11 现在写的是「已实现真实拦截」，两边必须一致。"
            )

        ledger = APP_DIR / "llm" / "budget.py"
        assert ledger.is_file(), "app/llm/budget.py 不见了 —— 日花费账本是预算拦截的全部依据。"
        ledger_src = ledger.read_text(encoding="utf-8")
        assert "llm_spend_daily" in ledger_src, (
            "账本不再读写 llm_spend_daily 表 —— 如果改成了内存计数，"
            "那么按进程计的预算不是预算（重启归零、多 worker 各记一份）。"
        )

    def test_security_doc_no_longer_calls_the_budget_decorative(self) -> None:
        """§10.3 / §10.4 不能再写「只展示不拦截」。

        把已实现的控制写成未实现，会让人在风险评估里少数一个可用的控制，
        或者去重做一遍。两个方向的文档错误代价不对称，但都真实。

        禁的是**这条控制的否认句**，不是"装饰性配置"这个词本身 ——
        第一版禁了整个词，结果误伤了 `DUNE_API_KEY` 那一行（它**确实**还是
        装饰性配置，那句话没错）。一个过宽的禁词会把正确的句子也判成错的，
        然后逼人去改一句本来对的话。
        """
        text = _doc_text()
        budget_lines = [line for line in text.splitlines() if "LLM_DAILY_BUDGET_USD" in line]
        assert len(budget_lines) >= 3, f"只找到 {len(budget_lines)} 行提到日预算 —— 解析器或文档结构已变，先修解析器。"
        for line in budget_lines:
            for stale in ("只展示不拦截", "没有任何拦截", "纯装饰"):
                assert stale not in line, f"这一行仍否认日预算拦截：{line.strip()[:120]}"

    def test_debug_endpoint_absent(self) -> None:
        paths = _openapi_paths()
        ghosts = sorted(p for p in paths if p.endswith("/debug"))
        assert not ghosts, (
            f"出现了 /debug 端点：{ghosts}。SECURITY.md §10.5 还说它不存在 —— "
            "请更新文档，并确认它不会返回 prompt 内容。"
        )


class TestImageSecurityClaims:
    """§6.3 讲镜像安全 —— 这一节此前三条里错了两条。

    2026-08-24 实测：
      · 写「基础镜像 `python:3.11-slim`」→ 实际两阶段都是 `python:3.12-slim`
      · 写「固定 digest」→ 实际没有任何 `@sha256:`
      · 写「Trivy/Grype」→ 仓库里只有 Trivy，没有 Grype

    为什么这种错值得钉门禁：**安全文档里的"已经做了"会被直接算进风险评估**。
    "固定了 digest"意味着"基础层不会在我不知情时变化" —— 而实际用的是
    可变 tag。读者按文档做威胁建模时，会漏掉整整一类供应链风险。

    与 §10/§11 那些"点名不存在"的断言方向相反：这里断言的是
    **文档不能声称超出代码的保护**。
    """

    _DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
    _SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"

    @classmethod
    def _dockerfile(cls) -> str:
        assert cls._DOCKERFILE.is_file(), f"{cls._DOCKERFILE} 不存在 —— 被测对象没了。"
        text = cls._DOCKERFILE.read_text(encoding="utf-8")
        assert "FROM python:" in text, "Dockerfile 里找不到 `FROM python:` —— 解析锚点变了，先修这里。"
        return text

    @classmethod
    def _section(cls) -> str:
        """§6.3 那一节的正文。"""
        text = _doc_text()
        start = text.index("### 6.3 镜像安全")
        end = text.index("## 7.", start)
        section = text[start:end]
        assert len(section) > 200, "§6.3 解析出来不到 200 字 —— 解析器失效，别信下面的断言。"
        return section

    def test_documented_base_image_matches_dockerfile(self) -> None:
        """§6.3 提到的每个 `python:X.Y-slim` 都必须是 Dockerfile 真在用的。

        ⚠️ 这条第一版写错了，变异测试才抓出来：原来只断言"真实版本号必须
        出现在本节里"。但本节会**多次**提到镜像名（一次在结论、一次在实测
        引述里），把其中一处改成 3.11 后，另一处仍是 3.12 —— 断言照样通过。

        **"至少写对一处"不是判据**：读者读到的是错的那一处。
        改成双向核对集合：文档提到的版本集合必须等于 Dockerfile 里的集合。
        这也是本仓库第三次踩"锚点是另一行的子串"这个坑。
        """
        real = set(re.findall(r"FROM (python:[0-9.]+-slim)", self._dockerfile()))
        assert real, "Dockerfile 里解析不到基础镜像 —— 先修解析器。"

        section = self._section()
        mentioned = set(re.findall(r"(python:[0-9.]+-slim)", section))
        assert mentioned, "§6.3 一个 `python:X.Y-slim` 都没提到 —— 解析器失效或本节被改空了。"

        stale = sorted(mentioned - real)
        assert not stale, (
            f"§6.3 提到了 Dockerfile 并没在用的镜像 {stale}（真实：{sorted(real)}）。\n"
            "安全文档里一个过期的版本号会让人按错的基础层做威胁建模。"
        )
        missing = sorted(real - mentioned)
        assert not missing, f"Dockerfile 用的是 {missing}，但 SECURITY.md §6.3 没提到。"

    def test_digest_pinning_claim_matches_reality(self) -> None:
        """声称固定 digest 时，Dockerfile 里必须真的有 `@sha256:`。

        方向是单向的：**没固定却说固定**才是问题（读者会少算一类风险）；
        真固定了而文档没提只是漏写，不构成误导。
        """
        pinned = "@sha256:" in self._dockerfile()
        section = self._section()
        claims_pinned = "固定 digest" in section and "未固定 digest" not in section
        assert not (claims_pinned and not pinned), (
            "§6.3 声称「固定 digest」，但 docker/Dockerfile 里没有任何 `@sha256:`。\n"
            "可变 tag 意味着同一份 Dockerfile 在不同时间可能构建出不同基础层 —— "
            "这正是读者会按文档漏掉的那一类供应链风险。"
        )

    def test_named_scanners_actually_exist_in_ci(self) -> None:
        """文档点名的扫描器必须真的在工作流里。

        ⚠️ 这条第一次跑就拦住了它自己的修复文案 —— §6.3 里那句
        「用 Grype 的说法是错的，仓库里没有 Grype」正是在**纠正**这个错，
        却因为提到了 `grype` 而被判成"点名了不存在的扫描器"。

        这是本仓库反复出现的同一个坑：**描述某个错误的文字，和犯那个错的文字，
        长得一模一样。** 之前在术语门禁、编码门禁（`check_encoding.py`
        自己被自己误报）、以及 8000 端口门禁上各犯过一次。

        解法沿用仓库既有的**行级显式豁免**约定（可 `grep -rn` 审计），
        而不是整节豁免 —— 整节豁免会让真正的幻影扫描器藏在里面。
        """
        workflows = REPO_ROOT / ".github" / "workflows"
        blob = "\n".join(p.read_text(encoding="utf-8") for p in workflows.glob("*.yml")).lower()
        assert "trivy" in blob, "解析不到 trivy —— 搜索器或工作流结构变了，先修这里。"

        # 逐行判，跳过带行级豁免标记的行（那些行在说"这个东西不存在"）
        lines = [
            line
            for line in self._section().lower().splitlines()
            if "scanner-absence-ok" not in line and not line.lstrip().startswith("#")
        ]
        assert lines, "§6.3 剔掉豁免行后一行不剩 —— 解析器失效。"
        section = "\n".join(lines)

        for scanner in ("grype", "snyk", "clair"):
            if scanner in section:
                assert scanner in blob, (
                    f"§6.3 点名了 `{scanner}`，但 .github/workflows 里一处都没有。"
                    "一个不存在的扫描器会让人以为镜像已经被扫过。"
                    f"\n（如果这一行是在说明「没有 {scanner}」，行尾加 `scanner-absence-ok` 标记。）"
                )

    def test_ignore_unfixed_is_disclosed(self) -> None:
        """扫描带 `ignore-unfixed: true` 时，文档必须说出来。

        因为它改变了"CI 绿"的含义：绿只代表**有补丁可修的**高危为零，
        不代表镜像无高危。这个差别不写出来，绿灯会被当成"干净"。
        """
        workflow = self._SECURITY_WORKFLOW
        assert workflow.is_file(), f"{workflow} 不存在 —— 被测对象没了。"
        text = workflow.read_text(encoding="utf-8")
        if "ignore-unfixed" not in text:
            pytest.skip("工作流没用 ignore-unfixed，这条不适用")

        section = self._section()
        assert "ignore-unfixed" in section, (
            "security.yml 的 Trivy 带 `ignore-unfixed: true`，但 SECURITY.md §6.3 没提。\n"
            "不写出来的话，「CI 绿」会被读成「镜像无高危」—— 实际只是「无可修的高危」。"
        )


class TestParsersFailLoudly:
    """解析器自检：永远返回空值的解析器会让上面全部断言假通过。"""

    def test_search_itself_works(self) -> None:
        """用一个**已知存在**的符号验证搜索器有效，再去相信它给出的「0 处」。

        这条是本文件最重要的自检。模块 docstring 里记的那次误判
        （`**` 只匹配一层子目录，漏掉 `app/*.py` 顶层 22 个文件）
        就是因为缺了这一步：搜索器坏了，而"搜不到"被当成了"不存在"。
        """
        assert _grep_app("RateLimitExceededError"), (
            "grep 找不到一个确实存在的符号 —— 搜索器已失效，所有「0 处」结论不可信。"
        )
        # 顶层文件必须在搜索范围内：这正是上次漏掉的那一层
        assert _grep_app("RateLimitMiddleware"), (
            "grep 找不到 `RateLimitMiddleware`（在 `app/rate_limit.py`，顶层）—— 搜索没覆盖顶层文件。"
        )
        assert _grep_app("rate_limit_enabled"), (
            "grep 找不到 `rate_limit_enabled`（在 `app/config.py`，顶层）—— 搜索没覆盖顶层文件。"
        )

    def test_parsers_find_real_content(self) -> None:
        text = _doc_text()
        assert len(text) > 8000
        body = _body_without_distortion_section(text)
        assert len(_block(text, _GHOSTS_BLOCK)) > 200
        assert len(_block(text, _DOMAINS_BLOCK)) > 200
        assert len(TestDomainWhitelistTable._rows()) >= 10
        assert len(_BACKEND_PATH_RE.findall(body)) >= 3
        assert _API_PATH_RE.findall(body)
        assert len(_app_py_files()) > 100
        assert len(_openapi_paths()) >= 40
        assert len(_app_source_blob()) > 200_000
        assert _expensive_limits()
        assert "getattr" in _executable_source(rate_limit_module, "_client_ip")
        assert _RPM_RE.findall(body), "正文抓不到任何 `N req/min` —— 限流数字断言会空转。"

    def test_docstring_stripper_actually_strips(self) -> None:
        """`_executable_source` 必须真的剥掉 docstring，且真的留下代码。

        两个方向都要验：
        - 剥掉了 → docstring 里的 `split(",")[0]` 不再出现；
        - 没剥过头 → 函数体里真实存在的 `trusted_proxy_count` 还在。

        只验一个方向不够：一个"把整段都剥掉"的实现会让上面那条
        禁止性断言永远通过 —— 又是一个永远为真的测试。
        """
        code = _executable_source(rate_limit_module, "_client_ip")
        full = inspect.getsource(rate_limit_module._client_ip)
        assert 'split(",")[0]' in full, (
            "`_client_ip` 的 docstring 不再提到那个反例写法 —— 本自检失去意义，请改用别的锚点。"
        )
        assert 'split(",")[0]' not in code.replace(" ", ""), "docstring 没被剥掉 —— 禁止性断言会误报。"
        assert "trusted_proxy_count" in code, "剥过头了，函数体也被删了 —— 断言会变成永远为真。"
        assert "return" in code, "剥掉后没有 return 语句 —— 显然剥过头了。"

    def test_missing_function_raises(self) -> None:
        with pytest.raises(AssertionError):
            _executable_source(rate_limit_module, "_no_such_function")

    def test_domain_row_parser_reads_the_verdict_column(self) -> None:
        """域名行解析必须同时拿到主机名和判定 —— 只拿主机名等于没判定。"""
        rows = TestDomainWhitelistTable._rows()
        verdicts = {host: rest for host, rest in rows}
        assert any("✅" in rest for rest in verdicts.values()), "一行 ✅ 都没解析到 —— 正向断言全空转。"
        assert any("❌" in rest for rest in verdicts.values()), "一行 ❌ 都没解析到 —— 反向断言全空转。"

    def test_missing_anchors_raise(self) -> None:
        with pytest.raises(AssertionError):
            _body_without_distortion_section("没有失真记录锚点的文本")
        with pytest.raises(AssertionError):
            _block("没有标记块", _GHOSTS_BLOCK)
        with pytest.raises(AssertionError):
            # 标记块在但内容为空 → 也必须炸
            _block(f"{_GHOSTS_BLOCK[0]}\n\n{_GHOSTS_BLOCK[1]}", _GHOSTS_BLOCK)
        with pytest.raises(AssertionError):
            _block("没有域名块", _DOMAINS_BLOCK)
