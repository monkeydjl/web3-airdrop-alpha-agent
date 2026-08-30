"""`docs/DATA_SOURCE_STRATEGY.md` 与代码实际采集面的一致性回归。

## 为什么需要这个测试

这份文档是全仓**最后一个**编码损坏登记文件（498 处中文字被截断成非法
UTF-8 字节）。跟 `OPERATIONS.md` / `OBSERVABILITY.md` / `API_SPEC.md`
一模一样的剧本：**登记豁免之后就没人读它了，于是它在内容上烂得更彻底。**

重写前实测到的失真：

- 10 个采集器全部已实现，但文档逐个标着「（计划实现位置）」，
  **10 个文件路径 10 个都不存在**（真实文件没有 `_collector` 后缀）；
- 给了一条 `discovery_score` 的**统一公式**，代码里没有任何地方实现它
  —— 真实是 10 个采集器各算各的；
- `POST /re-score/{id}` 是**幽灵接口**，而它的前缀在鉴权表里，
  所以调用会先返回 403 —— **403 比 404 更能骗人**；
- 说 GitHub / CoinGecko「跟随 DefiLlama 事件触发」，真实是各有独立 cron；
- 说 `raw_projects` 新增就「立即触发分析」，真实两条链完全解耦；
- 速率限制器路径写错（`utils/` vs 真实的 `collectors/`）；
- 4 个 P2 源（Discord/Medium/Mirror/Reddit）写成「自动采集」，**零代码**。

**这份文档的错误方式很特殊**：它把「已完成」持续标为「待办」。
危害不是让人少做事，而是**让人重做已经在跑的东西**，
并且在发现清单不准之后，连真正的待办也一起不信了。

## 测什么

1. §3 的 10 个采集器文件与类名，必须与 registry 里的真实对象一致。
2. §5.2 的来源优先级表，必须与 `app.utils.normalize.SOURCE_PRIORITY` 一致。
3. §6.1 的 cron 表逐条对齐 `settings`。
4. §8.4 的速率限制表逐条对齐 `TokenBucketRateLimiter.DEFAULTS`。
5. §9.1 的 5 个告警阈值对齐 `CollectionMetrics.check_alerts()` 源码。
6. §7 的采集表清单必须都是真实存在的表。
7. 正文里**被当成可用**的每个 `/api/v1` 路径必须真实存在（逐行豁免）。
8. 反方向：§12 明确点名不存在的东西（幽灵接口、幽灵文件路径、
   P2 源的 collector、`evaluation/collection/`），必须**确实都不存在** ——
   否则纠错清单自己就成了新的谎言。

## 两条从前几轮门禁里学到的原则

**钉规则不钉本机读数。** §4.3 那类「哪些源现在就绪」的判断依赖 `.env`，
CI 上必然不同 —— 一个因环境原因变红的门禁会训练人忽略它。
所以这里比对的是文件名/类名/cron/阈值这类**在任何机器上都一样**的事实。

**豁免逐行、且要求那一行自己说出「不存在」。** 不做整节或整文件豁免：
只要某个名字被登进 §12，正文任何地方把它当命令写出来都会被放过 ——
那正是这套门禁要防的事。

解析器自身也必须大声失败：什么都没解析到时**显式断言失败**，
绝不返回空集合。一个永远为真的测试比没有测试更有害。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.collectors.factory import build_default_registry
from app.collectors.metrics import CollectionMetrics
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings
from app.main import create_app
from app.utils.normalize import SOURCE_PRIORITY

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "DATA_SOURCE_STRATEGY.md"

_BLOCKS = {
    "files": ("<!-- collector-files:begin -->", "<!-- collector-files:end -->"),
    "priority": ("<!-- source-priority:begin -->", "<!-- source-priority:end -->"),
    "formula": ("<!-- discovery-formula:begin -->", "<!-- discovery-formula:end -->"),
    "yield": ("<!-- measured-yield:begin -->", "<!-- measured-yield:end -->"),
    "cron": ("<!-- collection-cron:begin -->", "<!-- collection-cron:end -->"),
    "tables": ("<!-- collection-tables:begin -->", "<!-- collection-tables:end -->"),
    "limits": ("<!-- rate-limits:begin -->", "<!-- rate-limits:end -->"),
    "alerts": ("<!-- alert-thresholds:begin -->", "<!-- alert-thresholds:end -->"),
    "retention": ("<!-- retention:begin -->", "<!-- retention:end -->"),
}

# §12 整节是「失真记录」：里面刻意写着不存在的路径、类名、接口。
# 正向断言必须整节排除，否则会把反例当正例来查。
_DISTORTION_ANCHOR = "## 12. 上一版本（v2.0）的失真记录"

# 「这个东西不存在」的行内标记；带标记的行是文档在纠错，逐行豁免。
_ABSENCE_MARKERS = ("不存在", "没有", "❌", "从未", "不读", "无任何代码", "是假的", "幽灵", "全错")

_PATH_RE = re.compile(r"`(?:GET|POST|PATCH|PUT|DELETE)?\s*(/api/v1[A-Za-z0-9_/{}.\-]*)`")


def _doc_text() -> str:
    assert DOC.is_file(), f"找不到 {DOC} —— 本测试的被测对象就是这份文档。"
    text = DOC.read_text(encoding="utf-8")
    assert len(text) > 15000, f"{DOC.name} 只有 {len(text)} 字符，疑似被截断或清空，解析结果不可信。"
    return text


def _block(text: str, key: str) -> str:
    """取出一个标记块。两个锚点都显式断言存在。

    锚点丢了意味着文档结构被改过，此时**必须让测试红** ——
    安静地返回空串会让下面的清单断言全部空转。
    """
    begin, end = _BLOCKS[key]
    assert begin in text, f"{DOC.name} 里找不到标记 `{begin}` —— 文档结构已变，请同步本测试。"
    assert end in text, f"{DOC.name} 里找不到标记 `{end}`，无法确定 `{begin}` 块在哪结束。"
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    assert start < stop, f"标记 `{end}` 出现在 `{begin}` 之前，文档结构与本测试的假设不符。"
    body = text[start:stop]
    assert body.strip(), f"标记块 `{begin}` 是空的 —— 空清单会让对应断言变成空转。"
    return body


def _body_without_distortion_section(text: str) -> str:
    assert _DISTORTION_ANCHOR in text, (
        f"{DOC.name} 里找不到 `{_DISTORTION_ANCHOR}` —— 那一节刻意列出不存在的东西，必须整节排除在正向断言之外。"
    )
    return text[: text.index(_DISTORTION_ANCHOR)]


def _lines_asserting_existence(body: str) -> list[str]:
    """只保留「声称某东西存在」的行；带否定标记的行按逐行豁免剔除。"""
    kept = [line for line in body.splitlines() if not any(m in line for m in _ABSENCE_MARKERS)]
    assert len(kept) > 150, (
        f"逐行过滤后只剩 {len(kept)} 行，远少于预期（>150）—— 过滤条件写反了会让断言几乎不检查任何东西。"
    )
    return kept


# ── 代码侧真相 ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def doc() -> str:
    return _doc_text()


def _real_collectors() -> dict[str, tuple[str, str]]:
    """`source_id -> (相对仓库根的文件路径, 类名)`，取自真实 registry。"""
    result: dict[str, tuple[str, str]] = {}
    for collector in build_default_registry().list_all():
        cls = type(collector)
        src = inspect.getsourcefile(cls)
        assert src, f"拿不到 {cls.__name__} 的源文件路径 —— 解析器已失效。"
        rel = Path(src).resolve().relative_to(REPO_ROOT).as_posix()
        result[collector.source_id] = (rel, cls.__name__)
    assert len(result) >= 10, f"只从 registry 解析出 {len(result)} 个采集器，远少于预期（≥10）。"
    return result


def _real_cron() -> dict[str, str]:
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


def _real_alert_thresholds() -> dict[str, float]:
    """告警阈值真相：解析 `check_alerts()` 源码里的字面量字典。

    刻意读源码而不是调用它 —— 调用需要一个真实数据库，
    而阈值本身是硬编码的常量，读源码就足够且在任何环境下一致。
    """
    source = inspect.getsource(CollectionMetrics.check_alerts)
    found = dict(re.findall(r'"(\w+)":\s*([0-9.]+)', source))
    assert len(found) >= 5, f"只从 check_alerts() 解析出 {len(found)} 个阈值，远少于预期（≥5）。解析器已失效。"
    return {k: float(v) for k, v in found.items()}


def _openapi_paths() -> set[str]:
    with TestClient(create_app()) as client:
        spec = client.get("/openapi.json").json()
    paths = {p for p in spec["paths"] if p.startswith("/api/v1")}
    assert len(paths) >= 40, f"只从 OpenAPI 解析出 {len(paths)} 个 /api/v1 路径，远少于预期（≥40）。"
    return paths


# ── §3 采集器文件与类名 ────────────────────────────────────────


class TestCollectorFiles:
    """上一版这张表 10 行全错（都写成 `{source}_collector.py`）。"""

    def test_documented_files_match_registry(self, doc):
        rows = re.findall(
            r"^\|\s*`([a-z0-9_]+)`\s*\|\s*`([^`]+)`\s*\|\s*`(\w+)`\s*\|",
            _block(doc, "files"),
            re.MULTILINE,
        )
        assert len(rows) >= 10, f"§3 采集器表只解析出 {len(rows)} 行，远少于预期（≥10）。"
        documented = {sid: (path, cls) for sid, path, cls in rows}
        real = _real_collectors()
        assert documented == real, (
            "§3 的采集器文件/类名与真实 registry 不一致。\n"
            f"文档独有：{sorted(set(documented.items()) - set(real.items()))}\n"
            f"代码独有：{sorted(set(real.items()) - set(documented.items()))}"
        )

    def test_documented_collector_files_all_exist(self, doc):
        rows = re.findall(r"^\|\s*`[a-z0-9_]+`\s*\|\s*`([^`]+)`\s*\|", _block(doc, "files"), re.MULTILINE)
        assert len(rows) >= 10, f"只解析出 {len(rows)} 个文件路径。"
        missing = [p for p in rows if not (REPO_ROOT / p).is_file()]
        assert not missing, f"§3 列的这些采集器文件不存在：{missing}"


# ── §5.2 来源优先级 ───────────────────────────────────────────


class TestSourcePriority:
    def test_documented_priority_matches_code(self, doc):
        rows = re.findall(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|", _block(doc, "priority"), re.MULTILINE)
        assert len(rows) >= 10, f"§5.2 优先级表只解析出 {len(rows)} 行，远少于预期（≥10）。"
        documented: dict[str, int] = {}
        for rank, sources in rows:
            for name in re.findall(r"`([a-z0-9_]+)`", sources):
                documented[name] = int(rank)
        assert len(documented) >= 12, f"只从优先级表解析出 {len(documented)} 个来源名，远少于预期（≥12）。"
        assert documented == SOURCE_PRIORITY, (
            "§5.2 的来源优先级与 app.utils.normalize.SOURCE_PRIORITY 不一致。\n"
            f"文档独有：{sorted(set(documented.items()) - set(SOURCE_PRIORITY.items()))}\n"
            f"代码独有：{sorted(set(SOURCE_PRIORITY.items()) - set(documented.items()))}"
        )

    def test_manual_outranks_every_collector(self, doc):
        """手动录入必须压过所有采集源 —— 这是文档里那句承诺的代码依据。

        上一版漏掉了 `manual` 和 `api` 这两个最高优先级。
        """
        collector_ranks = [SOURCE_PRIORITY[sid] for sid in _real_collectors() if sid in SOURCE_PRIORITY]
        assert collector_ranks, "一个采集源都没出现在 SOURCE_PRIORITY 里 —— 解析器已失效。"
        assert SOURCE_PRIORITY["manual"] < min(collector_ranks), (
            f"manual 的优先级 {SOURCE_PRIORITY['manual']} 没有压过所有采集源（最高 {min(collector_ranks)}），"
            "文档里「UI 改的字段不会被采集覆盖」这句就不成立了。"
        )


# ── §6.1 cron ─────────────────────────────────────────────────


class TestCron:
    def test_documented_cron_matches_settings(self, doc):
        rows = dict(re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|\s*`([^`]+)`\s*\|", _block(doc, "cron"), re.MULTILINE))
        assert len(rows) >= 10, f"§6.1 cron 表只解析出 {len(rows)} 行，远少于预期（≥10）。"
        real = _real_cron()
        assert rows == real, (
            "§6.1 的 cron 与 settings 实际值不一致。\n"
            f"文档独有：{sorted(set(rows.items()) - set(real.items()))}\n"
            f"代码独有：{sorted(set(real.items()) - set(rows.items()))}"
        )


# ── §8.4 速率限制 ─────────────────────────────────────────────


class TestRateLimits:
    def test_documented_limits_match_defaults(self, doc):
        rows = re.findall(
            r"^\|\s*`([a-z0-9_]+)`\s*\|\s*([0-9.]+)\s*\|\s*(\d+)\s*\|\s*(?:\*\*)?([0-9]+|无)(?:\*\*)?\s*\|",
            _block(doc, "limits"),
            re.MULTILINE,
        )
        assert len(rows) >= 10, f"§8.4 限流表只解析出 {len(rows)} 行，远少于预期（≥10）。"
        documented = {
            sid: (float(rps), int(burst), None if daily == "无" else int(daily)) for sid, rps, burst, daily in rows
        }
        real = {
            sid: (cfg.requests_per_second, cfg.burst, cfg.daily_limit)
            for sid, cfg in TokenBucketRateLimiter.DEFAULTS.items()
        }
        assert documented == real, (
            "§8.4 的限流表与 TokenBucketRateLimiter.DEFAULTS 不一致。\n"
            f"文档独有：{sorted(set(documented.items()) - set(real.items()))}\n"
            f"代码独有：{sorted(set(real.items()) - set(documented.items()))}"
        )

    def test_only_coingecko_has_a_daily_limit(self, doc):
        """文档明确说「`coingecko` 是唯一设了日限额的源」，这句要能被推翻。

        一个所有值都相同的断言会退化，所以这里同时要求"有日限额的恰好一个"。
        """
        with_daily = {sid for sid, cfg in TokenBucketRateLimiter.DEFAULTS.items() if cfg.daily_limit is not None}
        assert with_daily == {"coingecko"}, f"设了日限额的源变成了 {sorted(with_daily)}，§8.4 那句话需要同步改。"


# ── §9.1 告警阈值 ─────────────────────────────────────────────


class TestAlertThresholds:
    def test_documented_thresholds_match_code(self, doc):
        rows = re.findall(r"^\|\s*`(\w+)`\s*\|\s*([0-9.]+)\s*\|", _block(doc, "alerts"), re.MULTILINE)
        assert len(rows) >= 5, f"§9.1 阈值表只解析出 {len(rows)} 行，远少于预期（≥5）。"
        documented = {k: float(v) for k, v in rows}
        real = _real_alert_thresholds()
        assert documented == real, (
            "§9.1 的告警阈值与 check_alerts() 不一致。\n"
            f"文档独有：{sorted(set(documented.items()) - set(real.items()))}\n"
            f"代码独有：{sorted(set(real.items()) - set(documented.items()))}"
        )


# ── §7 采集表 ─────────────────────────────────────────────────


class TestCollectionTables:
    def test_documented_tables_have_real_ddl(self, doc):
        """§7 列的每张表都必须在 `DATABASE_DDL.md` 里有 DDL。

        不查活库（行数会变、CI 上根本没有这些数据），只查
        「文档说它在 DDL 的哪一节」这件事是不是真的 ——
        这在任何机器上都一样。
        """
        rows = re.findall(r"^\|\s*`(\w+)`\s*\|", _block(doc, "tables"), re.MULTILINE)
        assert len(rows) >= 6, f"§7 采集表清单只解析出 {len(rows)} 行，远少于预期（≥6）。"
        ddl = (REPO_ROOT / "docs" / "DATABASE_DDL.md").read_text(encoding="utf-8")
        missing = [t for t in rows if f"CREATE TABLE IF NOT EXISTS {t} " not in ddl]
        assert not missing, f"§7 列的这些表在 DATABASE_DDL.md 里找不到 DDL：{missing}"


# ── 正向：被当成可用的接口必须存在 ─────────────────────────────


class TestAssertedApiPathsExist:
    def test_paths_presented_as_usable_exist(self, doc):
        body = "\n".join(_lines_asserting_existence(_body_without_distortion_section(doc)))
        documented = {p for p in _PATH_RE.findall(body) if "*" not in p}
        assert len(documented) >= 5, f"正文里只解析出 {len(documented)} 个 /api/v1 路径，远少于预期（≥5）。"
        real = _openapi_paths()
        bogus = sorted(p for p in documented if p not in real and not any(r.startswith(p) for r in real))
        assert not bogus, (
            f"文档把这些路径当成可用，但 OpenAPI 里没有：{bogus}。如果是要指出它不存在，请在同一行里写出「不存在」。"
        )


# ── 反向：§12 点名不存在的东西，必须确实不存在 ─────────────────


class TestDistortionListIsHonest:
    """纠错清单自己也可能变成新的谎言 —— 反过来钉住它。"""

    def test_ghost_endpoint_really_absent(self):
        real = _openapi_paths()
        assert not [p for p in real if "re-score" in p], (
            f"`/re-score` 现在真实存在了（{[p for p in real if 're-score' in p]}），§6.2 与 §12.3 需要改写。"
        )

    def test_ghost_collector_paths_really_absent(self):
        """上一版写的 10 个 `*_collector.py` 与 `utils/rate_limiter.py`。"""
        stale = [
            "backend/app/collectors/defillama_collector.py",
            "backend/app/collectors/github_collector.py",
            "backend/app/collectors/coingecko_collector.py",
            "backend/app/collectors/twitter_collector.py",
            "backend/app/collectors/chain_collector.py",
            "backend/app/collectors/quest_collector.py",
            "backend/app/collectors/cryptorank_collector.py",
            "backend/app/utils/rate_limiter.py",
        ]
        existing = [p for p in stale if (REPO_ROOT / p).exists()]
        assert not existing, f"§12.1/§12.5 说这些路径不存在，但它们现在存在了：{existing}"

    def test_p2_sources_have_collectors(self):
        """Discord / Medium / Mirror / Reddit 在 §2 里应是 ✅ 且已注册。"""
        registered = set(_real_collectors())
        p2 = {"discord", "medium", "mirror", "reddit"}
        missing = sorted(p2 - registered)
        assert not missing, f"§12.9 已改写为「P2 源已实现」，但这些源没注册进 registry：{missing}"

    def test_collection_eval_dir_still_absent(self):
        assert not (REPO_ROOT / "evaluation" / "collection").exists(), (
            "`evaluation/collection/` 现在存在了 —— §9.1 与 §11 那两行要改成 ✅。"
        )
        assert (REPO_ROOT / "evaluation" / "llm").exists(), (
            "`evaluation/llm/` 不见了 —— 文档里「只有 evaluation/llm」这句需要同步。"
        )

    def test_unified_discovery_formula_really_absent(self):
        """§5.4 与 §12.2 断言「统一公式不存在」，这条必须可被推翻。

        判据是全仓采集器里搜不到 `twitter_score` / 跨源汇总。
        """
        collectors_dir = REPO_ROOT / "backend" / "app" / "collectors"
        hits = [p.name for p in collectors_dir.glob("*.py") if "twitter_score" in p.read_text(encoding="utf-8")]
        assert not hits, f"`twitter_score` 出现在 {hits} —— §5.4/§12.2 说的「没有统一公式」需要重新核对。"

    def test_collection_does_not_auto_trigger_analysis(self):
        """§6.2 与 §12.4 断言两条链解耦 —— 钉住那个开关的默认值。"""
        default = type(settings).model_fields["collection_auto_run_enabled"].default
        assert default is False, (
            "COLLECTION_AUTO_RUN_ENABLED 的默认值变成 True 了，§5.1/§6.2/§12.4 的「两条链解耦」需要改写。"
        )


# ── 解析器自检 ────────────────────────────────────────────────


class TestParsersFailLoudly:
    """一个静默返回空集合的解析器会让所有断言意外通过。"""

    def test_block_reader_rejects_missing_anchor(self, doc):
        with pytest.raises(AssertionError, match="找不到标记"):
            _block("no anchors here", "cron")

    def test_block_reader_rejects_empty_body(self):
        begin, end = _BLOCKS["cron"]
        with pytest.raises(AssertionError, match="是空的"):
            _block(f"{begin}\n\n{end}", "cron")

    def test_absence_filter_rejects_an_inverted_condition(self):
        with pytest.raises(AssertionError, match="远少于预期"):
            _lines_asserting_existence("这一行不存在\n那一行也没有\n")

    def test_absence_filter_keeps_positive_lines_and_drops_marked_ones(self):
        body = "\n".join(["真实存在的一行 A"] * 200 + ["`GET /api/v1/ghost` 不存在"])
        kept = _lines_asserting_existence(body)
        assert not any("ghost" in line for line in kept), "带「不存在」标记的行应被逐行豁免掉"
        assert any("真实存在" in line for line in kept), "正常行不该被过滤"

    def test_distortion_section_is_excluded(self, doc):
        head = _body_without_distortion_section(doc)
        assert _DISTORTION_ANCHOR not in head, "§12 应被整节排除在正向断言之外"
        assert len(head) > 8000, f"排除 §12 后正文只剩 {len(head)} 字符，疑似锚点位置不对。"

    def test_real_collector_parser_finds_ten(self):
        real = _real_collectors()
        assert len(real) >= 10, f"registry 只给出 {len(real)} 个采集器"
        assert all(path.startswith("backend/app/collectors/") for path, _cls in real.values()), (
            f"解析出的文件路径不在 collectors 目录下：{sorted(real.values())}"
        )

    def test_alert_threshold_parser_finds_the_five_names(self):
        real = _real_alert_thresholds()
        expected = {"success_rate", "avg_latency_ms", "freshness_minutes", "coverage_rate", "duplicate_rate"}
        assert expected <= set(real), f"check_alerts() 解析结果缺少：{sorted(expected - set(real))}"
