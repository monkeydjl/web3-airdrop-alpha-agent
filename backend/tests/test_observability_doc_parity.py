"""`docs/OBSERVABILITY.md` 与代码实际观测面的一致性回归。

## 为什么需要这个测试

重写前的 `docs/OBSERVABILITY.md` 列了 39 个指标名，其中 **35 个在代码里
根本不存在**；列了 15 个日志事件名，**一个都不存在**。

这类错误比"写错一个字"危险得多：Prometheus 查一个不存在的指标**不报错**，
返回空结果集。面板上呈现为一条空曲线 / 「No data」，读起来像"系统很安静"，
而不是"你查的东西不存在"。照这份文档写的告警规则同理 —— 永远不会触发，
于是给人一种"被监控着"的错觉。文档里的假指标名不会让任何 CI 变红，
所以只能靠这种跨语言（Markdown ↔ Python 注册表）断言把它钉住。

## 测什么

1. 文档正文里出现的每个 `airdrop_*` / `opportunity_economic_*` 指标名，
   都必须在 `app.metrics` 的 Prometheus 注册表里真实存在（按暴露名，
   Counter 带 `_total` 后缀）。
2. 反向：注册表里的每个指标都必须在文档里出现过 —— 少写一个指标，
   读者不会去搜索一个他不知道存在的东西。这个方向和正向一样重要。
3. §3.3 是**幽灵指标清单**（刻意列出不存在的名字，帮照旧文档写过查询的人
   对上号）。这一段必须整段排除在正向断言之外，且其中每个名字都必须
   **确实不存在** —— 否则清单本身就成了新的谎言。
4. 文档里以反引号引用的日志事件名，必须真实出现在 `backend/app/` 的
   logger 调用里。
5. 文档引用的 span 名必须真实出现在 `start_as_current_span` 调用里。
6. 已就位的 Prometheus 告警规则与 Grafana 面板引用的指标必须全部真实存在。

## 解析器必须大声失败

每个解析函数在什么都没找到时**显式断言失败**，绝不返回空集合。
一个静默返回空集合的解析器会让所有断言意外通过 —— 那是最坏的结果：
一个永远为真的测试，比没有测试更有害，因为它给人已被覆盖的错觉。
`TestParsersFailLoudly` 用真实文本反过来验证解析器本身能解析出东西。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from prometheus_client import Counter, Gauge, Histogram

import app.metrics as metrics_module

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "OBSERVABILITY.md"
APP_DIR = REPO_ROOT / "backend" / "app"
ALERT_RULES = REPO_ROOT / "configs" / "observability" / "prometheus" / "alert_rules.yml"
GRAFANA_DASHBOARD = (
    REPO_ROOT / "configs" / "observability" / "grafana" / "dashboards" / "airdrop-system-overview-v2.json"
)

_METRIC_RE = re.compile(r"`((?:airdrop|opportunity_economic)_[a-z0-9_]+)`")
# 事件名：形如 `a.b` / `a.b.c`，排除文件名（.md/.py/.json/.yml/.tsx）
_EVENT_RE = re.compile(r"`([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)`")
_NOT_EVENTS = (".md", ".py", ".json", ".yml", ".yaml", ".tsx", ".ts")
# 文档里还有别的点分标识符不是日志事件名：
# - `airdrop.*` 是 OTel span 名（由 TestDocumentedSpansExist 单独校验）
# - `logger.debug` 之类是 Python 方法引用
# - `nested.token` 是 JSON 字段路径示例
# 这些前缀必须显式排除，否则它们会被当成"不存在的事件名"误报。
_NON_EVENT_PREFIXES = ("airdrop.", "logger.", "nested.", "structlog.", "settings.", "app.metrics.")
_LOGGER_CALL_RE = re.compile(r'logger\.(?:debug|info|warning|warn|error|exception|critical)\(\s*"([a-z0-9_.]+)"')
_SPAN_RE = re.compile(r'start_as_current_span\(\s*(?:f)?"([^"]+)"')

GHOST_SECTION_START = "### 3.3"
GHOST_SECTION_END = "### 3.4"


def _doc_text() -> str:
    assert DOC.is_file(), f"找不到 {DOC} —— 本测试的被测对象就是这份文档。"
    text = DOC.read_text(encoding="utf-8")
    assert len(text) > 5000, f"{DOC.name} 只有 {len(text)} 字符，疑似被截断或清空，解析结果不可信。"
    return text


def _split_ghost_section(text: str) -> tuple[str, str]:
    """把文档拆成「正文（断言为真）」与「幽灵清单（断言为假）」两半。

    这个拆分是本测试正确性的关键：§3.3 刻意列出**不存在**的指标名，
    如果它被算进正文，正向断言会全部失败；如果拆分逻辑写错却没人发现
    （比如标题被改名导致 index 落在别处），断言就会检查错误的文本范围。
    因此两个锚点都显式断言存在。
    """
    assert GHOST_SECTION_START in text, (
        f"{DOC.name} 里找不到 `{GHOST_SECTION_START}` 小节 —— "
        "那一节是刻意列出的「代码中不存在的指标」清单，必须整段排除在正向断言之外。"
        "如果小节被改名或删除，请同步更新本测试，不要让它去检查错误的文本范围。"
    )
    assert GHOST_SECTION_END in text, f"{DOC.name} 里找不到 `{GHOST_SECTION_END}`，无法确定幽灵清单在哪里结束。"
    start = text.index(GHOST_SECTION_START)
    end = text.index(GHOST_SECTION_END)
    assert start < end, "§3.3 出现在 §3.4 之后，文档结构与本测试的假设不符。"
    return text[:start] + text[end:], text[start:end]


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


def _real_log_events() -> set[str]:
    events: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        events.update(_LOGGER_CALL_RE.findall(path.read_text(encoding="utf-8")))
    assert len(events) >= 200, f"只扫出 {len(events)} 个 logger 事件名，远少于预期（≥200）。解析器可能已失效。"
    return events


def _real_span_names() -> set[str]:
    spans: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        spans.update(_SPAN_RE.findall(path.read_text(encoding="utf-8")))
    assert spans, "没有扫到任何 start_as_current_span 的 span 名 —— 解析器已失效。"
    return spans


def _documented_metrics(body: str) -> set[str]:
    found = set(_METRIC_RE.findall(body))
    assert len(found) >= 25, (
        f"文档正文里只解析出 {len(found)} 个指标名，远少于预期（≥25）。"
        "解析器或文档格式（反引号包裹）已变化，断言不再可信。"
    )
    return found


def _documented_events(body: str) -> set[str]:
    found = {
        m for m in _EVENT_RE.findall(body) if not m.endswith(_NOT_EVENTS) and not m.startswith(_NON_EVENT_PREFIXES)
    }
    assert len(found) >= 8, f"文档里只解析出 {len(found)} 个事件名，远少于预期（≥8）。解析器可能已失效。"
    return found


def _documented_spans(body: str) -> set[str]:
    """从文档里解析 `airdrop.*` span 名（§4.2 的 span 表）。

    span 名与日志事件名在文档里都是反引号包裹的点分标识符，靠 `airdrop.` 前缀区分：
    仓内所有手动 span 都以 `airdrop.` 开头，而没有任何日志事件名用这个前缀。
    """
    found = {m for m in re.findall(r"`(airdrop\.[a-z0-9_.{}]+)`", body)}
    assert len(found) >= 3, (
        f"文档里只解析出 {len(found)} 个 span 名，远少于预期（≥3）。"
        "§4.2 的 span 表格式可能已变化 —— 解析不到就等于断言空转。"
    )
    return found


class TestDocumentedMetricsExist:
    """文档正文里的指标必须在代码注册表里真实存在。"""

    def test_every_documented_metric_is_registered(self):
        body, _ = _split_ghost_section(_doc_text())
        documented = _documented_metrics(body)
        exported = _exported_metric_names()
        missing = sorted(documented - exported)
        assert not missing, (
            f"文档写了这些指标，但 app.metrics 里没有：{missing}。\n"
            "Prometheus 查不存在的指标不报错、只返回空结果 —— 面板会显示 "
            "「No data」而不是报错，读起来像系统很安静。请改文档或补代码。"
        )

    def test_every_registered_metric_is_documented(self):
        """反向：注册表里的指标都必须写进文档。

        少写一个指标和写错一个指标一样有害 —— 读者不会去搜索一个
        他不知道存在的东西。
        """
        body, _ = _split_ghost_section(_doc_text())
        documented = _documented_metrics(body)
        exported = _exported_metric_names()
        undocumented = sorted(exported - documented)
        assert not undocumented, (
            f"代码里注册了这些指标，但 {DOC.name} 没写：{undocumented}。\n"
            "没写进文档的指标等于不存在 —— 没人会去查一个他不知道的指标名。"
        )


class TestGhostListIsActuallyGhosts:
    """§3.3 的「不存在指标」清单必须真的全部不存在。"""

    def test_ghost_list_contains_no_real_metric(self):
        _, ghost_block = _split_ghost_section(_doc_text())
        ghosts = set(_METRIC_RE.findall(ghost_block))
        # 门槛随 §3.3 逐步"移出为真"而下降：2026-08-29 从 33 → 29（agent 粒度、
        # 数据质量、HTTP 耗时三个指标已实现移出），档3-4 业务面板后还会再降到 26。
        # 底线是"解析器失效返回空集"那一类失败 —— 只要还能解析出几十个就不算失效。
        assert len(ghosts) >= 20, f"§3.3 只解析出 {len(ghosts)} 个名字，远少于预期（≥20）。解析器或该节格式已变化。"
        exported = _exported_metric_names()
        wrongly_listed = sorted(ghosts & exported)
        assert not wrongly_listed, (
            f"§3.3 声称这些指标不存在，但它们在代码里是真实的：{wrongly_listed}。\n"
            "把真指标列进「不存在」清单，会让人放弃使用一个可用的指标 —— "
            "这个清单本身就成了新的谎言。"
        )


class TestDocumentedEventsExist:
    """文档引用的日志事件名必须真实存在。"""

    def test_every_documented_event_is_emitted_somewhere(self):
        text = _doc_text()
        # §2.2 里刻意列出老文档的假事件名做对照，需排除那一段的枚举句
        documented = _documented_events(text)
        real = _real_log_events()
        # 老文档虚构的事件名（刻意保留在文档里做对照）
        known_fictional = {
            "run.start",
            "run.end",
            "run.error",
            "agent.run.start",
            "agent.run.end",
            "agent.run.error",
            "agent.llm.fallback",
            "api.request.start",
            "api.request.end",
            "fetcher.fetch.start",
            "fetcher.fetch.error",
            "fetcher.circuit.open",
            "db.write.error",
            "projects.fetched_at",
        }
        wrongly_real = sorted(known_fictional & real)
        assert not wrongly_real, (
            f"文档把这些事件名列为「老文档虚构、已不存在」，但代码里确实有：{wrongly_real}。请更新文档。"
        )
        missing = sorted(documented - real - known_fictional)
        assert not missing, (
            f"文档引用了这些日志事件名，但 backend/app 里没有任何 logger 调用发出它们：{missing}。\n"
            "按不存在的事件名写 Loki 查询会永远返回空。"
        )


class TestDocumentedSpansExist:
    """文档引用的 span 名必须真实存在。

    这里必须**从文档解析** span 名，不能把名字写死在测试里。
    第一版就写死了 `airdrop.pipeline.run` 等三个名字 —— 变异测试
    （把文档里的 `airdrop.project` 改成 `airdrop.single_project`）
    照样全绿，因为断言检查的是测试自己的常量，与文档无关。
    一个不读被测对象的断言，等于没有断言。
    """

    def test_documented_spans_are_real(self):
        documented = _documented_spans(_doc_text())
        real = _real_span_names()
        missing = sorted(documented - real)
        assert not missing, (
            f"文档写了这些 span 名，但代码里没有对应的 start_as_current_span 调用：{missing}。\n"
            "按不存在的 span 名在 Jaeger 里搜索会永远查不到。"
        )

    def test_every_real_span_is_documented(self):
        """反向：代码里的 span 都要写进文档。"""
        documented = _documented_spans(_doc_text())
        real = {s for s in _real_span_names() if s.startswith("airdrop.")}
        undocumented = sorted(real - documented)
        assert not undocumented, f"代码里有这些 span，但 {DOC.name} 没写：{undocumented}。"


class TestShippedObservabilityConfigsUseRealMetrics:
    """已交付的告警规则与面板不能引用幽灵指标。

    这两个文件比文档更危险：它们会被真实加载。一条引用幽灵指标的告警规则
    不会报错，只是永远不触发 —— 值班的人以为有人盯着。
    """

    def test_alert_rules_reference_only_real_metrics(self):
        assert ALERT_RULES.is_file(), f"找不到 {ALERT_RULES}"
        text = ALERT_RULES.read_text(encoding="utf-8")
        refs = set(re.findall(r"\b((?:airdrop|opportunity_economic)_[a-z0-9_]+)\b", text))
        assert refs, "告警规则里没解析出任何指标引用 —— 解析器或文件格式已变化。"
        ghosts = sorted(refs - _exported_metric_names())
        assert not ghosts, f"alert_rules.yml 引用了不存在的指标：{ghosts}。这些告警永远不会触发，却让人以为已被监控。"

    def test_grafana_dashboard_references_only_real_metrics(self):
        assert GRAFANA_DASHBOARD.is_file(), f"找不到 {GRAFANA_DASHBOARD}"
        raw = GRAFANA_DASHBOARD.read_text(encoding="utf-8")
        exprs = re.findall(r'"expr":\s*"((?:[^"\\]|\\.)*)"', raw)
        assert exprs, "面板 JSON 里没解析出任何 expr —— 解析器或面板 schema 已变化。"
        refs: set[str] = set()
        for expr in exprs:
            refs.update(re.findall(r"\b((?:airdrop|opportunity_economic)_[a-z0-9_]+)\b", expr))
        assert refs, "面板查询里没解析出任何指标名。"
        ghosts = sorted(refs - _exported_metric_names())
        assert not ghosts, f"Grafana 面板引用了不存在的指标：{ghosts}。这些面板会永远显示 No data。"

    def test_dashboard_json_is_valid(self):
        """面板 JSON 必须能解析 —— 一份坏掉的 JSON 会让 provisioning 静默跳过。"""
        data = json.loads(GRAFANA_DASHBOARD.read_text(encoding="utf-8"))
        assert data.get("spec", {}).get("title"), "面板 JSON 缺少 spec.title，provisioning 可能拒绝加载。"


class TestParsersFailLoudly:
    """解析器自检：一个静默返回空集合的解析器让所有断言变成空转。"""

    def test_metric_parser_finds_names_in_real_text(self):
        body, _ = _split_ghost_section(_doc_text())
        assert _METRIC_RE.findall(body), "指标解析器在真实文档上什么都没找到 —— 它已失效。"

    def test_metric_parser_ignores_unbackticked_names(self):
        assert _METRIC_RE.findall("airdrop_pipeline_runs_total 没有反引号") == []
        assert _METRIC_RE.findall("`airdrop_pipeline_runs_total`") == ["airdrop_pipeline_runs_total"]

    def test_event_parser_excludes_filenames(self):
        found = {
            m
            for m in _EVENT_RE.findall("`app.startup` `metrics.py` `flags.prod.json`")
            if not m.endswith(_NOT_EVENTS) and not m.startswith(_NON_EVENT_PREFIXES)
        }
        assert found == {"app.startup"}, f"事件解析器把文件名当成了事件名：{found}"

    def test_event_parser_excludes_span_and_method_references(self):
        """span 名与 Python 方法引用不是日志事件名，误判会造成假红。"""
        sample = "`airdrop.pipeline.run` `logger.debug` `nested.token` `app.startup` `pipeline.completed`"
        found = {
            m
            for m in _EVENT_RE.findall(sample)
            if not m.endswith(_NOT_EVENTS) and not m.startswith(_NON_EVENT_PREFIXES)
        }
        assert found == {"app.startup", "pipeline.completed"}, f"解析器把非事件标识符当成了事件名：{found}"

    def test_ghost_split_raises_when_anchor_missing(self):
        with pytest.raises(AssertionError, match="找不到"):
            _split_ghost_section("# 一份没有 3.3 小节的文档\n\n正文。\n" * 400)

    def test_doc_length_guard_rejects_truncated_file(self, tmp_path, monkeypatch):
        """文档被清空/截断时必须报错，而不是"没解析到东西所以全部通过"。"""
        tiny = tmp_path / "OBSERVABILITY.md"
        tiny.write_text("# 空文档\n", encoding="utf-8")
        monkeypatch.setattr(f"{__name__}.DOC", tiny)
        with pytest.raises(AssertionError, match="疑似被截断"):
            _doc_text()

    def test_span_parser_finds_real_spans(self):
        assert _real_span_names(), "span 解析器在真实源码上什么都没找到。"

    def test_span_doc_parser_reads_the_document(self):
        """文档 span 解析器必须真的从文档取值，且解析不到时大声失败。"""
        assert _documented_spans(_doc_text()), "文档 span 解析器在真实文档上什么都没找到。"
        with pytest.raises(AssertionError, match="只解析出"):
            _documented_spans("一段没有任何 span 名的文本。")
