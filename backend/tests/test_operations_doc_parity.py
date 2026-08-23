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
    }
    assert all(mapping.values()), f"有采集源的 cron 是空值：{mapping}"
    return mapping


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
        section = text[text.index(anchor) : text.index(anchor) + 700]
        # 源 id 含数字（layer3）。写成 `[a-z]+` 会静默漏掉一整个源 ——
        # 而"漏掉"在这个断言里表现为"文档写全了却报错"，很容易被误当成文档问题。
        documented = set(re.findall(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)?)`", section))
        actual = set(_collection_cron_from_settings())
        assert len(documented & actual) >= 5, (
            f"§4.3 只解析出 {len(documented & actual)} 个已知源名，解析器可能已失效（解析不到就等于断言空转）。"
        )
        missing = actual - documented
        assert not missing, f"§4.3 漏了 {len(missing)} 个采集源：{sorted(missing)}。漏写的源在故障时不会被想起来查。"


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
        URL 与端口映射），不查散文。文档确实需要在 §3.4 说明
        「`deploy.sh` 里硬编码的是 8000」—— 那是在纠错，不是在给错命令。
        把散文一起禁掉会逼着文档删掉这条真实的警告。
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

    def test_llm_budget_still_has_no_enforcement(self):
        """§4.4 与 §12.3 的核心论点：预算配置只被读出来展示，不拦截任何调用。"""
        app_dir = REPO_ROOT / "backend" / "app"
        readers = {
            path.relative_to(app_dir).as_posix()
            for path in app_dir.rglob("*.py")
            if "llm_daily_budget_usd" in path.read_text(encoding="utf-8")
        }
        # 允许：定义处（config.py）+ 两个只读回显端点。任何其它文件引用它，
        # 都意味着可能已经加了真实拦截 —— 那时文档就该改。
        allowed = {"config.py", "routers/v1/llm.py", "routers/v1/settings.py"}
        unexpected = readers - allowed
        assert not unexpected, (
            f"llm_daily_budget_usd 出现在新的文件里：{sorted(unexpected)}。\n"
            "如果这是真实的预算拦截，请更新 §4.4 与 §12.3 —— 文档目前明确写着它不生效。"
        )

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
