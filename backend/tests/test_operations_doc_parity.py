"""`docs/OPERATIONS.md` 与代码实际运维面的一致性回归。

## 为什么需要这个测试

重写前的 `docs/OPERATIONS.md` 有 404 处编码损坏，于是它被登记进
`scripts/check_encoding.py` 的 `KNOWN_BROKEN` 豁免清单。**豁免之后就没人读它了**，
于是它在内容上烂得更彻底：

- 引用 19 个 `airdrop_*` 指标，**18 个不存在**；
- 引用 4 个不存在的 API 路径；
- 整段贴出两个「已提供的巡检脚本」的源码，而这两个文件**根本不存在**；
- 端口全篇写 8000（真实 8002）；
- 声称「LLM 超预算会自动停用」，而代码里**没有任何拦截逻辑**。

最后一条最危险：值班照着 runbook 会相信有一层成本保护，而它不存在。

**一份运维手册的错误只在故障时才暴露** —— 那正是最不该现场调试文档的时候。
所以这些断言必须由 CI 承担，而不是靠人复读。

## 测什么

1. 文档正文引用的每个指标名，必须在 `app.metrics` 注册表里真实存在。
2. 文档正文引用的每个 `/api/v1` 路径，必须命中 OpenAPI（精确匹配，
   或作为某条真实路由的前缀 —— 文中确实需要提「前缀」这个概念）。
3. 文档提到的每个 `scripts/` 脚本文件必须真实存在。
4. §12 的三份**失真清单**（幽灵指标 / 幽灵路径 / 幽灵脚本）反过来断言
   它们**确实都不存在** —— 否则清单本身就成了新的谎言。
5. §7.1 的 cron 表逐条对齐 `settings` 的实际值。
6. §5.2 的管理员前缀清单与 `app.auth.ADMIN_ONLY_PREFIXES` 完全一致。
7. §8.1 的告警名与 `alert_rules.yml` 完全一致。
8. §4.3 的 10 个采集源 id 与调度器 cron_map 完全一致。
9. §8.2 的 5 个采集告警阈值与 `check_alerts()` 的硬编码值一致。
10. 一批**关键数字**（端口、熔断参数、标签阈值、发现阈值）与代码一致。

## 解析器必须大声失败

每个解析函数在什么都没找到时**显式断言失败**，绝不返回空集合。
一个静默返回空集合的解析器会让所有断言意外通过 —— 那是最坏的结果：
一个永远为真的测试比没有测试更有害，因为它给人已被覆盖的错觉。

而且断言必须读**被验证的那个文件**。上一轮写 OBSERVABILITY 的 span 检查时
犯过这个错：span 名写死在测试里，于是改文档不会让测试变红 ——
一个不读被测对象的断言不是断言。这里所有清单都从文档解析。
`TestParsersFailLoudly` 反过来验证解析器本身能解析出东西。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from prometheus_client import Counter, Gauge, Histogram

import app.metrics as metrics_module
from app.auth import ADMIN_ONLY_PREFIXES
from app.config import settings
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "OPERATIONS.md"
ALERT_RULES = REPO_ROOT / "configs" / "observability" / "prometheus" / "alert_rules.yml"

# ── 标记块：文档里用 HTML 注释成对包裹，便于精确切分 ───────────────
_BLOCKS = {
    "admin": ("<!-- admin-prefixes:begin -->", "<!-- admin-prefixes:end -->"),
    "cron": ("<!-- collection-cron:begin -->", "<!-- collection-cron:end -->"),
    "ready": ("<!-- collection-ready:begin -->", "<!-- collection-ready:end -->"),
    "ghost_metrics": ("<!-- ghost-metrics:begin -->", "<!-- ghost-metrics:end -->"),
    "ghost_paths": ("<!-- ghost-paths:begin -->", "<!-- ghost-paths:end -->"),
}

# §12 整节是「失真记录」：里面刻意写着不存在的指标名、路径名、脚本名。
# 正向断言必须整节排除，否则会把这些反例当成正例来查。
_DISTORTION_SECTION_ANCHOR = "## 12. 上一版本的失真记录"

_METRIC_RE = re.compile(r"`(airdrop_[a-z0-9_]+)`")
# 路径：可选前置 HTTP 方法，路径本身允许 {占位符}
_PATH_RE = re.compile(r"`(?:GET|POST|PATCH|PUT|DELETE)?\s*(/api/v1[A-Za-z0-9_/{}.\-]*)`")
_SCRIPT_RE = re.compile(r"scripts[/\\]([A-Za-z0-9_.\-]+\.(?:py|sh|ps1))")
# 源 id 含数字（layer3），别写成 [a-z_]+ —— 那样会静默漏掉一整个源。
_CRON_ROW_RE = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)
_ALERT_NAME_RE = re.compile(r"`([A-Z][A-Za-z]+)`")
_CODE_BLOCK_RE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)


def _doc_text() -> str:
    assert DOC.is_file(), f"找不到 {DOC} —— 本测试的被测对象就是这份文档。"
    text = DOC.read_text(encoding="utf-8")
    assert len(text) > 20000, f"{DOC.name} 只有 {len(text)} 字符，疑似被截断或清空，解析结果不可信。"
    return text


def _block(text: str, key: str) -> str:
    """取出一个标记块的内容。两个锚点都显式断言存在。

    锚点丢了就意味着文档结构被改过。此时**必须让测试红**，
    而不是安静地返回空串 —— 空串会让下面的清单断言全部空转。
    """
    begin, end = _BLOCKS[key]
    assert begin in text, f"{DOC.name} 里找不到标记 `{begin}` —— 文档结构已变，请同步本测试，别让它检查错误的范围。"
    assert end in text, f"{DOC.name} 里找不到标记 `{end}`，无法确定 `{begin}` 块在哪里结束。"
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    assert start < stop, f"标记 `{end}` 出现在 `{begin}` 之前，文档结构与本测试的假设不符。"
    body = text[start:stop]
    assert body.strip(), f"标记块 `{begin}` 是空的 —— 空清单会让对应断言变成空转。"
    return body


def _body_without_distortion_section(text: str) -> str:
    """去掉 §12「失真记录」，剩下的部分才适用正向断言。"""
    assert _DISTORTION_SECTION_ANCHOR in text, (
        f"{DOC.name} 里找不到 `{_DISTORTION_SECTION_ANCHOR}` —— "
        "那一节刻意列出不存在的指标/路径/脚本，必须整节排除在正向断言之外。"
    )
    return text[: text.index(_DISTORTION_SECTION_ANCHOR)]


# ── 代码侧真相 ─────────────────────────────────────────────────


def _exported_metric_names() -> set[str]:
    """从 Prometheus 注册表取出**暴露名**（Counter 自动带 `_total`）。"""
    names: set[str] = set()
    for attr in dir(metrics_module):
        obj = getattr(metrics_module, attr)
        if isinstance(obj, Counter):
            names.add(obj._name + "_total")
        elif isinstance(obj, (Histogram, Gauge)):
            names.add(obj._name)
    assert len(names) >= 30, (
        f"只从 app.metrics 解析出 {len(names)} 个指标，远少于预期（≥30）。"
        "要么注册表被大幅精简，要么本解析器已失效 —— 后者会让下面所有断言变成空转。"
    )
    return names


def _openapi_paths() -> set[str]:
    """路由真相取自 OpenAPI schema，而不是 `app.routes`。

    OpenAPI 是外部真正能看到的契约；`app.routes` 还包含未挂载/内部条目。
    """
    with TestClient(create_app()) as client:
        spec = client.get("/openapi.json").json()
    paths = {p for p in spec["paths"] if p.startswith("/api/v1")}
    assert len(paths) >= 40, f"只从 OpenAPI 解析出 {len(paths)} 个 /api/v1 路径，远少于预期（≥40）。解析器可能已失效。"
    return paths


def _collection_cron_from_settings() -> dict[str, str]:
    """采集 cron 的真相：与 `app.scheduler` 的 cron_map 同源同名。"""
    mapping = {
        "defillama": settings.defillama_cron,
        "github": settings.github_cron,
        "coingecko": settings.coingecko_cron,
        "cryptorank": settings.cryptorank_cron,
        "rootdata": settings.rootdata_cron,
        "twitter_kol": settings.twitter_kol_cron,
        "twitter_keyword": settings.twitter_keyword_cron,
        "etherscan": settings.etherscan_cron,
        "galxe": settings.galxe_cron,
        "layer3": settings.layer3_cron,
        "discord": settings.discord_cron,
        "reddit": settings.reddit_cron,
        "medium": settings.medium_cron,
        "mirror": settings.mirror_cron,
    }
    assert all(mapping.values()), f"有采集源的 cron 是空值：{mapping}"
    return mapping


def _collection_gating_from_code() -> dict[str, tuple[str, bool]]:
    """每个采集源的门控真相：`(开关配置名, 是否需要 Key)`。

    直接读 `is_enabled()` 的源码，而不是读它在**本机**的返回值 ——
    返回值取决于本地 `.env` 有没有配 Key，CI 上必然不同。
    要钉住的是「文档描述的门控规则」与「代码里的门控规则」一致，
    这一条在任何环境下都应该成立。
    """
    import inspect

    from app.collectors.factory import build_default_registry

    gating: dict[str, tuple[str, bool]] = {}
    for collector in build_default_registry().list_all():
        source = inspect.getsource(type(collector).is_enabled)
        # 两种写法都要认：`settings.galxe_enabled` 与
        # `getattr(settings, "rootdata_enabled", False)`。
        switch = re.search(r"settings(?:\.|,\s*\")(\w+_enabled)", source)
        assert switch, f"{type(collector).__name__}.is_enabled() 里找不到 `*_enabled` 开关 —— 解析器已失效。"
        needs_key = bool(re.search(r"api_key|bearer_token|github_token|bot_token|client_id|client_secret", source))
        gating[collector.source_id] = (switch.group(1), needs_key)
    assert len(gating) >= 10, f"只解析出 {len(gating)} 个采集源的门控，远少于预期（≥10）。"
    return gating


def _alert_names_from_rules() -> set[str]:
    assert ALERT_RULES.is_file(), f"找不到 {ALERT_RULES}"
    names = set(re.findall(r"^\s*-\s*alert:\s*(\S+)", ALERT_RULES.read_text(encoding="utf-8"), re.MULTILINE))
    assert names, f"没从 {ALERT_RULES.name} 解析出任何告警名 —— 解析器已失效。"
    return names


# ── 文档侧解析 ─────────────────────────────────────────────────


def _documented_metrics(body: str) -> set[str]:
    found = set(_METRIC_RE.findall(body))
    assert len(found) >= 8, (
        f"文档正文里只解析出 {len(found)} 个指标名，远少于预期（≥8）。解析器或文档格式已变化，断言不再可信。"
    )
    return found


def _documented_paths(body: str) -> set[str]:
    found = {p for p in _PATH_RE.findall(body) if "*" not in p and "..." not in p}
    assert len(found) >= 8, f"文档正文里只解析出 {len(found)} 个 /api/v1 路径，远少于预期（≥8）。解析器可能已失效。"
    return found


# 「这个东西不存在」的行内标记。带标记的行是文档在**纠错**，不是在给错命令，
# 所以正向断言必须跳过它 —— 但只跳过**那一行**。
#
# 为什么不能整份文档全局豁免（第一版就是这么写的，被变异测试抓出来了）：
# 只要 §12 的幽灵清单里列了 `/api/v1/audit`，正文任何地方写
# 「查 `GET /api/v1/audit` 的 count」都会被放过 —— 一条假命令伪装成
# 「已登记的已知问题」，正是这套门禁要防的事。豁免必须逐行、且要求
# 那一行自己说出「不存在」。
_ABSENCE_MARKERS = ("不存在", "没有", "❌", "从未", "顺序颠倒", "真实是")


def _lines_asserting_existence(body: str) -> list[str]:
    """只保留「声称某东西存在」的行；带否定标记的行按逐行豁免剔除。"""
    kept = [line for line in body.splitlines() if not any(m in line for m in _ABSENCE_MARKERS)]
    assert len(kept) > 200, (
        f"逐行过滤后只剩 {len(kept)} 行，远少于预期（>200）—— 过滤条件写反了会让断言几乎不检查任何东西。"
    )
    return kept


def _asserted_paths(body: str) -> set[str]:
    """正文里**被当成可用**的接口路径。"""
    found = _documented_paths("\n".join(_lines_asserting_existence(body)))
    return found


def _asserted_scripts(body: str) -> set[str]:
    """正文里**被当成可用**的脚本。"""
    return _documented_scripts("\n".join(_lines_asserting_existence(body)))


def _documented_scripts(body: str) -> set[str]:
    found = set(_SCRIPT_RE.findall(body))
    assert len(found) >= 6, f"文档里只解析出 {len(found)} 个脚本名，远少于预期（≥6）。解析器可能已失效。"
    return found


def _documented_cron(text: str) -> dict[str, str]:
    rows = dict(_CRON_ROW_RE.findall(_block(text, "cron")))
    assert len(rows) >= 10, f"§7.1 cron 表只解析出 {len(rows)} 行，远少于预期（≥10）。表格格式可能已变化。"
    return rows


def _documented_readiness(text: str) -> dict[str, tuple[str, bool]]:
    """§4.3 的门控表：`源 id → (开关配置名, 是否需要 Key)`。

    表里的 ✅/❌ 描述的是「这个源要不要 Key」，**不是**「本机现在是否就绪」——
    后者取决于 `.env`，写进被门禁比对的表格里会让这份文档在别人机器上必然过时。
    """
    rows = re.findall(
        r"^\|\s*`([a-z0-9_]+)`\s*\|\s*`([A-Z0-9_]+)`\s*\|\s*(✅|❌)",
        _block(text, "ready"),
        re.MULTILINE,
    )
    assert len(rows) >= 10, f"§4.3 门控表只解析出 {len(rows)} 行，远少于预期（≥10）。表格格式可能已变化。"
    return {sid: (switch.lower(), mark == "✅") for sid, switch, mark in rows}


def _documented_admin_prefixes(text: str) -> set[str]:
    found = set(re.findall(r"`(/api/v1/[A-Za-z0-9_/\-]+)`", _block(text, "admin")))
    assert found, "§5.2 管理员前缀块里解析不到任何路径 —— 解析器已失效。"
    return found


def _ghost_metrics(text: str) -> set[str]:
    found = set(re.findall(r"`(airdrop_[a-z0-9_]+)`", _block(text, "ghost_metrics")))
    assert len(found) >= 15, f"§12.1 幽灵指标清单只解析出 {len(found)} 个，远少于预期（≥15）。"
    return found


def _ghost_paths(text: str) -> set[str]:
    block = _block(text, "ghost_paths")
    found = {p for p in re.findall(r"`(?:GET|POST|PATCH|PUT|DELETE)?\s*(/api/v1[A-Za-z0-9_/{}.\-]*)`", block)}
    assert len(found) >= 3, f"§12.2 幽灵路径清单只解析出 {len(found)} 个，远少于预期（≥3）。"
    return found


def _ghost_scripts(text: str) -> set[str]:
    found = set(_SCRIPT_RE.findall(_block(text, "ghost_paths")))
    assert len(found) >= 2, f"§12.2 幽灵脚本清单只解析出 {len(found)} 个，远少于预期（≥2）。"
    return found


# ═══════════════════════════════════════════════════════════════
# 正向：文档写的都必须真实存在
# ═══════════════════════════════════════════════════════════════


class TestDocumentedMetricsExist:
    def test_every_documented_metric_is_registered(self):
        text = _doc_text()
        body = _body_without_distortion_section(text)
        documented = _documented_metrics("\n".join(_lines_asserting_existence(body)))
        exported = _exported_metric_names()
        ghosts = documented - exported
        assert not ghosts, (
            f"{DOC.name} 正文引用了 {len(ghosts)} 个代码里不存在的指标：{sorted(ghosts)}。\n"
            "Prometheus 查不存在的指标不报错，只返回空结果 —— 面板会显示成「系统很安静」，"
            "告警规则则永远不触发。幽灵指标名比错误的阈值危险得多。\n"
            "要么改成 OBSERVABILITY.md §3.2 里真实存在的名字，要么移进 §12.1 失真清单。"
        )


class TestDocumentedPathsExist:
    def test_every_documented_api_path_is_real(self):
        text = _doc_text()
        body = _body_without_distortion_section(text)
        documented = _asserted_paths(body)
        real = _openapi_paths()
        # `ADMIN_ONLY_PREFIXES` 是**前缀**而非路由（`/api/v1/re-score` 就没有
        # 对应路由），由 TestAdminPrefixesMatchCode 单独与代码比对。
        # 注意这里不豁免 §12.2 的幽灵路径：豁免必须靠 `_ABSENCE_MARKERS` 逐行
        # 判定，否则「已登记为幽灵」会变成一张全文通行证。
        exempt = set(ADMIN_ONLY_PREFIXES)

        def is_real(path: str) -> bool:
            # 精确命中，或作为某条真实路由的前缀（文中确实需要提「前缀」）
            return path in real or any(r.startswith(path.rstrip("/") + "/") for r in real)

        bogus = {p for p in documented - exempt if not is_real(p)}
        assert not bogus, (
            f"{DOC.name} 正文把 {len(bogus)} 个 OpenAPI 里不存在的路径当成可用接口：{sorted(bogus)}。\n"
            "运维手册里的假路径只在故障时暴露 —— 那正是最不该现场排查文档的时候。\n"
            "要么改成真实路径，要么在那一行明确写出它不存在。"
        )


class TestDocumentedScriptsExist:
    def test_every_documented_script_file_exists(self):
        text = _doc_text()
        body = _body_without_distortion_section(text)
        documented = _asserted_scripts(body)
        missing = set()
        for name in documented:
            in_root = (REPO_ROOT / "scripts" / name).is_file()
            in_backend = (REPO_ROOT / "backend" / "scripts" / name).is_file()
            if not in_root and not in_backend:
                missing.add(name)
        assert not missing, (
            f"{DOC.name} 把 {len(missing)} 个不存在的脚本当成可用：{sorted(missing)}。\n"
            "上一版本整段贴出了 `diagnose.sh` / `heal.sh` 的「源码」，而这两个文件从未存在过 —— "
            "贴出源码让人完全不会怀疑它不存在。"
        )


# ═══════════════════════════════════════════════════════════════
# 反向：失真清单里的东西必须**确实不存在**
# ═══════════════════════════════════════════════════════════════


class TestDistortionListsAreActuallyDistorted:
    """§12 的清单如果混进了真实存在的东西，它自己就成了新的谎言。"""

    def test_ghost_metrics_really_do_not_exist(self):
        ghosts = _ghost_metrics(_doc_text())
        exported = _exported_metric_names()
        wrong = ghosts & exported
        assert not wrong, (
            f"§12.1 把 {len(wrong)} 个**真实存在**的指标列为「不存在」：{sorted(wrong)}。\n"
            "一份用来纠错的清单本身出错，比原来的错误更难被发现。"
        )

    def test_ghost_paths_really_do_not_exist(self):
        ghosts = _ghost_paths(_doc_text())
        real = _openapi_paths()
        wrong = ghosts & real
        assert not wrong, f"§12.2 把 {len(wrong)} 个**真实存在**的路径列为「不存在」：{sorted(wrong)}。"

    def test_ghost_scripts_really_do_not_exist(self):
        ghosts = _ghost_scripts(_doc_text())
        wrong = {
            name
            for name in ghosts
            if (REPO_ROOT / "scripts" / name).is_file() or (REPO_ROOT / "backend" / "scripts" / name).is_file()
        }
        assert not wrong, f"§12.2 把 {len(wrong)} 个**真实存在**的脚本列为「不存在」：{sorted(wrong)}。"

    def test_rescore_endpoint_really_does_not_exist(self, monkeypatch):
        """§12.2 的核心论点：re-score 接口不存在，但因为鉴权前置而返回 403。

        这一条值得单独钉：403 比 404 更能骗人（「只是我权限不够」），
        正是它让文档里的错误活了这么久。断言必须证明**用管理员凭据也是 404**。

        注意 `conftest.py` 把 `API_KEY` 置空（否则本地 .env 的生产参数会让
        Settings 自检抛错），而鉴权中间件在 key 为空时**整体放行** ——
        所以这里必须显式注入一个 key，否则测的就不是鉴权路径，
        两次请求都拿 404，403 那半句论述等于没验证。
        """
        real = _openapi_paths()
        assert not [p for p in real if "re-score" in p], (
            "OpenAPI 里出现了 re-score 路由 —— §12.2 的论述已过期，请同步文档。"
        )
        admin_key = "operations-doc-parity-admin-key"
        monkeypatch.setattr(settings, "api_key", admin_key)
        with TestClient(create_app()) as client:
            anon = client.post("/api/v1/auth/anonymous").json()["access_token"]
            as_anon = client.post("/api/v1/re-score/1", headers={"Authorization": f"Bearer {anon}"})
            as_admin = client.post("/api/v1/re-score/1", headers={"X-API-Key": admin_key})
        assert as_anon.status_code == 403, (
            f"匿名调用 /api/v1/re-score/1 返回 {as_anon.status_code}，预期 403（鉴权在路由匹配前拦下）。"
        )
        assert as_admin.status_code == 404, (
            f"管理员调用 /api/v1/re-score/1 返回 {as_admin.status_code}，预期 404（该接口真的不存在）。"
        )


# ═══════════════════════════════════════════════════════════════
# 逐项对齐：cron / 前缀 / 告警 / 源清单 / 阈值 / 关键数字
# ═══════════════════════════════════════════════════════════════


class TestCronTableMatchesSettings:
    def test_every_documented_cron_matches_settings(self):
        documented = _documented_cron(_doc_text())
        actual = _collection_cron_from_settings()
        assert set(documented) == set(actual), (
            f"§7.1 的源清单与调度器不一致。\n文档多出：{sorted(set(documented) - set(actual))}\n"
            f"文档缺少：{sorted(set(actual) - set(documented))}"
        )
        mismatched = {k: (documented[k], actual[k]) for k in actual if documented[k] != actual[k]}
        assert not mismatched, (
            f"§7.1 有 {len(mismatched)} 个 cron 与配置不符（文档值, 实际值）：{mismatched}。\n"
            "写错的 cron 会让值班在错误的时间窗口里找错误的原因。"
        )


class TestAdminPrefixesMatchCode:
    def test_documented_admin_prefixes_match_code_exactly(self):
        documented = _documented_admin_prefixes(_doc_text())
        actual = set(ADMIN_ONLY_PREFIXES)
        assert documented == actual, (
            f"§5.2 与 app.auth.ADMIN_ONLY_PREFIXES 不一致。\n"
            f"文档多出：{sorted(documented - actual)}\n文档缺少：{sorted(actual - documented)}\n"
            "这份清单是运维判断「该用哪种凭据」的唯一依据，错一项就会在故障时白试一轮。"
        )


class TestAlertNamesMatchRules:
    def test_documented_alert_names_match_alert_rules(self):
        text = _doc_text()
        anchor = "### 8.1 告警规则"
        assert anchor in text, f"{DOC.name} 里找不到 `{anchor}`"
        start = text.index(anchor)
        section = text[start : start + 900]
        documented = set(_ALERT_NAME_RE.findall(section))
        actual = _alert_names_from_rules()
        # 小节里还有 `configs/...` 这类反引号内容，只保留真正的告警名候选
        documented &= {
            n for n in documented if n in actual or n.startswith(("Pipeline", "No", "DB", "High", "Backend"))
        }
        assert documented == actual, (
            f"§8.1 的告警名与 alert_rules.yml 不一致。\n"
            f"文档多出：{sorted(documented - actual)}\n文档缺少：{sorted(actual - documented)}"
        )


class TestCollectionSourcesMatchScheduler:
    def test_documented_source_ids_match_scheduler(self):
        text = _doc_text()
        anchor = "### 4.3 采集源故障"
        assert anchor in text, f"{DOC.name} 里找不到 `{anchor}`"
        documented = _documented_readiness(text)
        actual = set(_collection_cron_from_settings())
        missing = actual - set(documented)
        assert not missing, f"§4.3 漏了 {len(missing)} 个采集源：{sorted(missing)}。漏写的源在故障时不会被想起来查。"
        extra = set(documented) - actual
        assert not extra, f"§4.3 多列了 {len(extra)} 个调度器里没有的源：{sorted(extra)}。"

    def test_documented_config_ready_matches_endpoint(self):
        """§4.3 的门控表必须与 `is_enabled()` 的实现一致。

        上一版文档写「10 个源全部 `config_ready=true`」，实测只有 5 个 ——
        另外 5 个开关关着、Key 也没配。这条错误会让「为什么没发现新项目」
        的排查一头扎进一个从未运行过的源的日志里。

        断言比对的是**门控规则**（开关名 + 要不要 Key），不是本机当前的
        就绪值 —— 后者取决于 `.env`，钉住它会让这份文档在 CI 和别人机器上
        必然失败，而那种失败传达的是错误的信息。
        """
        documented = _documented_readiness(_doc_text())
        actual = _collection_gating_from_code()
        assert set(documented) == set(actual), (
            f"§4.3 的源清单与代码不一致。\n文档多出：{sorted(set(documented) - set(actual))}\n"
            f"文档缺少：{sorted(set(actual) - set(documented))}"
        )
        mismatched = {k: (documented[k], actual[k]) for k in actual if documented[k] != actual[k]}
        assert not mismatched, (
            f"§4.3 有 {len(mismatched)} 个源的门控与代码不符（文档值, 实际值）：{mismatched}。\n"
            "把「需要 Key」写成「不需要」，或写错开关名，都会让人以为源开着而其实从未运行。"
        )
        # 兜底：真实值里必须同时有需要 Key 和不需要 Key 的源，否则这条断言
        # 退化成「全 True == 全 True」，文档照抄一个常量也能通过。
        assert len({needs_key for _, needs_key in actual.values()}) == 2, (
            "代码里所有采集源的 Key 需求都一样了 —— 此时本断言无法区分「文档正确」和「文档照抄常量」。"
        )


class TestCollectionAlertThresholds:
    """§8.2 的 5 个阈值必须与 `check_alerts()` 的硬编码值一致。"""

    def test_documented_thresholds_match_code(self):
        from app.collectors import metrics as collectors_metrics

        source = Path(collectors_metrics.__file__).read_text(encoding="utf-8")
        code_thresholds = dict(
            re.findall(
                r'"(success_rate|avg_latency_ms|freshness_minutes|coverage_rate|duplicate_rate)":\s*([0-9.]+),', source
            )
        )
        assert len(code_thresholds) == 5, (
            f"只从 {Path(collectors_metrics.__file__).name} 解析出 {len(code_thresholds)} 个阈值，预期 5 个。解析器已失效。"
        )
        text = _doc_text()
        anchor = "### 8.2 代码侧的采集告警"
        assert anchor in text, f"{DOC.name} 里找不到 `{anchor}`"
        section = text[text.index(anchor) : text.index(anchor) + 900]
        for name, value in code_thresholds.items():
            numeric = float(value)
            # 文档里写成整数形式（30000 而不是 30000.0）也算对
            candidates = {value, str(int(numeric)) if numeric.is_integer() else value}
            assert any(f"{name} " in section and c in section for c in candidates), (
                f"§8.2 里找不到阈值 `{name}` = {value}。阈值写错会让值班判断「这算不算异常」时得出反的结论。"
            )


class TestCriticalNumbersMatchCode:
    """一批最容易写错、且写错代价最高的数字。"""

    def test_backend_port_is_documented_correctly(self):
        """上一版本全篇把后端端口写成 8000（真实 8002）。

        这里只查**可执行形态**的 8000（`localhost:8000` / `:8000` 这类
        URL 与端口映射），不查散文。文档需要在 §3.4 / §12.4 讲清
        「脚本原来硬编码的是 8000，2026-08-24 已修」—— 那是在纠错，
        不是在给错命令。把散文一起禁掉会逼着文档删掉这条真实的历史记录，
        而**知道某个坑存在过**对排查有价值：这条报错（「服务启动超时」）
        以后再出现时，第一件事仍然是确认探测地址对不对。
        """
        text = _doc_text()
        body = _body_without_distortion_section(text)
        assert str(settings.port) in body, f"文档正文里找不到真实端口 {settings.port}。"
        wrong_url = re.compile(r"(?:localhost|127\.0\.0\.1|[a-z-]+):8000\b|\b8000:8000\b")
        stray = [line for line in body.splitlines() if wrong_url.search(line)]
        assert not stray, (
            f"正文里有 {len(stray)} 处可直接复制执行的 8000 地址（真实端口是 {settings.port}）：{stray[:3]}"
        )

    def test_circuit_breaker_params_match_config(self):
        section = _doc_text()
        assert str(settings.fetcher_circuit_breaker_threshold) in section, (
            f"文档里找不到熔断阈值 {settings.fetcher_circuit_breaker_threshold}"
        )
        assert str(settings.fetcher_circuit_breaker_timeout_seconds) in section, (
            f"文档里找不到熔断超时 {settings.fetcher_circuit_breaker_timeout_seconds}"
        )

    def test_discovery_threshold_matches_config(self):
        assert str(settings.discovery_score_analysis_threshold) in _doc_text(), (
            f"文档里找不到发现阈值 {settings.discovery_score_analysis_threshold} —— "
            "它决定多少采集结果进入分析，写错会让「为什么项目不增长」的排查跑偏。"
        )

    def test_label_thresholds_match_scorer(self):
        """§4.8 直接抄了 `LABEL_THRESHOLDS` 的字面值，必须逐项对齐。

        标签阈值不在配置里而在代码里，运维改不了、只能读 —— 文档写错
        就会让人把「分数 52 却标 WATCH」当成缺陷去查。
        """
        from app.agents.scorer import LABEL_THRESHOLDS

        text = _doc_text()
        documented = [(int(c), lab) for c, lab in re.findall(r"\((\d+),\s*[\"'\u201c]([A-Z]+)[\"'\u201d]\)", text)]
        assert documented, (
            '文档里解析不到任何 `(分数,"标签")` 形式的阈值 —— §4.8 的写法可能已变，解析不到就等于断言空转。'
        )
        assert documented == [(c, lab) for c, lab in LABEL_THRESHOLDS], (
            f"§4.8 的标签阈值与 scorer.py 不一致。\n文档：{documented}\n代码：{list(LABEL_THRESHOLDS)}"
        )

    def test_analysis_run_limit_and_cron_match_config(self):
        text = _doc_text()
        assert str(settings.analysis_run_limit) in text, (
            f"文档里找不到 ANALYSIS_RUN_LIMIT={settings.analysis_run_limit}"
        )
        assert f"`{settings.cron_expression}`" in text, f"文档里找不到分析 cron `{settings.cron_expression}`"
        assert f"`{settings.archive_cron}`" in text, f"文档里找不到归档 cron `{settings.archive_cron}`"

    def test_archive_retention_days_match_config(self):
        text = _doc_text()
        for name, value in (
            ("RAW_ARCHIVE_RETENTION_DAYS", settings.raw_archive_retention_days),
            ("SIGNALS_ARCHIVE_RETENTION_DAYS", settings.signals_archive_retention_days),
        ):
            assert f"{name}={value}" in text, f"文档里找不到 `{name}={value}`"


class TestClaimsOfAbsenceAreStillTrue:
    """§11「未实现」里的「没有」必须真的还没有。

    一个已经实现了的功能被文档写成「未实现」，会让运维不去用它 ——
    和把未实现写成已实现同样有害，只是方向相反。
    """

    def test_diagnose_and_heal_scripts_still_absent(self):
        for name in ("diagnose.sh", "heal.sh"):
            assert not (REPO_ROOT / "scripts" / name).is_file(), (
                f"scripts/{name} 现在存在了 —— §11 与 §12.2 已过期，请同步文档。"
            )

    def test_evaluation_collection_dir_still_absent(self):
        assert not (REPO_ROOT / "evaluation" / "collection").is_dir(), (
            "evaluation/collection/ 现在存在了 —— §11 已过期，请同步文档。"
        )

    def test_llm_budget_enforcement_is_wired_into_the_call_path(self):
        """反过来钉：预算现在**真的会拦**，§4.4 / §11 / §12.3 已同步改口。

        这条门禁在 2026-08-24 之前是相反的方向 —— 它断言
        `llm_daily_budget_usd` 只出现在 config.py 与两个只读端点里，
        用来保护"文档说它不生效"这句话的真实性。

        现在实现补上了，门禁必须一起转向，否则它会**阻止正确的实现**：
        一个断言"这个功能必须仍然不存在"的测试，在功能实现后就成了
        反向的假绿 —— 它会让 CI 拒绝真正的修复。

        转向后钉的是三件缺一不可的事（少任何一件，预算都不会真的拦）：
        1. `budget.check_budget()` 存在且被 `llm/client.py` 调用；
        2. 调用点在**发请求之前**（否则是事后记账，不是拦截）；
        3. 成功调用会 `record_spend()`（不记账 = 累计永远是 0 = 永不超限）。
        """
        client_src = (REPO_ROOT / "backend" / "app" / "llm" / "client.py").read_text(encoding="utf-8")
        assert len(client_src) > 3000, f"client.py 只有 {len(client_src)} 字符，疑似读错文件 —— 解析器失效。"

        assert "check_budget" in client_src, (
            "app/llm/client.py 没有调用 check_budget —— 预算又变回装饰性配置了。\n"
            "文档 §4.4 / §12.3 现在写的是「真实拦截」，两边必须一致。"
        )
        assert "record_spend" in client_src, (
            "app/llm/client.py 没有调用 record_spend —— 花费不入账，日累计永远是 0，预算永不触发。"
        )

        # 拦截必须在发请求之前：比较两者在**llm_chat 函数体内**的先后位置。
        #
        # 必须先切出函数体再比较。第一版直接在整个文件里 index() 两个锚点，
        # 结果 `await _try_single(` 命中的是 `_RawCompletion` docstring 里
        # 举例用的那一行（第 169 行），位置远在真正的调用点之前，
        # 于是断言失败并报告"预算检查在调用之后" —— 一个**完全错误的诊断**。
        # 这跟本轮反复出现的那条是同一个：解析器出错时的表现是"断言失败"，
        # 和"被测对象真的有问题"长得一模一样。
        body_start = client_src.index("async def llm_chat(")
        body = client_src[body_start : client_src.index("async def llm_chat_simple(", body_start)]
        assert len(body) > 1500, f"llm_chat 函数体只切出 {len(body)} 字符 —— 切片锚点已失效，先修解析器。"

        check_at = body.index("check_budget(budget_usd=")
        dispatch_at = body.index("await _try_single(")
        assert check_at < dispatch_at, (
            "预算检查出现在 _try_single 调用之后 —— 那是事后记账，不是拦截。\n"
            f"（函数体内偏移：check_budget {check_at}，_try_single {dispatch_at}）"
        )

    def test_the_budget_doc_rows_no_longer_say_it_is_fake(self):
        """§11 未实现清单里不能再留着预算与成本指标这两条。

        它们在 2026-08-24 已实现。把已实现的控制留在「未实现」清单里，
        会让人重做一遍，或者放弃一个可用的控制 —— 清单的可信度是有限资源，
        一条假行会让读者怀疑其余每一行。
        """
        text = _doc_text()
        for stale in ("LLM 成本预算真实拦截 | ❌", "LLM token / 成本指标 | ❌"):
            assert stale not in text, f"OPERATIONS.md §11 仍写着「{stale}」，但它已经实现了。"

    def test_metrics_table_still_has_no_production_writer(self):
        """§11 说 `metrics` 表 0 个生产写入方。写入方只应出现在 repository 定义里。"""
        app_dir = REPO_ROOT / "backend" / "app"
        writers = {
            path.relative_to(app_dir).as_posix()
            for path in app_dir.rglob("*.py")
            if "INSERT INTO metrics" in path.read_text(encoding="utf-8")
        }
        assert writers <= {"repositories/v2.py"}, (
            f"`metrics` 表出现了新的写入方：{sorted(writers - {'repositories/v2.py'})} —— §11 已过期，请同步文档。"
        )


class TestDeadTableListIsComplete:
    """§12.14 列的 7 张死表 —— 这一栏此前只写了 `metrics` 一张。

    2026-08-25 在线上库上逐表实测才发现是 7 张。
    **只钉一张的门禁会让另外 6 张继续隐形** —— 而其中 `audit_logs`
    是审计日志，会被直接算进合规评估。

    三个方向都要守：
      · 死表里出现了生产写入方 → 文档过期（好事，但必须同步）
      · 文档列的表在 schema 里不存在 → 这份清单自己变成了幻影清单
      · 隔离实现改成用那张表 → 它就不再是死表
    """

    # 判据：0 行 + 除 repositories/ 外无写入方（2026-08-25 线上库实测）
    _DEAD_TABLES = (
        "metrics",
        "audit_logs",
        "llm_eval_changelog",
        "narratives",
        "dedup_keys",
        "prompt_versions",
        "quarantine",
    )
    _REPO_FILES: ClassVar[frozenset[str]] = frozenset({"repositories/v2.py"})

    @staticmethod
    def _dead_table_rows() -> set[str]:
        """抽出 §12.14 死表表格里被反引号点名的表名。

        只认「| `名字` | 数字 | ... |」这种表格行，不认散文里的提及。
        """
        text = _doc_text()
        start = text.find("### 12.14")
        assert start != -1, "OPERATIONS.md 里找不到 §12.14 —— 章节被删或改名了，先修文档。"
        end = text.find("\n### ", start + 1)
        section = text[start:] if end == -1 else text[start:end]

        rows = set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|\s*\d+\s*\|", section, re.MULTILINE))
        assert rows, "§12.14 里一行死表表格都没抽到 —— 解析器失效，别信结论。"
        return rows

    def test_doc_lists_every_dead_table(self):
        """每张死表都必须在 §12.14 **那张表格里**有自己的一行。

        ⚠️ 第一版写的是「整篇文档里搜表名」，变异测试直接证明它拦不住：
        把 `audit_logs` 从 §12.14 表格里删掉，门禁**照常通过** ——
        因为 `audit_logs` 在 §11 那行里也出现了，全文搜索照样命中。

        **"这个词在文档里出现过"和"这一行还在"是两件事。**
        本会话第三次踩同一个形状了（前两次：术语门禁、版本号门禁）。
        判据必须落在读者真正会看的那张表上，不是整篇文档。
        """
        rows = self._dead_table_rows()
        missing = [name for name in self._DEAD_TABLES if name not in rows]
        assert not missing, (
            f"这些死表在 §12.14 的表格里没有自己的一行：{missing}\n"
            "（注意：写在文档别处不算 —— 读者是在这张表里找它的。）"
        )

    def test_dead_tables_still_have_no_production_writer(self):
        """逐张核对，而不是只核对 `metrics`。"""
        app_dir = REPO_ROOT / "backend" / "app"
        sources = {
            path.relative_to(app_dir).as_posix(): path.read_text(encoding="utf-8") for path in app_dir.rglob("*.py")
        }
        assert len(sources) > 100, f"只扫到 {len(sources)} 个文件 —— 搜索器失效，别信下面的结论。"

        revived: dict[str, list[str]] = {}
        for table in self._DEAD_TABLES:
            writers = {
                rel
                for rel, text in sources.items()
                if f"INSERT INTO {table}" in text or f'INSERT INTO "{table}"' in text
            }
            extra = sorted(writers - self._REPO_FILES)
            if extra:
                revived[table] = extra

        assert not revived, (
            f"这些「死表」出现了生产写入方：{revived}\n"
            "如果是新接上的功能，请更新 OPERATIONS.md §12.14 与 §11 —— "
            "一张已经在用的表被文档记成死表，会让人去删它。"
        )

    def test_dead_tables_exist_in_schema(self):
        """反向：文档点名的表必须真的在 schema 里。

        否则这份"死表清单"自己就成了幻影清单 —— 和它想揭露的问题同一种。
        """
        db_source = (REPO_ROOT / "backend" / "app" / "db.py").read_text(encoding="utf-8")
        phantom = [name for name in self._DEAD_TABLES if f"CREATE TABLE IF NOT EXISTS {name} " not in db_source]
        assert not phantom, f"§12.14 列的这些表在 db.py 里找不到建表语句：{phantom}"

    def test_quarantine_feature_uses_the_flag_not_the_table(self):
        """`quarantine` 表是死的，但隔离**功能**是真的 —— 这个区分必须钉住。

        差点搞错的地方：只看表名和行数会得出"隔离功能是假的"，
        而真实实现走 `raw_projects.quarantined` 标志位（实测线上库 3 行）。
        **同名但无关**是这类误判里最容易踩的一种。

        如果哪天真实实现改成用那张表，这条会红 —— 那时该更新 §12.14。
        """
        source = (REPO_ROOT / "backend" / "app" / "quarantine.py").read_text(encoding="utf-8")
        assert "raw_projects" in source, "`app/quarantine.py` 不再操作 raw_projects —— 实现变了，§12.14 请同步。"
        assert "quarantined" in source, "找不到 `quarantined` 标志位 —— 实现变了。"
        assert "INSERT INTO quarantine" not in source, (
            "隔离实现开始写 `quarantine` 表了 —— 那它就不再是死表，请更新 §12.14。"
        )


class TestMigrationCountIsCurrent:
    """§3.5 写了 Alembic 有几个版本 —— 这种"数出来的数字"每加一个迁移就过期。

    2026-08-24 实测它已经过期了：文档写「只有 3 个版本」，实际 4 个
    （`0004_llm_spend_daily` 是当天随预算账本加的）。

    为什么这条值得钉：回滚步骤是**出事时照着做**的，那时没人有空核对。
    数字少一个，`downgrade -1` 回到的位置就和预期差一格 ——
    而 `downgrade` 不会因为文档写错而报错，它会老老实实退一步，
    只是运维以为自己退到了别的地方。
    """

    def test_documented_migration_count_matches_reality(self):
        versions_dir = REPO_ROOT / "backend" / "alembic" / "versions"
        real = sorted(p.stem for p in versions_dir.glob("[0-9][0-9][0-9][0-9]_*.py"))

        minimum_expected = 4
        assert len(real) >= minimum_expected, (
            f"只找到 {len(real)} 个迁移文件（{real}）—— 命名规则可能变了，解析不到就等于断言空转，先修这里的 glob。"
        )

        text = _doc_text()
        # 锚点刻意不含中文可选组：`(?:只)?` 这种写法会被 check_encoding.py
        # 判成「二型：整字变 '?'」—— 它的启发式无法区分正则语法里的 `?`
        # 和真被写坏的中文字。改用「数量 + 个版本」这个不带可选中文的形状。
        documented = re.findall(r"Alembic 迁移目前有 \*\*(\d+) 个版本\*\*", text)
        assert documented, (
            "§3.5 里解析不到「Alembic 迁移目前有 N 个版本」这句话 —— "
            "措辞可能改了。解析不到就等于这条门禁空转，先修锚点再说。"
        )
        assert int(documented[0]) == len(real), (
            f"§3.5 说有 {documented[0]} 个 Alembic 版本，实际 {len(real)} 个：{real}\n"
            "回滚步骤是出事时照着做的，数字错了会让人以为自己退到了别的位置。"
        )

    def test_every_migration_file_is_named_in_the_doc(self):
        """光对数字不够 —— 4 个版本里换掉一个，数字还是 4。

        所以逐个核对文件名都出现在文档里。这条也顺便保证新增迁移时
        必须回来改文档，而不是只把数字 +1。
        """
        versions_dir = REPO_ROOT / "backend" / "alembic" / "versions"
        real = sorted(p.stem for p in versions_dir.glob("[0-9][0-9][0-9][0-9]_*.py"))
        text = _doc_text()

        missing = [name for name in real if name not in text]
        assert not missing, f"这些迁移在 OPERATIONS.md 里没提到：{missing}（§3.5 请同步）"


# ═══════════════════════════════════════════════════════════════
# 解析器自检
# ═══════════════════════════════════════════════════════════════


class TestParsersFailLoudly:
    """解析器解析不到东西时必须报错，而不是返回空集合让断言空转。"""

    def test_metric_parser_finds_real_metrics(self):
        names = [
            "airdrop_pipeline_runs_total",
            "airdrop_pipeline_duration_seconds",
            "airdrop_db_projects_total",
            "airdrop_db_raw_projects_total",
            "airdrop_collection_runs_total",
            "airdrop_llm_requests_total",
            "airdrop_llm_errors_total",
            "airdrop_http_requests_total",
        ]
        found = _documented_metrics(" ".join(f"`{n}`" for n in names))
        assert found == set(names), f"解析结果与输入不符：{found}"

    def test_metric_parser_rejects_empty_input(self):
        with pytest.raises(AssertionError, match="只解析出 0 个指标名"):
            _documented_metrics("这段文字里没有任何指标名。")

    def test_path_parser_rejects_empty_input(self):
        with pytest.raises(AssertionError, match="只解析出 0 个 /api/v1 路径"):
            _documented_paths("这段文字里没有任何接口路径。")

    def test_path_parser_skips_wildcards(self):
        real = [
            "/api/v1/run",
            "/api/v1/quarantine",
            "/api/v1/archive/runs",
            "/api/v1/export",
            "/api/v1/import",
            "/api/v1/settings/config",
            "/api/v1/llm/status",
            "/api/v1/auth/anonymous",
        ]
        body = " ".join(f"`{p}`" for p in real) + " `/api/v1/*` `/api/v1/...`"
        found = _documented_paths(body)
        assert found == set(real), f"通配写法不该被当成真实路径：{found - set(real)}"

    def test_script_parser_rejects_empty_input(self):
        with pytest.raises(AssertionError, match="只解析出 0 个脚本名"):
            _documented_scripts("这段文字里没有任何脚本。")

    def test_absence_filter_keeps_positive_lines_and_drops_negated_ones(self):
        body = "\n".join(
            ["跑 `scripts/backup.sh` 做备份。"] * 250
            + ["`scripts/heal.sh` 文件不存在。"] * 150
            + ["| `scripts/diagnose.sh` | ❌ 未实现 |"] * 10
        )
        kept = _lines_asserting_existence(body)
        assert all("backup.sh" in line for line in kept), "带否定标记的行没被剔除。"
        assert len(kept) == 250, f"保留了 {len(kept)} 行，预期 250。"

    def test_absence_filter_rejects_over_filtering(self):
        """过滤条件写反（把绝大多数行都剔掉）时必须报错，而不是安静地几乎不检查。"""
        with pytest.raises(AssertionError, match="逐行过滤后只剩"):
            _lines_asserting_existence("`scripts/heal.sh` 不存在\n" * 300)

    def test_readiness_parser_rejects_missing_block(self):
        with pytest.raises(AssertionError, match="找不到标记"):
            _documented_readiness("没有就绪表标记的文本")

    def test_readiness_parser_reads_both_columns(self):
        block_begin, block_end = _BLOCKS["ready"]
        rows = "\n".join(f"| `src{i}` | `SRC{i}_ENABLED` | {'✅' if i % 2 else '❌'} 说明 |" for i in range(10))
        parsed = _documented_readiness(f"{block_begin}\n{rows}\n{block_end}")
        assert parsed["src1"] == ("src1_enabled", True)
        assert parsed["src2"] == ("src2_enabled", False)

    def test_collection_gating_parser_finds_all_sources(self):
        gating = _collection_gating_from_code()
        assert gating["defillama"] == ("defillama_enabled", False)
        assert gating["github"] == ("github_enabled", True)

    def test_block_parser_rejects_missing_anchor(self):
        with pytest.raises(AssertionError, match="找不到标记"):
            _block("没有任何标记的文本", "cron")

    def test_block_parser_rejects_empty_block(self):
        begin, end = _BLOCKS["cron"]
        with pytest.raises(AssertionError, match="是空的"):
            _block(f"{begin}\n\n{end}", "cron")

    def test_distortion_section_anchor_is_required(self):
        with pytest.raises(AssertionError, match="找不到"):
            _body_without_distortion_section("没有失真记录小节的文本")

    def test_doc_length_guard_rejects_truncated_file(self, monkeypatch, tmp_path):
        tiny = tmp_path / "OPERATIONS.md"
        tiny.write_text("# 太短了", encoding="utf-8")
        monkeypatch.setattr(f"{__name__}.DOC", tiny)
        with pytest.raises(AssertionError, match="疑似被截断或清空"):
            _doc_text()

    def test_openapi_parser_finds_many_paths(self):
        assert len(_openapi_paths()) >= 40

    def test_alert_rule_parser_finds_names(self):
        assert "BackendDown" in _alert_names_from_rules()
